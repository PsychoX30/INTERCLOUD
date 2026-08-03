"""Service lifecycle: admin services, suspend/unsuspend, terminate requests.

Split from the former monolithic routes.py - behavior preserved 1:1.
"""
import os
import asyncio
import logging
import secrets
import re
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket
from bson import ObjectId
from datetime import datetime, timezone, timedelta
from typing import List, Optional

from .. import models as m
from ..auth import (
    verify_password, hash_password, create_access_token,
    get_current_user, get_current_admin, get_current_staff, get_current_content,
    require_roles, sales_can_access,
    STAFF_ROLES, FINANCE_ROLES, BILLING_ROLES, CATALOG_ROLES,
    OPS_ROLES, USER_MGMT_ROLES, TICKET_ROLES, CONTENT_ROLES,
)
from ..audit import log_audit, serialize as _serialize_audit
from ..secretbox import (dec_value as _sb_dec, enc_value as _sb_enc,
                         decrypt_config as _sb_dec_config)
from .. import integrations_v2 as iv2
from .client import _VM_CATEGORIES  # noqa: E402
from .provision import _proxmox_settings_for_service  # noqa: E402
from .shared import _get_db, _load_user, _now, _oid, _sales_scope_filter, _serialize_service  # noqa: E402

router = APIRouter()


@router.get("/admin/services")
async def admin_list_services(admin=Depends(require_roles("admin", "finance", "support"))):
    db = await _get_db()
    docs = await db.services.find({}).sort("created_at", -1).to_list(2000)
    return [_serialize_service(d) for d in docs]


@router.get("/admin/services/{sid}/detail")
async def admin_service_detail(sid: str, admin=Depends(require_roles("admin", "finance", "support"))):
    """Service + client + provisioning trail for the admin detail modal."""
    db = await _get_db()
    d = await db.services.find_one({"_id": _oid(sid)})
    if not d:
        raise HTTPException(status_code=404, detail="Service not found")
    out = _serialize_service(d)
    u = await db.users.find_one({"_id": d["user_id"]}) or {}
    out["user"] = {"name": u.get("name", ""), "email": u.get("email", ""), "company": u.get("company", "")}
    order = None
    if d.get("order_id"):
        try:
            order = await db.orders.find_one({"_id": ObjectId(d["order_id"])})
        except Exception:
            order = None
    out["provision_log"] = (order or {}).get("provision_log", [])
    out["self_service_log"] = (d.get("self_service_log") or [])[-10:]
    out["pending_upgrade"] = d.get("pending_upgrade")
    return out


@router.post("/admin/services")
async def admin_create_service(payload: m.ServiceCreateIn, admin=Depends(get_current_admin)):
    db = await _get_db()
    u = await _load_user(db, payload.user_id)
    prod = await db.products.find_one({"_id": _oid(payload.product_id)})
    if not prod:
        raise HTTPException(status_code=404, detail="Product not found")
    now = datetime.now(timezone.utc)
    doc = {
        "user_id": u["_id"],
        "product_id": prod["_id"],
        "product_name": prod["name"],
        "category": prod.get("category", "other"),
        "name": payload.name,
        "status": payload.status,
        "start_date": now.date().isoformat(),
        "next_renewal": (now + timedelta(days=30)).date().isoformat(),
        "price_monthly": payload.price_monthly or prod.get("price_monthly", 0),
        "config": payload.config,
        "created_at": _now(),
    }
    r = await db.services.insert_one(doc)
    doc["_id"] = r.inserted_id
    return _serialize_service(doc)


# ============================================================
# Manual suspend / unsuspend & permintaan terminate layanan
# ============================================================
async def _service_vm_power(db, svc: dict, action: str) -> str:
    """Best-effort start/stop VM Proxmox milik service. Return keterangan singkat."""
    if svc.get("category") not in _VM_CATEGORIES:
        return "non-VM"
    cfg = svc.get("config") or {}
    node, vmid = cfg.get("node"), cfg.get("vmid")
    if not (node and vmid):
        return "VM tidak tertaut"
    s = await _proxmox_settings_for_service(db, svc)
    if not s:
        return "Proxmox nonaktif"
    try:
        await iv2.ProxmoxClient(s).vm_action(node, int(vmid), action)
        return f"VM {action}"
    except Exception as e:
        return f"VM {action} gagal: {str(e)[:80]}"


@router.post("/admin/services/{sid}/suspend")
async def admin_service_suspend(sid: str, payload: dict, request: Request,
                                staff=Depends(require_roles("admin", "support", "sales"))):
    """Suspend layanan secara manual (mis. toleransi keterlambatan bayar).
    Menonaktifkan self-service klien & mematikan VM (best-effort)."""
    db = await _get_db()
    svc = await db.services.find_one({"_id": _oid(sid)})
    if not svc:
        raise HTTPException(status_code=404, detail="Service not found")
    if not sales_can_access(staff, svc.get("user_id")):
        raise HTTPException(status_code=403, detail="Layanan ini di luar klien yang Anda tangani")
    if svc.get("status") == "suspended":
        raise HTTPException(status_code=400, detail="Layanan sudah dalam status suspended")
    if svc.get("status") == "terminated":
        raise HTTPException(status_code=400, detail="Layanan sudah diterminasi")
    reason = (payload.get("reason") or "").strip() or "Disuspend manual oleh staff"
    vm_note = await _service_vm_power(db, svc, "stop")
    await db.services.update_one({"_id": svc["_id"]}, {"$set": {
        "status": "suspended", "suspended_at": _now(),
        "suspended_reason": reason, "suspended_manual": True,
        "suspended_by": staff.get("email", "")}})
    await log_audit(db, actor=staff, action="service.suspend", category="services",
                    target_type="service", target_id=str(svc["_id"]),
                    target_label=svc.get("name", ""), severity="warning",
                    metadata={"reason": reason, "vm": vm_note}, request=request)

    async def _notify():
        from portal import emails as _em
        u = await db.users.find_one({"_id": svc["user_id"]})
        if u:
            await _em.on_service_lifecycle(db, u, svc, "service_suspended_manual", reason=reason)
    asyncio.create_task(_notify())
    return {"ok": True, "status": "suspended", "vm": vm_note}


@router.post("/admin/services/{sid}/unsuspend")
async def admin_service_unsuspend(sid: str, request: Request,
                                  staff=Depends(require_roles("admin", "support", "sales"))):
    """Aktifkan kembali layanan yang disuspend & nyalakan VM (best-effort)."""
    db = await _get_db()
    svc = await db.services.find_one({"_id": _oid(sid)})
    if not svc:
        raise HTTPException(status_code=404, detail="Service not found")
    if not sales_can_access(staff, svc.get("user_id")):
        raise HTTPException(status_code=403, detail="Layanan ini di luar klien yang Anda tangani")
    if svc.get("status") != "suspended":
        raise HTTPException(status_code=400, detail="Layanan tidak sedang disuspend")
    vm_note = await _service_vm_power(db, svc, "start")
    await db.services.update_one({"_id": svc["_id"]}, {
        "$set": {"status": "active", "reactivated_at": _now(),
                 "reactivated_reason": f"Diaktifkan manual oleh {staff.get('email', 'staff')}"},
        "$unset": {"suspended_at": "", "suspended_reason": "",
                   "suspended_manual": "", "suspended_by": ""}})
    await log_audit(db, actor=staff, action="service.unsuspend", category="services",
                    target_type="service", target_id=str(svc["_id"]),
                    target_label=svc.get("name", ""), severity="warning",
                    metadata={"vm": vm_note}, request=request)

    async def _notify():
        from portal import emails as _em
        u = await db.users.find_one({"_id": svc["user_id"]})
        if u:
            await _em.on_service_lifecycle(db, u, svc, "service_reactivated")
    asyncio.create_task(_notify())
    return {"ok": True, "status": "active", "vm": vm_note}


@router.post("/client/services/{sid}/terminate-request")
async def client_terminate_request(sid: str, payload: dict, request: Request,
                                   user=Depends(get_current_user)):
    """Klien mengajukan permintaan pengakhiran layanan. Perlu persetujuan staff."""
    db = await _get_db()
    svc = await db.services.find_one({"_id": _oid(sid), "user_id": ObjectId(user["id"])})
    if not svc:
        raise HTTPException(status_code=404, detail="Service not found")
    if svc.get("status") == "terminated":
        raise HTTPException(status_code=400, detail="Layanan sudah diterminasi")
    existing = svc.get("termination_request")
    if existing and existing.get("status") == "pending":
        raise HTTPException(status_code=400, detail="Sudah ada permintaan terminate yang menunggu persetujuan")
    reason = (payload.get("reason") or "").strip()
    req = {"status": "pending", "reason": reason, "requested_at": _now(),
           "requested_by": user.get("email", "")}
    await db.services.update_one({"_id": svc["_id"]}, {"$set": {"termination_request": req}})
    await log_audit(db, actor=user, action="service.terminate_request", category="services",
                    target_type="service", target_id=str(svc["_id"]),
                    target_label=svc.get("name", ""), severity="warning",
                    metadata={"reason": reason}, request=request)
    try:
        await db.followups.insert_one({
            "customer_id": None,
            "customer_name": user.get("name", "") or user.get("email", ""),
            "task": (f"Permintaan TERMINATE layanan '{svc.get('name', '')}' oleh "
                     f"{user.get('email', '')}" + (f" - alasan: {reason}" if reason else "")
                     + ". Tinjau di Admin > Active Services."),
            "channel": "internal",
            "due_date": datetime.now(timezone.utc).date().isoformat(),
            "done": False,
            "owner": "auto",
            "created_at": _now(),
        })
    except Exception:
        pass
    return {"ok": True, "termination_request": req}


@router.delete("/client/services/{sid}/terminate-request")
async def client_terminate_request_cancel(sid: str, user=Depends(get_current_user)):
    """Klien membatalkan permintaan terminate yang masih pending."""
    db = await _get_db()
    svc = await db.services.find_one({"_id": _oid(sid), "user_id": ObjectId(user["id"])})
    if not svc:
        raise HTTPException(status_code=404, detail="Service not found")
    req = svc.get("termination_request")
    if not req or req.get("status") != "pending":
        raise HTTPException(status_code=400, detail="Tidak ada permintaan terminate yang pending")
    await db.services.update_one({"_id": svc["_id"]}, {"$unset": {"termination_request": ""}})
    return {"ok": True}


@router.get("/admin/service-requests")
async def admin_service_requests(status: str = "pending",
                                 staff=Depends(require_roles("admin", "support", "sales"))):
    """Daftar permintaan terminate layanan. `status=pending` (default) hanya yang
    menunggu; `status=all` menyertakan riwayat (approved/rejected) untuk tracking."""
    db = await _get_db()
    if status == "all":
        query = {"termination_request": {"$exists": True, "$ne": None}}
    else:
        query = {"termination_request.status": "pending"}
    # Sales hanya melihat permintaan dari klien yang mereka tangani.
    query.update(_sales_scope_filter(staff))
    docs = await db.services.find(query).to_list(1000)
    out = []
    for d in docs:
        u = await db.users.find_one({"_id": d["user_id"]}) or {}
        item = _serialize_service(d)
        item["termination_request"] = d.get("termination_request")
        item["user"] = {"name": u.get("name", ""), "email": u.get("email", ""),
                        "company": u.get("company", "")}
        out.append(item)
    # Urutkan: pending dulu, lalu berdasarkan waktu permintaan terbaru.
    out.sort(key=lambda x: (
        0 if (x.get("termination_request") or {}).get("status") == "pending" else 1,
        (x.get("termination_request") or {}).get("requested_at", "")), reverse=False)
    return out


@router.post("/admin/services/{sid}/terminate-request/approve")
async def admin_terminate_approve(sid: str, payload: dict, request: Request,
                                  staff=Depends(require_roles("admin", "support", "sales"))):
    """Setujui permintaan terminate: hentikan VM (best-effort) & tandai terminated."""
    db = await _get_db()
    svc = await db.services.find_one({"_id": _oid(sid)})
    if not svc:
        raise HTTPException(status_code=404, detail="Service not found")
    if not sales_can_access(staff, svc.get("user_id")):
        raise HTTPException(status_code=403, detail="Layanan ini di luar klien yang Anda tangani")
    req = svc.get("termination_request") or {}
    if req.get("status") != "pending":
        raise HTTPException(status_code=400, detail="Tidak ada permintaan terminate yang pending")
    vm_note = await _service_vm_power(db, svc, "stop")
    req.update({"status": "approved", "resolved_at": _now(),
                "resolved_by": staff.get("email", ""),
                "note": (payload.get("note") or "").strip()})
    await db.services.update_one({"_id": svc["_id"]}, {"$set": {
        "status": "terminated", "terminated_at": _now(),
        "terminated_reason": req.get("reason") or "Permintaan klien disetujui",
        "auto_renew": False, "termination_request": req}})
    await log_audit(db, actor=staff, action="service.terminate_approve", category="services",
                    target_type="service", target_id=str(svc["_id"]),
                    target_label=svc.get("name", ""), severity="warning",
                    metadata={"vm": vm_note}, request=request)

    async def _notify():
        from portal import emails as _em
        u = await db.users.find_one({"_id": svc["user_id"]})
        if u:
            await _em.on_service_lifecycle(db, u, svc, "service_termination_approved",
                                           note=req.get("note", ""))
    asyncio.create_task(_notify())
    return {"ok": True, "status": "terminated", "vm": vm_note}


@router.post("/admin/services/{sid}/terminate-request/reject")
async def admin_terminate_reject(sid: str, payload: dict, request: Request,
                                 staff=Depends(require_roles("admin", "support", "sales"))):
    """Tolak permintaan terminate: layanan tetap aktif."""
    db = await _get_db()
    svc = await db.services.find_one({"_id": _oid(sid)})
    if not svc:
        raise HTTPException(status_code=404, detail="Service not found")
    if not sales_can_access(staff, svc.get("user_id")):
        raise HTTPException(status_code=403, detail="Layanan ini di luar klien yang Anda tangani")
    req = svc.get("termination_request") or {}
    if req.get("status") != "pending":
        raise HTTPException(status_code=400, detail="Tidak ada permintaan terminate yang pending")
    req.update({"status": "rejected", "resolved_at": _now(),
                "resolved_by": staff.get("email", ""),
                "note": (payload.get("note") or "").strip()})
    await db.services.update_one({"_id": svc["_id"]}, {"$set": {"termination_request": req}})
    await log_audit(db, actor=staff, action="service.terminate_reject", category="services",
                    target_type="service", target_id=str(svc["_id"]),
                    target_label=svc.get("name", ""), severity="info",
                    metadata={"note": req.get("note", "")}, request=request)

    async def _notify():
        from portal import emails as _em
        u = await db.users.find_one({"_id": svc["user_id"]})
        if u:
            await _em.on_service_lifecycle(db, u, svc, "service_termination_rejected",
                                           note=req.get("note", ""))
    asyncio.create_task(_notify())
    return {"ok": True, "status": svc.get("status", "active")}
