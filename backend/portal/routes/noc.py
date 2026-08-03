"""NOC/MikroTik: devices, live views, blackhole, DDoS detection, uptime polling.

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


@router.put("/admin/services/{sid}/traffic-source")
async def admin_set_service_traffic_source(sid: str, payload: dict, admin=Depends(get_current_admin)):
    """Map a service to a MikroTik device+interface for the hourly traffic
    collector. Empty device/interface clears the mapping."""
    db = await _get_db()
    svc = await db.services.find_one({"_id": _oid(sid)})
    if not svc:
        raise HTTPException(status_code=404, detail="Service not found")
    device_id = str(payload.get("device_id") or "").strip()
    interface = (payload.get("interface") or "").strip()
    if not device_id or not interface:
        await db.services.update_one(
            {"_id": svc["_id"]},
            {"$unset": {"config.traffic_device_id": "", "config.traffic_interface": ""}})
        return {"ok": True, "cleared": True}
    device = await _get_mikrotik_device(db, None if device_id == "legacy" else device_id)
    if not device:
        raise HTTPException(status_code=404, detail="MikroTik device not found")
    await db.services.update_one(
        {"_id": svc["_id"]},
        {"$set": {"config.traffic_device_id": device_id, "config.traffic_interface": interface}})
    sample = None
    try:
        from portal import emails as _em
        sample = await _em.sample_service_traffic(db, str(svc["_id"]), device, interface)
    except Exception:
        sample = None
    return {"ok": True, "device": device.get("name", ""), "interface": interface, "sample": sample}


# ---------------- Mikrotik multi-device management ----------------
async def _get_mikrotik_device(db, device_id: str | None):
    """Resolve a Mikrotik device by id; if id is missing return the legacy
    single-device credentials from `integration_settings.mikrotik` as a
    seamless fallback."""
    if device_id:
        try:
            doc = await db.mikrotik_devices.find_one({"_id": _oid(device_id)})
        except Exception:
            doc = None
        if not doc:
            raise HTTPException(status_code=404, detail="Mikrotik device not found")
        return doc
    # Fallback: use the integration_settings.mikrotik credentials
    s = await iv2.get_settings(db, "mikrotik")
    if not s or not s.get("enabled"):
        raise HTTPException(status_code=400, detail="Mikrotik not configured. Add a device in Admin ▸ MikroTik Ops ▸ Devices, or enable the legacy MikroTik integration.")
    return {"_id": None, "name": "default", **(s.get("credentials") or {})}


def _serialize_device(d: dict) -> dict:
    return {
        "id": str(d["_id"]) if d.get("_id") else None,
        "name": d.get("name", ""),
        "host": d.get("host", ""),
        "port": int(d.get("port") or 8728),
        "username": d.get("username", ""),
        "use_tls": bool(d.get("use_tls", False)),
        "site": d.get("site", ""),
        "notes": d.get("notes", ""),
        "created_at": d.get("created_at"),
    }


@router.get("/admin/mikrotik/devices")
async def mikrotik_devices_list(admin=Depends(require_roles("admin", "support"))):
    db = await _get_db()
    docs = await db.mikrotik_devices.find({}).sort("created_at", 1).to_list(500)
    out = [_serialize_device(d) for d in docs]
    # Attach legacy single-device fallback marker so the UI can show it too
    legacy = await iv2.get_settings(db, "mikrotik")
    if legacy and legacy.get("enabled") and (legacy.get("credentials") or {}).get("host"):
        c = legacy["credentials"]
        out.insert(0, {
            "id": None, "name": "Legacy (Integrations)", "host": c.get("host"),
            "port": int(c.get("port") or 8728), "username": c.get("username"),
            "use_tls": bool(c.get("use_tls", False)), "site": "", "notes": "",
            "legacy": True,
        })
    return out


@router.post("/admin/mikrotik/devices")
async def mikrotik_devices_create(payload: dict, admin=Depends(get_current_admin)):
    db = await _get_db()
    doc = {
        "name": (payload.get("name") or "").strip() or "unnamed",
        "host": (payload.get("host") or "").strip(),
        "port": int(payload.get("port") or 8728),
        "username": (payload.get("username") or "").strip(),
        "password": payload.get("password") or "",
        "use_tls": bool(payload.get("use_tls", False)),
        "site": payload.get("site") or "",
        "notes": payload.get("notes") or "",
        "created_at": _now(),
    }
    if not doc["host"] or not doc["username"]:
        raise HTTPException(status_code=400, detail="host and username are required")
    r = await db.mikrotik_devices.insert_one(doc)
    doc["_id"] = r.inserted_id
    return _serialize_device(doc)


@router.put("/admin/mikrotik/devices/{did}")
async def mikrotik_devices_update(did: str, payload: dict, admin=Depends(get_current_admin)):
    db = await _get_db()
    allowed = {"name", "host", "port", "username", "password", "use_tls", "site", "notes"}
    upd = {k: v for k, v in (payload or {}).items() if k in allowed}
    if "port" in upd: upd["port"] = int(upd["port"] or 8728)
    if "use_tls" in upd: upd["use_tls"] = bool(upd["use_tls"])
    if "password" in upd and not upd["password"]:
        upd.pop("password")  # don't blank out password when field is empty
    r = await db.mikrotik_devices.update_one({"_id": _oid(did)}, {"$set": upd})
    if not r.matched_count:
        raise HTTPException(status_code=404, detail="Device not found")
    d = await db.mikrotik_devices.find_one({"_id": _oid(did)})
    return _serialize_device(d)


@router.delete("/admin/mikrotik/devices/{did}")
async def mikrotik_devices_delete(did: str, admin=Depends(get_current_admin)):
    db = await _get_db()
    r = await db.mikrotik_devices.delete_one({"_id": _oid(did)})
    return {"ok": True, "deleted": r.deleted_count}


@router.post("/admin/mikrotik/devices/{did}/test")
async def mikrotik_devices_test(did: str, admin=Depends(get_current_admin)):
    db = await _get_db()
    d = await _get_mikrotik_device(db, did)
    import asyncio as _a
    r = await _a.get_event_loop().run_in_executor(None, lambda: iv2.MikrotikClient(d).test_connection())
    return r


async def _run_mikrotik(db, device_id: str | None, fn_name: str, *args, **kwargs):
    """Helper - resolve the device, dispatch a MikrotikClient method in a
    threadpool (librouteros is sync), return the result."""
    d = await _get_mikrotik_device(db, device_id)
    client = iv2.MikrotikClient(d)
    fn = getattr(client, fn_name)
    import asyncio as _a
    return await _a.get_event_loop().run_in_executor(None, lambda: fn(*args, **kwargs))


# ---------------- Mikrotik live views ----------------
@router.get("/admin/mikrotik/interfaces")
async def mikrotik_interfaces(admin=Depends(require_roles("admin", "support")), device_id: str | None = None):
    db = await _get_db()
    return await _run_mikrotik(db, device_id, "list_interfaces")


@router.get("/admin/mikrotik/bgp")
async def mikrotik_bgp(admin=Depends(require_roles("admin", "support")), device_id: str | None = None):
    db = await _get_db()
    return await _run_mikrotik(db, device_id, "list_bgp_peers")


@router.get("/admin/mikrotik/traffic")
async def mikrotik_traffic(interface: str, admin=Depends(require_roles("admin", "support")), device_id: str | None = None):
    db = await _get_db()
    return await _run_mikrotik(db, device_id, "traffic_monitor", interface)


@router.get("/admin/mikrotik/system")
async def mikrotik_system(admin=Depends(require_roles("admin", "support")), device_id: str | None = None):
    db = await _get_db()
    return await _run_mikrotik(db, device_id, "system_resource")


# ---------- Looking Glass ----------
@router.post("/admin/mikrotik/looking-glass")
async def mikrotik_looking_glass(payload: dict, admin=Depends(get_current_admin)):
    """Execute a Looking-Glass style lookup from the router:
    payload = {device_id?, tool: 'ping'|'traceroute'|'bgp_route', target: str}"""
    db = await _get_db()
    tool = (payload.get("tool") or "ping").lower()
    if tool not in ("ping", "traceroute", "bgp_route"):
        raise HTTPException(status_code=400, detail="tool must be ping/traceroute/bgp_route")
    target = (payload.get("target") or "").strip()
    if not target:
        raise HTTPException(status_code=400, detail="target is required")
    src_address = (payload.get("src_address") or payload.get("src-address") or "").strip() or None
    return await _run_mikrotik(db, payload.get("device_id"),
                               "looking_glass", tool=tool, target=target,
                               src_address=src_address)


# ---------- Blackhole ----------
@router.get("/admin/mikrotik/blackhole")
async def mikrotik_blackhole_list(admin=Depends(require_roles("admin", "support")),
                                  device_id: str | None = None,
                                  prefix_filter: str | None = None):
    db = await _get_db()
    return await _run_mikrotik(db, device_id, "blackhole_list", prefix_filter=prefix_filter)


@router.post("/admin/mikrotik/blackhole")
async def mikrotik_blackhole_add(payload: dict, admin=Depends(get_current_admin)):
    db = await _get_db()
    prefix = (payload.get("prefix") or "").strip()
    if not prefix:
        raise HTTPException(status_code=400, detail="prefix required")
    dev = await _get_mikrotik_device(db, payload.get("device_id"))
    result = await _run_mikrotik(db, payload.get("device_id"),
                                 "blackhole_add", prefix,
                                 comment=payload.get("comment") or "portal-blackhole")
    await db.blackhole_log.insert_one({
        "prefix": prefix, "action": "add", "by": admin.get("email", ""),
        "source": "manual", "device": dev.get("name", ""),
        "ok": not (isinstance(result, dict) and result.get("error")),
        "detail": str(result)[:300], "at": _now(),
    })
    return result


@router.delete("/admin/mikrotik/blackhole/{route_id}")
async def mikrotik_blackhole_remove(route_id: str, admin=Depends(get_current_admin),
                                    device_id: str | None = None):
    db = await _get_db()
    dev = await _get_mikrotik_device(db, device_id)
    result = await _run_mikrotik(db, device_id, "blackhole_remove", route_id)
    prefix = (result or {}).get("prefix") if isinstance(result, dict) else ""
    await db.blackhole_log.insert_one({
        "prefix": prefix or route_id, "action": "remove", "by": admin.get("email", ""),
        "source": "manual", "device": dev.get("name", ""),
        "ok": not (isinstance(result, dict) and result.get("error")),
        "detail": str(result)[:300], "at": _now(),
    })
    return result


@router.get("/admin/noc/blackhole-log")
async def noc_blackhole_log(q: Optional[str] = None, limit: int = 100,
                            admin=Depends(require_roles("admin", "support"))):
    """Riwayat announce/remove blackhole (auto + manual) dengan pencarian prefix/aktor."""
    db = await _get_db()
    limit = max(1, min(limit, 500))
    query = {}
    if q:
        rx = {"$regex": re.escape(q.strip()), "$options": "i"}
        query = {"$or": [{"prefix": rx}, {"by": rx}, {"device": rx}]}
    docs = await db.blackhole_log.find(query).sort("at", -1).to_list(limit)
    return [{
        "id": str(d["_id"]),
        "prefix": d.get("prefix", ""),
        "action": d.get("action", "add"),
        "by": d.get("by", ""),
        "source": d.get("source", "manual"),
        "device": d.get("device", ""),
        "ok": d.get("ok", True),
        "at": d.get("at", ""),
    } for d in docs]


@router.get("/admin/noc/netflow/sankey")
async def noc_netflow_sankey(device_id: Optional[str] = None, limit: int = 12,
                             admin=Depends(require_roles("admin", "support"))):
    """Data agregat arus trafik (torch MikroTik live) untuk Diagram Sankey:
    flows = [{src, dst, gbps}] top-N berdasarkan rate."""
    db = await _get_db()
    limit = max(3, min(limit, 50))
    devices = ([await _get_mikrotik_device(db, device_id)] if device_id
               else await db.mikrotik_devices.find({}).to_list(50))
    agg: dict = {}
    sampled = 0
    for d in devices:
        if not d:
            continue
        iface = d.get("main_interface") or d.get("interface") or "ether1"
        try:
            import asyncio as _a
            client = iv2.MikrotikClient(d)
            res = await _a.get_event_loop().run_in_executor(
                None, lambda c=client, i=iface: c.torch(interface=i, duration=2))
        except Exception:
            continue
        if not res.get("ok"):
            continue
        sampled += 1
        for f in res.get("rows", []):
            src = (f.get("src_address") or "").split("/")[0]
            dst = (f.get("dst_address") or "").split("/")[0]
            if not src or not dst or src == dst:
                continue
            agg[(src, dst)] = agg.get((src, dst), 0) + f.get("rx_rate", 0) + f.get("tx_rate", 0)
    flows = sorted(({"src": k[0], "dst": k[1], "gbps": round(v / 1e9, 3)}
                    for k, v in agg.items() if v > 0),
                   key=lambda x: x["gbps"], reverse=True)[:limit]
    return {"live": sampled > 0, "devices_sampled": sampled,
            "flows": flows, "sampled_at": _now()}


# ---------- Backup ----------
@router.get("/admin/mikrotik/backups")
async def mikrotik_backups_list(admin=Depends(require_roles("admin", "support")), device_id: str | None = None):
    db = await _get_db()
    return await _run_mikrotik(db, device_id, "backup_list")


@router.post("/admin/mikrotik/backups")
async def mikrotik_backups_create(payload: dict, admin=Depends(get_current_admin)):
    db = await _get_db()
    return await _run_mikrotik(db, payload.get("device_id"),
                               "backup_create", name=payload.get("name"))


@router.delete("/admin/mikrotik/backups/{filename}")
async def mikrotik_backups_delete(filename: str, admin=Depends(get_current_admin),
                                  device_id: str | None = None):
    db = await _get_db()
    return await _run_mikrotik(db, device_id, "backup_delete", filename)


# ---------- Reboot ----------
@router.post("/admin/mikrotik/reboot")
async def mikrotik_reboot(payload: dict, admin=Depends(get_current_admin)):
    db = await _get_db()
    confirm = (payload.get("confirm") or "").strip().upper()
    if confirm != "REBOOT":
        raise HTTPException(status_code=400, detail="Confirm by sending {confirm: 'REBOOT'}")
    return await _run_mikrotik(db, payload.get("device_id"), "reboot")


# ---------------- NOC: DDoS threshold rules (CRUD) ----------------
def _serialize_threshold_rule(d: dict) -> dict:
    return {
        "id": str(d["_id"]),
        "name": d.get("name", ""),
        "metric": d.get("metric", "pps"),
        "threshold": d.get("threshold", 0),
        "window_s": d.get("window_s", 60),
        "action": d.get("action", "alert"),
        "enabled": d.get("enabled", True),
        "created_at": _iso(d.get("created_at", "")),
    }


@router.get("/admin/noc/threshold-rules")
async def noc_threshold_rules_list(admin=Depends(require_roles("admin", "support"))):
    db = await _get_db()
    docs = await db.ddos_threshold_rules.find({}).sort("created_at", -1).to_list(200)
    return [_serialize_threshold_rule(d) for d in docs]


@router.post("/admin/noc/threshold-rules")
async def noc_threshold_rules_create(payload: m.ThresholdRuleIn, request: Request,
                                     admin=Depends(require_roles("admin", "support"))):
    db = await _get_db()
    doc = payload.model_dump()
    doc["created_at"] = _now()
    r = await db.ddos_threshold_rules.insert_one(doc)
    doc["_id"] = r.inserted_id
    await log_audit(db, actor=admin, action="noc.threshold_rule_created", category="noc",
                    target_type="threshold_rule", target_id=str(r.inserted_id),
                    target_label=payload.name, metadata=payload.model_dump(), request=request)
    return _serialize_threshold_rule(doc)


@router.put("/admin/noc/threshold-rules/{rid}")
async def noc_threshold_rules_update(rid: str, payload: m.ThresholdRuleIn, request: Request,
                                     admin=Depends(require_roles("admin", "support"))):
    db = await _get_db()
    upd = payload.model_dump()
    res = await db.ddos_threshold_rules.update_one({"_id": _oid(rid)}, {"$set": upd})
    if not res.matched_count:
        raise HTTPException(status_code=404, detail="Rule not found")
    d = await db.ddos_threshold_rules.find_one({"_id": _oid(rid)})
    await log_audit(db, actor=admin, action="noc.threshold_rule_updated", category="noc",
                    target_type="threshold_rule", target_id=rid,
                    target_label=payload.name, metadata=upd, request=request)
    return _serialize_threshold_rule(d)


@router.delete("/admin/noc/threshold-rules/{rid}")
async def noc_threshold_rules_delete(rid: str, request: Request, admin=Depends(require_roles("admin", "support"))):
    db = await _get_db()
    d = await db.ddos_threshold_rules.find_one({"_id": _oid(rid)})
    r = await db.ddos_threshold_rules.delete_one({"_id": _oid(rid)})
    if d:
        await log_audit(db, actor=admin, action="noc.threshold_rule_deleted", category="noc",
                        target_type="threshold_rule", target_id=rid,
                        target_label=d.get("name", ""), request=request)
    return {"deleted": r.deleted_count}


@router.post("/admin/noc/ddos/run-detect")
async def noc_ddos_run_detect(admin=Depends(require_roles("admin", "support"))):
    """Jalankan evaluasi threshold + deteksi insiden DDoS sekarang (manual trigger)."""
    db = await _get_db()
    from portal import emails as _em
    return await _em.run_ddos_detection_sweep(db)


def _serialize_ddos_incident(d: dict) -> dict:
    return {
        "id": str(d["_id"]),
        "target": d.get("target", ""),
        "attack_type": d.get("attack_type", ""),
        "pps": d.get("pps", 0),
        "bps": d.get("bps", 0),
        "severity": d.get("severity", "medium"),
        "status": d.get("status", "active"),
        "action": d.get("action", "alert"),
        "rule_id": d.get("rule_id"),
        "rule_name": d.get("rule_name", ""),
        "device": d.get("device", ""),
        "started_at": d.get("started_at", ""),
        "ended_at": d.get("ended_at"),
        "notified": d.get("notified", []),
    }


@router.get("/admin/noc/ddos/incidents")
async def noc_ddos_incidents(status: Optional[str] = None, limit: int = 100,
                             admin=Depends(require_roles("admin", "support"))):
    db = await _get_db()
    q = {"status": status} if status else {}
    limit = max(1, min(limit, 500))
    docs = await db.ddos_incidents.find(q).sort("started_at", -1).to_list(limit)
    return [_serialize_ddos_incident(d) for d in docs]


@router.put("/admin/noc/ddos/incidents/{iid}/status")
async def noc_ddos_incident_status(iid: str, payload: m.DDoSIncidentStatusIn, request: Request,
                                   admin=Depends(require_roles("admin", "support"))):
    db = await _get_db()
    upd = {"status": payload.status}
    if payload.status in ("resolved", "false_positive"):
        upd["ended_at"] = _now()
    res = await db.ddos_incidents.update_one({"_id": _oid(iid)}, {"$set": upd})
    if not res.matched_count:
        raise HTTPException(status_code=404, detail="Incident not found")
    d = await db.ddos_incidents.find_one({"_id": _oid(iid)})
    await log_audit(db, actor=admin, action="noc.ddos_incident_status", category="noc",
                    target_type="ddos_incident", target_id=iid,
                    target_label=d.get("target", ""), metadata=upd, request=request)
    return _serialize_ddos_incident(d)


# ---------------- NOC: saluran notifikasi insiden (CRUD) + log pengiriman ----------------
def _serialize_notif_channel(d: dict) -> dict:
    return {
        "id": str(d["_id"]),
        "type": d.get("type", "email"),
        "target": d.get("target", ""),
        "events": d.get("events", []),
        "enabled": d.get("enabled", True),
        "created_at": _iso(d.get("created_at", "")),
    }


@router.get("/admin/noc/notif-channels")
async def noc_notif_channels_list(admin=Depends(require_roles("admin", "support"))):
    db = await _get_db()
    docs = await db.notif_channels.find({}).sort("created_at", -1).to_list(100)
    return [_serialize_notif_channel(d) for d in docs]


@router.post("/admin/noc/notif-channels")
async def noc_notif_channels_create(payload: m.NotifChannelIn, request: Request,
                                    admin=Depends(require_roles("admin", "support"))):
    db = await _get_db()
    doc = payload.model_dump()
    doc["created_at"] = _now()
    r = await db.notif_channels.insert_one(doc)
    doc["_id"] = r.inserted_id
    await log_audit(db, actor=admin, action="noc.notif_channel_created", category="noc",
                    target_type="notif_channel", target_id=str(r.inserted_id),
                    target_label=f"{payload.type}:{payload.target}", request=request)
    return _serialize_notif_channel(doc)


@router.put("/admin/noc/notif-channels/{cid}")
async def noc_notif_channels_update(cid: str, payload: m.NotifChannelIn, request: Request,
                                    admin=Depends(require_roles("admin", "support"))):
    db = await _get_db()
    res = await db.notif_channels.update_one({"_id": _oid(cid)}, {"$set": payload.model_dump()})
    if not res.matched_count:
        raise HTTPException(status_code=404, detail="Channel not found")
    d = await db.notif_channels.find_one({"_id": _oid(cid)})
    return _serialize_notif_channel(d)


@router.delete("/admin/noc/notif-channels/{cid}")
async def noc_notif_channels_delete(cid: str, admin=Depends(require_roles("admin", "support"))):
    db = await _get_db()
    r = await db.notif_channels.delete_one({"_id": _oid(cid)})
    return {"deleted": r.deleted_count}


@router.get("/admin/noc/ddos/notify-log")
async def noc_ddos_notify_log(limit: int = 100, admin=Depends(require_roles("admin", "support"))):
    db = await _get_db()
    limit = max(1, min(limit, 500))
    docs = await db.ddos_notify_log.find({}).sort("at", -1).to_list(limit)
    return [{
        "id": str(d["_id"]),
        "incident_id": d.get("incident_id", ""),
        "target": d.get("target", ""),
        "channel_type": d.get("channel_type", ""),
        "channel_target": d.get("channel_target", ""),
        "status": d.get("status", ""),
        "at": d.get("at", ""),
    } for d in docs]


# ============================================================
# NOC - proactive MikroTik reachability polling
# ============================================================
async def _noc_uptime_window(db, dev_ids, days: int):
    """Uptime % over the last `days` days, combining `noc_daily_uptime`
    rollups (full past days) with raw `noc_probes` for days not yet rolled
    up (today + any recent gap). Survives raw-probe retention deletion."""
    now = datetime.now(timezone.utc)
    day_from = (now - timedelta(days=days)).strftime("%Y-%m-%d")
    today = now.strftime("%Y-%m-%d")
    base: dict = {}
    if dev_ids is not None:
        base["device_id"] = {"$in": dev_ids}
    total = 0
    up = 0.0
    rolled: set = set()
    async for r in db.noc_daily_uptime.find({**base, "date": {"$gte": day_from, "$lt": today}}):
        sc = int(r.get("sample_count") or 0)
        total += sc
        up += sc * float(r.get("uptime_pct") or 0) / 100.0
        rolled.add((r.get("device_id"), r.get("date")))
    async for p in db.noc_probes.find({**base, "at": {"$gte": day_from}},
                                      {"device_id": 1, "at": 1, "ok": 1}):
        if (p.get("device_id"), (p.get("at") or "")[:10]) in rolled:
            continue
        total += 1
        up += 1 if p.get("ok") else 0
    return round(up / total * 100, 2) if total else None


@router.get("/admin/noc/devices")
async def noc_devices_list(admin=Depends(require_roles("admin", "support"))):
    """Current uptime state for every MikroTik device.

    Aggregates `noc_device_state` (last known status) so the frontend can
    render a device grid without paginating through the full event log."""
    db = await _get_db()
    devices = await db.mikrotik_devices.find({}).to_list(500)
    out = []
    for d in devices:
        state = await db.noc_device_state.find_one({"device_id": d["_id"]}) or {}
        # 24h uptime %: count up-samples / total samples in the last 24h
        since = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
        samples = await db.noc_probes.count_documents({
            "device_id": d["_id"], "at": {"$gte": since},
        })
        up_samples = await db.noc_probes.count_documents({
            "device_id": d["_id"], "at": {"$gte": since}, "ok": True,
        })
        uptime_pct = round((up_samples / samples) * 100, 2) if samples else None
        uptime_30d = await _noc_uptime_window(db, [d["_id"]], 30)
        out.append({
            "id": str(d["_id"]),
            "name": d.get("name") or "unnamed",
            "host": d.get("host") or "",
            "site": d.get("site") or "",
            "status": state.get("status") or "unknown",   # up / down / unknown
            "last_probe_at": state.get("last_probe_at"),
            "last_change_at": state.get("last_change_at"),
            "last_message": state.get("last_message") or "",
            "uptime_24h_pct": uptime_pct,
            "uptime_30d_pct": uptime_30d,
            "samples_24h": samples,
        })
    return out


@router.get("/admin/noc/events")
async def noc_events_list(admin=Depends(require_roles("admin", "support")),
                          limit: int = 200,
                          device_id: Optional[str] = None,
                          type: Optional[str] = None):
    """Chronological device_up / device_down events (newest first)."""
    db = await _get_db()
    limit = max(1, min(int(limit or 200), 500))
    query: dict = {}
    if device_id:
        try:
            query["device_id"] = ObjectId(device_id)
        except Exception:
            query["device_id"] = None
    if type:
        query["type"] = type
    cur = db.noc_events.find(query).sort("at", -1).limit(limit)
    docs = [d async for d in cur]
    return [{
        "id": str(d["_id"]),
        "device_id": str(d.get("device_id")) if d.get("device_id") else None,
        "device_name": d.get("device_name") or "",
        "device_host": d.get("device_host") or "",
        "type": d.get("type") or "",
        "message": d.get("message") or "",
        "at": d.get("at") or "",
        "email_notified": bool(d.get("email_notified")),
    } for d in docs]


@router.post("/admin/noc/run-poll")
async def noc_run_poll_now(admin=Depends(require_roles("admin", "support"))):
    """Manually trigger a single NOC probe sweep (same code the scheduler runs)."""
    db = await _get_db()
    from portal import emails as _em
    return await _em.run_noc_probe_sweep(db)


@router.post("/admin/noc/run-retention")
async def noc_run_retention_now(admin=Depends(get_current_admin)):
    """Manually trigger the daily probe rollup + retention job."""
    db = await _get_db()
    from portal import emails as _em
    return await _em.run_noc_probe_retention(db)
