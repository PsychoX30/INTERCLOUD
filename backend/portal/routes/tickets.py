"""Tickets: client + admin ticketing and timelines.

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
from .shared import _get_db, _iso, _next_number, _now, _oid  # noqa: E402
from .users import _paginate  # noqa: E402

router = APIRouter()


# Client tickets
def _deny_creative(user: dict) -> None:
    """Creative role is content-scoped: block billing/CRM/sales surfaces."""
    if user.get("role") == "creative":
        raise HTTPException(status_code=403, detail="Content team only - no billing/CRM access")


async def _serialize_ticket(db, d: dict, include_internal: bool = True) -> dict:
    u = await db.users.find_one({"_id": d["user_id"]}) or {}
    dev_name = None
    if d.get("related_device_id"):
        try:
            dev = await db.mikrotik_devices.find_one({"_id": ObjectId(d["related_device_id"])})
            dev_name = (dev or {}).get("name")
        except Exception:
            dev_name = None
    replies = d.get("replies", [])
    if not include_internal:
        replies = [r for r in replies if not r.get("internal")]
    return {
        "id": str(d["_id"]),
        "number": d.get("number", ""),
        "user_id": str(d["user_id"]),
        "user_name": u.get("name", ""),
        "user_email": u.get("email", ""),
        "subject": d.get("subject", ""),
        "department": d.get("department", "technical"),
        "priority": d.get("priority", "medium"),
        "status": d.get("status", "open"),
        "replies": replies,
        "related_device_id": d.get("related_device_id"),
        "related_device_name": dev_name,
        "created_at": _iso(d.get("created_at", "")),
        "updated_at": _iso(d.get("updated_at", "")),
    }


@router.get("/client/tickets")
async def client_tickets(user=Depends(get_current_user)):
    db = await _get_db()
    docs = await db.tickets.find({"user_id": ObjectId(user["id"])}).sort("updated_at", -1).to_list(500)
    return [await _serialize_ticket(db, d, include_internal=False) for d in docs]


@router.post("/client/tickets")
async def client_create_ticket(payload: m.TicketIn, user=Depends(get_current_user)):
    db = await _get_db()
    now = _now()
    number = await _next_number(db, "tickets", "TCK")
    doc = {
        "user_id": ObjectId(user["id"]),
        "number": number,
        "subject": payload.subject,
        "department": payload.department,
        "priority": payload.priority,
        "status": "open",
        "related_device_id": payload.related_device_id or None,
        "replies": [{
            "author_id": user["id"],
            "author_name": user["name"],
            "author_role": "client",
            "message": payload.message,
            "created_at": now,
        }],
        "created_at": now,
        "updated_at": now,
    }
    r = await db.tickets.insert_one(doc)
    doc["_id"] = r.inserted_id
    return await _serialize_ticket(db, doc)


@router.post("/client/tickets/{tid}/replies")
async def client_reply_ticket(tid: str, payload: m.TicketReplyIn, user=Depends(get_current_user)):
    db = await _get_db()
    d = await db.tickets.find_one({"_id": _oid(tid), "user_id": ObjectId(user["id"])})
    if not d:
        raise HTTPException(status_code=404, detail="Ticket not found")
    reply = {
        "author_id": user["id"],
        "author_name": user["name"],
        "author_role": "client",
        "message": payload.message,
        "created_at": _now(),
    }
    await db.tickets.update_one(
        {"_id": d["_id"]},
        {"$push": {"replies": reply}, "$set": {"status": "awaiting_staff", "updated_at": _now()}},
    )
    d = await db.tickets.find_one({"_id": d["_id"]})
    return await _serialize_ticket(db, d, include_internal=False)


@router.put("/client/tickets/{tid}/close")
async def client_close_ticket(tid: str, user=Depends(get_current_user)):
    """UAT-011: klien dapat menutup tiketnya sendiri."""
    db = await _get_db()
    d = await db.tickets.find_one({"_id": _oid(tid), "user_id": ObjectId(user["id"])})
    if not d:
        raise HTTPException(status_code=404, detail="Ticket not found")
    if d.get("status") == "closed":
        raise HTTPException(status_code=400, detail="Tiket sudah ditutup")
    now = _now()
    await db.tickets.update_one({"_id": d["_id"]}, {
        "$set": {"status": "closed", "closed_at": now, "closed_by": "client", "updated_at": now},
        "$push": {"replies": {"author_id": user["id"], "author_name": user["name"],
                              "author_role": "system",
                              "message": "Tiket ditutup oleh klien.", "created_at": now}},
    })
    d = await db.tickets.find_one({"_id": d["_id"]})
    return await _serialize_ticket(db, d, include_internal=False)


@router.put("/admin/tickets/{tid}/status")
async def admin_ticket_status(tid: str, payload: m.TicketStatusIn, staff=Depends(get_current_staff)):
    """UAT-011: staf dapat mengubah status tiket (termasuk close/resolve)."""
    db = await _get_db()
    d = await db.tickets.find_one({"_id": _oid(tid)})
    if not d:
        raise HTTPException(status_code=404, detail="Ticket not found")
    now = _now()
    upd = {"status": payload.status, "updated_at": now}
    if payload.status == "closed":
        upd["closed_at"] = now
        upd["closed_by"] = "staff"
    await db.tickets.update_one({"_id": d["_id"]}, {
        "$set": upd,
        "$push": {"replies": {"author_id": staff["id"], "author_name": staff["name"],
                              "author_role": "system",
                              "message": f"Status tiket diubah menjadi '{payload.status}' oleh {staff['name']}.",
                              "created_at": now}},
    })
    d = await db.tickets.find_one({"_id": d["_id"]})
    return await _serialize_ticket(db, d)


# Tickets (staff - any staff role can view/reply)
@router.get("/admin/tickets")
async def admin_list_tickets(staff=Depends(get_current_staff),
                             device_id: Optional[str] = None,
                             view: Optional[str] = None,
                             page: Optional[int] = None, limit: int = 25):
    db = await _get_db()
    query: dict = {}
    if device_id:
        query["related_device_id"] = device_id
    if view == "active":
        query["status"] = {"$ne": "closed"}
    elif view == "archive":
        query["status"] = "closed"
    docs = await db.tickets.find(query).sort("updated_at", -1).to_list(2000)
    return _paginate([await _serialize_ticket(db, d) for d in docs], page, limit)


@router.post("/admin/tickets/{tid}/replies")
async def admin_reply_ticket(tid: str, payload: m.TicketReplyIn, staff=Depends(get_current_staff)):
    db = await _get_db()
    d = await db.tickets.find_one({"_id": _oid(tid)})
    if not d:
        raise HTTPException(status_code=404, detail="Ticket not found")
    reply = {
        "author_id": staff["id"],
        "author_name": staff["name"],
        "author_role": staff["role"],
        "message": payload.message,
        "internal": bool(payload.internal),
        "created_at": _now(),
    }
    upd = {"updated_at": _now()}
    if not payload.internal:
        upd["status"] = "awaiting_client"
    await db.tickets.update_one(
        {"_id": d["_id"]},
        {"$push": {"replies": reply}, "$set": upd},
    )
    d = await db.tickets.find_one({"_id": d["_id"]})
    return await _serialize_ticket(db, d)


@router.get("/admin/tickets/{tid}/timeline")
async def admin_ticket_timeline(tid: str, staff=Depends(get_current_staff)):
    """Timeline gabungan: pembuatan tiket, balasan (internal + publik), dan perubahan status."""
    db = await _get_db()
    d = await db.tickets.find_one({"_id": _oid(tid)})
    if not d:
        raise HTTPException(status_code=404, detail="Ticket not found")
    events = [{"kind": "created", "at": _iso(d.get("created_at", "")),
               "actor": d.get("user_name", ""), "message": f"Tiket {d.get('number','')} dibuat."}]
    for r in d.get("replies", []):
        events.append({
            "kind": "status" if r.get("author_role") == "system" else ("internal_note" if r.get("internal") else "reply"),
            "at": _iso(r.get("created_at", "")), "actor": r.get("author_name", ""),
            "role": r.get("author_role", ""), "message": r.get("message", ""),
            "internal": bool(r.get("internal")),
        })
    if d.get("closed_at"):
        events.append({"kind": "closed", "at": _iso(d["closed_at"]),
                       "actor": d.get("closed_by", ""), "message": "Tiket ditutup."})
    events.sort(key=lambda e: e["at"])
    return {"ticket_id": str(d["_id"]), "number": d.get("number", ""), "events": events}


@router.get("/admin/noc/devices/{did}/tickets")
async def admin_tickets_by_device(did: str, staff=Depends(get_current_staff)):
    """Daftar tiket yang terkait dengan sebuah perangkat NOC."""
    db = await _get_db()
    docs = await db.tickets.find({"related_device_id": did}).sort("updated_at", -1).to_list(200)
    return [await _serialize_ticket(db, d) for d in docs]


# ============================================================
# TICKET ↔ DEVICE linking - minimal device options for dropdowns
# ============================================================
@router.get("/tickets/device-options")
async def ticket_device_options(user=Depends(get_current_user)):
    """Names only (no hosts/IPs) so clients can point a ticket at a device."""
    db = await _get_db()
    docs = await db.mikrotik_devices.find({}, {"name": 1}).sort("name", 1).to_list(500)
    return [{"id": str(d["_id"]), "name": d.get("name") or "unnamed"} for d in docs]
