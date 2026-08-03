"""Security: login analytics, settings, blocked IPs, notifications, diagnostics.

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
from .shared import _get_db, _get_security_settings, _now  # noqa: E402

router = APIRouter()


# ============================================================
# SECURITY - Login Attempt Analytics
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
async def security_settings_put(payload: dict, request: Request, admin=Depends(get_current_admin)):
    db = await _get_db()
    before = await _get_security_settings(db)
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
        v = upd["notify_emails"]
        if isinstance(v, str):
            v = [x for x in v.replace(",", "\n").splitlines()]
        upd["notify_emails"] = [str(x).strip() for x in (v or []) if str(x).strip()]
    if "whitelist_ips" in upd:
        v = upd["whitelist_ips"]
        if isinstance(v, str):
            v = [x for x in v.replace(",", "\n").splitlines()]
        upd["whitelist_ips"] = [str(x).strip() for x in (v or []) if str(x).strip()]
    await db.settings.update_one({"_id": "security"}, {"$set": upd}, upsert=True)
    after = await _get_security_settings(db)
    await log_audit(db, actor=admin, action="security.settings_update", category="security",
                    target_type="settings", target_label="Security Settings",
                    before=before, after=after, severity="warning", request=request)
    return after


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
async def diagnostics_run(payload: dict, admin=Depends(require_roles("admin", "support"))):
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
async def diagnostics_tools_list(admin=Depends(require_roles("admin", "support"))):
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
