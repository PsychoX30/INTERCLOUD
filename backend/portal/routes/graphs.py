"""Graph CRUD endpoints for admin monitoring.

Admin-only mutations. Admin+support read. Client-scoped read via separate endpoint.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional
import uuid
import socket
import re

from fastapi import APIRouter, Depends, HTTPException, Query

from ..auth import get_current_admin, get_current_user, get_current_staff, require_roles
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
from .shared import _get_db, _oid
from bson import ObjectId

router = APIRouter()

VALID_GRAPH_TYPES = {
    "snmp_traffic_in", "snmp_traffic_out", "snmp_cpu",
    "snmp_memory", "snmp_disk", "snmp_uptime", "ping",
}


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
    """Merge two direction series into combined {at, in, out} rows by timestamp."""
    by_ts: dict[str, dict] = {}
    for r in primary_rows:
        ts = r["at"]
        if isinstance(ts, datetime):
            ts = ts.isoformat()
        by_ts[ts] = {"at": r["at"], "in": r.get("value"), "out": None}
    for r in pair_rows:
        ts = r["at"]
        if isinstance(ts, datetime):
            ts = ts.isoformat()
        entry = by_ts.get(ts)
        if entry:
            entry["out"] = r.get("value")
        else:
            by_ts[ts] = {"at": r["at"], "in": None, "out": r.get("value")}
    return sorted(by_ts.values(), key=lambda x: x["at"] if isinstance(x["at"], datetime) else x["at"])


@router.get("/admin/monitoring/graphs/{graph_id}/export")
async def export_graph(
    graph_id: str,
    from_: str = Query(..., alias="from"),
    to: str = Query(...),
    resolution: str = Query("auto"),
    fmt: str = Query("pdf", pattern="^(pdf|csv)$"),
    pair_id: Optional[str] = Query(None, description="Sibling OUT/IN graph id to merge into a combined IN+OUT export"),
    staff=Depends(require_roles("admin", "support")),
):
    """Export graph data as PDF or CSV. When ``pair_id`` is given and fmt=csv,
    merge the sibling traffic direction into combined IN/OUT columns."""
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
    if fmt == "csv" and pair_id:
        pair_rows, _ = await get_graph_data(db, pair_id, from_dt, to_dt, resolution=resolution)
        rows = _merge_pair_rows(rows, pair_rows)
    return graph_export_response(doc, rows, fmt)


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