"""Integrations: module hub (legacy) + integrations-v2 provider settings.

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
from .shared import _EXTRA_PAYMENT_MODULES, _get_db, _get_setting_value, _iso, _now, _oid  # noqa: E402

router = APIRouter()


# ============================================================
# INTEGRATIONS (WHMCS-style module hub)
# ============================================================
from ..integrations_registry import (
    module_list, module_schema, redact, SECRET_FIELD_TYPES,
)


def _cfg_encrypt(module: str, cfg: dict) -> dict:
    """Encrypt schema-marked secret fields (type password) of a module-hub config."""
    keys = {f["key"] for f in (module_schema(module) or {}).get("fields", [])
            if f["type"] in SECRET_FIELD_TYPES}
    return {k: (_sb_enc(v) if k in keys else v) for k, v in (cfg or {}).items()}


def _iv2_settings_for_module(module: str, cfg: dict) -> dict:
    """Map a module-hub config (hostname/port/protocol/...) to the
    integrations_v2 settings shape ({credentials, options})."""
    cfg = _sb_dec_config(cfg or {})
    proto = (cfg.get("protocol") or "https").lower()
    host = cfg.get("hostname") or ""

    def _url(default_port: int) -> str:
        scheme = "http" if proto == "http" else "https"
        return f"{scheme}://{host}:{int(cfg.get('port') or default_port)}"

    if module == "cpanel":
        return {"credentials": {"host": _url(2087), "username": cfg.get("username"),
                                "api_token": cfg.get("api_token")},
                "options": {"ssl_verify": False}}
    if module == "plesk":
        return {"credentials": {"host": _url(8443), "username": cfg.get("username"),
                                "password": cfg.get("password")},
                "options": {"ssl_verify": False}}
    if module == "directadmin":
        return {"credentials": {"host": _url(2222), "username": cfg.get("username"),
                                "api_token": cfg.get("api_token")},
                "options": {"ssl_verify": False}}
    if module == "proxmox":
        return {"credentials": {"host": _url(8006), "username": cfg.get("username"),
                                "password": cfg.get("password"),
                                "token_id": cfg.get("api_token_id"),
                                "token_secret": cfg.get("api_token_secret")},
                "options": {"ssl_verify": False}}
    if module == "mikrotik":
        return {"credentials": {"host": host, "port": cfg.get("port") or 8728,
                                "username": cfg.get("username"), "password": cfg.get("password"),
                                "use_tls": proto == "api-ssl"}}
    if module == "smtp":
        return {"credentials": {"host": host, "port": cfg.get("port") or 587,
                                "username": cfg.get("username"), "password": cfg.get("password")},
                "options": {"use_tls": proto == "tls", "use_ssl": proto == "ssl",
                            "from_email": cfg.get("from_email"),
                            "from_name": cfg.get("from_name")}}
    if module == "duitku":
        return {"credentials": {"merchant_code": cfg.get("merchant_code"),
                                "api_key": cfg.get("api_key")},
                "options": {"environment": cfg.get("environment") or "production"}}
    if module == "midtrans":
        return {"credentials": {"server_key": cfg.get("server_key"),
                                "client_key": cfg.get("client_key")},
                "options": {"environment": cfg.get("environment") or "production"}}
    if module == "xendit":
        return {"credentials": {"secret_key": cfg.get("secret_key"),
                                "webhook_token": cfg.get("callback_token")}}
    return {"credentials": dict(cfg or {})}


async def _live_test_connection(module: str, cfg: dict) -> dict:
    """Run a REAL connection test for a module-hub integration. Returns
    {ok, message, latency_ms}. No mocked success in production."""
    import time as _time
    import asyncio as _asyncio
    schema = module_schema(module)
    if not schema:
        return {"ok": False, "message": f"Unknown module: {module}"}
    missing = [f["label"] for f in schema["fields"]
               if f.get("required") and not cfg.get(f["key"])]
    if missing:
        return {"ok": False, "message": f"Missing required fields: {', '.join(missing)}"}
    started = _time.monotonic()
    try:
        settings = _iv2_settings_for_module(module, cfg)
        if module == "cpanel":
            result = await iv2.CpanelClient(settings).test_connection()
        elif module == "plesk":
            result = await iv2.PleskClient(settings).test_connection()
        elif module == "directadmin":
            result = await iv2.DirectAdminClient(settings).test_connection()
        elif module == "proxmox":
            result = await iv2.ProxmoxClient(settings).test_connection()
        elif module == "mikrotik":
            result = await _asyncio.to_thread(iv2.MikrotikClient(settings).test_connection)
        elif module == "smtp":
            result = await _asyncio.to_thread(iv2.SMTPMailer(settings).test_connection)
        elif module == "duitku":
            result = await iv2.DuitkuGateway(settings).test_connection()
        elif module == "midtrans":
            result = await iv2.MidtransGateway(settings).test_connection()
        elif module == "xendit":
            result = await iv2.XenditGateway(settings).test_connection()
        elif module in ("whois", "blacklist"):
            import httpx as _httpx
            endpoint = cfg.get("endpoint") or ""
            async with _httpx.AsyncClient(timeout=10, follow_redirects=True) as c:
                r = await c.get(endpoint)
            result = {"ok": r.status_code < 500,
                      "message": f"Endpoint reachable (HTTP {r.status_code})"}
        else:
            result = {"ok": False, "message": f"No live test available for module '{module}'"}
    except Exception as e:
        result = {"ok": False, "message": f"{type(e).__name__}: {str(e)[:180]}"}
    result["latency_ms"] = int((_time.monotonic() - started) * 1000)
    result.pop("details", None)
    return result


@router.get("/admin/integrations/modules")
async def list_integration_modules(admin=Depends(get_current_admin)):
    """Return the module registry (schemas for the Add Server dialog).

    Midtrans/Xendit stay hidden unless `enable_extra_payment_gateways` is on -
    Duitku is the only active payment gateway by policy."""
    db = await _get_db()
    allow_extra = bool(await _get_setting_value(db, "enable_extra_payment_gateways", False))
    return [mdl for mdl in module_list()
            if allow_extra or mdl["key"] not in _EXTRA_PAYMENT_MODULES]


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
    allow_extra = bool(await _get_setting_value(db, "enable_extra_payment_gateways", False))
    if not allow_extra:
        docs = [d for d in docs if d.get("module") not in _EXTRA_PAYMENT_MODULES]
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
        "config": _cfg_encrypt(module, payload.get("config", {})),
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
        "config": _cfg_encrypt(existing["module"], merged),
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
    result = await _live_test_connection(d["module"], d.get("config", {}))
    await db.integrations.update_one(
        {"_id": d["_id"]},
        {"$set": {"last_test_at": _now(), "last_test_result": result}},
    )
    return result


@router.post("/admin/integrations/test-config")
async def test_integration_draft(payload: dict, admin=Depends(get_current_admin)):
    """Test connection with an unsaved config (used by the Add Server dialog)."""
    return await _live_test_connection(payload.get("module", ""), payload.get("config", {}))


@router.get("/admin/integrations-v2/schema")
async def integrations_v2_schema(admin=Depends(get_current_admin)):
    """Returns the field schema the admin UI uses to render each integration's settings form."""
    db = await _get_db()
    allow_extra = bool(await _get_setting_value(db, "enable_extra_payment_gateways", False))
    return {k: v for k, v in iv2.INTEGRATION_SCHEMA.items()
            if allow_extra or k not in _EXTRA_PAYMENT_MODULES}


@router.get("/admin/integrations-v2")
async def integrations_v2_list(admin=Depends(get_current_admin)):
    """Return all persisted integration settings (secrets masked)."""
    db = await _get_db()
    allow_extra = bool(await _get_setting_value(db, "enable_extra_payment_gateways", False))
    out = {}
    for provider in iv2.INTEGRATION_SCHEMA.keys():
        if not allow_extra and provider in _EXTRA_PAYMENT_MODULES:
            continue
        d = await iv2.get_settings(db, provider)
        out[provider] = iv2.redact(d) or {"provider": provider, "enabled": False, "credentials": {}, "options": {}}
    return out


@router.put("/admin/integrations-v2/{provider}")
async def integrations_v2_upsert(provider: str, payload: dict, request: Request, admin=Depends(get_current_admin)):
    if provider not in iv2.INTEGRATION_SCHEMA:
        raise HTTPException(status_code=404, detail="Unknown provider")
    db = await _get_db()
    if provider in _EXTRA_PAYMENT_MODULES and not bool(
            await _get_setting_value(db, "enable_extra_payment_gateways", False)):
        raise HTTPException(status_code=400,
                            detail="Gateway ini dinonaktifkan - Duitku adalah satu-satunya payment gateway aktif.")
    # Merge - never drop existing secrets if the incoming value is empty
    existing = await iv2.get_settings(db, provider) or {}
    creds_in = payload.get("credentials") or {}
    merged_creds = {**(existing.get("credentials") or {})}
    for k, v in creds_in.items():
        if v not in ("", None):
            merged_creds[k] = v
    doc = {
        "enabled": bool(payload.get("enabled")),
        "sandbox": payload.get("sandbox", existing.get("sandbox")),
        "channel": payload.get("channel", existing.get("channel")),
        "credentials": merged_creds,
        "options": payload.get("options", existing.get("options") or {}),
    }
    saved = await iv2.upsert_settings(db, provider, doc)
    # Redact both snapshots before writing audit (credentials → ••••)
    await log_audit(db, actor=admin, action="integration.update", category="integrations",
                    target_type="integration", target_id=provider, target_label=provider,
                    before=iv2.redact(existing) if existing else None,
                    after=iv2.redact(saved),
                    severity="warning", request=request)
    return iv2.redact(saved)


@router.delete("/admin/integrations-v2/{provider}")
async def integrations_v2_delete(provider: str, request: Request, admin=Depends(get_current_admin)):
    """Wipe all persisted settings for a provider (credentials + options + enabled).

    Useful for rotating credentials cleanly - the PUT endpoint merges by design,
    so it cannot clear a stored secret on its own.
    """
    if provider not in iv2.INTEGRATION_SCHEMA:
        raise HTTPException(status_code=404, detail="Unknown provider")
    db = await _get_db()
    r = await db.integration_settings.delete_one({"provider": provider})
    if r.deleted_count:
        await log_audit(db, actor=admin, action="integration.delete", category="integrations",
                        target_type="integration", target_id=provider, target_label=provider,
                        severity="warning", request=request)
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
    if provider == "cpanel":
        c = settings.get("credentials") or {}
        missing = [k for k in ("host", "username") if not c.get(k)]
        secret_ok = bool(c.get("api_token") or c.get("password"))
        if missing or not secret_ok:
            return {"ok": False, "message": f"Missing credentials: {', '.join(missing) or 'api_token/password'}"}
        return await iv2.CpanelClient(settings).test_connection()
    if provider == "plesk":
        c = settings.get("credentials") or {}
        missing = [k for k in ("host", "username") if not c.get(k)]
        secret_ok = bool(c.get("api_token") or c.get("password"))
        if missing or not secret_ok:
            return {"ok": False, "message": f"Missing credentials: {', '.join(missing) or 'api_token/password'}"}
        return await iv2.PleskClient(settings).test_connection()
    if provider == "directadmin":
        c = settings.get("credentials") or {}
        missing = [k for k in ("host", "username") if not c.get(k)]
        secret_ok = bool(c.get("api_token") or c.get("password"))
        if missing or not secret_ok:
            return {"ok": False, "message": f"Missing credentials: {', '.join(missing) or 'api_token/password'}"}
        return await iv2.DirectAdminClient(settings).test_connection()
    if provider == "rna":
        c = settings.get("credentials") or {}
        missing = [k for k in ("reseller_id", "api_key") if not c.get(k)]
        if missing:
            return {"ok": False, "message": f"Missing credentials: {', '.join(missing)}"}
        return await iv2.RdashClient(settings).test_connection()
    return {"ok": False, "message": "No test method"}
