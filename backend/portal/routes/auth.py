"""Auth: login, 2FA, register, password lifecycle (change/forgot/reset).

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
from .shared import _get_db, _is_ip_blocked, _log_login_attempt, _now, _oid, _user_public  # noqa: E402
from portal.security import AUTH_FORGOT_LIMIT  # noqa: E402
from portal.security import AUTH_LOGIN_LIMIT  # noqa: E402
from portal.security import AUTH_REGISTER_LIMIT  # noqa: E402
from portal.security import AUTH_RESET_LIMIT  # noqa: E402
from portal.security import limiter as _rl_limiter  # noqa: E402

router = APIRouter()


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


@router.post("/auth/login", response_model=m.LoginOut)
@_rl_limiter.limit(AUTH_LOGIN_LIMIT)
async def login(payload: m.LoginIn, request: Request):
    db = await _get_db()
    from portal import integrations_v2 as _iv2
    from portal.security import _client_ip as _rl_client_ip
    ip = _rl_client_ip(request)
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
    if u.get("totp_enabled"):
        from portal import twofa as _tf
        await _log_login_attempt(db, email=email, action="login", success=True, reason="mfa_challenge",
                                 ip=ip, user_agent=ua, recaptcha_enabled=bool(recap_doc),
                                 recaptcha_score=recap_score)
        return {"require_2fa": True, "mfa_token": _tf.make_mfa_token(str(u["_id"]))}
    token = create_access_token(str(u["_id"]), u["email"], u["role"])
    await _log_login_attempt(db, email=email, action="login", success=True, reason="ok",
                             ip=ip, user_agent=ua, recaptcha_enabled=bool(recap_doc),
                             recaptcha_score=recap_score)
    return {"token": token, "user": _user_public(u)}


@router.post("/auth/login/2fa", response_model=m.LoginOut)
@_rl_limiter.limit(AUTH_LOGIN_LIMIT)
async def login_2fa(payload: dict, request: Request):
    """Langkah kedua login: verifikasi kode TOTP atau recovery code."""
    from portal import twofa as _tf
    from portal.security import _client_ip as _rl_client_ip
    db = await _get_db()
    ip = _rl_client_ip(request)
    ua = request.headers.get("user-agent", "")
    try:
        uid = _tf.decode_mfa_token(payload.get("mfa_token", ""))
    except Exception:
        raise HTTPException(status_code=401, detail="Sesi 2FA kedaluwarsa, silakan login ulang")
    u = await db.users.find_one({"_id": _oid(uid)})
    if not u or not u.get("totp_enabled"):
        raise HTTPException(status_code=400, detail="2FA tidak aktif untuk akun ini")
    code = str(payload.get("code", "")).strip()
    ok = _tf.verify_totp(_tf.decrypt_secret(u["totp_secret"]), code)
    if not ok:
        idx = _tf.check_recovery_code(code, u.get("recovery_codes") or [])
        if idx >= 0:
            rcs = u["recovery_codes"]
            rcs[idx]["used"] = True
            await db.users.update_one({"_id": u["_id"]}, {"$set": {"recovery_codes": rcs}})
            ok = True
    if not ok:
        await db.users.update_one({"_id": u["_id"]}, {"$inc": {"failed_2fa": 1}})
        await _log_login_attempt(db, email=u["email"], action="login_2fa", success=False,
                                 reason="invalid_2fa_code", ip=ip, user_agent=ua)
        raise HTTPException(status_code=401, detail="Kode 2FA tidak valid")
    await db.users.update_one({"_id": u["_id"]}, {"$set": {"failed_2fa": 0}})
    await _log_login_attempt(db, email=u["email"], action="login_2fa", success=True, reason="ok",
                             ip=ip, user_agent=ua)
    token = create_access_token(str(u["_id"]), u["email"], u["role"])
    return {"token": token, "user": _user_public(u)}


@router.get("/auth/2fa/status")
async def twofa_status(user=Depends(get_current_user)):
    db = await _get_db()
    u = await db.users.find_one({"_id": ObjectId(user["id"])})
    codes = u.get("recovery_codes") or []
    return {"enabled": bool(u.get("totp_enabled")),
            "recovery_codes_left": sum(1 for c in codes if not c.get("used"))}


@router.post("/auth/2fa/setup")
async def twofa_setup(user=Depends(get_current_user)):
    """Mulai aktivasi 2FA: buat secret pending + QR (belum aktif sampai diverifikasi)."""
    from portal import twofa as _tf
    db = await _get_db()
    secret = _tf.new_totp_secret()
    await db.users.update_one({"_id": ObjectId(user["id"])},
                              {"$set": {"pending_totp_secret": _tf.encrypt_secret(secret)}})
    uri = _tf.provisioning_uri(secret, user["email"])
    return {"otpauth_uri": uri, "qr": _tf.qr_data_url(uri), "secret": secret}


@router.post("/auth/2fa/verify-enable")
async def twofa_verify_enable(payload: dict, request: Request, user=Depends(get_current_user)):
    from portal import twofa as _tf
    db = await _get_db()
    u = await db.users.find_one({"_id": ObjectId(user["id"])})
    pend = u.get("pending_totp_secret")
    if not pend:
        raise HTTPException(status_code=400, detail="Belum ada setup 2FA yang berjalan")
    if not _tf.verify_totp(_tf.decrypt_secret(pend), payload.get("code", "")):
        raise HTTPException(status_code=400, detail="Kode tidak valid, coba lagi")
    plaintext, docs = _tf.new_recovery_codes(10)
    await db.users.update_one({"_id": u["_id"]}, {
        "$set": {"totp_secret": pend, "totp_enabled": True,
                 "recovery_codes": docs, "failed_2fa": 0},
        "$unset": {"pending_totp_secret": ""}})
    await log_audit(db, actor=user, action="user.2fa_enabled", category="security",
                    target_type="user", target_id=user["id"], target_label=user["email"],
                    request=request)
    return {"ok": True, "recovery_codes": plaintext}


@router.post("/auth/2fa/disable")
async def twofa_disable(payload: dict, request: Request, user=Depends(get_current_user)):
    from portal import twofa as _tf
    db = await _get_db()
    u = await db.users.find_one({"_id": ObjectId(user["id"])})
    if not u.get("totp_enabled"):
        raise HTTPException(status_code=400, detail="2FA belum aktif")
    code = str(payload.get("code", "")).strip()
    ok = _tf.verify_totp(_tf.decrypt_secret(u["totp_secret"]), code)
    if not ok and _tf.check_recovery_code(code, u.get("recovery_codes") or []) < 0:
        raise HTTPException(status_code=401, detail="Kode 2FA tidak valid")
    await db.users.update_one({"_id": u["_id"]}, {
        "$set": {"totp_enabled": False, "recovery_codes": [], "failed_2fa": 0},
        "$unset": {"totp_secret": "", "pending_totp_secret": ""}})
    await log_audit(db, actor=user, action="user.2fa_disabled", category="security",
                    target_type="user", target_id=user["id"], target_label=user["email"],
                    severity="warning", request=request)
    return {"ok": True}


@router.post("/admin/users/{uid}/reset-2fa")
async def admin_reset_2fa(uid: str, request: Request, admin=Depends(get_current_admin)):
    """Admin mereset 2FA staf yang kehilangan authenticator."""
    db = await _get_db()
    target = await db.users.find_one({"_id": _oid(uid)})
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    await db.users.update_one({"_id": target["_id"]}, {
        "$set": {"totp_enabled": False, "recovery_codes": [], "failed_2fa": 0},
        "$unset": {"totp_secret": "", "pending_totp_secret": ""}})
    await log_audit(db, actor=admin, action="user.2fa_reset_by_admin", category="security",
                    target_type="user", target_id=str(target["_id"]),
                    target_label=target.get("email", ""), severity="warning", request=request)
    return {"ok": True, "message": f"2FA direset untuk {target.get('email','')}"}


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
        "attention": u.get("attention", ""),
        "address_line1": u.get("address_line1", ""),
        "address_line2": u.get("address_line2", ""),
        "city": u.get("city", ""),
        "province": u.get("province", ""),
        "postal_code": u.get("postal_code", ""),
        "country": u.get("country", ""),
        "npwp": u.get("npwp", ""),
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
@_rl_limiter.limit(AUTH_REGISTER_LIMIT)
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

    # Fire welcome email (best-effort - never blocks registration)
    try:
        from portal import emails as _em
        await _em.on_user_registered(db, doc)
    except Exception:
        pass

    token = create_access_token(str(doc["_id"]), doc["email"], doc["role"])
    return {"token": token, "user": _user_public(doc)}


@router.get("/auth/me", response_model=m.UserOut)
async def me(user=Depends(get_current_user)):
    # Route through _user_public so legacy/directly-inserted user docs that
    # lack created_at (or store it as a datetime) don't trip the UserOut
    # response validator with a 500. _user_public defaults + coerces to ISO.
    return _user_public(user)


@router.put("/auth/me", response_model=m.UserOut)
async def update_me(payload: m.UserUpdateIn, user=Depends(get_current_user)):
    """Update profil sendiri (name, company, phone, address, dll)."""
    db = await _get_db()
    upd = {}
    for k in ("name", "company", "phone", "attention", "address_line1",
              "address_line2", "city", "province", "postal_code",
              "country", "npwp", "billing_emails"):
        v = getattr(payload, k, None)
        if v is not None:
            upd[k] = v
    if not upd:
        return _user_public(user)
    await db.users.update_one({"_id": ObjectId(user["id"])}, {"$set": upd})
    updated = await db.users.find_one({"_id": ObjectId(user["id"])})
    # Mirror to CRM
    try:
        await _upsert_crm_from_user(db, updated, status="existing")
    except Exception:
        pass
    return _user_public(updated)


# ============================================================
# Password lifecycle - change / admin-reset / forgot / reset
# ============================================================
import hashlib  # noqa: E402


import secrets as _secrets  # noqa: E402


from fastapi import Request  # noqa: E402




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
                  "password_changed_at": _now(),
                  "must_change_password": False}},
    )
    # Invalidate any outstanding reset tokens for this user
    await db.password_resets.update_many({"user_id": u["_id"], "used": False}, {"$set": {"used": True}})
    return {"ok": True, "message": "Password updated"}


@router.post("/admin/users/{uid}/reset-password")
async def admin_reset_user_password(uid: str, payload: m.AdminResetPasswordIn,
                                    request: Request,
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
    await log_audit(db, actor=admin, action="user.password_reset", category="security",
                    target_type="user", target_id=uid,
                    target_label=target.get("email", ""),
                    metadata={"notify_user": bool(payload.notify_user)},
                    severity="warning", request=request)
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
@_rl_limiter.limit(AUTH_FORGOT_LIMIT)
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
            logging.getLogger("portal.password_reset").warning(
                f"[password-reset] SMTP unavailable ({e}) - reset link for {email}: {reset_url}"
            )
    # Always the same response
    return {"ok": True, "message": "If an account exists for that email, a reset link has been sent."}


@router.post("/auth/reset-password")
@_rl_limiter.limit(AUTH_RESET_LIMIT)
async def auth_reset_password(payload: m.ResetPasswordIn, request: Request):
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

    Raises on any failure - caller decides whether to swallow.
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
            f"<p style='color:#64748b;font-size:12px'>Didn't request this? You can ignore this email - your password wasn't changed.</p>"
        )
    else:
        subject = "Your Intercloud portal password was reset"
        html = (
            f"<p>Hi {user.get('name','there')},</p>"
            f"<p>An administrator has reset the password for your Intercloud portal account. "
            f"Please contact your account manager for the new password, "
            f"or use the &lsquo;Forgot password&rsquo; link on the portal login page.</p>"
        )
    await asyncio.to_thread(_iv2.SMTPMailer(smtp).send,
                            to=user["email"], subject=subject, html=html)
