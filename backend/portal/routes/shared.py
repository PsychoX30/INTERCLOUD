"""Shared helpers, serializers and security utilities used across route modules.

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


# ---------- helpers ----------
def _iso(dt: datetime | str) -> str:
    if isinstance(dt, str):
        return dt
    return dt.isoformat()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _user_public(u: dict) -> dict:
    return {
        "id": str(u["_id"]) if "_id" in u else u["id"],
        "email": u["email"],
        "name": u.get("name", ""),
        "role": u["role"],
        "company": u.get("company"),
        "phone": u.get("phone"),
        "created_at": _iso(u.get("created_at", _now())),
        "assigned_client_ids": [str(x) for x in (u.get("assigned_client_ids") or [])],
        "twofa_enabled": bool(u.get("totp_enabled")),
        "billing_emails": list(u.get("billing_emails") or []),
        "attention": u.get("attention"),
        "address_line1": u.get("address_line1"),
        "address_line2": u.get("address_line2"),
        "city": u.get("city"),
        "province": u.get("province"),
        "postal_code": u.get("postal_code"),
        "country": u.get("country") or "Indonesia",
        "npwp": u.get("npwp"),
        "menu_keys": u.get("menu_keys"),
        "feature_flags": list(u.get("feature_flags") or []),
        "is_active": u.get("is_active", True),
        "must_change_password": bool(u.get("must_change_password", False)),
    }


async def _get_db():
    from server import db
    return db


async def _load_user(db, user_id: str) -> dict:
    try:
        u = await db.users.find_one({"_id": ObjectId(user_id)})
    except Exception:
        u = None
    if not u:
        raise HTTPException(status_code=404, detail="User not found")
    return u


def _oid(id_str: str) -> ObjectId:
    try:
        return ObjectId(id_str)
    except Exception:
        raise HTTPException(status_code=400, detail=f"Invalid id: {id_str}")


def _sales_scope_filter(staff: dict, key: str = "user_id") -> dict:
    """Return an extra Mongo filter clause that restricts sales to their
    assigned clients. Returns {} for non-sales roles (no restriction).

    For sales with an empty assignment list we deliberately match nothing so
    the endpoint returns an empty list rather than leaking global data.
    """
    if staff.get("role") != "sales":
        return {}
    assigned = staff.get("assigned_client_ids") or []
    if not assigned:
        return {"_id": None}  # matches nothing
    return {key: {"$in": [ObjectId(x) for x in assigned]}}


async def _sales_visible_crm_ids(db, staff: dict) -> list | None:
    """Return the list of crm_customers._id that a sales staff can access.

    Returns None if the staff is not a sales role (i.e., no restriction).
    For sales, we consider a CRM row "theirs" if its `user_id` is in their
    assigned_client_ids. This is what powers scoping on the Follow-ups table.
    """
    if staff.get("role") != "sales":
        return None
    assigned = [ObjectId(x) for x in (staff.get("assigned_client_ids") or [])]
    if not assigned:
        return []
    cur = db.crm_customers.find({"user_id": {"$in": assigned}}, {"_id": 1})
    return [d["_id"] async for d in cur]


async def _next_number(db, coll: str, prefix: str) -> str:
    """Race-safe sequential document numbering via an atomic counter doc.
    The old count_documents()+1 approach produced duplicate numbers (and 500s
    on the unique index) under concurrent creation."""
    from pymongo import ReturnDocument
    year = datetime.now(timezone.utc).year
    key = f"number:{coll}"
    doc = await db.counters.find_one_and_update(
        {"_id": key}, {"$inc": {"seq": 1}},
        upsert=True, return_document=ReturnDocument.AFTER,
    )
    seq = int(doc["seq"])
    if seq == 1:
        # First use on an existing dataset: fast-forward past legacy numbers.
        last = await db[coll].find_one({"number": {"$regex": f"^{prefix}-"}},
                                       sort=[("number", -1)])
        if last:
            try:
                legacy = int(str(last.get("number", "")).rsplit("-", 1)[-1])
            except (TypeError, ValueError):
                legacy = await db[coll].count_documents({})
            if legacy >= seq:
                doc = await db.counters.find_one_and_update(
                    {"_id": key}, {"$max": {"seq": legacy + 1}},
                    return_document=ReturnDocument.AFTER,
                )
                seq = int(doc["seq"])
    return f"{prefix}-{year}-{seq:05d}"


async def _insert_numbered(db, coll: str, prefix: str, doc: dict):
    """Insert a document carrying a unique sequential `number`.
    Retries with a fresh number on the (rare) DuplicateKeyError - e.g. when a
    DB restore rolls the counter back underneath concurrent writers."""
    from pymongo.errors import DuplicateKeyError
    for _ in range(5):
        doc["number"] = await _next_number(db, coll, prefix)
        try:
            r = await db[coll].insert_one(doc)
            doc["_id"] = r.inserted_id
            return doc
        except DuplicateKeyError:
            # Fast-forward the counter past the current max and retry
            last = await db[coll].find_one({"number": {"$regex": f"^{prefix}-"}},
                                           sort=[("number", -1)])
            if last:
                try:
                    legacy = int(str(last.get("number", "")).rsplit("-", 1)[-1])
                    await db.counters.update_one({"_id": f"number:{coll}"},
                                                 {"$max": {"seq": legacy}}, upsert=True)
                except (TypeError, ValueError):
                    pass
            doc.pop("_id", None)
    raise HTTPException(status_code=500, detail=f"Could not allocate a unique {prefix} number")


async def _mark_overdue(db):
    """Auto-mark unpaid invoices past due as 'overdue'."""
    today = datetime.now(timezone.utc).date().isoformat()
    await db.invoices.update_many(
        {"status": "unpaid", "due_date": {"$lt": today}},
        {"$set": {"status": "overdue"}},
    )


# ---------- Global settings helpers (settings collection: {key, value}) ----------
async def _get_setting_value(db, key: str, default=None):
    doc = await db.settings.find_one({"key": key})
    return doc.get("value") if doc and "value" in doc else default


async def _set_setting_value(db, key: str, value) -> None:
    await db.settings.update_one(
        {"key": key},
        {"$set": {"key": key, "value": value, "updated_at": _now()}},
        upsert=True,
    )


# Billing defaults - `default_tax_percent` is only ever a SUGGESTED initial
# value pre-filled into invoice/quotation forms and the renewal auto-invoice
# generator. It is stored per-document and stays fully manual/overridable
# (down to 0). Nothing ever recalculates tax_percent after creation.
BILLING_SETTING_DEFAULTS = {
    "default_tax_percent": 11.0,
    "renewal_lead_days": 7,
    "enable_extra_payment_gateways": False,
    "noc_alert_recipients": [],
}


# Extra gateways stay implemented (classes untouched in integrations_v2) but
# hidden from all admin/client surfaces unless the flag above is turned on.
_EXTRA_PAYMENT_MODULES = {"midtrans", "xendit"}


async def _log_login_attempt(db, *, email: str, action: str, success: bool, reason: str,
                             ip: str, user_agent: str = "", recaptcha_score: float | None = None,
                             recaptcha_enabled: bool = False):
    """Append a document to `login_attempts` for the Security Analytics dashboard.
    Best-effort - never raise into the caller. On failure, also runs auto-block check."""
    try:
        await db.login_attempts.insert_one({
            "email": (email or "").lower(),
            "action": action,
            "success": bool(success),
            "reason": reason,
            "ip": ip or "unknown",
            "user_agent": user_agent[:400],
            "recaptcha_enabled": bool(recaptcha_enabled),
            "recaptcha_score": recaptcha_score,
            "created_at": _now(),
        })
        if not success and ip and ip != "unknown":
            await _maybe_auto_block(db, ip)
    except Exception:
        logging.getLogger("portal.security").warning("[login_attempts] insert failed for %s", email)


DEFAULT_SECURITY_SETTINGS = {
    "auto_block_enabled": True,
    "fail_threshold": 10,        # failures to trigger a block
    "window_minutes": 15,        # sliding window to count failures
    "ban_minutes": 30,           # block duration
    "notify_emails": [],         # recipients for block notifications
    "whitelist_ips": [],         # IPs / CIDRs that are never blocked
    "email_notify_enabled": True,
    "telegram_notify_enabled": True,
}


def _ip_in_whitelist(ip: str, whitelist: list[str]) -> bool:
    """Return True if `ip` matches any entry in the whitelist. Entries may be
    exact IPs, CIDR ranges, or hostnames (exact string match fallback)."""
    if not ip or not whitelist:
        return False
    import ipaddress as _ipaddr
    try:
        target = _ipaddr.ip_address(ip)
    except ValueError:
        target = None
    for raw in whitelist:
        entry = (raw or "").strip()
        if not entry:
            continue
        if entry == ip:
            return True
        if target is None:
            continue
        try:
            if "/" in entry:
                if target in _ipaddr.ip_network(entry, strict=False):
                    return True
            else:
                if target == _ipaddr.ip_address(entry):
                    return True
        except ValueError:
            continue
    return False


async def _get_security_settings(db) -> dict:
    doc = await db.settings.find_one({"_id": "security"})
    if not doc:
        return dict(DEFAULT_SECURITY_SETTINGS)
    merged = dict(DEFAULT_SECURITY_SETTINGS)
    merged.update({k: v for k, v in doc.items() if k != "_id"})
    return merged


async def _maybe_auto_block(db, ip: str):
    """After each failed login, check if this IP has crossed the threshold and,
    if so, upsert a `blocked_ips` doc + emit a `security_notifications` event."""
    s = await _get_security_settings(db)
    if not s.get("auto_block_enabled", True):
        return
    if _ip_in_whitelist(ip, s.get("whitelist_ips") or []):
        return
    window_iso = (datetime.now(timezone.utc) - timedelta(minutes=int(s["window_minutes"]))).isoformat()
    fails = await db.login_attempts.count_documents({
        "ip": ip, "success": False, "created_at": {"$gte": window_iso},
    })
    if fails < int(s["fail_threshold"]):
        return
    now_dt = datetime.now(timezone.utc)
    expires = now_dt + timedelta(minutes=int(s["ban_minutes"]))
    # Only insert a notification if this IP wasn't already actively blocked
    existing = await db.blocked_ips.find_one({"ip": ip})
    existing_exp = existing.get("expires_at") if existing else None
    # Normalize both string ISO and naive-datetime forms to offset-aware.
    if isinstance(existing_exp, str):
        try:
            existing_exp = datetime.fromisoformat(existing_exp.replace("Z", "+00:00"))
        except Exception:
            existing_exp = None
    if isinstance(existing_exp, datetime) and existing_exp.tzinfo is None:
        existing_exp = existing_exp.replace(tzinfo=timezone.utc)
    if existing and existing_exp and existing_exp > now_dt and not existing.get("unblocked_at"):
        # Extend the ban by another window
        await db.blocked_ips.update_one({"ip": ip}, {"$set": {
            "expires_at": expires, "hits": fails, "last_seen_at": now_dt.isoformat(),
        }})
        return
    await db.blocked_ips.update_one(
        {"ip": ip},
        {"$set": {
            "ip": ip,
            "blocked_at": now_dt.isoformat(),
            "expires_at": expires,
            "reason": "auto_block_threshold",
            "hits": fails,
            "unblocked_at": None,
        }},
        upsert=True,
    )
    await db.security_notifications.insert_one({
        "kind": "ip_auto_blocked",
        "ip": ip,
        "hits": fails,
        "window_minutes": int(s["window_minutes"]),
        "ban_minutes": int(s["ban_minutes"]),
        "created_at": now_dt.isoformat(),
        "read": False,
    })
    # Fire-and-forget alerts - never let a mail/Telegram outage break /auth/login
    try:
        import asyncio as _asyncio
        _asyncio.create_task(_dispatch_block_alerts(db, ip, fails, int(s["ban_minutes"]), s))
    except Exception:
        pass


async def _dispatch_block_alerts(db, ip: str, hits: int, ban_minutes: int, settings: dict):
    """Best-effort: send email(s) via SMTP + a Telegram DM.
    Runs in the background - failures are swallowed."""
    log = logging.getLogger("portal.security")
    from portal import integrations_v2 as _iv2

    now_iso = datetime.now(timezone.utc).isoformat()
    subject = f"[Security] IP {ip} auto-blocked - {hits} failed logins"
    text = (f"An IP has been auto-blocked by the portal.\n\n"
            f"IP:      {ip}\n"
            f"Hits:    {hits} failed logins within window\n"
            f"Blocked: {ban_minutes} minute(s)\n"
            f"Time:    {now_iso}\n\n"
            f"Unblock via Admin ▸ Security ▸ Blocked IPs, or DELETE "
            f"/api/portal/admin/security/blocked-ips/{ip}")
    html = (f"<h3>IP auto-blocked</h3>"
            f"<p>An IP has been auto-blocked by the portal.</p>"
            f"<ul>"
            f"<li><b>IP:</b> <code>{ip}</code></li>"
            f"<li><b>Failed logins:</b> {hits}</li>"
            f"<li><b>Blocked for:</b> {ban_minutes} minute(s)</li>"
            f"<li><b>Time:</b> {now_iso}</li>"
            f"</ul>"
            f"<p>Unblock via <b>Admin ▸ Security ▸ Blocked IPs</b>.</p>")

    # Email dispatch
    if settings.get("email_notify_enabled", True):
        recipients = [r for r in (settings.get("notify_emails") or []) if r]
        smtp_doc = await _iv2.get_settings(db, "smtp")
        if smtp_doc and smtp_doc.get("enabled") and recipients:
            try:
                mailer = _iv2.SMTPMailer(smtp_doc)
                loop = __import__("asyncio").get_event_loop()
                for to in recipients:
                    try:
                        await loop.run_in_executor(None, lambda t=to: mailer.send(
                            to=t, subject=subject, html=html, text=text))
                    except Exception as e:
                        log.warning("[security] email to %s failed: %s", to, e)
            except Exception as e:
                log.warning("[security] SMTP init failed: %s", e)

    # Telegram dispatch
    if settings.get("telegram_notify_enabled", True):
        tg_doc = await _iv2.get_telegram_settings(db)
        if tg_doc:
            try:
                tg = _iv2.TelegramNotifier(tg_doc)
                await tg.send(
                    f"*⛔ IP auto-blocked*\n"
                    f"`{ip}` after *{hits}* failed logins\n"
                    f"Ban duration: *{ban_minutes} min*"
                )
            except Exception as e:
                log.warning("[security] Telegram send failed: %s", e)


async def _is_ip_blocked(db, ip: str) -> bool:
    if not ip or ip == "unknown":
        return False
    # Whitelist short-circuit - makes the guard idempotent even if a stale
    # block doc still exists for an IP that was just added to the whitelist.
    s = await _get_security_settings(db)
    if _ip_in_whitelist(ip, s.get("whitelist_ips") or []):
        return False
    now_dt = datetime.now(timezone.utc)
    doc = await db.blocked_ips.find_one({"ip": ip, "unblocked_at": None})
    if not doc:
        return False
    expires_at = doc.get("expires_at")
    # Support both ISO strings and datetime objects
    if isinstance(expires_at, str):
        try:
            expires_at = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        except Exception:
            return False
    # MongoDB returns naive UTC datetimes - normalize to offset-aware.
    if isinstance(expires_at, datetime) and expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at and expires_at > now_dt:
        return True
    return False


from portal.security import (
    limiter as _rl_limiter,
    AUTH_LOGIN_LIMIT, AUTH_REGISTER_LIMIT,
    AUTH_FORGOT_LIMIT, AUTH_RESET_LIMIT, PUBLIC_STATUS_LIMIT,
)


async def _serialize_invoice(db, d: dict) -> dict:
    u = await db.users.find_one({"_id": d["user_id"]}) or {}
    pay_token = d.get("pay_token")
    if not pay_token:
        pay_token = secrets.token_urlsafe(24)
        await db.invoices.update_one({"_id": d["_id"]}, {"$set": {"pay_token": pay_token}})
    credit_applied = await _sum_applied_credit(db, d["_id"])
    total = float(d.get("total") or 0)
    return {
        "pay_token": pay_token,
        "credit_applied": credit_applied,
        "amount_due": 0.0 if d.get("status") == "paid" else max(0.0, total - credit_applied),
        "id": str(d["_id"]),
        "number": d["number"],
        "user_id": str(d["user_id"]),
        "user_name": u.get("name", ""),
        "user_email": u.get("email", ""),
        "items": d.get("items", []),
        "subtotal": d.get("subtotal", 0),
        "tax_percent": d.get("tax_percent"),
        "tax_amount": d.get("tax_amount", 0),
        "total": d.get("total", 0),
        "due_date": d.get("due_date", ""),
        "status": d.get("status", "unpaid"),
        "payment_method": d.get("payment_method"),
        "paid_at": d.get("paid_at"),
        "payment_link": d.get("payment_link"),
        "payment_ref": d.get("payment_ref"),
        "service_id": d.get("service_id"),
        "order_id": d.get("order_id"),
        "renewal_period": d.get("renewal_period"),
        "created_at": _iso(d.get("created_at", "")),
        "notes": d.get("notes", ""),
        "source_quotation_id": d.get("source_quotation_id"),
        "source_quotation_number": d.get("source_quotation_number"),
    }


# Services (admin)
def _serialize_service(d: dict) -> dict:
    return {
        "id": str(d["_id"]),
        "user_id": str(d["user_id"]),
        "product_id": str(d["product_id"]),
        "product_name": d.get("product_name", ""),
        "category": d.get("category", ""),
        "name": d.get("name", ""),
        "status": d.get("status", "active"),
        "start_date": d.get("start_date", ""),
        "next_renewal": d.get("next_renewal", ""),
        "price_monthly": d.get("price_monthly", 0),
        "config": d.get("config", {}),
        "order_id": d.get("order_id"),
        "termination_request": d.get("termination_request"),
        "suspended_reason": d.get("suspended_reason", ""),
        "suspended_manual": d.get("suspended_manual", False),
    }


async def _sum_applied_credit(db, invoice_id: ObjectId) -> float:
    """Sum of `amount` from applied credit notes for a given invoice."""
    cur = db.credit_notes.find({"invoice_id": invoice_id, "status": "applied"},
                               {"amount": 1})
    total = 0.0
    async for d in cur:
        total += float(d.get("amount") or 0)
    return total


# ============================================================
# Outstanding-amount helper for InvoiceOut serialization
# ============================================================
async def _invoice_outstanding(db, invoice: dict) -> float:
    """Invoice total minus applied credit notes. Never negative."""
    if invoice.get("status") == "paid":
        return 0.0
    total = float(invoice.get("total") or 0)
    applied = await _sum_applied_credit(db, invoice["_id"])
    return max(0.0, total - applied)
