"""Catalog: categories, products, add-ons, public leads and form builder.

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
from .shared import _get_db, _iso, _now, _oid, _pagination_params, _pagination_response  # noqa: E402
from .tickets import _deny_creative  # noqa: E402

router = APIRouter()


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
        "provision": d.get("provision") or {},
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
    {"slug": "other",        "label": "Other",        "icon": "Boxes",       "sort_order": 999},
]

# System categories are permanent. Their slugs carry provisioning behaviour in
# the backend (see provision.py: cat in ("vps","cloud"), cat in ("hosting",),
# cat in ("dedicated","colocation","interconnect","firewall","lease")). They
# must NOT be deletable or re-slugged from the admin portal - doing so would
# silently break auto-provisioning for every product in that category. Removal
# is only possible in source code, never via the admin UI/API.
SYSTEM_CATEGORY_SLUGS = {
    "cloud", "vps", "hosting", "dedicated", "colocation",
    "firewall", "interconnect", "lease",
}


async def _ensure_default_categories(db):
    # Retire the legacy catalog-only domain category. Domain registration is
    # handled by the dedicated RDASH flow, not catalog product provisioning.
    # Keep it if data still references it so no product is orphaned.
    if not await db.products.count_documents({"category": "domain"}):
        await db.categories.delete_one({"slug": "domain"})
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
        "system": d["slug"] in SYSTEM_CATEGORY_SLUGS,
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
    # System categories protect their slug. The slug is the behaviour key for
    # provisioning; changing it would break every product in the category.
    old_slug = current["slug"]
    if old_slug in SYSTEM_CATEGORY_SLUGS and slug != old_slug:
        raise HTTPException(
            status_code=400,
            detail=f"Category '{old_slug}' is a permanent system category. Its slug cannot be changed through the admin portal.",
        )
    # If slug changed, cascade-update all products (only possible for non-system)
    if slug != old_slug:
        if await db.categories.find_one({"slug": slug, "_id": {"$ne": _oid(cid)}}):
            raise HTTPException(status_code=409, detail=f"Category '{slug}' already exists")
        await db.products.update_many({"category": old_slug}, {"$set": {"category": slug}})
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
    if d["slug"] in SYSTEM_CATEGORY_SLUGS:
        raise HTTPException(
            status_code=400,
            detail=f"Category '{d['slug']}' is a permanent system category and cannot be deleted through the admin portal.",
        )
    if await db.products.count_documents({"category": d["slug"]}) > 0:
        raise HTTPException(status_code=400, detail="Cannot delete: products still use this category. Reassign them first.")
    r = await db.categories.delete_one({"_id": _oid(cid)})
    return {"deleted": r.deleted_count}


@router.get("/admin/products")
async def admin_list_products(
    admin=Depends(require_roles("admin", "support")),
    skip: int = 0, limit: int = 50, sort: str = "created_at",
    order: str = "desc", q: Optional[str] = None,
    paginate: bool = False, is_addon: Optional[bool] = None,
):
    db = await _get_db()
    query = {}
    if q:
        query["$or"] = [
            {"name": {"$regex": q, "$options": "i"}},
            {"description": {"$regex": q, "$options": "i"}},
        ]
    if is_addon is not None:
        query["is_addon"] = is_addon
    allowed = {"created_at", "name", "sort_order", "category", "price_monthly"}
    sort_field = sort if sort in allowed else "created_at"
    direction = 1 if order.lower() == "asc" else -1
    if not paginate:
        docs = await db.products.find(query).sort(sort_field, direction).to_list(500)
        return [_serialize_product(d) for d in docs]
    skip_n, limit_n = _pagination_params(skip, limit)
    total = await db.products.count_documents(query)
    cursor = db.products.find(query).sort(sort_field, direction).skip(skip_n)
    if limit_n is not None:
        cursor = cursor.limit(limit_n)
    docs = await cursor.to_list(limit_n or 500)
    return _pagination_response([_serialize_product(d) for d in docs], total, skip_n, limit_n, True)


@router.get("/portal-public/products")
async def public_products():
    """Products list - public catalog used by client order flow."""
    db = (await _get_db())
    docs = await db.products.find({"is_active": True, "is_addon": {"$ne": True}}).sort([("sort_order", 1), ("category", 1)]).to_list(500)
    return [_serialize_product(d) for d in docs]


@router.get("/portal-public/addons")
async def public_addons(product_id: Optional[str] = None):
    """Add-on products - used by client Order flow to attach to a base product.
    Dengan ?product_id= hasil difilter sesuai kompatibilitas add-on (applies_to)."""
    db = (await _get_db())
    docs = await db.products.find({"is_active": True, "is_addon": True}).sort([("sort_order", 1), ("name", 1)]).to_list(500)
    rows = [_serialize_product(d) for d in docs]
    if product_id:
        prod = await db.products.find_one({"_id": _oid(product_id)})
        if not prod:
            raise HTTPException(status_code=404, detail="Product not found")
        cat = prod.get("category", "")

        def _compatible(a: dict) -> bool:
            pids = a.get("applies_to_product_ids") or []
            cats = a.get("applies_to_categories") or []
            if not pids and not cats:
                return True
            return product_id in pids or cat in cats

        rows = [a for a in rows if _compatible(a)]
    return rows


def _serialize_lead(d: dict) -> dict:
    return {
        "id": str(d["_id"]),
        "name": d.get("name", ""),
        "email": d.get("email", ""),
        "phone": d.get("phone", ""),
        "company": d.get("company", ""),
        "need": d.get("need", ""),
        "message": d.get("message", ""),
        "source": d.get("source", "landing"),
        "status": d.get("status", "new"),
        "crm_id": str(d["crm_id"]) if d.get("crm_id") else None,
        "created_at": _iso(d.get("created_at", "")),
    }


@router.post("/portal-public/leads")
async def public_submit_lead(payload: m.LeadIn, request: Request):
    """Terima lead dari form landing page (publik). reCAPTCHA v3 diverifikasi bila aktif,
    lead disimpan dan otomatis disinkronkan ke CRM sebagai prospect."""
    db = await _get_db()
    remote_ip = request.client.host if request.client else None
    await iv2.enforce_recaptcha(db, payload.recaptcha_token, "lead", remote_ip)
    email = payload.email.lower()
    ten_min_ago = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
    dup = await db.leads.find_one({"email": email, "created_at": {"$gte": ten_min_ago}})
    if dup:
        return {"ok": True, "lead_id": str(dup["_id"]), "duplicate": True}
    # Sinkron CRM: upsert prospect berdasarkan email
    crm = await db.crm_customers.find_one({"email": email})
    if crm:
        crm_id = crm["_id"]
    else:
        r = await db.crm_customers.insert_one({
            "name": payload.name, "email": email, "phone": payload.phone,
            "company": payload.company, "position": "", "industry": "",
            "status": "prospect",
            "notes": f"Lead dari landing page ({payload.need or 'umum'})",
            "created_at": _now(), "updated_at": _now(),
        })
        crm_id = r.inserted_id
    doc = {
        "name": payload.name,
        "email": email,
        "phone": payload.phone,
        "company": payload.company,
        "need": payload.need,
        "message": payload.message,
        "source": payload.source or "landing",
        "status": "new",
        "crm_id": crm_id,
        "ip": remote_ip,
        "created_at": _now(),
    }
    r = await db.leads.insert_one(doc)
    # Auto follow-up: buat tugas follow-up H+1 agar lead cepat dihubungi
    try:
        due = (datetime.now(timezone.utc) + timedelta(days=1)).date().isoformat()
        await db.followups.insert_one({
            "customer_id": crm_id, "customer_name": payload.name,
            "task": f"Follow up lead baru: {payload.name} ({payload.need or 'umum'})",
            "channel": "whatsapp", "due_date": due, "done": False,
            "owner": "auto", "created_at": _now(),
        })
    except Exception:
        pass
    return {"ok": True, "lead_id": str(r.inserted_id), "duplicate": False}


# ---------- Lead Form Builder ----------

_FB_FIELD_TYPES = {"text", "email", "phone", "textarea", "select", "checkbox", "number"}


def _fb_serialize(d: dict) -> dict:
    return {
        "id": str(d["_id"]), "name": d.get("name", ""), "slug": d.get("slug", ""),
        "title": d.get("title", ""), "description": d.get("description", ""),
        "submit_label": d.get("submit_label", "Kirim"),
        "success_message": d.get("success_message", "Terima kasih, kami akan segera menghubungi Anda."),
        "fields": d.get("fields", []), "active": d.get("active", True),
        "submissions": d.get("submissions", 0),
        "created_at": _iso(d.get("created_at", "")), "updated_at": _iso(d.get("updated_at", "")),
    }


def _fb_clean_fields(fields) -> list:
    out = []
    for i, f in enumerate(fields or []):
        ftype = str(f.get("type", "text")).lower()
        if ftype not in _FB_FIELD_TYPES:
            raise HTTPException(status_code=400, detail=f"Tipe field tidak dikenal: {ftype}")
        key = re.sub(r"[^a-z0-9_]+", "_", str(f.get("key") or f.get("label", f"field_{i}")).lower()).strip("_")
        if not key:
            raise HTTPException(status_code=400, detail="Field key kosong")
        out.append({
            "key": key, "label": str(f.get("label", key)), "type": ftype,
            "required": bool(f.get("required")), "placeholder": str(f.get("placeholder", "")),
            "options": [str(o) for o in (f.get("options") or [])],
            "order": int(f.get("order", i)),
        })
    out.sort(key=lambda x: x["order"])
    return out


@router.get("/admin/form-builder")
async def form_builder_list(staff=Depends(get_current_staff)):
    db = await _get_db()
    docs = await db.form_configs.find({}).sort("created_at", -1).to_list(100)
    return [_fb_serialize(d) for d in docs]


@router.post("/admin/form-builder")
async def form_builder_create(payload: dict, staff=Depends(get_current_staff)):
    db = await _get_db()
    name = str(payload.get("name", "")).strip()
    if not name:
        raise HTTPException(status_code=400, detail="Nama form wajib diisi")
    slug = re.sub(r"[^a-z0-9-]+", "-", str(payload.get("slug") or name).lower()).strip("-")
    if await db.form_configs.find_one({"slug": slug}):
        raise HTTPException(status_code=409, detail=f"Slug '{slug}' sudah dipakai")
    doc = {
        "name": name, "slug": slug,
        "title": payload.get("title", name), "description": payload.get("description", ""),
        "submit_label": payload.get("submit_label", "Kirim"),
        "success_message": payload.get("success_message", "Terima kasih, kami akan segera menghubungi Anda."),
        "fields": _fb_clean_fields(payload.get("fields") or [
            {"key": "name", "label": "Nama lengkap", "type": "text", "required": True},
            {"key": "email", "label": "Email", "type": "email", "required": True},
            {"key": "phone", "label": "No. WhatsApp", "type": "phone", "required": False},
            {"key": "message", "label": "Pesan", "type": "textarea", "required": False},
        ]),
        "active": bool(payload.get("active", True)), "submissions": 0,
        "created_at": _now(), "updated_at": _now(),
    }
    r = await db.form_configs.insert_one(doc)
    doc["_id"] = r.inserted_id
    return _fb_serialize(doc)


@router.put("/admin/form-builder/{fid}")
async def form_builder_update(fid: str, payload: dict, staff=Depends(get_current_staff)):
    db = await _get_db()
    d = await db.form_configs.find_one({"_id": _oid(fid)})
    if not d:
        raise HTTPException(status_code=404, detail="Form not found")
    upd = {"updated_at": _now()}
    for k in ("name", "title", "description", "submit_label", "success_message"):
        if k in payload:
            upd[k] = str(payload[k])
    if "active" in payload:
        upd["active"] = bool(payload["active"])
    if "fields" in payload:
        upd["fields"] = _fb_clean_fields(payload["fields"])
    await db.form_configs.update_one({"_id": d["_id"]}, {"$set": upd})
    d = await db.form_configs.find_one({"_id": d["_id"]})
    return _fb_serialize(d)


@router.delete("/admin/form-builder/{fid}")
async def form_builder_delete(fid: str, staff=Depends(get_current_staff)):
    db = await _get_db()
    await db.form_configs.delete_one({"_id": _oid(fid)})
    return {"ok": True}


@router.get("/portal-public/forms/{slug}")
async def public_form_config(slug: str):
    """Konfigurasi form publik untuk dirender di landing page."""
    db = await _get_db()
    d = await db.form_configs.find_one({"slug": slug, "active": True})
    if not d:
        raise HTTPException(status_code=404, detail="Form tidak ditemukan atau nonaktif")
    out = _fb_serialize(d)
    out.pop("submissions", None)
    return out


@router.post("/portal-public/forms/{slug}/submit")
async def public_form_submit(slug: str, payload: dict, request: Request):
    """Terima kiriman form dinamis: validasi server-side per field, simpan sebagai lead + CRM prospect."""
    db = await _get_db()
    d = await db.form_configs.find_one({"slug": slug, "active": True})
    if not d:
        raise HTTPException(status_code=404, detail="Form tidak ditemukan atau nonaktif")
    remote_ip = request.client.host if request.client else None
    await iv2.enforce_recaptcha(db, payload.get("recaptcha_token"), "lead", remote_ip)
    values, errors = {}, {}
    for f in d.get("fields", []):
        raw = payload.get(f["key"])
        val = ("" if raw is None else str(raw)).strip() if f["type"] != "checkbox" else bool(raw)
        if f["required"] and (val == "" or val is False):
            errors[f["key"]] = f"{f['label']} wajib diisi"
            continue
        if val == "" or val is None:
            values[f["key"]] = val
            continue
        if f["type"] == "email" and not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", str(val)):
            errors[f["key"]] = "Format email tidak valid"
        elif f["type"] == "phone" and not re.match(r"^[0-9+()\-\s]{7,20}$", str(val)):
            errors[f["key"]] = "Format nomor telepon tidak valid"
        elif f["type"] == "number":
            try:
                float(val)
            except ValueError:
                errors[f["key"]] = "Harus berupa angka"
        elif f["type"] == "select" and f.get("options") and val not in f["options"]:
            errors[f["key"]] = "Pilihan tidak valid"
        values[f["key"]] = val
    if errors:
        raise HTTPException(status_code=422, detail={"errors": errors})
    email = str(values.get("email", "")).lower()
    name = str(values.get("name") or values.get("nama") or email or "Anonim")
    crm_id = None
    if email:
        crm = await db.crm_customers.find_one({"email": email})
        if crm:
            crm_id = crm["_id"]
        else:
            r = await db.crm_customers.insert_one({
                "name": name, "email": email, "phone": str(values.get("phone", "")),
                "company": str(values.get("company", "")), "position": "", "industry": "",
                "status": "prospect", "notes": f"Lead dari form '{d.get('name','')}'",
                "created_at": _now(), "updated_at": _now(),
            })
            crm_id = r.inserted_id
    lead = {
        "name": name, "email": email, "phone": str(values.get("phone", "")),
        "company": str(values.get("company", "")), "need": d.get("name", ""),
        "message": str(values.get("message", "")), "source": f"form:{slug}",
        "form_slug": slug, "form_values": values, "status": "new",
        "crm_id": crm_id, "ip": remote_ip, "created_at": _now(),
    }
    r = await db.leads.insert_one(lead)
    await db.form_configs.update_one({"_id": d["_id"]}, {"$inc": {"submissions": 1}})
    return {"ok": True, "lead_id": str(r.inserted_id),
            "message": d.get("success_message", "Terima kasih!")}


@router.get("/admin/leads")
async def admin_list_leads(status: Optional[str] = None, staff=Depends(get_current_staff)):
    _deny_creative(staff)
    db = await _get_db()
    q = {"status": status} if status else {}
    docs = await db.leads.find(q).sort("created_at", -1).to_list(1000)
    return [_serialize_lead(d) for d in docs]


@router.put("/admin/leads/{lid}/status")
async def admin_update_lead_status(lid: str, payload: m.LeadStatusIn, staff=Depends(get_current_staff)):
    _deny_creative(staff)
    db = await _get_db()
    await db.leads.update_one({"_id": _oid(lid)}, {"$set": {"status": payload.status}})
    d = await db.leads.find_one({"_id": _oid(lid)})
    if not d:
        raise HTTPException(status_code=404, detail="Lead not found")
    return _serialize_lead(d)


@router.post("/admin/products", response_model=m.ProductOut)
async def admin_create_product(payload: m.ProductIn, admin=Depends(require_roles("admin", "support"))):
    db = await _get_db()
    doc = payload.model_dump()
    doc["created_at"] = _now()
    r = await db.products.insert_one(doc)
    doc["_id"] = r.inserted_id
    return _serialize_product(doc)


@router.put("/admin/products/{pid}", response_model=m.ProductOut)
async def admin_update_product(pid: str, payload: m.ProductIn, admin=Depends(require_roles("admin", "support"))):
    db = await _get_db()
    await db.products.update_one({"_id": _oid(pid)}, {"$set": payload.model_dump()})
    d = await db.products.find_one({"_id": _oid(pid)})
    if not d:
        raise HTTPException(status_code=404, detail="Product not found")
    return _serialize_product(d)


@router.delete("/admin/products/{pid}")
async def admin_delete_product(pid: str, admin=Depends(require_roles("admin", "support"))):
    db = await _get_db()
    r = await db.products.delete_one({"_id": _oid(pid)})
    return {"deleted": r.deleted_count}
