"""Network map endpoints for admin monitoring.

Admin-only mutations. Admin+support read.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException

from ..auth import get_current_admin, require_roles
from .shared import _get_db, _oid

router = APIRouter()

_VALID_NODE_TYPES = {"router", "switch", "server", "cloud", "custom"}


def _serialize_node(doc: dict) -> dict:
    return {
        "id": str(doc["_id"]),
        "label": doc.get("label") or "",
        "device_id": doc.get("device_id") or None,
        "graph_id": doc.get("graph_id") or None,
        "x": float(doc.get("x") or 0),
        "y": float(doc.get("y") or 0),
        "type": doc.get("type") or "custom",
        "icon": doc.get("icon") or None,
        "status": doc.get("status") or "unknown",
        "created_at": doc.get("created_at"),
        "updated_at": doc.get("updated_at"),
    }


def _serialize_link(doc: dict) -> dict:
    return {
        "id": str(doc["_id"]),
        "source_id": str(doc.get("source_id") or ""),
        "target_id": str(doc.get("target_id") or ""),
        "label": doc.get("label") or "",
        "color": doc.get("color") or None,
        "width": float(doc.get("width") or 1),
        "created_at": doc.get("created_at"),
    }


# ---------------------------------------------------------------------------
# Node CRUD
# ---------------------------------------------------------------------------
@router.get("/admin/monitoring/map/nodes")
async def list_nodes(staff=Depends(require_roles("admin", "support"))):
    db = await _get_db()
    cursor = db.network_map_nodes.find({}).sort("created_at", 1)
    docs = await cursor.to_list(500)
    return [_serialize_node(doc) for doc in docs]


@router.post("/admin/monitoring/map/nodes")
async def create_node(payload: dict, admin=Depends(get_current_admin)):
    db = await _get_db()
    now = datetime.now(timezone.utc)
    label = str(payload.get("label") or "").strip()
    if not label or len(label) > 120:
        raise HTTPException(status_code=400, detail="label is required (max 120 chars)")
    node_type = str(payload.get("type") or "custom").strip()
    if node_type not in _VALID_NODE_TYPES:
        raise HTTPException(status_code=400, detail=f"type must be one of: {_VALID_NODE_TYPES}")

    doc = {
        "label": label,
        "device_id": payload.get("device_id") or None,
        "graph_id": payload.get("graph_id") or None,
        "x": float(payload.get("x") or 0),
        "y": float(payload.get("y") or 0),
        "type": node_type,
        "icon": payload.get("icon") or None,
        "status": "unknown",
        "created_by": str(admin.get("_id") or admin.get("id") or "admin"),
        "created_at": now,
        "updated_at": now,
    }
    result = await db.network_map_nodes.insert_one(doc)
    doc["_id"] = result.inserted_id
    return _serialize_node(doc)


@router.put("/admin/monitoring/map/nodes/{node_id}")
async def update_node(node_id: str, payload: dict, admin=Depends(get_current_admin)):
    db = await _get_db()
    updates = {}
    if "label" in payload:
        label = str(payload["label"] or "").strip()
        if not label or len(label) > 120:
            raise HTTPException(status_code=400, detail="label is required (max 120 chars)")
        updates["label"] = label
    if "x" in payload:
        updates["x"] = float(payload["x"])
    if "y" in payload:
        updates["y"] = float(payload["y"])
    if "type" in payload:
        node_type = str(payload["type"] or "custom").strip()
        if node_type not in _VALID_NODE_TYPES:
            raise HTTPException(status_code=400, detail=f"type must be one of: {_VALID_NODE_TYPES}")
        updates["type"] = node_type
    if "icon" in payload:
        updates["icon"] = payload["icon"]
    if "device_id" in payload:
        updates["device_id"] = payload["device_id"] or None
    if "graph_id" in payload:
        updates["graph_id"] = payload["graph_id"] or None
    if "status" in payload:
        updates["status"] = payload["status"]
    if not updates:
        raise HTTPException(status_code=400, detail="No supported fields supplied")
    updates["updated_at"] = datetime.now(timezone.utc)
    result = await db.network_map_nodes.update_one({"_id": _oid(node_id)}, {"$set": updates})
    if not result.matched_count:
        raise HTTPException(status_code=404, detail="Node not found")
    doc = await db.network_map_nodes.find_one({"_id": _oid(node_id)})
    return _serialize_node(doc)


@router.delete("/admin/monitoring/map/nodes/{node_id}")
async def delete_node(node_id: str, admin=Depends(get_current_admin)):
    db = await _get_db()
    result = await db.network_map_nodes.delete_one({"_id": _oid(node_id)})
    if not result.deleted_count:
        raise HTTPException(status_code=404, detail="Node not found")
    # Also delete links referencing this node
    await db.network_map_links.delete_many({
        "$or": [{"source_id": node_id}, {"target_id": node_id}]
    })
    return {"ok": True}


# ---------------------------------------------------------------------------
# Link CRUD
# ---------------------------------------------------------------------------
@router.get("/admin/monitoring/map/links")
async def list_links(staff=Depends(require_roles("admin", "support"))):
    db = await _get_db()
    cursor = db.network_map_links.find({}).sort("created_at", 1)
    docs = await cursor.to_list(500)
    return [_serialize_link(doc) for doc in docs]


@router.post("/admin/monitoring/map/links")
async def create_link(payload: dict, admin=Depends(get_current_admin)):
    db = await _get_db()
    now = datetime.now(timezone.utc)
    source_id = str(payload.get("source_id") or "").strip()
    target_id = str(payload.get("target_id") or "").strip()
    if not source_id or not target_id:
        raise HTTPException(status_code=400, detail="source_id and target_id are required")

    # Verify both nodes exist
    for nid in (source_id, target_id):
        doc = await db.network_map_nodes.find_one({"_id": _oid(nid)})
        if not doc:
            raise HTTPException(status_code=400, detail=f"Node {nid} does not exist")

    doc = {
        "source_id": source_id,
        "target_id": target_id,
        "label": str(payload.get("label") or "").strip() or None,
        "color": payload.get("color") or None,
        "width": float(payload.get("width") or 1),
        "created_by": str(admin.get("_id") or admin.get("id") or "admin"),
        "created_at": now,
    }
    result = await db.network_map_links.insert_one(doc)
    doc["_id"] = result.inserted_id
    return _serialize_link(doc)


@router.put("/admin/monitoring/map/links/{link_id}")
async def update_link(link_id: str, payload: dict, admin=Depends(get_current_admin)):
    db = await _get_db()
    updates = {}
    if "label" in payload:
        updates["label"] = payload["label"] or None
    if "color" in payload:
        updates["color"] = payload["color"] or None
    if "width" in payload:
        updates["width"] = float(payload["width"])
    if "source_id" in payload:
        updates["source_id"] = str(payload["source_id"]).strip()
    if "target_id" in payload:
        updates["target_id"] = str(payload["target_id"]).strip()
    if not updates:
        raise HTTPException(status_code=400, detail="No supported fields supplied")
    result = await db.network_map_links.update_one({"_id": _oid(link_id)}, {"$set": updates})
    if not result.matched_count:
        raise HTTPException(status_code=404, detail="Link not found")
    doc = await db.network_map_links.find_one({"_id": _oid(link_id)})
    return _serialize_link(doc)


@router.delete("/admin/monitoring/map/links/{link_id}")
async def delete_link(link_id: str, admin=Depends(get_current_admin)):
    db = await _get_db()
    result = await db.network_map_links.delete_one({"_id": _oid(link_id)})
    if not result.deleted_count:
        raise HTTPException(status_code=404, detail="Link not found")
    return {"ok": True}