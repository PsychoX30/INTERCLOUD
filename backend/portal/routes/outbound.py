"""Outbound abuse control plane — config, enforcer preview, shadow review.

Everything an operator needs to run this feature without touching code or a
router CLI:

  GET   /admin/noc/outbound/config          current effective config
  PUT   /admin/noc/outbound/config          edit thresholds (audited)
  POST  /admin/noc/outbound/mode            shadow <-> enforce (typed confirm)
  GET   /admin/noc/outbound/enforcers       which devices would enforce what
  POST  /admin/noc/outbound/resolve         "why this IP -> this router" preview
  GET   /admin/noc/outbound/shadow          recent would-block decisions
  POST  /admin/noc/outbound/overrides       per-customer threshold override
  DELETE /admin/noc/outbound/overrides/{id}
  POST  /admin/noc/outbound/lift            remove a block, verified

The mode switch is separated from the threshold editor on purpose: changing a
number is routine, flipping the system from "observe" to "disconnect paying
customers" is not, and the two must not share an accidental save button.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request

from ..audit import log_audit
from .. import outbound_detector as detect
from .. import outbound_guard as guard
from .. import outbound_sweep as sweep
from ..auth import require_roles
from .shared import _get_db, _oid

router = APIRouter()

CONFIRM_WORD = "ENFORCE"


def _now():
    return datetime.now(timezone.utc)


@router.get("/admin/noc/outbound/config")
async def outbound_config_get(admin=Depends(require_roles("admin", "support"))):
    db = await _get_db()
    cfg = await sweep.load_config(db, force=True)
    stored = await db.ddos_detection_config.find_one({"_id": sweep.CONFIG_ID}) or {}
    return {
        "id": sweep.CONFIG_ID,
        "config": cfg,
        "defaults": detect.DEFAULT_CONFIG,
        "fields": list(detect.CONFIG_FIELDS),
        # Only the fields an operator actually changed, so the UI can flag them
        # and an auditor can see what diverged from the shipped defaults.
        "overrides": {k: v for k, v in stored.items()
                      if k in detect.DEFAULT_CONFIG and v != detect.DEFAULT_CONFIG.get(k)},
    }


@router.put("/admin/noc/outbound/config")
async def outbound_config_put(payload: dict, request: Request,
                              admin=Depends(require_roles("admin", "support"))):
    db = await _get_db()
    updates: dict = {}
    rejected: list[str] = []
    for key, value in (payload or {}).items():
        if key not in detect.DEFAULT_CONFIG:
            rejected.append(key)
            continue
        if key == "mode":
            rejected.append("mode")  # must go through /outbound/mode
            continue
        try:
            updates[key] = _coerce(key, value, detect.DEFAULT_CONFIG[key])
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=f"{key}: {exc}")
    if not updates:
        raise HTTPException(status_code=400,
                            detail=f"no valid fields supplied (rejected: {rejected})")
    updates["updated_at"] = _now()
    updates["updated_by"] = getattr(admin, "email", str(admin))
    await db.ddos_detection_config.update_one(
        {"_id": sweep.CONFIG_ID}, {"$set": updates}, upsert=True)
    sweep.invalidate_config_cache()
    await log_audit(db, actor=admin, action="noc.outbound_config_updated",
                    category="noc", target_type="ddos_detection_config",
                    target_id=sweep.CONFIG_ID,
                    target_label=", ".join(sorted(k for k in updates if k != "updated_at")),
                    request=request)
    return {"ok": True, "applied": {k: v for k, v in updates.items()
                                    if k not in ("updated_at", "updated_by")},
            "rejected": rejected, "effective": await sweep.load_config(db, force=True)}


def _coerce(key: str, value, default):
    """Validate one config value against the shape of its default.

    A threshold of "abc" or -5 must fail loudly at the API boundary: a silently
    coerced 0 would make every target breach, and a silently coerced huge number
    would make the detector deaf. Neither is acceptable for a field that can
    disconnect a customer.
    """
    if isinstance(default, bool):
        return bool(value)
    if isinstance(default, list):
        if not isinstance(value, list):
            raise ValueError("expected a list")
        out = []
        for item in value:
            num = float(item)
            if key.endswith("_hours") and num < 0 and num != -1:
                raise ValueError("hours must be > 0, or -1 for permanent")
            out.append(int(num) if float(num).is_integer() else num)
        if not out:
            raise ValueError("list must not be empty")
        return out
    if isinstance(default, int):
        num = int(value)
        if num < 0:
            raise ValueError("must be >= 0")
        return num
    if isinstance(default, float):
        num = float(value)
        if num < 0:
            raise ValueError("must be >= 0")
        return num
    return value


@router.post("/admin/noc/outbound/mode")
async def outbound_mode_set(payload: dict, request: Request,
                            admin=Depends(require_roles("admin", "support"))):
    db = await _get_db()
    mode = str(payload.get("mode") or "").strip().lower()
    if mode not in ("shadow", "enforce"):
        raise HTTPException(status_code=400, detail="mode must be 'shadow' or 'enforce'")
    if mode == "enforce" and str(payload.get("confirm") or "") != CONFIRM_WORD:
        raise HTTPException(
            status_code=400,
            detail=f"type {CONFIRM_WORD} in 'confirm' to enable automatic blocking")
    if mode == "enforce":
        # Refuse to arm the system when it has no verified place to act. Without
        # this check the first real attack would end in "failed" incidents with
        # no block, which looks identical to the detector being broken.
        devices = await db.mikrotik_devices.find({}).to_list(500)
        ready = [d for d in devices
                 if str(d.get("collection_role") or "").lower() in guard.ENFORCER_ROLES
                 and d.get("block_enabled") is not False]
        if not ready:
            raise HTTPException(
                status_code=409,
                detail="no device has collection_role=enforcer|both; declare one first")
    await db.ddos_detection_config.update_one(
        {"_id": sweep.CONFIG_ID},
        {"$set": {"mode": mode, "mode_changed_at": _now(),
                  "mode_changed_by": getattr(admin, "email", str(admin))}},
        upsert=True)
    sweep.invalidate_config_cache()
    await log_audit(db, actor=admin, action=f"noc.outbound_mode_{mode}",
                    category="noc", target_type="ddos_detection_config",
                    target_id=sweep.CONFIG_ID, target_label=mode, request=request)
    return {"ok": True, "mode": mode,
            "effective": (await sweep.load_config(db, force=True)).get("mode")}


@router.get("/admin/noc/outbound/enforcers")
async def outbound_enforcers(admin=Depends(require_roles("admin", "support"))):
    db = await _get_db()
    devices = await db.mikrotik_devices.find({}).to_list(500)
    prefixes = await db.dcim_prefixes.find({}).to_list(500)
    out = []
    for device in devices:
        role = str(device.get("collection_role") or "none")
        covers = guard.coverage_prefixes(device, prefixes)
        out.append({
            "id": str(device.get("_id") or ""),
            "name": device.get("name") or "",
            "host": device.get("host") or "",
            "role": role,
            "block_enabled": device.get("block_enabled") is not False,
            "priority": int(device.get("priority") or 0),
            "sites": guard.device_sites(device),
            "coverage": covers,
            "coverage_count": len(covers),
            "can_enforce": role in guard.ENFORCER_ROLES and device.get("block_enabled") is not False,
        })
    out.sort(key=lambda d: (not d["can_enforce"], -d["priority"], d["host"]))
    return {"devices": out, "prefix_count": len(prefixes),
            "enforcers": sum(1 for d in out if d["can_enforce"])}


@router.post("/admin/noc/outbound/resolve")
async def outbound_resolve(payload: dict,
                           admin=Depends(require_roles("admin", "support"))):
    """Explain, for one IP, which routers would be tried and why."""
    db = await _get_db()
    target = str(payload.get("target") or "").strip()
    if not target:
        raise HTTPException(status_code=400, detail="target is required")
    devices = await db.mikrotik_devices.find({}).to_list(500)
    prefixes = await db.dcim_prefixes.find({}).to_list(500)
    choices = guard.resolve_enforcers(target, devices, prefixes)
    ip_row = await db.dcim_ips.find_one({"address": target}) or {}
    prefix_row = {}
    if ip_row.get("prefix_id"):
        prefix_row = await db.dcim_prefixes.find_one({"_id": ip_row["prefix_id"]}) or {}
    return {
        "target": target,
        "customer": ip_row.get("customer") or "",
        "hostname": ip_row.get("hostname") or "",
        "prefix": prefix_row.get("prefix") or "",
        "site": prefix_row.get("site") or "",
        "order": [{"device": c.device.get("name") or c.device.get("host"),
                   "host": c.device.get("host") or "",
                   "matched_prefix": c.matched_prefix,
                   "specificity": c.specificity,
                   "reason": c.reason} for c in choices],
        "first": (choices[0].device.get("name") if choices else None),
    }


@router.get("/admin/noc/outbound/shadow")
async def outbound_shadow(limit: int = 100, only_block: bool = False,
                          target: Optional[str] = None,
                          admin=Depends(require_roles("admin", "support"))):
    db = await _get_db()
    query: dict = {}
    if only_block:
        query["would_block"] = True
    if target:
        query["target"] = target
    rows = await db.ddos_outbound_shadow.find(query).sort("at", -1).to_list(
        max(1, min(int(limit or 100), 500)))
    return {"items": [{
        "id": str(r.get("_id")),
        "at": r.get("at"),
        "target": r.get("target"),
        "score": r.get("score"),
        "would_block": bool(r.get("would_block")),
        "reason": r.get("reason"),
        "signals": r.get("signals") or {},
        "metrics": r.get("metrics") or {},
        "mode": r.get("mode"),
    } for r in rows]}


@router.get("/admin/noc/outbound/summary")
async def outbound_summary(hours: int = 24,
                           admin=Depends(require_roles("admin", "support"))):
    """Shadow review stats: how often the detector WOULD have blocked.

    This is the number that decides whether enforcement is safe to arm. A clean
    network should show zero for days; anything more needs the list inspected
    before switching modes.
    """
    db = await _get_db()
    cut = _now() - timedelta(hours=max(1, min(int(hours or 24), 24 * 30)))
    total = await db.ddos_outbound_shadow.count_documents({"at": {"$gte": cut}})
    would = await db.ddos_outbound_shadow.count_documents(
        {"at": {"$gte": cut}, "would_block": True})
    by_target = await db.ddos_outbound_shadow.aggregate([
        {"$match": {"at": {"$gte": cut}, "would_block": True}},
        {"$group": {"_id": "$target", "hits": {"$sum": 1},
                    "max_score": {"$max": "$score"}}},
        {"$sort": {"hits": -1}},
        {"$limit": 25},
    ]).to_list(25)
    return {"hours": hours, "scored_windows": total, "would_block": would,
            "rate": round(would / total, 4) if total else 0.0,
            "top_targets": [{"target": t["_id"], "hits": t["hits"],
                             "max_score": t["max_score"]} for t in by_target],
            "mode": (await sweep.load_config(db)).get("mode")}


@router.post("/admin/noc/outbound/overrides")
async def outbound_override_create(payload: dict, request: Request,
                                   admin=Depends(require_roles("admin", "support"))):
    db = await _get_db()
    target = str(payload.get("target") or "").strip()
    field = str(payload.get("field") or "").strip()
    if not target:
        raise HTTPException(status_code=400, detail="target is required")
    if field not in detect.DEFAULT_CONFIG or field in ("mode", "enabled"):
        raise HTTPException(status_code=400, detail=f"field {field!r} cannot be overridden")
    hours = payload.get("hours")
    doc = {
        "target": target,
        "field": field,
        "value": payload.get("value"),
        "reason": str(payload.get("reason") or "")[:400],
        "created_by": getattr(admin, "email", str(admin)),
        "created_at": _now(),
        "expires_at": (_now() + timedelta(hours=float(hours))) if hours else None,
    }
    r = await db.ddos_detection_overrides.insert_one(doc)
    await log_audit(db, actor=admin, action="noc.outbound_override_created",
                    category="noc", target_type="ddos_detection_override",
                    target_id=str(r.inserted_id), target_label=f"{target}:{field}",
                    request=request)
    return {"ok": True, "id": str(r.inserted_id)}


@router.delete("/admin/noc/outbound/overrides/{oid}")
async def outbound_override_delete(oid: str, request: Request,
                                   admin=Depends(require_roles("admin", "support"))):
    db = await _get_db()
    row = await db.ddos_detection_overrides.find_one({"_id": _oid(oid)})
    if not row:
        raise HTTPException(status_code=404, detail="override not found")
    await db.ddos_detection_overrides.delete_one({"_id": row["_id"]})
    await log_audit(db, actor=admin, action="noc.outbound_override_deleted",
                    category="noc", target_type="ddos_detection_override",
                    target_id=oid, target_label=f"{row.get('target')}:{row.get('field')}",
                    request=request)
    return {"ok": True}


@router.post("/admin/noc/outbound/lift")
async def outbound_lift(payload: dict, request: Request,
                        admin=Depends(require_roles("admin", "support"))):
    """Remove an automated block and verify it is gone from the router."""
    db = await _get_db()
    target = str(payload.get("target") or "").strip()
    if not target:
        raise HTTPException(status_code=400, detail="target is required")
    from ..integrations_v2 import MikrotikClient
    devices = await db.mikrotik_devices.find({}).to_list(500)
    prefixes = await db.dcim_prefixes.find({}).to_list(500)
    choices = guard.resolve_enforcers(target, devices, prefixes)
    results = []
    for choice in choices:
        device = choice.device
        try:
            outcome = guard.remove_block(MikrotikClient(device), target)
        except Exception as exc:  # noqa: BLE001
            outcome = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        results.append({"device": device.get("name") or device.get("host"),
                        "ok": bool(outcome.get("ok")),
                        "removed": outcome.get("removed", 0),
                        "error": outcome.get("error") or ""})
        if outcome.get("removed"):
            break
    cleared = any(r["ok"] and r["removed"] for r in results) or all(r["ok"] for r in results)
    if cleared:
        await db.ddos_incidents.update_many(
            {"target": target, "direction": "outbound",
             "status": {"$in": ["active", "mitigated"]}},
            {"$set": {"status": "resolved", "ended_at": _now().isoformat(),
                      "lifted_by": getattr(admin, "email", str(admin))}})
        await db.blackhole_log.insert_one({
            "prefix": f"{target}/32", "action": "remove", "by": "manual-lift",
            "source": "manual", "device": results[0]["device"] if results else "",
            "ok": True, "at": _now().isoformat()})
    await log_audit(db, actor=admin, action="noc.outbound_lift", category="noc",
                    target_type="ip", target_id=target, target_label=target,
                    request=request)
    return {"ok": cleared, "target": target, "attempts": results}
