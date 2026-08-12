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

_MIN_INTERVAL = 30
_MAX_INTERVAL = 3600


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
# Known OID bases for common sensor categories.  These are standard MIB-II /
# HOST-RESOURCES / UCD-SNMP / IF-MIB locations used to enumerate what a device
# exposes so NOC does not have to type OIDs by hand.
_SNMP_DISCOVERY_BASES = {
    "interfaces": {
        "oid": "1.3.6.1.2.1.2.2.1.2",  # ifDescr
        "label": "Interfaces",
        "unit": "bps",
        "kind": "snmp_traffic",
        "walk": True,
    },
    "if_in_octets": {
        "oid": "1.3.6.1.2.1.2.2.1.10",  # ifInOctets
        "label": "Interface In Octets",
        "unit": "bytes",
        "kind": "snmp_traffic",
        "walk": True,
    },
    "if_out_octets": {
        "oid": "1.3.6.1.2.1.2.2.1.16",  # ifOutOctets
        "label": "Interface Out Octets",
        "unit": "bytes",
        "kind": "snmp_traffic",
        "walk": True,
    },
    "cpu_load": {
        "oid": "1.3.6.1.4.1.2021.10.1.3",  # UCD-SNMP-MIB laLoad (1/5/15 min)
        "label": "CPU Load Average",
        "unit": "load",
        "kind": "snmp_cpu",
        "walk": True,
    },
    "memory_used": {
        "oid": "1.3.6.1.4.1.2021.4.5.0",  # UCD-SNMP-MIB memAvailReal (KB free)
        "label": "Memory Available",
        "unit": "KB",
        "kind": "snmp_memory",
        "walk": False,
    },
    "system_uptime": {
        "oid": "1.3.6.1.2.1.1.3.0",  # sysUpTime
        "label": "System Uptime",
        "unit": "seconds",
        "kind": "snmp_uptime",
        "walk": False,
    },
    "hr_storage": {
        "oid": "1.3.6.1.2.1.25.2.3.1.3",  # hrStorageDescr
        "label": "Disk Storage",
        "unit": "%",
        "kind": "snmp_disk",
        "walk": True,
    },
}

# Map discovered OID suffix to a human-readable name / unit for common cases.
# For interface walks, the suffix is the ifIndex.
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


async def discover_snmp_sensors(target: str, community: str = "public",
                                port: int = 161, version: str = "2c",
                                user: str = "", auth_protocol: str = "",
                                auth_key: str = "", priv_protocol: str = "",
                                priv_key: str = "", timeout: float = 4.0) -> dict:
    """Auto-scan a host for available SNMP sensors.

    Runs snmpwalk against a set of well-known base OIDs and returns a list of
    discovered sensors with their OID, human label, unit, and graph kind, so
    NOC can pick a sensor without knowing the OID by hand.

    Returns {"ok": bool, "sensors": [...], "error": str|None, "target": ...}.
    """
    sensors = []
    errors = []

    for key, base in _SNMP_DISCOVERY_BASES.items():
        base_oid = base["oid"]
        try:
            cmd = _build_discovery_cmd(
                target, base_oid, community, port, version,
                user, auth_protocol, auth_key, priv_protocol, priv_key, timeout,
            )
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout + 2)
            lines = stdout.decode("utf-8", "replace").splitlines()
            stderr_text = stderr.decode("utf-8", "replace").strip()

            if proc.returncode != 0 and not lines:
                # snmpwalk returns non-zero when the OID subtree is empty
                # (no such instance). Not an error for a category that isn't
                # present on the device.
                if "Timeout" in stderr_text or "timed out" in stderr_text:
                    errors.append(f"{key}: timeout")
                continue

            if base.get("walk"):
                # Walk: each line is a distinct instance under base_oid
                for line in lines:
                    oid, value = _parse_walk_line(line)
                    if not oid:
                        continue
                    # Derive a short label from the instance suffix
                    suffix = oid.rsplit(".", 1)[-1] if "." in oid else oid
                    label = f"{base['label']} [{suffix}]"
                    sensors.append({
                        "oid": oid,
                        "label": label,
                        "unit": base["unit"],
                        "kind": base["kind"],
                        "value": value,
                        "category": key,
                    })
            else:
                # Single scalar OID
                for line in lines:
                    oid, value = _parse_walk_line(line)
                    if not oid:
                        continue
                    sensors.append({
                        "oid": oid,
                        "label": base["label"],
                        "unit": base["unit"],
                        "kind": base["kind"],
                        "value": value,
                        "category": key,
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
# Graph sweep (mirrors run_monitoring_probe_sweep)
# ---------------------------------------------------------------------------
async def probe_graph(db, *, graph: dict, owner: str,
                      timeout: float = 3.0) -> dict:
    """Poll a single graph and store the sample."""
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
    else:
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
    sample = {
        "graph_id": graph_id,
        "at": now,
        "value": value,
    }
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
