"""Graph CRUD endpoints for admin monitoring.

Admin-only mutations. Admin+support read. Client-scoped read via separate endpoint.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional
import uuid
import socket

from fastapi import APIRouter, Depends, HTTPException, Query

from ..auth import get_current_admin, get_current_user, require_roles
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

router = APIRouter()


def _clean_or_400(cleaner, value):
    """Convert validation failures into API client errors, not 500s."""
    try:
        return cleaner(value)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# SNMP discovery (auto-scan available sensors on a host)
# ---------------------------------------------------------------------------
@router.post("/admin/monitoring/discover")
async def discover_sensors(payload: dict, admin=Depends(get_current_admin)):
    """Auto-scan a target for available SNMP sensors via snmpwalk.

    Returns a list of discovered sensors (OID, label, unit, kind) so NOC can
    pick one to create a graph without typing OIDs by hand. Admin only.
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

    doc = {
        "name": _clean_or_400(_clean_graph_name, payload.get("name")),
        "target": _clean_or_400(_clean_graph_target, payload.get("target")),
        "type": payload.get("type", "snmp_traffic"),
        "snmp_oid": _clean_oid(payload.get("snmp_oid")) if payload.get("snmp_oid") else None,
        "snmp_community": _clean_community(payload.get("snmp_community")),
        "snmp_port": int(payload.get("snmp_port") or 161),
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
        updates["type"] = payload["type"]
    if "snmp_oid" in payload:
        updates["snmp_oid"] = _clean_oid(payload["snmp_oid"]) if payload["snmp_oid"] else None
    if "snmp_community" in payload:
        updates["snmp_community"] = _clean_community(payload["snmp_community"])
    if "snmp_port" in payload:
        updates["snmp_port"] = int(payload["snmp_port"] or 161)
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

    data = await get_graph_data(db, graph_id, from_dt, to_dt, resolution=resolution)
    return {"graph_id": graph_id, "resolution": resolution, "data": data}


@router.get("/admin/monitoring/graphs/{graph_id}/export")
async def export_graph(
    graph_id: str,
    from_: str = Query(..., alias="from"),
    to: str = Query(...),
    fmt: str = Query("xlsx", pattern="^(xlsx|pdf)$"),
    resolution: str = Query("auto"),
    staff=Depends(require_roles("admin", "support")),
):
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
    rows = await get_graph_data(db, graph_id, from_dt, to_dt, resolution=resolution)
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

    data = await get_graph_data(db, graph_id, from_dt, to_dt, resolution=resolution)
    return {"graph_id": graph_id, "resolution": resolution, "data": data}


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