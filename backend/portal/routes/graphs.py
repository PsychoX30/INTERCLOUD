"""Graph CRUD endpoints for admin monitoring.

Admin-only mutations. Admin+support read. Client-scoped read via separate endpoint.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional
import uuid
import socket
import re

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from ..auth import get_current_admin, get_current_user, get_current_staff, require_roles
from ..audit import log_audit
from ..monitoring_graphs import (
    serialize_graph,
    probe_graph,
    run_graph_sweep,
    run_downsample_sweep,
    discover_snmp_sensors,
    _clean_graph_name,
    _clean_graph_target,
    _clean_graph_interval,
    _clean_oid,
    _clean_community,
    _clean_visible_roles,
)
from ..monitoring_samples import (
    get_graph_data,
    ensure_indexes as ensure_sample_indexes,
)
from ..monitoring_reports import graph_export_response
from .. import graph_alerts as ga
from .. import models as m
from .shared import _get_db, _oid, _iso, _now
from bson import ObjectId

router = APIRouter()

VALID_GRAPH_TYPES = {
    "snmp_traffic_in", "snmp_traffic_out", "snmp_cpu",
    "snmp_memory", "snmp_disk", "snmp_uptime", "ping",
}


async def _visible_graph_ids(db, staff: dict) -> Optional[list[str]]:
    """Return every graph id visible to non-admin staff; ``None`` means unrestricted.

    Uses MongoDB ``distinct`` rather than ``to_list(N)`` so row-level
    authorization never silently weakens past an arbitrary page cap.
    """
    if staff.get("role") == "admin":
        return None
    ids = await db.monitoring_graphs.distinct(
        "_id", {"visible_roles": staff.get("role")}
    )
    return [str(graph_id) for graph_id in ids]


async def _require_visible_graph_ids(db, staff: dict, graph_ids: list[str]) -> None:
    """Reject a non-admin mutation that targets a graph outside its scope.

    List filtering alone is insufficient: a caller who knows an object ID must
    not be able to create, edit, or delete a graph-scoped rule/window for a
    hidden graph. Return 404 so the response does not disclose that it exists.
    """
    visible_ids = await _visible_graph_ids(db, staff)
    if visible_ids is None:
        return
    requested = {str(graph_id) for graph_id in graph_ids if graph_id}
    if not requested.issubset(set(visible_ids)):
        raise HTTPException(status_code=404, detail="Monitoring graph not found")


def _rule_graph_ids(d: dict) -> list[str]:
    """Scope of an existing alert rule as a list (single graph or global).

    An empty ``graph_id`` means the rule is *global* — it fires for every
    graph, including admin-only ones — so it scopes to ``[]`` exactly like
    a global maintenance window. Returning ``[""]`` instead would make the
    visibility guard treat the empty string as a visible graph id and let
    support mutate a global rule it cannot even list.
    """
    graph_id = d.get("graph_id")
    return [str(graph_id)] if graph_id else []


def _window_graph_ids(d: dict) -> list[str]:
    """Scope of an existing maintenance window (list of graphs; empty = global)."""
    return [str(graph_id) for graph_id in (d.get("graph_ids") or [])]


async def _require_visible_object(db, staff: dict, existing_graph_ids: list[str]) -> None:
    """Row-level guard: non-admin may not mutate an object scoped to hidden graphs.

    An empty ``existing_graph_ids`` means the stored object is *global* — it
    touches every graph, including admin-only ones — so it must be admin-only
    to mutate as well. Without this, support could hijack a global rule/window
    by ID and silently alter alerting for graphs it cannot even list. As with
    ``_require_visible_graph_ids`` the answer is 404, never a disclosure.
    """
    if staff.get("role") == "admin":
        return
    if not existing_graph_ids:
        raise HTTPException(status_code=404, detail="Monitoring object not found")
    await _require_visible_graph_ids(db, staff, existing_graph_ids)


def _clean_or_400(cleaner, value):
    """Convert validation failures into API client errors, not 500s."""
    try:
        return cleaner(value)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _clean_snmp_port(value) -> int:
    """Validate SNMP port. Defaults to 161, rejects non-integer input."""
    if value is None or value == "":
        return 161
    try:
        port = int(value)
    except (ValueError, TypeError) as exc:
        raise ValueError("snmp_port must be an integer") from exc
    if not 1 <= port <= 65535:
        raise ValueError("snmp_port must be between 1 and 65535")
    return port


# ---------------------------------------------------------------------------
# SNMP discovery (auto-scan available sensors on a host)
# ---------------------------------------------------------------------------
@router.post("/admin/monitoring/discover")
async def discover_sensors(payload: dict, admin=Depends(get_current_admin)):
    """Auto-scan a target for available SNMP sensors via snmpwalk.

    Returns a structured list of discovered sensors:
    - interfaces: real names (ifName/ifDescr) with in/out counter sensors
    - system: CPU, memory, uptime
    Admin only.
    """
    db = await _get_db()
    target = _clean_or_400(_clean_graph_target, payload.get("target"))
    community = _clean_community(payload.get("snmp_community"))
    port = int(payload.get("snmp_port") or 161)
    version = str(payload.get("snmp_version") or "2c").strip()
    result = await discover_snmp_sensors(
        target, community, port=port, version=version,
        user=str(payload.get("snmp_user") or ""),
        auth_protocol=str(payload.get("snmp_auth_protocol") or ""),
        auth_key=str(payload.get("snmp_auth_key") or ""),
        priv_protocol=str(payload.get("snmp_priv_protocol") or ""),
        priv_key=str(payload.get("snmp_priv_key") or ""),
    )
    return result


# ---------------------------------------------------------------------------
# Bulk graph creation (from discovery multi-select)
# ---------------------------------------------------------------------------
@router.post("/admin/monitoring/graphs/bulk")
async def create_graphs_bulk(payload: dict, admin=Depends(get_current_admin)):
    """Create multiple graphs at once from discovery scan selections.

    Accepts a common SNMP config + a list of sensor specs.
    """
    db = await _get_db()
    now = datetime.now(timezone.utc)
    sensors = payload.get("sensors") or []
    if not sensors or not isinstance(sensors, list):
        raise HTTPException(status_code=400, detail="sensors list is required")
    if len(sensors) > 200:
        raise HTTPException(status_code=400, detail="at most 200 sensors may be created at once")

    # Common SNMP config shared across all graphs
    common = {
        "target": _clean_or_400(_clean_graph_target, payload.get("target")),
        "snmp_community": _clean_community(payload.get("snmp_community")),
        "snmp_port": int(payload.get("snmp_port") or 161),
        "snmp_version": str(payload.get("snmp_version") or "2c").strip(),
        "snmp_user": str(payload.get("snmp_user") or ""),
        "snmp_auth_protocol": str(payload.get("snmp_auth_protocol") or ""),
        "snmp_auth_key": str(payload.get("snmp_auth_key") or ""),
        "snmp_priv_protocol": str(payload.get("snmp_priv_protocol") or ""),
        "snmp_priv_key": str(payload.get("snmp_priv_key") or ""),
        "interval_seconds": _clean_or_400(_clean_graph_interval, payload.get("interval_seconds")),
        "enabled": bool(payload.get("enabled", True)),
        "client_id": _oid(payload["client_id"]) if payload.get("client_id") else None,
        "visible_roles": _clean_visible_roles(payload.get("visible_roles")),
        "created_by": str(admin.get("_id") or admin.get("id") or "admin"),
        "created_at": now,
        "updated_at": now,
    }

    created = []
    for i, sensor in enumerate(sensors):
        if not isinstance(sensor, dict):
            continue
        oid = sensor.get("oid")
        if not oid:
            continue
        oid = _clean_or_400(_clean_oid, oid)
        name = _clean_or_400(_clean_graph_name, sensor.get("name") or f"Graph-{i+1}")
        gtype = str(sensor.get("type") or "").strip()
        if gtype not in VALID_GRAPH_TYPES or gtype == "ping":
            raise HTTPException(status_code=400, detail=f"unsupported discovered sensor type: {gtype}")
        unit = str(sensor.get("unit") or "")[:32]
        display_name = str(sensor.get("display_name") or sensor.get("label") or "")[:120]

        doc = {
            **common,
            "name": name,
            "type": gtype,
            "snmp_oid": oid,
            "unit": unit,
            "display_name": display_name,
        }
        # Persist the interface identity so the sweep can re-map the OID if the
        # device renumbers its ifIndex (a MikroTik router reboot/upgrade can
        # move "VLAN 108 - RIVAN" from .9 to .65, which silently kills the
        # graph because the stored OID then returns "No Such Object").
        if sensor.get("interface_name") is not None:
            doc["interface_name"] = str(sensor.get("interface_name") or "")[:120]
        if sensor.get("interface_index") is not None:
            doc["interface_index"] = str(sensor.get("interface_index") or "")[:16]
        # Oper status drives the port chip in the UI. Missing means the caller
        # (older UI build) did not send it; keep it empty rather than guessing.
        if sensor.get("interface_status") is not None:
            doc["interface_status"] = str(sensor.get("interface_status") or "")[:16]
        result = await db.monitoring_graphs.insert_one(doc)
        doc["_id"] = result.inserted_id
        created.append(serialize_graph(doc))

    return {"ok": True, "created": len(created), "graphs": created}


# ---------------------------------------------------------------------------
# Client search endpoint (for client_id dropdown)
# ---------------------------------------------------------------------------
@router.get("/admin/monitoring/clients")
async def search_clients(
    q: str = Query("", max_length=100),
    client_id: Optional[str] = Query(None),
    staff=Depends(require_roles("admin", "support", "sales")),
):
    """Search clients by name, email, or company for graph assignment dropdown.

    Returns minimal fields: id, name, email, company.
    Sales staff only see their assigned clients.
    Pass an exact ``client_id`` to look up a single client (used when editing
    an existing graph to render its assigned client name).
    """
    db = await _get_db()
    role = staff.get("role", "")

    query = {"role": "client"}
    if client_id:
        try:
            exact_oid = ObjectId(client_id)
        except Exception:
            return []
        if role == "sales":
            assigned_oids = []
            for assigned_id in staff.get("assigned_client_ids") or []:
                try:
                    assigned_oids.append(ObjectId(assigned_id))
                except Exception:
                    continue
            if exact_oid not in assigned_oids:
                return []
        query["_id"] = exact_oid
        # exact lookup ignores the q filter
        cursor = db.users.find(query, {"name": 1, "email": 1, "company": 1}).limit(1)
        results = []
        async for u in cursor:
            results.append({
                "id": str(u["_id"]),
                "name": u.get("name", ""),
                "email": u.get("email", ""),
                "company": u.get("company", ""),
            })
        return results

    if role == "sales":
        assigned = staff.get("assigned_client_ids") or []
        if not assigned:
            return []
        assigned_oids = []
        for assigned_id in assigned:
            try:
                assigned_oids.append(ObjectId(assigned_id))
            except Exception:
                continue
        if not assigned_oids:
            return []
        query["_id"] = {"$in": assigned_oids}

    if q:
        q_lower = re.escape(q.strip().lower())
        query["$or"] = [
            {"name": {"$regex": q_lower, "$options": "i"}},
            {"email": {"$regex": q_lower, "$options": "i"}},
            {"company": {"$regex": q_lower, "$options": "i"}},
        ]
    cursor = db.users.find(query, {"name": 1, "email": 1, "company": 1}).limit(25)
    results = []
    async for u in cursor:
        results.append({
            "id": str(u["_id"]),
            "name": u.get("name", ""),
            "email": u.get("email", ""),
            "company": u.get("company", ""),
        })
    return results


# ---------------------------------------------------------------------------
# Admin graph CRUD
# ---------------------------------------------------------------------------
@router.get("/admin/monitoring/graphs")
async def list_graphs(
    enabled: Optional[bool] = None,
    client_id: Optional[str] = None,
    staff=Depends(require_roles("admin", "support")),
):
    db = await _get_db()
    query = {}
    if enabled is not None:
        query["enabled"] = enabled
    if client_id:
        query["client_id"] = _oid(client_id)
    # RBAC: filter by visible_roles for non-admin (support only sees graphs with their role)
    if staff.get("role") != "admin":
        query["visible_roles"] = staff.get("role")
    cursor = db.monitoring_graphs.find(query).sort("created_at", 1)
    docs = await cursor.to_list(500)
    return [serialize_graph(doc) for doc in docs]


@router.post("/admin/monitoring/graphs")
async def create_graph(payload: dict, admin=Depends(get_current_admin)):
    db = await _get_db()
    now = datetime.now(timezone.utc)

    gtype = payload.get("type", "snmp_traffic_in")
    if gtype not in VALID_GRAPH_TYPES:
        raise HTTPException(status_code=400, detail=f"Unsupported graph type: {gtype}")
    doc = {
        "name": _clean_or_400(_clean_graph_name, payload.get("name")),
        "target": _clean_or_400(_clean_graph_target, payload.get("target")),
        "type": gtype,
        # SNMP graph types require a valid OID; ping graphs do not use one.
        "snmp_oid": None if gtype == "ping" else _clean_or_400(_clean_oid, payload.get("snmp_oid")),
        "snmp_community": _clean_community(payload.get("snmp_community")),
        "snmp_port": _clean_or_400(_clean_snmp_port, payload.get("snmp_port")),
        "snmp_version": payload.get("snmp_version", "2c"),
        "interval_seconds": _clean_or_400(_clean_graph_interval, payload.get("interval_seconds")),
        "enabled": bool(payload.get("enabled", True)),
        "client_id": _oid(payload["client_id"]) if payload.get("client_id") else None,
        "visible_roles": _clean_visible_roles(payload.get("visible_roles")),
        "unit": payload.get("unit") or "",
        "display_name": payload.get("display_name") or "",
        "created_by": str(admin.get("_id") or admin.get("id") or "admin"),
        "created_at": now,
        "updated_at": now,
    }

    result = await db.monitoring_graphs.insert_one(doc)
    doc["_id"] = result.inserted_id
    return serialize_graph(doc)


@router.put("/admin/monitoring/graphs/{graph_id}")
async def update_graph(graph_id: str, payload: dict, admin=Depends(get_current_admin)):
    db = await _get_db()
    updates = {}

    if "name" in payload:
        updates["name"] = _clean_or_400(_clean_graph_name, payload["name"])
    if "target" in payload:
        updates["target"] = _clean_or_400(_clean_graph_target, payload["target"])
    if "type" in payload:
        if payload["type"] not in VALID_GRAPH_TYPES:
            raise HTTPException(status_code=400, detail=f"Unsupported graph type: {payload['type']}")
        updates["type"] = payload["type"]
    if "snmp_oid" in payload:
        updates["snmp_oid"] = _clean_or_400(_clean_oid, payload["snmp_oid"]) if payload["snmp_oid"] else None
        # A manual OID change invalidates the recorded interface identity, which
        # the auto-heal uses to re-map a drifted ifIndex. Keeping a stale name
        # would let the healer move the graph back to an interface the admin
        # deliberately moved it away from.
        if "interface_name" not in payload:
            updates["interface_name"] = ""
            updates["interface_index"] = ""
    if "snmp_community" in payload:
        updates["snmp_community"] = _clean_community(payload["snmp_community"])
    if "snmp_port" in payload:
        updates["snmp_port"] = _clean_or_400(_clean_snmp_port, payload["snmp_port"])
    if "snmp_version" in payload:
        updates["snmp_version"] = payload["snmp_version"]
    if "interval_seconds" in payload:
        updates["interval_seconds"] = _clean_or_400(_clean_graph_interval, payload["interval_seconds"])
    if "enabled" in payload:
        updates["enabled"] = bool(payload["enabled"])
    if "client_id" in payload:
        updates["client_id"] = _oid(payload["client_id"]) if payload["client_id"] else None
    if "unit" in payload:
        updates["unit"] = payload["unit"]
    if "display_name" in payload:
        updates["display_name"] = payload["display_name"]
    if "interface_name" in payload:
        updates["interface_name"] = str(payload["interface_name"] or "")[:120]
    if "interface_index" in payload:
        updates["interface_index"] = str(payload["interface_index"] or "")[:16]
    if "visible_roles" in payload:
        updates["visible_roles"] = _clean_visible_roles(payload["visible_roles"])

    if not updates:
        raise HTTPException(status_code=400, detail="No supported fields supplied")

    updates["updated_at"] = datetime.now(timezone.utc)
    result = await db.monitoring_graphs.update_one(
        {"_id": _oid(graph_id)}, {"$set": updates}
    )
    if not result.matched_count:
        raise HTTPException(status_code=404, detail="Graph not found")

    doc = await db.monitoring_graphs.find_one({"_id": _oid(graph_id)})
    return serialize_graph(doc)


@router.delete("/admin/monitoring/graphs/{graph_id}")
async def delete_graph(graph_id: str, admin=Depends(get_current_admin)):
    db = await _get_db()
    result = await db.monitoring_graphs.delete_one({"_id": _oid(graph_id)})
    if not result.deleted_count:
        raise HTTPException(status_code=404, detail="Graph not found")
    return {"ok": True}


# ---------------------------------------------------------------------------
# Admin graph data endpoint (read)
# ---------------------------------------------------------------------------
@router.get("/admin/monitoring/graphs/{graph_id}/data")
async def graph_data(
    graph_id: str,
    from_: str = Query(..., alias="from"),
    to: str = Query(...),
    resolution: str = Query("auto"),
    staff=Depends(require_roles("admin", "support")),
):
    db = await _get_db()

    # Verify graph exists AND is visible to this role
    query = {"_id": _oid(graph_id)}
    if staff.get("role") != "admin":
        query["visible_roles"] = staff.get("role")
    doc = await db.monitoring_graphs.find_one(query)
    if not doc:
        raise HTTPException(status_code=404, detail="Graph not found or not visible to your role")

    try:
        from_dt = datetime.fromisoformat(from_.replace("Z", "+00:00"))
        to_dt = datetime.fromisoformat(to.replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format (use ISO 8601)")

    if from_dt >= to_dt:
        raise HTTPException(status_code=400, detail="'from' must be before 'to'")

    data, resolved_resolution = await get_graph_data(db, graph_id, from_dt, to_dt, resolution=resolution)
    return {"graph_id": graph_id, "resolution": resolved_resolution, "data": data}


def _merge_pair_rows(primary_rows: list[dict], pair_rows: list[dict]) -> list[dict]:
    """Merge two direction series into combined {at, in, out} rows by timestamp.

    IN and OUT are polled as separate documents, so their sample timestamps
    are never bit-identical (they differ by milliseconds / the probe latency
    between the two SNMP GETs). To line them up we normalize each timestamp to
    whole seconds before joining; rows within the same second are treated as
    the same polling interval.
    """
    def _key(at):
        if isinstance(at, datetime):
            return at.replace(microsecond=0)
        return at

    by_ts: dict = {}
    for r in primary_rows:
        key = _key(r["at"])
        by_ts[key] = {"at": r["at"], "in": r.get("value"), "out": None}
    for r in pair_rows:
        key = _key(r["at"])
        entry = by_ts.get(key)
        if entry:
            entry["out"] = r.get("value")
        else:
            by_ts[key] = {"at": r["at"], "in": None, "out": r.get("value")}
    return sorted(
        by_ts.values(),
        key=lambda x: x["at"] if isinstance(x["at"], datetime) else x["at"],
    )


@router.get("/admin/monitoring/graphs/{graph_id}/export")
async def export_graph(
    graph_id: str,
    from_: str = Query(..., alias="from"),
    to: str = Query(...),
    resolution: str = Query("auto"),
    pair_id: Optional[str] = Query(None, description="Sibling OUT/IN graph id for a combined IN+OUT PDF"),
    staff=Depends(require_roles("admin", "support")),
):
    """Export the selected time range as PDF, optionally combining IN and OUT."""
    db = await _get_db()
    query = {"_id": _oid(graph_id)}
    if staff.get("role") != "admin":
        query["visible_roles"] = staff.get("role")
    doc = await db.monitoring_graphs.find_one(query)
    if not doc:
        raise HTTPException(status_code=404, detail="Graph not found or not visible to your role")
    try:
        from_dt = datetime.fromisoformat(from_.replace("Z", "+00:00"))
        to_dt = datetime.fromisoformat(to.replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format (use ISO 8601)")
    if from_dt >= to_dt:
        raise HTTPException(status_code=400, detail="'from' must be before 'to'")
    rows, _ = await get_graph_data(db, graph_id, from_dt, to_dt, resolution=resolution)
    if pair_id:
        pair_rows, _ = await get_graph_data(db, pair_id, from_dt, to_dt, resolution=resolution)
        rows = _merge_pair_rows(rows, pair_rows)
    return graph_export_response(doc, rows)


@router.post("/admin/monitoring/graphs/{graph_id}/run")
async def run_graph_manual(graph_id: str, admin=Depends(get_current_admin)):
    """Manual run for a single graph (admin only)."""
    db = await _get_db()

    doc = await db.monitoring_graphs.find_one({"_id": _oid(graph_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Graph not found")

    admin_id = admin.get("id") or admin.get("_id") or "admin"
    owner = f"manual:{admin_id}:{uuid.uuid4().hex}"

    result = await probe_graph(db, graph=doc, owner=owner)
    return result


# ---------------------------------------------------------------------------
# Client-scoped graph endpoints
# ---------------------------------------------------------------------------
@router.get("/client/monitoring/graphs")
async def client_list_graphs(
    user=Depends(get_current_user),
):
    db = await _get_db()
    if user.get("role") != "client":
        raise HTTPException(status_code=403, detail="Client only")
    client_oid = _oid(user["id"])
    cursor = db.monitoring_graphs.find({"enabled": True, "client_id": client_oid}).sort("created_at", 1)
    docs = await cursor.to_list(500)
    return [serialize_graph(doc) for doc in docs]


@router.get("/client/monitoring/graphs/{graph_id}/data")
async def client_graph_data(
    graph_id: str,
    from_: str = Query(..., alias="from"),
    to: str = Query(...),
    resolution: str = Query("auto"),
    user=Depends(get_current_user),
):
    db = await _get_db()
    if user.get("role") != "client":
        raise HTTPException(status_code=403, detail="Client only")

    # Verify graph exists AND belongs to this client
    doc = await db.monitoring_graphs.find_one({"_id": _oid(graph_id), "client_id": _oid(user["id"])})
    if not doc:
        raise HTTPException(status_code=404, detail="Graph not found or not assigned to you")

    try:
        from_dt = datetime.fromisoformat(from_.replace("Z", "+00:00"))
        to_dt = datetime.fromisoformat(to.replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format (use ISO 8601)")

    data, resolved_resolution = await get_graph_data(db, graph_id, from_dt, to_dt, resolution=resolution)
    return {"graph_id": graph_id, "resolution": resolved_resolution, "data": data}


# ---------------------------------------------------------------------------
# Scheduler-triggered endpoints (for on-demand admin run)
# ---------------------------------------------------------------------------
@router.post("/admin/monitoring/sweep")
async def trigger_graph_sweep(admin=Depends(get_current_admin)):
    """Trigger a graph sweep manually (admin only)."""
    db = await _get_db()
    owner = f"{socket.gethostname()}:{admin.get('id') or admin.get('_id')}:{uuid.uuid4().hex}"
    result = await run_graph_sweep(db, owner=owner)
    return result


@router.post("/admin/monitoring/downsample")
async def trigger_downsample(admin=Depends(get_current_admin)):
    """Trigger downsampling manually (admin only)."""
    db = await _get_db()
    owner = f"{socket.gethostname()}:{admin.get('id') or admin.get('_id')}:{uuid.uuid4().hex}"
    result = await run_downsample_sweep(db, owner=owner)
    return result


# ---------------------------------------------------------------------------
# Collection / retention health (silent-failure detector)
# ---------------------------------------------------------------------------
_SAMPLE_COLLECTIONS = (
    ("monitoring_graph_samples_raw", "at"),
    ("monitoring_graph_samples_halfhour", "slot"),
    ("monitoring_graph_samples_hourly", "hour"),
    ("monitoring_graph_samples_daily", "date"),
    ("monitoring_graph_alerts", "fired_at"),
)


@router.get("/admin/monitoring/health")
async def monitoring_health(staff=Depends(require_roles("admin", "support"))):
    """Report retention/rollup health so silent failures become visible.

    The failure modes this exists to catch are the ones that never raise:
    a TTL index that was never created (collection grows forever), a rollup
    job that silently stopped (recent buckets empty while raw keeps filling),
    and lease rows that accumulate because nobody released them.
    """
    db = await _get_db()
    now = datetime.now(timezone.utc)

    # --- collections: indexed? TTL present? bounded? -----------------------
    collections = []
    for name, time_field in _SAMPLE_COLLECTIONS:
        coll = db[name]
        info: dict = {"name": name, "time_field": time_field}
        try:
            info["docs"] = await coll.estimated_document_count()
        except Exception as exc:
            info["docs"] = None
            info["error"] = f"{type(exc).__name__}: {exc}"
        ttl_seconds = None
        try:
            indexes = await coll.list_indexes().to_list(length=None)
        except Exception:
            indexes = []
        for idx in indexes:
            if idx.get("key", {}).get(time_field) == 1 and "expireAfterSeconds" in idx:
                ttl_seconds = idx["expireAfterSeconds"]
                break
        info["ttl_seconds"] = ttl_seconds
        info["ttl_ok"] = ttl_seconds is not None
        try:
            newest = await coll.find_one({}, {time_field: 1}, sort=[(time_field, -1)])
            info["newest"] = newest.get(time_field).isoformat() if newest and newest.get(time_field) else None
        except Exception:
            info["newest"] = None
        collections.append(info)

    # --- per-graph freshness vs its own poll interval ----------------------
    graph_rows = []
    unhealthy = 0
    # Same RBAC filter as the listings: a non-admin must not learn the names or
    # error strings of graphs outside their visible_roles.
    health_query: dict = {"enabled": True}
    if staff.get("role") != "admin":
        health_query["visible_roles"] = staff.get("role")
    try:
        graphs = await db.monitoring_graphs.find(
            health_query, {"name": 1, "display_name": 1, "interface_name": 1,
                           "interval_seconds": 1, "last_poll_at": 1,
                           "last_poll_state": 1, "last_poll_error": 1}
        ).to_list(1000)
    except Exception:
        graphs = []

    for g in graphs:
        interval = int(g.get("interval_seconds") or 300)
        last = g.get("last_poll_at")
        age_seconds = None
        if isinstance(last, datetime):
            # Older backends persisted naive UTC; the sweep now writes aware
            # datetimes. Normalize so this can never raise (a 500 here would be
            # exactly the kind of silent failure the endpoint exists to catch).
            if last.tzinfo is None:
                last = last.replace(tzinfo=timezone.utc)
            age_seconds = (now - last).total_seconds()
        # 3 missed intervals = genuinely stalled, not just a slow sweep.
        stale = age_seconds is None or age_seconds > max(interval * 3, 120)
        state = g.get("last_poll_state")
        ok = (not stale) and state != "error"
        if not ok:
            unhealthy += 1
        graph_rows.append({
            "id": str(g["_id"]),
            "name": g.get("display_name") or g.get("name") or g.get("interface_name") or "",
            "interval_seconds": interval,
            "last_poll_age_seconds": round(age_seconds, 1) if age_seconds is not None else None,
            "last_poll_state": state,
            "last_poll_error": (g.get("last_poll_error") or "")[:200],
            "healthy": ok,
        })

    # --- scheduler leases: how many are held vs abandoned ------------------
    leases = {"total": 0, "active": 0, "released": 0, "expired_released": 0,
              "per_graph": 0, "released_per_graph": 0, "error": None}
    try:
        async for lease in db.scheduler_leases.find(
                {}, {"_id": 1, "owner": 1, "expires_at": 1}):
            leases["total"] += 1
            owner = lease.get("owner")
            expires = lease.get("expires_at")
            if owner is None:
                leases["released"] += 1
                if isinstance(expires, datetime) and expires < now:
                    leases["expired_released"] += 1
            elif isinstance(expires, datetime) and expires < now:
                leases["expired_released"] += 1
            else:
                leases["active"] += 1
            if str(lease.get("_id", "")).startswith("job:graph:"):
                leases["per_graph"] += 1
                if owner is None:
                    leases["released_per_graph"] += 1
    except Exception as exc:
        leases["error"] = f"{type(exc).__name__}: {exc}"

    # --- alert rules / open alerts -----------------------------------------
    alerts = {"rules": 0, "open": 0, "suppressed_open": 0, "maintenance_windows": 0,
              "error": None}
    try:
        # Counts must respect the same row-level scoping as the graph rows above,
        # otherwise a non-admin learns how many alerts exist on graphs they
        # cannot see (an information leak through aggregate counters).
        rule_q: dict = {"enabled": True}
        alert_q: dict = {"resolved_at": None}
        window_q: dict = {"enabled": True}
        if staff.get("role") != "admin":
            vis = await _visible_graph_ids(db, staff)
            rule_q = {"enabled": True,
                      "$or": [{"graph_id": {"$in": vis}}, {"graph_id": {"$in": ["", None]}}]}
            alert_q = {"resolved_at": None, "graph_id": {"$in": vis}}
            window_q = {"enabled": True,
                        "$or": [{"graph_ids": {"$in": vis}}, {"graph_ids": []}]}
        alerts["rules"] = await db[ga.RULES_COLLECTION].count_documents(rule_q)
        alerts["open"] = await db[ga.ALERTS_COLLECTION].count_documents(alert_q)
        alerts["suppressed_open"] = await db[ga.ALERTS_COLLECTION].count_documents(
            {**alert_q, "suppressed": True})
        alerts["maintenance_windows"] = await db[ga.WINDOWS_COLLECTION].count_documents(
            window_q)
    except Exception as exc:
        alerts["error"] = f"{type(exc).__name__}: {exc}"

    # --- verdict ----------------------------------------------------------
    problems = []
    for c in collections:
        if c.get("docs") and not c.get("ttl_ok"):
            problems.append(f"{c['name']} has {c['docs']} docs but no TTL index "
                            f"on {c['time_field']} — collection will grow forever")
    if unhealthy:
        problems.append(f"{unhealthy} enabled graph(s) stalled or in error state")
    if leases["released_per_graph"] > 50:
        problems.append(f"{leases['released_per_graph']} released per-graph leases "
                        f"awaiting reaper — reaper may not be running")

    return {
        "at": now.isoformat(),
        "healthy": not problems,
        "problems": problems,
        "graphs": {"total": len(graph_rows), "unhealthy": unhealthy, "items": graph_rows},
        "collections": collections,
        "leases": leases,
        "alerts": alerts,
    }


# ---------------------------------------------------------------------------
# Graph alert rules CRUD (phase 3)
# ---------------------------------------------------------------------------
def _serialize_rule(d: dict) -> dict:
    return {
        "id": str(d["_id"]),
        "name": d.get("name", ""),
        "metric": d.get("metric", "bps"),
        "comparator": d.get("comparator", ">"),
        "threshold": d.get("threshold", 0),
        "consecutive": int(d.get("consecutive") or 2),
        "severity": d.get("severity", "warning"),
        "enabled": bool(d.get("enabled", True)),
        "graph_id": d.get("graph_id") or None,
        "created_at": _iso(d.get("created_at", "")),
    }


@router.get("/admin/monitoring/alert-rules")
async def alert_rules_list(staff=Depends(require_roles("admin", "support"))):
    db = await _get_db()
    # Scope to graphs visible to this role (same pattern as monitoring_health graph rows)
    visible_ids = await _visible_graph_ids(db, staff)
    if visible_ids is not None:
        # Rules with graph_id set must match; rules with empty graph_id (global) are visible
        query = {"$or": [{"graph_id": {"$in": visible_ids}}, {"graph_id": {"$in": ["", None]}}]}
    else:
        query = {}
    docs = await db[ga.RULES_COLLECTION].find(query).sort("created_at", -1).to_list(200)
    return [_serialize_rule(d) for d in docs]


@router.post("/admin/monitoring/alert-rules")
async def alert_rules_create(payload: m.GraphAlertRuleIn, request: Request,
                             admin=Depends(require_roles("admin", "support"))):
    db = await _get_db()
    await _require_visible_graph_ids(db, admin, [payload.graph_id or ""])
    doc = payload.model_dump(exclude_none=True)
    doc["created_at"] = _now()
    r = await db[ga.RULES_COLLECTION].insert_one(doc)
    doc["_id"] = r.inserted_id
    await log_audit(db, actor=admin, action="monitoring.alert_rule_created",
                    category="monitoring", target_type="graph_alert_rule",
                    target_id=str(r.inserted_id), target_label=payload.name, request=request)
    return _serialize_rule(doc)


@router.put("/admin/monitoring/alert-rules/{rule_id}")
async def alert_rules_update(rule_id: str, payload: m.GraphAlertRuleIn, request: Request,
                             admin=Depends(require_roles("admin", "support"))):
    db = await _get_db()
    existing = await db[ga.RULES_COLLECTION].find_one({"_id": _oid(rule_id)})
    if existing is None:
        raise HTTPException(status_code=404, detail="Alert rule not found")
    # Visibility guard on the OBJECT, not just the payload: a non-admin must not
    # edit a rule scoped to a hidden graph, nor a global rule (empty graph_id)
    # which touches graphs it cannot see. Then guard the target scope, so a
    # visible rule cannot be retargeted onto a hidden graph either.
    await _require_visible_object(db, admin, _rule_graph_ids(existing))
    await _require_visible_graph_ids(db, admin, [payload.graph_id or ""])
    res = await db[ga.RULES_COLLECTION].update_one(
        {"_id": _oid(rule_id)}, {"$set": payload.model_dump(exclude_none=True)})
    d = await db[ga.RULES_COLLECTION].find_one({"_id": _oid(rule_id)})
    await log_audit(db, actor=admin, action="monitoring.alert_rule_updated",
                    category="monitoring", target_type="graph_alert_rule",
                    target_id=rule_id, target_label=str(d.get("name", "")), request=request)
    return _serialize_rule(d)


@router.delete("/admin/monitoring/alert-rules/{rule_id}")
async def alert_rules_delete(rule_id: str, admin=Depends(require_roles("admin", "support"))):
    db = await _get_db()
    existing = await db[ga.RULES_COLLECTION].find_one({"_id": _oid(rule_id)})
    if existing is None:
        raise HTTPException(status_code=404, detail="Alert rule not found")
    # Same object-level guard as update: a global rule (empty graph_id) or a
    # rule scoped to a hidden graph is admin-only to delete. _require_visible_graph_ids
    # alone would wave through a global rule because its empty scope is a
    # trivial subset of any visible set.
    await _require_visible_object(db, admin, _rule_graph_ids(existing))
    r = await db[ga.RULES_COLLECTION].delete_one({"_id": _oid(rule_id)})
    if not r.deleted_count:
        raise HTTPException(status_code=404, detail="Alert rule not found")
    return {"deleted": r.deleted_count}


# ---------------------------------------------------------------------------
# Maintenance windows CRUD (phase 3)
# ---------------------------------------------------------------------------
def _serialize_window(d: dict, visible_ids: Optional[set[str]] = None) -> dict:
    graph_ids = [str(graph_id) for graph_id in (d.get("graph_ids") or [])]
    if visible_ids is not None:
        # A window may span visible and hidden graphs. Returning the raw list
        # would leak hidden graph identifiers even though the row itself
        # legitimately intersects the caller's scope.
        graph_ids = [graph_id for graph_id in graph_ids if graph_id in visible_ids]
    return {
        "id": str(d["_id"]),
        "name": d.get("name", ""),
        "starts_at": d.get("starts_at", ""),
        "ends_at": d.get("ends_at", ""),
        "graph_ids": graph_ids,
        "enabled": bool(d.get("enabled", True)),
        "created_at": _iso(d.get("created_at", "")),
    }


def _validate_window_dates(payload: m.MaintenanceWindowIn) -> None:
    start = datetime.fromisoformat(payload.starts_at.replace("Z", "+00:00"))
    end = datetime.fromisoformat(payload.ends_at.replace("Z", "+00:00"))
    if start >= end:
        raise HTTPException(status_code=422, detail="ends_at must be after starts_at")


@router.get("/admin/monitoring/maintenance-windows")
async def maintenance_windows_list(staff=Depends(require_roles("admin", "support"))):
    db = await _get_db()
    # Scope to graphs visible to this role.
    visible_ids = await _visible_graph_ids(db, staff)
    if visible_ids is not None:
        # Windows scoped to a visible graph intersect; global windows (empty list) stay visible.
        query = {"$or": [
            {"graph_ids": {"$in": visible_ids}},
            {"graph_ids": []},
        ]}
    else:
        query = {}
    docs = await db[ga.WINDOWS_COLLECTION].find(query).sort("created_at", -1).to_list(200)
    visible_set = set(visible_ids) if visible_ids is not None else None
    return [_serialize_window(d, visible_set) for d in docs]


@router.post("/admin/monitoring/maintenance-windows")
async def maintenance_windows_create(payload: m.MaintenanceWindowIn, request: Request,
                                     admin=Depends(require_roles("admin", "support"))):
    _validate_window_dates(payload)
    db = await _get_db()
    await _require_visible_graph_ids(db, admin, payload.graph_ids)
    doc = payload.model_dump()
    doc["created_at"] = _now()
    r = await db[ga.WINDOWS_COLLECTION].insert_one(doc)
    doc["_id"] = r.inserted_id
    await log_audit(db, actor=admin, action="monitoring.maintenance_window_created",
                    category="monitoring", target_type="maintenance_window",
                    target_id=str(r.inserted_id), target_label=payload.name, request=request)
    return _serialize_window(doc)


@router.put("/admin/monitoring/maintenance-windows/{window_id}")
async def maintenance_windows_update(window_id: str, payload: m.MaintenanceWindowIn,
                                     request: Request,
                                     admin=Depends(require_roles("admin", "support"))):
    _validate_window_dates(payload)
    db = await _get_db()
    existing = await db[ga.WINDOWS_COLLECTION].find_one({"_id": _oid(window_id)})
    if existing is None:
        raise HTTPException(status_code=404, detail="Maintenance window not found")
    existing_ids = _window_graph_ids(existing)
    # Guard the OBJECT first (hidden or global windows are admin-only), then
    # the payload targets, so a visible window cannot be retargeted to hidden
    # graphs.
    await _require_visible_object(db, admin, existing_ids)
    await _require_visible_graph_ids(
        db, admin, existing_ids + list(payload.graph_ids))
    res = await db[ga.WINDOWS_COLLECTION].update_one(
        {"_id": _oid(window_id)}, {"$set": payload.model_dump()})
    d = await db[ga.WINDOWS_COLLECTION].find_one({"_id": _oid(window_id)})
    await log_audit(db, actor=admin, action="monitoring.maintenance_window_updated",
                    category="monitoring", target_type="maintenance_window",
                    target_id=window_id, target_label=str(d.get("name", "")), request=request)
    return _serialize_window(d)


@router.delete("/admin/monitoring/maintenance-windows/{window_id}")
async def maintenance_windows_delete(window_id: str,
                                     admin=Depends(require_roles("admin", "support"))):
    db = await _get_db()
    existing = await db[ga.WINDOWS_COLLECTION].find_one({"_id": _oid(window_id)})
    if existing is None:
        raise HTTPException(status_code=404, detail="Maintenance window not found")
    # Object-level guard, matching update: a global window (empty graph_ids) or
    # one scoped to a hidden graph is admin-only to delete.
    await _require_visible_object(db, admin, _window_graph_ids(existing))
    r = await db[ga.WINDOWS_COLLECTION].delete_one({"_id": _oid(window_id)})
    if not r.deleted_count:
        raise HTTPException(status_code=404, detail="Maintenance window not found")
    return {"deleted": r.deleted_count}


# ---------------------------------------------------------------------------
# Alert event history (read-only)
# ---------------------------------------------------------------------------
def _serialize_alert(d: dict) -> dict:
    return {
        "id": str(d["_id"]),
        "rule_id": d.get("rule_id", ""),
        "rule_name": d.get("rule_name", ""),
        "graph_id": d.get("graph_id", ""),
        "graph_name": d.get("graph_name", ""),
        "target": d.get("target", ""),
        "metric": d.get("metric", ""),
        "comparator": d.get("comparator", ""),
        "threshold": d.get("threshold", 0),
        "severity": d.get("severity", "warning"),
        "value": d.get("value"),
        "state": d.get("state", ""),
        "error": d.get("error", ""),
        "fired_at": _iso(d.get("fired_at", "")),
        "resolved_at": _iso(d.get("resolved_at", "")) if d.get("resolved_at") else "",
        # `open` is computed from resolved_at, never from a stored flag, so a
        # reaper that resolves rows can't leave the UI showing stale open alerts.
        "open": d.get("resolved_at") is None,
        "dispatched": bool(d.get("dispatched")),
        "suppressed": bool(d.get("suppressed")),
    }


@router.get("/admin/monitoring/graph-alerts")
async def graph_alerts_list(open_only: bool = False, limit: int = 50,
                            staff=Depends(require_roles("admin", "support"))):
    """Recent alert events. `open_only=true` filters to unresolved rows."""
    db = await _get_db()
    query = {"resolved_at": None} if open_only else {}
    # Same row-level scoping as the graph listings: a non-admin must not read
    # alerts raised on graphs outside their visible_roles.
    visible_ids = await _visible_graph_ids(db, staff)
    if visible_ids is not None:
        query["graph_id"] = {"$in": visible_ids}
    capped = min(max(int(limit or 50), 1), 200)
    docs = await db[ga.ALERTS_COLLECTION].find(query).sort("fired_at", -1).to_list(capped)
    return [_serialize_alert(d) for d in docs]