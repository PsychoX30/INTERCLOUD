"""Staff/user management: users CRUD, access catalog, personal email settings, webmail.

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
from .auth import _upsert_crm_from_user  # noqa: E402
from .shared import _get_db, _iso, _load_user, _now, _oid, _serialize_service, _user_public  # noqa: E402

router = APIRouter()


# ============================================================
# Per-admin email settings (F1) - every staff member configures their
# own IMAP/SMTP so Admin ▸ Mail shows their personal inbox instead of
# a single shared mailbox. Stored on the user document under
# `email_settings` with the same shape the shared iv2 integration uses.
# ============================================================
def _mask_email_settings(es: dict) -> dict:
    """Return a copy with the password redacted for GET responses."""
    if not es:
        return {}
    def _redact(creds: dict) -> dict:
        c = dict(creds or {})
        if c.get("password"):
            c["password"] = "•" * 8
        return c
    imap_creds_legacy = _redact(es.get("credentials") or {})
    smtp_creds = _redact((es.get("smtp") or {}).get("credentials") or {})
    imap_creds = _redact((es.get("imap") or {}).get("credentials") or imap_creds_legacy)
    return {
        "smtp": {"credentials": smtp_creds,
                  "options": dict((es.get("smtp") or {}).get("options") or {})},
        "imap": {"credentials": imap_creds, "options": dict(es.get("options") or {})},
        "from_name": es.get("from_name") or "",
        "from_email": es.get("from_email") or (imap_creds.get("username") or ""),
        "configured": bool(imap_creds.get("host") and imap_creds.get("username")),
    }


@router.get("/settings/email")
async def get_my_email_settings(user=Depends(get_current_user)):
    """Return the calling staff member's IMAP/SMTP config (password masked)."""
    db = await _get_db()
    doc = await db.users.find_one({"_id": ObjectId(user["id"])})
    return _mask_email_settings((doc or {}).get("email_settings") or {})


def _merge_email_payload(existing: dict, payload: dict) -> dict:
    """Merge an incoming (possibly password-masked) email-settings payload with
    what's already stored on the user document. Shared by the save endpoint and
    the test-connection endpoint so both resolve masked "••••••••" passwords
    back to the stored value."""
    def _merge(kind: str) -> dict:
        old_creds = ((existing.get(kind) or {}).get("credentials") or
                     (existing.get("credentials") if kind == "imap" else {})) or {}
        new = (payload or {}).get(kind) or {}
        pwd = new.get("password") or ""
        if not pwd or set(pwd) == {"•"}:
            pwd = old_creds.get("password") or ""
        return {
            "credentials": {
                "host":     (new.get("host") or old_creds.get("host") or "").strip(),
                "port":     int(new.get("port") or old_creds.get("port") or (993 if kind == "imap" else 465)),
                "username": (new.get("username") or old_creds.get("username") or "").strip(),
                "password": pwd,
            },
            "options": {"use_ssl": bool(new.get("use_ssl", True))},
        }

    imap = _merge("imap")
    return {
        "from_name":  ((payload or {}).get("from_name") or "").strip(),
        "from_email": ((payload or {}).get("from_email") or "").strip(),
        "imap": imap,
        "smtp": _merge("smtp"),
        # Legacy top-level fields kept for backward compat with IMAPClient
        "credentials": imap["credentials"],
        "options":     imap["options"],
    }


@router.post("/settings/email")
async def save_my_email_settings(payload: dict, user=Depends(get_current_user)):
    """Save this staff member's personal cPanel IMAP/SMTP credentials.

    Expected shape:
      {
        "from_name": "Anang Support",
        "from_email": "anang@intercloud-digital.com",
        "imap": {"host":"...", "port":993, "username":"...", "password":"...", "use_ssl":true},
        "smtp": {"host":"...", "port":465, "username":"...", "password":"...", "use_ssl":true},
      }
    Passwords equal to "•••••••" are treated as "unchanged" so operators
    can edit host/port without re-entering their password.
    """
    db = await _get_db()
    doc = await db.users.find_one({"_id": ObjectId(user["id"])})
    existing = (doc or {}).get("email_settings") or {}
    stored = _merge_email_payload(existing, payload)
    await db.users.update_one(
        {"_id": ObjectId(user["id"])},
        {"$set": {"email_settings": stored}},
    )
    return _mask_email_settings(stored)


@router.post("/settings/email/test")
async def test_my_email_settings(payload: dict = None, user=Depends(get_current_user)):
    """Test IMAP **and** SMTP connectivity for this staff member's webmail.

    Accepts the same payload shape as POST /settings/email (so the setup modal
    can test what's currently typed before saving). Masked passwords fall back
    to the stored value; an empty/missing payload tests the saved settings.
    Returns per-protocol results:
      { "ok": bool, "imap": {"ok":…, "message":…}, "smtp": {"ok":…, "message":…} }
    """
    db = await _get_db()
    doc = await db.users.find_one({"_id": ObjectId(user["id"])})
    existing = (doc or {}).get("email_settings") or {}
    merged = _merge_email_payload(existing, payload or {})

    def _test(kind: str) -> dict:
        cfg = merged[kind]
        c = cfg["credentials"]
        if not (c.get("host") and c.get("username") and c.get("password")):
            return {"ok": False,
                    "message": f"{kind.upper()} belum dikonfigurasi (host/username/password wajib diisi)."}
        try:
            if kind == "imap":
                return iv2.IMAPClient(cfg).test_connection()
            return iv2.SMTPMailer(cfg).test_connection()
        except Exception as e:  # pragma: no cover - test_connection already catches
            return {"ok": False, "message": f"{type(e).__name__}: {e}"}

    imap_res = _test("imap")
    smtp_res = _test("smtp")
    return {"ok": bool(imap_res.get("ok") and smtp_res.get("ok")),
            "imap": imap_res, "smtp": smtp_res}


@router.delete("/settings/email")
async def clear_my_email_settings(user=Depends(get_current_user)):
    db = await _get_db()
    await db.users.update_one(
        {"_id": ObjectId(user["id"])},
        {"$unset": {"email_settings": ""}},
    )
    return {"ok": True}


# Menu catalog (used by the Admin User Access modal to render per-menu checkboxes).
# The frontend PortalLayout.jsx must import ADMIN_MENU_CATALOG matching these keys.
ADMIN_MENU_CATALOG = [
    {"key": "dashboard",       "label": "Dashboard",        "group": "Overview",       "default_roles": ["admin", "sales", "finance", "support", "ticket_only", "creative"]},
    {"key": "orders",          "label": "Orders",           "group": "Sales & Billing", "default_roles": ["admin", "sales", "finance"]},
    {"key": "invoices",        "label": "Invoices",         "group": "Sales & Billing", "default_roles": ["admin", "finance"]},
    {"key": "quotations",      "label": "Quotations",       "group": "Sales & Billing", "default_roles": ["admin", "sales", "finance"]},
    {"key": "finance",         "label": "Finance",          "group": "Sales & Billing", "default_roles": ["admin", "finance"]},
    {"key": "assets",          "label": "Assets",           "group": "Sales & Billing", "default_roles": ["admin", "finance"]},
    {"key": "products",        "label": "Products",         "group": "Catalog",        "default_roles": ["admin", "support"]},
    {"key": "addons",          "label": "Add-ons",          "group": "Catalog",        "default_roles": ["admin", "support"]},
    {"key": "categories",      "label": "Categories",       "group": "Catalog",        "default_roles": ["admin"]},
    {"key": "services",        "label": "Services",         "group": "Catalog",        "default_roles": ["admin", "finance", "support"]},
    {"key": "service_requests","label": "Termination Requests","group": "Catalog",     "default_roles": ["admin", "support", "sales"]},
    {"key": "users",           "label": "Users / Clients",  "group": "Support & CRM",  "default_roles": ["admin", "sales", "finance", "support"]},
    {"key": "tickets",         "label": "Tickets",          "group": "Support & CRM",  "default_roles": ["admin", "sales", "finance", "support", "ticket_only"]},
    {"key": "mail",            "label": "Webmail",          "group": "Support & CRM",  "default_roles": ["admin", "sales", "finance", "support"]},
    {"key": "email",           "label": "Email Automation", "group": "Support & CRM",  "default_roles": ["admin"]},
    {"key": "articles",        "label": "Articles",         "group": "Support & CRM",  "default_roles": ["admin", "sales", "finance", "support", "creative"]},
    {"key": "provisioning",    "label": "Provisioning",     "group": "Operations",     "default_roles": ["admin", "support"]},
    {"key": "mikrotik",        "label": "MikroTik Ops",     "group": "Operations",     "default_roles": ["admin", "support"]},
    {"key": "dcim",            "label": "DCIM & IPAM",      "group": "Operations",     "default_roles": ["admin", "support"]},
    {"key": "diagnostics",     "label": "Diagnostics",      "group": "Operations",     "default_roles": ["admin", "support"]},
    {"key": "crm",             "label": "Customer DB (CRM)","group": "Business",       "default_roles": ["admin", "sales", "finance", "support"]},
    {"key": "projects",        "label": "Project Tracker",  "group": "Business",       "default_roles": ["admin", "sales", "support"]},
    {"key": "content",         "label": "Content Planner",  "group": "Business",       "default_roles": ["admin", "sales", "finance", "support", "creative"]},
    {"key": "followups",       "label": "Follow-ups",       "group": "Business",       "default_roles": ["admin", "sales", "finance", "support"]},
    {"key": "documents",       "label": "Documents",        "group": "Business",       "default_roles": ["admin", "sales", "finance", "support"]},
    {"key": "integrations",    "label": "Integrations",     "group": "System",         "default_roles": ["admin"]},
    {"key": "security",        "label": "Security",         "group": "System",         "default_roles": ["admin"]},
    {"key": "audit_log",       "label": "Audit Log",        "group": "System",         "default_roles": ["admin"]},
    {"key": "noc",             "label": "NOC Monitor",      "group": "Operations",     "default_roles": ["admin", "support"]},
    {"key": "credit_notes",    "label": "Credit Notes",     "group": "Sales & Billing", "default_roles": ["admin", "finance"]},
    {"key": "owner_dashboard", "label": "Executive Overview","group": "Overview",       "default_roles": ["admin", "owner"]},
    {"key": "media_library",   "label": "Media Library",    "group": "Creative",       "default_roles": ["admin", "creative"]},
    {"key": "content_calendar","label": "Content Calendar", "group": "Creative",       "default_roles": ["admin", "creative"]},
    {"key": "utm_builder",     "label": "UTM Builder",      "group": "Creative",       "default_roles": ["admin", "creative", "sales"]},
    {"key": "branding",        "label": "Branding",         "group": "System",         "default_roles": ["admin"]},
    {"key": "site_content",    "label": "Landing CMS",      "group": "System",         "default_roles": ["admin"]},
    {"key": "backup",          "label": "Backup & Restore", "group": "System",         "default_roles": ["admin"]},
    {"key": "status_page",     "label": "Public Status Page", "group": "System",       "default_roles": ["admin"]},
    {"key": "form_builder",    "label": "Form Builder",     "group": "Creative",       "default_roles": ["admin", "creative", "sales"]},
]


FEATURE_FLAG_CATALOG = [
    # Delete / destructive
    {"key": "can_delete_invoices",   "label": "Can permanently delete invoices"},
    {"key": "can_delete_users",      "label": "Can delete user accounts"},
    {"key": "can_delete_tickets",    "label": "Can delete support tickets"},
    {"key": "can_run_factory_reset", "label": "Can trigger Factory Reset (DANGEROUS)"},
    # Financial
    {"key": "can_view_all_invoices", "label": "Can see ALL invoices (not just own clients)"},
    {"key": "can_edit_pricing",      "label": "Can edit product / add-on pricing"},
    {"key": "can_apply_discounts",   "label": "Can apply discounts on quotations"},
    {"key": "can_view_assets",       "label": "Can view Assets & depreciation reports"},
    {"key": "can_export_data",       "label": "Can export CRM / invoices to CSV"},
    # Technical / Ops
    {"key": "can_edit_dcim_devices", "label": "Can edit DCIM devices (racks / equipment)"},
    {"key": "can_edit_ip_prefixes",  "label": "Can allocate & edit IP prefixes"},
    {"key": "can_run_provisioning",  "label": "Can trigger auto-provisioning manually"},
    {"key": "can_control_mikrotik",  "label": "Can run live MikroTik ops (traffic-ctrl, blackhole)"},
    {"key": "can_run_diagnostics",   "label": "Can run diagnostics (ping / traceroute / BGP lookup)"},
    # System
    {"key": "can_manage_users",      "label": "Can create/edit staff users (assign roles)"},
    {"key": "can_manage_articles",   "label": "Can publish / edit knowledge-base articles"},
    {"key": "can_edit_branding",     "label": "Can update logo / colours / landing CMS"},
    {"key": "can_manage_integrations","label": "Can configure MikroTik / Telegram / SMTP integrations"},
    {"key": "can_run_backups",       "label": "Can trigger backups & restore snapshots"},
    # CRM / Sales
    {"key": "can_view_all_clients",  "label": "Can view ALL client accounts (not just assigned)"},
    {"key": "can_reassign_clients",  "label": "Can reassign clients to different sales staff"},
    {"key": "can_impersonate_client","label": "Can impersonate a client for support"},
    {"key": "can_view_email_automation", "label": "Can access Email Automation module"},
]


@router.get("/admin/user-access-catalog")
async def admin_user_access_catalog(admin=Depends(require_roles("admin", "sales", "finance", "support"))):
    """Returns everything the User Access UI needs to render checkboxes.

    - `menu_catalog`: list of menu keys with human labels & the default roles that
      have access to each menu (used to show the default vs. the override).
    - `feature_flags`: list of extra per-user feature toggles.
    """
    return {
        "menu_catalog": ADMIN_MENU_CATALOG,
        "feature_flags": FEATURE_FLAG_CATALOG,
    }


def _paginate(items: list, page: Optional[int], limit: int):
    """Server-side pagination opsional: tanpa `page` kembalikan list penuh (kompatibel lama)."""
    if page is None:
        return items
    limit = max(1, min(int(limit or 25), 200))
    page = max(1, int(page))
    total = len(items)
    start = (page - 1) * limit
    return {"items": items[start:start + limit], "total": total, "page": page,
            "limit": limit, "pages": max(1, (total + limit - 1) // limit)}


@router.get("/admin/users")
async def admin_list_users(staff=Depends(require_roles("admin", "sales", "finance", "support")),
                           page: Optional[int] = None, limit: int = 25):
    """Sales sees only their assigned clients; other staff see all."""
    db = await _get_db()
    if staff["role"] == "sales":
        ids = [ObjectId(x) for x in (staff.get("assigned_client_ids") or [])]
        docs = await db.users.find({"_id": {"$in": ids}}).to_list(500) if ids else []
    else:
        docs = await db.users.find({}).sort("created_at", -1).to_list(1000)
    return _paginate([_user_public(u) for u in docs], page, limit)


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
    # Mirror this new user into CRM (as "existing" client - admin-created)
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
async def admin_update_user(uid: str, payload: m.UserUpdateIn, request: Request, admin=Depends(get_current_admin)):
    db = await _get_db()
    existing = await _load_user(db, uid)
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
    password_changed = False
    if payload.password:
        upd["password_hash"] = hash_password(payload.password)
        password_changed = True
    if upd:
        await db.users.update_one({"_id": _oid(uid)}, {"$set": upd})
    u = await _load_user(db, uid)
    # ---- Audit: log role changes and password resets separately for clarity ----
    if existing.get("role") != u.get("role"):
        await log_audit(db, actor=admin, action="user.role_change", category="users",
                        target_type="user", target_id=uid, target_label=u.get("email", ""),
                        before={"role": existing.get("role")}, after={"role": u.get("role")},
                        severity="warning", request=request)
    if password_changed:
        await log_audit(db, actor=admin, action="user.password_change", category="security",
                        target_type="user", target_id=uid, target_label=u.get("email", ""),
                        severity="warning", request=request)
    if existing.get("is_active") != u.get("is_active"):
        await log_audit(db, actor=admin, action="user.active_toggle", category="users",
                        target_type="user", target_id=uid, target_label=u.get("email", ""),
                        before={"is_active": existing.get("is_active")},
                        after={"is_active": u.get("is_active")},
                        severity="warning", request=request)
    return _user_public(u)


@router.delete("/admin/users/{uid}")
async def admin_delete_user(uid: str, request: Request, admin=Depends(get_current_admin)):
    db = await _get_db()
    if str(admin["id"]) == uid:
        raise HTTPException(status_code=400, detail="You cannot delete yourself")
    target = await db.users.find_one({"_id": _oid(uid)})
    r = await db.users.delete_one({"_id": _oid(uid)})
    if r.deleted_count and target:
        await log_audit(db, actor=admin, action="user.delete", category="users",
                        target_type="user", target_id=uid,
                        target_label=target.get("email", ""),
                        before={"role": target.get("role"), "email": target.get("email")},
                        severity="critical", request=request)
    return {"deleted": r.deleted_count}


@router.post("/admin/users/{uid}/impersonate")
async def admin_impersonate_client(uid: str, request: Request, admin=Depends(get_current_admin)):
    """Login-as-client untuk troubleshooting. Hanya klien aktif, tercatat di audit log."""
    db = await _get_db()
    target = await db.users.find_one({"_id": _oid(uid)})
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    if target.get("role") != "client":
        raise HTTPException(status_code=400, detail="Hanya akun klien yang bisa diimpersonasi")
    if target.get("status") == "suspended":
        raise HTTPException(status_code=400, detail="Akun klien sedang disuspensi")
    token = create_access_token(str(target["_id"]), target["email"], "client")
    await log_audit(db, actor=admin, action="user.impersonate", category="security",
                    target_type="user", target_id=str(target["_id"]),
                    target_label=target.get("email", ""), severity="warning",
                    metadata={"admin_email": admin.get("email", "")}, request=request)
    return {"token": token,
            "user": {"id": str(target["_id"]), "name": target.get("name", ""),
                     "email": target.get("email", ""), "role": "client"}}


@router.get("/admin/users/{uid}/profile")
async def admin_user_profile(uid: str, admin=Depends(require_roles("admin", "sales", "finance", "support"))):
    """Client 360 profile: services (hosting accounts highlighted), billing summary."""
    db = await _get_db()
    u = await db.users.find_one({"_id": _oid(uid)})
    if not u:
        raise HTTPException(status_code=404, detail="User not found")
    svc_docs = await db.services.find({"user_id": u["_id"]}).sort("created_at", -1).to_list(200)
    services = [_serialize_service(s) for s in svc_docs]
    inv_docs = await db.invoices.find({"user_id": u["_id"]}).sort("created_at", -1).to_list(500)
    outstanding = sum(i.get("total", 0) for i in inv_docs if i.get("status") in ("unpaid", "overdue"))
    today = datetime.now(timezone.utc).date()
    overdue_list = []
    for i in inv_docs:
        if i.get("status") != "overdue":
            continue
        try:
            days = (today - datetime.strptime((i.get("due_date") or "")[:10], "%Y-%m-%d").date()).days
        except Exception:
            days = 0
        overdue_list.append({"id": str(i["_id"]), "number": i.get("number", ""),
                             "total": i.get("total", 0), "due_date": i.get("due_date", ""),
                             "days_past_due": max(0, days)})
    suspended_list = [{"id": str(s["_id"]), "name": s.get("name") or s.get("product_name", ""),
                       "reason": s.get("suspended_reason", ""), "suspended_at": s.get("suspended_at", "")}
                      for s in svc_docs if s.get("status") == "suspended"]
    max_days = max((o["days_past_due"] for o in overdue_list), default=0)
    if suspended_list:
        dunning_level = "suspended"
    elif max_days >= 7:
        dunning_level = "urgent"
    elif overdue_list:
        dunning_level = "reminder"
    else:
        dunning_level = "clear"
    return {
        "user": {"id": str(u["_id"]), "name": u.get("name", ""), "email": u.get("email", ""),
                 "company": u.get("company", ""), "phone": u.get("phone", ""),
                 "role": u.get("role", "client"), "created_at": _iso(u.get("created_at", ""))},
        "services": services,
        "hosting_accounts": [s for s in services if s.get("category") == "hosting"],
        "stats": {
            "orders": await db.orders.count_documents({"user_id": u["_id"]}),
            "tickets": await db.tickets.count_documents({"user_id": u["_id"]}),
            "invoices": len(inv_docs),
            "outstanding": round(outstanding, 2),
        },
        "recent_invoices": [{
            "id": str(i["_id"]), "number": i.get("number", ""), "total": i.get("total", 0),
            "status": i.get("status", "unpaid"), "due_date": i.get("due_date", ""),
        } for i in inv_docs[:5]],
        "dunning": {
            "level": dunning_level,
            "overdue_invoices": overdue_list,
            "max_days_past_due": max_days,
            "suspended_services": suspended_list,
        },
    }


# ============================================================
# WEBMAIL (staff-only) - SMTP for sending, IMAP for inbox.
# Currently backed by MongoDB (mock) so the UX works end-to-end.
# When an SMTP + IMAP integration is enabled under /admin/integrations,
# these endpoints can be swapped to real IMAP/SMTP calls.
# ============================================================

@router.get("/admin/mail/inbox")
async def admin_mail_inbox(staff=Depends(get_current_staff)):
    db = await _get_db()
    # ---- F1: Per-admin inbox - use the caller's OWN email_settings ----
    user_doc = await db.users.find_one({"_id": ObjectId(staff["id"])})
    my_settings = (user_doc or {}).get("email_settings") or {}
    my_imap = my_settings.get("imap") or {}
    if my_imap.get("credentials", {}).get("host") and my_imap.get("credentials", {}).get("username"):
        try:
            live = iv2.IMAPClient(my_imap).fetch_recent()
        except iv2.IMAPConnectionError as e:
            # Personal IMAP creds are set but the mailbox can't be reached -
            # tell the operator exactly why so they can fix it.
            return {"not_setup": True, "reason": "connection_failed",
                    "message": f"IMAP tidak bisa terhubung. {e}",
                    "detail": str(e)}
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

    # No personal creds → surface an actionable "click to setup" hint.
    # Frontend AdminMail.jsx renders a big card with a Configure button.
    return {"not_setup": True, "reason": "no_credentials",
            "message": "Email pribadi Anda belum di-setup. Klik untuk konfigurasi IMAP + SMTP cPanel Anda."}


@router.get("/admin/mail/messages/{mid}")
async def admin_mail_message(mid: str, staff=Depends(get_current_staff)):
    db = await _get_db()
    # ---- IMAP live message (id prefixed with "imap-") - uses caller's own creds ----
    if mid.startswith("imap-"):
        uid = mid[len("imap-"):]
        user_doc = await db.users.find_one({"_id": ObjectId(staff["id"])})
        my_imap = ((user_doc or {}).get("email_settings") or {}).get("imap") or {}
        if my_imap.get("credentials", {}).get("host"):
            try:
                for msg in iv2.IMAPClient(my_imap).fetch_recent():
                    if str(msg.get("id")) == uid:
                        return {
                            "id": mid,
                            "from_name": msg["from"].split("<")[0].strip(" \""),
                            "from_email": (msg["from"].split("<")[-1].rstrip(">") if "<" in msg["from"] else msg["from"]),
                            "subject": msg.get("subject", ""),
                            "body": msg.get("body") or msg.get("preview") or "",
                            "received_at": msg.get("date"),
                            "starred": False,
                        }
            except iv2.IMAPConnectionError as e:
                raise HTTPException(status_code=502, detail=f"IMAP tidak bisa terhubung: {e}")
        raise HTTPException(status_code=404, detail="IMAP message no longer available (mailbox may have been re-synced)")

    # ---- Mongo-backed message (legacy seeded demo - no per-user creds path) ----
    try:
        oid = _oid(mid)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid message id")
    d = await db.mail_inbox.find_one({"_id": oid})
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
    """Send outgoing email using the *caller's own* SMTP credentials.

    Every staff member configures their personal cPanel SMTP under
    Settings ▸ Email; the outbox uses those creds so replies come back to
    the same mailbox they read from. If no personal SMTP is configured,
    we hard-fail with 400 so the user is nudged to set it up.
    """
    db = await _get_db()
    to = payload.get("to", "")
    subject = payload.get("subject", "")
    body = payload.get("body", "")
    if not to or not subject:
        raise HTTPException(status_code=400, detail="to and subject are required")

    # ---- Load caller's personal SMTP settings ----
    user_doc = await db.users.find_one({"_id": ObjectId(staff["id"])})
    my_settings = (user_doc or {}).get("email_settings") or {}
    my_smtp = my_settings.get("smtp") or {}
    smtp_creds = my_smtp.get("credentials") or {}
    if not (smtp_creds.get("host") and smtp_creds.get("username") and smtp_creds.get("password")):
        raise HTTPException(
            status_code=400,
            detail="Silakan setup SMTP dulu di Settings ▸ Email sebelum mengirim.",
        )

    # Build a settings dict compatible with SMTPMailer, merging in the
    # caller's display name / from-address from the per-user config.
    smtp_settings = {
        "credentials": smtp_creds,
        "options": {
            **(my_smtp.get("options") or {}),
            "from_email": my_settings.get("from_email") or smtp_creds.get("username"),
            "from_name":  my_settings.get("from_name")  or staff.get("name") or "Intercloud",
        },
    }

    delivered = False
    delivered_via = "queued"
    from_email = smtp_settings["options"]["from_email"]
    from_name  = smtp_settings["options"]["from_name"]
    try:
        await asyncio.to_thread(iv2.SMTPMailer(smtp_settings).send,
                                to=to, subject=subject, html=body or "")
        delivered = True
        delivered_via = "smtp"
    except Exception as e:
        # Surface the underlying reason to the caller so the UI can show a
        # meaningful error instead of a silent "queued".
        raise HTTPException(
            status_code=502,
            detail=f"SMTP kirim gagal ({type(e).__name__}): {e}",
        )

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
