"""DCIM/IPAM: sites, racks, prefixes, IP addresses.

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
from .provision import _allocate_ip_from_pool  # noqa: E402
from .shared import _get_db, _now, _oid  # noqa: E402

router = APIRouter()


async def _recompute_prefix_usage(db, prefix_id) -> int:
    """Usage = jumlah record dcim_ips yang menunjuk ke prefix ini. Update field
    `usage` agar konsisten dengan alokasi nyata (dan auto-calculate, bukan input
    manual). Dipanggil di setiap titik mutasi IP."""
    count = await db.dcim_ips.count_documents({"prefix_id": prefix_id})
    await db.dcim_prefixes.update_one({"_id": prefix_id}, {"$set": {"usage": count}})
    return count


@router.post("/admin/dcim/prefixes/{pid}/allocate")
async def dcim_prefix_allocate(pid: str, payload: dict, staff=Depends(get_current_staff)):
    db = await _get_db()
    p = await db.dcim_prefixes.find_one({"_id": _oid(pid)})
    if not p:
        raise HTTPException(status_code=404, detail="Prefix not found")
    ip = await _allocate_ip_from_pool(db, p, hostname=payload.get("hostname", ""),
                                      customer=payload.get("customer", ""),
                                      description=payload.get("description", ""))
    if not ip:
        raise HTTPException(status_code=409, detail="Tidak ada IP bebas tersisa di prefix ini")
    return {"ok": True, "address": ip, "prefix": p.get("prefix", "")}


@router.get("/admin/dcim/prefixes/{pid}/utilization")
async def dcim_prefix_utilization(pid: str, staff=Depends(get_current_staff)):
    db = await _get_db()
    p = await db.dcim_prefixes.find_one({"_id": _oid(pid)})
    if not p:
        raise HTTPException(status_code=404, detail="Prefix not found")
    allocated = await _recompute_prefix_usage(db, p["_id"])
    capacity = int(p.get("capacity", 0)) or 1
    usage = allocated
    return {"prefix": p.get("prefix", ""), "capacity": capacity, "usage": usage,
            "allocated_records": allocated,
            "utilization_pct": round(min(100.0, usage / capacity * 100), 2)}


@router.get("/admin/dcim/racks")
async def dcim_racks(staff=Depends(get_current_staff)):
    db = await _get_db()
    docs = await db.dcim_racks.find({}).sort("name", 1).to_list(500)
    if not docs:
        # First-load seed for demo
        seed = [
            {"name": "Rack B12", "site": "Cyber 1 - Metta (Lantai 5)", "u_size": 42,
             "occupancy": [{"u_top": 40, "u_bot": 40, "label": "Patch Panel", "customer": ""},
                            {"u_top": 39, "u_bot": 39, "label": "sw-tor-1", "customer": "internal"},
                            {"u_top": 38, "u_bot": 38, "label": "sw-tor-2", "customer": "internal"},
                            {"u_top": 36, "u_bot": 34, "label": "3U Server", "customer": "PT Contoh Digital"}],
             "power_draw_w": 2450, "power_cap_w": 6000},
            {"name": "Rack A05", "site": "Cyber 1 - Omni (Lantai 2)", "u_size": 42,
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
            {"prefix": "103.28.14.0/24", "usage": 148, "capacity": 256, "vlan": "vlan-100", "site": "Cyber 1 - Metta", "family": 4},
            {"prefix": "103.28.15.0/24", "usage": 22, "capacity": 256, "vlan": "vlan-110", "site": "Cyber 1 - Omni", "family": 4},
            {"prefix": "2401:a900:1234::/48", "usage": 3, "capacity": 65536, "vlan": "vlan-100", "site": "Cyber 1 - Metta", "family": 6},
            {"prefix": "10.10.0.0/16", "usage": 1284, "capacity": 65534, "vlan": "mgmt", "site": "Internal", "family": 4},
        ]
        for s in seed:
            await db.dcim_prefixes.insert_one({**s, "created_at": _now()})
        docs = await db.dcim_prefixes.find({}).to_list(500)
    out = []
    for d in docs:
        usage = await _recompute_prefix_usage(db, d["_id"])
        out.append({"id": str(d["_id"]), "usage": usage,
                    **{k: v for k, v in d.items() if k not in ("_id", "usage")}})
    return out


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
    # `usage` tidak lagi bisa di-override manual: selalu dihitung dari record
    # dcim_ips. Payload yang membawa `usage` diabaikan.
    upd = {k: v for k, v in payload.items() if k in {"prefix", "capacity", "vlan", "site", "family", "description", "gateway", "reserved", "vps_provision"}}
    for k in ("capacity", "family"):
        if k in upd:
            upd[k] = int(upd[k] or 0)
    await db.dcim_prefixes.update_one({"_id": _oid(pid)}, {"$set": upd})
    d = await db.dcim_prefixes.find_one({"_id": _oid(pid)})
    if not d:
        raise HTTPException(status_code=404, detail="Not found")
    usage = await _recompute_prefix_usage(db, d["_id"])
    return {"id": str(d["_id"]), "usage": usage,
            **{k: v for k, v in d.items() if k not in ("_id", "usage")}}


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
    if doc.get("prefix_id"):
        await _recompute_prefix_usage(db, doc["prefix_id"])
    doc["_id"] = r.inserted_id
    return {"id": str(doc["_id"]), "prefix_id": str(doc["prefix_id"]) if doc.get("prefix_id") else None,
            **{k: v for k, v in doc.items() if k not in ("_id", "prefix_id")}}


@router.put("/admin/dcim/ips/{ipid}")
async def dcim_ip_update(ipid: str, payload: dict, staff=Depends(get_current_staff)):
    db = await _get_db()
    before = await db.dcim_ips.find_one({"_id": _oid(ipid)})
    if not before:
        raise HTTPException(status_code=404, detail="Not found")
    upd = {k: v for k, v in payload.items() if k in {"address", "status", "role", "hostname", "customer", "description"}}
    if "prefix_id" in payload:
        upd["prefix_id"] = _oid(payload["prefix_id"]) if payload["prefix_id"] else None
    await db.dcim_ips.update_one({"_id": _oid(ipid)}, {"$set": upd})
    d = await db.dcim_ips.find_one({"_id": _oid(ipid)})
    for prefix_id in {before.get("prefix_id"), d.get("prefix_id")}:
        if prefix_id:
            await _recompute_prefix_usage(db, prefix_id)
    return {"id": str(d["_id"]), "prefix_id": str(d.get("prefix_id", "")) if d.get("prefix_id") else None,
            **{k: v for k, v in d.items() if k not in ("_id", "prefix_id")}}


@router.delete("/admin/dcim/ips/{ipid}")
async def dcim_ip_delete(ipid: str, staff=Depends(get_current_staff)):
    db = await _get_db()
    before = await db.dcim_ips.find_one({"_id": _oid(ipid)})
    r = await db.dcim_ips.delete_one({"_id": _oid(ipid)})
    if before and before.get("prefix_id"):
        await _recompute_prefix_usage(db, before["prefix_id"])
    return {"deleted": r.deleted_count}


# Sites
@router.get("/admin/dcim/sites")
async def dcim_sites(staff=Depends(get_current_staff)):
    db = await _get_db()
    docs = await db.dcim_sites.find({}).sort("name", 1).to_list(500)
    if not docs:
        for s in [
            {"name": "Cyber 1 - Metta Lantai 5", "code": "JKT-METTA-5F", "address": "Cyber 1 Building, Jakarta"},
            {"name": "Cyber 1 - Omni Lantai 2", "code": "JKT-OMNI-2F", "address": "Cyber 1 Building, Jakarta"},
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
