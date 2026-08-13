"""Internal ping-check registry for the monitoring foundation.

This route intentionally only manages checks. Scheduling, SNMP collection,
graphs, network maps, and client-facing visibility are separate phases.
"""
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException

from ..auth import get_current_admin, require_roles
from ..monitoring import probe_target, resolve_ip, validate_target
from .shared import _get_db, _oid

router = APIRouter()

_MIN_INTERVAL_SECONDS = 30
_MAX_INTERVAL_SECONDS = 3600


def _serialize_check(doc: dict) -> dict:
    return {
        "id": str(doc["_id"]),
        "name": doc.get("name", ""),
        "target": doc.get("target", ""),
        "type": doc.get("type", "ping"),
        "enabled": bool(doc.get("enabled", True)),
        "interval_seconds": int(doc.get("interval_seconds") or 300),
        "created_at": doc.get("created_at"),
        "updated_at": doc.get("updated_at"),
    }


def _clean_name(value) -> str:
    name = str(value or "").strip()
    if not name or len(name) > 120:
        raise HTTPException(status_code=400, detail="name is required and must be at most 120 characters")
    return name


def _clean_target(value) -> str:
    target = str(value or "").strip()
    if not target or len(target) > 253:
        raise HTTPException(status_code=400, detail="target is required and must be at most 253 characters")
    try:
        validated = validate_target(target)
        # Fail fast at registry write time as well as at probe time.  The
        # probe re-resolves and validates again to defend against later DNS
        # rebinding, but unsafe hostnames should never be persisted.
        validate_target(resolve_ip(validated))
        return validated
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _clean_interval(value) -> int:
    try:
        interval = int(value if value is not None else 300)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="interval_seconds must be an integer") from exc
    if not _MIN_INTERVAL_SECONDS <= interval <= _MAX_INTERVAL_SECONDS:
        raise HTTPException(
            status_code=400,
            detail=f"interval_seconds must be between {_MIN_INTERVAL_SECONDS} and {_MAX_INTERVAL_SECONDS}",
        )
    return interval


def _clean_enabled(value) -> bool:
    if not isinstance(value, bool):
        raise HTTPException(status_code=400, detail="enabled must be a boolean")
    return value


@router.get("/admin/monitoring/checks")
async def monitoring_checks_list(staff=Depends(require_roles("admin", "support"))):
    db = await _get_db()
    docs = await db.monitoring_checks.find({}).sort("created_at", 1).to_list(500)
    return [_serialize_check(doc) for doc in docs]


@router.post("/admin/monitoring/checks")
async def monitoring_check_create(payload: dict, admin=Depends(get_current_admin)):
    db = await _get_db()
    now = datetime.now(timezone.utc)
    doc = {
        "name": _clean_name(payload.get("name")),
        "target": _clean_target(payload.get("target")),
        "type": "ping",
        "enabled": _clean_enabled(payload.get("enabled", True)),
        "interval_seconds": _clean_interval(payload.get("interval_seconds")),
        "created_at": now,
        "updated_at": now,
    }
    result = await db.monitoring_checks.insert_one(doc)
    doc["_id"] = result.inserted_id
    return _serialize_check(doc)


@router.put("/admin/monitoring/checks/{check_id}")
async def monitoring_check_update(check_id: str, payload: dict, admin=Depends(get_current_admin)):
    db = await _get_db()
    updates = {}
    if "name" in payload:
        updates["name"] = _clean_name(payload["name"])
    if "target" in payload:
        updates["target"] = _clean_target(payload["target"])
    if "enabled" in payload:
        updates["enabled"] = _clean_enabled(payload["enabled"])
    if "interval_seconds" in payload:
        updates["interval_seconds"] = _clean_interval(payload["interval_seconds"])
    if not updates:
        raise HTTPException(status_code=400, detail="No supported monitoring-check fields supplied")
    updates["updated_at"] = datetime.now(timezone.utc)
    result = await db.monitoring_checks.update_one({"_id": _oid(check_id)}, {"$set": updates})
    if not result.matched_count:
        raise HTTPException(status_code=404, detail="Monitoring check not found")
    doc = await db.monitoring_checks.find_one({"_id": _oid(check_id)})
    return _serialize_check(doc)


@router.delete("/admin/monitoring/checks/{check_id}")
async def monitoring_check_delete(check_id: str, admin=Depends(get_current_admin)):
    db = await _get_db()
    result = await db.monitoring_checks.delete_one({"_id": _oid(check_id)})
    if not result.deleted_count:
        raise HTTPException(status_code=404, detail="Monitoring check not found")
    return {"ok": True}


@router.get("/admin/monitoring/checks/{check_id}/history")
async def monitoring_check_history(check_id: str,
                                   staff=Depends(require_roles("admin", "support")),
                                   limit: int = 100):
    """Return bounded operational history for one persisted check."""
    db = await _get_db()
    doc = await db.monitoring_checks.find_one({"_id": _oid(check_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Monitoring check not found")

    limit = max(1, min(int(limit or 100), 500))
    state = await db.monitoring_check_state.find_one({"check_id": check_id}) or {}
    samples = await db.monitoring_probes.find({"check_id": check_id}).sort("at", -1).limit(limit).to_list(limit)
    events = await db.monitoring_events.find({"check_id": check_id}).sort("at", -1).limit(limit).to_list(limit)
    return {
        "check": _serialize_check(doc),
        "state": {
            "status": state.get("status") or "unknown",
            "target": state.get("target") or doc.get("target") or "",
            "last_at": state.get("last_at"),
            "last_rtt_ms": state.get("last_rtt_ms"),
            "consecutive_failures": int(state.get("consecutive_failures") or 0),
        },
        "samples": [{
            "at": sample.get("at"),
            "up": bool(sample.get("up")),
            "rtt_ms": sample.get("rtt_ms"),
            "rtt_min_ms": sample.get("rtt_min_ms"),
            "rtt_max_ms": sample.get("rtt_max_ms"),
            "loss": sample.get("loss"),
            "resolved_ip": sample.get("resolved_ip"),
        } for sample in samples],
        "events": [{
            "id": str(event["_id"]),
            "at": event.get("at"),
            "from": event.get("from"),
            "to": event.get("to"),
            "target": event.get("target"),
        } for event in events],
    }


@router.post("/admin/monitoring/checks/{check_id}/run")
async def monitoring_check_run(check_id: str, admin=Depends(get_current_admin)):
    """Trigger one probe using a unique per-request lease owner."""
    db = await _get_db()
    doc = await db.monitoring_checks.find_one({"_id": _oid(check_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Monitoring check not found")

    admin_id = admin.get("id") or admin.get("_id") or "admin"
    owner = f"manual:{admin_id}:{uuid.uuid4().hex}"
    return await probe_target(
        db,
        target=str(doc.get("target") or "").strip(),
        check_id=str(doc["_id"]),
        owner=owner,
    )

