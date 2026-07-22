"""All portal routes (auth + client + admin) under /api/portal."""
import os
from fastapi import APIRouter, Depends, HTTPException, Request
from bson import ObjectId
from datetime import datetime, timezone, timedelta
from typing import List, Optional

from . import models as m
from .auth import (
    verify_password, hash_password, create_access_token,
    get_current_user, get_current_admin, get_current_staff,
    require_roles, sales_can_access,
    STAFF_ROLES, FINANCE_ROLES, BILLING_ROLES, CATALOG_ROLES,
    OPS_ROLES, USER_MGMT_ROLES, TICKET_ROLES,
)

router = APIRouter(prefix="/api/portal")


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


async def _next_number(db, coll: str, prefix: str) -> str:
    year = datetime.now(timezone.utc).year
    count = await db[coll].count_documents({}) + 1
    return f"{prefix}-{year}-{count:05d}"


async def _mark_overdue(db):
    """Auto-mark unpaid invoices past due as 'overdue'."""
    today = datetime.now(timezone.utc).date().isoformat()
    await db.invoices.update_many(
        {"status": "unpaid", "due_date": {"$lt": today}},
        {"$set": {"status": "overdue"}},
    )


# ============================================================
# AUTH
# ============================================================
@router.get("/auth/config")
async def auth_config():
    """Public config exposed to unauthenticated login/register pages.

    Frontend uses this to decide whether to load the Google reCAPTCHA v3
    script and which site_key to pass to `grecaptcha.execute()`.
    Secrets are never included here.
    """
    db = await _get_db()
    from portal import integrations_v2 as _iv2
    doc = await _iv2.get_recaptcha_settings(db)
    if not doc:
        return {"recaptcha": {"enabled": False, "site_key": None}}
    site_key = ((doc.get("credentials") or {}).get("site_key") or "").strip()
    return {
        "recaptcha": {
            "enabled": bool(site_key),
            "site_key": site_key or None,
        }
    }


async def _log_login_attempt(db, *, email: str, action: str, success: bool, reason: str,
                             ip: str, user_agent: str = "", recaptcha_score: float | None = None,
                             recaptcha_enabled: bool = False):
    """Append a document to `login_attempts` for the Security Analytics dashboard.
    Best-effort — never raise into the caller. On failure, also runs auto-block check."""
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
        import logging
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
    # Fire-and-forget alerts — never let a mail/Telegram outage break /auth/login
    try:
        import asyncio as _asyncio
        _asyncio.create_task(_dispatch_block_alerts(db, ip, fails, int(s["ban_minutes"]), s))
    except Exception:
        pass


async def _dispatch_block_alerts(db, ip: str, hits: int, ban_minutes: int, settings: dict):
    """Best-effort: send email(s) via SMTP + a Telegram DM.
    Runs in the background — failures are swallowed."""
    import logging
    log = logging.getLogger("portal.security")
    from portal import integrations_v2 as _iv2

    now_iso = datetime.now(timezone.utc).isoformat()
    subject = f"[Security] IP {ip} auto-blocked — {hits} failed logins"
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
    # Whitelist short-circuit — makes the guard idempotent even if a stale
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
    # MongoDB returns naive UTC datetimes — normalize to offset-aware.
    if isinstance(expires_at, datetime) and expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at and expires_at > now_dt:
        return True
    return False


@router.post("/auth/login", response_model=m.LoginOut)
async def login(payload: m.LoginIn, request: Request):
    db = await _get_db()
    from portal import integrations_v2 as _iv2
    ip = request.client.host if request.client else "unknown"
    ua = request.headers.get("user-agent", "")
    email = payload.email.lower().strip()

    # Auto-block short-circuit
    if await _is_ip_blocked(db, ip):
        raise HTTPException(status_code=429, detail="IP temporarily blocked due to repeated failures")

    recap_doc = await _iv2.get_recaptcha_settings(db)
    recap_score = None

    if recap_doc:
        try:
            result = await _iv2.RecaptchaV3Verifier(recap_doc).verify(
                payload.recaptcha_token, "login", ip
            )
            recap_score = float(result.get("score", 0.0))
        except HTTPException as e:
            reason = ("recaptcha_missing" if "Missing" in str(e.detail)
                      else "recaptcha_low_score" if getattr(e, "status_code", 0) == 403
                      else "recaptcha_failed")
            await _log_login_attempt(db, email=email, action="login", success=False, reason=reason,
                                     ip=ip, user_agent=ua, recaptcha_enabled=True,
                                     recaptcha_score=recap_score)
            raise

    u = await db.users.find_one({"email": email})
    if not u or not verify_password(payload.password, u["password_hash"]):
        await _log_login_attempt(db, email=email, action="login", success=False,
                                 reason="invalid_credentials", ip=ip, user_agent=ua,
                                 recaptcha_enabled=bool(recap_doc), recaptcha_score=recap_score)
        raise HTTPException(status_code=401, detail="Invalid email or password")
    token = create_access_token(str(u["_id"]), u["email"], u["role"])
    await _log_login_attempt(db, email=email, action="login", success=True, reason="ok",
                             ip=ip, user_agent=ua, recaptcha_enabled=bool(recap_doc),
                             recaptcha_score=recap_score)
    return {"token": token, "user": _user_public(u)}


async def _upsert_crm_from_user(db, u: dict, *, status: str = "prospect", extra_notes: str = "") -> None:
    """Ensure a matching row exists in `crm_customers` for the given user.

    Matches on email (case-insensitive). If the CRM row already exists,
    refresh a small set of contact fields but never downgrade its status.
    """
    email = (u.get("email") or "").lower()
    if not email:
        return
    existing = await db.crm_customers.find_one({"email": email})
    now = _now()
    payload = {
        "name": u.get("name", ""),
        "email": email,
        "phone": u.get("phone", ""),
        "company": u.get("company", ""),
        "updated_at": now,
    }
    if existing:
        # Never downgrade a manually-set status; keep as-is
        payload.pop("email", None)
        if u.get("_id"):
            payload["user_id"] = u["_id"]
        await db.crm_customers.update_one({"_id": existing["_id"]}, {"$set": payload})
        return
    payload.update({
        "position": "",
        "industry": u.get("industry") or "",
        "status": status,
        "notes": extra_notes,
        "user_id": u.get("_id"),
        "source": "self_registration" if status == "prospect" else "admin_registered",
        "created_at": now,
    })
    await db.crm_customers.insert_one(payload)


@router.post("/auth/register", response_model=m.LoginOut)
async def register(payload: m.RegisterIn, request: Request):
    """Public self-registration endpoint.

    Creates a `client` user, mirrors them into `crm_customers` (as a
    `prospect`), and returns a signed JWT so the browser can auto-login.
    """
    db = await _get_db()
    from portal import integrations_v2 as _iv2
    await _iv2.enforce_recaptcha(
        db, payload.recaptcha_token, "register",
        request.client.host if request.client else None,
    )
    email = payload.email.lower().strip()

    if not payload.accepts_tos:
        raise HTTPException(status_code=400, detail="You must accept the Terms of Service to register")

    if await db.users.find_one({"email": email}):
        raise HTTPException(status_code=409, detail="An account already exists for this email")

    doc = {
        "email": email,
        "password_hash": hash_password(payload.password),
        "name": payload.name.strip(),
        "role": "client",
        "company": payload.company,
        "phone": payload.phone,
        "assigned_client_ids": [],
        "billing_emails": [],
        "attention": payload.attention or payload.name.strip(),
        "address_line1": payload.address_line1,
        "address_line2": payload.address_line2,
        "city": payload.city,
        "province": payload.province,
        "postal_code": payload.postal_code,
        "country": payload.country or "Indonesia",
        "npwp": payload.npwp,
        "industry": payload.industry,
        "created_at": _now(),
    }
    r = await db.users.insert_one(doc)
    doc["_id"] = r.inserted_id

    # Mirror into CRM as a prospect
    try:
        await _upsert_crm_from_user(db, doc, status="prospect",
                                    extra_notes="Registered via portal self-signup")
    except Exception:
        # CRM mirroring must never block registration
        pass

    # Fire welcome email (best-effort — never blocks registration)
    try:
        from portal import emails as _em
        await _em.on_user_registered(db, doc)
    except Exception:
        pass

    token = create_access_token(str(doc["_id"]), doc["email"], doc["role"])
    return {"token": token, "user": _user_public(doc)}


@router.get("/auth/me", response_model=m.UserOut)
async def me(user=Depends(get_current_user)):
    return user


# ============================================================
# CLIENT
# ============================================================
@router.get("/client/dashboard")
async def client_dashboard(user=Depends(get_current_user)):
    db = await _get_db()
    await _mark_overdue(db)
    uid = ObjectId(user["id"])
    services_count = await db.services.count_documents({"user_id": uid, "status": "active"})
    unpaid = await db.invoices.count_documents({"user_id": uid, "status": "unpaid"})
    overdue = await db.invoices.count_documents({"user_id": uid, "status": "overdue"})
    open_tickets = await db.tickets.count_documents(
        {"user_id": uid, "status": {"$in": ["open", "awaiting_client", "awaiting_staff"]}}
    )
    # Overdue invoice summary
    overdue_docs = await db.invoices.find({"user_id": uid, "status": "overdue"}).to_list(20)
    overdue_total = sum(d.get("total", 0) for d in overdue_docs)
    return {
        "stats": {
            "active_services": services_count,
            "unpaid_invoices": unpaid,
            "overdue_invoices": overdue,
            "open_tickets": open_tickets,
            "overdue_total": overdue_total,
        },
    }


@router.get("/client/services")
async def client_services(user=Depends(get_current_user)):
    db = await _get_db()
    docs = await db.services.find({"user_id": ObjectId(user["id"])}).sort("created_at", -1).to_list(500)
    result = []
    for d in docs:
        result.append({
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
        })
    return result


@router.get("/client/services/{sid}")
async def client_service_detail(sid: str, user=Depends(get_current_user)):
    db = await _get_db()
    d = await db.services.find_one({"_id": _oid(sid), "user_id": ObjectId(user["id"])})
    if not d:
        raise HTTPException(status_code=404, detail="Service not found")
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
    }


async def _serialize_invoice(db, d: dict) -> dict:
    u = await db.users.find_one({"_id": d["user_id"]}) or {}
    return {
        "id": str(d["_id"]),
        "number": d["number"],
        "user_id": str(d["user_id"]),
        "user_name": u.get("name", ""),
        "user_email": u.get("email", ""),
        "items": d.get("items", []),
        "subtotal": d.get("subtotal", 0),
        "tax_amount": d.get("tax_amount", 0),
        "total": d.get("total", 0),
        "due_date": d.get("due_date", ""),
        "status": d.get("status", "unpaid"),
        "payment_method": d.get("payment_method"),
        "paid_at": d.get("paid_at"),
        "created_at": _iso(d.get("created_at", "")),
        "notes": d.get("notes", ""),
    }


@router.get("/client/invoices")
async def client_invoices(user=Depends(get_current_user)):
    db = await _get_db()
    await _mark_overdue(db)
    docs = await db.invoices.find({"user_id": ObjectId(user["id"])}).sort("created_at", -1).to_list(500)
    return [await _serialize_invoice(db, d) for d in docs]


@router.get("/client/invoices/{iid}")
async def client_invoice_detail(iid: str, user=Depends(get_current_user)):
    db = await _get_db()
    await _mark_overdue(db)
    d = await db.invoices.find_one({"_id": _oid(iid), "user_id": ObjectId(user["id"])})
    if not d:
        raise HTTPException(status_code=404, detail="Invoice not found")
    return await _serialize_invoice(db, d)


@router.post("/client/orders")
async def create_order(payload: m.OrderIn, user=Depends(get_current_user)):
    db = await _get_db()
    prod = await db.products.find_one({"_id": _oid(payload.product_id)})
    if not prod or prod.get("is_addon"):
        raise HTTPException(status_code=404, detail="Product not found")

    # Price the cart from the selected options + add-ons.
    selections_data = [s.model_dump() for s in (payload.selections or [])]
    cart = await _price_cart(
        db, product=prod,
        selections=selections_data,
        addon_ids=payload.addon_ids or [],
    )

    # 1. Create the order
    doc = {
        "user_id": ObjectId(user["id"]),
        "user_name": user["name"],
        "user_email": user["email"],
        "product_id": prod["_id"],
        "product_name": prod["name"],
        "notes": payload.notes,
        "config": payload.config,
        "selections": selections_data,
        "addon_ids": [ObjectId(x) for x in (payload.addon_ids or [])],
        "cart_snapshot": cart,   # audit — the price shown to the user at confirm time
        "billing_cycle": payload.billing_cycle or prod.get("billing_cycle", "monthly"),
        "status": "pending_payment",
        "assigned_admin_id": None,
        "invoice_id": None,
        "service_id": None,
        "provision_log": [{"at": _now(), "step": "order_created", "message": "Order placed by client."}],
        "created_at": _now(),
    }
    r = await db.orders.insert_one(doc)
    doc["_id"] = r.inserted_id

    # 2. Auto-create an invoice for the order (14-day due window)
    items = []
    # Base line — first billing period
    base_line = cart["base_line"]
    if base_line["monthly"]:
        items.append({
            "description": f"{prod['name']} — first month",
            "qty": 1, "unit_price": base_line["monthly"], "total": base_line["monthly"],
        })
    if base_line["setup"]:
        items.append({
            "description": f"{prod['name']} — setup fee",
            "qty": 1, "unit_price": base_line["setup"], "total": base_line["setup"],
        })
    # Configurable option lines
    for ol in cart["option_lines"]:
        if ol.get("monthly"):
            items.append({
                "description": f"{ol['group_label']}: {ol['choice']} — monthly",
                "qty": 1, "unit_price": ol["monthly"], "total": ol["monthly"],
            })
        if ol.get("setup"):
            items.append({
                "description": f"{ol['group_label']}: {ol['choice']} — setup",
                "qty": 1, "unit_price": ol["setup"], "total": ol["setup"],
            })
    # Add-on lines
    for al in cart["addon_lines"]:
        if al.get("monthly"):
            items.append({
                "description": f"Add-on: {al['name']} — monthly",
                "qty": 1, "unit_price": al["monthly"], "total": al["monthly"],
            })
        if al.get("setup"):
            items.append({
                "description": f"Add-on: {al['name']} — setup",
                "qty": 1, "unit_price": al["setup"], "total": al["setup"],
            })

    if not items:
        # Custom quote / firewall — mark order as needing manual quotation, no auto-invoice
        await db.orders.update_one({"_id": doc["_id"]}, {"$set": {"status": "awaiting_quote"}})
        doc["status"] = "awaiting_quote"
        doc["provision_log"].append({"at": _now(), "step": "awaiting_quote", "message": "Custom-priced product; sales will send a quotation."})
    else:
        line_subtotal = sum(i["total"] for i in items)
        tax = round(line_subtotal * 0.11, 2)
        total = round(line_subtotal + tax, 2)
        due = (datetime.now(timezone.utc) + timedelta(days=14)).date().isoformat()
        number = await _next_number(db, "invoices", "INV")
        inv = {
            "number": number,
            "user_id": ObjectId(user["id"]),
            "items": items,
            "subtotal": line_subtotal,
            "tax_percent": 11,
            "tax_amount": tax,
            "total": total,
            "due_date": due,
            "status": "unpaid",
            "payment_method": None,
            "paid_at": None,
            "notes": f"Auto-generated from order for {prod['name']}.",
            "order_id": str(doc["_id"]),
            "created_at": _now(),
        }
        ir = await db.invoices.insert_one(inv)
        await db.orders.update_one(
            {"_id": doc["_id"]},
            {"$set": {"invoice_id": ir.inserted_id},
             "$push": {"provision_log": {"at": _now(), "step": "invoice_created", "message": f"Invoice {number} generated ({total:,.0f} IDR)."}}},
        )
        doc["invoice_id"] = ir.inserted_id
        doc["provision_log"].append({"at": _now(), "step": "invoice_created", "message": f"Invoice {number} generated ({total:,.0f} IDR)."})

    # Fire order + invoice notification emails (best-effort — never blocks the order)
    try:
        from portal import emails as _em
        user_doc = await db.users.find_one({"_id": ObjectId(user["id"])}) or {"email": user["email"], "name": user["name"]}
        await _em.on_order_created(db, doc, user_doc)
        if doc.get("invoice_id"):
            inv_doc = await db.invoices.find_one({"_id": doc["invoice_id"]})
            if inv_doc:
                await _em.on_invoice_generated(db, inv_doc, user_doc, order_doc=doc)
    except Exception:
        pass

    return _serialize_order(doc)


def _serialize_order(d: dict) -> dict:
    return {
        "id": str(d["_id"]),
        "user_id": str(d["user_id"]),
        "user_name": d.get("user_name", ""),
        "user_email": d.get("user_email", ""),
        "product_id": str(d["product_id"]),
        "product_name": d.get("product_name", ""),
        "notes": d.get("notes", ""),
        "config": d.get("config", {}),
        "status": d.get("status", "pending"),
        "assigned_admin_id": str(d["assigned_admin_id"]) if d.get("assigned_admin_id") else None,
        "invoice_id": str(d["invoice_id"]) if d.get("invoice_id") else None,
        "service_id": str(d["service_id"]) if d.get("service_id") else None,
        "provision_log": d.get("provision_log", []),
        "created_at": _iso(d.get("created_at", "")),
    }


async def _auto_provision(db, order: dict) -> dict:
    """Actually run auto-provisioning based on product category.
    Returns the created service (or None if manual setup is required).
    Currently uses realistic mocked module calls — swap for real cPanel/Plesk/
    Proxmox API calls once credentials are wired via /admin/integrations.
    """
    prod = await db.products.find_one({"_id": order["product_id"]})
    if not prod:
        return None
    cat = prod.get("category", "other")
    now = datetime.now(timezone.utc)
    cfg = dict(order.get("config", {}))

    # Append a provision log entry
    async def _log(step, msg):
        await db.orders.update_one(
            {"_id": order["_id"]},
            {"$push": {"provision_log": {"at": _now(), "step": step, "message": msg}}},
        )

    await _log("provisioning_started", f"Provisioning started for category '{cat}'.")

    if cat in ("hosting",):
        # cPanel/Plesk auto-account
        module = await db.integrations.find_one({"module": {"$in": ["cpanel", "plesk"]}, "status": "enabled"})
        provider = module["module"] if module else "cpanel"
        cfg.setdefault("control_panel", "cPanel/WHM" if provider == "cpanel" else "Plesk")
        cfg.setdefault("hostname", f"{order['user_email'].split('@')[0]}.icd-cust.net")
        cfg.setdefault("ip", "103.28.14." + str((hash(str(order["_id"])) % 240) + 10))
        await _log("panel_account_created", f"{provider.upper()} account provisioned (mock).")
    elif cat in ("vps", "cloud"):
        module = await db.integrations.find_one({"module": "proxmox", "status": "enabled"})
        cfg.setdefault("node", (module or {}).get("config", {}).get("default_node") or "prox-jkt-05")
        cfg.setdefault("os", cfg.get("os") or "Ubuntu 22.04 LTS Server")
        cfg.setdefault("hostname", f"vm-{str(order['_id'])[-6:]}.icd-cust.net")
        cfg.setdefault("ip", "103.28.14." + str((hash(str(order["_id"])) % 240) + 10))
        await _log("vm_created", f"Proxmox VM created on {cfg['node']} with {cfg['os']} (mock).")
    elif cat in ("dedicated", "colocation", "interconnect", "firewall", "lease"):
        # These need manual DC/network setup — mark the service as provisioning
        cfg.setdefault("rack", "TBD by NOC")
        await _log("manual_setup_required", "Requires physical / network setup by NOC team.")
    else:
        await _log("manual_setup_required", "Category needs manual handling.")

    svc = {
        "user_id": order["user_id"],
        "product_id": prod["_id"],
        "product_name": prod["name"],
        "category": cat,
        "name": f"{prod['name']} — {order.get('user_name','')}",
        "status": "active" if cat in ("hosting", "vps", "cloud") else "pending",
        "start_date": now.date().isoformat(),
        "next_renewal": (now + timedelta(days=30)).date().isoformat(),
        "price_monthly": prod.get("price_monthly", 0),
        "config": cfg,
        "order_id": str(order["_id"]),
        "created_at": _now(),
    }
    sr = await db.services.insert_one(svc)
    await db.orders.update_one(
        {"_id": order["_id"]},
        {"$set": {"service_id": sr.inserted_id, "status": "active" if svc["status"] == "active" else "provisioning"},
         "$push": {"provision_log": {"at": _now(), "step": "service_handover", "message": "Service delivered to client dashboard."}}},
    )
    return svc


@router.get("/client/orders")
async def client_orders(user=Depends(get_current_user)):
    db = await _get_db()
    docs = await db.orders.find({"user_id": ObjectId(user["id"])}).sort("created_at", -1).to_list(500)
    return [_serialize_order(d) for d in docs]


# Client tickets
async def _serialize_ticket(db, d: dict) -> dict:
    u = await db.users.find_one({"_id": d["user_id"]}) or {}
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
        "replies": d.get("replies", []),
        "created_at": _iso(d.get("created_at", "")),
        "updated_at": _iso(d.get("updated_at", "")),
    }


@router.get("/client/tickets")
async def client_tickets(user=Depends(get_current_user)):
    db = await _get_db()
    docs = await db.tickets.find({"user_id": ObjectId(user["id"])}).sort("updated_at", -1).to_list(500)
    return [await _serialize_ticket(db, d) for d in docs]


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
    return await _serialize_ticket(db, d)


# ============================================================
# ADMIN
# ============================================================
@router.get("/admin/dashboard")
async def admin_dashboard(staff=Depends(get_current_staff)):
    db = await _get_db()
    await _mark_overdue(db)
    total_users = await db.users.count_documents({"role": "client"})
    active_services = await db.services.count_documents({"status": "active"})
    open_tickets = await db.tickets.count_documents(
        {"status": {"$in": ["open", "awaiting_staff"]}}
    )

    stats = {
        "total_clients": total_users,
        "active_services": active_services,
        "open_tickets": open_tickets,
    }

    if staff["role"] in FINANCE_ROLES:
        unpaid = await db.invoices.count_documents({"status": "unpaid"})
        overdue = await db.invoices.count_documents({"status": "overdue"})
        pending_orders = await db.orders.count_documents({"status": "pending"})

        now = datetime.now(timezone.utc)
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()
        paid_docs = await db.invoices.find(
            {"status": "paid", "paid_at": {"$gte": month_start}}
        ).to_list(1000)
        revenue_month = sum(d.get("total", 0) for d in paid_docs)
        all_paid = await db.invoices.find({"status": "paid"}).to_list(5000)
        revenue_total = sum(d.get("total", 0) for d in all_paid)
        overdue_docs = await db.invoices.find({"status": "overdue"}).to_list(1000)
        overdue_total = sum(d.get("total", 0) for d in overdue_docs)
        stats.update({
            "unpaid_invoices": unpaid,
            "overdue_invoices": overdue,
            "pending_orders": pending_orders,
            "revenue_month": revenue_month,
            "revenue_total": revenue_total,
            "overdue_total": overdue_total,
        })

    return {"stats": stats, "role": staff["role"]}


# Menu catalog (used by the Admin User Access modal to render per-menu checkboxes).
# The frontend PortalLayout.jsx must import ADMIN_MENU_CATALOG matching these keys.
ADMIN_MENU_CATALOG = [
    {"key": "dashboard",       "label": "Dashboard",        "group": "Overview",       "default_roles": ["admin", "sales", "support", "ticket_only"]},
    {"key": "orders",          "label": "Orders",           "group": "Sales & Billing", "default_roles": ["admin", "sales"]},
    {"key": "invoices",        "label": "Invoices",         "group": "Sales & Billing", "default_roles": ["admin"]},
    {"key": "quotations",      "label": "Quotations",       "group": "Sales & Billing", "default_roles": ["admin", "sales"]},
    {"key": "finance",         "label": "Finance",          "group": "Sales & Billing", "default_roles": ["admin"]},
    {"key": "assets",          "label": "Assets",           "group": "Sales & Billing", "default_roles": ["admin"]},
    {"key": "products",        "label": "Products",         "group": "Catalog",        "default_roles": ["admin", "support"]},
    {"key": "addons",          "label": "Add-ons",          "group": "Catalog",        "default_roles": ["admin", "support"]},
    {"key": "categories",      "label": "Categories",       "group": "Catalog",        "default_roles": ["admin"]},
    {"key": "services",        "label": "Services",         "group": "Catalog",        "default_roles": ["admin", "sales", "support"]},
    {"key": "users",           "label": "Users / Clients",  "group": "Support & CRM",  "default_roles": ["admin", "sales"]},
    {"key": "tickets",         "label": "Tickets",          "group": "Support & CRM",  "default_roles": ["admin", "sales", "support", "ticket_only"]},
    {"key": "mail",            "label": "Webmail",          "group": "Support & CRM",  "default_roles": ["admin", "sales", "support"]},
    {"key": "email",           "label": "Email Automation", "group": "Support & CRM",  "default_roles": ["admin", "support"]},
    {"key": "articles",        "label": "Articles",         "group": "Support & CRM",  "default_roles": ["admin", "sales", "support"]},
    {"key": "provisioning",    "label": "Provisioning",     "group": "Operations",     "default_roles": ["admin", "support"]},
    {"key": "mikrotik",        "label": "MikroTik Ops",     "group": "Operations",     "default_roles": ["admin", "support"]},
    {"key": "dcim",            "label": "DCIM & IPAM",      "group": "Operations",     "default_roles": ["admin", "support"]},
    {"key": "diagnostics",     "label": "Diagnostics",      "group": "Operations",     "default_roles": ["admin", "sales", "support"]},
    {"key": "crm",             "label": "Customer DB (CRM)","group": "Business",       "default_roles": ["admin", "sales"]},
    {"key": "projects",        "label": "Project Tracker",  "group": "Business",       "default_roles": ["admin", "sales", "support"]},
    {"key": "content",         "label": "Content Planner",  "group": "Business",       "default_roles": ["admin", "sales"]},
    {"key": "followups",       "label": "Follow-ups",       "group": "Business",       "default_roles": ["admin", "sales"]},
    {"key": "documents",       "label": "Documents",        "group": "Business",       "default_roles": ["admin", "sales", "support"]},
    {"key": "integrations",    "label": "Integrations",     "group": "System",         "default_roles": ["admin"]},
    {"key": "user_settings",   "label": "User Settings",    "group": "System",         "default_roles": ["admin"]},
]


FEATURE_FLAG_CATALOG = [
    {"key": "can_delete_invoices",   "label": "Can permanently delete invoices"},
    {"key": "can_delete_users",      "label": "Can delete user accounts"},
    {"key": "can_edit_dcim_devices", "label": "Can edit DCIM devices (racks / equipment)"},
    {"key": "can_edit_ip_prefixes",  "label": "Can allocate & edit IP prefixes"},
    {"key": "can_run_provisioning",  "label": "Can trigger auto-provisioning manually"},
    {"key": "can_view_assets",       "label": "Can view finance Assets & depreciation"},
    {"key": "can_impersonate_client","label": "Can impersonate a client for support"},
    {"key": "can_export_data",       "label": "Can export CRM / invoices to CSV"},
]


@router.get("/admin/user-access-catalog")
async def admin_user_access_catalog(admin=Depends(get_current_admin)):
    """Returns everything the User Access UI needs to render checkboxes.

    - `menu_catalog`: list of menu keys with human labels & the default roles that
      have access to each menu (used to show the default vs. the override).
    - `feature_flags`: list of extra per-user feature toggles.
    """
    return {
        "menu_catalog": ADMIN_MENU_CATALOG,
        "feature_flags": FEATURE_FLAG_CATALOG,
    }


@router.get("/admin/users")
async def admin_list_users(staff=Depends(get_current_staff)):
    """Sales sees only their assigned clients; other staff see all."""
    db = await _get_db()
    if staff["role"] == "sales":
        ids = [ObjectId(x) for x in (staff.get("assigned_client_ids") or [])]
        docs = await db.users.find({"_id": {"$in": ids}}).to_list(500) if ids else []
    else:
        docs = await db.users.find({}).sort("created_at", -1).to_list(1000)
    return [_user_public(u) for u in docs]


@router.get("/admin/users/{uid}")
async def admin_get_user(uid: str, staff=Depends(get_current_staff)):
    db = await _get_db()
    if staff["role"] == "sales" and not sales_can_access(staff, uid):
        raise HTTPException(status_code=403, detail="Not your client")
    u = await _load_user(db, uid)
    return _user_public(u)


@router.post("/admin/users", response_model=m.UserOut)
async def admin_create_user(payload: m.UserCreateIn, admin=Depends(get_current_admin)):
    db = await _get_db()
    email = payload.email.lower().strip()
    if await db.users.find_one({"email": email}):
        raise HTTPException(status_code=409, detail="Email already registered")
    doc = {
        "email": email,
        "password_hash": hash_password(payload.password),
        "name": payload.name,
        "role": payload.role,
        "company": payload.company,
        "phone": payload.phone,
        "assigned_client_ids": [ObjectId(x) for x in (payload.assigned_client_ids or [])],
        "billing_emails": payload.billing_emails or [],
        "attention": payload.attention,
        "address_line1": payload.address_line1,
        "address_line2": payload.address_line2,
        "city": payload.city,
        "province": payload.province,
        "postal_code": payload.postal_code,
        "country": payload.country or "Indonesia",
        "npwp": payload.npwp,
        "menu_keys": payload.menu_keys,
        "feature_flags": payload.feature_flags or [],
        "is_active": payload.is_active,
        "created_at": _now(),
    }
    r = await db.users.insert_one(doc)
    doc["_id"] = r.inserted_id
    # Mirror this new user into CRM (as "existing" client — admin-created)
    if payload.role == "client":
        try:
            await _upsert_crm_from_user(db, doc, status="existing",
                                        extra_notes="Registered by admin from Users console")
        except Exception:
            pass
        try:
            from portal import emails as _em
            await _em.on_user_registered(db, doc)
        except Exception:
            pass
    return _user_public(doc)


@router.put("/admin/users/{uid}", response_model=m.UserOut)
async def admin_update_user(uid: str, payload: m.UserUpdateIn, admin=Depends(get_current_admin)):
    db = await _get_db()
    upd = {}
    for k in ("name", "role", "company", "phone", "billing_emails",
              "attention", "address_line1", "address_line2", "city",
              "province", "postal_code", "country", "npwp",
              "menu_keys", "feature_flags", "is_active"):
        v = getattr(payload, k, None)
        if v is not None:
            upd[k] = v
    if payload.assigned_client_ids is not None:
        upd["assigned_client_ids"] = [ObjectId(x) for x in payload.assigned_client_ids]
    if payload.password:
        upd["password_hash"] = hash_password(payload.password)
    if upd:
        await db.users.update_one({"_id": _oid(uid)}, {"$set": upd})
    u = await _load_user(db, uid)
    return _user_public(u)


@router.delete("/admin/users/{uid}")
async def admin_delete_user(uid: str, admin=Depends(get_current_admin)):
    db = await _get_db()
    if str(admin["id"]) == uid:
        raise HTTPException(status_code=400, detail="You cannot delete yourself")
    r = await db.users.delete_one({"_id": _oid(uid)})
    return {"deleted": r.deleted_count}


# Client-side billing email preferences
@router.get("/client/billing-emails")
async def client_billing_emails(user=Depends(get_current_user)):
    db = await _get_db()
    u = await db.users.find_one({"_id": ObjectId(user["id"])})
    return {"billing_emails": list(u.get("billing_emails") or [])}


@router.put("/client/billing-emails")
async def client_update_billing_emails(payload: m.BillingEmailsIn, user=Depends(get_current_user)):
    db = await _get_db()
    emails = [str(e).lower() for e in payload.billing_emails]
    await db.users.update_one(
        {"_id": ObjectId(user["id"])},
        {"$set": {"billing_emails": emails}},
    )
    return {"billing_emails": emails}


# Products
def _serialize_product(d: dict) -> dict:
    return {
        "id": str(d["_id"]),
        "name": d["name"],
        "category": d.get("category", "other"),
        "description": d.get("description", ""),
        "price_monthly": d.get("price_monthly", 0),
        "setup_fee": d.get("setup_fee", 0),
        "billing_cycle": d.get("billing_cycle", "monthly"),
        "features": d.get("features", []),
        "is_active": d.get("is_active", True),
        "is_addon": d.get("is_addon", False),
        "applies_to_product_ids": [str(x) for x in (d.get("applies_to_product_ids") or [])],
        "applies_to_categories": list(d.get("applies_to_categories") or []),
        "option_groups": list(d.get("option_groups") or []),
        "stock_qty": d.get("stock_qty"),
        "sort_order": d.get("sort_order", 100),
        "created_at": _iso(d.get("created_at", "")),
    }


DEFAULT_CATEGORIES = [
    {"slug": "cloud",        "label": "Cloud",        "icon": "Cloud",       "sort_order": 10},
    {"slug": "vps",          "label": "VPS",          "icon": "Server",      "sort_order": 20},
    {"slug": "hosting",      "label": "Web Hosting",  "icon": "Globe",       "sort_order": 30},
    {"slug": "dedicated",    "label": "Dedicated",    "icon": "HardDrive",   "sort_order": 40},
    {"slug": "colocation",   "label": "Colocation",   "icon": "Building2",   "sort_order": 50},
    {"slug": "firewall",     "label": "Firewall",     "icon": "Shield",      "sort_order": 60},
    {"slug": "interconnect", "label": "Interconnect", "icon": "Network",     "sort_order": 70},
    {"slug": "lease",        "label": "Lease-to-Own", "icon": "Package",     "sort_order": 80},
    {"slug": "domain",       "label": "Domains",      "icon": "Globe2",      "sort_order": 90},
    {"slug": "other",        "label": "Other",        "icon": "Boxes",       "sort_order": 999},
]


async def _ensure_default_categories(db):
    for c in DEFAULT_CATEGORIES:
        if not await db.categories.find_one({"slug": c["slug"]}):
            await db.categories.insert_one({
                **c, "description": "", "is_active": True,
                "created_at": _now(),
            })


def _serialize_category(d: dict, product_count: int = 0) -> dict:
    return {
        "id": str(d["_id"]),
        "slug": d["slug"],
        "label": d.get("label", d["slug"]),
        "description": d.get("description", ""),
        "icon": d.get("icon", ""),
        "sort_order": d.get("sort_order", 100),
        "is_active": d.get("is_active", True),
        "product_count": product_count,
        "created_at": _iso(d.get("created_at", "")),
    }


@router.get("/admin/categories")
async def admin_list_categories(staff=Depends(get_current_staff)):
    db = await _get_db()
    await _ensure_default_categories(db)
    docs = await db.categories.find({}).sort("sort_order", 1).to_list(500)
    # Product counts
    counts = {}
    async for c in db.products.aggregate([
        {"$group": {"_id": "$category", "n": {"$sum": 1}}},
    ]):
        counts[c["_id"]] = c["n"]
    return [_serialize_category(d, counts.get(d["slug"], 0)) for d in docs]


@router.get("/portal-public/categories")
async def public_categories():
    db = await _get_db()
    await _ensure_default_categories(db)
    docs = await db.categories.find({"is_active": True}).sort("sort_order", 1).to_list(500)
    return [_serialize_category(d) for d in docs]


@router.post("/admin/categories")
async def admin_create_category(payload: m.CategoryIn, admin=Depends(get_current_admin)):
    db = await _get_db()
    slug = payload.slug.lower().strip()
    if await db.categories.find_one({"slug": slug}):
        raise HTTPException(status_code=409, detail=f"Category '{slug}' already exists")
    doc = payload.model_dump()
    doc["slug"] = slug
    doc["created_at"] = _now()
    r = await db.categories.insert_one(doc)
    doc["_id"] = r.inserted_id
    return _serialize_category(doc)


@router.put("/admin/categories/{cid}")
async def admin_update_category(cid: str, payload: m.CategoryIn, admin=Depends(get_current_admin)):
    db = await _get_db()
    slug = payload.slug.lower().strip()
    current = await db.categories.find_one({"_id": _oid(cid)})
    if not current:
        raise HTTPException(status_code=404, detail="Category not found")
    # If slug changed, cascade-update all products
    if slug != current["slug"]:
        if await db.categories.find_one({"slug": slug, "_id": {"$ne": _oid(cid)}}):
            raise HTTPException(status_code=409, detail=f"Category '{slug}' already exists")
        await db.products.update_many({"category": current["slug"]}, {"$set": {"category": slug}})
    upd = payload.model_dump()
    upd["slug"] = slug
    await db.categories.update_one({"_id": _oid(cid)}, {"$set": upd})
    d = await db.categories.find_one({"_id": _oid(cid)})
    return _serialize_category(d)


@router.delete("/admin/categories/{cid}")
async def admin_delete_category(cid: str, admin=Depends(get_current_admin)):
    db = await _get_db()
    d = await db.categories.find_one({"_id": _oid(cid)})
    if not d:
        raise HTTPException(status_code=404, detail="Category not found")
    if await db.products.count_documents({"category": d["slug"]}) > 0:
        raise HTTPException(status_code=400, detail="Cannot delete: products still use this category. Reassign them first.")
    r = await db.categories.delete_one({"_id": _oid(cid)})
    return {"deleted": r.deleted_count}


@router.get("/admin/products")
async def admin_list_products(admin=Depends(get_current_admin)):
    db = await _get_db()
    docs = await db.products.find({}).sort([("sort_order", 1), ("created_at", -1)]).to_list(500)
    return [_serialize_product(d) for d in docs]


@router.get("/portal-public/products")
async def public_products():
    """Products list — public catalog used by client order flow."""
    db = (await _get_db())
    docs = await db.products.find({"is_active": True, "is_addon": {"$ne": True}}).sort([("sort_order", 1), ("category", 1)]).to_list(500)
    return [_serialize_product(d) for d in docs]


@router.get("/portal-public/addons")
async def public_addons():
    """Add-on products — used by client Order flow to attach to a base product."""
    db = (await _get_db())
    docs = await db.products.find({"is_active": True, "is_addon": True}).sort([("sort_order", 1), ("name", 1)]).to_list(500)
    return [_serialize_product(d) for d in docs]


@router.post("/admin/products", response_model=m.ProductOut)
async def admin_create_product(payload: m.ProductIn, admin=Depends(get_current_admin)):
    db = await _get_db()
    doc = payload.model_dump()
    doc["created_at"] = _now()
    r = await db.products.insert_one(doc)
    doc["_id"] = r.inserted_id
    return _serialize_product(doc)


@router.put("/admin/products/{pid}", response_model=m.ProductOut)
async def admin_update_product(pid: str, payload: m.ProductIn, admin=Depends(get_current_admin)):
    db = await _get_db()
    await db.products.update_one({"_id": _oid(pid)}, {"$set": payload.model_dump()})
    d = await db.products.find_one({"_id": _oid(pid)})
    if not d:
        raise HTTPException(status_code=404, detail="Product not found")
    return _serialize_product(d)


@router.delete("/admin/products/{pid}")
async def admin_delete_product(pid: str, admin=Depends(get_current_admin)):
    db = await _get_db()
    r = await db.products.delete_one({"_id": _oid(pid)})
    return {"deleted": r.deleted_count}


# ============================================================
# ORDER PREVIEW — build a WHMCS-style price cart WITHOUT persisting
# ============================================================

async def _price_cart(db, *, product: dict, selections: list, addon_ids: list, tax_percent: float = 11.0) -> dict:
    """Compute a full price breakdown from a product + option selections + add-ons."""
    base_monthly = float(product.get("price_monthly") or 0)
    base_setup = float(product.get("setup_fee") or 0)
    lines_options = []      # [{group_key, group_label, choice, monthly, setup}]
    monthly_options_sum = 0.0
    setup_options_sum = 0.0

    groups_by_key = {g.get("key"): g for g in (product.get("option_groups") or [])}
    for sel in (selections or []):
        gk = sel.get("group_key") if isinstance(sel, dict) else sel.group_key
        grp = groups_by_key.get(gk)
        if not grp:
            continue
        gtype = grp.get("type", "dropdown")
        glabel = grp.get("label", gk)
        if gtype == "quantity":
            qty = int((sel.get("quantity") if isinstance(sel, dict) else sel.quantity) or 0)
            if qty <= 0:
                continue
            unit_m = float(grp.get("unit_price_monthly") or 0)
            unit_s = float(grp.get("unit_price_setup") or 0)
            m_total = qty * unit_m
            s_total = qty * unit_s
            unit = grp.get("unit_label") or ""
            lines_options.append({
                "group_key": gk, "group_label": glabel,
                "choice": f"{qty} {unit}".strip(),
                "monthly": m_total, "setup": s_total,
            })
            monthly_options_sum += m_total
            setup_options_sum += s_total
        else:
            labels = (sel.get("option_labels") if isinstance(sel, dict) else sel.option_labels) or []
            for opt_lbl in labels:
                opt = next((o for o in (grp.get("options") or []) if o.get("label") == opt_lbl), None)
                if not opt:
                    continue
                m_delta = float(opt.get("price_monthly_delta") or 0)
                s_delta = float(opt.get("price_setup_delta") or 0)
                lines_options.append({
                    "group_key": gk, "group_label": glabel,
                    "choice": opt_lbl, "monthly": m_delta, "setup": s_delta,
                })
                monthly_options_sum += m_delta
                setup_options_sum += s_delta

    # Add-ons
    addon_lines = []
    if addon_ids:
        addon_docs = await db.products.find({"_id": {"$in": [_oid(x) for x in addon_ids]}, "is_addon": True}).to_list(50)
        for a in addon_docs:
            addon_lines.append({
                "id": str(a["_id"]),
                "name": a["name"],
                "monthly": float(a.get("price_monthly") or 0),
                "setup": float(a.get("setup_fee") or 0),
            })

    subtotal_monthly = base_monthly + monthly_options_sum + sum(x["monthly"] for x in addon_lines)
    setup_total = base_setup + setup_options_sum + sum(x["setup"] for x in addon_lines)
    # First-invoice basis = first month + setup fees
    first_invoice_subtotal = subtotal_monthly + setup_total
    tax_amount = round(first_invoice_subtotal * (tax_percent / 100.0), 2)
    total = round(first_invoice_subtotal + tax_amount, 2)
    return {
        "base_line": {
            "product_name": product["name"],
            "monthly": base_monthly,
            "setup": base_setup,
            "billing_cycle": product.get("billing_cycle", "monthly"),
        },
        "option_lines": lines_options,
        "addon_lines": addon_lines,
        "subtotal_monthly": round(subtotal_monthly, 2),
        "setup_total": round(setup_total, 2),
        "subtotal": round(first_invoice_subtotal, 2),
        "tax_percent": tax_percent,
        "tax_amount": tax_amount,
        "total": total,
    }


@router.post("/orders/preview")
async def order_preview(payload: m.OrderIn, user=Depends(get_current_user)):
    """Compute a full price breakdown for a client's cart WITHOUT creating an order.

    Used by the client's Order → Review step so users can confirm the total
    before we generate an invoice.
    """
    db = await _get_db()
    prod = await db.products.find_one({"_id": _oid(payload.product_id)})
    if not prod or prod.get("is_addon"):
        raise HTTPException(status_code=404, detail="Product not found")
    cart = await _price_cart(
        db, product=prod,
        selections=[s.model_dump() for s in (payload.selections or [])],
        addon_ids=payload.addon_ids or [],
    )
    return cart


# Orders
@router.get("/admin/orders")
async def admin_list_orders(admin=Depends(get_current_admin)):
    db = await _get_db()
    docs = await db.orders.find({}).sort("created_at", -1).to_list(1000)
    return [_serialize_order(d) for d in docs]


@router.put("/admin/orders/{oid}/status")
async def admin_update_order_status(
    oid: str, payload: m.OrderStatusUpdateIn, admin=Depends(get_current_admin)
):
    """Manually move an order between statuses. Auto-provisioning primarily
    happens when the linked invoice is marked paid, but admins can still nudge
    the state machine (e.g. mark rejected)."""
    db = await _get_db()
    upd = {"status": payload.status}
    if payload.status == "assigned":
        upd["assigned_admin_id"] = ObjectId(admin["id"])
    await db.orders.update_one(
        {"_id": _oid(oid)},
        {"$set": upd,
         "$push": {"provision_log": {"at": _now(), "step": f"admin_set_{payload.status}",
                                      "message": f"Admin set status to {payload.status}."}}},
    )
    d = await db.orders.find_one({"_id": _oid(oid)})
    return _serialize_order(d)


# Client can flag a bank-transfer payment as sent; admin still needs to confirm.
@router.post("/client/orders/{oid}/confirm-transfer")
async def client_confirm_transfer(oid: str, payload: dict, user=Depends(get_current_user)):
    db = await _get_db()
    o = await db.orders.find_one({"_id": _oid(oid), "user_id": ObjectId(user["id"])})
    if not o:
        raise HTTPException(status_code=404, detail="Order not found")
    await db.orders.update_one(
        {"_id": o["_id"]},
        {"$set": {"status": "awaiting_verification"},
         "$push": {"provision_log": {"at": _now(), "step": "transfer_declared",
                                      "message": f"Client declared bank transfer. Ref: {payload.get('reference','-')}"}}},
    )
    d = await db.orders.find_one({"_id": o["_id"]})
    return _serialize_order(d)


# Invoices (admin)
@router.get("/admin/invoices")
async def admin_list_invoices(admin=Depends(get_current_admin)):
    db = await _get_db()
    await _mark_overdue(db)
    docs = await db.invoices.find({}).sort("created_at", -1).to_list(2000)
    return [await _serialize_invoice(db, d) for d in docs]


@router.post("/admin/invoices", response_model=m.InvoiceOut)
async def admin_create_invoice(payload: m.InvoiceIn, admin=Depends(get_current_admin)):
    db = await _get_db()
    u = await _load_user(db, payload.user_id)
    subtotal = sum(i.total for i in payload.items)
    tax_amount = round(subtotal * payload.tax_percent / 100, 2)
    total = round(subtotal + tax_amount, 2)
    number = await _next_number(db, "invoices", "INV")
    doc = {
        "number": number,
        "user_id": u["_id"],
        "items": [i.model_dump() for i in payload.items],
        "subtotal": subtotal,
        "tax_percent": payload.tax_percent,
        "tax_amount": tax_amount,
        "total": total,
        "due_date": payload.due_date,
        "status": "unpaid",
        "payment_method": None,
        "paid_at": None,
        "notes": payload.notes,
        "created_at": _now(),
    }
    r = await db.invoices.insert_one(doc)
    doc["_id"] = r.inserted_id
    return await _serialize_invoice(db, doc)


@router.put("/admin/invoices/{iid}/status")
async def admin_update_invoice_status(
    iid: str, payload: m.InvoiceStatusIn, admin=Depends(get_current_admin)
):
    db = await _get_db()
    upd = {"status": payload.status}
    if payload.status == "paid":
        upd["paid_at"] = _now()
        upd["payment_method"] = payload.payment_method or "bank_transfer"
    await db.invoices.update_one({"_id": _oid(iid)}, {"$set": upd})
    d = await db.invoices.find_one({"_id": _oid(iid)})
    if not d:
        raise HTTPException(status_code=404, detail="Invoice not found")

    # If payment just confirmed AND invoice is linked to an order → auto-provision.
    if payload.status == "paid" and d.get("order_id"):
        order = await db.orders.find_one({"_id": _oid(d["order_id"])})
        if order and not order.get("service_id"):
            await db.orders.update_one(
                {"_id": order["_id"]},
                {"$set": {"status": "payment_verified"},
                 "$push": {"provision_log": {"at": _now(), "step": "payment_verified",
                                              "message": f"Payment received for invoice {d['number']}."}}},
            )
            order = await db.orders.find_one({"_id": order["_id"]})
            await _auto_provision(db, order)

    return await _serialize_invoice(db, d)


# Quotations
async def _serialize_quotation(db, d: dict) -> dict:
    u = await db.users.find_one({"_id": d["user_id"]}) or {}
    return {
        "id": str(d["_id"]),
        "number": d["number"],
        "user_id": str(d["user_id"]),
        "user_name": u.get("name", ""),
        "user_email": u.get("email", ""),
        "items": d.get("items", []),
        "subtotal": d.get("subtotal", 0),
        "tax_amount": d.get("tax_amount", 0),
        "total": d.get("total", 0),
        "valid_until": d.get("valid_until", ""),
        "status": d.get("status", "draft"),
        "created_at": _iso(d.get("created_at", "")),
        "notes": d.get("notes", ""),
    }


@router.get("/admin/quotations")
async def admin_list_quotations(admin=Depends(get_current_admin)):
    db = await _get_db()
    docs = await db.quotations.find({}).sort("created_at", -1).to_list(1000)
    return [await _serialize_quotation(db, d) for d in docs]


@router.post("/admin/quotations", response_model=m.QuotationOut)
async def admin_create_quotation(payload: m.QuotationIn, admin=Depends(get_current_admin)):
    db = await _get_db()
    u = await _load_user(db, payload.user_id)
    subtotal = sum(i.total for i in payload.items)
    tax_amount = round(subtotal * payload.tax_percent / 100, 2)
    total = round(subtotal + tax_amount, 2)
    number = await _next_number(db, "quotations", "QTN")
    doc = {
        "number": number,
        "user_id": u["_id"],
        "items": [i.model_dump() for i in payload.items],
        "subtotal": subtotal,
        "tax_percent": payload.tax_percent,
        "tax_amount": tax_amount,
        "total": total,
        "valid_until": payload.valid_until,
        "status": "draft",
        "notes": payload.notes,
        "created_at": _now(),
    }
    r = await db.quotations.insert_one(doc)
    doc["_id"] = r.inserted_id
    return await _serialize_quotation(db, doc)


@router.put("/admin/quotations/{qid}/status")
async def admin_update_quotation_status(
    qid: str, payload: m.QuotationStatusIn, admin=Depends(get_current_admin)
):
    db = await _get_db()
    await db.quotations.update_one({"_id": _oid(qid)}, {"$set": {"status": payload.status}})
    d = await db.quotations.find_one({"_id": _oid(qid)})
    if not d:
        raise HTTPException(status_code=404, detail="Quotation not found")
    return await _serialize_quotation(db, d)


# Tickets (staff — any staff role can view/reply)
@router.get("/admin/tickets")
async def admin_list_tickets(staff=Depends(get_current_staff)):
    db = await _get_db()
    docs = await db.tickets.find({}).sort("updated_at", -1).to_list(2000)
    return [await _serialize_ticket(db, d) for d in docs]


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
        "created_at": _now(),
    }
    await db.tickets.update_one(
        {"_id": d["_id"]},
        {"$push": {"replies": reply}, "$set": {"status": "awaiting_client", "updated_at": _now()}},
    )
    d = await db.tickets.find_one({"_id": d["_id"]})
    return await _serialize_ticket(db, d)


# Finance
@router.get("/admin/finance/summary")
async def admin_finance_summary(admin=Depends(get_current_admin)):
    db = await _get_db()
    # Aggregate by month for last 12 months
    paid = await db.invoices.find({"status": "paid"}).to_list(5000)
    by_month = {}
    for inv in paid:
        p = inv.get("paid_at") or inv.get("created_at", "")
        if not p:
            continue
        key = p[:7]  # YYYY-MM
        by_month[key] = by_month.get(key, 0) + inv.get("total", 0)
    series = sorted(
        [{"month": k, "revenue": v} for k, v in by_month.items()],
        key=lambda x: x["month"],
    )
    unpaid = await db.invoices.find({"status": {"$in": ["unpaid", "overdue"]}}).to_list(2000)
    outstanding = sum(d.get("total", 0) for d in unpaid)
    total_revenue = sum(d.get("total", 0) for d in paid)
    return {
        "total_revenue": total_revenue,
        "outstanding": outstanding,
        "paid_invoices": len(paid),
        "monthly_series": series,
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
    }


@router.get("/admin/services")
async def admin_list_services(admin=Depends(get_current_admin)):
    db = await _get_db()
    docs = await db.services.find({}).sort("created_at", -1).to_list(2000)
    return [_serialize_service(d) for d in docs]


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


# Payment gateway config lives inside /admin/integrations (WHMCS-style module hub).


@router.get("/client/payment-info")
async def client_payment_info(user=Depends(get_current_user)):
    """Bank accounts + Duitku availability visible to clients (read from integrations)."""
    db = await _get_db()
    # Read bank accounts from settings (admin-editable)
    bank_doc = await db.settings.find_one({"key": "bank_accounts"}) or {}
    banks = bank_doc.get("value") or [
        {"bank": "MANDIRI", "number": "1240011911816", "holder": "INTERCLOUD DIGITAL INOVASI"},
        {"bank": "BCA", "number": "4730862038", "holder": "ANANG MADIA CUGITA"},
    ]
    # Any enabled duitku integration?
    duitku = await db.integrations.find_one({"module": "duitku", "status": "enabled"})
    return {
        "bank_accounts": banks,
        "duitku_enabled": bool(duitku),
    }


# ============================================================
# INTEGRATIONS (WHMCS-style module hub)
# ============================================================
from .integrations_registry import (
    module_list, module_schema, redact, mock_test_connection,
)


@router.get("/admin/integrations/modules")
async def list_integration_modules(admin=Depends(get_current_admin)):
    """Return the module registry (schemas for the Add Server dialog)."""
    return module_list()


def _serialize_integration(d: dict, hide_secrets: bool = True) -> dict:
    schema = module_schema(d.get("module", ""))
    cfg = d.get("config", {}) or {}
    return {
        "id": str(d["_id"]),
        "name": d.get("name", ""),
        "module": d.get("module", ""),
        "module_label": schema["label"] if schema else d.get("module", ""),
        "category": schema["category"] if schema else "other",
        "config": redact(cfg, schema) if hide_secrets else cfg,
        "status": d.get("status", "disabled"),
        "last_test_at": d.get("last_test_at"),
        "last_test_result": d.get("last_test_result"),
        "created_at": _iso(d.get("created_at", "")),
        "updated_at": _iso(d.get("updated_at", "")),
    }


@router.get("/admin/integrations")
async def list_integrations(admin=Depends(get_current_admin)):
    db = await _get_db()
    docs = await db.integrations.find({}).sort("created_at", -1).to_list(500)
    return [_serialize_integration(d) for d in docs]


@router.post("/admin/integrations")
async def create_integration(payload: dict, admin=Depends(get_current_admin)):
    db = await _get_db()
    module = payload.get("module")
    if not module_schema(module):
        raise HTTPException(status_code=400, detail=f"Unknown module: {module}")
    doc = {
        "name": payload.get("name") or f"{module_schema(module)['label']} {int(datetime.now(timezone.utc).timestamp())}",
        "module": module,
        "config": payload.get("config", {}),
        "status": payload.get("status", "disabled"),
        "last_test_at": None,
        "last_test_result": None,
        "created_at": _now(),
        "updated_at": _now(),
    }
    r = await db.integrations.insert_one(doc)
    doc["_id"] = r.inserted_id
    return _serialize_integration(doc)


@router.put("/admin/integrations/{iid}")
async def update_integration(iid: str, payload: dict, admin=Depends(get_current_admin)):
    db = await _get_db()
    existing = await db.integrations.find_one({"_id": _oid(iid)})
    if not existing:
        raise HTTPException(status_code=404, detail="Integration not found")
    schema = module_schema(existing["module"])
    # Merge config so masked secret fields aren't wiped
    new_cfg = payload.get("config", {})
    merged = dict(existing.get("config", {}))
    if schema:
        for f in schema["fields"]:
            if f["key"] in new_cfg:
                val = new_cfg[f["key"]]
                # Skip masked placeholder
                if f["type"] == "password" and isinstance(val, str) and val.strip() in ("••••••••", "", "*", None):
                    continue
                merged[f["key"]] = val
    upd = {
        "name": payload.get("name", existing["name"]),
        "config": merged,
        "status": payload.get("status", existing.get("status", "disabled")),
        "updated_at": _now(),
    }
    await db.integrations.update_one({"_id": existing["_id"]}, {"$set": upd})
    d = await db.integrations.find_one({"_id": existing["_id"]})
    return _serialize_integration(d)


@router.delete("/admin/integrations/{iid}")
async def delete_integration(iid: str, admin=Depends(get_current_admin)):
    db = await _get_db()
    r = await db.integrations.delete_one({"_id": _oid(iid)})
    return {"deleted": r.deleted_count}


@router.post("/admin/integrations/{iid}/test")
async def test_integration(iid: str, admin=Depends(get_current_admin)):
    db = await _get_db()
    d = await db.integrations.find_one({"_id": _oid(iid)})
    if not d:
        raise HTTPException(status_code=404, detail="Integration not found")
    result = mock_test_connection(d["module"], d.get("config", {}))
    await db.integrations.update_one(
        {"_id": d["_id"]},
        {"$set": {"last_test_at": _now(), "last_test_result": result}},
    )
    return result


@router.post("/admin/integrations/test-config")
async def test_integration_draft(payload: dict, admin=Depends(get_current_admin)):
    """Test connection with an unsaved config (used by the Add Server dialog)."""
    return mock_test_connection(payload.get("module", ""), payload.get("config", {}))


# Bank accounts admin CRUD (simple)
@router.get("/admin/bank-accounts")
async def get_bank_accounts(admin=Depends(get_current_admin)):
    db = await _get_db()
    doc = await db.settings.find_one({"key": "bank_accounts"}) or {}
    return doc.get("value") or [
        {"bank": "MANDIRI", "number": "1240011911816", "holder": "INTERCLOUD DIGITAL INOVASI"},
        {"bank": "BCA", "number": "4730862038", "holder": "ANANG MADIA CUGITA"},
    ]


@router.put("/admin/bank-accounts")
async def update_bank_accounts(payload: list, admin=Depends(get_current_admin)):
    db = await _get_db()
    await db.settings.update_one(
        {"key": "bank_accounts"},
        {"$set": {"key": "bank_accounts", "value": payload}},
        upsert=True,
    )
    return payload


# ============================================================
# WEBMAIL (staff-only) — SMTP for sending, IMAP for inbox.
# Currently backed by MongoDB (mock) so the UX works end-to-end.
# When an SMTP + IMAP integration is enabled under /admin/integrations,
# these endpoints can be swapped to real IMAP/SMTP calls.
# ============================================================

@router.get("/admin/mail/inbox")
async def admin_mail_inbox(staff=Depends(get_current_staff)):
    db = await _get_db()
    # Prefer live IMAP if configured & enabled — fall back to mocked seed otherwise.
    imap_settings = await iv2.get_settings(db, "imap")
    if imap_settings and imap_settings.get("enabled"):
        try:
            live = iv2.IMAPClient(imap_settings).fetch_recent()
            if live:
                return [{
                    "id": f"imap-{msg['id']}",
                    "from_name": msg["from"].split("<")[0].strip(" \""),
                    "from_email": (msg["from"].split("<")[-1].rstrip(">") if "<" in msg["from"] else msg["from"]),
                    "subject": msg["subject"],
                    "preview": msg["preview"],
                    "received_at": msg["date"],
                    "unread": False,
                    "starred": False,
                    "_live": True,
                } for msg in live]
        except Exception:
            pass
    # Seed a handful of demo messages once for realism
    if await db.mail_inbox.count_documents({}) == 0:
        now = datetime.now(timezone.utc)
        demo = [
            {
                "from_name": "PT Contoh Digital", "from_email": "billing@contoh-digital.co.id",
                "subject": "Konfirmasi transfer INV-2026-00003",
                "preview": "Halo, kami sudah transfer via BCA sebesar Rp 1.665.000...",
                "body": "Halo tim Intercloud,\n\nKami sudah transfer via BCA sebesar Rp 1.665.000 untuk invoice INV-2026-00003. Mohon konfirmasi.\n\nTerima kasih,\nBudi",
                "received_at": (now - timedelta(hours=2)).isoformat(),
                "unread": True, "starred": False,
            },
            {
                "from_name": "Rameza NOC", "from_email": "noc@rameza.id",
                "subject": "Maintenance jadwal ulang - Cyber 1 Metta",
                "preview": "Sesuai koordinasi, kami mengusulkan reschedule maintenance...",
                "body": "Selamat sore,\n\nUntuk maintenance link ke Cyber 1 Metta, kami mengusulkan reschedule ke Sabtu jam 02:00-04:00 WIB. Mohon konfirmasi.\n\nSalam,\nNOC Rameza",
                "received_at": (now - timedelta(hours=5)).isoformat(),
                "unread": True, "starred": True,
            },
            {
                "from_name": "APJII IX Team", "from_email": "peering@apjii.or.id",
                "subject": "BGP session update — AS ICD",
                "preview": "Kami memperbarui prefix filter di route server APJII...",
                "body": "Halo,\n\nKami memperbarui prefix filter di route server APJII IIX. Silakan re-announce prefix Anda melalui neighbor 218.100.36.1.\n\nRegards,\nPeering Team",
                "received_at": (now - timedelta(days=1)).isoformat(),
                "unread": False, "starred": False,
            },
            {
                "from_name": "Duitku Support", "from_email": "no-reply@duitku.com",
                "subject": "Settlement Report — Weekly",
                "preview": "Berikut laporan settlement periode 08-14 Juli 2026...",
                "body": "Halo Merchant,\n\nBerikut laporan settlement mingguan Anda. Total 27 transaksi berhasil, senilai Rp 12.850.000.\n\nDuitku",
                "received_at": (now - timedelta(days=2)).isoformat(),
                "unread": False, "starred": False,
            },
        ]
        for d in demo:
            await db.mail_inbox.insert_one(d)
    docs = await db.mail_inbox.find({}).sort("received_at", -1).to_list(200)
    return [{
        "id": str(d["_id"]),
        "from_name": d.get("from_name", ""),
        "from_email": d.get("from_email", ""),
        "subject": d.get("subject", ""),
        "preview": d.get("preview", ""),
        "received_at": d.get("received_at"),
        "unread": bool(d.get("unread", False)),
        "starred": bool(d.get("starred", False)),
    } for d in docs]


@router.get("/admin/mail/messages/{mid}")
async def admin_mail_message(mid: str, staff=Depends(get_current_staff)):
    db = await _get_db()
    d = await db.mail_inbox.find_one({"_id": _oid(mid)})
    if not d:
        raise HTTPException(status_code=404, detail="Not found")
    if d.get("unread"):
        await db.mail_inbox.update_one({"_id": d["_id"]}, {"$set": {"unread": False}})
    return {
        "id": str(d["_id"]),
        "from_name": d.get("from_name", ""),
        "from_email": d.get("from_email", ""),
        "subject": d.get("subject", ""),
        "body": d.get("body", ""),
        "received_at": d.get("received_at"),
        "starred": bool(d.get("starred", False)),
    }


@router.post("/admin/mail/messages/{mid}/toggle-star")
async def admin_mail_toggle_star(mid: str, staff=Depends(get_current_staff)):
    db = await _get_db()
    d = await db.mail_inbox.find_one({"_id": _oid(mid)})
    if not d:
        raise HTTPException(status_code=404, detail="Not found")
    await db.mail_inbox.update_one({"_id": d["_id"]}, {"$set": {"starred": not d.get("starred", False)}})
    return {"starred": not d.get("starred", False)}


@router.post("/admin/mail/send")
async def admin_mail_send(payload: dict, staff=Depends(get_current_staff)):
    db = await _get_db()
    smtp_v2 = await iv2.get_settings(db, "smtp")
    smtp_v1 = await db.integrations.find_one({"module": "smtp", "status": "enabled"})
    to = payload.get("to", "")
    subject = payload.get("subject", "")
    body = payload.get("body", "")
    if not to or not subject:
        raise HTTPException(status_code=400, detail="to and subject are required")
    # Determine sender identity + delivery status
    from_email = ""
    from_name = "Intercloud"
    delivered = False
    delivered_via = "queued (SMTP not configured)"
    if smtp_v2 and smtp_v2.get("enabled"):
        try:
            iv2.SMTPMailer(smtp_v2).send(to=to, subject=subject, html=body or "")
            delivered = True; delivered_via = "smtp"
            from_email = (smtp_v2.get("options") or {}).get("from_email") or (smtp_v2.get("credentials") or {}).get("username") or ""
            from_name = (smtp_v2.get("options") or {}).get("from_name") or "Intercloud"
        except Exception as e:
            delivered = False; delivered_via = f"smtp-failed: {type(e).__name__}"
    elif smtp_v1:
        # Legacy mocked delivery
        delivered = True; delivered_via = "smtp-mock"
        from_email = smtp_v1.get("config", {}).get("from_email") or "no-reply@intercloud-digital.com"
        from_name = smtp_v1.get("config", {}).get("from_name") or "Intercloud"
    doc = {
        "from_email": from_email or "no-reply@intercloud-digital.com",
        "from_name": from_name,
        "to": to, "subject": subject, "body": body,
        "sent_at": _now(),
        "sent_by_id": staff["id"], "sent_by_name": staff["name"],
        "delivered": delivered, "delivered_via": delivered_via,
    }
    r = await db.mail_sent.insert_one(doc)
    doc["_id"] = r.inserted_id
    return {
        "id": str(doc["_id"]),
        "delivered": doc["delivered"],
        "delivered_via": doc["delivered_via"],
        "sent_at": doc["sent_at"],
    }


@router.get("/admin/mail/sent")
async def admin_mail_sent(staff=Depends(get_current_staff)):
    db = await _get_db()
    docs = await db.mail_sent.find({}).sort("sent_at", -1).to_list(200)
    return [{
        "id": str(d["_id"]),
        "from_email": d.get("from_email"),
        "to": d.get("to"),
        "subject": d.get("subject"),
        "body": d.get("body"),
        "sent_at": d.get("sent_at"),
        "delivered": d.get("delivered", False),
        "delivered_via": d.get("delivered_via", ""),
    } for d in docs]


# ============================================================
# BUSINESS — CRM, Projects, Content Planner, Follow-ups, Documents
# ============================================================

# ---------- CRM (customers/prospects) ----------
def _serialize_crm(d):
    return {
        "id": str(d["_id"]),
        "name": d.get("name", ""),
        "email": d.get("email", ""),
        "phone": d.get("phone", ""),
        "company": d.get("company", ""),
        "position": d.get("position", ""),
        "industry": d.get("industry", ""),
        "status": d.get("status", "prospect"),
        "notes": d.get("notes", ""),
        "user_id": str(d["user_id"]) if d.get("user_id") else None,
        "source": d.get("source", ""),
        "created_at": _iso(d.get("created_at", "")),
        "updated_at": _iso(d.get("updated_at", "")),
    }


# Order statuses that count as "in-progress" (needs attention) vs "won" vs "closed"
ORDER_TERMINAL_LOST = {"rejected", "cancelled"}
ORDER_IN_PROGRESS = {"pending", "pending_payment", "awaiting_verification",
                     "awaiting_quote", "payment_verified", "assigned", "provisioning"}
ORDER_WON = {"active"}


async def _crm_enrichment_by_uid(db, user_ids: list) -> dict:
    """Return {user_id_str: {latest_order, active_orders_count, lifetime_value, in_progress_count}}
    for the given user IDs, in one round-trip per collection."""
    if not user_ids:
        return {}
    result = {}
    # ---- Orders (grouped in-memory: small dataset per tenant) ----
    orders_cur = db.orders.find(
        {"user_id": {"$in": user_ids}},
        {"user_id": 1, "status": 1, "created_at": 1, "product_name": 1,
         "invoice_id": 1, "config": 1},
    ).sort("created_at", -1)
    async for o in orders_cur:
        key = str(o["user_id"])
        bucket = result.setdefault(key, {
            "latest_order": None,
            "active_orders_count": 0,
            "in_progress_count": 0,
            "won_orders_count": 0,
            "lifetime_value": 0.0,
        })
        if bucket["latest_order"] is None:
            bucket["latest_order"] = {
                "id": str(o["_id"]),
                "status": o.get("status", "pending"),
                "product_name": o.get("product_name", ""),
                "created_at": _iso(o.get("created_at", "")),
                "invoice_id": str(o["invoice_id"]) if o.get("invoice_id") else None,
            }
        st = o.get("status", "pending")
        if st not in ORDER_TERMINAL_LOST:
            bucket["active_orders_count"] += 1
        if st in ORDER_IN_PROGRESS:
            bucket["in_progress_count"] += 1
        if st in ORDER_WON:
            bucket["won_orders_count"] += 1
    # ---- Paid invoices → lifetime value ----
    inv_cur = db.invoices.find(
        {"user_id": {"$in": user_ids}, "status": "paid"},
        {"user_id": 1, "total": 1, "number": 1},
    )
    async for inv in inv_cur:
        key = str(inv["user_id"])
        bucket = result.setdefault(key, {
            "latest_order": None,
            "active_orders_count": 0,
            "in_progress_count": 0,
            "won_orders_count": 0,
            "lifetime_value": 0.0,
        })
        try:
            bucket["lifetime_value"] += float(inv.get("total") or 0)
        except Exception:
            pass
    return result


@router.get("/admin/crm")
async def crm_list(staff=Depends(get_current_staff)):
    db = await _get_db()
    docs = await db.crm_customers.find({}).sort("updated_at", -1).to_list(2000)
    # Collect user_ids for enrichment
    uid_pairs = [(str(d.get("user_id")), d.get("user_id")) for d in docs if d.get("user_id")]
    uids = [pair[1] for pair in uid_pairs]
    enrich = await _crm_enrichment_by_uid(db, uids)
    out = []
    for d in docs:
        row = _serialize_crm(d)
        e = enrich.get(str(d.get("user_id"))) if d.get("user_id") else None
        row["latest_order"] = (e or {}).get("latest_order")
        row["active_orders_count"] = (e or {}).get("active_orders_count", 0)
        row["in_progress_count"] = (e or {}).get("in_progress_count", 0)
        row["won_orders_count"] = (e or {}).get("won_orders_count", 0)
        row["lifetime_value"] = (e or {}).get("lifetime_value", 0.0)
        # Warm-lead heuristic: any prospect / lead with an in-progress order,
        # OR an existing customer with a fresh in-progress order (upsell signal)
        row["is_warm"] = row["in_progress_count"] > 0
        out.append(row)
    return out


@router.post("/admin/crm")
async def crm_create(payload: dict, staff=Depends(get_current_staff)):
    db = await _get_db()
    doc = {
        "name": payload.get("name", ""),
        "email": (payload.get("email") or "").lower(),
        "phone": payload.get("phone", ""),
        "company": payload.get("company", ""),
        "position": payload.get("position", ""),
        "industry": payload.get("industry", ""),
        "status": payload.get("status", "prospect"),
        "notes": payload.get("notes", ""),
        "created_at": _now(),
        "updated_at": _now(),
    }
    r = await db.crm_customers.insert_one(doc)
    doc["_id"] = r.inserted_id
    return _serialize_crm(doc)


@router.put("/admin/crm/{cid}")
async def crm_update(cid: str, payload: dict, staff=Depends(get_current_staff)):
    db = await _get_db()
    payload = {k: v for k, v in payload.items() if k in {
        "name", "email", "phone", "company", "position", "industry", "status", "notes"
    }}
    payload["updated_at"] = _now()
    if "email" in payload and payload["email"]:
        payload["email"] = payload["email"].lower()
    await db.crm_customers.update_one({"_id": _oid(cid)}, {"$set": payload})
    d = await db.crm_customers.find_one({"_id": _oid(cid)})
    if not d:
        raise HTTPException(status_code=404, detail="Not found")
    return _serialize_crm(d)


@router.delete("/admin/crm/{cid}")
async def crm_delete(cid: str, staff=Depends(get_current_staff)):
    db = await _get_db()
    r = await db.crm_customers.delete_one({"_id": _oid(cid)})
    return {"deleted": r.deleted_count}


# ---------- Projects ----------
def _serialize_project(d):
    return {
        "id": str(d["_id"]),
        "name": d.get("name", ""),
        "customer_id": str(d.get("customer_id", "")) if d.get("customer_id") else None,
        "customer_name": d.get("customer_name", ""),
        "owner": d.get("owner", ""),
        "status": d.get("status", "planning"),
        "priority": d.get("priority", "medium"),
        "progress": d.get("progress", 0),
        "start_date": d.get("start_date", ""),
        "target_date": d.get("target_date", ""),
        "description": d.get("description", ""),
        "tasks": d.get("tasks", []),
        "created_at": _iso(d.get("created_at", "")),
        "updated_at": _iso(d.get("updated_at", "")),
    }


@router.get("/admin/projects")
async def projects_list(staff=Depends(get_current_staff)):
    db = await _get_db()
    docs = await db.projects.find({}).sort("updated_at", -1).to_list(1000)
    return [_serialize_project(d) for d in docs]


@router.post("/admin/projects")
async def projects_create(payload: dict, staff=Depends(get_current_staff)):
    db = await _get_db()
    doc = {
        "name": payload.get("name", ""),
        "customer_id": _oid(payload["customer_id"]) if payload.get("customer_id") else None,
        "customer_name": payload.get("customer_name", ""),
        "owner": payload.get("owner", ""),
        "status": payload.get("status", "planning"),
        "priority": payload.get("priority", "medium"),
        "progress": int(payload.get("progress", 0)),
        "start_date": payload.get("start_date", ""),
        "target_date": payload.get("target_date", ""),
        "description": payload.get("description", ""),
        "tasks": payload.get("tasks", []),
        "created_at": _now(),
        "updated_at": _now(),
    }
    r = await db.projects.insert_one(doc)
    doc["_id"] = r.inserted_id
    return _serialize_project(doc)


@router.put("/admin/projects/{pid}")
async def projects_update(pid: str, payload: dict, staff=Depends(get_current_staff)):
    db = await _get_db()
    upd = {k: v for k, v in payload.items() if k in {
        "name", "customer_name", "owner", "status", "priority", "progress",
        "start_date", "target_date", "description", "tasks"
    }}
    if "customer_id" in payload:
        upd["customer_id"] = _oid(payload["customer_id"]) if payload["customer_id"] else None
    upd["updated_at"] = _now()
    await db.projects.update_one({"_id": _oid(pid)}, {"$set": upd})
    d = await db.projects.find_one({"_id": _oid(pid)})
    return _serialize_project(d)


@router.delete("/admin/projects/{pid}")
async def projects_delete(pid: str, staff=Depends(get_current_staff)):
    db = await _get_db()
    r = await db.projects.delete_one({"_id": _oid(pid)})
    return {"deleted": r.deleted_count}


# ---------- Content Planner ----------
def _serialize_content(d):
    return {
        "id": str(d["_id"]),
        "title": d.get("title", ""),
        "channel": d.get("channel", "blog"),
        "type": d.get("type", "post"),
        "status": d.get("status", "idea"),
        "owner": d.get("owner", ""),
        "publish_date": d.get("publish_date", ""),
        "hook": d.get("hook", ""),
        "url": d.get("url", ""),
        "created_at": _iso(d.get("created_at", "")),
    }


@router.get("/admin/content")
async def content_list(staff=Depends(get_current_staff)):
    db = await _get_db()
    docs = await db.content_plan.find({}).sort("publish_date", 1).to_list(1000)
    return [_serialize_content(d) for d in docs]


@router.post("/admin/content")
async def content_create(payload: dict, staff=Depends(get_current_staff)):
    db = await _get_db()
    doc = {
        "title": payload.get("title", ""),
        "channel": payload.get("channel", "blog"),
        "type": payload.get("type", "post"),
        "status": payload.get("status", "idea"),
        "owner": payload.get("owner", ""),
        "publish_date": payload.get("publish_date", ""),
        "hook": payload.get("hook", ""),
        "url": payload.get("url", ""),
        "created_at": _now(),
    }
    r = await db.content_plan.insert_one(doc)
    doc["_id"] = r.inserted_id
    return _serialize_content(doc)


@router.put("/admin/content/{cid}")
async def content_update(cid: str, payload: dict, staff=Depends(get_current_staff)):
    db = await _get_db()
    upd = {k: v for k, v in payload.items() if k in {
        "title", "channel", "type", "status", "owner", "publish_date", "hook", "url"
    }}
    await db.content_plan.update_one({"_id": _oid(cid)}, {"$set": upd})
    d = await db.content_plan.find_one({"_id": _oid(cid)})
    return _serialize_content(d)


@router.delete("/admin/content/{cid}")
async def content_delete(cid: str, staff=Depends(get_current_staff)):
    db = await _get_db()
    r = await db.content_plan.delete_one({"_id": _oid(cid)})
    return {"deleted": r.deleted_count}


# ---------- Follow-ups ----------
def _serialize_followup(d):
    return {
        "id": str(d["_id"]),
        "customer_id": str(d.get("customer_id", "")) if d.get("customer_id") else None,
        "customer_name": d.get("customer_name", ""),
        "task": d.get("task", ""),
        "channel": d.get("channel", "whatsapp"),
        "due_date": d.get("due_date", ""),
        "done": bool(d.get("done", False)),
        "owner": d.get("owner", ""),
        "created_at": _iso(d.get("created_at", "")),
    }


@router.get("/admin/followups")
async def followups_list(staff=Depends(get_current_staff)):
    db = await _get_db()
    docs = await db.followups.find({}).sort("due_date", 1).to_list(1000)
    return [_serialize_followup(d) for d in docs]


@router.post("/admin/followups")
async def followups_create(payload: dict, staff=Depends(get_current_staff)):
    db = await _get_db()
    doc = {
        "customer_id": _oid(payload["customer_id"]) if payload.get("customer_id") else None,
        "customer_name": payload.get("customer_name", ""),
        "task": payload.get("task", ""),
        "channel": payload.get("channel", "whatsapp"),
        "due_date": payload.get("due_date", ""),
        "done": False,
        "owner": payload.get("owner", staff["name"]),
        "created_at": _now(),
    }
    r = await db.followups.insert_one(doc)
    doc["_id"] = r.inserted_id
    return _serialize_followup(doc)


@router.put("/admin/followups/{fid}")
async def followups_update(fid: str, payload: dict, staff=Depends(get_current_staff)):
    db = await _get_db()
    upd = {k: v for k, v in payload.items() if k in {"task", "channel", "due_date", "done", "owner", "customer_name"}}
    await db.followups.update_one({"_id": _oid(fid)}, {"$set": upd})
    d = await db.followups.find_one({"_id": _oid(fid)})
    return _serialize_followup(d)


@router.delete("/admin/followups/{fid}")
async def followups_delete(fid: str, staff=Depends(get_current_staff)):
    db = await _get_db()
    r = await db.followups.delete_one({"_id": _oid(fid)})
    return {"deleted": r.deleted_count}


# ---------- Documents (metadata only for MVP) ----------
def _serialize_doc(d):
    return {
        "id": str(d["_id"]),
        "title": d.get("title", ""),
        "category": d.get("category", "contract"),
        "customer_name": d.get("customer_name", ""),
        "url": d.get("url", ""),
        "notes": d.get("notes", ""),
        "created_at": _iso(d.get("created_at", "")),
    }


@router.get("/admin/documents")
async def docs_list(staff=Depends(get_current_staff)):
    db = await _get_db()
    docs = await db.documents.find({}).sort("created_at", -1).to_list(1000)
    return [_serialize_doc(d) for d in docs]


@router.post("/admin/documents")
async def docs_create(payload: dict, staff=Depends(get_current_staff)):
    db = await _get_db()
    doc = {
        "title": payload.get("title", ""),
        "category": payload.get("category", "contract"),
        "customer_name": payload.get("customer_name", ""),
        "url": payload.get("url", ""),
        "notes": payload.get("notes", ""),
        "created_at": _now(),
    }
    r = await db.documents.insert_one(doc)
    doc["_id"] = r.inserted_id
    return _serialize_doc(doc)


@router.delete("/admin/documents/{did}")
async def docs_delete(did: str, staff=Depends(get_current_staff)):
    db = await _get_db()
    r = await db.documents.delete_one({"_id": _oid(did)})
    return {"deleted": r.deleted_count}


# ============================================================
# DCIM / IPAM (native, not via NetBox)
# ============================================================
@router.get("/admin/dcim/racks")
async def dcim_racks(staff=Depends(get_current_staff)):
    db = await _get_db()
    docs = await db.dcim_racks.find({}).sort("name", 1).to_list(500)
    if not docs:
        # First-load seed for demo
        seed = [
            {"name": "Rack B12", "site": "Cyber 1 — Metta (Lantai 5)", "u_size": 42,
             "occupancy": [{"u_top": 40, "u_bot": 40, "label": "Patch Panel", "customer": ""},
                            {"u_top": 39, "u_bot": 39, "label": "sw-tor-1", "customer": "internal"},
                            {"u_top": 38, "u_bot": 38, "label": "sw-tor-2", "customer": "internal"},
                            {"u_top": 36, "u_bot": 34, "label": "3U Server", "customer": "PT Contoh Digital"}],
             "power_draw_w": 2450, "power_cap_w": 6000},
            {"name": "Rack A05", "site": "Cyber 1 — Omni (Lantai 2)", "u_size": 42,
             "occupancy": [{"u_top": 24, "u_bot": 20, "label": "5U Blade Chassis", "customer": "Bank ABC"}],
             "power_draw_w": 3800, "power_cap_w": 6000},
        ]
        for s in seed:
            await db.dcim_racks.insert_one({**s, "created_at": _now()})
        docs = await db.dcim_racks.find({}).sort("name", 1).to_list(500)
    return [{"id": str(d["_id"]), **{k: v for k, v in d.items() if k != "_id"}} for d in docs]


@router.get("/admin/dcim/prefixes")
async def dcim_prefixes(staff=Depends(get_current_staff)):
    db = await _get_db()
    docs = await db.dcim_prefixes.find({}).to_list(500)
    if not docs:
        seed = [
            {"prefix": "103.28.14.0/24", "usage": 148, "capacity": 256, "vlan": "vlan-100", "site": "Cyber 1 — Metta", "family": 4},
            {"prefix": "103.28.15.0/24", "usage": 22, "capacity": 256, "vlan": "vlan-110", "site": "Cyber 1 — Omni", "family": 4},
            {"prefix": "2401:a900:1234::/48", "usage": 3, "capacity": 65536, "vlan": "vlan-100", "site": "Cyber 1 — Metta", "family": 6},
            {"prefix": "10.10.0.0/16", "usage": 1284, "capacity": 65534, "vlan": "mgmt", "site": "Internal", "family": 4},
        ]
        for s in seed:
            await db.dcim_prefixes.insert_one({**s, "created_at": _now()})
        docs = await db.dcim_prefixes.find({}).to_list(500)
    return [{"id": str(d["_id"]), **{k: v for k, v in d.items() if k != "_id"}} for d in docs]


@router.post("/admin/dcim/racks")
async def dcim_rack_create(payload: dict, staff=Depends(get_current_staff)):
    db = await _get_db()
    doc = {
        "name": payload.get("name", "Untitled Rack"),
        "site": payload.get("site", ""),
        "u_size": int(payload.get("u_size", 42)),
        "occupancy": payload.get("occupancy", []),
        "power_draw_w": int(payload.get("power_draw_w", 0) or 0),
        "power_cap_w": int(payload.get("power_cap_w", 6000) or 6000),
        "notes": payload.get("notes", ""),
        "created_at": _now(),
    }
    r = await db.dcim_racks.insert_one(doc)
    doc["_id"] = r.inserted_id
    return {"id": str(doc["_id"]), **{k: v for k, v in doc.items() if k != "_id"}}


@router.put("/admin/dcim/racks/{rid}")
async def dcim_rack_update(rid: str, payload: dict, staff=Depends(get_current_staff)):
    db = await _get_db()
    upd = {k: v for k, v in payload.items() if k in {"name", "site", "u_size", "occupancy", "power_draw_w", "power_cap_w", "notes"}}
    for k in ("u_size", "power_draw_w", "power_cap_w"):
        if k in upd:
            upd[k] = int(upd[k] or 0)
    await db.dcim_racks.update_one({"_id": _oid(rid)}, {"$set": upd})
    d = await db.dcim_racks.find_one({"_id": _oid(rid)})
    if not d:
        raise HTTPException(status_code=404, detail="Not found")
    return {"id": str(d["_id"]), **{k: v for k, v in d.items() if k != "_id"}}


@router.delete("/admin/dcim/racks/{rid}")
async def dcim_rack_delete(rid: str, staff=Depends(get_current_staff)):
    db = await _get_db()
    r = await db.dcim_racks.delete_one({"_id": _oid(rid)})
    return {"deleted": r.deleted_count}


@router.put("/admin/dcim/prefixes/{pid}")
async def dcim_prefix_update(pid: str, payload: dict, staff=Depends(get_current_staff)):
    db = await _get_db()
    upd = {k: v for k, v in payload.items() if k in {"prefix", "usage", "capacity", "vlan", "site", "family", "description"}}
    for k in ("usage", "capacity", "family"):
        if k in upd:
            upd[k] = int(upd[k] or 0)
    await db.dcim_prefixes.update_one({"_id": _oid(pid)}, {"$set": upd})
    d = await db.dcim_prefixes.find_one({"_id": _oid(pid)})
    if not d:
        raise HTTPException(status_code=404, detail="Not found")
    return {"id": str(d["_id"]), **{k: v for k, v in d.items() if k != "_id"}}


# IP Addresses (within a prefix)
@router.get("/admin/dcim/ips")
async def dcim_ips_list(prefix_id: str | None = None, staff=Depends(get_current_staff)):
    db = await _get_db()
    q = {}
    if prefix_id:
        q["prefix_id"] = _oid(prefix_id)
    docs = await db.dcim_ips.find(q).sort("address", 1).to_list(2000)
    return [{"id": str(d["_id"]), "prefix_id": str(d.get("prefix_id", "")) if d.get("prefix_id") else None,
             **{k: v for k, v in d.items() if k not in ("_id", "prefix_id")}} for d in docs]


@router.post("/admin/dcim/ips")
async def dcim_ip_create(payload: dict, staff=Depends(get_current_staff)):
    db = await _get_db()
    doc = {
        "address": payload.get("address", ""),
        "prefix_id": _oid(payload["prefix_id"]) if payload.get("prefix_id") else None,
        "status": payload.get("status", "active"),
        "role": payload.get("role", ""),
        "hostname": payload.get("hostname", ""),
        "customer": payload.get("customer", ""),
        "description": payload.get("description", ""),
        "created_at": _now(),
    }
    r = await db.dcim_ips.insert_one(doc)
    doc["_id"] = r.inserted_id
    return {"id": str(doc["_id"]), "prefix_id": str(doc["prefix_id"]) if doc.get("prefix_id") else None,
            **{k: v for k, v in doc.items() if k not in ("_id", "prefix_id")}}


@router.put("/admin/dcim/ips/{ipid}")
async def dcim_ip_update(ipid: str, payload: dict, staff=Depends(get_current_staff)):
    db = await _get_db()
    upd = {k: v for k, v in payload.items() if k in {"address", "status", "role", "hostname", "customer", "description"}}
    if "prefix_id" in payload:
        upd["prefix_id"] = _oid(payload["prefix_id"]) if payload["prefix_id"] else None
    await db.dcim_ips.update_one({"_id": _oid(ipid)}, {"$set": upd})
    d = await db.dcim_ips.find_one({"_id": _oid(ipid)})
    return {"id": str(d["_id"]), "prefix_id": str(d.get("prefix_id", "")) if d.get("prefix_id") else None,
            **{k: v for k, v in d.items() if k not in ("_id", "prefix_id")}}


@router.delete("/admin/dcim/ips/{ipid}")
async def dcim_ip_delete(ipid: str, staff=Depends(get_current_staff)):
    db = await _get_db()
    r = await db.dcim_ips.delete_one({"_id": _oid(ipid)})
    return {"deleted": r.deleted_count}


# Sites
@router.get("/admin/dcim/sites")
async def dcim_sites(staff=Depends(get_current_staff)):
    db = await _get_db()
    docs = await db.dcim_sites.find({}).sort("name", 1).to_list(500)
    if not docs:
        for s in [
            {"name": "Cyber 1 — Metta Lantai 5", "code": "JKT-METTA-5F", "address": "Cyber 1 Building, Jakarta"},
            {"name": "Cyber 1 — Omni Lantai 2", "code": "JKT-OMNI-2F", "address": "Cyber 1 Building, Jakarta"},
            {"name": "TIFA Building", "code": "JKT-TIFA", "address": "TIFA Building, Jakarta"},
            {"name": "APJII DC Cyber 1 Lantai 1", "code": "JKT-APJII-1F", "address": "Cyber 1 Building, Jakarta"},
        ]:
            await db.dcim_sites.insert_one({**s, "created_at": _now()})
        docs = await db.dcim_sites.find({}).sort("name", 1).to_list(500)
    return [{"id": str(d["_id"]), **{k: v for k, v in d.items() if k != "_id"}} for d in docs]


@router.post("/admin/dcim/sites")
async def dcim_site_create(payload: dict, staff=Depends(get_current_staff)):
    db = await _get_db()
    doc = {**payload, "created_at": _now()}
    r = await db.dcim_sites.insert_one(doc)
    return {"id": str(r.inserted_id), **payload}


@router.delete("/admin/dcim/sites/{sid}")
async def dcim_site_delete(sid: str, staff=Depends(get_current_staff)):
    db = await _get_db()
    r = await db.dcim_sites.delete_one({"_id": _oid(sid)})
    return {"deleted": r.deleted_count}


@router.post("/admin/dcim/prefixes")
async def dcim_prefix_create(payload: dict, staff=Depends(get_current_staff)):
    db = await _get_db()
    doc = {**payload, "created_at": _now()}
    r = await db.dcim_prefixes.insert_one(doc)
    doc["_id"] = r.inserted_id
    return {"id": str(doc["_id"]), **{k: v for k, v in doc.items() if k != "_id"}}


@router.delete("/admin/dcim/prefixes/{pid}")
async def dcim_prefix_delete(pid: str, staff=Depends(get_current_staff)):
    db = await _get_db()
    r = await db.dcim_prefixes.delete_one({"_id": _oid(pid)})
    return {"deleted": r.deleted_count}


# ============================================================
# PROXMOX — available OS templates & OS request ticket bridge
# ============================================================
@router.get("/admin/proxmox/os-templates")
async def proxmox_os_templates(staff=Depends(get_current_staff)):
    """Return OS templates as would be reported by Proxmox ISO storage.
    Reads from an admin-editable settings doc; falls back to a common list."""
    db = await _get_db()
    doc = await db.settings.find_one({"key": "proxmox_os_templates"})
    if doc and doc.get("value"):
        return doc["value"]
    return [
        {"name": "Ubuntu 22.04 LTS Server", "family": "ubuntu", "type": "iso"},
        {"name": "Ubuntu 20.04 LTS Server", "family": "ubuntu", "type": "iso"},
        {"name": "Debian 12", "family": "debian", "type": "iso"},
        {"name": "AlmaLinux 9", "family": "rhel", "type": "iso"},
        {"name": "Rocky Linux 9", "family": "rhel", "type": "iso"},
        {"name": "CentOS Stream 9", "family": "rhel", "type": "iso"},
        {"name": "Windows Server 2022 Std", "family": "windows", "type": "iso"},
        {"name": "cloud-init/ubuntu-24.04-noble", "family": "ubuntu", "type": "template"},
        {"name": "cloud-init/debian-12", "family": "debian", "type": "template"},
    ]


@router.put("/admin/proxmox/os-templates")
async def proxmox_os_templates_set(payload: list, admin=Depends(get_current_admin)):
    db = await _get_db()
    await db.settings.update_one(
        {"key": "proxmox_os_templates"},
        {"$set": {"key": "proxmox_os_templates", "value": payload}},
        upsert=True,
    )
    return payload


@router.post("/client/proxmox/os-request")
async def client_request_os(payload: dict, user=Depends(get_current_user)):
    """Client requests an OS that isn't currently in the Proxmox library.
    Creates a ticket in the technical department."""
    db = await _get_db()
    os_name = (payload.get("os_name") or "").strip()
    if not os_name:
        raise HTTPException(status_code=400, detail="os_name is required")
    now = _now()
    number = await _next_number(db, "tickets", "TCK")
    subject = f"OS Provision Request: {os_name}"
    doc = {
        "user_id": ObjectId(user["id"]),
        "number": number,
        "subject": subject,
        "department": "technical",
        "priority": "medium",
        "status": "open",
        "replies": [{
            "author_id": user["id"], "author_name": user["name"], "author_role": "client",
            "message": f"Hi team, I'd like to request that '{os_name}' be added to the Proxmox ISO library. Additional notes: {payload.get('notes','-')}",
            "created_at": now,
        }],
        "created_at": now, "updated_at": now,
    }
    r = await db.tickets.insert_one(doc)
    return {"ticket_number": number, "ticket_id": str(r.inserted_id)}


# ============================================================
# ASSETS (native asset tracking + STRAIGHT-LINE depreciation)
# Formula (Metode Garis Lurus):
#   Penyusutan per Tahun = (Harga Perolehan − Nilai Sisa) / Umur Ekonomis
#   Penyusutan per Bulan = Penyusutan per Tahun / 12
#   Akumulasi Penyusutan = Penyusutan per Bulan × bulan_terpakai
#   Nilai Buku            = max(Harga Perolehan − Akumulasi Penyusutan, Nilai Sisa)
# ============================================================
def _asset_life_years(a: dict) -> int:
    """Effective useful-life in years. Prefer explicit field, fall back to
    legacy fields (`useful_life_months`, `depreciation_percent`) so we stay
    backwards-compatible with data seeded before the straight-line rewrite."""
    life_y = int(a.get("useful_life_years", 0) or 0)
    if life_y > 0:
        return life_y
    life_m = int(a.get("useful_life_months", 0) or 0)
    if life_m > 0:
        return max(1, round(life_m / 12))
    dep_pct = float(a.get("depreciation_percent", 0) or 0)
    if dep_pct > 0:
        return max(1, round(100.0 / dep_pct))
    return 0


def _asset_depreciation(a: dict) -> dict:
    """Compute straight-line depreciation snapshot for an asset document."""
    value = float(a.get("value", 0) or 0)
    salvage = float(a.get("salvage_value", 0) or 0)
    life_y = _asset_life_years(a)
    purchase = a.get("purchase_date", "") or ""

    if life_y <= 0 or not purchase:
        return {
            "life_years": life_y,
            "depreciable_base": max(value - salvage, 0.0),
            "annual_depreciation": 0.0,
            "monthly_depreciation": 0.0,
            "months_elapsed": 0,
            "total_months": life_y * 12,
            "accumulated_depreciation": 0.0,
            "book_value": round(value, 2),
            "is_fully_depreciated": False,
        }

    base = max(value - salvage, 0.0)
    annual = base / life_y
    monthly = annual / 12.0
    total_months = life_y * 12

    try:
        p = datetime.fromisoformat(purchase[:10])
    except Exception:
        return {
            "life_years": life_y, "depreciable_base": base,
            "annual_depreciation": round(annual, 2), "monthly_depreciation": round(monthly, 2),
            "months_elapsed": 0, "total_months": total_months,
            "accumulated_depreciation": 0.0, "book_value": round(value, 2),
            "is_fully_depreciated": False,
        }

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    months = (now.year - p.year) * 12 + (now.month - p.month)
    if now.day >= p.day:
        months += 1
    months = max(0, min(months, total_months))

    accumulated = round(monthly * months, 2)
    book = max(round(value - accumulated, 2), salvage)
    return {
        "life_years": life_y,
        "depreciable_base": round(base, 2),
        "annual_depreciation": round(annual, 2),
        "monthly_depreciation": round(monthly, 2),
        "months_elapsed": months,
        "total_months": total_months,
        "accumulated_depreciation": accumulated,
        "book_value": book,
        "is_fully_depreciated": months >= total_months,
    }


def _asset_book_value(a: dict) -> float:
    """Current book value using the straight-line method (floored at salvage)."""
    return _asset_depreciation(a)["book_value"]


def _asset_schedule(a: dict) -> list:
    """Yearly schedule from purchase year through end of useful life."""
    value = float(a.get("value", 0) or 0)
    salvage = float(a.get("salvage_value", 0) or 0)
    life_y = _asset_life_years(a)
    purchase = a.get("purchase_date", "") or ""
    if life_y <= 0 or not purchase:
        return []
    base = max(value - salvage, 0.0)
    annual = base / life_y
    try:
        start_year = datetime.fromisoformat(purchase[:10]).year
    except Exception:
        return []
    rows, accumulated = [], 0.0
    for i in range(life_y):
        accumulated = min(accumulated + annual, base)
        book = max(value - accumulated, salvage)
        rows.append({
            "period": i + 1,
            "year": start_year + i,
            "depreciation": round(annual, 2),
            "accumulated_depreciation": round(accumulated, 2),
            "book_value": round(book, 2),
        })
    return rows


def _serialize_asset(d):
    dep = _asset_depreciation(d)
    return {
        "id": str(d["_id"]),
        "name": d.get("name", ""),
        "category": d.get("category", "server"),
        "serial_number": d.get("serial_number", ""),
        "location": d.get("location", ""),
        "vendor": d.get("vendor", ""),
        "value": float(d.get("value", 0)),
        "salvage_value": float(d.get("salvage_value", 0) or 0),
        "useful_life_years": dep["life_years"],
        # legacy fields kept for backward compat with UI/tests still referencing them
        "depreciation_percent": float(d.get("depreciation_percent", 0) or 0),
        "useful_life_months": int(d.get("useful_life_months", 0) or 0),
        "purchase_date": d.get("purchase_date", ""),
        "annual_depreciation": dep["annual_depreciation"],
        "monthly_depreciation": dep["monthly_depreciation"],
        "accumulated_depreciation": dep["accumulated_depreciation"],
        "book_value": dep["book_value"],
        # kept for compat with old frontend field name
        "depreciated_amount": dep["accumulated_depreciation"],
        "months_elapsed": dep["months_elapsed"],
        "total_months": dep["total_months"],
        "is_fully_depreciated": dep["is_fully_depreciated"],
        "notes": d.get("notes", ""),
        "created_at": _iso(d.get("created_at", "")),
    }


@router.get("/admin/assets")
async def assets_list(admin=Depends(get_current_admin)):
    db = await _get_db()
    docs = await db.assets.find({}).sort("created_at", -1).to_list(2000)
    return [_serialize_asset(d) for d in docs]


@router.get("/admin/assets/{aid}")
async def assets_get(aid: str, admin=Depends(get_current_admin)):
    db = await _get_db()
    d = await db.assets.find_one({"_id": _oid(aid)})
    if not d:
        raise HTTPException(status_code=404, detail="Not found")
    payload = _serialize_asset(d)
    payload["schedule"] = _asset_schedule(d)
    return payload


def _coerce_asset_payload(payload: dict) -> dict:
    """Normalize incoming asset payload. Falls back to legacy fields when
    salvage/useful_life_years are omitted."""
    life_y = payload.get("useful_life_years")
    if life_y in (None, "", 0, "0"):
        # derive from legacy fields if provided in same payload
        dep_pct = float(payload.get("depreciation_percent", 0) or 0)
        life_m = int(payload.get("useful_life_months", 0) or 0)
        if life_m > 0:
            life_y = max(1, round(life_m / 12))
        elif dep_pct > 0:
            life_y = max(1, round(100.0 / dep_pct))
        else:
            life_y = 0
    return {
        "salvage_value": float(payload.get("salvage_value", 0) or 0),
        "useful_life_years": int(life_y or 0),
    }


@router.post("/admin/assets")
async def assets_create(payload: dict, admin=Depends(get_current_admin)):
    db = await _get_db()
    coerced = _coerce_asset_payload(payload)
    doc = {
        "name": payload.get("name", ""),
        "category": payload.get("category", "server"),
        "serial_number": payload.get("serial_number", ""),
        "location": payload.get("location", ""),
        "vendor": payload.get("vendor", ""),
        "value": float(payload.get("value", 0) or 0),
        "salvage_value": coerced["salvage_value"],
        "useful_life_years": coerced["useful_life_years"],
        # legacy fields retained if the client still sends them
        "depreciation_percent": float(payload.get("depreciation_percent", 0) or 0),
        "useful_life_months": int(payload.get("useful_life_months", 0) or 0),
        "purchase_date": payload.get("purchase_date", ""),
        "notes": payload.get("notes", ""),
        "created_at": _now(),
    }
    r = await db.assets.insert_one(doc)
    doc["_id"] = r.inserted_id
    return _serialize_asset(doc)


@router.put("/admin/assets/{aid}")
async def assets_update(aid: str, payload: dict, admin=Depends(get_current_admin)):
    db = await _get_db()
    allowed = {
        "name", "category", "serial_number", "location", "vendor", "value",
        "salvage_value", "useful_life_years",
        "depreciation_percent", "useful_life_months",
        "purchase_date", "notes",
    }
    upd = {k: v for k, v in payload.items() if k in allowed}
    coerced = _coerce_asset_payload({**upd})
    upd["salvage_value"] = coerced["salvage_value"]
    if coerced["useful_life_years"] > 0:
        upd["useful_life_years"] = coerced["useful_life_years"]
    for k in ("value", "depreciation_percent"):
        if k in upd:
            upd[k] = float(upd[k] or 0)
    if "useful_life_months" in upd:
        upd["useful_life_months"] = int(upd["useful_life_months"] or 0)
    await db.assets.update_one({"_id": _oid(aid)}, {"$set": upd})
    d = await db.assets.find_one({"_id": _oid(aid)})
    if not d:
        raise HTTPException(status_code=404, detail="Not found")
    return _serialize_asset(d)


@router.delete("/admin/assets/{aid}")
async def assets_delete(aid: str, admin=Depends(get_current_admin)):
    db = await _get_db()
    r = await db.assets.delete_one({"_id": _oid(aid)})
    return {"deleted": r.deleted_count}


# ============================================================
# EXPENSES (manual bookkeeping)
# ============================================================
def _serialize_expense(d):
    return {
        "id": str(d["_id"]),
        "date": d.get("date", ""),
        "category": d.get("category", "other"),
        "vendor": d.get("vendor", ""),
        "amount": float(d.get("amount", 0)),
        "description": d.get("description", ""),
        "created_at": _iso(d.get("created_at", "")),
    }


@router.get("/admin/expenses")
async def expenses_list(admin=Depends(get_current_admin)):
    db = await _get_db()
    docs = await db.expenses.find({}).sort("date", -1).to_list(5000)
    return [_serialize_expense(d) for d in docs]


@router.post("/admin/expenses")
async def expenses_create(payload: dict, admin=Depends(get_current_admin)):
    db = await _get_db()
    doc = {
        "date": payload.get("date", datetime.now(timezone.utc).date().isoformat()),
        "category": payload.get("category", "other"),
        "vendor": payload.get("vendor", ""),
        "amount": float(payload.get("amount", 0) or 0),
        "description": payload.get("description", ""),
        "created_at": _now(),
    }
    r = await db.expenses.insert_one(doc)
    doc["_id"] = r.inserted_id
    return _serialize_expense(doc)


@router.delete("/admin/expenses/{eid}")
async def expenses_delete(eid: str, admin=Depends(get_current_admin)):
    db = await _get_db()
    r = await db.expenses.delete_one({"_id": _oid(eid)})
    return {"deleted": r.deleted_count}


# Extended finance report (revenue + expenses + assets)
@router.get("/admin/finance/report")
async def admin_finance_report(admin=Depends(get_current_admin)):
    db = await _get_db()
    paid = await db.invoices.find({"status": "paid"}).to_list(5000)
    total_revenue = sum(d.get("total", 0) for d in paid)
    expenses = await db.expenses.find({}).to_list(5000)
    total_expenses = sum(d.get("amount", 0) for d in expenses)
    net_profit = total_revenue - total_expenses

    assets = await db.assets.find({}).to_list(2000)
    total_assets_value = sum(float(a.get("value", 0)) for a in assets)
    net_assets_value = sum(_asset_book_value(a) for a in assets)
    total_depreciation = round(total_assets_value - net_assets_value, 2)

    # Revenue & expenses by month (last 12 months)
    by_month_rev, by_month_exp = {}, {}
    for inv in paid:
        p = inv.get("paid_at") or inv.get("created_at", "")
        if not p:
            continue
        key = p[:7]
        by_month_rev[key] = by_month_rev.get(key, 0) + inv.get("total", 0)
    for e in expenses:
        key = (e.get("date") or "")[:7]
        if not key:
            continue
        by_month_exp[key] = by_month_exp.get(key, 0) + e.get("amount", 0)

    all_keys = sorted(set(by_month_rev.keys()) | set(by_month_exp.keys()))
    monthly = [
        {"month": k, "revenue": by_month_rev.get(k, 0), "expenses": by_month_exp.get(k, 0),
         "profit": by_month_rev.get(k, 0) - by_month_exp.get(k, 0)}
        for k in all_keys
    ]

    return {
        "total_revenue": total_revenue,
        "total_expenses": total_expenses,
        "net_profit": net_profit,
        "total_assets_value": total_assets_value,
        "net_assets_value": net_assets_value,
        "total_depreciation": total_depreciation,
        "asset_count": len(assets),
        "monthly": monthly,
    }


# ============================================================
# PDF (HTML/PDF) documents — Invoice & Quotation
# Rendered as an HTML preview by default; add ?format=pdf for a real
# WeasyPrint-rendered downloadable .pdf that matches the WHMCS-style layout.
# ============================================================
from fastapi.responses import HTMLResponse, Response


# Long-form English/Indonesian date used inside the document
def _long_date(iso_or_ymd: str) -> str:
    if not iso_or_ymd:
        return "-"
    try:
        s = iso_or_ymd[:10]
        dt = datetime.strptime(s, "%Y-%m-%d")
    except Exception:
        try:
            dt = datetime.fromisoformat(iso_or_ymd.replace("Z", "+00:00"))
        except Exception:
            return iso_or_ymd
    # e.g. "Thursday, June 18th, 2026"
    day = dt.day
    suffix = "th" if 10 <= day % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
    return dt.strftime(f"%A, %B {day}{suffix}, %Y")


def _idr(v) -> str:
    """Format IDR as 'Rp3,300,000.00' (WHMCS-style)."""
    try:
        f = float(v or 0)
    except Exception:
        f = 0.0
    return "Rp" + f"{f:,.2f}"


def _period_label(item: dict) -> str:
    """If item has period_start / period_end (YYYY-MM-DD), append ' (dd/mm/yyyy - dd/mm/yyyy)'."""
    ps, pe = item.get("period_start"), item.get("period_end")
    if not (ps and pe):
        return ""
    try:
        s = datetime.strptime(ps[:10], "%Y-%m-%d").strftime("%d/%m/%Y")
        e = datetime.strptime(pe[:10], "%Y-%m-%d").strftime("%d/%m/%Y")
        return f" ({s} - {e})"
    except Exception:
        return ""


def _addressed_to_block(u: dict) -> str:
    company = u.get("company") or u.get("name") or ""
    attn = u.get("attention") or u.get("name") or ""
    lines = []
    if company:
        lines.append(f"<div style='font-weight:700;color:#111'>{company}</div>")
    if attn:
        lines.append(f"<div>ATTN: {attn}</div>")
    if u.get("address_line1"):
        lines.append(f"<div>{u['address_line1']}</div>")
    if u.get("address_line2"):
        lines.append(f"<div>{u['address_line2']}</div>")
    city_line = ", ".join([x for x in [u.get("city"), u.get("province"), u.get("postal_code")] if x])
    if city_line:
        lines.append(f"<div>{city_line}</div>")
    if u.get("country"):
        lines.append(f"<div>{u['country']}</div>")
    return "\n".join(lines)


# Diagonal corner ribbon (top-right), color depends on status
def _corner_ribbon(status: str) -> str:
    s = (status or "").lower()
    if s == "paid":
        color = "#22c55e"  # green
        label = "PAID"
    elif s == "overdue":
        color = "#dc2626"  # red
        label = "OVERDUE"
    elif s == "cancelled":
        color = "#64748b"
        label = "CANCELLED"
    elif s == "unpaid":
        color = "#f59e0b"  # amber
        label = "UNPAID"
    elif s in ("draft", "sent"):
        color = "#0a2350"  # navy
        label = s.upper()
    elif s == "accepted":
        color = "#22c55e"
        label = "ACCEPTED"
    elif s == "rejected":
        color = "#dc2626"
        label = "REJECTED"
    elif s == "expired":
        color = "#64748b"
        label = "EXPIRED"
    else:
        color = "#f5b120"
        label = (status or "").upper() or "&nbsp;"
    return f"""
    <div class="ribbon-wrap">
      <div class="ribbon" style="background:{color}">{label}</div>
    </div>
    """


COMPANY_HEADER_HTML = """
<div class="company-block">
  <div style="font-weight:800;letter-spacing:.02em;color:#0a2350">PT. INTERCLOUD DIGITAL INOVASI</div>
  <div>Menara Cakrawala Lt 12, Unit 1205A</div>
  <div>Jl. M.H. Thamrin No.9, RT.2/RW.1,</div>
  <div>Kb. Sirih, Kec. Menteng Kota Jakarta Pusat,</div>
  <div>Daerah Khusus Ibukota Jakarta,</div>
  <div>10340</div>
  <div style="margin-top:6px">NPWP : 62.573.806.7-021.000</div>
</div>
"""


LOGO_URL = "https://intercloud-digital.com/wp-content/uploads/2024/07/Mask-group.png"


def _pdf_template(
    *,
    doc_kind: str,           # "invoice" or "quotation"
    number: str,
    issued_date: str,        # YYYY-MM-DD or ISO
    due_or_valid_date: str,  # YYYY-MM-DD
    due_or_valid_label: str, # "Due Date" or "Valid Until"
    items: list,
    subtotal: float,
    tax_amount: float,
    total: float,
    tax_percent: float,
    status: str,
    billed_to: dict,
    transactions: list = None,
    balance: float = None,
    notes: str = "",
    banks: list = None,
    extra_footer: str = "",
    for_pdf: bool = False,
) -> str:
    """Renders the invoice/quotation HTML matching the reference layout."""
    transactions = transactions or []
    title = "Invoice" if doc_kind == "invoice" else "Quotation"
    header_title = f"{title} #{number}"

    # ---- items table (Description | Total) ----
    item_rows = "".join(
        f"<tr>"
        f"<td class='desc'>{i.get('description','')}{_period_label(i)}</td>"
        f"<td class='amt'>{_idr(i.get('total', (i.get('qty',1) * i.get('unit_price',0))))}</td>"
        f"</tr>"
        for i in items
    )

    # ---- transactions table (only if there are any) ----
    tx_rows = "".join(
        f"<tr>"
        f"<td>{_long_date(t.get('date',''))}</td>"
        f"<td>{t.get('gateway','')}</td>"
        f"<td>{t.get('transaction_id','') or '—'}</td>"
        f"<td class='amt'>{_idr(t.get('amount',0))}</td>"
        f"</tr>"
        for t in transactions
    )
    if transactions:
        bal = balance if balance is not None else max(0.0, float(total or 0) - sum(float(x.get("amount") or 0) for x in transactions))
        tx_block = f"""
        <div class="section-title">Transactions</div>
        <table class="tx">
          <thead>
            <tr>
              <th style="width:28%">Transaction Date</th>
              <th style="width:22%">Gateway</th>
              <th style="width:28%">Transaction ID</th>
              <th style="width:22%;text-align:right">Amount</th>
            </tr>
          </thead>
          <tbody>{tx_rows}</tbody>
          <tfoot>
            <tr><td colspan="3" class="bal-lbl">Balance</td><td class="amt bal-val">{_idr(bal)}</td></tr>
          </tfoot>
        </table>
        """
    else:
        tx_block = ""

    # ---- banks (unpaid only) ----
    if banks:
        bank_rows = "".join(
            f"<div class='bank-row'><span class='bank-name'>{b['bank']}</span>"
            f"<span class='bank-num'>{b['number']}</span>"
            f"<span class='bank-holder'>A/N {b['holder']}</span></div>"
            for b in banks
        )
        bank_block = f"""
        <div class="bank-panel">
          <div class="section-title" style="margin-top:0">Payment — Bank Transfer</div>
          {bank_rows}
          <div class="bank-note">Please include invoice number <b>{number}</b> in the transfer memo. Confirmation via WhatsApp speeds up reconciliation.</div>
        </div>
        """
    else:
        bank_block = ""

    ribbon = _corner_ribbon(status)
    generated_on = _long_date(datetime.now(timezone.utc).strftime("%Y-%m-%d"))

    # Actions bar only for browser (HTML) view
    actions_bar = "" if for_pdf else (
        f'<div class="actions">'
        f'<button onclick="window.print()">Print</button>'
        f'<a class="dl" href="?format=pdf&token={{TOKEN_PLACEHOLDER}}">Download PDF</a>'
        f'</div>'
    )

    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>{title} #{number}</title>
<style>
  @page {{ size: A4; margin: 14mm 14mm 16mm 14mm; }}
  * {{ box-sizing: border-box; }}
  body {{ font-family: -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
         color:#334155; margin:0; padding:0; background:#f1f5f9; font-size:12px; line-height:1.45; }}
  .paper {{ background:#fff; padding:34px 40px 30px; max-width:800px; margin:20px auto; position:relative; box-shadow:0 6px 30px rgba(2,6,23,.08); }}

  /* Corner ribbon top-right */
  .ribbon-wrap {{ position:absolute; top:0; right:0; width:170px; height:170px; overflow:hidden; pointer-events:none; }}
  .ribbon {{ position:absolute; top:24px; right:-52px; transform:rotate(45deg); width:220px; text-align:center;
             color:#fff; font-weight:800; letter-spacing:.2em; padding:8px 0; font-size:14px;
             box-shadow:0 2px 6px rgba(0,0,0,.15); }}

  /* Header */
  .head {{ display:flex; justify-content:space-between; align-items:flex-start; gap:24px; }}
  .head .logo img {{ height:64px; width:auto; object-fit:contain; }}
  .company-block {{ text-align:right; font-size:11.5px; color:#334155; line-height:1.55; }}

  /* Invoice title strip */
  .titlebar {{ margin-top:28px; background:#e5edf5; padding:14px 18px; }}
  .titlebar h1 {{ margin:0 0 6px 0; font-size:20px; color:#334155; font-weight:800; }}
  .titlebar .meta-line {{ font-size:12px; color:#475569; }}
  .titlebar .meta-line b {{ color:#0f172a; font-weight:600; }}

  /* Invoiced To */
  .to {{ margin-top:22px; }}
  .to .lbl {{ font-weight:700; font-size:12px; color:#111; margin-bottom:6px; }}
  .to .body {{ font-size:11.5px; color:#475569; line-height:1.6; }}

  /* Items table */
  table.items {{ width:100%; border-collapse:collapse; margin-top:22px; font-size:12px; }}
  table.items thead th {{ background:#e5edf5; color:#334155; font-weight:700; padding:9px 12px; text-align:center; border:1px solid #cbd5e1; }}
  table.items tbody td {{ padding:11px 12px; border:1px solid #e2e8f0; vertical-align:top; }}
  table.items td.desc {{ background:#fff; }}
  table.items td.amt {{ text-align:right; white-space:nowrap; font-variant-numeric:tabular-nums; }}

  /* Totals block */
  .totals {{ margin-top:6px; }}
  .totals table {{ margin-left:auto; border-collapse:collapse; font-size:12px; }}
  .totals td {{ padding:7px 14px; border:1px solid #e2e8f0; }}
  .totals td.lbl {{ background:#f1f5f9; text-align:right; font-weight:700; color:#0f172a; width:170px; }}
  .totals td.val {{ text-align:right; width:170px; font-variant-numeric:tabular-nums; }}
  .totals tr.grand td.lbl,
  .totals tr.grand td.val {{ background:#f1f5f9; font-weight:800; color:#0f172a; }}

  /* Transactions */
  .section-title {{ margin-top:28px; font-size:15px; font-weight:800; color:#0f172a; }}
  table.tx {{ width:100%; border-collapse:collapse; margin-top:10px; font-size:12px; }}
  table.tx thead th {{ background:#e5edf5; padding:9px 12px; border:1px solid #cbd5e1; color:#334155; text-align:center; font-weight:700; }}
  table.tx tbody td {{ padding:9px 12px; border:1px solid #e2e8f0; text-align:center; }}
  table.tx td.amt {{ text-align:right; font-variant-numeric:tabular-nums; }}
  table.tx tfoot td {{ padding:9px 12px; border:1px solid #e2e8f0; }}
  table.tx tfoot td.bal-lbl {{ text-align:right; font-weight:800; color:#0f172a; background:#f1f5f9; }}
  table.tx tfoot td.bal-val {{ background:#f1f5f9; font-weight:800; color:#0f172a; }}

  /* Bank panel */
  .bank-panel {{ margin-top:26px; background:#fffbeb; border:1px solid #fde68a; padding:14px 16px; }}
  .bank-row {{ display:flex; gap:16px; padding:4px 0; font-size:12px; }}
  .bank-name {{ font-weight:800; color:#0a2350; min-width:80px; }}
  .bank-num  {{ font-family: "SFMono-Regular", ui-monospace, Menlo, Consolas, monospace; color:#111; min-width:180px; }}
  .bank-holder {{ color:#78350f; }}
  .bank-note {{ font-size:11px; color:#78350f; margin-top:6px; }}

  /* Notes */
  .notes {{ margin-top:22px; font-size:11.5px; color:#475569; }}

  /* Footer */
  .foot {{ margin-top:26px; text-align:center; font-size:11px; color:#94a3b8; }}

  /* Print actions bar (HTML view only) */
  .actions {{ text-align:center; padding:16px 0 0 0; }}
  .actions button, .actions a.dl {{ display:inline-block; background:#0a2350; color:#fff; border:0; border-radius:99px; padding:8px 22px; font-weight:700; font-size:12px; cursor:pointer; text-decoration:none; margin: 0 6px; }}
  .actions a.dl {{ background:#f5b120; color:#0a2350; }}
  @media print {{ body {{ background:#fff }} .paper {{ box-shadow:none; margin:0 }} .actions {{ display:none }} }}
</style></head>
<body>
{actions_bar}
<div class="paper">
  {ribbon}

  <div class="head">
    <div class="logo"><img src="{LOGO_URL}" alt="Intercloud Digital Inovasi"/></div>
    {COMPANY_HEADER_HTML}
  </div>

  <div class="titlebar">
    <h1>{header_title}</h1>
    <div class="meta-line">{title} Date: <b>{_long_date(issued_date)}</b></div>
    <div class="meta-line">{due_or_valid_label}: <b>{_long_date(due_or_valid_date)}</b></div>
  </div>

  <div class="to">
    <div class="lbl">Invoiced To</div>
    <div class="body">
      {_addressed_to_block(billed_to)}
    </div>
  </div>

  <table class="items">
    <thead>
      <tr><th style="text-align:center">Description</th><th style="text-align:center;width:180px">Total</th></tr>
    </thead>
    <tbody>{item_rows}</tbody>
  </table>

  <div class="totals">
    <table>
      <tr><td class="lbl">Sub Total</td><td class="val">{_idr(subtotal)}</td></tr>
      <tr><td class="lbl">Tax ({tax_percent:g}%)</td><td class="val">{_idr(tax_amount)}</td></tr>
      <tr><td class="lbl">Credit</td><td class="val">{_idr(0)}</td></tr>
      <tr class="grand"><td class="lbl">Total</td><td class="val">{_idr(total)}</td></tr>
    </table>
  </div>

  {tx_block}

  {bank_block}

  {("<div class='notes'>" + notes + "</div>") if notes else ""}

  {extra_footer}

  <div class="foot">PDF Generated on {generated_on}</div>
</div>
</body></html>
"""


def _render_pdf_bytes(html: str) -> bytes:
    from weasyprint import HTML
    return HTML(string=html).write_pdf()


@router.get("/documents/invoice/{iid}")
async def render_invoice_pdf(iid: str, format: str = "html", user=Depends(get_current_user)):
    db = await _get_db()
    d = await db.invoices.find_one({"_id": _oid(iid)})
    if not d:
        raise HTTPException(status_code=404, detail="Invoice not found")
    # Access: owner or staff
    if user["role"] == "client" and str(d["user_id"]) != str(user["id"]):
        raise HTTPException(status_code=403, detail="Not your invoice")
    u = await db.users.find_one({"_id": d["user_id"]}) or {}

    bank_doc = await db.settings.find_one({"key": "bank_accounts"}) or {}
    banks = bank_doc.get("value") or [
        {"bank": "MANDIRI", "number": "1240011911816", "holder": "INTERCLOUD DIGITAL INOVASI"},
        {"bank": "BCA", "number": "4730862038", "holder": "ANANG MADIA CUGITA"},
    ]

    status = (d.get("status") or "unpaid").lower()

    # Synthesize transactions from paid_at + payment_method when invoice is paid
    tx_list = list(d.get("transactions") or [])
    if not tx_list and status == "paid" and d.get("paid_at"):
        tx_list = [{
            "date": d.get("paid_at"),
            "gateway": (d.get("payment_method") or "Bank Transfer").replace("_", " ").title(),
            "transaction_id": d.get("payment_ref") or "",
            "amount": d.get("total", 0),
        }]

    html = _pdf_template(
        doc_kind="invoice",
        number=d.get("number", ""),
        issued_date=(d.get("created_at") or "")[:10],
        due_or_valid_date=d.get("due_date", ""),
        due_or_valid_label="Due Date",
        items=d.get("items", []),
        subtotal=d.get("subtotal", 0),
        tax_amount=d.get("tax_amount", 0),
        total=d.get("total", 0),
        tax_percent=d.get("tax_percent", 11.0),
        status=status,
        billed_to=u,
        transactions=tx_list,
        banks=banks if status in ("unpaid", "overdue") else None,
        notes=d.get("notes", ""),
        for_pdf=(format == "pdf"),
    )

    if format == "pdf":
        pdf_bytes = _render_pdf_bytes(html)
        filename = f"Invoice-{d.get('number','invoice')}.pdf"
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    # For HTML view, inject token so the "Download PDF" button in-page can carry auth
    token = user.get("_token", "")
    html = html.replace("{TOKEN_PLACEHOLDER}", token)
    return HTMLResponse(content=html)


@router.get("/documents/quotation/{qid}")
async def render_quotation_pdf(qid: str, format: str = "html", staff=Depends(get_current_staff)):
    db = await _get_db()
    d = await db.quotations.find_one({"_id": _oid(qid)})
    if not d:
        raise HTTPException(status_code=404, detail="Quotation not found")
    u = await db.users.find_one({"_id": d["user_id"]}) or {}
    status = (d.get("status") or "draft").lower()

    html = _pdf_template(
        doc_kind="quotation",
        number=d.get("number", ""),
        issued_date=(d.get("created_at") or "")[:10],
        due_or_valid_date=d.get("valid_until", ""),
        due_or_valid_label="Valid Until",
        items=d.get("items", []),
        subtotal=d.get("subtotal", 0),
        tax_amount=d.get("tax_amount", 0),
        total=d.get("total", 0),
        tax_percent=d.get("tax_percent", 11.0),
        status=status,
        billed_to=u,
        transactions=[],
        banks=None,
        notes=d.get("notes", ""),
        extra_footer=(
            "<div style='margin-top:22px;font-size:11px;color:#64748b;line-height:1.7'>"
            "This quotation is valid until the date shown above. Prices are in Indonesian Rupiah (IDR) and exclude any applicable "
            "withholding tax. To accept this quotation, reply via email or WhatsApp — an invoice will be issued upon acceptance."
            "</div>"
        ),
        for_pdf=(format == "pdf"),
    )

    if format == "pdf":
        pdf_bytes = _render_pdf_bytes(html)
        filename = f"Quotation-{d.get('number','quotation')}.pdf"
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f'inline; filename="{filename}"'},
        )

    token = staff.get("_token", "")
    html = html.replace("{TOKEN_PLACEHOLDER}", token)
    return HTMLResponse(content=html)


# Traffic Report (mocked realistic time series)
@router.get("/client/services/{sid}/traffic")
async def client_service_traffic(sid: str, user=Depends(get_current_user)):
    db = await _get_db()
    d = await db.services.find_one({"_id": _oid(sid), "user_id": ObjectId(user["id"])})
    if not d:
        raise HTTPException(status_code=404, detail="Service not found")
    # Deterministic mocked data based on service id hash
    import random
    seed = sum(ord(c) for c in sid)
    r = random.Random(seed)
    now = datetime.now(timezone.utc)
    points = []
    for i in range(24):
        h = now - timedelta(hours=23 - i)
        base_in = r.uniform(150, 850)
        base_out = r.uniform(120, 700)
        points.append({
            "t": h.strftime("%H:00"),
            "in_mbps": round(base_in, 1),
            "out_mbps": round(base_out, 1),
        })
    total_in = round(sum(p["in_mbps"] for p in points) * 60 / 8 / 1024, 2)  # GB
    total_out = round(sum(p["out_mbps"] for p in points) * 60 / 8 / 1024, 2)
    return {
        "service_id": sid,
        "service_name": d.get("name", ""),
        "range": "24h",
        "points": points,
        "totals": {"in_gb": total_in, "out_gb": total_out},
        "peak_in_mbps": max(p["in_mbps"] for p in points),
        "peak_out_mbps": max(p["out_mbps"] for p in points),
    }


# ============================================================
# Password lifecycle — change / admin-reset / forgot / reset
# ============================================================
import hashlib  # noqa: E402
import secrets as _secrets  # noqa: E402
from fastapi import Request  # noqa: E402
from portal import integrations_v2 as iv2  # noqa: E402


@router.post("/auth/change-password")
async def auth_change_password(payload: m.ChangePasswordIn, user=Depends(get_current_user)):
    """Any authenticated user (client or staff) can rotate their OWN password."""
    db = await _get_db()
    u = await db.users.find_one({"_id": ObjectId(user["id"])})
    if not u or not verify_password(payload.current_password, u["password_hash"]):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    if payload.current_password == payload.new_password:
        raise HTTPException(status_code=400, detail="New password must differ from the current one")
    await db.users.update_one(
        {"_id": u["_id"]},
        {"$set": {"password_hash": hash_password(payload.new_password),
                  "password_changed_at": _now()}},
    )
    # Invalidate any outstanding reset tokens for this user
    await db.password_resets.update_many({"user_id": u["_id"], "used": False}, {"$set": {"used": True}})
    return {"ok": True, "message": "Password updated"}


@router.post("/admin/users/{uid}/reset-password")
async def admin_reset_user_password(uid: str, payload: m.AdminResetPasswordIn,
                                    admin=Depends(get_current_admin)):
    """Admin sets a new password for another user. Optionally emails them."""
    db = await _get_db()
    target = await db.users.find_one({"_id": _oid(uid)})
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    await db.users.update_one(
        {"_id": target["_id"]},
        {"$set": {"password_hash": hash_password(payload.new_password),
                  "password_changed_at": _now(),
                  "password_reset_by": ObjectId(admin["id"])}},
    )
    await db.password_resets.update_many({"user_id": target["_id"], "used": False},
                                         {"$set": {"used": True}})
    # Optional email
    sent = False
    if payload.notify_user:
        try:
            await _send_password_notice(db, target, kind="admin_reset")
            sent = True
        except Exception:
            sent = False
    return {"ok": True, "message": f"Password reset for {target['email']}", "email_sent": sent}


@router.post("/auth/forgot-password")
async def auth_forgot_password(payload: m.ForgotPasswordIn, request: Request):
    """Public. Always returns 200 to avoid email enumeration.

    Generates a signed one-time token, stores it (hashed) in `password_resets`,
    and emails the user a link. If SMTP isn't configured we log the link so
    the admin can still recover the user manually while awaiting SMTP setup.
    """
    db = await _get_db()
    from portal import integrations_v2 as _iv2
    await _iv2.enforce_recaptcha(
        db, payload.recaptcha_token, "forgot",
        request.client.host if request.client else None,
    )
    email = payload.email.lower().strip()
    u = await db.users.find_one({"email": email})
    if u:
        raw = _secrets.token_urlsafe(48)
        token_hash = hashlib.sha256(raw.encode()).hexdigest()
        expires = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        await db.password_resets.insert_one({
            "user_id": u["_id"], "email": email, "token_hash": token_hash,
            "expires_at": expires, "used": False, "created_at": _now(),
            "requester_ip": (request.client.host if request.client else "unknown"),
        })
        # Best-effort email
        origin = os.environ.get("REACT_APP_BACKEND_URL", "")
        reset_url = f"{origin}/portal/reset-password?token={raw}"
        try:
            await _send_password_notice(db, u, kind="forgot", reset_url=reset_url)
        except Exception as e:
            # SMTP down or not configured → log the link to backend log so admin can share it.
            import logging
            logging.getLogger("portal.password_reset").warning(
                f"[password-reset] SMTP unavailable ({e}) — reset link for {email}: {reset_url}"
            )
    # Always the same response
    return {"ok": True, "message": "If an account exists for that email, a reset link has been sent."}


@router.post("/auth/reset-password")
async def auth_reset_password(payload: m.ResetPasswordIn):
    db = await _get_db()
    token_hash = hashlib.sha256(payload.token.encode()).hexdigest()
    row = await db.password_resets.find_one({"token_hash": token_hash, "used": False})
    if not row:
        raise HTTPException(status_code=400, detail="This reset link is invalid or has already been used.")
    if row.get("expires_at", "") < datetime.now(timezone.utc).isoformat():
        raise HTTPException(status_code=400, detail="This reset link has expired. Request a new one.")
    await db.users.update_one(
        {"_id": row["user_id"]},
        {"$set": {"password_hash": hash_password(payload.new_password),
                  "password_changed_at": _now()}},
    )
    await db.password_resets.update_one({"_id": row["_id"]},
                                        {"$set": {"used": True, "used_at": _now()}})
    return {"ok": True, "message": "Password updated. You may now log in."}


async def _send_password_notice(db, user: dict, *, kind: str, reset_url: str = "") -> None:
    """Compose + send transactional email via SMTP integration.

    Raises on any failure — caller decides whether to swallow.
    """
    smtp = await iv2.get_settings(db, "smtp") if False else None  # avoid circular; done below
    # Late import (routes.py appended block hasn't imported iv2 up here in this hunk)
    from portal import integrations_v2 as _iv2
    smtp = await _iv2.get_settings(db, "smtp")
    if not smtp or not smtp.get("enabled"):
        raise RuntimeError("SMTP not configured")
    if kind == "forgot":
        subject = "Reset your Intercloud portal password"
        html = (
            f"<p>Hi {user.get('name','there')},</p>"
            f"<p>We received a password-reset request for your Intercloud portal account. "
            f"Click the button below within the next 60 minutes to set a new password:</p>"
            f"<p><a href='{reset_url}' style='display:inline-block;padding:10px 22px;"
            f"background:#0a2350;color:#fff;text-decoration:none;border-radius:99px;"
            f"font-weight:700;letter-spacing:.05em'>Reset password</a></p>"
            f"<p style='color:#64748b;font-size:12px'>If the button doesn't work, copy and paste this link:<br>{reset_url}</p>"
            f"<p style='color:#64748b;font-size:12px'>Didn't request this? You can ignore this email — your password wasn't changed.</p>"
        )
    else:
        subject = "Your Intercloud portal password was reset"
        html = (
            f"<p>Hi {user.get('name','there')},</p>"
            f"<p>An administrator has reset the password for your Intercloud portal account. "
            f"Please contact your account manager for the new password, "
            f"or use the &lsquo;Forgot password&rsquo; link on the portal login page.</p>"
        )
    _iv2.SMTPMailer(smtp).send(to=user["email"], subject=subject, html=html)



@router.get("/admin/integrations-v2/schema")
async def integrations_v2_schema(admin=Depends(get_current_admin)):
    """Returns the field schema the admin UI uses to render each integration's settings form."""
    return iv2.INTEGRATION_SCHEMA


@router.get("/admin/integrations-v2")
async def integrations_v2_list(admin=Depends(get_current_admin)):
    """Return all persisted integration settings (secrets masked)."""
    db = await _get_db()
    out = {}
    for provider in iv2.INTEGRATION_SCHEMA.keys():
        d = await iv2.get_settings(db, provider)
        out[provider] = iv2.redact(d) or {"provider": provider, "enabled": False, "credentials": {}, "options": {}}
    return out


@router.put("/admin/integrations-v2/{provider}")
async def integrations_v2_upsert(provider: str, payload: dict, admin=Depends(get_current_admin)):
    if provider not in iv2.INTEGRATION_SCHEMA:
        raise HTTPException(status_code=404, detail="Unknown provider")
    db = await _get_db()
    # Merge — never drop existing secrets if the incoming value is empty
    existing = await iv2.get_settings(db, provider) or {}
    creds_in = payload.get("credentials") or {}
    merged_creds = {**(existing.get("credentials") or {})}
    for k, v in creds_in.items():
        if v not in ("", None):
            merged_creds[k] = v
    doc = {
        "enabled": bool(payload.get("enabled")),
        "sandbox": payload.get("sandbox", existing.get("sandbox", True)),
        "channel": payload.get("channel", existing.get("channel")),
        "credentials": merged_creds,
        "options": payload.get("options", existing.get("options") or {}),
    }
    saved = await iv2.upsert_settings(db, provider, doc)
    return iv2.redact(saved)


@router.delete("/admin/integrations-v2/{provider}")
async def integrations_v2_delete(provider: str, admin=Depends(get_current_admin)):
    """Wipe all persisted settings for a provider (credentials + options + enabled).

    Useful for rotating credentials cleanly — the PUT endpoint merges by design,
    so it cannot clear a stored secret on its own.
    """
    if provider not in iv2.INTEGRATION_SCHEMA:
        raise HTTPException(status_code=404, detail="Unknown provider")
    db = await _get_db()
    r = await db.integration_settings.delete_one({"provider": provider})
    return {"deleted": r.deleted_count}


@router.post("/admin/integrations-v2/{provider}/test")
async def integrations_v2_test(provider: str, admin=Depends(get_current_admin)):
    db = await _get_db()
    settings = await iv2.get_settings(db, provider)
    if not settings:
        return {"ok": False, "message": "Integration is not configured yet."}
    if provider == "proxmox":
        return await iv2.ProxmoxClient(settings).test_connection()
    if provider == "mikrotik":
        return iv2.MikrotikClient(settings).test_connection()
    if provider in iv2.PAYMENT_PROVIDERS:
        gw = iv2.payment_gateway(provider, settings)
        return await gw.test_connection()
    if provider == "smtp":
        return iv2.SMTPMailer(settings).test_connection()
    if provider == "imap":
        return iv2.IMAPClient(settings).test_connection()
    if provider in ("cpanel", "plesk"):
        # No SDK adapter yet — validate that required fields are present.
        c = settings.get("credentials") or {}
        missing = [k for k in ("host", "username") if not c.get(k)]
        secret_ok = bool(c.get("api_token") or c.get("password"))
        if missing or not secret_ok:
            return {"ok": False, "message": f"Missing credentials: {', '.join(missing) or 'api_token/password'}"}
        return {"ok": True, "message": f"{provider.upper()} credentials look complete — live wiring pending."}
    return {"ok": False, "message": "No test method"}


# ---------------- Proxmox live actions ----------------
@router.get("/admin/proxmox/nodes")
async def proxmox_nodes(admin=Depends(get_current_admin)):
    db = await _get_db()
    s = await iv2.get_settings(db, "proxmox")
    if not s or not s.get("enabled"):
        raise HTTPException(status_code=400, detail="Proxmox not configured")
    return await iv2.ProxmoxClient(s).list_nodes()


@router.get("/admin/proxmox/vms")
async def proxmox_vms(node: Optional[str] = None, admin=Depends(get_current_admin)):
    db = await _get_db()
    s = await iv2.get_settings(db, "proxmox")
    if not s or not s.get("enabled"):
        raise HTTPException(status_code=400, detail="Proxmox not configured")
    return await iv2.ProxmoxClient(s).list_vms(node)


@router.post("/admin/proxmox/vms/{node}/{vmid}/{action}")
async def proxmox_vm_action(node: str, vmid: int, action: str, admin=Depends(get_current_admin)):
    if action not in ("start", "stop", "reboot", "shutdown", "suspend", "resume"):
        raise HTTPException(status_code=400, detail="Unsupported action")
    db = await _get_db()
    s = await iv2.get_settings(db, "proxmox")
    if not s or not s.get("enabled"):
        raise HTTPException(status_code=400, detail="Proxmox not configured")
    return await iv2.ProxmoxClient(s).vm_action(node, vmid, action)


@router.get("/admin/proxmox/vnc/{node}/{vmid}")
async def proxmox_vnc(node: str, vmid: int, admin=Depends(get_current_admin)):
    db = await _get_db()
    s = await iv2.get_settings(db, "proxmox")
    if not s or not s.get("enabled"):
        raise HTTPException(status_code=400, detail="Proxmox not configured")
    ticket = await iv2.ProxmoxClient(s).vnc_ticket(node, vmid)
    return {"ticket": ticket, "wss": f"{iv2.ProxmoxClient(s).host}/?console=kvm&novnc=1&vmid={vmid}&node={node}"}


# ---------------- Mikrotik live views ----------------
@router.get("/admin/mikrotik/interfaces")
async def mikrotik_interfaces(admin=Depends(get_current_admin)):
    db = await _get_db()
    s = await iv2.get_settings(db, "mikrotik")
    if not s or not s.get("enabled"):
        raise HTTPException(status_code=400, detail="Mikrotik not configured")
    return iv2.MikrotikClient(s).list_interfaces()


@router.get("/admin/mikrotik/bgp")
async def mikrotik_bgp(admin=Depends(get_current_admin)):
    db = await _get_db()
    s = await iv2.get_settings(db, "mikrotik")
    if not s or not s.get("enabled"):
        raise HTTPException(status_code=400, detail="Mikrotik not configured")
    return iv2.MikrotikClient(s).list_bgp_peers()


@router.get("/admin/mikrotik/traffic")
async def mikrotik_traffic(interface: str, admin=Depends(get_current_admin)):
    db = await _get_db()
    s = await iv2.get_settings(db, "mikrotik")
    if not s or not s.get("enabled"):
        raise HTTPException(status_code=400, detail="Mikrotik not configured")
    return iv2.MikrotikClient(s).traffic_monitor(interface)


# ---------------- Payment gateway — create + webhook ----------------
@router.post("/client/invoices/{iid}/pay-online")
async def client_pay_online(iid: str, provider: str, user=Depends(get_current_user)):
    """Create a hosted payment link for the given invoice."""
    db = await _get_db()
    inv = await db.invoices.find_one({"_id": _oid(iid), "user_id": ObjectId(user["id"])})
    if not inv:
        raise HTTPException(status_code=404, detail="Invoice not found")
    if inv.get("status") == "paid":
        raise HTTPException(status_code=400, detail="Invoice already paid")
    s = await iv2.get_settings(db, provider)
    if not s or not s.get("enabled"):
        raise HTTPException(status_code=400, detail=f"{provider} not configured")
    gw = iv2.payment_gateway(provider, s)
    backend = os.environ.get("REACT_APP_BACKEND_URL") or ""
    callback = f"{backend}/api/portal/webhooks/{provider}"
    result = await gw.create_payment(
        invoice_id=inv["number"] or str(inv["_id"]),
        amount_idr=int(inv["total"]),
        customer_email=user["email"],
        callback_url=callback,
    )
    await db.invoices.update_one(
        {"_id": inv["_id"]},
        {"$set": {"payment_provider": provider, "payment_external_id": result.get("external_id"),
                  "payment_link": result.get("payment_url")}},
    )
    return result


@router.post("/webhooks/{provider}")
async def payment_webhook(provider: str, request: Request):
    """Public webhook. Verifies signature before marking any invoice as paid."""
    db = await _get_db()
    s = await iv2.get_settings(db, provider)
    if not s:
        raise HTTPException(status_code=404, detail="Unknown gateway")
    raw = await request.body()
    gw = iv2.payment_gateway(provider, s)
    try:
        if provider == "xendit":
            verified = gw.verify_webhook({k.lower(): v for k, v in request.headers.items()}, raw)
        else:
            verified = gw.verify_webhook(raw)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid webhook: {e}")

    if verified["status"] == "paid":
        # Mark the invoice paid by external reference number (which we set to invoice.number)
        upd = {"status": "paid", "paid_at": _now(), "payment_method": provider,
               "payment_ref": verified.get("external_id")}
        r = await db.invoices.update_one({"number": verified["invoice_id"]}, {"$set": upd})
        # Fire the same auto-provision hook as manual admin-mark-paid
        if r.modified_count:
            inv = await db.invoices.find_one({"number": verified["invoice_id"]})
            if inv and inv.get("order_id"):
                order = await db.orders.find_one({"_id": _oid(inv["order_id"])})
                if order:
                    try:
                        await _auto_provision(db, order)
                    except Exception:
                        pass
    return {"received": True, "status": verified["status"]}


# ============================================================
# SECURITY — Login Attempt Analytics
# ============================================================
@router.get("/admin/security/login-analytics")
async def login_analytics(
    admin=Depends(get_current_admin),
    window: str = "24h",  # 24h | 7d | 30d
    limit: int = 100,
):
    """Aggregate login attempts for the Admin Security dashboard.
    Powered by the `login_attempts` collection populated by `/auth/login`."""
    db = await _get_db()
    now = datetime.now(timezone.utc)
    windows = {"24h": timedelta(hours=24), "7d": timedelta(days=7), "30d": timedelta(days=30)}
    delta = windows.get(window, timedelta(hours=24))
    since = (now - delta).isoformat()

    cursor = db.login_attempts.find({"created_at": {"$gte": since}}).sort("created_at", -1)
    rows = await cursor.to_list(20000)

    total = len(rows)
    successes = sum(1 for r in rows if r.get("success"))
    failures = total - successes
    success_rate = round((successes / total) * 100, 2) if total else 0.0
    recap_blocks = sum(1 for r in rows if r.get("reason", "").startswith("recaptcha"))

    # Reason breakdown
    reason_counts: dict[str, int] = {}
    for r in rows:
        k = r.get("reason", "unknown")
        reason_counts[k] = reason_counts.get(k, 0) + 1

    # Top offending IPs (failures only)
    ip_counts: dict[str, int] = {}
    for r in rows:
        if not r.get("success"):
            ip = r.get("ip", "unknown")
            ip_counts[ip] = ip_counts.get(ip, 0) + 1
    top_ips = sorted(ip_counts.items(), key=lambda kv: kv[1], reverse=True)[:10]

    # Top targeted emails (failures only)
    email_counts: dict[str, int] = {}
    for r in rows:
        if not r.get("success"):
            em = r.get("email") or "(empty)"
            email_counts[em] = email_counts.get(em, 0) + 1
    top_emails = sorted(email_counts.items(), key=lambda kv: kv[1], reverse=True)[:10]

    # Time series buckets
    if window == "24h":
        # hourly buckets
        buckets: dict[str, dict] = {}
        for h in range(24, -1, -1):
            t = now - timedelta(hours=h)
            key = t.strftime("%Y-%m-%d %H:00")
            buckets[key] = {"bucket": key, "success": 0, "failed": 0, "recaptcha_block": 0}
        for r in rows:
            ts = r.get("created_at", "")
            key = ts[:13] + ":00"
            if key in buckets:
                if r.get("success"):
                    buckets[key]["success"] += 1
                else:
                    buckets[key]["failed"] += 1
                    if r.get("reason", "").startswith("recaptcha"):
                        buckets[key]["recaptcha_block"] += 1
        series = list(buckets.values())
    else:
        days = 7 if window == "7d" else 30
        buckets = {}
        for d in range(days, -1, -1):
            t = now - timedelta(days=d)
            key = t.strftime("%Y-%m-%d")
            buckets[key] = {"bucket": key, "success": 0, "failed": 0, "recaptcha_block": 0}
        for r in rows:
            key = (r.get("created_at", "") or "")[:10]
            if key in buckets:
                if r.get("success"):
                    buckets[key]["success"] += 1
                else:
                    buckets[key]["failed"] += 1
                    if r.get("reason", "").startswith("recaptcha"):
                        buckets[key]["recaptcha_block"] += 1
        series = list(buckets.values())

    # reCAPTCHA score distribution (buckets of 0.1)
    score_buckets = [{"bucket": f"{b/10:.1f}", "count": 0} for b in range(0, 11)]
    for r in rows:
        s = r.get("recaptcha_score")
        if s is None:
            continue
        idx = min(int(float(s) * 10), 10)
        score_buckets[idx]["count"] += 1
    scored_rows = sum(sb["count"] for sb in score_buckets)

    # Recent attempts
    recent = [{
        "id": str(r.get("_id", "")),
        "email": r.get("email", ""),
        "action": r.get("action", ""),
        "success": bool(r.get("success")),
        "reason": r.get("reason", ""),
        "ip": r.get("ip", ""),
        "user_agent": (r.get("user_agent") or "")[:120],
        "recaptcha_enabled": bool(r.get("recaptcha_enabled")),
        "recaptcha_score": r.get("recaptcha_score"),
        "created_at": r.get("created_at", ""),
    } for r in rows[:max(1, min(limit, 500))]]

    return {
        "window": window,
        "since": since,
        "totals": {
            "attempts": total,
            "successes": successes,
            "failures": failures,
            "success_rate": success_rate,
            "recaptcha_blocks": recap_blocks,
        },
        "reason_breakdown": [{"reason": k, "count": v} for k, v in
                             sorted(reason_counts.items(), key=lambda kv: kv[1], reverse=True)],
        "top_ips": [{"ip": k, "count": v} for k, v in top_ips],
        "top_emails": [{"email": k, "count": v} for k, v in top_emails],
        "series": series,
        "score_distribution": {"buckets": score_buckets, "total_scored": scored_rows},
        "recent": recent,
    }


# ---------- Security Settings & Blocked IPs ----------
@router.get("/admin/security/settings")
async def security_settings_get(admin=Depends(get_current_admin)):
    db = await _get_db()
    s = await _get_security_settings(db)
    return s


@router.put("/admin/security/settings")
async def security_settings_put(payload: dict, admin=Depends(get_current_admin)):
    db = await _get_db()
    allowed = {"auto_block_enabled", "fail_threshold", "window_minutes", "ban_minutes",
               "notify_emails", "whitelist_ips",
               "email_notify_enabled", "telegram_notify_enabled"}
    upd = {k: v for k, v in (payload or {}).items() if k in allowed}
    # type coercion
    if "fail_threshold" in upd: upd["fail_threshold"] = max(1, int(upd["fail_threshold"]))
    if "window_minutes" in upd: upd["window_minutes"] = max(1, int(upd["window_minutes"]))
    if "ban_minutes" in upd:    upd["ban_minutes"]    = max(1, int(upd["ban_minutes"]))
    for boolkey in ("auto_block_enabled", "email_notify_enabled", "telegram_notify_enabled"):
        if boolkey in upd: upd[boolkey] = bool(upd[boolkey])
    if "notify_emails" in upd:
        upd["notify_emails"] = [str(x).strip() for x in (upd["notify_emails"] or []) if str(x).strip()]
    if "whitelist_ips" in upd:
        upd["whitelist_ips"] = [str(x).strip() for x in (upd["whitelist_ips"] or []) if str(x).strip()]
    await db.settings.update_one({"_id": "security"}, {"$set": upd}, upsert=True)
    return await _get_security_settings(db)


@router.get("/admin/security/blocked-ips")
async def blocked_ips_list(admin=Depends(get_current_admin), active_only: bool = False):
    db = await _get_db()
    now_dt = datetime.now(timezone.utc)
    docs = await db.blocked_ips.find({}).sort("blocked_at", -1).to_list(500)
    out = []
    for d in docs:
        exp = d.get("expires_at")
        if isinstance(exp, str):
            try: exp_dt = datetime.fromisoformat(exp.replace("Z", "+00:00"))
            except Exception: exp_dt = None
        else:
            exp_dt = exp
        # Normalize naive datetimes (MongoDB returns tz-naive UTC)
        if isinstance(exp_dt, datetime) and exp_dt.tzinfo is None:
            exp_dt = exp_dt.replace(tzinfo=timezone.utc)
        is_active = (exp_dt is not None and exp_dt > now_dt and not d.get("unblocked_at"))
        if active_only and not is_active:
            continue
        out.append({
            "ip": d.get("ip"),
            "blocked_at": d.get("blocked_at"),
            "expires_at": (exp_dt.isoformat() if exp_dt else None),
            "reason": d.get("reason"),
            "hits": d.get("hits", 0),
            "unblocked_at": d.get("unblocked_at"),
            "active": bool(is_active),
        })
    return out


@router.delete("/admin/security/blocked-ips/{ip}")
async def blocked_ips_unblock(ip: str, admin=Depends(get_current_admin)):
    db = await _get_db()
    await db.blocked_ips.update_one(
        {"ip": ip},
        {"$set": {"unblocked_at": _now(), "expires_at": _now()}},
    )
    return {"ok": True, "ip": ip}


@router.post("/admin/security/blocked-ips")
async def blocked_ips_add(payload: dict, admin=Depends(get_current_admin)):
    ip = (payload.get("ip") or "").strip()
    ban_minutes = max(1, int(payload.get("ban_minutes") or 30))
    if not ip:
        raise HTTPException(status_code=400, detail="ip required")
    db = await _get_db()
    now_dt = datetime.now(timezone.utc)
    await db.blocked_ips.update_one(
        {"ip": ip},
        {"$set": {
            "ip": ip,
            "blocked_at": now_dt.isoformat(),
            "expires_at": now_dt + timedelta(minutes=ban_minutes),
            "reason": payload.get("reason") or "manual_block",
            "hits": int(payload.get("hits", 0)),
            "unblocked_at": None,
        }},
        upsert=True,
    )
    return {"ok": True, "ip": ip}


@router.get("/admin/security/notifications")
async def security_notifications_list(admin=Depends(get_current_admin), limit: int = 50):
    db = await _get_db()
    limit = max(1, min(limit, 200))
    docs = await db.security_notifications.find({}).sort("created_at", -1).to_list(limit)
    return [{**{k: v for k, v in d.items() if k != "_id"}, "id": str(d["_id"])} for d in docs]


@router.post("/admin/security/notifications/mark-read")
async def security_notifications_mark_read(payload: dict, admin=Depends(get_current_admin)):
    db = await _get_db()
    ids = payload.get("ids") or []
    if ids:
        from bson import ObjectId as _OID
        await db.security_notifications.update_many(
            {"_id": {"$in": [_OID(i) for i in ids]}},
            {"$set": {"read": True}},
        )
    else:
        await db.security_notifications.update_many({}, {"$set": {"read": True}})
    return {"ok": True}


@router.post("/admin/security/notifications/test")
async def security_notifications_test(payload: dict, admin=Depends(get_current_admin)):
    """Fire a sample notification through email + Telegram so the admin can
    verify their SMTP / Telegram integrations from the Security dashboard."""
    db = await _get_db()
    s = await _get_security_settings(db)
    from portal import integrations_v2 as _iv2
    result = {"email": {"attempted": False}, "telegram": {"attempted": False}}

    # Email
    recipients = payload.get("emails") or s.get("notify_emails") or []
    recipients = [r.strip() for r in recipients if r and r.strip()]
    smtp_doc = await _iv2.get_settings(db, "smtp")
    if smtp_doc and smtp_doc.get("enabled") and recipients:
        result["email"]["attempted"] = True
        try:
            mailer = _iv2.SMTPMailer(smtp_doc)
            import asyncio as _asyncio
            loop = _asyncio.get_event_loop()
            errs = []
            for to in recipients:
                try:
                    await loop.run_in_executor(None, lambda t=to: mailer.send(
                        to=t, subject="[Intercloud Security] Test alert",
                        html="<p>This is a <b>test</b> alert from the Intercloud Portal Security dashboard.</p>",
                        text="Test alert from Intercloud Portal Security dashboard."))
                except Exception as e:
                    errs.append(f"{to}: {e}")
            result["email"]["ok"] = not errs
            result["email"]["errors"] = errs
            result["email"]["sent_to"] = recipients
        except Exception as e:
            result["email"]["ok"] = False
            result["email"]["errors"] = [str(e)]
    else:
        result["email"]["reason"] = "SMTP integration not enabled or no recipients"

    # Telegram
    tg_doc = await _iv2.get_telegram_settings(db)
    if tg_doc:
        result["telegram"]["attempted"] = True
        try:
            tg = _iv2.TelegramNotifier(tg_doc)
            r = await tg.send("*🔔 Intercloud test alert*\nThis is a test message from Security dashboard.")
            result["telegram"]["ok"] = bool(r.get("ok"))
            result["telegram"]["details"] = r
        except Exception as e:
            result["telegram"]["ok"] = False
            result["telegram"]["errors"] = [str(e)]
    else:
        result["telegram"]["reason"] = "Telegram integration not enabled"

    return result


# ---------- Real Diagnostic Tools ----------
@router.post("/admin/diagnostics/run")
async def diagnostics_run(payload: dict, admin=Depends(get_current_admin)):
    from portal import diagnostics as _diag
    tool = (payload.get("tool") or "").strip().lower()
    target = (payload.get("target") or "").strip()
    extras: dict = {}
    for key in ("count", "max_hops", "record",
                "interface", "src_address", "dst_address",
                "protocol", "port", "duration", "ip_version"):
        if key in payload and payload[key] not in (None, ""):
            extras[key] = payload[key]
    db = await _get_db()
    try:
        result = await _diag.dispatch(tool, target, db=db, **extras)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Diagnostic failed: {type(e).__name__}: {e}")
    return result


@router.get("/admin/diagnostics/tools")
async def diagnostics_tools_list(admin=Depends(get_current_admin)):
    """Advertise which tools are available on this host so the UI can grey out
    any missing binaries (e.g. traceroute) without a round-trip."""
    from portal import diagnostics as _diag
    from portal import integrations_v2 as _iv2
    db = await _get_db()
    mikrotik_settings = await _iv2.get_settings(db, "mikrotik")
    mikrotik_ready = bool(mikrotik_settings and mikrotik_settings.get("enabled"))
    tools_meta = {
        "ping":       {"label": "Ping",       "requires": "ping3 (python)",       "extras": ["count"]},
        "traceroute": {"label": "Traceroute", "requires": "traceroute",           "extras": ["max_hops"]},
        "dns":        {"label": "DNS Lookup", "requires": "dig",                  "extras": ["record"]},
        "whois":      {"label": "WHOIS",      "requires": "whois",                "extras": []},
        "blacklist":  {"label": "DNSBL",      "requires": "dns",                  "extras": []},
        "portscan":   {"label": "Port Scan",  "requires": "tcp sockets",          "extras": []},
        "http":       {"label": "HTTP Check", "requires": "httpx",                "extras": []},
        "torch":      {"label": "MikroTik Torch",
                       "requires": f"mikrotik integration ({'ready' if mikrotik_ready else 'not configured'})",
                       "available": mikrotik_ready,
                       "extras": ["interface", "src_address", "dst_address", "protocol", "port", "duration"]},
    }
    return {"tools": list(_diag.TOOLS.keys()), "meta": tools_meta,
            "mikrotik_ready": mikrotik_ready}


# ============================================================
# FINANCE V2 — Kas Kecil / Salaries / Sales Fees / Excel reports
# ============================================================
from fastapi.responses import StreamingResponse  # noqa: E402
import io as _io  # noqa: E402


def _generic_ledger_serialize(d: dict) -> dict:
    return {
        "id": str(d["_id"]),
        "date": d.get("date", ""),
        "amount": float(d.get("amount") or 0),
        "category": d.get("category", ""),
        "notes": d.get("notes", ""),
        "vendor": d.get("vendor", ""),
        "employee": d.get("employee", ""),
        "sales_person": d.get("sales_person", ""),
        "invoice_number": d.get("invoice_number", ""),
        "period_yyyy_mm": d.get("period_yyyy_mm") or (d.get("date", "")[:7]),
        "created_at": _iso(d.get("created_at", "")),
    }


def _month_locked(period_yyyy_mm: str) -> bool:
    """A month is 'locked' once its data is frozen for reporting.

    Rule: a month M/Y is locked as soon as we're in month M+1/Y or later.
    Additionally, once the calendar year Y completes, ALL months of Y stay
    locked until January 5th of Y+1 (audit window). Only strictly future
    months are always mutable.
    """
    today = datetime.now(timezone.utc).date()
    try:
        y, m = int(period_yyyy_mm[:4]), int(period_yyyy_mm[5:7])
    except Exception:
        return False
    # Future months → not locked
    if (y, m) > (today.year, today.month):
        return False
    # Prior calendar year: locked until Jan 5 of Y+1
    if y < today.year:
        if today.year == y + 1 and today.month == 1 and today.day <= 5:
            return False   # 5-day amendment window
        return True
    # Same year, prior month: locked
    if y == today.year and m < today.month:
        return True
    return False


def _mk_ledger_router(*, collection: str, label: str, extra_fields: list):
    """Factory that creates a set of endpoints for a simple ledger table.

    Each ledger has: date (YYYY-MM-DD), amount, notes, plus `extra_fields`.
    We register 3 endpoints per ledger: list / create / delete.
    """

    async def _list(admin=Depends(get_current_admin)):
        db = await _get_db()
        docs = await db[collection].find({}).sort("date", -1).to_list(5000)
        return [_generic_ledger_serialize(d) for d in docs]

    async def _create(payload: dict, admin=Depends(get_current_admin)):
        db = await _get_db()
        date_str = payload.get("date") or datetime.now(timezone.utc).date().isoformat()
        period = date_str[:7]
        if _month_locked(period):
            raise HTTPException(status_code=403, detail=f"Cannot add {label} for locked month {period}. Contact finance to unlock.")
        doc = {"date": date_str, "amount": float(payload.get("amount", 0) or 0),
               "notes": payload.get("notes", ""), "period_yyyy_mm": period,
               "created_at": _now()}
        for k in extra_fields:
            doc[k] = payload.get(k, "")
        r = await db[collection].insert_one(doc)
        doc["_id"] = r.inserted_id
        return _generic_ledger_serialize(doc)

    async def _delete(item_id: str, admin=Depends(get_current_admin)):
        db = await _get_db()
        d = await db[collection].find_one({"_id": _oid(item_id)})
        if not d:
            raise HTTPException(status_code=404, detail="Not found")
        if _month_locked(d.get("period_yyyy_mm") or d.get("date", "")[:7]):
            raise HTTPException(status_code=403, detail=f"Cannot delete {label} from a locked month")
        r = await db[collection].delete_one({"_id": _oid(item_id)})
        return {"deleted": r.deleted_count}

    return _list, _create, _delete


# --- kas kecil (petty cash) ---
_kk_list, _kk_create, _kk_delete = _mk_ledger_router(
    collection="kas_kecil", label="petty cash", extra_fields=["category", "vendor"],
)
router.get("/admin/kas-kecil")(_kk_list)
router.post("/admin/kas-kecil")(_kk_create)
router.delete("/admin/kas-kecil/{item_id}")(_kk_delete)

# --- salaries ---
_sal_list, _sal_create, _sal_delete = _mk_ledger_router(
    collection="salaries", label="salary", extra_fields=["employee", "category"],
)
router.get("/admin/salaries")(_sal_list)
router.post("/admin/salaries")(_sal_create)
router.delete("/admin/salaries/{item_id}")(_sal_delete)

# --- sales fees ---
_sf_list, _sf_create, _sf_delete = _mk_ledger_router(
    collection="sales_fees", label="sales fee", extra_fields=["sales_person", "invoice_number"],
)
router.get("/admin/sales-fees")(_sf_list)
router.post("/admin/sales-fees")(_sf_create)
router.delete("/admin/sales-fees/{item_id}")(_sf_delete)


# ---------------- Finance detailed report ----------------
@router.get("/admin/finance/detailed")
async def finance_detailed(admin=Depends(get_current_admin)):
    """Returns paid-invoice detail + all four expense ledgers + assets + depreciation.

    The frontend Finance page uses this to render tabbed detailed tables.
    """
    db = await _get_db()
    paid = await db.invoices.find({"status": "paid"}).sort("paid_at", -1).to_list(5000)
    revenue_rows = [{
        "id": str(inv["_id"]),
        "number": inv.get("number", ""),
        "paid_at": inv.get("paid_at", "")[:10],
        "customer": inv.get("customer_name") or "",
        "total": float(inv.get("total") or 0),
        "period_yyyy_mm": (inv.get("paid_at") or inv.get("created_at", ""))[:7],
    } for inv in paid]

    async def _fetch(coll):
        docs = await db[coll].find({}).sort("date", -1).to_list(5000)
        return [_generic_ledger_serialize(d) for d in docs]

    expenses_rows = []
    async for d in db.expenses.find({}).sort("date", -1):
        expenses_rows.append({
            "id": str(d["_id"]),
            "date": d.get("date", ""),
            "category": d.get("category", ""),
            "vendor": d.get("vendor", ""),
            "amount": float(d.get("amount", 0)),
            "description": d.get("description", ""),
            "period_yyyy_mm": (d.get("date") or "")[:7],
        })
    kk_rows = await _fetch("kas_kecil")
    sal_rows = await _fetch("salaries")
    sf_rows = await _fetch("sales_fees")

    assets_rows = []
    async for a in db.assets.find({}):
        dep = _asset_depreciation(a)
        assets_rows.append({
            "id": str(a["_id"]),
            "name": a.get("name", ""),
            "category": a.get("category", ""),
            "purchase_date": a.get("purchase_date", ""),
            "value": float(a.get("value", 0)),
            "salvage_value": float(a.get("salvage_value", 0) or 0),
            "useful_life_years": dep["life_years"],
            "useful_life_months": int(a.get("useful_life_months", 0) or 0),
            "annual_depreciation": dep["annual_depreciation"],
            "monthly_depreciation": dep["monthly_depreciation"],
            "book_value": dep["book_value"],
            "accumulated_depreciation": dep["accumulated_depreciation"],
        })

    total_revenue = sum(r["total"] for r in revenue_rows)
    total_expenses = sum(e["amount"] for e in expenses_rows)
    total_kas_kecil = sum(r["amount"] for r in kk_rows)
    total_salaries = sum(r["amount"] for r in sal_rows)
    total_sales_fees = sum(r["amount"] for r in sf_rows)
    total_all_expenses = total_expenses + total_kas_kecil + total_salaries + total_sales_fees
    total_depreciation = sum(a["accumulated_depreciation"] for a in assets_rows)
    return {
        "revenue_rows": revenue_rows,
        "expenses_rows": expenses_rows,
        "kas_kecil_rows": kk_rows,
        "salaries_rows": sal_rows,
        "sales_fees_rows": sf_rows,
        "assets_rows": assets_rows,
        "totals": {
            "revenue": total_revenue,
            "expenses_recurring": total_expenses,
            "kas_kecil": total_kas_kecil,
            "salaries": total_salaries,
            "sales_fees": total_sales_fees,
            "expenses_all": total_all_expenses,
            "depreciation_accumulated": total_depreciation,
            "net_profit": total_revenue - total_all_expenses - total_depreciation,
        },
    }


# ---------------- Excel report generation ----------------
def _idr_fmt(v):
    return f"Rp {float(v or 0):,.0f}".replace(",", ".")


def _write_xlsx(sheets: list) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment
    wb = Workbook()
    wb.remove(wb.active)
    header_font = Font(bold=True, color="FFFFFFFF")
    header_fill = PatternFill("solid", fgColor="FF0A2350")
    total_font = Font(bold=True)
    total_fill = PatternFill("solid", fgColor="FFFEF3C7")
    for name, rows in sheets:
        ws = wb.create_sheet(title=name[:31])
        for r_idx, row in enumerate(rows, start=1):
            for c_idx, cell in enumerate(row, start=1):
                c = ws.cell(row=r_idx, column=c_idx, value=cell)
                if r_idx == 1:
                    c.font = header_font
                    c.fill = header_fill
                    c.alignment = Alignment(horizontal="center")
                elif r_idx == len(rows) and str(row[0]).lower().startswith(("total", "net ")):
                    c.font = total_font
                    c.fill = total_fill
        # auto-width
        for col in ws.columns:
            length = max((len(str(c.value)) for c in col if c.value is not None), default=8)
            ws.column_dimensions[col[0].column_letter].width = min(length + 2, 40)
    buf = _io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf.read()


async def _gather_period_data(db, *, year: int, month: Optional[int] = None) -> dict:
    def in_period(dt: str) -> bool:
        if not dt or len(dt) < 7:
            return False
        y = int(dt[:4])
        if y != year:
            return False
        if month is not None:
            return int(dt[5:7]) == month
        return True

    paid = await db.invoices.find({"status": "paid"}).to_list(10000)
    revenue = [i for i in paid if in_period(i.get("paid_at") or i.get("created_at", ""))]
    expenses = [e for e in await db.expenses.find({}).to_list(10000)
                if in_period(e.get("date", ""))]
    kk = [e for e in await db.kas_kecil.find({}).to_list(10000) if in_period(e.get("date", ""))]
    sal = [e for e in await db.salaries.find({}).to_list(10000) if in_period(e.get("date", ""))]
    sf = [e for e in await db.sales_fees.find({}).to_list(10000) if in_period(e.get("date", ""))]
    assets = await db.assets.find({}).to_list(10000)
    return {"revenue": revenue, "expenses": expenses, "kk": kk, "sal": sal, "sf": sf, "assets": assets}


@router.get("/admin/finance/report/monthly/{period}")
async def finance_monthly_xlsx(period: str, admin=Depends(get_current_admin)):
    """`period` is YYYY-MM. Returns an .xlsx with 6 sheets:
    Summary / Revenue / Expenses / Kas Kecil / Salaries / Sales Fees.
    Also freezes the month into `finalized_reports` so it becomes read-only.
    """
    try:
        y, m = int(period[:4]), int(period[5:7])
    except Exception:
        raise HTTPException(status_code=400, detail="Bad period, use YYYY-MM")
    db = await _get_db()
    d = await _gather_period_data(db, year=y, month=m)
    rev_total = sum(float(i.get("total") or 0) for i in d["revenue"])
    exp_total = sum(float(e.get("amount") or 0) for e in d["expenses"])
    kk_total = sum(float(e.get("amount") or 0) for e in d["kk"])
    sal_total = sum(float(e.get("amount") or 0) for e in d["sal"])
    sf_total = sum(float(e.get("amount") or 0) for e in d["sf"])
    all_exp = exp_total + kk_total + sal_total + sf_total
    net_profit = rev_total - all_exp
    summary = [
        ["Line", "Amount (IDR)"],
        ["Revenue (paid invoices)", _idr_fmt(rev_total)],
        ["Expenses (recurring)", _idr_fmt(exp_total)],
        ["Kas Kecil (petty cash)", _idr_fmt(kk_total)],
        ["Salaries", _idr_fmt(sal_total)],
        ["Sales Fees", _idr_fmt(sf_total)],
        ["Total expenses", _idr_fmt(all_exp)],
        ["Net profit (before depreciation)", _idr_fmt(net_profit)],
    ]
    rev_rows = [["Paid at", "Invoice #", "Customer", "Amount"]] + [
        [i.get("paid_at", "")[:10], i.get("number", ""), i.get("customer_name") or "",
         _idr_fmt(i.get("total"))] for i in d["revenue"]
    ] + [["TOTAL", "", "", _idr_fmt(rev_total)]]
    exp_rows = [["Date", "Category", "Vendor", "Description", "Amount"]] + [
        [e.get("date", ""), e.get("category", ""), e.get("vendor", ""),
         e.get("description", ""), _idr_fmt(e.get("amount"))] for e in d["expenses"]
    ] + [["TOTAL", "", "", "", _idr_fmt(exp_total)]]
    kk_rows = [["Date", "Category", "Vendor", "Notes", "Amount"]] + [
        [e.get("date", ""), e.get("category", ""), e.get("vendor", ""),
         e.get("notes", ""), _idr_fmt(e.get("amount"))] for e in d["kk"]
    ] + [["TOTAL", "", "", "", _idr_fmt(kk_total)]]
    sal_rows = [["Date", "Employee", "Category", "Notes", "Amount"]] + [
        [e.get("date", ""), e.get("employee", ""), e.get("category", ""),
         e.get("notes", ""), _idr_fmt(e.get("amount"))] for e in d["sal"]
    ] + [["TOTAL", "", "", "", _idr_fmt(sal_total)]]
    sf_rows = [["Date", "Sales person", "Invoice #", "Notes", "Amount"]] + [
        [e.get("date", ""), e.get("sales_person", ""), e.get("invoice_number", ""),
         e.get("notes", ""), _idr_fmt(e.get("amount"))] for e in d["sf"]
    ] + [["TOTAL", "", "", "", _idr_fmt(sf_total)]]

    xlsx = _write_xlsx([
        (f"Summary {period}", summary),
        ("Revenue", rev_rows),
        ("Expenses", exp_rows),
        ("Kas Kecil", kk_rows),
        ("Salaries", sal_rows),
        ("Sales Fees", sf_rows),
    ])

    # Freeze: save into finalized_reports for the month (idempotent)
    await db.finalized_reports.update_one(
        {"period": period, "kind": "monthly"},
        {"$set": {"period": period, "kind": "monthly", "totals": {
            "revenue": rev_total, "expenses_all": all_exp, "net_profit": net_profit,
        }, "generated_at": _now()}},
        upsert=True,
    )
    filename = f"Intercloud_Finance_{period}.xlsx"
    return StreamingResponse(
        _io.BytesIO(xlsx),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/admin/finance/report/annual/{year}")
async def finance_annual_xlsx(year: int, admin=Depends(get_current_admin)):
    """One workbook with per-month AND cumulative Jan-Dec P&L + assets."""
    db = await _get_db()
    d = await _gather_period_data(db, year=year)

    # Per-month buckets
    months = [f"{year}-{m:02d}" for m in range(1, 13)]
    buckets = {mm: {"rev": 0.0, "exp": 0.0, "kk": 0.0, "sal": 0.0, "sf": 0.0} for mm in months}
    for i in d["revenue"]:
        k = (i.get("paid_at") or i.get("created_at", ""))[:7]
        if k in buckets: buckets[k]["rev"] += float(i.get("total") or 0)
    for e in d["expenses"]:
        k = e.get("date", "")[:7]
        if k in buckets: buckets[k]["exp"] += float(e.get("amount") or 0)
    for e in d["kk"]:
        k = e.get("date", "")[:7]
        if k in buckets: buckets[k]["kk"] += float(e.get("amount") or 0)
    for e in d["sal"]:
        k = e.get("date", "")[:7]
        if k in buckets: buckets[k]["sal"] += float(e.get("amount") or 0)
    for e in d["sf"]:
        k = e.get("date", "")[:7]
        if k in buckets: buckets[k]["sf"] += float(e.get("amount") or 0)

    # Monthly + cumulative sheet
    monthly_rows = [["Month", "Revenue", "Recurring exp.", "Kas Kecil", "Salaries",
                     "Sales Fees", "Total expenses", "Net profit",
                     "Cumulative revenue", "Cumulative net"]]
    cum_rev = cum_net = 0.0
    for mm in months:
        b = buckets[mm]
        exps = b["exp"] + b["kk"] + b["sal"] + b["sf"]
        net = b["rev"] - exps
        cum_rev += b["rev"]; cum_net += net
        monthly_rows.append([mm, _idr_fmt(b["rev"]), _idr_fmt(b["exp"]), _idr_fmt(b["kk"]),
                             _idr_fmt(b["sal"]), _idr_fmt(b["sf"]), _idr_fmt(exps),
                             _idr_fmt(net), _idr_fmt(cum_rev), _idr_fmt(cum_net)])
    total_rev = sum(b["rev"] for b in buckets.values())
    total_exp_all = sum(b["exp"] + b["kk"] + b["sal"] + b["sf"] for b in buckets.values())
    monthly_rows.append(["TOTAL", _idr_fmt(total_rev), "", "", "", "",
                         _idr_fmt(total_exp_all), _idr_fmt(total_rev - total_exp_all),
                         _idr_fmt(total_rev), _idr_fmt(total_rev - total_exp_all)])

    # Assets sheet (straight-line depreciation)
    asset_rows = [["Asset", "Category", "Purchased", "Cost", "Salvage",
                   "Useful life (yr)", "Annual depreciation",
                   "Book value", "Accumulated depreciation"]]
    total_cost = total_book = 0.0
    for a in d["assets"]:
        dep = _asset_depreciation(a)
        cost = float(a.get("value", 0)); book = dep["book_value"]
        total_cost += cost; total_book += book
        asset_rows.append([a.get("name", ""), a.get("category", ""),
                           a.get("purchase_date", ""), _idr_fmt(cost),
                           _idr_fmt(float(a.get("salvage_value", 0) or 0)),
                           dep["life_years"],
                           _idr_fmt(dep["annual_depreciation"]),
                           _idr_fmt(book),
                           _idr_fmt(dep["accumulated_depreciation"])])
    asset_rows.append(["TOTAL", "", "", _idr_fmt(total_cost), "", "", "",
                       _idr_fmt(total_book), _idr_fmt(total_cost - total_book)])

    # Details
    rev_rows = [["Paid at", "Invoice #", "Customer", "Amount"]] + [
        [i.get("paid_at", "")[:10], i.get("number", ""), i.get("customer_name") or "",
         _idr_fmt(i.get("total"))] for i in d["revenue"]] + [["TOTAL", "", "", _idr_fmt(total_rev)]]

    xlsx = _write_xlsx([
        (f"P&L {year}", monthly_rows),
        (f"Assets {year}", asset_rows),
        (f"Revenue {year}", rev_rows),
    ])

    await db.finalized_reports.update_one(
        {"period": str(year), "kind": "annual"},
        {"$set": {"period": str(year), "kind": "annual",
                  "totals": {"revenue": total_rev, "expenses_all": total_exp_all,
                             "net_profit": total_rev - total_exp_all},
                  "generated_at": _now()}},
        upsert=True,
    )
    return StreamingResponse(
        _io.BytesIO(xlsx),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="Intercloud_Finance_Annual_{year}.xlsx"'},
    )


@router.get("/admin/finance/reports")
async def finance_finalized_reports(admin=Depends(get_current_admin)):
    """List all previously-generated monthly/annual reports (audit trail)."""
    db = await _get_db()
    docs = await db.finalized_reports.find({}).sort("period", -1).to_list(500)
    return [{
        "id": str(r["_id"]), "period": r["period"], "kind": r["kind"],
        "totals": r.get("totals", {}), "generated_at": _iso(r.get("generated_at", "")),
        "locked": _month_locked(r["period"]) if r["kind"] == "monthly" else True,
    } for r in docs]


# ============================================================
# Email Automation — templates, preview, logs, blasts
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
                            detail="System templates cannot be deleted — pause them via is_active=false instead")
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
                        "window": "Sabtu, 15 Feb 2026, 02:00–04:00 WIB",
                        "impact": "Kemungkinan latensi meningkat 5–10 menit."},
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
    """One-off broadcast — newsletter / maintenance / arbitrary."""
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
            {"key": "invoice_reminder_d3", "label": "Payment reminder — D-3", "trigger": "scheduled",
             "offset_days": -3},
            {"key": "invoice_due", "label": "Payment due today", "trigger": "scheduled", "offset_days": 0},
            {"key": "invoice_overdue_d1", "label": "Overdue — D+1", "trigger": "scheduled", "offset_days": 1},
            {"key": "invoice_overdue_d3", "label": "Overdue — D+3", "trigger": "scheduled", "offset_days": 3},
            {"key": "invoice_overdue_d7", "label": "Overdue — D+7 (final)", "trigger": "scheduled", "offset_days": 7},
            {"key": "service_suspension", "label": "Service suspension — D+8",
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


# ============================================================
# Articles / CMS — admin editor + public listing + search
# ============================================================
import re as _re_slug  # noqa: E402


def _slugify(text: str) -> str:
    s = (text or "").lower().strip()
    s = _re_slug.sub(r"[^a-z0-9]+", "-", s)
    s = _re_slug.sub(r"-+", "-", s).strip("-")
    return s[:80] or "article"


def _norm_tags(tags):
    out = []
    seen = set()
    for t in tags or []:
        s = _slugify(str(t))
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    return out


def _serialize_article(d: dict, *, include_body: bool = True) -> dict:
    out = {
        "id": str(d["_id"]),
        "title": d.get("title", ""),
        "slug": d.get("slug", ""),
        "excerpt": d.get("excerpt", ""),
        "cover_image_url": d.get("cover_image_url", ""),
        "video_url": d.get("video_url", ""),
        "author_name": d.get("author_name", ""),
        "tags": d.get("tags", []),
        "category": d.get("category", ""),
        "status": d.get("status", "draft"),
        "published_at": d.get("published_at"),
        "meta_title": d.get("meta_title", ""),
        "meta_description": d.get("meta_description", ""),
        "meta_keywords": d.get("meta_keywords", []),
        "og_image_url": d.get("og_image_url", ""),
        "is_featured": bool(d.get("is_featured", False)),
        "view_count": int(d.get("view_count", 0)),
        "created_at": _iso(d.get("created_at", "")),
        "updated_at": _iso(d.get("updated_at", "")),
    }
    if include_body:
        out["body_html"] = d.get("body_html", "")
    return out


async def _ensure_article_indexes(db):
    try:
        await db.articles.create_index("slug", unique=True)
    except Exception:
        pass
    try:
        # Text index for search (title, excerpt, body, tags)
        await db.articles.create_index([
            ("title", "text"), ("excerpt", "text"),
            ("body_html", "text"), ("tags", "text"),
        ], default_language="english", name="articles_text_idx")
    except Exception:
        pass


async def _unique_slug(db, base: str, ignore_id: Optional[str] = None) -> str:
    slug = _slugify(base)
    i = 1
    candidate = slug
    while True:
        q = {"slug": candidate}
        if ignore_id:
            q["_id"] = {"$ne": _oid(ignore_id)}
        exists = await db.articles.find_one(q)
        if not exists:
            return candidate
        i += 1
        candidate = f"{slug}-{i}"


# ---- Admin CRUD ----
@router.get("/admin/articles")
async def admin_articles_list(status: str = "", q: str = "", tag: str = "",
                              staff=Depends(get_current_staff)):
    db = await _get_db()
    await _ensure_article_indexes(db)
    filt: dict = {}
    if status in ("draft", "published", "archived"):
        filt["status"] = status
    if tag:
        filt["tags"] = _slugify(tag)
    if q:
        filt["$text"] = {"$search": q}
    docs = await db.articles.find(filt).sort("updated_at", -1).to_list(500)
    return [_serialize_article(d, include_body=False) for d in docs]


@router.get("/admin/articles/{aid}")
async def admin_article_get(aid: str, staff=Depends(get_current_staff)):
    db = await _get_db()
    d = await db.articles.find_one({"_id": _oid(aid)})
    if not d:
        raise HTTPException(status_code=404, detail="Article not found")
    return _serialize_article(d)


@router.post("/admin/articles")
async def admin_article_create(payload: m.ArticleIn, admin=Depends(get_current_admin)):
    db = await _get_db()
    await _ensure_article_indexes(db)
    now = _now()
    slug_base = payload.slug or payload.title
    slug = await _unique_slug(db, slug_base)
    doc = payload.model_dump()
    doc.update({
        "slug": slug,
        "tags": _norm_tags(payload.tags),
        "meta_keywords": _norm_tags(payload.meta_keywords),
        "author_name": payload.author_name or admin["name"],
        "created_at": now,
        "updated_at": now,
        "view_count": 0,
    })
    if payload.status == "published" and not payload.published_at:
        doc["published_at"] = now
    r = await db.articles.insert_one(doc)
    doc["_id"] = r.inserted_id
    return _serialize_article(doc)


@router.put("/admin/articles/{aid}")
async def admin_article_update(aid: str, payload: m.ArticleIn,
                               admin=Depends(get_current_admin)):
    db = await _get_db()
    existing = await db.articles.find_one({"_id": _oid(aid)})
    if not existing:
        raise HTTPException(status_code=404, detail="Article not found")
    upd = payload.model_dump()
    upd["tags"] = _norm_tags(payload.tags)
    upd["meta_keywords"] = _norm_tags(payload.meta_keywords)
    upd["updated_at"] = _now()
    # slug: only regenerate if changed or blank
    incoming_slug = payload.slug or payload.title
    if _slugify(incoming_slug) != existing.get("slug"):
        upd["slug"] = await _unique_slug(db, incoming_slug, ignore_id=aid)
    else:
        upd["slug"] = existing["slug"]
    # First-publish → stamp published_at
    if payload.status == "published" and not existing.get("published_at") and not payload.published_at:
        upd["published_at"] = _now()
    await db.articles.update_one({"_id": _oid(aid)}, {"$set": upd})
    d2 = await db.articles.find_one({"_id": _oid(aid)})
    return _serialize_article(d2)


@router.delete("/admin/articles/{aid}")
async def admin_article_delete(aid: str, admin=Depends(get_current_admin)):
    db = await _get_db()
    r = await db.articles.delete_one({"_id": _oid(aid)})
    return {"deleted": r.deleted_count}


@router.get("/admin/articles-tags")
async def admin_articles_tags(staff=Depends(get_current_staff)):
    """Return all tags used across articles with a count (for suggestions)."""
    db = await _get_db()
    pipeline = [
        {"$unwind": "$tags"},
        {"$group": {"_id": "$tags", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
    ]
    rows = await db.articles.aggregate(pipeline).to_list(500)
    return [{"tag": r["_id"], "count": r["count"]} for r in rows]


# ---- Public endpoints (unauthenticated) ----
@router.get("/public/articles")
async def public_articles_list(q: str = "", tag: str = "",
                               limit: int = 24, skip: int = 0):
    db = await _get_db()
    await _ensure_article_indexes(db)
    filt: dict = {"status": "published"}
    if tag:
        filt["tags"] = _slugify(tag)
    projection = None
    sort = [("published_at", -1)]
    if q:
        filt["$text"] = {"$search": q}
        projection = {"score": {"$meta": "textScore"}}
        sort = [("score", {"$meta": "textScore"}), ("published_at", -1)]
    cursor = db.articles.find(filt, projection).sort(sort).skip(max(0, skip)).limit(max(1, min(limit, 100)))
    docs = await cursor.to_list(200)
    total = await db.articles.count_documents(filt)
    return {
        "total": total,
        "count": len(docs),
        "results": [_serialize_article(d, include_body=False) for d in docs],
    }


@router.get("/public/articles/tags")
async def public_articles_tags():
    """Return every tag that appears on at least one published article."""
    db = await _get_db()
    pipeline = [
        {"$match": {"status": "published"}},
        {"$unwind": "$tags"},
        {"$group": {"_id": "$tags", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
    ]
    rows = await db.articles.aggregate(pipeline).to_list(500)
    return [{"tag": r["_id"], "count": r["count"]} for r in rows]


@router.get("/public/articles/{slug}")
async def public_article_detail(slug: str):
    db = await _get_db()
    d = await db.articles.find_one({"slug": slug, "status": "published"})
    if not d:
        raise HTTPException(status_code=404, detail="Article not found")
    # Track a view; ignore if it fails.
    try:
        await db.articles.update_one({"_id": d["_id"]}, {"$inc": {"view_count": 1}})
    except Exception:
        pass
    d["view_count"] = int(d.get("view_count", 0)) + 1
    # Sibling: 3 most recent published, excluding this one.
    related_cursor = db.articles.find(
        {"status": "published", "_id": {"$ne": d["_id"]},
         **({"tags": {"$in": d.get("tags", [])}} if d.get("tags") else {})},
    ).sort("published_at", -1).limit(3)
    related = [_serialize_article(x, include_body=False) for x in await related_cursor.to_list(3)]
    return {"article": _serialize_article(d), "related": related}
