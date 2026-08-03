"""Email automation admin: templates, preview, broadcast, logs.

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
from .shared import _get_db, _iso, _now, _oid  # noqa: E402

router = APIRouter()


# ============================================================
# Email Automation - templates, preview, logs, blasts
# ============================================================
from portal import emails as _emails  # noqa: E402


def _serialize_template(t: dict) -> dict:
    return {
        "id": str(t["_id"]),
        "event_key": t.get("event_key", ""),
        "name": t.get("name", ""),
        "subject": t.get("subject", ""),
        "body_html": t.get("body_html", ""),
        "offset_days": t.get("offset_days"),
        "send_time": t.get("send_time"),
        "is_active": t.get("is_active", True),
        "notes": t.get("notes", ""),
        "is_system": t.get("is_system", False),
        "last_sent_at": t.get("last_sent_at"),
        "send_count": t.get("send_count", 0),
        "created_at": _iso(t.get("created_at", "")),
        "updated_at": _iso(t.get("updated_at", "")),
    }


@router.get("/admin/email-templates")
async def admin_email_templates_list(admin=Depends(get_current_admin)):
    db = await _get_db()
    docs = await db.email_templates.find({}).sort("event_key", 1).to_list(500)
    return [_serialize_template(d) for d in docs]


@router.get("/admin/email-templates/{tid}")
async def admin_email_template_get(tid: str, admin=Depends(get_current_admin)):
    db = await _get_db()
    d = await db.email_templates.find_one({"_id": _oid(tid)})
    if not d:
        raise HTTPException(status_code=404, detail="Template not found")
    return _serialize_template(d)


@router.post("/admin/email-templates")
async def admin_email_template_create(payload: m.EmailTemplateIn, admin=Depends(get_current_admin)):
    db = await _get_db()
    if await db.email_templates.find_one({"event_key": payload.event_key}):
        raise HTTPException(status_code=409, detail="A template with this event_key already exists")
    now = _now()
    doc = {**payload.model_dump(), "is_system": False,
           "created_at": now, "updated_at": now,
           "last_sent_at": None, "send_count": 0}
    r = await db.email_templates.insert_one(doc)
    doc["_id"] = r.inserted_id
    return _serialize_template(doc)


@router.put("/admin/email-templates/{tid}")
async def admin_email_template_update(tid: str, payload: m.EmailTemplateIn,
                                      admin=Depends(get_current_admin)):
    db = await _get_db()
    d = await db.email_templates.find_one({"_id": _oid(tid)})
    if not d:
        raise HTTPException(status_code=404, detail="Template not found")
    upd = {**payload.model_dump(), "updated_at": _now()}
    # event_key on system templates is immutable
    if d.get("is_system"):
        upd["event_key"] = d["event_key"]
    await db.email_templates.update_one({"_id": d["_id"]}, {"$set": upd})
    d2 = await db.email_templates.find_one({"_id": d["_id"]})
    return _serialize_template(d2)


@router.delete("/admin/email-templates/{tid}")
async def admin_email_template_delete(tid: str, admin=Depends(get_current_admin)):
    db = await _get_db()
    d = await db.email_templates.find_one({"_id": _oid(tid)})
    if not d:
        raise HTTPException(status_code=404, detail="Template not found")
    if d.get("is_system"):
        raise HTTPException(status_code=400,
                            detail="System templates cannot be deleted - pause them via is_active=false instead")
    await db.email_templates.delete_one({"_id": d["_id"]})
    return {"ok": True}


@router.post("/admin/email-templates/preview")
async def admin_email_template_preview(payload: m.EmailPreviewIn,
                                       admin=Depends(get_current_admin)):
    """Render subject + body against a sample user/invoice/order.

    Priority: use raw subject/body_html from payload if provided; else fall
    back to the referenced template. Returns wrapped HTML ready for iframe.
    """
    db = await _get_db()
    subject = payload.subject or ""
    body = payload.body_html or ""
    if not subject and not body and payload.template_id:
        t = await db.email_templates.find_one({"_id": _oid(payload.template_id)})
        if not t:
            raise HTTPException(status_code=404, detail="Template not found")
        subject = t["subject"]
        body = t["body_html"]

    # Build sample context
    user_doc = None
    inv_doc = None
    order_doc = None
    if payload.sample_user_id:
        user_doc = await db.users.find_one({"_id": _oid(payload.sample_user_id)})
    if payload.sample_invoice_id:
        inv_doc = await db.invoices.find_one({"_id": _oid(payload.sample_invoice_id)})
        if inv_doc and not user_doc:
            user_doc = await db.users.find_one({"_id": inv_doc["user_id"]})
    if payload.sample_order_id:
        order_doc = await db.orders.find_one({"_id": _oid(payload.sample_order_id)})
        if order_doc and not user_doc:
            user_doc = await db.users.find_one({"_id": order_doc["user_id"]})
    if not user_doc:
        # Fall back to a demo shape so template preview always renders.
        user_doc = {"name": "Sample Client", "email": "sample@example.com", "company": "Sample Co"}
    if not inv_doc:
        inv_doc = {"number": "INV-2026-00042", "total": 4500000,
                   "due_date": (datetime.now(timezone.utc) + timedelta(days=3)).date().isoformat(),
                   "status": "unpaid"}
    if not order_doc:
        order_doc = {"product_name": "VPS 4 vCPU / 8 GB RAM", "status": "pending_payment"}
    extra = {
        "reset_url": os.environ.get("REACT_APP_BACKEND_URL", "") + "/portal/reset-password?token=SAMPLE",
        "maintenance": {"title": "Emergency network upgrade",
                        "window": "Sabtu, 15 Feb 2026, 02:00-04:00 WIB",
                        "impact": "Kemungkinan latensi meningkat 5-10 menit."},
        "month": {"name": datetime.now(timezone.utc).strftime("%B %Y")},
    }
    ctx = _emails.build_context(user=user_doc, invoice=inv_doc, order=order_doc, extra=extra)
    rendered_subject = _emails.render(subject, ctx)
    rendered_body = _emails.wrap_html(_emails.render(body, ctx))
    return {"subject": rendered_subject, "body_html": rendered_body}


@router.post("/admin/email-templates/send-test")
async def admin_email_template_send_test(payload: m.EmailSendTestIn,
                                         admin=Depends(get_current_admin)):
    db = await _get_db()
    t = await db.email_templates.find_one({"_id": _oid(payload.template_id)})
    if not t:
        raise HTTPException(status_code=404, detail="Template not found")
    # Render with admin's own context so it looks realistic
    admin_doc = await db.users.find_one({"_id": ObjectId(admin["id"])}) or admin
    inv_doc = {"number": "INV-2026-TEST",
               "total": 1500000,
               "due_date": (datetime.now(timezone.utc) + timedelta(days=3)).date().isoformat(),
               "status": "unpaid",
               "_id": ObjectId()}
    ctx = _emails.build_context(user=admin_doc, invoice=inv_doc, extra={
        "reset_url": os.environ.get("REACT_APP_BACKEND_URL", "") + "/portal/reset-password?token=TEST",
        "maintenance": {"title": "Test maintenance", "window": "Test window", "impact": "None."},
        "month": {"name": datetime.now(timezone.utc).strftime("%B %Y")},
    })
    subject = _emails.render(t["subject"], ctx)
    body = _emails.wrap_html(_emails.render(t["body_html"], ctx))
    res = await _emails.deliver(db, to_email=payload.to_email, subject=subject,
                                body_html=body, event_key=f"test:{t['event_key']}",
                                template_id=str(t["_id"]),
                                user_id=str(admin_doc.get("_id") or ""))
    return {"ok": res.get("status") == "sent", **res, "subject": subject}


@router.post("/admin/email/broadcast")
async def admin_email_broadcast(payload: m.EmailNewsletterIn,
                                admin=Depends(get_current_admin)):
    """One-off broadcast - newsletter / maintenance / arbitrary."""
    db = await _get_db()
    recipients: List[dict] = []
    if payload.audience == "all_clients":
        recipients = await db.users.find({"role": "client", "is_active": {"$ne": False}}).to_list(5000)
    elif payload.audience == "all_users":
        recipients = await db.users.find({"is_active": {"$ne": False}}).to_list(5000)
    elif payload.audience == "custom":
        if not payload.to_emails:
            raise HTTPException(status_code=400, detail="Custom audience requires to_emails[]")
        recipients = [{"email": e, "name": e.split("@")[0], "company": ""} for e in payload.to_emails]

    sent = 0
    failed = 0
    skipped = 0
    for u in recipients:
        ctx = _emails.build_context(user=u, extra={
            "month": {"name": datetime.now(timezone.utc).strftime("%B %Y")},
        })
        subject = _emails.render(payload.subject, ctx)
        body = _emails.wrap_html(_emails.render(payload.body_html, ctx))
        res = await _emails.deliver(db, to_email=u["email"], subject=subject,
                                    body_html=body, event_key="broadcast",
                                    user_id=str(u.get("_id") or "") or None)
        s = res.get("status")
        if s == "sent":
            sent += 1
        elif s == "failed":
            failed += 1
        else:
            skipped += 1
    return {"recipients": len(recipients), "sent": sent, "failed": failed, "skipped": skipped}


@router.get("/admin/email-logs")
async def admin_email_logs(limit: int = 200, admin=Depends(get_current_admin)):
    db = await _get_db()
    docs = await db.email_logs.find({}).sort("created_at", -1).to_list(max(1, min(limit, 1000)))
    out = []
    for d in docs:
        out.append({
            "id": str(d["_id"]),
            "event_key": d.get("event_key", ""),
            "template_id": d.get("template_id"),
            "to_email": d.get("to_email", ""),
            "subject": d.get("subject", ""),
            "status": d.get("status", ""),
            "delivered_via": d.get("delivered_via", ""),
            "error": d.get("error"),
            "sent_at": d.get("sent_at"),
            "invoice_id": d.get("invoice_id"),
            "order_id": d.get("order_id"),
            "user_id": d.get("user_id"),
            "created_at": _iso(d.get("created_at", "")),
        })
    return out


@router.post("/admin/email/run-scheduler-now")
async def admin_email_run_scheduler_now(admin=Depends(get_current_admin)):
    """Fire the invoice-reminder sweep on demand (used by admin UI + tests)."""
    db = await _get_db()
    summary = await _emails.run_invoice_reminder_sweep(db)
    return summary


@router.get("/admin/email/event-catalog")
async def admin_email_event_catalog(admin=Depends(get_current_admin)):
    """Return the canonical list of event keys the frontend can reference."""
    return {
        "events": [
            {"key": "welcome", "label": "Welcome (on registration)", "trigger": "instant"},
            {"key": "order_confirmation", "label": "Order confirmation", "trigger": "instant"},
            {"key": "invoice_generated", "label": "Invoice generated (D-14)", "trigger": "instant"},
            {"key": "invoice_reminder_d3", "label": "Payment reminder - D-3", "trigger": "scheduled",
             "offset_days": -3},
            {"key": "invoice_due", "label": "Payment due today", "trigger": "scheduled", "offset_days": 0},
            {"key": "invoice_overdue_d1", "label": "Overdue - D+1", "trigger": "scheduled", "offset_days": 1},
            {"key": "invoice_overdue_d3", "label": "Overdue - D+3", "trigger": "scheduled", "offset_days": 3},
            {"key": "invoice_overdue_d7", "label": "Overdue - D+7 (final)", "trigger": "scheduled", "offset_days": 7},
            {"key": "service_suspension", "label": "Service suspension - D+8",
             "trigger": "scheduled", "offset_days": 8},
            {"key": "password_reset", "label": "Password reset link", "trigger": "instant"},
            {"key": "maintenance", "label": "Maintenance / downtime", "trigger": "on_demand"},
            {"key": "newsletter", "label": "Newsletter (blast)", "trigger": "on_demand"},
        ],
        "variables": [
            "user.name", "user.email", "user.company",
            "invoice.number", "invoice.total_fmt", "invoice.due_date", "invoice.status",
            "order.id_short", "order.product_name", "order.status",
            "portal.login_url", "portal.invoice_url",
            "reset_url", "maintenance.title", "maintenance.window", "maintenance.impact",
            "month.name",
        ],
    }
