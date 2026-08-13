"""SNMP/MRTG-style graph definitions, collection, and sweep.

Graph definitions live in ``monitoring_graphs`` (Mongo).  Raw time-series
samples go to ``monitoring_graph_samples_raw`` (TTL 7d).  Downsampled
rollups go to ``_hourly`` (TTL 90d) and ``_daily`` (TTL 2y).

The module is intentionally self-contained: every function receives ``db``
as a parameter, mirroring ``monitoring.py`` / ``emails.py`` conventions.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from bson import ObjectId

from portal.monitoring import validate_target, resolve_ip

logger = logging.getLogger("portal.monitoring_graphs")

_MIN_INTERVAL = 20
_MAX_INTERVAL = 3600

# Graph types that represent a counter (monotonic increasing octet counter)
# and therefore need rate (delta / elapsed) conversion to produce a bps value.
COUNTER_GRAPH_TYPES = {"snmp_traffic_in", "snmp_traffic_out"}
# Graph types that are already a rate in their own unit (no delta needed).
RATE_GRAPH_TYPES = {"snmp_cpu", "snmp_memory", "snmp_disk", "snmp_uptime", "ping"}


# ---------------------------------------------------------------------------
# Target / field cleaners (reused from routes.monitoring pattern)
# ---------------------------------------------------------------------------
def _clean_graph_name(value) -> str:
    name = str(value or "").strip()
    if not name or len(name) > 120:
        raise ValueError("name is required and must be at most 120 characters")
    return name


def _clean_graph_target(value) -> str:
    target = str(value or "").strip()
    if not target or len(target) > 253:
        raise ValueError("target is required and must be at most 253 characters")
    validated = validate_target(target)
    validate_target(resolve_ip(validated))
    return validated


def _clean_graph_interval(value) -> int:
    try:
        interval = int(value if value is not None else 300)
    except (TypeError, ValueError):
        raise ValueError("interval_seconds must be an integer")
    if not _MIN_INTERVAL <= interval <= _MAX_INTERVAL:
        raise ValueError(f"interval_seconds must be between {_MIN_INTERVAL} and {_MAX_INTERVAL}")
    return interval


def _clean_oid(value) -> str:
    oid = str(value or "").strip()
    if not oid:
        raise ValueError("snmp_oid is required for SNMP graph types")
    if len(oid) > 256:
        raise ValueError("snmp_oid must be at most 256 characters")
    return oid


def _clean_community(value) -> str:
    community = str(value or "public").strip()
    if len(community) > 64:
        raise ValueError("snmp_community must be at most 64 characters")
    return community


VALID_VISIBLE_ROLES = {"admin", "owner", "sales", "finance", "support", "ticket_only", "creative"}

def _clean_visible_roles(value) -> list[str]:
    """Validate and normalize visible_roles list."""
    if not value:
        return ["admin", "support"]
    if isinstance(value, str):
        roles = [r.strip() for r in value.split(",") if r.strip()]
    elif isinstance(value, list):
        roles = [str(r).strip() for r in value if str(r).strip()]
    else:
        return ["admin", "support"]
    # Filter to valid roles
    roles = [r for r in roles if r in VALID_VISIBLE_ROLES]
    if not roles:
        return ["admin", "support"]
    return roles


# ---------------------------------------------------------------------------
# SNMP polling
# ---------------------------------------------------------------------------
async def poll_snmp(target: str, oid: str, community: str = "public",
                    timeout: float = 3.0, port: int = 161,
                    version: str = "2c",
                    user: str = "", auth_protocol: str = "", auth_key: str = "",
                    priv_protocol: str = "", priv_key: str = "") -> dict:
    """Poll a single SNMP OID via subprocess snmpget.

    Supports SNMPv2c (community) and SNMPv3 (user + auth/priv).
    Returns {value, raw, error}.  Falls back gracefully if snmpget is not
    installed.
    """
    base = ["snmpget", "-t", str(timeout), f"{target}:{port}", oid]

    if version == "3":
        args = base.copy()
        args[1:1] = ["-v3"]
        if user:
            args[1:1] = ["-u", user]
        if auth_protocol and auth_key:
            args[1:1] = ["-l", "authPriv" if priv_protocol and priv_key else "authNoPriv",
                         "-a", auth_protocol, "-A", auth_key]
        if priv_protocol and priv_key:
            args[1:1] = ["-x", priv_protocol, "-X", priv_key]
    else:
        args = base.copy()
        args[1:1] = ["-v2c", "-c", community]

    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=timeout + 2
        )
        raw = stdout.decode("utf-8", "replace").strip()
        err = stderr.decode("utf-8", "replace").strip()
        if proc.returncode != 0:
            return {"value": None, "raw": raw, "error": err or "snmpget failed"}
        # Parse "OID = TYPE: VALUE" format
        value = None
        if "=" in raw:
            parts = raw.split("=", 1)
            if ":" in parts[1]:
                value = parts[1].split(":", 1)[1].strip()
            else:
                value = parts[1].strip()
            try:
                value = float(value)
            except (ValueError, TypeError):
                pass
        return {"value": value, "raw": raw, "error": None}
    except FileNotFoundError:
        return {"value": None, "raw": "", "error": "snmpget not installed"}
    except asyncio.TimeoutError:
        return {"value": None, "raw": "", "error": "SNMP timeout"}
    except Exception as exc:
        return {"value": None, "raw": "", "error": str(exc)}


# ---------------------------------------------------------------------------
# SNMP discovery (auto-scan available sensors on a host)
# ---------------------------------------------------------------------------
# Standard MIB locations used to enumerate what a device exposes so NOC does
# not have to type OIDs by hand.  Interface discovery walks IF-MIB to read
# real interface names and pairs them with 64-bit HC octet counters.
_IF_DESCR_OID = "1.3.6.1.2.1.2.2.1.2"       # ifDescr   (walk -> ifIndex)
_IF_NAME_OID = "1.3.6.1.2.1.31.1.1.1.1"      # ifName    (walk -> ifIndex)
_IF_ALIAS_OID = "1.3.6.1.2.1.31.1.1.1.18"    # ifAlias   (walk -> ifIndex)
_IF_OPER_OID = "1.3.6.1.2.1.2.2.1.8"         # ifOperStatus (walk -> ifIndex)
_IF_HC_IN_OID = "1.3.6.1.2.1.31.1.1.1.6"     # ifHCInOctets  (64-bit, walk -> ifIndex)
_IF_HC_OUT_OID = "1.3.6.1.2.1.31.1.1.1.10"   # ifHCOutOctets (64-bit, walk -> ifIndex)
_IF_IN_OID = "1.3.6.1.2.1.2.2.1.10"          # ifInOctets   (32-bit fallback)
_IF_OUT_OID = "1.3.6.1.2.1.2.2.1.16"         # ifOutOctets  (32-bit fallback)


# System scalar sensors (not per-interface).
# Use HOST-RESOURCES-MIB (HR-MIB) OIDs which are standard and supported by
# MikroTik RouterOS, not UCD-SNMP-MIB (Linux-only net-snmp) OIDs.
_SYSTEM_SENSORS = {
    "cpu_load": {
        # hrProcessorLoad (percentage per core). We average across all cores
        # in the frontend. Multiple instances returned; use first available.
        "oid": "1.3.6.1.2.1.25.3.3.1.2",  # HR-MIB hrProcessorLoad
        "label": "CPU Load (per core, %)",
        "unit": "%",
        "kind": "snmp_cpu",
    },
    "memory_used": {
        # hrStorageUsed for main memory (index 65536). Memory % computed as
        # used/total * 100. Total is hrStorageSize at same index.
        "oid": "1.3.6.1.2.1.25.2.3.1.6.65536",  # HR-MIB hrStorageUsed (KB)
        "label": "Memory Used",
        "unit": "KB",
        "kind": "snmp_memory",
    },
    "memory_total": {
        "oid": "1.3.6.1.2.1.25.2.3.1.5.65536",  # HR-MIB hrStorageSize (KB)
        "label": "Memory Total",
        "unit": "KB",
        "kind": "snmp_memory",
    },
    "system_uptime": {
        "oid": "1.3.6.1.2.1.1.3.0",          # sysUpTime (standard SNMPv2-MIB)
        "label": "System Uptime",
        "unit": "seconds",
        "kind": "snmp_uptime",
    },
}


def _build_discovery_cmd(target, base_oid, community, port, version,
                         user, auth_protocol, auth_key, priv_protocol, priv_key,
                         timeout):
    """Build an snmpwalk command list for a base OID."""
    cmd = ["snmpwalk", "-t", str(timeout), "-r", "0", "-On", f"{target}:{port}", base_oid]
    if version == "3":
        cmd.append("-v3")
        if user:
            cmd += ["-u", user]
        if auth_protocol and auth_key:
            cmd += ["-l", "authPriv" if priv_protocol and priv_key else "authNoPriv",
                    "-a", auth_protocol, "-A", auth_key]
        if priv_protocol and priv_key:
            cmd += ["-x", priv_protocol, "-X", priv_key]
    else:
        cmd += ["-v2c", "-c", community]
    return cmd


def _parse_walk_line(line: str):
    """Parse one snmpwalk output line into (oid, value).

    Handles both ``OID = TYPE: VALUE`` and ``OID = VALUE`` forms, plus
    numeric string values.
    """
    line = line.strip()
    if not line or "=" not in line:
        return None, None
    oid_part, _, rest = line.partition("=")
    oid = oid_part.strip()
    rest = rest.strip()
    value = rest
    if ":" in rest:
        # "TYPE: VALUE" — drop the type token
        _type, _, value = rest.partition(":")
        value = value.strip()
    return oid, value


async def _walk_oid(target, base_oid, community, port, version,
                    user, auth_protocol, auth_key, priv_protocol, priv_key,
                    timeout) -> dict:
    """Run snmpwalk against a base OID and return {oid: value} map.

    Returns {} (empty) when the subtree is absent or times out — treated as
    "device doesn't expose this" rather than a fatal error.
    """
    cmd = _build_discovery_cmd(
        target, base_oid, community, port, version,
        user, auth_protocol, auth_key, priv_protocol, priv_key, timeout,
    )
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout + 2)
        lines = stdout.decode("utf-8", "replace").splitlines()
        stderr_text = stderr.decode("utf-8", "replace").strip()
        if proc.returncode != 0 and not lines:
            # Empty subtree or timeout — not an error for a category the
            # device doesn't expose.
            return {}
        result = {}
        for line in lines:
            oid, value = _parse_walk_line(line)
            if oid:
                result[oid] = value
        return result
    except FileNotFoundError:
        raise
    except asyncio.TimeoutError:
        return {}
    except Exception:
        return {}


def _if_index_from_oid(oid: str) -> str:
    """Extract the ifIndex (final numeric suffix) from an interface OID."""
    return oid.rsplit(".", 1)[-1]


def _parse_counter(value) -> Optional[float]:
    """Parse an octet counter value to float. Returns None if not numeric."""
    if value is None:
        return None
    try:
        return float(str(value).strip())
    except (ValueError, TypeError):
        return None


def _serialize_interface_sensor(name, descr, alias, oper, index, in_oid, out_oid, direction):
    """Build a discovery sensor dict for one interface direction."""
    label = name or descr or f"if{index}"
    if alias and alias != label:
        label = f"{label} ({alias})"
    oid = in_oid if direction == "in" else out_oid
    return {
        "oid": oid,
        "label": label,
        "unit": "bps",
        "kind": "snmp_traffic_in" if direction == "in" else "snmp_traffic_out",
        "value": None,
        "category": "interface",
        "interface_index": index,
        "interface_name": name or "",
        "interface_descr": descr or "",
        "interface_alias": alias or "",
        "interface_status": oper or "unknown",
        "direction": direction,
    }


async def discover_snmp_sensors(target: str, community: str = "public",
                                port: int = 161, version: str = "2c",
                                user: str = "", auth_protocol: str = "",
                                auth_key: str = "", priv_protocol: str = "",
                                priv_key: str = "", timeout: float = 4.0) -> dict:
    """Auto-scan a host for available SNMP sensors.

    Returns a structured list of discovered sensors grouped by category:

    - ``interfaces``: real interface names (ifName/ifDescr) with their
      ifIndex, status, and two counter sensors (in / out) using 64-bit
      HC octet counters when available.
    - ``system``: CPU load, memory, uptime scalars.

    Returns {"ok": bool, "sensors": [...], "error": str|None, "target": ...}.
    """
    sensors = []
    errors = []

    # ---- Interface discovery: read ifName/ifDescr/ifAlias/ifOperStatus +
    # ---- HC counters, grouped by ifIndex.
    try:
        names = await _walk_oid(target, _IF_NAME_OID, community, port, version,
                                user, auth_protocol, auth_key, priv_protocol, priv_key, timeout)
        descrs = await _walk_oid(target, _IF_DESCR_OID, community, port, version,
                                 user, auth_protocol, auth_key, priv_protocol, priv_key, timeout)
        aliases = await _walk_oid(target, _IF_ALIAS_OID, community, port, version,
                                  user, auth_protocol, auth_key, priv_protocol, priv_key, timeout)
        opers = await _walk_oid(target, _IF_OPER_OID, community, port, version,
                                user, auth_protocol, auth_key, priv_protocol, priv_key, timeout)
        hc_in = await _walk_oid(target, _IF_HC_IN_OID, community, port, version,
                                user, auth_protocol, auth_key, priv_protocol, priv_key, timeout)
        hc_out = await _walk_oid(target, _IF_HC_OUT_OID, community, port, version,
                                 user, auth_protocol, auth_key, priv_protocol, priv_key, timeout)
        # 32-bit fallback counters
        in32 = await _walk_oid(target, _IF_IN_OID, community, port, version,
                               user, auth_protocol, auth_key, priv_protocol, priv_key, timeout)
        out32 = await _walk_oid(target, _IF_OUT_OID, community, port, version,
                                user, auth_protocol, auth_key, priv_protocol, priv_key, timeout)

        # Collect all ifIndexes seen across name/descr/counter tables.
        indexes = set()
        for table in (names, descrs, aliases, opers, hc_in, hc_out, in32, out32):
            for oid in table:
                indexes.add(_if_index_from_oid(oid))

        for idx in sorted(indexes, key=lambda x: (len(x), x)):
            # Prefer 64-bit HC counters; fall back to 32-bit.
            in_oid = next((o for o in hc_in if _if_index_from_oid(o) == idx), None)
            out_oid = next((o for o in hc_out if _if_index_from_oid(o) == idx), None)
            if not in_oid:
                in_oid = next((o for o in in32 if _if_index_from_oid(o) == idx), None)
            if not out_oid:
                out_oid = next((o for o in out32 if _if_index_from_oid(o) == idx), None)
            if not in_oid and not out_oid:
                # No counters — not a usable traffic interface.
                continue

            name = next((v for o, v in names.items() if _if_index_from_oid(o) == idx), "")
            descr = next((v for o, v in descrs.items() if _if_index_from_oid(o) == idx), "")
            alias = next((v for o, v in aliases.items() if _if_index_from_oid(o) == idx), "")
            oper = next((v for o, v in opers.items() if _if_index_from_oid(o) == idx), "unknown")

            if in_oid:
                sensors.append(_serialize_interface_sensor(
                    name, descr, alias, oper, idx, in_oid, out_oid, "in"))
            if out_oid:
                sensors.append(_serialize_interface_sensor(
                    name, descr, alias, oper, idx, in_oid, out_oid, "out"))

        if not indexes:
            errors.append("interfaces: no IF-MIB data")
    except FileNotFoundError:
        return {"ok": False, "sensors": [], "error": "snmpwalk not installed",
                "target": target}
    except asyncio.TimeoutError:
        errors.append("interfaces: timeout")
    except Exception as exc:
        errors.append(f"interfaces: {exc}")

    # ---- System scalar sensors.
    for key, base in _SYSTEM_SENSORS.items():
        try:
            values = await _walk_oid(target, base["oid"], community, port, version,
                                     user, auth_protocol, auth_key, priv_protocol, priv_key, timeout)
            # A walk base such as hrProcessorLoad returns one row per core.
            # Suffix the label with the instance index so the operator can tell
            # them apart in the discovery list instead of seeing N identical rows.
            multi = len(values) > 1
            for oid, value in values.items():
                label = base["label"]
                if multi:
                    label = f"{label} #{oid.rsplit('.', 1)[-1]}"
                sensors.append({
                    "oid": oid,
                    "label": label,
                    "unit": base["unit"],
                    "kind": base["kind"],
                    "value": value,
                    "category": "system",
                })
        except FileNotFoundError:
            return {"ok": False, "sensors": [], "error": "snmpwalk not installed",
                    "target": target}
        except asyncio.TimeoutError:
            errors.append(f"{key}: timeout")
        except Exception as exc:
            errors.append(f"{key}: {exc}")

    # If we found nothing at all, the host likely does not respond to SNMP
    # with the given community/version. Report it so NOC can adjust.
    if not sensors:
        err = errors[0] if errors else "no SNMP response (check community/version/port)"
        return {"ok": False, "sensors": [], "error": err, "target": target}

    return {"ok": True, "sensors": sensors, "error": None, "target": target}


# ---------------------------------------------------------------------------
# Counter rate engine
# ---------------------------------------------------------------------------
# Store last counter state per graph so we can compute a rate (delta/elapsed)
# for counter-based graph types (traffic).  This mirrors how Cacti/PRTG turn
# a monotonically increasing octet counter into a bits-per-second line.
async def _load_last_counter(db, graph_id: str) -> Optional[dict]:
    """Return the most recent raw sample for a graph, or None."""
    return await db.monitoring_graph_samples_raw.find_one(
        {"graph_id": graph_id}, sort=[("at", -1)]
    )


def _compute_rate(current: float, prev: Optional[dict], now: datetime,
                  prev_at_fn=None) -> Optional[float]:
    """Compute a bits-per-second rate from two octet counter snapshots.

    Returns None when a rate cannot be computed (first poll, counter reset,
    reboot, or non-positive elapsed time) so the caller can skip storing a
    bogus sample instead of drawing a huge spike.
    """
    if prev is None:
        return None
    prev_value = prev.get("value")
    raw_counter = prev.get("raw_counter", prev_value)
    prev_at = prev.get("at")
    if raw_counter is None or prev_at is None:
        return None
    # Traffic samples store the rendered bps value in ``value`` and preserve
    # the device's monotonic octet counter separately.  Fall back to legacy
    # ``value`` only for historical baseline samples created before this field.
    try:
        prev_counter = float(raw_counter)
    except (ValueError, TypeError):
        return None

    # Normalize timestamps.
    if isinstance(prev_at, datetime):
        if prev_at.tzinfo is None:
            prev_at = prev_at.replace(tzinfo=timezone.utc)
    else:
        try:
            prev_at = datetime.fromisoformat(str(prev_at).replace("Z", "+00:00"))
        except ValueError:
            return None
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    elapsed = (now - prev_at).total_seconds()
    if elapsed <= 0:
        return None

    delta = current - prev_counter
    # Counter reset / reboot / wrap: delta negative or implausibly large.
    # A 64-bit counter wrapping is astronomically rare; a large positive delta
    # usually means the device rebooted between polls.  Guard against both.
    if delta < 0:
        # 64-bit wrap or counter reset — treat as no valid rate this poll.
        return None
    if delta > (2 ** 63):  # impossible for a real 64-bit counter delta
        return None

    # octets/sec * 8 = bits/sec
    return (delta * 8.0) / elapsed


# ---------------------------------------------------------------------------
# Graph sweep (mirrors run_monitoring_probe_sweep)
# ---------------------------------------------------------------------------
async def probe_graph(db, *, graph: dict, owner: str,
                      timeout: float = 3.0) -> dict:
    """Poll a single graph and store the sample.

    For counter-based graph types (snmp_traffic_in/out), computes a
    bits-per-second rate from the previous counter and stores that, so the
    chart shows throughput rather than a raw octet counter.
    """
    graph_id = str(graph["_id"])
    g_type = graph.get("type", "snmp_traffic")
    target = str(graph.get("target") or "").strip()

    if g_type == "ping":
        from portal.diagnostics import run_ping
        probe_ip = resolve_ip(validate_target(target))
        validate_target(probe_ip)
        result = await run_ping(probe_ip, count=3, timeout=timeout)
        summary = (result or {}).get("summary") or {}
        value = float(summary.get("avg_ms") or 0)
        now = datetime.now(timezone.utc)
        sample = {"graph_id": graph_id, "at": now, "value": value, "raw": ""}
        await db.monitoring_graph_samples_raw.insert_one(sample)
        return {"probed": True, "value": value}

    # SNMP-based graph
    oid = str(graph.get("snmp_oid") or "").strip()
    community = str(graph.get("snmp_community") or "public").strip()
    port = int(graph.get("snmp_port") or 161)
    version = str(graph.get("snmp_version") or "2c").strip()
    snmp_result = await poll_snmp(
        target, oid, community,
        timeout=timeout, port=port,
        version=version,
        user=str(graph.get("snmp_user") or ""),
        auth_protocol=str(graph.get("snmp_auth_protocol") or ""),
        auth_key=str(graph.get("snmp_auth_key") or ""),
        priv_protocol=str(graph.get("snmp_priv_protocol") or ""),
        priv_key=str(graph.get("snmp_priv_key") or ""),
    )
    if snmp_result.get("error"):
        logger.warning("[graphs] SNMP poll failed for %s: %s", graph_id, snmp_result["error"])
        return {"skipped": True, "error": snmp_result["error"]}
    value = snmp_result.get("value")
    if value is None:
        return {"skipped": True, "error": "no value"}
    try:
        value = float(value)
    except (ValueError, TypeError):
        return {"skipped": True, "error": f"non-numeric value: {value}"}

    now = datetime.now(timezone.utc)

    # For counter-based traffic types, convert the raw octet counter into a
    # bits-per-second rate using the previous sample.  If no rate can be
    # computed (first poll / reboot / reset), skip storing a bogus spike.
    if g_type in COUNTER_GRAPH_TYPES:
        prev = await _load_last_counter(db, graph_id)
        rate = _compute_rate(value, prev, now)
        if rate is None:
            # Store the counter baseline only so the next poll has a reference.
            await db.monitoring_graph_samples_raw.insert_one(
                {"graph_id": graph_id, "at": now, "value": None, "raw": "baseline", "raw_counter": value})
            return {"probed": True, "value": value, "baseline": True}
        value = rate

    sample = {
        "graph_id": graph_id,
        "at": now,
        "value": value,
        "raw": snmp_result.get("raw") or "",
    }
    if g_type in COUNTER_GRAPH_TYPES:
        sample["raw_counter"] = snmp_result["value"]
    await db.monitoring_graph_samples_raw.insert_one(sample)
    return {"probed": True, "value": value}


async def run_graph_sweep(db, *, owner: str,
                          now: Optional[datetime] = None,
                          timeout: float = 3.0) -> dict:
    """Poll all due enabled graphs, store samples, return counts.

    Mirrors run_monitoring_probe_sweep: lease per-graph, failure isolation,
    interval-based scheduling.
    """
    from portal.emails import acquire_scheduler_lease, _release_scheduler_lease

    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    graphs = await db.monitoring_graphs.find({"enabled": True}).to_list(500)
    summary = {"checked": len(graphs), "probed": 0, "skipped_not_due": 0, "errors": 0}

    for graph in graphs:
        graph_id = str(graph.get("_id") or "")
        try:
            # Check if due based on last sample time
            last_sample = await db.monitoring_graph_samples_raw.find_one(
                {"graph_id": graph_id}, sort=[("at", -1)]
            )
            interval = max(_MIN_INTERVAL, min(_MAX_INTERVAL, int(graph.get("interval_seconds") or 300)))
            if last_sample:
                last_at = last_sample.get("at")
                if isinstance(last_at, datetime):
                    if last_at.tzinfo is None:
                        last_at = last_at.replace(tzinfo=timezone.utc)
                    if last_at + timedelta(seconds=interval) > now:
                        summary["skipped_not_due"] += 1
                        continue

            # Per-graph lease
            lease_id = f"job:graph:{graph_id}"
            acquired, current_owner = await acquire_scheduler_lease(
                db, lease_id=lease_id, owner=owner, ttl_seconds=300
            )
            if not acquired:
                summary["skipped_not_due"] += 1
                continue

            try:
                result = await probe_graph(db, graph=graph, owner=owner, timeout=timeout)
                if result.get("probed"):
                    summary["probed"] += 1
                elif result.get("skipped"):
                    summary["errors"] += 1
            finally:
                try:
                    await _release_scheduler_lease(db, lease_id=lease_id, owner=owner)
                except Exception:
                    logger.exception("[graphs] release failed for %s", graph_id)

        except Exception:
            summary["errors"] += 1
            logger.exception("[graphs] sweep failed for %s", graph_id)

    return summary


# ---------------------------------------------------------------------------
# Downsampling
# ---------------------------------------------------------------------------
async def run_downsample_sweep(db, *, owner: str) -> dict:
    """Run hourly + daily downsampling for graph samples.

    Called by scheduler hourly. Uses atomic lease.
    """
    from portal.emails import acquire_scheduler_lease, _release_scheduler_lease
    from portal.monitoring_samples import downsample_raw_to_hourly, downsample_hourly_to_daily

    lease_id = "job:graph_downsample"
    acquired, current_owner = await acquire_scheduler_lease(
        db, lease_id=lease_id, owner=owner, ttl_seconds=600
    )
    if not acquired:
        return {"skipped": True, "owner": current_owner}

    try:
        hourly_result = await downsample_raw_to_hourly(db)
        daily_result = await downsample_hourly_to_daily(db)
        return {"hourly": hourly_result, "daily": daily_result}
    finally:
        try:
            await _release_scheduler_lease(db, lease_id=lease_id, owner=owner)
        except Exception:
            logger.exception("[graphs] downsample release failed")


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------
def serialize_graph(doc: dict) -> dict:
    return {
        "id": str(doc["_id"]),
        "name": doc.get("name", ""),
        "target": doc.get("target", ""),
        "type": doc.get("type", "snmp_traffic"),
        "snmp_oid": doc.get("snmp_oid") or "",
        "snmp_community": doc.get("snmp_community") or "",
        "snmp_port": int(doc.get("snmp_port") or 161),
        "snmp_version": doc.get("snmp_version") or "2c",
        "snmp_user": doc.get("snmp_user") or "",
        "snmp_auth_protocol": doc.get("snmp_auth_protocol") or "",
        "snmp_priv_protocol": doc.get("snmp_priv_protocol") or "",
        "interval_seconds": int(doc.get("interval_seconds") or 300),
        "enabled": bool(doc.get("enabled", True)),
        "client_id": str(doc["client_id"]) if doc.get("client_id") else None,
        "unit": doc.get("unit") or "",
        "display_name": doc.get("display_name") or "",
        "visible_roles": doc.get("visible_roles") or ["admin", "support"],
        "created_at": doc.get("created_at"),
        "updated_at": doc.get("updated_at"),
    }
