"""Daily flow report: hourly NetFlow rollup, AS annotation, 24 h analytics.

Why this module exists
----------------------
The NOC surface used to render a Sankey diagram straight out of the goflow2
collector's tail. That tail is a *rolling window*, not a history: measured on
production 2026-11-24, ``/var/log/goflow2/flows.json`` held 142,709 records
spanning 49.3 s (2,894 flows/s, ~2.9 MB/s of JSON) before logrotate truncated
it. A live diagram is a fine consumer of a 50-second window. A *report* is
not, because there is nothing behind it - which is exactly why the Sankey kept
"losing its lines": every refresh drew a different random sample of a few
seconds, so the top-12 link set barely overlapped between two draws.

This module answers a different question: over a full day, what came in, what
went out, to whom, and where in the world is that. That needs history, so the
collector tail is folded into hourly buckets that outlive the file::

    goflow2 tail --12 s tick--> _Hour accumulators --60 s flush--> flow_rollup
                                                                       |
    flow_samples (top-50 links/min, 6 h retention) --backfill----------+
                                                                       v
                                          GET /admin/noc/netflow/daily-report

ASN / origin prefix / country annotation comes from bgp.tools through its
bulk whois interface (see ``bgptools``), cached for 30 days so a busy hour
costs a handful of lookups instead of hundreds.

Honesty rules (each one is here because getting it wrong is silent)
-------------------------------------------------------------------
* **The bucket clock is SERVER time.** The router's export stamps have been
  observed 7.7 h off (WIB vs UTC) and frozen for 120 s while the datagram
  counter kept advancing, so they are never used to place a record in time.
  They are used for exactly one thing: detecting a truncated/replaced file.
* **A partial hour says so.** ``flow_rollup_meta.first_at`` records when the
  rollup first saw each hour; anything that did not start near :00 is flagged
  partial instead of being drawn as a real dip in traffic.
* **Backfilled buckets are labelled.** ``flow_samples`` only holds the top-50
  links per minute, so a bucket rebuilt from it is a lower bound and carries
  ``source: "backfill"``.
* **Caps are reported.** Peer /24s, peer IPs and ports are capped per hour to
  keep the collection bounded; anything dropped is summed into an ``_other``
  row and counted in ``coverage.evicted_peers`` rather than vanishing.
* **Unresolved ASNs are visible.** A peer that bgp.tools could not resolve is
  shown as "unknown", never silently dropped or guessed.
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional

from . import bgptools

log = logging.getLogger("portal.netflow")

# --------------------------------------------------------------------------
# constants
# --------------------------------------------------------------------------

ROLLUP_COLL = "flow_rollup"
META_COLL = "flow_rollup_meta"
CURSOR_COLL = "flow_rollup_cursor"
CURSOR_ID = "netflow_rollup_cursor"
CONFIG_ID = "netflow"
SAMPLES_COLL = "flow_samples"

DEFAULT_FLOW_PATH = "/var/log/goflow2/flows.json"
TICK_MAX_BYTES = 96 << 20      # per tick; the rest is picked up next tick
ROLLUP_RETENTION_DAYS = 7
ROLLUP_HOUR_KEEP = 3           # hours kept in memory (current + 2 for safety)

# Write caps per hour per prefix per direction. A /24 that carries real traffic
# stays; the long tail is summed into `__other` so totals stay exact.
NET_TOP = 400
IP_TOP = 400
PORT_TOP = 60
PROTO_TOP = 24
# In-memory caps. When exceeded the map is halved by bytes; heavy hitters keep
# growing and therefore survive, which is the whole point of the report.
NET_CAP = 20_000
IP_CAP = 30_000
PORT_CAP = 3_000
OTHER = "__other__"

FLUSH_INTERVAL_S = 55.0
# Peers annotated per flush, and per report render.
#
# bgp.tools' bulk whois answers a whole batch in ONE connection: measured on
# production, 250 items in, 250 rows out, in a single round trip. Throttling to
# 60 per flush therefore wasted most of that capacity and left ~17% of traffic
# in the report classified as "unknown" - peers that the report had simply never
# asked about. 240 keeps the batch under the parser's 250-item ceiling while
# still costing one session per flush (the module self-limits to 2/s).
ENRICH_PER_FLUSH = 240

_REPORT_CACHE: dict = {}
REPORT_CACHE_S = 20.0

# --------------------------------------------------------------------------
# IP helpers (integer math: this runs ~3,000 times per second)
# --------------------------------------------------------------------------


def _ipv4_int(s: str) -> Optional[int]:
    if not s or ":" in s:
        return None
    parts = s.split(".")
    if len(parts) != 4:
        return None
    n = 0
    for p in parts:
        if not p.isdigit():
            return None
        v = int(p)
        if v > 255:
            return None
        n = (n << 8) | v
    return n


def _v4_str(n: int) -> str:
    return f"{(n >> 24) & 255}.{(n >> 16) & 255}.{(n >> 8) & 255}.{n & 255}"


def prefix24_of(ip: str) -> Optional[str]:
    """Grouping key for a peer address: /24 for IPv4, /48 for IPv6.

    A whole /24 is nearly always one origin ASN, which is what makes it the
    right join key for bgp.tools - one lookup annotates every address in it.

    Accepts a bare address *or* an existing prefix. Callers pass both shapes
    (the collector records bare addresses, the rollup stores /24 keys), and
    normalising inside this one function keeps every caller's cache key
    identical instead of letting ``a.b.c.0/24`` and ``a.b.c.7`` become two
    different keys for the same network.
    """
    if not ip:
        return None
    if "/" in ip:
        try:
            net = ipaddress.ip_network(ip, strict=False)
        except ValueError:
            return None
        if net.version == 4:
            return str(ipaddress.ip_network(f"{net.network_address}/24", strict=False))
        return str(ipaddress.ip_network(f"{net.network_address}/48", strict=False))
    i = _ipv4_int(ip)
    if i is not None:
        return _v4_str(i & 0xFFFFFF00) + "/24"
    try:
        net = ipaddress.ip_network(f"{ip}/48", strict=False)
        return str(net)
    except ValueError:
        return None


class _Net:
    __slots__ = ("prefix", "base", "mask", "bits", "cidr", "version", "label")

    def __init__(self, cidr: str, label: str = ""):
        net = ipaddress.ip_network(cidr, strict=False)
        self.cidr = str(net)
        self.prefix = self.cidr
        self.version = net.version
        self.bits = net.prefixlen
        self.label = label or self.cidr
        if net.version == 4:
            self.base = int(net.network_address)
            self.mask = (0xFFFFFFFF << (32 - net.prefixlen)) & 0xFFFFFFFF
        else:
            self.base = int(net.network_address)
            self.mask = (1 << 128) - 1 << (128 - net.prefixlen)

    def contains_int(self, value: int) -> bool:
        return (value & self.mask) == self.base


def _compile_nets(cidrs: Iterable[str]) -> list:
    out = []
    for c in cidrs:
        try:
            out.append(_Net(c))
        except ValueError:
            log.warning("[netflow] ignoring invalid local prefix %r", c)
    # Most specific first: with both a /16 and a /24 configured, a flow must be
    # attributed to the /24 so the report's per-prefix numbers do not overlap.
    out.sort(key=lambda n: n.bits, reverse=True)
    return out


def _match_net(nets: list, ip: str):
    """Return ``(net, int_value)`` for the most specific matching local net."""
    i = _ipv4_int(ip)
    if i is not None:
        for n in nets:
            if n.version == 4 and n.contains_int(i):
                return n, i
        return None, None
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return None, None
    for n in nets:
        if n.version == addr.version and n.contains_int(int(addr)):
            return n, int(addr)
    return None, None


# --------------------------------------------------------------------------
# in-memory hour accumulator
# --------------------------------------------------------------------------


def _bump(d: dict, key: str, byts: float, pkts: float) -> None:
    cur = d.get(key)
    if cur is None:
        d[key] = [byts, pkts]
    else:
        cur[0] += byts
        cur[1] += pkts


def _trim(d: dict, cap: int) -> float:
    """Halve ``d`` by bytes, folding the tail into ``__other__``.

    Returns the number of dropped keys so the caller can report the cap
    instead of pretending the long tail never existed.
    """
    if len(d) <= cap:
        return 0
    items = sorted(d.items(), key=lambda kv: kv[1][0], reverse=True)
    keep = items[: cap // 2]
    dropped = items[cap // 2:]
    db_ = sum(v[0] for _, v in dropped)
    dp = sum(v[1] for _, v in dropped)
    d.clear()
    for k, v in keep:
        d[k] = v
    prev = d.get(OTHER)
    if prev:
        prev[0] += db_
        prev[1] += dp
    else:
        d[OTHER] = [db_, dp]
    return len(dropped)


class _Hour:
    """One wall-clock hour of aggregated flows for one local prefix."""

    __slots__ = ("h", "bucket", "nets", "ips", "ports", "protos",
                 "bytes", "packets", "flows", "internal_bytes",
                 "dir_bytes", "dir_packets", "noport",
                 "first_at", "last_at", "ticks", "evicted", "loaded")

    def __init__(self, h: datetime):
        self.h = h
        self.bucket = h.strftime("%Y-%m-%dT%H")
        self.nets: dict = {}     # pfx -> {"in": {peer24: [bytes, packets]}, "out": {...}}
        self.ips: dict = {}      # pfx -> {"in": {ip: [...]}, "out": {...}}
        self.ports: dict = {}    # pfx -> {"in": {port: [...]}, "out": {...}}
        self.protos: dict = {}   # pfx -> {"in": {proto: [...]}, "out": {...}}
        self.bytes = 0.0         # exact total, independent of the peer caps
        self.packets = 0.0
        self.flows = 0
        self.internal_bytes = 0.0
        # Exact per-direction totals, kept OUTSIDE the capped maps. Deriving the
        # stored `tot` row from the maps made the total depend on the caps: a
        # map that had been trimmed by `_trim` could sum to more than the map it
        # was summed from, and a map that was never trimmed reported a different
        # base than one that was. Readers then compared rows from a capped map
        # against a total from a different map, which is how `proto` came to
        # exceed `tot` on production (103% of it).
        #
        # The headline volume also belongs here, not in the tail: `bytes` above
        # is the whole hour including the hours rehydrated from documents that
        # were themselves capped.
        self.dir_bytes = {"in": 0.0, "out": 0.0}
        self.dir_packets = {"in": 0.0, "out": 0.0}
        # Volume with no destination port (GRE/ESP/ICMP/undissected). Kept out
        # of the port dimension by necessity, so it is measured explicitly and
        # reported instead of appearing as an unexplained shortfall.
        self.noport = {"in": 0.0, "out": 0.0}
        self.first_at: Optional[datetime] = None
        self.last_at: Optional[datetime] = None
        self.ticks = 0
        self.evicted = 0
        self.loaded = False

    def side(self, attr: str, pfx: str, dirn: str) -> dict:
        outer = getattr(self, attr)
        byp = outer.get(pfx)
        if byp is None:
            byp = {"in": {}, "out": {}}
            outer[pfx] = byp
        return byp[dirn]


_HOURS: dict = {}
_TICK_LOCK = asyncio.Lock()


def _hour_of(ts: datetime) -> datetime:
    return ts.replace(minute=0, second=0, microsecond=0)


def _prune_hours(now: datetime) -> None:
    cutoff = _hour_of(now) - timedelta(hours=ROLLUP_HOUR_KEEP)
    for k in [k for k, v in _HOURS.items() if v.h < cutoff]:
        _HOURS.pop(k, None)


# --------------------------------------------------------------------------
# folding one record
# --------------------------------------------------------------------------


def _fold(acc: _Hour, rec: dict, nets: list) -> int:
    """Add one goflow2 record to ``acc``. Returns 1 when it counted."""
    try:
        byts = float(rec.get("bytes") or 0)
        pkts = float(rec.get("packets") or 0)
    except (TypeError, ValueError):
        return 0
    # `sampling_rate: 0` means "no sampling" (RouterOS default), so the
    # multiplier is 1 - not 0, which would zero every byte.
    rate = int(rec.get("sampling_rate") or 0) or 1
    if rate < 1:
        rate = 1
    byts *= rate
    pkts *= rate
    if byts <= 0 and pkts <= 0:
        return 0

    src = (rec.get("src_addr") or "").split("/")[0]
    dst = (rec.get("dst_addr") or "").split("/")[0]
    if not src or not dst:
        return 0

    src_net, _ = _match_net(nets, src)
    dst_net, _ = _match_net(nets, dst)
    if src_net is not None and dst_net is not None:
        # Lateral traffic never leaves the portal's own space; it belongs in
        # the volume total but not in a "top sources on the internet" table.
        acc.internal_bytes += byts
        acc.bytes += byts
        acc.packets += pkts
        acc.flows += 1
        return 1
    if dst_net is not None:
        pfx, dirn, peer = dst_net.cidr, "in", src
    elif src_net is not None:
        pfx, dirn, peer = src_net.cidr, "out", dst
    else:
        return 0  # transit traffic that does not touch us

    acc.bytes += byts
    acc.packets += pkts
    acc.flows += 1
    acc.dir_bytes[dirn] += byts
    acc.dir_packets[dirn] += pkts

    peer24 = prefix24_of(peer) or OTHER
    _bump(acc.side("nets", pfx, dirn), peer24, byts, pkts)
    _bump(acc.side("ips", pfx, dirn), peer, byts, pkts)

    # The remote service port is dst_port in both directions: inbound it is the
    # port the world connects to on our side, outbound it is the port we
    # connect to on theirs. src_port is ephemeral and carries no meaning here.
    try:
        dport = int(rec.get("dst_port") or 0)
    except (TypeError, ValueError):
        dport = 0
    if dport > 0:
        _bump(acc.side("ports", pfx, dirn), str(dport), byts, pkts)

    proto = str(rec.get("proto") or "?").upper()[:12] or "?"
    _bump(acc.side("protos", pfx, dirn), proto, byts, pkts)
    if dport <= 0:
        # Volume with no destination port is real traffic that no port row can
        # claim (GRE, ESP, ICMP, and anything the exporter could not dissect).
        # Tracked so the port panel can state why its rows sum below the total
        # instead of looking like it silently lost traffic.
        acc.noport[dirn] += byts
    return 1


# --------------------------------------------------------------------------
# collector file cursor
# --------------------------------------------------------------------------


async def flow_path(db) -> str:
    try:
        cfg = await db.integration_settings.find_one({"_id": "goflow2"})
        if cfg and cfg.get("flow_path"):
            return cfg["flow_path"]
    except Exception:  # noqa: BLE001
        pass
    return DEFAULT_FLOW_PATH


def _read_increment(path: str, cursor: dict, max_bytes: int) -> tuple:
    """Read new complete lines from ``path``.

    Returns ``(lines, new_cursor, gaps)``. Two independent checks decide
    whether the file was truncated or replaced under us, because logrotate
    uses ``copytruncate`` here: the inode survives, so a size comparison alone
    is not enough - the file can regrow past the stored offset within one tick
    and the shrink is never observed.

      1. ``size < offset`` -> truncated.
      2. the 64 bytes that precede ``offset`` must still equal what we last
         read. If they differ, the offset points into different data.

    On a reset we re-read from 0; the worst case is a few seconds of duplicated
    traffic at a rotation boundary, which is reported as a gap, never silently
    folded into a rate.
    """
    size = os.path.getsize(path)
    start = int(cursor.get("offset") or 0)
    marker = cursor.get("marker") or b""
    gaps = 0
    reset = False
    if size < start:
        reset, gaps = True, 1
    elif start > 0 and marker:
        try:
            with open(path, "rb") as fh:
                fh.seek(max(0, start - len(marker)))
                if fh.read(len(marker)) != marker:
                    reset, gaps = True, 1
        except OSError:
            reset, gaps = True, 1
    if reset:
        start = 0
    if size <= start:
        return [], {"offset": start, "marker": marker}, gaps

    with open(path, "rb") as fh:
        fh.seek(start)
        chunk = fh.read(max_bytes)
    if not chunk:
        return [], {"offset": start, "marker": marker}, gaps
    nl = chunk.rfind(b"\n")
    if nl < 0:
        # Not a single complete line in the whole chunk. Either the writer is
        # mid-line (try again next tick) or one record exceeds max_bytes (skip
        # it so the reader cannot wedge forever).
        if len(chunk) < max_bytes:
            return [], {"offset": start, "marker": marker}, gaps
        return [], {"offset": start + len(chunk), "marker": chunk[-64:]}, gaps
    body = chunk[: nl + 1]
    return body.split(b"\n"), {"offset": start + nl + 1, "marker": body[-64:]}, gaps


# --------------------------------------------------------------------------
# tick
# --------------------------------------------------------------------------


def _reconcile_dim(rows: dict, target: float, label: str, bucket: str) -> float:
    """Force ``sum(rows) == target``, returning the amount that had to move.

    ``target`` is the direction counter, which is incremented once per counted
    record and is therefore the only figure that cannot drift. The maps can
    drift in two directions and both were observed on production:

      * short - the old writer stored only the top-N rows and dropped the
        remainder, so a rehydrated map covered less than its own total;
      * long - the same writer computed some dimensions against a different
        denominator, leaving a fixed excess (measured: exactly +262,615,165
        bytes on `proto`) that rehydration then inherited forever, because
        nothing ever corrected *over*-counting.

    A shortfall is real traffic whose detail was dropped, so it belongs in the
    tail row. An excess is detail that was counted more times than the traffic
    existed, so it is removed from the largest rows first: that never invents
    traffic, and it keeps every named row at or below its stored value. Both
    paths log, because a silent repair is indistinguishable from a silent bug.
    """
    if not rows:
        return 0.0
    total = sum(v[0] for v in rows.values())
    delta = target - total
    if abs(delta) < 1.0:
        return 0.0

    if delta > 0:
        cur = rows.get(OTHER)
        if cur is not None:
            cur[0] += delta
        else:
            rows[OTHER] = [delta, 0.0]
        log.info("[netflow] %s %s/%s: short by %.3f GB, folded into tail",
                 bucket, label, "dir", delta / 1e9)
        return delta

    # Excess: take it off the heaviest rows, largest first.
    over = -delta
    for key, val in sorted(rows.items(), key=lambda kv: kv[1][0], reverse=True):
        if over <= 1.0:
            break
        if key == OTHER:
            continue
        take = min(val[0], over)
        val[0] -= take
        over -= take
        if val[0] <= 0:
            rows.pop(key, None)
    log.warning("[netflow] %s %s: over by %.3f GB, trimmed from largest rows",
                bucket, label, (-delta) / 1e9)
    return delta


async def _ensure_hour_loaded(db, acc: _Hour) -> None:
    """Re-hydrate the current hour from Mongo after a restart.

    Without this, the first flush of a fresh process would REPLACE the hour's
    documents with only post-restart traffic, silently deleting the part of
    the hour the previous process had already aggregated.
    """
    if acc.loaded:
        return
    acc.loaded = True
    try:
        docs = await db[ROLLUP_COLL].find({"h": acc.h}).to_list(200_000)
    except Exception:  # noqa: BLE001
        return
    for d in docs:
        pfx, dirn, dim = d.get("pfx"), d.get("dir"), d.get("dim")
        key = d.get("key")
        byts = float(d.get("bytes") or 0)
        pkts = float(d.get("packets") or 0)
        if dim == "tot":
            # The hour total and the direction totals are restored from the
            # stored documents, which are already exact for their hour. Adding
            # the aggregate a second time on top of the per-direction counters
            # would double every hour this process rehydrates.
            acc.packets += pkts
            acc.flows += int(d.get("flows") or 0)
            if dirn in ("in", "out"):
                acc.dir_bytes[dirn] += byts
                acc.dir_packets[dirn] += pkts
            acc.internal_bytes = max(acc.internal_bytes, float(d.get("internal_bytes") or 0))
            if dirn in ("in", "out"):
                acc.noport[dirn] = max(acc.noport[dirn],
                                      float(d.get("noport_bytes") or 0))
            continue
        if not pfx or dirn not in ("in", "out") or not key:
            continue
        if dim == "net":
            acc.side("nets", pfx, dirn)[key] = [byts, pkts]
        elif dim == "ip":
            acc.side("ips", pfx, dirn)[key] = [byts, pkts]
        elif dim == "port":
            acc.side("ports", pfx, dirn)[key] = [byts, pkts]
        elif dim == "proto":
            acc.side("protos", pfx, dirn)[key] = [byts, pkts]
    # Repair an hour that a previous, lossier writer left inconsistent. The
    # direction counters in `tot` are authoritative; the maps are aligned to
    # them in both directions. `port` is excluded by design - a record with no
    # destination port has no row to land in, so its shortfall is real and is
    # reported through `noport`/`port_coverage` instead of being papered over.
    for attr in ("nets", "ips", "protos"):
        outer = getattr(acc, attr)
        for pfx, byp in outer.items():
            for dirn in ("in", "out"):
                if byp[dirn]:
                    _reconcile_dim(byp[dirn], acc.dir_bytes[dirn], attr, acc.bucket)
    acc.bytes = acc.dir_bytes["in"] + acc.dir_bytes["out"] + acc.internal_bytes
    log.info("[netflow] rehydrated hour %s: %d docs, %.2f GB (in %.2f / out %.2f)",
             acc.bucket, len(docs), acc.bytes / 1e9,
             acc.dir_bytes["in"] / 1e9, acc.dir_bytes["out"] / 1e9)


def _consume(lines: list, acc: "_Hour", nets: list) -> tuple:
    """Parse and fold a batch. Runs in the executor, never on the event loop.

    At the measured rate (2,894 flows/s on production) a 12 s tick carries
    ~35k records; ``json.loads`` over that is a few hundred milliseconds of
    pure CPU. Doing it inline would stall every other coroutine in the worker
    - including the API requests this report serves - so the whole
    parse-and-fold happens off-loop. ``acc`` is only touched here and inside
    ``_TICK_LOCK``, so no corruption is possible.
    """
    counted = 0
    bad = 0
    for raw in lines:
        raw = raw.strip()
        if not raw:
            continue
        if raw[:1] != b"{":
            bad += 1
            continue
        try:
            rec = json.loads(raw)
        except (ValueError, TypeError):
            # A torn final line after copytruncate. Dropping it is correct;
            # counting it would invent a flow that never completed.
            bad += 1
            continue
        counted += _fold(acc, rec, nets)
    return counted, bad


async def rollup_tick(db) -> dict:
    """One aggregator tick: read new flow lines, fold them, flush if due.

    Leased by the scheduler (see ``emails.start_scheduler``), so only one
    worker aggregates at a time and the cursor in Mongo is single-writer.
    """
    if _TICK_LOCK.locked():
        return {"skipped": "in-progress"}
    async with _TICK_LOCK:
        if not _INDEXES_OK["done"]:
            await ensure_indexes(db)
        path = await flow_path(db)
        if not os.path.exists(path):
            return {"skipped": "no-collector", "path": path}
        try:
            size = os.path.getsize(path)
        except OSError as exc:
            return {"error": f"stat: {exc}"}

        cursor = await db[CURSOR_COLL].find_one({"_id": CURSOR_ID}) or {}
        loop = asyncio.get_running_loop()
        try:
            lines, new_cursor, gaps = await loop.run_in_executor(
                None, _read_increment, path, cursor, TICK_MAX_BYTES)
        except OSError as exc:
            return {"error": f"read: {exc}"}

        now = datetime.now(timezone.utc)
        nets = await _compile_local(db)
        bucket = _hour_of(now)
        acc = _HOURS.get(bucket.strftime("%Y-%m-%dT%H"))
        if acc is None:
            acc = _Hour(bucket)
            _HOURS[acc.bucket] = acc
            await _ensure_hour_loaded(db, acc)
        _prune_hours(now)

        counted, bad = await loop.run_in_executor(None, _consume, lines, acc, nets)

        acc.ticks += 1
        acc.last_at = now
        if counted and acc.first_at is None:
            acc.first_at = now
        for attr, cap in (("nets", NET_CAP), ("ips", IP_CAP), ("ports", PORT_CAP)):
            for byp in getattr(acc, attr).values():
                for d in byp.values():
                    acc.evicted += _trim(d, cap)

        # Close out every hour older than the current one. Without this, the
        # last ~55 s before :00 sits in memory unflushed and is then dropped:
        # the tick that crosses the boundary starts a fresh accumulator and
        # nothing ever writes the old one again. That is a silent hole at the
        # top of every hour, in every bucket of the report.
        closed = 0
        for key in [k for k, v in _HOURS.items() if v.h < bucket and v.loaded]:
            old = _HOURS.pop(key)
            try:
                closed += await flush_hour(db, old, final=True, nets=nets)
            except Exception as exc:  # noqa: BLE001
                log.warning("[netflow] finalize of hour %s failed: %s", old.bucket, exc)

        await db[CURSOR_COLL].update_one(
            {"_id": CURSOR_ID},
            {"$set": {"offset": new_cursor["offset"],
                      "marker": new_cursor["marker"],
                      "file_size": size,
                      "last_tick_at": now,
                      "last_lines": len(lines),
                      "last_counted": counted,
                      "last_bad": bad,
                      "last_hour": acc.bucket},
             "$inc": {"gaps": gaps},
             "$setOnInsert": {"created_at": now}},
            upsert=True,
        )

        flushed = 0
        last_flush = float(cursor.get("last_flush_ts") or 0)
        if time.time() - last_flush >= FLUSH_INTERVAL_S and counted:
            flushed = await flush_hour(db, acc, final=False, nets=nets)
            await db[CURSOR_COLL].update_one(
                {"_id": CURSOR_ID}, {"$set": {"last_flush_ts": time.time()}})

        return {"lines": len(lines), "counted": counted, "bad": bad,
                "gaps": gaps, "bytes_read": new_cursor["offset"] - int(cursor.get("offset") or 0),
                "flushed_docs": flushed + closed, "hour": acc.bucket}


# --------------------------------------------------------------------------
# flush
# --------------------------------------------------------------------------


def _asn_sidecars(docs_by_peer: dict, asmap: dict) -> dict:
    out = {}
    for key in docs_by_peer:
        row = asmap.get(key) or {}
        out[key] = {"asn": row.get("asn"), "cc": row.get("cc"),
                    "as_name": row.get("name"), "bgp_prefix": row.get("prefix")}
    return out


async def _enrich_peers(db, peers: list) -> dict:
    """bgp.tools annotation for a batch of peer /24s (cached)."""
    if not peers:
        return {}
    try:
        return await bgptools.lookup_many(db, peers, kind="ip")
    except Exception as exc:  # noqa: BLE001 - annotation is cosmetic, never fatal
        log.warning("[netflow] bgp.tools enrichment failed: %s", exc)
        return {}


async def flush_hour(db, acc: _Hour, *, final: bool = False, nets: Optional[list] = None) -> int:
    """Write the accumulator's current values for its hour.

    Uses ``replace_one`` on a deterministic ``_id`` and prunes by the flush
    sequence ``ft``. That combination means a reader never sees an empty
    window (no delete-then-insert) and a peer that dropped out of the top-N
    keeps its last real value for at most one flush instead of disappearing
    and reappearing.
    """
    ft = int(time.time())
    docs: list = []

    # Which peer /24s and IPs need an AS annotation?
    #
    # Ranked by volume across both directions, not by list position. Building
    # this as `in` then `out` and slicing it meant the cap was spent entirely on
    # inbound traffic and outbound peers were never asked about at all: measured
    # on production, 11 of the 15 heaviest unannotated rows were `out` and the
    # cache held correct ASNs for them the whole time. Volume is the fair
    # currency here - the heaviest peers are the ones a reader actually sees.
    want: dict = {}
    for pfx, byp in acc.nets.items():
        for dirn in ("in", "out"):
            ranked = sorted(byp[dirn].items(), key=lambda kv: kv[1][0], reverse=True)[:NET_TOP]
            for key, val in ranked:
                if key != OTHER:
                    want[key] = max(want.get(key, 0.0), val[0])
    for pfx, byp in acc.ips.items():
        for dirn in ("in", "out"):
            ranked = sorted(byp[dirn].items(), key=lambda kv: kv[1][0], reverse=True)[:IP_TOP]
            for ip, val in ranked:
                p24 = prefix24_of(ip)
                if p24:
                    want[p24] = max(want.get(p24, 0.0), val[0])
    wanted = [k for k, _ in sorted(want.items(), key=lambda kv: kv[1], reverse=True)][:ENRICH_PER_FLUSH]
    asmap = await _enrich_peers(db, wanted)

    for pfx in acc.nets:
        for dirn in ("in", "out"):
            base_id = f"{acc.bucket}|{pfx}|{dirn}"
            for dim, attr, top in (("net", "nets", NET_TOP),
                                   ("ip", "ips", IP_TOP),
                                   ("port", "ports", PORT_TOP),
                                   ("proto", "protos", PROTO_TOP)):
                items = acc.side(attr, pfx, dirn)
                if not items:
                    continue
                # Truncation has to be lossless or the hour lies about itself.
                # Writing only the top-N left the remainder in no document at
                # all, while the `tot` row is summed from the FULL map - so the
                # stored rows could never add up to the stored total. Measured
                # on production: `net` rows summed to 93% of `tot`, and `proto`
                # (4 keys, never truncated) summed to 103% of it. Rehydration
                # then read those truncated rows back as if they were the whole
                # hour, which is how the gap became permanent across restarts.
                # Reserving one slot inside the cap for a remainder row makes
                # the write exact: top-(N-1) plus the tail, and the sum of the
                # documents equals the accumulator for every dimension.
                ranked = sorted(items.items(), key=lambda kv: kv[1][0], reverse=True)
                keep = ranked[: max(1, top - 1)] if len(ranked) > top else ranked
                rows = {k: [v[0], v[1]] for k, v in keep}
                if len(ranked) > len(keep):
                    tail_b = sum(v[0] for v in items.values()) - sum(v[0] for v in rows.values())
                    tail_p = sum(v[1] for v in items.values()) - sum(v[1] for v in rows.values())
                    if tail_b > 0 or tail_p > 0:
                        cur = rows.get(OTHER)
                        if cur is not None:
                            # A trimmed in-memory map may already carry a
                            # sentinel; it is a real bucket, so add to it rather
                            # than overwrite the doc that holds it.
                            cur[0] += tail_b
                            cur[1] += tail_p
                        else:
                            rows[OTHER] = [tail_b, tail_p]
                dim_docs: list = []
                for key, (byts, pkts) in rows.items():
                    doc = {"_id": f"{base_id}|{dim}|{key}", "h": acc.h, "pfx": pfx,
                           "dir": dirn, "dim": dim, "key": key,
                           "bytes": byts, "packets": pkts, "ft": ft}
                    if key == OTHER:
                        doc["tail"] = True
                    if dim in ("net", "ip"):
                        peer = key if dim == "net" else (prefix24_of(key) or key)
                        row = asmap.get(peer) or {}
                        doc.update({"asn": row.get("asn"), "cc": row.get("cc"),
                                    "as_name": row.get("name"),
                                    "bgp_prefix": row.get("prefix")})
                    dim_docs.append(doc)

                # Enforced at write, after truncation, because that is the only
                # point where the stored sum is actually known. Two independent
                # traps make this necessary: `_trim` can leave a tail row that
                # then ranks below the cut and is dropped from `rows`, and a
                # `proto` row can retain an excess inherited from a previous
                # writer's bad denominator. Either one would make the hour
                # disagree with its own `tot` row, so the documents about to be
                # written are aligned to the direction counter here. `port` is
                # excluded by design: a record with no destination port has no
                # row to land in, so its shortfall is real and is reported
                # through `port_coverage` instead of being hidden in a tail.
                if dim in ("net", "ip", "proto") and dim_docs:
                    stored = sum(d["bytes"] for d in dim_docs)
                    delta = acc.dir_bytes[dirn] - stored
                    if delta > 1:
                        tail = next((d for d in dim_docs if d.get("key") == OTHER), None)
                        if tail is None:
                            tail = {"_id": f"{base_id}|{dim}|{OTHER}", "h": acc.h,
                                    "pfx": pfx, "dir": dirn, "dim": dim, "key": OTHER,
                                    "bytes": delta, "packets": 0.0, "ft": ft, "tail": True}
                            if dim in ("net", "ip"):
                                tail.update({"asn": None, "cc": None,
                                             "as_name": None, "bgp_prefix": None})
                            dim_docs.append(tail)
                        else:
                            tail["bytes"] += delta
                    elif delta < -1:
                        # More is about to be stored than the counter recorded,
                        # so take it off the heaviest rows: that never invents
                        # traffic, and no named row ends up above its own value.
                        over = -delta
                        for d in sorted(dim_docs, key=lambda x: x["bytes"], reverse=True):
                            if over <= 1 or d.get("key") == OTHER:
                                continue
                            take = min(d["bytes"], over)
                            d["bytes"] -= take
                            over -= take
                docs.extend(dim_docs)
            # Exact per-direction totals. These come from the counters, not from
            # the maps above: summing a capped map would make the hour's own
            # total move depending on whether a trim had happened, which is
            # exactly the inconsistency this row exists to prevent.
            docs.append({"_id": f"{base_id}|tot|_", "h": acc.h, "pfx": pfx, "dir": dirn,
                         "dim": "tot", "key": "_", "bytes": acc.dir_bytes[dirn],
                         "packets": acc.dir_packets[dirn], "ft": ft,
                         "flows": acc.flows, "exact": True,
                         # Lateral traffic (both ends inside our own space) is
                         # volume without being a peer row, so it has nowhere
                         # else to live. Carried here once per hour and restored
                         # on rehydration; `max` across prefixes is correct
                         # because it is a global figure, not a per-prefix one.
                         "internal_bytes": acc.internal_bytes,
                         "noport_bytes": acc.noport[dirn]})

    if not docs:
        return 0
    try:
        from pymongo import ReplaceOne
        await db[ROLLUP_COLL].bulk_write(
            [ReplaceOne({"_id": d["_id"]}, d, upsert=True) for d in docs],
            ordered=False,
        )
        # Prune what this flush did not touch: same hour, same prefix, older ft.
        await db[ROLLUP_COLL].delete_many(
            {"h": acc.h, "ft": {"$lt": ft}})
    except Exception as exc:  # noqa: BLE001
        log.warning("[netflow] flush failed for %s: %s", acc.bucket, exc)
        return 0

    for pfx in acc.nets:
        try:
            await db[META_COLL].update_one(
                {"_id": f"{acc.bucket}|{pfx}"},
                {"$set": {"h": acc.h, "pfx": pfx,
                          "first_at": acc.first_at, "last_at": acc.last_at,
                          "ticks": acc.ticks, "final": final,
                          "evicted": acc.evicted, "ft": ft},
                 "$setOnInsert": {"created_at": datetime.now(timezone.utc)}},
                upsert=True,
            )
        except Exception:  # noqa: BLE001
            pass
    return len(docs)


# --------------------------------------------------------------------------
# local prefix configuration
# --------------------------------------------------------------------------

_CFG_CACHE = {"at": 0.0, "nets": None}
_CFG_TTL_S = 60.0


def _widen_to_24(cidr: str) -> Optional[str]:
    try:
        net = ipaddress.ip_network(cidr, strict=False)
    except ValueError:
        return None
    if net.version != 4:
        return str(net)
    if net.prefixlen > 24:
        return str(net.supernet(new_prefix=24))
    return str(net)


async def _derive_prefixes(db) -> list:
    """Discover the portal's own networks, without hard-coding them.

    Two independent sources, both real records rather than a constant:
      * ``dcim_prefixes`` - the allocated IP blocks (widened to the enclosing
        /24, because a /28 allocation is not a routing boundary and the report
        groups peers by /24 anyway);
      * ``services.config.ip`` - the address actually assigned to each
        customer service.
    """
    found: list = []
    try:
        for doc in await db.dcim_prefixes.find({}).to_list(500):
            p = doc.get("prefix")
            if p:
                w = _widen_to_24(p)
                if w:
                    found.append(w)
    except Exception:  # noqa: BLE001
        pass
    try:
        for doc in await db.services.find({}, {"config.ip": 1, "status": 1}).to_list(2000):
            ip = ((doc.get("config") or {}).get("ip") or "").strip()
            if ip:
                w = _widen_to_24(ip)
                if w:
                    found.append(w)
    except Exception:  # noqa: BLE001
        pass
    # Private/loopback blocks are not "our traffic" in a NOC report.
    out = []
    for c in dict.fromkeys(found):
        try:
            net = ipaddress.ip_network(c, strict=False)
        except ValueError:
            continue
        if net.is_private or net.is_loopback or net.is_link_local:
            continue
        out.append(str(net))
    return out


async def local_prefix_config(db) -> dict:
    cfg = {}
    try:
        cfg = await db.integration_settings.find_one({"_id": CONFIG_ID}) or {}
    except Exception:  # noqa: BLE001
        cfg = {}
    return cfg


async def _compile_local(db) -> list:
    now = time.time()
    if _CFG_CACHE["nets"] is not None and now - _CFG_CACHE["at"] < _CFG_TTL_S:
        return _CFG_CACHE["nets"]
    cfg = await local_prefix_config(db)
    cidrs = [c for c in (cfg.get("local_prefixes") or []) if c]
    if not cidrs:
        cidrs = await _derive_prefixes(db)
    nets = _compile_nets(cidrs)
    _CFG_CACHE.update({"at": now, "nets": nets})
    return nets


def invalidate_prefix_cache() -> None:
    _CFG_CACHE.update({"at": 0.0, "nets": None})
    _REPORT_CACHE.clear()


async def list_prefixes(db) -> dict:
    """Configured local prefixes plus what actually carries traffic."""
    nets = await _compile_local(db)
    observed: dict = {}
    try:
        since = datetime.now(timezone.utc) - timedelta(hours=24)
        cursor = db[ROLLUP_COLL].aggregate([
            {"$match": {"dir": "in", "dim": "tot", "h": {"$gte": since}}},
            {"$group": {"_id": "$pfx", "bytes": {"$sum": "$bytes"}}},
            {"$sort": {"bytes": -1}},
        ])
        for row in await cursor.to_list(100):
            observed[row["_id"]] = float(row.get("bytes") or 0)
    except Exception:  # noqa: BLE001
        pass
    out = []
    for n in nets:
        out.append({"prefix": n.cidr,
                    "bytes_24h": observed.get(n.cidr, 0.0),
                    "configured": True})
    for pfx, byts in observed.items():
        if pfx not in {n.cidr for n in nets}:
            out.append({"prefix": pfx, "bytes_24h": byts, "configured": False})
    out.sort(key=lambda r: r["bytes_24h"], reverse=True)
    return {"prefixes": out, "default": out[0]["prefix"] if out else None,
            "configured": [n.cidr for n in nets]}


async def set_local_prefixes(db, prefixes: list) -> dict:
    cleaned = []
    for p in prefixes:
        p = (p or "").strip()
        if not p:
            continue
        try:
            cleaned.append(str(ipaddress.ip_network(p, strict=False)))
        except ValueError:
            raise ValueError(f"prefix tidak valid: {p!r}")
    await db.integration_settings.update_one(
        {"_id": CONFIG_ID},
        {"$set": {"local_prefixes": cleaned,
                  "updated_at": datetime.now(timezone.utc)}},
        upsert=True,
    )
    invalidate_prefix_cache()
    return {"local_prefixes": cleaned}


# --------------------------------------------------------------------------
# report assembly
# --------------------------------------------------------------------------

_PROTO_SERVICES = {
    20: "ftp-data", 21: "ftp", 22: "ssh", 23: "telnet", 25: "smtp", 53: "dns",
    80: "http", 110: "pop3", 123: "ntp", 143: "imap", 161: "snmp", 389: "ldap",
    443: "https", 445: "smb", 465: "smtps", 587: "submission", 993: "imaps",
    995: "pop3s", 1194: "openvpn", 1433: "mssql", 1723: "pptp", 1935: "rtmp",
    2320: "soteria", 3128: "squid", 3306: "mysql", 3389: "rdp", 5060: "sip",
    5432: "postgres", 5672: "amqp", 5900: "vnc", 6379: "redis", 8080: "http-alt",
    8443: "https-alt", 9002: "dvpn", 9200: "elasticsearch", 27017: "mongodb",
}


def _as_utc(dt: Optional[datetime]) -> Optional[datetime]:
    """Normalise a datetime to aware UTC.

    PyMongo returns naive datetimes (it stores UTC but strips the tzinfo), while
    everything this module writes is ``datetime.now(timezone.utc)``. Subtracting
    one from the other raises ``TypeError: can't subtract offset-naive and
    offset-aware datetimes`` - which is exactly how the ASN enrichment silently
    died on its first dry run against production: every lookup raised, the
    handler swallowed it as "annotation is cosmetic", and the whole report came
    back with zero AS names and an all-"unknown" geo split.

    A naive value from this database is always UTC, never local time, so
    attaching UTC is a correction rather than a guess.
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _fmt_ts(dt: Optional[datetime]) -> Optional[str]:
    d = _as_utc(dt)
    return d.isoformat().replace("+00:00", "Z") if d else None


async def _backfill_from_samples(db, prefix: str, start: datetime, end: datetime) -> tuple:
    """Rebuild hourly in/out for hours without rollup data.

    ``flow_samples`` stores the top-50 links per minute (bps per link), so a
    bucket rebuilt from it is a LOWER BOUND - the label in the UI says so.
    Summing per-link averages is still the correct operation: the average of a
    sum equals the sum of the averages for independent links.
    """
    buckets: dict = {}
    try:
        cursor = db[SAMPLES_COLL].aggregate([
            {"$match": {"at": {"$gte": start, "$lt": end}}},
            {"$group": {"_id": {"h": {"$dateTrunc": {"date": "$at", "unit": "hour"}},
                                "src": "$src", "dst": "$dst"},
                        "bps": {"$avg": "$bps"}}},
        ])
        rows = await cursor.to_list(300_000)
    except Exception as exc:  # noqa: BLE001
        log.warning("[netflow] flow_samples backfill failed: %s", exc)
        return {}, 0
    net = _Net(prefix)
    seen = 0
    for r in rows:
        src, dst, bps = r["_id"].get("src"), r["_id"].get("dst"), float(r.get("bps") or 0)
        if not src or not dst or bps <= 0:
            continue
        s_net, _ = _match_net([net], src)
        d_net, _ = _match_net([net], dst)
        if s_net is not None and d_net is not None:
            continue
        if d_net is not None:
            dirn = "in"
        elif s_net is not None:
            dirn = "out"
        else:
            continue
        h = r["_id"]["h"]
        if isinstance(h, datetime):
            if h.tzinfo is None:
                h = h.replace(tzinfo=timezone.utc)
            key = h.astimezone(timezone.utc).strftime("%Y-%m-%dT%H")
        else:
            key = str(h)[:13]
        slot = buckets.setdefault(key, {"in_bps": 0.0, "out_bps": 0.0})
        slot[f"{dirn}_bps"] += bps
        seen += 1
    return buckets, seen


async def build_daily_report(db, *, prefix: Optional[str] = None, hours: int = 24,
                             now: Optional[datetime] = None, use_cache: bool = True) -> dict:
    now = now or datetime.now(timezone.utc)
    hours = max(1, min(int(hours or 24), 168))

    prefix_info = await list_prefixes(db)
    prefix = prefix or prefix_info.get("default")
    if not prefix:
        return {"ok": False, "error": "no local prefix configured",
                "prefixes": prefix_info.get("prefixes") or [],
                "hint": "set integration_settings/_id=netflow.local_prefixes or "
                        "create a dcim prefix / service with an IP"}
    try:
        net = _Net(prefix)
    except ValueError:
        return {"ok": False, "error": f"invalid prefix {prefix!r}"}
    prefix = net.cidr

    # A zero TTL would divide by zero here and 500 the endpoint, so the cache
    # is disabled by skipping it rather than by setting the TTL to nothing.
    use_cache = use_cache and REPORT_CACHE_S > 0
    cache_key = (prefix, hours, int(now.timestamp() // REPORT_CACHE_S)) if use_cache else None
    if use_cache and cache_key in _REPORT_CACHE:
        return _REPORT_CACHE[cache_key]

    end_hour = _hour_of(now)
    start_hour = end_hour - timedelta(hours=hours - 1)
    errors: list = []

    try:
        docs = await db[ROLLUP_COLL].find(
            {"pfx": prefix, "h": {"$gte": start_hour}}).to_list(200_000)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"rollup read failed: {exc}", "prefix": prefix}

    buckets: dict = {}
    for i in range(hours):
        h = start_hour + timedelta(hours=i)
        buckets[h.strftime("%Y-%m-%dT%H")] = {
            "hour": h, "in_bytes": 0.0, "out_bytes": 0.0,
            "in_bps": 0.0, "out_bps": 0.0, "source": "none", "partial": False,
        }

    peers_in: dict = {}       # peer24 -> {bytes, asn, cc, as_name, hourly: {h: bytes}}
    peers_out: dict = {}
    ip_in: dict = {}          # ip -> {bytes, asn, cc, as_name, peer24}
    ip_out: dict = {}
    ports_in: dict = {}
    ports_out: dict = {}
    protos_in: dict = {}
    protos_out: dict = {}
    evicted = 0

    for d in docs:
        key = _as_utc(d.get("h"))
        if key is None:
            continue
        bkey = key.strftime("%Y-%m-%dT%H")
        slot = buckets.get(bkey)
        if slot is None:
            continue
        dim = d.get("dim")
        byts = float(d.get("bytes") or 0)
        if dim == "tot":
            if d.get("dir") == "in":
                slot["in_bytes"] = max(slot["in_bytes"], byts)
            else:
                slot["out_bytes"] = max(slot["out_bytes"], byts)
            slot["source"] = "rollup"
            continue
        dirn = d.get("dir")
        peer_key = d.get("key")
        is_tail = bool(d.get("tail"))
        if dim == "net":
            target = peers_in if dirn == "in" else peers_out
            row = target.get(peer_key)
            if row is None:
                row = target[peer_key] = {"peer": peer_key, "bytes": 0.0,
                                          "asn": d.get("asn"), "cc": d.get("cc"),
                                          "as_name": d.get("as_name"), "hourly": {},
                                          "tail": is_tail}
            row["bytes"] += byts
            row["hourly"][bkey] = row["hourly"].get(bkey, 0.0) + byts
            if not row.get("asn") and d.get("asn"):
                row.update({"asn": d.get("asn"), "cc": d.get("cc"),
                            "as_name": d.get("as_name")})
            if is_tail:
                row["tail"] = True
                evicted += 1
        elif dim == "ip":
            target = ip_in if dirn == "in" else ip_out
            row = target.get(peer_key)
            if row is None:
                row = target[peer_key] = {"ip": peer_key, "bytes": 0.0,
                                          "asn": d.get("asn"), "cc": d.get("cc"),
                                          "as_name": d.get("as_name"),
                                          "peer24": prefix24_of(peer_key)}
            row["bytes"] += byts
            if not row.get("asn") and d.get("asn"):
                row.update({"asn": d.get("asn"), "cc": d.get("cc"),
                            "as_name": d.get("as_name")})
        elif dim == "port":
            target = ports_in if dirn == "in" else ports_out
            target[peer_key] = target.get(peer_key, 0.0) + byts
        elif dim == "proto":
            target = protos_in if dirn == "in" else protos_out
            target[peer_key] = target.get(peer_key, 0.0) + byts

    # A hour with no `tot` row but with peer rows still has real traffic.
    for bkey, slot in buckets.items():
        if slot["source"] == "none" and (slot["in_bytes"] or slot["out_bytes"]):
            slot["source"] = "rollup"

    # ---- partial hours + coverage ------------------------------------
    try:
        metas = await db[META_COLL].find(
            {"pfx": prefix, "h": {"$gte": start_hour}}).to_list(400)
    except Exception:  # noqa: BLE001
        metas = []
    meta_by_hour = {}
    for m in metas:
        h = _as_utc(m.get("h"))
        if h is not None:
            meta_by_hour[h.strftime("%Y-%m-%dT%H")] = m
    first_rollup = None
    for bkey, slot in buckets.items():
        m = meta_by_hour.get(bkey)
        if not m:
            if slot["hour"] < start_hour + timedelta(hours=1) or slot["source"] != "rollup":
                slot["partial"] = slot["source"] != "none"
            continue
        fa = _as_utc(m.get("first_at"))
        if fa is not None:
            slot["first_at"] = _fmt_ts(fa)
            if first_rollup is None or fa < first_rollup:
                first_rollup = fa
            if fa.minute > 5 and fa.hour == slot["hour"].hour:
                slot["partial"] = True
    # The hour in progress is inherently partial.
    if buckets:
        buckets[end_hour.strftime("%Y-%m-%dT%H")]["partial"] = True

    # ---- backfill the hours rollup cannot cover ----------------------
    empty = [k for k, v in buckets.items() if v["source"] == "none"]
    backfilled = 0
    if empty:
        samples_from = datetime.now(timezone.utc) - timedelta(hours=7)
        bstart = max(start_hour, samples_from)
        if end_hour >= bstart:
            fill, seen = await _backfill_from_samples(db, prefix, bstart, now + timedelta(minutes=1))
            backfilled = seen
            for bkey, vals in fill.items():
                slot = buckets.get(bkey)
                if slot is None or slot["source"] != "none":
                    continue
                slot["in_bps"] = vals["in_bps"]
                slot["out_bps"] = vals["out_bps"]
                slot["in_bytes"] = vals["in_bps"] * 3600 / 8
                slot["out_bytes"] = vals["out_bps"] * 3600 / 8
                slot["source"] = "backfill"
                slot["partial"] = True
    if backfilled:
        errors.append({"source": "backfill",
                       "detail": f"{backfilled} link-hours rebuilt from flow_samples "
                                 f"(top-50 links/min - lower bound)"})

    # ---- convert byte totals into rates ------------------------------
    for bkey, slot in buckets.items():
        if slot["source"] == "backfill":
            continue  # already rates
        slot["in_bps"] = slot["in_bytes"] * 8 / 3600
        slot["out_bps"] = slot["out_bytes"] * 8 / 3600

    ordered = [buckets[(start_hour + timedelta(hours=i)).strftime("%Y-%m-%dT%H")] for i in range(hours)]

    # ---- enrich any peer the flush could not annotate ----------------
    # Also re-check peers that resolved to an ASN but no country: without a
    # country they land in the "unknown" geo bucket, which is the one number in
    # this report an operator cannot act on.
    missing = [p for p, r in peers_in.items()
               if (not r.get("asn") or not r.get("cc")) and p != OTHER and not r.get("tail")]
    missing += [p for p, r in peers_out.items()
                if (not r.get("asn") or not r.get("cc")) and p != OTHER and not r.get("tail")]
    # Sorted by bytes so the biggest unannotated peers are resolved first: an
    # unknown 60% of traffic is a gap in the report, an unknown 0.1% block is a
    # footnote. 200 fits one whois batch, so a full re-annotation of the report's
    # peer set costs a single connection.
    missing = list(dict.fromkeys(missing))[:200]
    if missing:
        order = {p: (peers_in.get(p) or peers_out.get(p) or {}).get("bytes", 0) for p in missing}
        missing.sort(key=lambda p: order.get(p, 0), reverse=True)
        asmap = await _enrich_peers(db, missing)
        for p, row in asmap.items():
            for table in (peers_in, peers_out):
                cur = table.get(p)
                if cur is None:
                    continue
                if not cur.get("asn") and row.get("asn"):
                    cur.update({"asn": row.get("asn"), "as_name": row.get("name")})
                if not cur.get("cc") and row.get("cc"):
                    cur["cc"] = row.get("cc")

    # ---- totals -------------------------------------------------------
    #
    # Two different quantities, deliberately kept apart:
    #
    #   * the WINDOW total - every hour that has a number, including hours
    #     rebuilt from `flow_samples`. This is what the headline metrics show.
    #   * the PEER total - only the hours the aggregator measured itself.
    #
    # The second exists because the two sources are not the same measurement.
    # A bucket built from `flow_samples` contains the top-50 links per minute
    # only, so it is a lower bound on VOLUME - but for a share denominator it
    # is worse than that: the traffic *missing* from the sample is concentrated
    # in the heavy peer /24s, which were cut. Dividing peer bytes (rollup only)
    # by a window total that includes those understated hours produced shares
    # of 0.03% for the #1 source on production. Peer, protocol and port shares
    # therefore use the rollup-only total, and when there is no rollup at all
    # the denominator falls back to the full window so the panel is never all
    # zeros.
    total_in = sum(s["in_bytes"] for s in ordered)
    total_out = sum(s["out_bytes"] for s in ordered)
    rollup_in = sum(s["in_bytes"] for s in ordered if s["source"] == "rollup")
    rollup_out = sum(s["out_bytes"] for s in ordered if s["source"] == "rollup")
    denom_in = rollup_in or total_in or 1.0
    denom_out = rollup_out or total_out or 1.0
    # Average rate over the window's real length, not over 24 h when the
    # window is shorter than a day.
    span_h = max(1.0, (now - start_hour).total_seconds() / 3600)
    avg_in = total_in * 8 / (span_h * 3600)
    avg_out = total_out * 8 / (span_h * 3600)
    peak_in = max(ordered, key=lambda s: s["in_bps"]) if ordered else None
    peak_out = max(ordered, key=lambda s: s["out_bps"]) if ordered else None

    def _series(getter):
        return [round(buckets[(start_hour + timedelta(hours=i)).strftime("%Y-%m-%dT%H")].get(getter) or 0, 1)
                for i in range(hours)]

    # ---- peer tables ---------------------------------------------------
    def _peer_rows(table: dict, total: float, limit: int = 8) -> list:
        # The long-tail sentinel is not a network: it is the sum of every peer
        # below the write cap. Keeping it out of the ranking stops it from
        # displacing a real peer, and re-appending it at the end keeps the table
        # honest about how much traffic it does not name individually.
        tail = table.get(OTHER)
        rows = sorted((r for k, r in table.items() if k != OTHER),
                      key=lambda r: r["bytes"], reverse=True)
        picked = [r for r in rows[:limit] if r["bytes"] > 0]
        if tail and tail["bytes"] > 0:
            picked.append(tail)
        out = []
        for r in picked:
            out.append({
                "peer": r.get("peer") or OTHER,
                "tail": bool(r.get("tail")),
                "asn": r.get("asn"),
                "as_name": r.get("as_name") or None,
                "cc": r.get("cc"),
                "bytes": round(r["bytes"], 0),
                "share": round(r["bytes"] / total, 4) if total else 0.0,
                "gb": round(r["bytes"] / 1e9, 3),
                "avg_bps": round(r["bytes"] * 8 / (span_h * 3600), 1),
                "series": [round(r["hourly"].get(
                    (start_hour + timedelta(hours=i)).strftime("%Y-%m-%dT%H"), 0.0) / 1e9, 4)
                    for i in range(hours)],
            })
        return out

    top_sources = _peer_rows(peers_in, denom_in)
    top_destinations = _peer_rows(peers_out, denom_out)

    # ---- per-IP talkers, annotated with their AS ----------------------
    def _ip_rows(table: dict, total: float, limit: int = 25) -> list:
        rows = sorted(table.values(), key=lambda r: r["bytes"], reverse=True)
        out = []
        for r in rows[:limit]:
            if r["bytes"] <= 0:
                continue
            out.append({
                "ip": r["ip"],
                "peer": r.get("peer24"),
                "tail": r["ip"] == OTHER,
                "asn": r.get("asn"),
                "as_name": r.get("as_name") or None,
                "cc": r.get("cc"),
                "bytes": round(r["bytes"], 0),
                "gb": round(r["bytes"] / 1e9, 3),
                "share": round(r["bytes"] / total, 4) if total else 0.0,
            })
        return out

    talkers_in = _ip_rows(ip_in, denom_in, 30)
    talkers_out = _ip_rows(ip_out, denom_out, 30)

    # Top IPs grouped per AS - the reference report's "top IP per AS" table.
    # An IP whose /24 bgp.tools could not resolve is grouped by its own /24, not
    # lumped under one shared "AS ?" row: those addresses belong to unrelated
    # networks (observed on production: Telkomsel, Cloudflare and Telemedia
    # stacked into a single "unknown" group), and presenting them as one network
    # states something false.
    per_as: dict = {}
    for dirn, rows in (("in", talkers_in), ("out", talkers_out)):
        for r in rows:
            if r.get("asn"):
                k = (dirn, "asn", r["asn"])
            else:
                k = (dirn, "peer", r.get("peer") or "unknown")
            slot = per_as.setdefault(k, {"direction": dirn, "asn": r.get("asn"),
                                         "as_name": r.get("as_name"),
                                         "cc": r.get("cc"), "bytes": 0.0,
                                         "peer": r.get("peer") if not r.get("asn") else None,
                                         "tail": bool(r.get("tail")),
                                         "ips": []})
            slot["bytes"] += r["bytes"]
            if r.get("tail"):
                slot["tail"] = True
            if not slot.get("asn") and r.get("asn"):
                slot.update({"asn": r["asn"], "as_name": r.get("as_name"), "cc": r.get("cc")})
            if len(slot["ips"]) < 3:
                slot["ips"].append({"ip": r["ip"], "bytes": r["bytes"], "gb": r["gb"],
                                    "share": r["share"],
                                    "tail": bool(r.get("tail"))})
    top_talkers = sorted(per_as.values(), key=lambda s: s["bytes"], reverse=True)[:12]

    # ---- geo split (both directions, by peer /24) ---------------------
    geo = {"domestic": {"bytes": 0.0, "peers": 0, "asns": set()},
           "international": {"bytes": 0.0, "peers": 0, "asns": set()},
           "unknown": {"bytes": 0.0, "peers": 0, "asns": set()}}
    for table in (peers_in, peers_out):
        for p, r in table.items():
            if p == OTHER or r.get("tail"):
                continue
            cc = (r.get("cc") or "").upper()
            bucket = "domestic" if cc == "ID" else ("international" if cc else "unknown")
            geo[bucket]["bytes"] += r["bytes"]
            geo[bucket]["peers"] += 1
            if r.get("asn"):
                geo[bucket]["asns"].add(r["asn"])
    geo_total = sum(g["bytes"] for g in geo.values())
    geo_out = {}
    for k, g in geo.items():
        geo_out[k] = {"bytes": round(g["bytes"], 0), "gb": round(g["bytes"] / 1e9, 3),
                      "share": round(g["bytes"] / geo_total, 4) if geo_total else 0.0,
                      "peers": g["peers"], "asns": len(g["asns"]),
                      "avg_bps": round(g["bytes"] * 8 / (span_h * 3600), 1)}

    # ---- protocol / port breakdown ------------------------------------
    def _share_rows(d: dict, total: float, limit: int = 12, with_service: bool = False) -> list:
        """Top rows plus one remainder, so the shares add up to 100%.

        Two truncations happen on the way here - the writer stores only the
        top PORT_TOP/PROTO_TOP keys, and this display shows fewer still. If the
        display just cut the list, the bars would silently under-report and a
        protocol that carries 20% of the traffic could be absent from a panel
        whose numbers appear to sum to the total. The remainder row is labelled
        by the client and is never dressed up as a protocol or a port.
        """
        named = {k: v for k, v in d.items() if k != OTHER}
        tail_bytes = d.get(OTHER, 0.0)
        ranked = sorted(named.items(), key=lambda kv: kv[1], reverse=True)
        shown = ranked[:limit] if len(ranked) > limit else ranked
        rest = sum(v for _, v in ranked[len(shown):]) + tail_bytes
        out = []
        for k, v in shown:
            if v <= 0:
                continue
            item = {"key": k, "bytes": round(v, 0), "gb": round(v / 1e9, 3),
                    "share": round(v / total, 4) if total else 0.0, "tail": False}
            if with_service:
                try:
                    item["service"] = _PROTO_SERVICES.get(int(k))
                except (TypeError, ValueError):
                    item["service"] = None
            out.append(item)
        if rest > 0:
            out.append({"key": OTHER, "bytes": round(rest, 0),
                        "gb": round(rest / 1e9, 3),
                        "share": round(rest / total, 4) if total else 0.0,
                        "tail": True,
                        "service": None,
                        "grouped": len(ranked) - len(shown) + (1 if tail_bytes else 0)})
        return out

    protocols = {
        "in": _share_rows(protos_in, denom_in, 10),
        "out": _share_rows(protos_out, denom_out, 10),
    }
    ports = {
        "in": _share_rows(ports_in, denom_in, 15, with_service=True),
        "out": _share_rows(ports_out, denom_out, 15, with_service=True),
    }
    # Port shares are computed against the direction total, but a record with no
    # destination port has no row to land in. Reporting that volume lets the
    # panel say "these rows cover 77% because the rest carries no port" instead
    # of leaving the reader to assume the missing quarter was never measured.
    port_coverage = {}
    for dirn, total in (("in", denom_in), ("out", denom_out)):
        covered = sum(p["bytes"] for p in ports[dirn])
        port_coverage[dirn] = {
            "bytes": round(covered, 0),
            "share": round(covered / total, 4) if total else 0.0,
            "missing_share": round(max(0.0, 1 - covered / total), 4) if total else 0.0,
        }
    # Self-check: the shown rows must reconstruct the measured total for this
    # dimension. If they do not, the report is under-reporting and the operator
    # sees bars that quietly omit traffic. This was a real defect on production
    # (`net` summed to 93% of `tot`, `proto` to 103%), so it is asserted here
    # rather than trusted: any mismatch is surfaced in `errors` instead of
    # being rendered as if the numbers were complete.
    for label, table, total, listed in (
        ("net", peers_in, denom_in, top_sources),
        ("net-out", peers_out, denom_out, top_destinations),
        ("proto-in", protos_in, denom_in, protocols["in"]),
        ("proto-out", protos_out, denom_out, protocols["out"]),
    ):
        shown = sum(float(r.get("bytes") or 0) for r in listed)
        # peers are displayed capped at 8 named rows plus the tail row; the tail
        # is what makes the sum whole, so a shortfall here is a real bug.
        if total > 0 and shown > total * 1.005:
            errors.append({"source": f"dimension:{label}",
                           "detail": (f"baris {label} berjumlah {shown / 1e9:.3f} GB, "
                                      f"melebihi total {total / 1e9:.3f} GB - "
                                      "agregator menulis lebih dari yang dihitung")})

    # ---- AS-level rollup ----------------------------------------------
    as_rows: dict = {}
    for dirn, table, total in (("in", peers_in, denom_in), ("out", peers_out, denom_out)):
        for p, r in table.items():
            if p == OTHER:
                continue
            key = (dirn, r.get("asn") or 0)
            slot = as_rows.setdefault(key, {"direction": dirn, "asn": r.get("asn"),
                                            "as_name": r.get("as_name"), "cc": r.get("cc"),
                                            "bytes": 0.0, "peers": 0})
            slot["bytes"] += r["bytes"]
            slot["peers"] += 1
    as_breakdown = []
    for slot in sorted(as_rows.values(), key=lambda s: s["bytes"], reverse=True)[:20]:
        total = denom_in if slot["direction"] == "in" else denom_out
        as_breakdown.append({**slot, "bytes": round(slot["bytes"], 0),
                             "gb": round(slot["bytes"] / 1e9, 3),
                             "share": round(slot["bytes"] / total, 4) if total else 0.0})

    # ---- coverage ------------------------------------------------------
    rollup_hours = sum(1 for s in ordered if s["source"] == "rollup")
    backfill_hours = sum(1 for s in ordered if s["source"] == "backfill")
    empty_hours = sum(1 for s in ordered if s["source"] == "none")

    collector = {"path": await flow_path(db), "exists": False}
    try:
        p = collector["path"]
        if os.path.exists(p):
            st = os.stat(p)
            collector.update({"exists": True, "size": st.st_size,
                              "file_age_s": round(time.time() - st.st_mtime, 1)})
    except OSError:
        pass
    try:
        cur = await db[CURSOR_COLL].find_one({"_id": CURSOR_ID}) or {}
        lt = _as_utc(cur.get("last_tick_at"))
        collector["last_tick_at"] = _fmt_ts(lt)
        collector["lag_s"] = round((datetime.now(timezone.utc) - lt).total_seconds(), 1) if lt else None
        collector["gaps"] = int(cur.get("gaps") or 0)
        collector["offset"] = int(cur.get("offset") or 0)
    except Exception:  # noqa: BLE001
        pass

    payload = {
        "ok": True,
        "prefix": prefix,
        "prefixes": prefix_info.get("prefixes") or [],
        "generated_at": _fmt_ts(now),
        "window": {"from": _fmt_ts(start_hour), "to": _fmt_ts(now),
                   "hours": hours, "span_hours": round(span_h, 2)},
        "totals": {
            "bytes_in": round(total_in, 0), "bytes_out": round(total_out, 0),
            "bytes_total": round(total_in + total_out, 0),
            "gb_in": round(total_in / 1e9, 3), "gb_out": round(total_out / 1e9, 3),
            "gb_total": round((total_in + total_out) / 1e9, 3),
            "avg_in_bps": round(avg_in, 1), "avg_out_bps": round(avg_out, 1),
            "avg_total_bps": round(avg_in + avg_out, 1),
            "peak_in_bps": round(peak_in["in_bps"], 1) if peak_in else 0.0,
            "peak_out_bps": round(peak_out["out_bps"], 1) if peak_out else 0.0,
            "peak_in_hour": _fmt_ts(peak_in["hour"]) if peak_in else None,
            "peak_out_hour": _fmt_ts(peak_out["hour"]) if peak_out else None,
        },
        "buckets": [{
            "hour": _fmt_ts(s["hour"]),
            "in_bps": round(s["in_bps"], 1),
            "out_bps": round(s["out_bps"], 1),
            "in_bytes": round(s["in_bytes"], 0),
            "out_bytes": round(s["out_bytes"], 0),
            "source": s["source"],
            "partial": bool(s.get("partial")),
        } for s in ordered],
        "download": {"label": "DOWNLOAD (IN)", "avg_bps": round(avg_in, 1),
                     "peak_bps": round(peak_in["in_bps"], 1) if peak_in else 0.0,
                     "peak_hour": _fmt_ts(peak_in["hour"]) if peak_in else None,
                     "series": _series("in_bps")},
        "upload": {"label": "UPLOAD (OUT)", "avg_bps": round(avg_out, 1),
                   "peak_bps": round(peak_out["out_bps"], 1) if peak_out else 0.0,
                   "peak_hour": _fmt_ts(peak_out["hour"]) if peak_out else None,
                   "series": _series("out_bps")},
        "geo": geo_out,
        "top_sources": top_sources,
        "top_destinations": top_destinations,
        "top_talkers": top_talkers,
        "as_breakdown": as_breakdown,
        "protocols": protocols,
        "ports": ports,
        "port_coverage": port_coverage,
        "coverage": {
            "rollup_hours": rollup_hours,
            "backfill_hours": backfill_hours,
            "empty_hours": empty_hours,
            "first_rollup_at": _fmt_ts(first_rollup),
            "evicted_peer_rows": evicted,
            "tail_peer_rows": evicted,
            "rollup_docs": len(docs),
            "collector": collector,
        },
        "errors": errors,
    }
    if use_cache and cache_key is not None:
        _REPORT_CACHE[cache_key] = payload
        if len(_REPORT_CACHE) > 24:
            for k in list(_REPORT_CACHE)[:-12]:
                _REPORT_CACHE.pop(k, None)
    return payload


# --------------------------------------------------------------------------
# light health probe (feeds the sampling badge; no aggregation)
# --------------------------------------------------------------------------


async def health_snapshot(db) -> dict:
    out = {"ok": True, "path": None, "stale": True, "file_age_s": None,
           "rollup": {}, "source": "none"}
    try:
        path = await flow_path(db)
        out["path"] = path
        if os.path.exists(path):
            st = os.stat(path)
            age = time.time() - st.st_mtime
            out.update({"file_age_s": round(age, 1), "stale": age > 300,
                        "size": st.st_size, "source": "goflow2"})
    except OSError as exc:
        out["error"] = str(exc)[:160]
    try:
        cur = await db[CURSOR_COLL].find_one({"_id": CURSOR_ID}) or {}
        lt = _as_utc(cur.get("last_tick_at"))
        lag = round((datetime.now(timezone.utc) - lt).total_seconds(), 1) if lt else None
        out["rollup"] = {"last_tick_at": _fmt_ts(lt),
                         "lag_s": lag, "gaps": int(cur.get("gaps") or 0),
                         "offset": int(cur.get("offset") or 0),
                         "counted": int(cur.get("last_counted") or 0),
                         "last_hour": cur.get("last_hour")}
    except Exception as exc:  # noqa: BLE001
        out["rollup"] = {"error": str(exc)[:160]}
    try:
        out["hours"] = await db[ROLLUP_COLL].distinct("h")
        out["hours"] = len(out["hours"])
    except Exception:  # noqa: BLE001
        out["hours"] = 0
    return out


async def retention_sweep(db, days: int = ROLLUP_RETENTION_DAYS) -> dict:
    cutoff = datetime.now(timezone.utc) - timedelta(days=max(1, days))
    deleted = {"rollup": 0, "meta": 0}
    try:
        r = await db[ROLLUP_COLL].delete_many({"h": {"$lt": cutoff}})
        deleted["rollup"] = r.deleted_count
    except Exception as exc:  # noqa: BLE001
        log.warning("[netflow] rollup retention failed: %s", exc)
    try:
        r = await db[META_COLL].delete_many({"h": {"$lt": cutoff}})
        deleted["meta"] = r.deleted_count
    except Exception:  # noqa: BLE001
        pass
    return deleted


_INDEXES_OK = {"done": False}
_INDEX_LOCK = asyncio.Lock()


async def ensure_indexes(db) -> None:
    """Create the rollup indexes once per process.

    ``flow_rollup`` is written every ~55 s and read every time the report
    renders, always filtered by ``pfx`` + ``h``: without that compound index
    the read becomes a collection scan over millions of documents and the
    panel times out instead of merely being slow.
    """
    if _INDEXES_OK["done"]:
        return
    async with _INDEX_LOCK:
        if _INDEXES_OK["done"]:
            return
        try:
            await db[ROLLUP_COLL].create_index([("pfx", 1), ("h", 1)])
            await db[ROLLUP_COLL].create_index([("h", 1)])
            await db[META_COLL].create_index([("pfx", 1), ("h", 1)])
            # Retention is enforced by `retention_sweep`, which is a real
            # delete - no TTL index here, because these documents are read by
            # date range and a TTL would delete mid-hour under a slow sweep.
            _INDEXES_OK["done"] = True
        except Exception as exc:  # noqa: BLE001
            # Retried on the next tick; a missing index degrades speed, not
            # correctness, so it must never stop aggregation.
            log.warning("[netflow] index creation failed: %s", exc)
