"""Client portal: dashboard, services, VM self-service, invoices view, traffic.

Split from the former monolithic routes.py - behavior preserved 1:1.
"""
import os
import asyncio
import logging
import secrets
import re
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket
from fastapi.responses import JSONResponse
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
from .provision import _proxmox_settings_for_service, _cp_settings_for_service  # noqa: E402
from .shared import _get_db, _get_setting_value, _insert_numbered, _mark_overdue, _now, _oid, _serialize_invoice  # noqa: E402

router = APIRouter()


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
            "auto_renew": d.get("auto_renew", True),
            "config": d.get("config", {}),
            "termination_request": d.get("termination_request"),
            "suspended_reason": d.get("suspended_reason", ""),
        })
    return result


@router.get("/client/hosting-accounts")
async def client_hosting_accounts(user=Depends(get_current_user)):
    """Daftar akun hosting (cPanel/Plesk/DirectAdmin) milik klien."""
    db = await _get_db()
    docs = await db.services.find(
        {"user_id": ObjectId(user["id"]), "category": "hosting"}
    ).sort("created_at", -1).to_list(200)
    out = []
    for d in docs:
        cfg = d.get("config") or {}
        out.append({
            "id": str(d["_id"]),
            "product_name": d.get("product_name", ""),
            "name": d.get("name", ""),
            "status": d.get("status", "active"),
            "next_renewal": d.get("next_renewal", ""),
            "price_monthly": d.get("price_monthly", 0),
            "control_panel": cfg.get("control_panel", ""),
            "domain": cfg.get("domain") or cfg.get("hostname", ""),
            "username": cfg.get("username", ""),
            "ip": cfg.get("ip", ""),
            "provision_status": cfg.get("provision_status", "manual"),
        })
    return out


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
        "auto_renew": d.get("auto_renew", True),
        "config": d.get("config", {}),
        "self_service_log": (d.get("self_service_log") or [])[-10:],
        "pending_upgrade": bool(d.get("pending_upgrade")),
    }


@router.put("/client/services/{sid}/auto-renew")
async def client_service_auto_renew(sid: str, payload: dict, user=Depends(get_current_user)):
    """Klien mengatur auto-renewal per layanan. False = sweep tidak membuat invoice perpanjangan."""
    db = await _get_db()
    d = await db.services.find_one({"_id": _oid(sid), "user_id": ObjectId(user["id"])})
    if not d:
        raise HTTPException(status_code=404, detail="Service not found")
    val = bool(payload.get("auto_renew", True))
    await db.services.update_one({"_id": d["_id"]}, {
        "$set": {"auto_renew": val},
        "$push": {"self_service_log": {"at": _now(), "action": "auto_renew",
                                       "message": f"Auto-renewal {'diaktifkan' if val else 'dimatikan'} oleh klien."}},
    })
    return {"ok": True, "auto_renew": val}


# ---------------- Client self-service VM control ----------------
_CLIENT_VM_ACTIONS = ("start", "stop", "reboot", "shutdown", "reset")


_VM_CATEGORIES = ("vps", "cloud", "dedicated")


@router.get("/client/vms")
async def client_vms(user=Depends(get_current_user)):
    """Daftar semua VM milik klien dengan status terkini dari Proxmox."""
    db = await _get_db()
    svcs = await db.services.find(
        {"user_id": ObjectId(user["id"]), "category": {"$in": list(_VM_CATEGORIES)}}
    ).sort("created_at", -1).to_list(100)
    _px_cache: dict = {}

    async def _px_for(svc_doc):
        key = ((svc_doc.get("config") or {}).get("server_id") or "").strip() or "legacy"
        if key not in _px_cache:
            st = await _proxmox_settings_for_service(db, svc_doc)
            _px_cache[key] = iv2.ProxmoxClient(st) if st else None
        return _px_cache[key]

    out = []
    for svc in svcs:
        cfg = svc.get("config") or {}
        item = {
            "service_id": str(svc["_id"]),
            "name": svc.get("name", ""),
            "product_name": svc.get("product_name", ""),
            "service_status": svc.get("status", ""),
            "node": cfg.get("node"),
            "vmid": cfg.get("vmid"),
            "configured": False,
            "status": "unknown",
        }
        client = await _px_for(svc)
        if client and cfg.get("node") and cfg.get("vmid"):
            item["configured"] = True
            try:
                st = await client.vm_status(cfg["node"], int(cfg["vmid"]))
                item["status"] = st.get("status", "unknown")
                item["uptime"] = st.get("uptime")
                item["cpu"] = st.get("cpu")
                item["mem"] = st.get("mem")
            except Exception:
                item["status"] = "unreachable"
        out.append(item)
    return out


@router.get("/client/services/{sid}/vm")
async def client_vm_status(sid: str, user=Depends(get_current_user)):
    """Live VM status for the client's own service (read-only)."""
    db = await _get_db()
    svc = await db.services.find_one({"_id": _oid(sid), "user_id": ObjectId(user["id"])})
    if not svc:
        raise HTTPException(status_code=404, detail="Service not found")
    cfg = svc.get("config") or {}
    s = await _proxmox_settings_for_service(db, svc)
    restart_required = bool(cfg.get("restart_required"))
    if not (s and cfg.get("node") and cfg.get("vmid")):
        return {"configured": False, "status": "unknown", "restart_required": restart_required}
    try:
        st = await iv2.ProxmoxClient(s).vm_status(cfg["node"], int(cfg["vmid"]))
        return {"configured": True, "status": st.get("status", "unknown"),
                "uptime": st.get("uptime"), "cpu": st.get("cpu"),
                "mem": st.get("mem"), "maxmem": st.get("maxmem"),
                "node": cfg["node"], "vmid": int(cfg["vmid"]),
                "restart_required": restart_required}
    except Exception as e:
        return {"configured": True, "status": "unreachable", "error": str(e)[:200],
                "restart_required": restart_required}


@router.get("/client/services/{sid}/vm/metrics")
async def client_vm_metrics(sid: str, timeframe: str = "hour", user=Depends(get_current_user)):
    """Grafik resource VM (CPU/RAM/Disk/Net) dari RRD Proxmox - default 1 jam."""
    db = await _get_db()
    svc = await db.services.find_one({"_id": _oid(sid), "user_id": ObjectId(user["id"])})
    if not svc:
        raise HTTPException(status_code=404, detail="Service not found")
    cfg = svc.get("config") or {}
    s = await _proxmox_settings_for_service(db, svc)
    if not (s and cfg.get("node") and cfg.get("vmid")):
        return {"available": False, "message": "VM belum terhubung ke layanan ini."}
    try:
        rows = await iv2.ProxmoxClient(s).rrddata(cfg["node"], int(cfg["vmid"]), timeframe)
    except Exception as e:
        return {"available": False, "message": f"Gagal membaca metrik dari server: {str(e)[:150]}"}
    series = []
    for r in rows:
        if r.get("time") is None:
            continue
        maxmem = float(r.get("maxmem") or 0)
        mem = float(r.get("mem") or 0)
        series.append({
            "t": int(r["time"]),
            "cpu_pct": round(float(r.get("cpu") or 0) * 100, 2),
            "mem_used_mb": round(mem / 1048576, 1),
            "mem_total_mb": round(maxmem / 1048576, 1),
            "mem_pct": round(mem / maxmem * 100, 2) if maxmem else 0,
            "disk_read_kb": round(float(r.get("diskread") or 0) / 1024, 1),
            "disk_write_kb": round(float(r.get("diskwrite") or 0) / 1024, 1),
            "net_in_kb": round(float(r.get("netin") or 0) / 1024, 1),
            "net_out_kb": round(float(r.get("netout") or 0) / 1024, 1),
        })
    return {"available": True, "timeframe": timeframe, "series": series,
            "vm": {"node": cfg["node"], "vmid": int(cfg["vmid"])}}


@router.get("/client/services/{sid}/vm/console")
async def client_vm_console_info(sid: str, user=Depends(get_current_user)):
    """Tiket noVNC console untuk VM milik klien sendiri (via WS proxy portal)."""
    db = await _get_db()
    svc = await db.services.find_one({"_id": _oid(sid), "user_id": ObjectId(user["id"])})
    if not svc:
        raise HTTPException(status_code=404, detail="Service not found")
    if svc.get("category") not in _VM_CATEGORIES:
        raise HTTPException(status_code=400, detail="Layanan ini bukan VM")
    if svc.get("status") == "terminated":
        raise HTTPException(status_code=403, detail="Layanan sudah diterminasi - console dinonaktifkan.")
    if svc.get("status") == "suspended":
        raise HTTPException(status_code=403, detail="Layanan sedang disuspend")
    cfg = svc.get("config") or {}
    s = await _proxmox_settings_for_service(db, svc)
    if not (s and cfg.get("node") and cfg.get("vmid")):
        raise HTTPException(status_code=400, detail="VM belum terhubung ke layanan ini")
    try:
        t = await iv2.ProxmoxClient(s).vnc_ticket(cfg["node"], int(cfg["vmid"]))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Gagal membuat tiket console: {str(e)[:150]}")
    await db.services.update_one({"_id": svc["_id"]}, {"$push": {"self_service_log": {
        "at": _now(), "action": "console_opened", "by": user.get("email", "")}}})
    return {"ok": True, "node": cfg["node"], "vmid": int(cfg["vmid"]),
            "port": t.get("port"), "ticket": t.get("ticket"),
            "ws_path": f"/api/portal/client/services/{sid}/vm/console-ws"}


@router.websocket("/client/services/{sid}/vm/console-ws")
async def client_vm_console_ws(ws: WebSocket, sid: str):
    """WS relay browser (noVNC) <-> Proxmox vncwebsocket. Klien tidak perlu
    kredensial Proxmox - autentikasi via JWT portal + vncticket sekali pakai."""
    from portal import auth as _auth
    token = ws.query_params.get("token", "")
    port = ws.query_params.get("port", "")
    vncticket = ws.query_params.get("vncticket", "")
    try:
        payload = _auth.decode_token(token)
        uid = payload["sub"]
    except Exception:
        await ws.close(code=4401)
        return
    db = await _get_db()
    try:
        svc = await db.services.find_one({"_id": _oid(sid), "user_id": ObjectId(uid)})
    except Exception:
        svc = None
    cfg = (svc or {}).get("config") or {}
    s = await _proxmox_settings_for_service(db, svc) if svc else None
    if not (svc and svc.get("category") in _VM_CATEGORIES
            and svc.get("status") not in ("suspended", "terminated")
            and cfg.get("node") and cfg.get("vmid") and s and port and vncticket):
        await ws.close(code=4403)
        return
    px = iv2.ProxmoxClient(s)
    scheme = "wss" if px.host.startswith("https") else "ws"
    hostpart = px.host.split("://", 1)[1]
    upstream = (f"{scheme}://{hostpart}/api2/json/nodes/{cfg['node']}/qemu/{int(cfg['vmid'])}"
                f"/vncwebsocket?port={quote(str(port), safe='')}&vncticket={quote(vncticket, safe='')}")
    headers = {}
    if px.token_id and px.token_secret:
        headers["Authorization"] = f"PVEAPIToken={px.token_id}={px.token_secret}"
    import ssl as _ssl
    import websockets as _wsl
    ssl_ctx = None
    if scheme == "wss":
        ssl_ctx = _ssl.create_default_context()
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = _ssl.CERT_NONE
    # Echo back the "binary" subprotocol only when the client (noVNC) offered it.
    # Forcing a subprotocol the client didn't request makes the browser reject
    # the upgrade -> silent disconnect.
    offered = ws.scope.get("subprotocols") or []
    accept_sub = "binary" if "binary" in offered else None
    await ws.accept(subprotocol=accept_sub)
    try:
        async with _wsl.connect(upstream, additional_headers=headers, ssl=ssl_ctx,
                                subprotocols=["binary"], max_size=None,
                                open_timeout=15, ping_interval=20) as up:
            async def _client_to_pve():
                while True:
                    msg = await ws.receive()
                    if msg.get("type") == "websocket.disconnect":
                        return
                    if msg.get("bytes") is not None:
                        await up.send(msg["bytes"])
                    elif msg.get("text"):
                        await up.send(msg["text"].encode())

            async def _pve_to_client():
                async for m in up:
                    await ws.send_bytes(m if isinstance(m, (bytes, bytearray)) else m.encode())

            t1 = asyncio.create_task(_client_to_pve())
            t2 = asyncio.create_task(_pve_to_client())
            _, pending = await asyncio.wait({t1, t2}, return_when=asyncio.FIRST_COMPLETED)
            for p in pending:
                p.cancel()
    except Exception:
        pass
    finally:
        try:
            await ws.close()
        except Exception:
            pass


@router.post("/client/services/{sid}/vm/reset-password")
async def client_vm_reset_password(sid: str, payload: dict, request: Request, user=Depends(get_current_user)):
    """Self-service guest OS password reset via QEMU guest agent (audited)."""
    username = (payload.get("username") or "root").strip()
    password = payload.get("password") or ""
    generated = False
    if not password and payload.get("generate"):
        alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789!@#$%"
        password = "".join(secrets.choice(alphabet) for _ in range(16))
        generated = True
    if len(password) < 8:
        raise HTTPException(status_code=400, detail="Password minimal 8 karakter")
    db = await _get_db()
    svc = await db.services.find_one({"_id": _oid(sid), "user_id": ObjectId(user["id"])})
    if not svc:
        raise HTTPException(status_code=404, detail="Service not found")
    if svc.get("category") not in _VM_CATEGORIES:
        raise HTTPException(status_code=400, detail="Layanan ini bukan VM")
    if svc.get("status") == "terminated":
        raise HTTPException(status_code=403, detail="Layanan sudah diterminasi - kontrol VM dinonaktifkan.")
    if svc.get("status") == "suspended":
        raise HTTPException(status_code=403, detail="Layanan ditangguhkan. Lunasi tagihan untuk mengaktifkan kembali.")
    cfg = svc.get("config") or {}
    node, vmid = cfg.get("node"), cfg.get("vmid")
    if not (node and vmid):
        raise HTTPException(status_code=400, detail="VM belum terhubung ke layanan ini. Hubungi support.")
    s = await _proxmox_settings_for_service(db, svc)
    if not s:
        raise HTTPException(status_code=400, detail="Integrasi Proxmox belum aktif. Hubungi support.")
    client = iv2.ProxmoxClient(s)
    method = "guest-agent"
    try:
        st = await client.vm_status(node, int(vmid))
        if st.get("status") != "running":
            raise HTTPException(status_code=400, detail="VM harus dalam keadaan running untuk reset password.")
        await client.set_user_password(node, int(vmid), username, password)
    except HTTPException:
        raise
    except Exception as e:
        detail = str(e)[:200].lower()
        agent_missing = ("agent" in detail or "500" in detail or "timeout" in detail
                         or "timed out" in detail or "not running" in detail)
        if not agent_missing:
            raise HTTPException(status_code=502, detail=str(e)[:200])
        # Fallback: cloud-init password reset. cloud-init's set-passwords module
        # re-applies on every boot, so updating cipassword + rebooting resets the
        # OS password even without the QEMU guest agent.
        try:
            ci_user = username if username else "root"
            await client.set_config(node, int(vmid), {"ciuser": ci_user, "cipassword": password})
            await client.vm_action(node, int(vmid), "reboot")
            method = "cloud-init-reboot"
        except Exception as e2:
            raise HTTPException(
                status_code=502,
                detail=("Guest agent tidak aktif dan reset via cloud-init gagal "
                        f"({str(e2)[:120]}). Gunakan Console (noVNC) untuk reset manual."))
    await log_audit(db, actor=user, action="client_vm.reset_password", category="services",
                    target_type="service", target_id=str(svc["_id"]),
                    target_label=svc.get("name", ""),
                    metadata={"node": node, "vmid": int(vmid), "os_username": username, "method": method},
                    severity="warning", request=request)
    await db.services.update_one(
        {"_id": svc["_id"]},
        {"$push": {"self_service_log": {"at": _now(), "action": "reset_password",
                                        "by": user["email"], "method": method}}})
    out = {"ok": True, "username": username, "method": method}
    if method == "cloud-init-reboot":
        out["message"] = ("Guest agent tidak tersedia - password diterapkan via cloud-init. "
                          "VM sedang di-reboot; password baru aktif setelah VM menyala kembali (~1 menit).")
    if generated:
        out["generated_password"] = password
    return out


@router.post("/client/services/{sid}/vm/{action}")
async def client_vm_action(sid: str, action: str, request: Request, user=Depends(get_current_user)):
    """Self-service start/stop/reboot on the client's own VM (audited)."""
    if action not in _CLIENT_VM_ACTIONS:
        raise HTTPException(status_code=400, detail="Aksi tidak didukung")
    db = await _get_db()
    svc = await db.services.find_one({"_id": _oid(sid), "user_id": ObjectId(user["id"])})
    if not svc:
        raise HTTPException(status_code=404, detail="Service not found")
    if svc.get("category") not in _VM_CATEGORIES:
        raise HTTPException(status_code=400, detail="Layanan ini bukan VM")
    if svc.get("status") == "terminated":
        raise HTTPException(status_code=403, detail="Layanan sudah diterminasi - kontrol VM dinonaktifkan.")
    if svc.get("status") == "suspended":
        raise HTTPException(status_code=403, detail="Layanan ditangguhkan. Lunasi tagihan untuk mengaktifkan kembali.")
    cfg = svc.get("config") or {}
    node, vmid = cfg.get("node"), cfg.get("vmid")
    if not (node and vmid):
        raise HTTPException(status_code=400, detail="VM belum terhubung ke layanan ini. Hubungi support.")
    s = await _proxmox_settings_for_service(db, svc)
    if not s:
        raise HTTPException(status_code=400, detail="Integrasi Proxmox belum aktif. Hubungi support.")
    try:
        result = await iv2.ProxmoxClient(s).vm_action(node, int(vmid), action)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Proxmox error: {str(e)[:200]}")
    await log_audit(db, actor=user, action=f"client_vm.{action}", category="services",
                    target_type="service", target_id=str(svc["_id"]),
                    target_label=svc.get("name", ""),
                    metadata={"node": node, "vmid": int(vmid)}, request=request)
    ops = {"$push": {"self_service_log": {"at": _now(), "action": action, "by": user["email"]}}}
    if action in ("start", "reboot", "reset"):
        # Restart menerapkan spesifikasi upgrade -> hapus penanda "restart diperlukan".
        ops["$unset"] = {"config.restart_required": ""}
    await db.services.update_one({"_id": svc["_id"]}, ops)
    return {"ok": True, "action": action, "task": result}


# ---------------- Client self-service resource upgrade ----------------
_UPGRADE_PRICING_DEFAULT = {"cpu_per_core": 50000.0, "ram_per_gb": 25000.0, "disk_per_gb": 2000.0}


def _upgrade_quote(svc: dict, pricing: dict, cpu: int, ram_gb: int, disk_gb: int, tax_percent: float) -> dict:
    monthly_delta = (cpu * float(pricing["cpu_per_core"])
                     + ram_gb * float(pricing["ram_per_gb"])
                     + disk_gb * float(pricing["disk_per_gb"]))
    today = datetime.now(timezone.utc).date()
    try:
        renewal = datetime.fromisoformat(svc.get("next_renewal", "")).date()
        days_left = max(0, min(31, (renewal - today).days))
    except Exception:
        days_left = 30
    factor = days_left / 30.0
    prorated = round(monthly_delta * factor, 2)
    tax = round(prorated * tax_percent / 100.0, 2)
    return {
        "cpu": cpu, "ram_gb": ram_gb, "disk_gb": disk_gb,
        "monthly_delta": round(monthly_delta, 2),
        "days_left": days_left,
        "prorated_charge": prorated,
        "tax_percent": tax_percent,
        "tax_amount": tax,
        "total": round(prorated + tax, 2),
    }


async def _upgrade_ctx(db, sid: str, user):
    svc = await db.services.find_one({"_id": _oid(sid), "user_id": ObjectId(user["id"])})
    if not svc:
        raise HTTPException(status_code=404, detail="Service not found")
    if svc.get("category") not in _VM_CATEGORIES:
        raise HTTPException(status_code=400, detail="Upgrade resource hanya tersedia untuk layanan VM")
    if svc.get("status") not in ("active",):
        raise HTTPException(status_code=403, detail="Layanan harus aktif untuk melakukan upgrade")
    pricing = await _get_setting_value(db, "upgrade_pricing", _UPGRADE_PRICING_DEFAULT)
    pricing = {**_UPGRADE_PRICING_DEFAULT, **(pricing or {})}
    tax_percent = float(await _get_setting_value(db, "default_tax_percent", 11.0))
    return svc, pricing, tax_percent


def _upgrade_units(payload: dict) -> tuple:
    try:
        cpu = max(0, min(64, int(payload.get("cpu") or 0)))
        ram_gb = max(0, min(256, int(payload.get("ram_gb") or 0)))
        disk_gb = max(0, min(2000, int(payload.get("disk_gb") or 0)))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Nilai upgrade tidak valid")
    if cpu + ram_gb + disk_gb == 0:
        raise HTTPException(status_code=400, detail="Pilih minimal satu resource untuk di-upgrade")
    return cpu, ram_gb, disk_gb


@router.get("/client/services/{sid}/upgrade/options")
async def client_upgrade_options(sid: str, user=Depends(get_current_user)):
    db = await _get_db()
    svc, pricing, tax_percent = await _upgrade_ctx(db, sid, user)
    cfg = svc.get("config") or {}
    return {
        "pricing": pricing,
        "tax_percent": tax_percent,
        "current": {"cpu": cfg.get("cpu"), "ram_gb": cfg.get("ram_gb"), "disk_gb": cfg.get("disk_gb")},
        "pending_upgrade": bool(svc.get("pending_upgrade")),
    }


@router.post("/client/services/{sid}/upgrade/preview")
async def client_upgrade_preview(sid: str, payload: dict, user=Depends(get_current_user)):
    db = await _get_db()
    svc, pricing, tax_percent = await _upgrade_ctx(db, sid, user)
    cpu, ram_gb, disk_gb = _upgrade_units(payload)
    return _upgrade_quote(svc, pricing, cpu, ram_gb, disk_gb, tax_percent)


@router.post("/client/services/{sid}/upgrade")
async def client_upgrade_request(sid: str, payload: dict, request: Request, user=Depends(get_current_user)):
    """Create the prorated difference invoice for a self-service resource upgrade."""
    db = await _get_db()
    svc, pricing, tax_percent = await _upgrade_ctx(db, sid, user)
    if svc.get("pending_upgrade"):
        raise HTTPException(status_code=400, detail="Masih ada upgrade yang menunggu pembayaran untuk layanan ini")
    cpu, ram_gb, disk_gb = _upgrade_units(payload)
    q = _upgrade_quote(svc, pricing, cpu, ram_gb, disk_gb, tax_percent)
    items = []
    if cpu:
        items.append({"description": f"Upgrade +{cpu} vCPU - {svc.get('product_name','')} (prorata {q['days_left']} hari)",
                      "qty": 1, "price": round(cpu * pricing["cpu_per_core"] * q["days_left"] / 30.0, 2)})
    if ram_gb:
        items.append({"description": f"Upgrade +{ram_gb} GB RAM - {svc.get('product_name','')} (prorata {q['days_left']} hari)",
                      "qty": 1, "price": round(ram_gb * pricing["ram_per_gb"] * q["days_left"] / 30.0, 2)})
    if disk_gb:
        items.append({"description": f"Upgrade +{disk_gb} GB Disk - {svc.get('product_name','')} (prorata {q['days_left']} hari)",
                      "qty": 1, "price": round(disk_gb * pricing["disk_per_gb"] * q["days_left"] / 30.0, 2)})
    for it in items:
        it["total"] = round(it["qty"] * it["price"], 2)
    subtotal = round(sum(i["total"] for i in items), 2)
    tax = round(subtotal * tax_percent / 100.0, 2)
    due = (datetime.now(timezone.utc) + timedelta(days=7)).date().isoformat()
    inv = {
        "user_id": ObjectId(user["id"]),
        "items": items,
        "subtotal": subtotal,
        "tax_percent": tax_percent,
        "tax_amount": tax,
        "total": round(subtotal + tax, 2),
        "due_date": due,
        "status": "unpaid",
        "payment_method": None,
        "paid_at": None,
        "notes": f"Upgrade resource {svc.get('name','')} - berlaku setelah pembayaran.",
        "service_id": str(svc["_id"]),
        "upgrade": {"cpu": cpu, "ram_gb": ram_gb, "disk_gb": disk_gb,
                    "monthly_delta": q["monthly_delta"]},
        "created_at": _now(),
    }
    inv = await _insert_numbered(db, "invoices", "INV", inv)
    await db.services.update_one(
        {"_id": svc["_id"]},
        {"$set": {"pending_upgrade": {
            "cpu": cpu, "ram_gb": ram_gb, "disk_gb": disk_gb,
            "monthly_delta": q["monthly_delta"],
            "invoice_id": str(inv["_id"]),
            "requested_at": _now(),
        }}})
    await log_audit(db, actor=user, action="client_service.upgrade_requested", category="services",
                    target_type="service", target_id=str(svc["_id"]), target_label=svc.get("name", ""),
                    metadata={"cpu": cpu, "ram_gb": ram_gb, "disk_gb": disk_gb,
                              "invoice": inv["number"], "total": inv["total"]},
                    request=request)
    return {"ok": True, "invoice_id": str(inv["_id"]), "number": inv["number"],
            "total": inv["total"], "due_date": due, "quote": q}


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
    if not duitku:
        # iv2-style settings count too (either storage system may hold the creds)
        iv2_duitku = await iv2.get_settings(db, "duitku")
        duitku = iv2_duitku if (iv2_duitku or {}).get("enabled") else None
    return {
        "bank_accounts": banks,
        "duitku_enabled": bool(duitku),
    }


# Traffic Report - live samples only (no mock data in production)
@router.get("/client/services/{sid}/traffic")
async def client_service_traffic(sid: str, user=Depends(get_current_user)):
    db = await _get_db()
    d = await db.services.find_one({"_id": _oid(sid), "user_id": ObjectId(user["id"])})
    if not d:
        raise HTTPException(status_code=404, detail="Service not found")
    samples = await db.traffic_samples.find({"service_id": sid}).sort("at", 1).to_list(500)
    if not samples:
        return {
            "service_id": sid,
            "service_name": d.get("name", ""),
            "range": "24h",
            "available": False,
            "points": [],
            "totals": {"in_gb": 0, "out_gb": 0},
            "peak_in_mbps": 0,
            "peak_out_mbps": 0,
            "message": ("Data trafik belum tersedia untuk layanan ini. "
                        "Hubungkan sumber data (NetFlow/SNMP/MikroTik) melalui "
                        "Admin - Integrations untuk menampilkan trafik live."),
        }
    points = [{"t": p.get("t", ""), "in_mbps": float(p.get("in_mbps", 0)),
               "out_mbps": float(p.get("out_mbps", 0))} for p in samples[-24:]]
    # 1 sampel = 1 jam (kolektor per jam) -> GB = Mbps * 3600 dtk / 8 / 1024
    total_in = round(sum(p["in_mbps"] for p in points) * 3600 / 8 / 1024, 2)
    total_out = round(sum(p["out_mbps"] for p in points) * 3600 / 8 / 1024, 2)
    return {
        "service_id": sid,
        "service_name": d.get("name", ""),
        "range": "24h",
        "available": True,
        "points": points,
        "totals": {"in_gb": total_in, "out_gb": total_out},
        "peak_in_mbps": max(p["in_mbps"] for p in points),
        "peak_out_mbps": max(p["out_mbps"] for p in points),
    }


# ---------------- Client self-service hosting (cPanel) ----------------
async def _client_hosting_service(db, sid: str, user: dict) -> tuple:
    """Resolve a hosting service owned by the requesting user + its WHM client.

    Enforces ownership (user_id match), hosting category, active status, and
    that a WHM username + server affinity exist. Raises HTTPException otherwise.
    Returns (service_doc, whm_username, CpanelClient).
    """
    svc = await db.services.find_one({"_id": _oid(sid), "user_id": ObjectId(user["id"])})
    if not svc:
        raise HTTPException(status_code=404, detail="Service not found")
    if svc.get("category") != "hosting":
        raise HTTPException(status_code=400, detail="Layanan ini bukan hosting")
    if svc.get("status") == "terminated":
        raise HTTPException(status_code=403, detail="Layanan sudah diterminasi.")
    if svc.get("status") == "suspended":
        raise HTTPException(status_code=403,
                            detail="Layanan ditangguhkan. Lunasi tagihan untuk mengaktifkan kembali.")
    username = ((svc.get("config") or {}).get("username") or "").strip()
    if not username:
        raise HTTPException(status_code=400,
                            detail="Akun hosting belum terhubung. Hubungi support.")
    settings = await _cp_settings_for_service(db, svc)
    if not settings:
        raise HTTPException(status_code=400,
                            detail="Integrasi panel hosting belum aktif. Hubungi support.")
    return svc, username, iv2.CpanelClient(settings)


@router.post("/client/services/{sid}/cpanel-sso")
async def client_cpanel_sso(sid: str, request: Request, user=Depends(get_current_user)):
    """Return a short-lived cPanel SSO login URL for the service owner.

    SECURITY: the URL is a login capability. It is returned only to the
    authenticated owner over HTTPS, never persisted to the DB or audit log,
    and the response carries Cache-Control: no-store.
    """
    db = await _get_db()
    svc, username, cp = await _client_hosting_service(db, sid, user)
    try:
        data = await cp.create_sso_session(username)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Gagal membuat sesi cPanel: {str(e)[:160]}")
    url = (data or {}).get("url") or ""
    if not url:
        raise HTTPException(status_code=502, detail="WHM tidak mengembalikan URL sesi cPanel.")
    # Audit the fact of an SSO issuance WITHOUT recording the URL/token.
    await log_audit(db, actor=user, action="client_hosting.cpanel_sso", category="services",
                    target_type="service", target_id=str(svc["_id"]),
                    target_label=svc.get("name", ""),
                    metadata={"whm_username": username}, request=request)
    # Return URL with explicit no-store header — never persist the URL anywhere.
    return JSONResponse(
        content={"url": url},
        headers={"Cache-Control": "no-store"},
    )


@router.post("/client/services/{sid}/reset-password")
async def client_hosting_reset_password(sid: str, payload: dict, request: Request,
                                        user=Depends(get_current_user)):
    """Self-service cPanel password reset for the service owner.

    A strong password is generated server-side, applied via WHM `passwd`, and
    returned once in the HTTPS response. It is NEVER stored in the DB or audit
    log; the customer is expected to save it / change it in cPanel.
    """
    db = await _get_db()
    svc, username, cp = await _client_hosting_service(db, sid, user)
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789!@#$%"
    password = "".join(secrets.choice(alphabet) for _ in range(16))
    try:
        await cp.change_password(username, password)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Reset password gagal: {str(e)[:160]}")
    # Audit the action WITHOUT the password value.
    await log_audit(db, actor=user, action="client_hosting.reset_password", category="services",
                    target_type="service", target_id=str(svc["_id"]),
                    target_label=svc.get("name", ""),
                    metadata={"whm_username": username}, severity="warning", request=request)
    return {"ok": True, "username": username, "generated_password": password,
            "message": ("Password cPanel berhasil direset. Simpan password ini sekarang - "
                        "kami tidak menyimpannya. Disarankan menggantinya di cPanel.")}


@router.get("/client/services/{sid}/packages")
async def client_hosting_packages(sid: str, user=Depends(get_current_user)):
    """List WHM packages available on the service's node, for upgrade UX."""
    db = await _get_db()
    svc, _username, cp = await _client_hosting_service(db, sid, user)
    try:
        packages = await cp.list_packages()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Gagal mengambil paket: {str(e)[:160]}")
    current = ((svc.get("config") or {}).get("whm_package") or "").strip()
    return {"packages": packages, "current_package": current}
