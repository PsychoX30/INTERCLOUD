"""bgp.tools lookup + cache (ASN, origin prefix, country, AS name).

Why the whois interface and not the HTTP API
--------------------------------------------
bgp.tools documents several automated interfaces (https://bgp.tools/kb/api).
The HTTP table dumps (``/table.txt``, ``/table.jsonl``, ``/asns.csv``) are
*whole-table* exports that the operator asks callers to fetch at most every
30 minutes and cache for 2-24 hours, and the HTML pages are explicitly
off-limits to robots. None of that fits the question this portal asks
thousands of times a day: "which AS originates this /24, and in which
country".

Their bulk whois interface on TCP/43 answers exactly that, and it answers a
whole batch in one connection::

    begin
    138.199.35.207
    91.108.56.10
    end

    212238 | 138.199.35.207 | 138.199.35.0/24 | GB | RIPE | 2020-12-02 | Datacamp Limited
    62014  | 91.108.56.10   | 91.108.56.0/24 | VG | RIPE | 2014-03-24 | Telegram Messenger - Singapore

One row carries the ASN, the IP, the *origin prefix*, the country code, the
registry and the AS name - i.e. everything the daily flow report annotates
with, in a single round trip. Verified against production on 2026-11-24:
12 items in, 12 rows out, order preserved, unallocated input answered with
``asn=0, name=ERR_AS_NAME_NOT_FOUND`` (a normal, cacheable negative). An
ASN can also be queried directly (``as7713``), which is how the AS name
backstop works without downloading ``asns.csv``.

Two rules keep us a good citizen, because the service is free and has no
SLA:
  * one session at a time, at most two per second;
  * every answer cached for 30 days (6 hours for a negative), so a busy
    hour costs a handful of lookups, not hundreds.

``asns.csv`` is only touched when whois hands back an ASN with no name, and
then it is *streamed and filtered* - the wanted ASNs are kept, the rest of
the file is discarded. HTTP requests carry the contactable User-Agent that
bgp.tools asks for; generic agents get blocked.
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import socket
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional

log = logging.getLogger("portal.bgptools")

WHOIS_HOST = "bgp.tools"
WHOIS_PORT = 43
CONNECT_TIMEOUT_S = 6.0
READ_TIMEOUT_S = 12.0
MAX_BATCH = 250          # items per whois session
MAX_BYTES = 1 << 20      # a 250-row answer is a few KB; this is a runaway guard

# bgp.tools asks automated HTTP callers to identify themselves and give a way
# to reach them, and warns that default/generic agents get blocked.
HTTP_UA = "intercloud-portal bgp.tools - support@intercloud-digital.com"
ASNS_CSV_URL = "https://bgp.tools/asns.csv"

CACHE_COLL = "bgp_lookup_cache"
CACHE_TTL = timedelta(days=30)
MISS_TTL = timedelta(hours=6)

# One connection at a time, at most 2/s.
_MIN_INTERVAL_S = 0.5
_LAST_CALL = [0.0]
_SESSION_LOCK = asyncio.Lock()

ERR_NAMES = {"ERR_AS_NAME_NOT_FOUND", "ERR_ASN_NOT_FOUND", "<nil>", ""}


# --------------------------------------------------------------------------
# parsing
# --------------------------------------------------------------------------

def _parse_row(line: str) -> Optional[dict]:
    """Parse one whois output row.

    ``212238 | 138.199.35.207 | 138.199.35.0/24 | GB | RIPE | 2020-12-02 | Datacamp Limited``

    The AS name is the last column and is the only free-form one (it can
    contain spaces, commas and parentheses), so the row is split at most six
    times and the remainder is kept whole.
    """
    parts = line.split("|", 6)
    if len(parts) < 7:
        return None
    asn_s, ip, pfx, cc, registry, allocated, name = (p.strip() for p in parts)
    if not asn_s.isdigit():
        return None
    asn = int(asn_s)
    name = name.strip()
    if name in ERR_NAMES:
        name = ""
    return {
        "asn": asn if asn > 0 else None,
        "name": name or None,
        "ip": ip if ip and ip != "<nil>" else None,
        "prefix": pfx if pfx and pfx != "<nil>" else None,
        "cc": (cc.upper() if cc and len(cc) == 2 else None),
        "registry": registry or None,
        "allocated": (allocated if allocated and allocated != "0001-01-01" else None),
    }


def parse_whois(text: str, items: list[str]) -> dict:
    """Turn a whois answer into ``{item: row}``.

    The service answers one row per input, in input order (verified on
    production). Positional mapping is used, but only when the row counts
    agree - a mismatched answer is reported as unresolved rather than
    silently attached to the wrong IP, which would mislabel an AS in a
    report an operator then acts on.
    """
    rows: list[Optional[dict]] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("Vendor:"):
            continue
        row = _parse_row(line)
        if row is not None:
            rows.append(row)
    out: dict = {}
    if len(rows) == len(items):
        for item, row in zip(items, rows):
            out[item.lower()] = row
        return out
    # Row count disagreement: fall back to matching on the echoed IP/ASN
    # column, and leave anything unmatched absent.
    by_ip = {r["ip"]: r for r in rows if r and r.get("ip")}
    for item in items:
        row = by_ip.get(item)
        if row:
            out[item.lower()] = row
    if len(out) != len(items):
        log.warning("[bgp.tools] answer/request row mismatch: %d items, %d rows, %d matched",
                    len(items), len(rows), len(out))
    return out


# --------------------------------------------------------------------------
# whois transport
# --------------------------------------------------------------------------

def whois_bulk_blocking(items: Iterable[str], timeout: float = READ_TIMEOUT_S) -> dict:
    """Blocking bulk lookup. Call through ``run_in_executor``."""
    items = [str(i).strip() for i in items if str(i).strip()]
    if not items:
        return {}
    items = items[:MAX_BATCH]
    payload = "\n".join(["begin"] + items + ["end"]) + "\n"
    buf = bytearray()
    sock = None
    try:
        sock = socket.create_connection((WHOIS_HOST, WHOIS_PORT), timeout=CONNECT_TIMEOUT_S)
        sock.settimeout(timeout)
        sock.sendall(payload.encode("ascii", "ignore"))
        # The server closes after `end`; read until EOF or the runaway guard.
        while len(buf) < MAX_BYTES:
            chunk = sock.recv(65536)
            if not chunk:
                break
            buf.extend(chunk)
    except (OSError, socket.timeout) as exc:
        log.warning("[bgp.tools] whois session failed: %s", exc)
        return {}
    finally:
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass
    return parse_whois(buf.decode("utf-8", "replace"), items)


async def _throttle() -> None:
    gap = time.monotonic() - _LAST_CALL[0]
    if gap < _MIN_INTERVAL_S:
        await asyncio.sleep(_MIN_INTERVAL_S - gap)
    _LAST_CALL[0] = time.monotonic()


# --------------------------------------------------------------------------
# HTTP backstop for AS names
# --------------------------------------------------------------------------

def _asn_names_http_blocking(wanted: set, timeout: float = 15.0) -> dict:
    """Stream ``asns.csv`` and keep only the ASNs in ``wanted``.

    Used only when whois returns an ASN with no name. The file is ~15 MB and
    covers every ASN on the internet; the portal needs a handful, so it is
    read line by line and abandoned as soon as every wanted ASN is found.
    """
    if not wanted:
        return {}
    found: dict = {}
    want = {int(a) for a in wanted if a}
    try:
        req = urllib.request.Request(ASNS_CSV_URL, headers={"User-Agent": HTTP_UA})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            for raw in resp:
                line = raw.decode("utf-8", "replace").strip()
                if not line or line.startswith("asn,"):
                    continue
                head, _, tail = line.partition(",")
                if not head.upper().startswith("AS"):
                    continue
                try:
                    asn = int(head[2:])
                except ValueError:
                    continue
                if asn in want:
                    # name,class,cc - the name may be quoted and contain commas
                    rest = tail.strip()
                    if rest.startswith('"'):
                        end = rest.find('"', 1)
                        name = rest[1:end] if end > 0 else rest.strip('"')
                        after = rest[end + 1:] if end > 0 else ""
                    else:
                        name, _, after = rest.partition(",")
                    kos = [p.strip() for p in after.split(",") if p.strip()]
                    found[asn] = {
                        "name": name.strip() or None,
                        "class": kos[0] if kos else None,
                        "cc": (kos[1].upper() if len(kos) > 1 and len(kos[1]) == 2 else None),
                    }
                    if len(found) >= len(want):
                        break
    except Exception as exc:  # noqa: BLE001 - naming is cosmetic, never fatal
        log.warning("[bgp.tools] asns.csv backstop failed: %s", exc)
    return found


# --------------------------------------------------------------------------
# cache
# --------------------------------------------------------------------------

def _cache_id(kind: str, value: str) -> str:
    return f"{kind}:{value}"


def _p24(value: str) -> Optional[str]:
    """Normalise an address or prefix to its /24 (or /48) key.

    Local copy rather than an import of ``netflow_report.prefix24_of``: this
    module must stay importable on its own, and the two must agree on the key
    anyway because the cache is shared between them.
    """
    if not value:
        return None
    try:
        if "/" in value:
            net = ipaddress.ip_network(value, strict=False)
            bits = 24 if net.version == 4 else 48
            return str(ipaddress.ip_network(f"{net.network_address}/{bits}", strict=False))
        addr = ipaddress.ip_address(value)
        bits = 24 if addr.version == 4 else 48
        return str(ipaddress.ip_network(f"{addr}/{bits}", strict=False))
    except ValueError:
        return None


async def _ensure_index(db) -> None:
    global _INDEX_OK
    if _INDEX_OK:
        return
    try:
        # TTL is enforced on `at`; without it the cache is a slow leak, with
        # it a stale ASN silently expires instead of being trusted forever.
        await db[CACHE_COLL].create_index("at", expireAfterSeconds=int(CACHE_TTL.total_seconds()))
        _INDEX_OK = True
    except Exception:  # noqa: BLE001
        pass


_INDEX_OK = False


async def lookup_many(db, items: Iterable[str], *, kind: str = "ip",
                      refresh_missing: bool = True) -> dict:
    """Return ``{item: row}`` for every item, using the cache when possible.

    ``kind`` is ``"ip"`` (a literal address - the cache key is the /24 the
    address lives in, because an entire /24 is nearly always one ASN and the
    report groups by /24 anyway) or ``"asn"``.

    Unknown items are answered with ``{"asn": None, "error": "unresolved"}``
    rather than omitted: a caller must be able to tell "we looked and bgp.tools
    had nothing" apart from "we never looked", otherwise an AS column full of
    blanks looks like a bug instead of a fact.
    """
    items_l = [str(i).strip() for i in items if str(i).strip()]
    if not items_l:
        return {}
    await _ensure_index(db)

    # A prefix shares a /24 with any address inside it, so expanding the batch
    # to one probe address per distinct /24 costs nothing and removes the join
    # problem entirely.
    keys = {}
    probes = {}

    def _key_of(item: str) -> str:
        return _p24(item) or item

    for it in items_l:
        if kind == "ip":
            # `_p24` is the parse test as well as the normaliser: it returns
            # None for anything that is not an address or a prefix, which is
            # how `not-an-ip` gets excluded here. `_key_of` cannot be used for
            # that check because it falls back to the raw string.
            kof = _p24(it)
            if kof:
                keys[it] = _cache_id("net", kof)
                probes[kof] = kof.split("/")[0]
            else:
                # Not an address or a prefix. Caching this would store a
                # negative under a key the caller will never ask for again
                # (`not-an-ip` was found in the production cache), so it is
                # answered as unparseable instead of being persisted.
                continue
        else:
            keys[it] = _cache_id("asn", it.lower().lstrip("as").lstrip("AS"))
            probes[it] = f"as{str(it).lower().lstrip('as')}"

    found = {it: None for it in items_l}
    ids = list({v for v in keys.values()})
    try:
        docs = await db[CACHE_COLL].find({"_id": {"$in": ids}}).to_list(len(ids) + 1)
    except Exception:  # noqa: BLE001
        docs = []
    by_id = {d["_id"]: d for d in docs}
    now = datetime.now(timezone.utc)
    missing: list[str] = []
    for it in items_l:
        if it not in keys:
            continue   # unparseable, answered as None above
        doc = by_id.get(keys[it])
        if doc:
            # Cache documents written before this fix carry a naive `at`;
            # treat it as UTC rather than letting the subtraction raise and
            # turn a cache hit into a fresh network call.
            at = doc.get("at")
            if isinstance(at, datetime) and at.tzinfo is None:
                at = at.replace(tzinfo=timezone.utc)
            age = now - (at if isinstance(at, datetime) else now)
            ttl = MISS_TTL if not doc.get("asn") else CACHE_TTL
            if age <= ttl:
                found[it] = {k: v for k, v in doc.items() if k not in ("_id", "at")}
                continue
        missing.append(it)

    if missing and refresh_missing:
        async with _SESSION_LOCK:
            await _throttle()
            loop = asyncio.get_running_loop()
            answered = True
            if kind == "ip":
                # Probe one address per distinct /24 and map every answer back
                # through the /24 key. One connection, no duplicate inputs.
                ask = list(dict.fromkeys(probes[_key_of(it)] for it in missing))
                rows = await loop.run_in_executor(None, whois_bulk_blocking, ask)
                # {} means the session never delivered; fewer rows than asked
                # means it dropped some. Either way the answers are partial, so
                # nothing from this call may be cached as a fact.
                answered = len(rows) >= len(ask)
                by_key = {}
                for it in missing:
                    probe = probes[_key_of(it)]
                    row = rows.get(probe.lower())
                    if row is None:
                        # Fall back to the echoed IP when the service dropped
                        # rows: it echoes the address it actually answered
                        # about, which for a /24 probe IS the key.
                        for r in rows.values():
                            if r and r.get("ip") and _p24(r["ip"]) == _key_of(it):
                                row = r
                                break
                    by_key[it] = row
                resolved = by_key
            else:
                asked = {it: probes[_key_of(it)] for it in missing}
                rows = await loop.run_in_executor(None, whois_bulk_blocking, list(asked.values()))
                answered = len(rows) >= len(set(asked.values()))
                resolved = {it: rows.get(asked[it].lower()) for it in missing}

            # AS name backstop: whois answered with an ASN but no name.
            nameless = {r["asn"] for r in resolved.values() if r and r.get("asn") and not r.get("name")}
            if nameless:
                names = await loop.run_in_executor(None, _asn_names_http_blocking, nameless)
                for r in resolved.values():
                    if r and r.get("asn") and not r.get("name") and r["asn"] in names:
                        r["name"] = names[r["asn"]].get("name")
                        r["cc"] = r.get("cc") or names[r["asn"]].get("cc")

        writes = []
        for it, row in resolved.items():
            if it not in keys:
                continue
            if row:
                payload = {
                    "asn": row.get("asn"),
                    "name": row.get("name"),
                    "prefix": row.get("prefix"),
                    "cc": row.get("cc"),
                    "registry": row.get("registry"),
                    "allocated": row.get("allocated"),
                    "source": "bgp.tools",
                    "at": now,
                }
            else:
                # A negative is a claim about the internet, so it is only
                # recorded when the service actually answered the request.
                # `whois_bulk_blocking` returns {} on a transport failure, and
                # a batch where bgp.tools silently dropped rows used to be
                # indistinguishable from "no such network" - which cached a
                # false negative for 6 hours. Measured on production
                # 2026-11-24: 185.199.109.0/24 (Fastly) and 104.16.5.0/24
                # (Cloudflare) were stored as unresolved while resolving fine
                # on the next call, and the report showed them as "AS tidak
                # dikenal" traffic. Now a caller that got no answer at all
                # stores nothing, so the next tick simply asks again.
                if not answered:
                    found[it] = {"asn": None, "error": "no-answer", "at": now}
                    continue
                payload = {"asn": None, "name": None, "prefix": None, "cc": None,
                           "source": "bgp.tools", "at": now, "error": "unresolved"}
            found[it] = payload
            writes.append((keys[it], payload))
        if writes:
            try:
                from pymongo import ReplaceOne
                await db[CACHE_COLL].bulk_write(
                    [ReplaceOne({"_id": cid}, {"_id": cid, **payload}, upsert=True)
                     for cid, payload in writes],
                    ordered=False,
                )
            except Exception as exc:  # noqa: BLE001 - a cache miss is not an error
                log.warning("[bgp.tools] cache write failed: %s", exc)
    return found


def _cache_asn_of(row: Optional[dict]) -> Optional[int]:
    return (row or {}).get("asn")
