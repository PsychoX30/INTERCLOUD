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

# Field kinds accepted by the builder. Derived from the HeyForm taxonomy but
# limited to what this portal can validate + render without extra storage.
#   section  - layout heading only, never stored, never validated
#   multiselect - list of choices (checkbox group)
#   radio    - single choice rendered as radios (vs `select` dropdown)
#   rating   - integer 1..max, default max=5
_FB_FIELD_TYPES = {
    "text", "email", "phone", "textarea", "number", "url",
    "date", "time", "select", "radio", "multiselect",
    "checkbox", "rating", "section",
}
# Kinds that carry no answer and are excluded from stored values + CSV columns.
_FB_LAYOUT_TYPES = {"section"}
_FB_CHOICE_TYPES = {"select", "radio", "multiselect"}
_FB_MAX_FIELDS = 60
_FB_MAX_OPTIONS = 100
_WEEKDAYS = None  # placeholder to keep module namespace stable


def _fb_coerce_choice_list(raw) -> list:
    if isinstance(raw, (list, tuple)):
        items = raw
    elif raw is None:
        items = []
    else:
        items = str(raw).split(",")
    out, seen = [], set()
    for o in items:
        s = str(o).strip()
        if not s or s.lower() in seen:
            continue
        seen.add(s.lower())
        out.append(s)
        if len(out) >= _FB_MAX_OPTIONS:
            break
    return out


def _fb_int_or_none(v):
    if v is None or v == "":
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _fb_serialize(d: dict) -> dict:
    return {
        "id": str(d["_id"]), "name": d.get("name", ""), "slug": d.get("slug", ""),
        "title": d.get("title", ""), "description": d.get("description", ""),
        "submit_label": d.get("submit_label", "Kirim"),
        "success_message": d.get("success_message", "Terima kasih, kami akan segera menghubungi Anda."),
        "fields": d.get("fields", []), "active": d.get("active", True),
        "submissions": d.get("submissions", 0),
        "status": d.get("status", "draft"),
        "version": d.get("version", 1),
        "share_id": d.get("share_id", ""),
        "closed": bool(d.get("closed")),
        "closed_message": d.get("closed_message", "Form ini sudah ditutup."),
        "submission_cap": d.get("submission_cap"),
        "expires_at": d.get("expires_at") or "",
        "created_at": _iso(d.get("created_at", "")), "updated_at": _iso(d.get("updated_at", "")),
    }


def _fb_clean_fields(fields) -> list:
    """Normalize and validate builder field definitions.

    Preserves the original contract (key/label/type/required/placeholder/
    options/order) and adds the layout + validation metadata the richer field
    kinds need: ``help``, ``min``/``max``, ``rating_max``, ``default``.
    """
    if not isinstance(fields, (list, tuple)):
        raise HTTPException(status_code=400, detail="fields harus berupa list")
    if len(fields) > _FB_MAX_FIELDS:
        raise HTTPException(status_code=400, detail=f"Maksimum {_FB_MAX_FIELDS} field per form")
    out, seen_keys = [], set()
    for i, f in enumerate(fields or []):
        if not isinstance(f, dict):
            raise HTTPException(status_code=400, detail=f"Field #{i + 1} bukan objek")
        ftype = str(f.get("type", "text")).lower()
        if ftype not in _FB_FIELD_TYPES:
            raise HTTPException(status_code=400, detail=f"Tipe field tidak dikenal: {ftype}")
        raw_key = str(f.get("key") or f.get("label") or f"field_{i + 1}")
        key = re.sub(r"[^a-z0-9_]+", "_", raw_key.lower()).strip("_")[:64]
        if not key:
            raise HTTPException(status_code=400, detail="Field key kosong")
        # Layout blocks do not store answers, so they may share a key.
        if ftype not in _FB_LAYOUT_TYPES:
            if key in seen_keys:
                raise HTTPException(status_code=400, detail=f"Key field duplikat: {key}")
            seen_keys.add(key)
        options = _fb_coerce_choice_list(f.get("options")) if ftype in _FB_CHOICE_TYPES else []
        if ftype in _FB_CHOICE_TYPES and not options:
            raise HTTPException(status_code=400,
                                detail=f"Field '{f.get('label', key)}' ({ftype}) butuh minimal 1 pilihan")
        default = f.get("default")
        if ftype == "checkbox":
            default = bool(default)
        elif ftype == "multiselect":
            dv = default if isinstance(default, list) else []
            default = [str(x) for x in dv if str(x) in options]
        elif ftype in ("select", "radio"):
            default = str(default) if default and str(default) in options else ""
        else:
            default = "" if default is None else str(default)
        out.append({
            "key": key, "label": str(f.get("label", key))[:200], "type": ftype,
            "required": bool(f.get("required")),
            "placeholder": str(f.get("placeholder", ""))[:300],
            "help": str(f.get("help", ""))[:500],
            "options": options,
            "order": _fb_int_or_none(f.get("order")) if f.get("order") is not None else i,
            "min": _fb_int_or_none(f.get("min")),
            "max": _fb_int_or_none(f.get("max")),
            "rating_max": min(10, max(3, _fb_int_or_none(f.get("rating_max")) or 5)),
            "default": default,
        })
    out.sort(key=lambda x: x.get("order") if x.get("order") is not None else 0)
    for idx, f in enumerate(out):
        f["order"] = idx
    return out

# ---------- Form v2 helpers ----------
_FB_STATUSES = {"draft", "published"}

def _fb_public_shape(d: dict) -> dict:
    """Minimal shape for public form rendering - no internal counters."""
    return {
        "id": str(d["_id"]),
        "name": d.get("name", ""),
        "slug": d.get("slug", ""),
        "share_id": d.get("share_id", ""),
        "title": d.get("title", ""),
        "description": d.get("description", ""),
        "submit_label": d.get("submit_label", "Kirim"),
        "success_message": d.get("success_message", "Terima kasih, kami akan segera menghubungi Anda."),
        "fields": d.get("fields", []),
        "active": d.get("active", True),
        "version": d.get("version", 1),
        "status": d.get("status", "draft"),
        "closed": bool(d.get("closed")),
        "closed_message": d.get("closed_message", "Form ini sudah ditutup."),
    }


def _fb_public_block_reason(d: dict) -> str:
    """Return an Indonesian reason when a published form must stop accepting.

    Empty string means the form is open. Checked on both the public config
    fetch (so the page can render the closed state) and on submit (so a client
    that cached the form cannot bypass the cap).
    """
    if d.get("closed"):
        return d.get("closed_message") or "Form ini sudah ditutup."
    cap = d.get("submission_cap")
    if cap and int(d.get("submissions", 0) or 0) >= int(cap):
        return "Kuota kiriman untuk form ini sudah terpenuhi."
    expires_at = d.get("expires_at")
    if expires_at:
        try:
            dt = datetime.fromisoformat(str(expires_at).replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) > dt:
                return "Form ini sudah melewati batas waktu pengisian."
        except (TypeError, ValueError):
            pass
    return ""

def _fb_csv_safe(v) -> str:
    """Prefix formula-injection triggers so Excel/Sheets treat as plain text."""
    if v is None:
        return ""
    if isinstance(v, (list, tuple)):
        sv = "; ".join(str(x) for x in v)
    elif isinstance(v, bool):
        sv = "Ya" if v else "Tidak"
    else:
        sv = str(v)
    if sv and sv[0] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + sv
    return sv


def _fb_validate_submission(fields: list, payload: dict) -> tuple[dict, dict]:
    """Validate one submission against the form's field definitions.

    Returns ``(values, errors)``. Layout fields (section) are skipped entirely.
    Accepted keys are derived from the definition, so unknown keys in the
    payload are silently dropped instead of being persisted.
    """
    values, errors = {}, {}
    for f in fields or []:
        ftype = f.get("type", "text")
        key = f.get("key")
        if not key or ftype in _FB_LAYOUT_TYPES:
            continue
        label = f.get("label") or key
        raw = payload.get(key)

        if ftype == "checkbox":
            val = bool(raw)
            if f.get("required") and not val:
                errors[key] = f"{label} wajib dicentang"
                continue
            values[key] = val
            continue

        if ftype == "multiselect":
            picked = raw if isinstance(raw, (list, tuple)) else ([] if raw in (None, "") else [raw])
            picked = [str(x) for x in picked]
            allowed = f.get("options") or []
            bad = [x for x in picked if x not in allowed]
            if bad:
                errors[key] = "Pilihan tidak valid"
                continue
            if f.get("required") and not picked:
                errors[key] = f"{label} wajib diisi"
                continue
            values[key] = picked
            continue

        val = ("" if raw is None else str(raw)).strip()

        if val == "":
            if f.get("required"):
                errors[key] = f"{label} wajib diisi"
            else:
                values[key] = "" if ftype != "rating" else None
            continue

        if len(val) > 5000:
            errors[key] = "Jawaban terlalu panjang (maksimum 5000 karakter)"
            continue

        if ftype == "email":
            if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]{2,}$", val):
                errors[key] = "Format email tidak valid"
                continue
        elif ftype == "phone":
            if not re.match(r"^[0-9+()\-\s]{7,20}$", val):
                errors[key] = "Format nomor telepon tidak valid"
                continue
        elif ftype == "number":
            try:
                num = float(val)
            except ValueError:
                errors[key] = "Harus berupa angka"
                continue
            if f.get("min") is not None and num < f["min"]:
                errors[key] = f"Nilai minimum {f['min']}"
                continue
            if f.get("max") is not None and num > f["max"]:
                errors[key] = f"Nilai maksimum {f['max']}"
                continue
        elif ftype == "rating":
            try:
                num = int(float(val))
            except ValueError:
                errors[key] = "Rating harus berupa angka"
                continue
            top = int(f.get("rating_max") or 5)
            if num < 1 or num > top:
                errors[key] = f"Rating harus antara 1 dan {top}"
                continue
            values[key] = num
            continue
        elif ftype == "url":
            if not re.match(r"^https?://[^\s.]+\.[^\s]+$", val, re.I):
                errors[key] = "URL harus diawali http:// atau https://"
                continue
        elif ftype == "date":
            if not re.match(r"^\d{4}-\d{2}-\d{2}$", val):
                errors[key] = "Format tanggal harus YYYY-MM-DD"
                continue
            try:
                datetime.strptime(val, "%Y-%m-%d")
            except ValueError:
                errors[key] = "Tanggal tidak valid"
                continue
        elif ftype == "time":
            if not re.match(r"^\d{2}:\d{2}(:\d{2})?$", val):
                errors[key] = "Format jam harus HH:MM"
                continue
        elif ftype in _FB_CHOICE_TYPES:
            if f.get("options") and val not in f["options"]:
                errors[key] = "Pilihan tidak valid"
                continue
        elif ftype in ("text", "textarea"):
            if f.get("max") is not None and len(val) > int(f["max"]):
                errors[key] = f"Maksimum {f['max']} karakter"
                continue
        values[key] = val
    return values, errors


def _fb_columns(doc: dict) -> list:
    """Column metadata for the submissions table, derived from the definition."""
    cols = [{"key": "__created_at", "label": "Waktu kirim", "type": "datetime"}]
    for f in doc.get("fields", []):
        if f.get("type") in _FB_LAYOUT_TYPES:
            continue
        cols.append({"key": f.get("key", ""), "label": f.get("label", f.get("key", "")),
                     "type": f.get("type", "text"), "options": f.get("options") or []})
    return cols


def _fb_row(sub: dict, doc: dict) -> dict:
    vals = sub.get("values") or {}
    cells = {"__created_at": _iso(sub.get("created_at", ""))}
    for f in doc.get("fields", []):
        if f.get("type") in _FB_LAYOUT_TYPES:
            continue
        k = f.get("key", "")
        v = vals.get(k, "")
        cells[k] = v if isinstance(v, (list, bool, int, float)) or v is None else str(v)
    return {
        "id": str(sub.get("_id", "")),
        "created_at": _iso(sub.get("created_at", "")),
        "name": sub.get("name", ""),
        "email": sub.get("email", ""),
        "phone": sub.get("phone", ""),
        "ip": sub.get("ip", ""),
        "values": cells,
    }


async def _fb_load_or_404(db, fid: str) -> dict:
    try:
        oid = _oid(fid)
    except HTTPException:
        raise HTTPException(status_code=404, detail="Form not found")
    d = await db.form_configs.find_one({"_id": oid})
    if not d:
        raise HTTPException(status_code=404, detail="Form not found")
    return d


def _csv_safe(v) -> str:
    """Backwards-compatible alias kept for test_form_csv.py."""
    return _fb_csv_safe(v)



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
        "status": "draft", "version": 1, "share_id": "",
        "closed": False, "closed_message": "Form ini sudah ditutup.",
        "submission_cap": _fb_int_or_none(payload.get("submission_cap")),
        "expires_at": str(payload.get("expires_at") or "")[:40] or None,
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
    # Only allow edits on draft; published forms require new draft
    if d.get("status") == "published":
        raise HTTPException(status_code=409, detail="Form sudah dipublikasikan. Buat draft baru untuk mengedit.")
    upd = {"updated_at": _now()}
    for k in ("name", "title", "description", "submit_label", "success_message", "closed_message"):
        if k in payload:
            upd[k] = str(payload[k])[:2000]
    if "active" in payload:
        upd["active"] = bool(payload["active"])
    if "closed" in payload:
        upd["closed"] = bool(payload["closed"])
    if "submission_cap" in payload:
        cap = _fb_int_or_none(payload.get("submission_cap"))
        upd["submission_cap"] = None if cap is None or cap <= 0 else min(cap, 1_000_000)
    if "expires_at" in payload:
        upd["expires_at"] = str(payload.get("expires_at") or "")[:40] or None
    if "fields" in payload:
        upd["fields"] = _fb_clean_fields(payload["fields"])
    await db.form_configs.update_one({"_id": d["_id"]}, {"$set": upd})
    d = await db.form_configs.find_one({"_id": d["_id"]})
    return _fb_serialize(d)

@router.put("/admin/form-builder/{fid}/publish")
async def form_builder_publish(fid: str, staff=Depends(get_current_staff)):
    """Publish draft -> published, bump version, generate share_id if first publish."""
    db = await _get_db()
    d = await db.form_configs.find_one({"_id": _oid(fid)})
    if not d:
        raise HTTPException(status_code=404, detail="Form not found")
    if d.get("status") == "published":
        raise HTTPException(status_code=409, detail="Form sudah dipublikasikan")
    new_version = d.get("version", 1) + 1
    share_id = d.get("share_id") or secrets.token_urlsafe(24)
    await db.form_configs.update_one(
        {"_id": d["_id"]},
        {"$set": {"status": "published", "version": new_version, "share_id": share_id, "updated_at": _now()}}
    )
    d = await db.form_configs.find_one({"_id": d["_id"]})
    return _fb_serialize(d)


@router.put("/admin/form-builder/{fid}/draft")
async def form_builder_new_draft(fid: str, staff=Depends(get_current_staff)):
    """Create a new draft from a published form (copy for editing)."""
    db = await _get_db()
    d = await db.form_configs.find_one({"_id": _oid(fid)})
    if not d:
        raise HTTPException(status_code=404, detail="Form not found")
    if d.get("status") != "published":
        raise HTTPException(status_code=400, detail="Hanya form published yang bisa dibuat draft baru")
    new_version = d.get("version", 1) + 1
    await db.form_configs.update_one(
        {"_id": d["_id"]},
        {"$set": {"status": "draft", "version": new_version, "updated_at": _now()}}
    )
    d = await db.form_configs.find_one({"_id": d["_id"]})
    return _fb_serialize(d)


@router.delete("/admin/form-builder/{fid}")
async def form_builder_delete(fid: str, staff=Depends(get_current_staff)):
    db = await _get_db()
    oid = _oid(fid)
    d = await db.form_configs.find_one({"_id": oid})
    if not d:
        raise HTTPException(status_code=404, detail="Form not found")
    # Cascade: orphaned submissions would otherwise stay in the collection
    # forever and keep inflating the /submissions index.
    removed = await db.form_submissions.delete_many({"form_id": oid})
    await db.form_configs.delete_one({"_id": oid})
    return {"ok": True, "submissions_deleted": removed.deleted_count}


@router.put("/admin/form-builder/{fid}/close")
async def form_builder_toggle_close(fid: str, payload: dict = None, staff=Depends(get_current_staff)):
    """Open/close a published form and adjust its submission cap.

    Closing keeps the data (unlike delete) and flips the public endpoint to a
    friendly ``closed`` response, matching how Google Forms stops accepting
    answers without discarding responses.
    """
    db = await _get_db()
    d = await _fb_load_or_404(db, fid)
    payload = payload or {}
    upd = {"updated_at": _now()}
    if "closed" in payload:
        upd["closed"] = bool(payload["closed"])
    elif not any(k in payload for k in ("submission_cap", "expires_at", "closed_message")):
        # Bare call = pure toggle. A call that only adjusts the cap/expiry must
        # not silently close a form the operator still wants open.
        upd["closed"] = not bool(d.get("closed"))
    if "submission_cap" in payload:
        cap = _fb_int_or_none(payload.get("submission_cap"))
        upd["submission_cap"] = None if cap is None or cap <= 0 else min(cap, 1_000_000)
    if "expires_at" in payload:
        raw = payload.get("expires_at")
        upd["expires_at"] = None if not raw else str(raw)[:40]
    if "closed_message" in payload:
        upd["closed_message"] = str(payload["closed_message"])[:1000]
    await db.form_configs.update_one({"_id": d["_id"]}, {"$set": upd})
    d = await db.form_configs.find_one({"_id": d["_id"]})
    return _fb_serialize(d)


@router.get("/admin/form-builder/{fid}/detail")
async def form_builder_detail(fid: str, staff=Depends(get_current_staff)):
    """Single form incl. share URL + live submission stats for the detail page."""
    db = await _get_db()
    d = await _fb_load_or_404(db, fid)
    total = await db.form_submissions.count_documents({"form_id": d["_id"]})
    with_email = await db.form_submissions.count_documents(
        {"form_id": d["_id"], "email": {"$nin": ["", None]}})
    last = await db.form_submissions.find_one({"form_id": d["_id"]},
                                              sort=[("created_at", -1)])
    out = _fb_serialize(d)
    out["stats"] = {
        "total": total,
        "with_email": with_email,
        "without_email": max(0, total - with_email),
        "last_submission_at": _iso(last.get("created_at", "")) if last else "",
        "cap": d.get("submission_cap"),
        "closed": bool(d.get("closed")),
        "expires_at": d.get("expires_at") or "",
    }
    return out


@router.get("/portal-public/forms/{identifier}")
async def public_form_config(identifier: str):
    """Konfigurasi form publik - accepts slug OR share_id. Only serves published."""
    db = await _get_db()
    # Try slug first, then share_id
    d = await db.form_configs.find_one({"slug": identifier, "active": True, "status": "published"})
    if not d:
        d = await db.form_configs.find_one({"share_id": identifier, "active": True, "status": "published"})
    if not d:
        raise HTTPException(status_code=404, detail="Form tidak ditemukan atau nonaktif")
    out = _fb_public_shape(d)
    # Closed/expired/capped forms still render, but the renderer must not show
    # an input the server will reject.
    out["closed_reason"] = _fb_public_block_reason(d)
    return out


@router.post("/portal-public/forms/{identifier}/submit")
async def public_form_submit(identifier: str, payload: dict, request: Request):
    """Terima kiriman form dinamis: validasi server-side per field, simpan sebagai lead + CRM prospect."""
    db = await _get_db()
    d = await db.form_configs.find_one({"slug": identifier, "active": True, "status": "published"})
    if not d:
        d = await db.form_configs.find_one({"share_id": identifier, "active": True, "status": "published"})
    if not d:
        raise HTTPException(status_code=404, detail="Form tidak ditemukan atau nonaktif")
    block = _fb_public_block_reason(d)
    if block:
        raise HTTPException(status_code=410, detail=block)
    remote_ip = request.client.host if request.client else None
    await iv2.enforce_recaptcha(db, payload.get("recaptcha_token"), "lead", remote_ip)
    values, errors = _fb_validate_submission(d.get("fields", []), payload)
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
    # ``slug`` used to be read here without ever being bound - every submit
    # raised NameError and returned 500. Bind it from the form document that
    # was already resolved above.
    slug = d.get("slug", "")
    lead = {
        "name": name, "email": email, "phone": str(values.get("phone", "")),
        "company": str(values.get("company", "")), "need": d.get("name", ""),
        "message": str(values.get("message", "")), "source": f"form:{slug}",
        "form_slug": slug, "form_values": values, "status": "new",
        "crm_id": crm_id, "ip": remote_ip, "created_at": _now(),
    }
    r = await db.leads.insert_one(lead)
    # Also store in form_submissions so every form has its own queryable dataset.
    # Request metadata is best-effort: headers are optional so the route stays
    # callable from tests and internal callers without a full Starlette Request.
    _hdrs = getattr(request, "headers", None) or {}
    await db.form_submissions.insert_one({
        "form_id": d["_id"], "form_slug": slug, "form_name": d.get("name", ""),
        "form_version": d.get("version", 1), "values": values,
        "email": email, "name": name, "phone": str(values.get("phone", "")),
        "company": str(values.get("company", "")), "ip": remote_ip,
        "user_agent": str(_hdrs.get("user-agent") or "")[:400],
        "referer": str(_hdrs.get("referer") or "")[:500],
        "lead_id": r.inserted_id, "crm_id": crm_id,
        "created_at": _now(),
    })
    await db.form_configs.update_one({"_id": d["_id"]}, {"$inc": {"submissions": 1}})
    return {"ok": True, "lead_id": str(r.inserted_id),
            "message": d.get("success_message", "Terima kasih!")}


@router.get("/admin/form-builder/{fid}/submissions")
async def form_builder_submissions(fid: str, skip: int = 0, limit: int = 25,
                                   q: Optional[str] = None, status: Optional[str] = None,
                                   staff=Depends(get_current_staff)):
    """Paged submissions for one form, shaped as table columns + rows.

    ``q`` does a case-insensitive substring match across the stored identity
    fields and every string answer, so the table is searchable without a
    per-form index.
    """
    db = await _get_db()
    d = await _fb_load_or_404(db, fid)
    skip, limit = _pagination_params(skip, limit)

    query = {"form_id": d["_id"]}
    if status == "with_email":
        query["email"] = {"$nin": ["", None]}
    elif status == "without_email":
        query["email"] = {"$in": ["", None]}
    if q and str(q).strip():
        needle = re.escape(str(q).strip()[:100])
        rx = {"$regex": needle, "$options": "i"}
        ors = [{"name": rx}, {"email": rx}, {"phone": rx}, {"company": rx}, {"ip": rx}]
        for f in d.get("fields", []):
            if f.get("type") in _FB_LAYOUT_TYPES:
                continue
            ors.append({f"values.{f.get('key', '')}": rx})
        query["$or"] = ors

    total = await db.form_submissions.count_documents(query)
    cursor = db.form_submissions.find(query).sort("created_at", -1)
    cursor = cursor.skip(skip)
    if limit:
        cursor = cursor.limit(limit)
    docs = await cursor.to_list(limit or 1000)
    return {
        "form": {"id": str(d["_id"]), "name": d.get("name", ""), "slug": d.get("slug", ""),
                 "status": d.get("status", "draft"), "version": d.get("version", 1)},
        "columns": _fb_columns(d),
        "rows": [_fb_row(s, d) for s in docs],
        "total": total, "skip": skip,
        "limit": 0 if limit is None else limit,
    }


@router.delete("/admin/form-builder/{fid}/submissions/{sid}")
async def form_builder_delete_submission(fid: str, sid: str, staff=Depends(get_current_staff)):
    """Delete one submission (spam cleanup) and resync the form counter."""
    db = await _get_db()
    d = await _fb_load_or_404(db, fid)
    try:
        soid = _oid(sid)
    except HTTPException:
        raise HTTPException(status_code=404, detail="Submission not found")
    r = await db.form_submissions.delete_one({"_id": soid, "form_id": d["_id"]})
    if not r.deleted_count:
        raise HTTPException(status_code=404, detail="Submission not found")
    remaining = await db.form_submissions.count_documents({"form_id": d["_id"]})
    await db.form_configs.update_one({"_id": d["_id"]}, {"$set": {"submissions": remaining}})
    return {"ok": True, "submissions": remaining}


@router.get("/admin/leads")
async def admin_list_leads(status: Optional[str] = None, staff=Depends(get_current_staff)):
    _deny_creative(staff)
    db = await _get_db()
    q = {"status": status} if status else {}
    docs = await db.leads.find(q).sort("created_at", -1).to_list(1000)
    return [_serialize_lead(d) for d in docs]

@router.get("/admin/form-builder/{fid}/export")
async def form_builder_export(fid: str, status: Optional[str] = None,
                              q: Optional[str] = None, staff=Depends(get_current_staff)):
    """Export form submissions as CSV with formula-injection protection.

    Columns mirror the form definition exactly (layout blocks excluded), so the
    CSV, the on-screen table and the public form never drift apart.
    """
    from fastapi.responses import StreamingResponse
    import csv
    import io

    db = await _get_db()
    d = await _fb_load_or_404(db, fid)

    query = {"form_id": d["_id"]}
    if status == "with_email":
        query["email"] = {"$nin": ["", None]}
    elif status == "without_email":
        query["email"] = {"$in": ["", None]}
    if q and str(q).strip():
        needle = re.escape(str(q).strip()[:100])
        rx = {"$regex": needle, "$options": "i"}
        ors = [{"name": rx}, {"email": rx}, {"phone": rx}, {"company": rx}, {"ip": rx}]
        for f in d.get("fields", []):
            if f.get("type") in _FB_LAYOUT_TYPES:
                continue
            ors.append({f"values.{f.get('key', '')}": rx})
        query["$or"] = ors

    cursor = db.form_submissions.find(query).sort("created_at", -1)

    # Fixed identity columns + one column per answerable field.
    headers = ["submitted_at", "name", "email", "phone", "ip"]
    flds = [f for f in d.get("fields", []) if f.get("type") not in _FB_LAYOUT_TYPES]
    headers += [f.get("label", f.get("key", "")) for f in flds]

    async def generate():
        output = io.StringIO()
        writer = csv.writer(output)
        # BOM keeps Excel from mangling UTF-8 (Indonesian names/accents).
        yield "\ufeff"
        writer.writerow([_fb_csv_safe(h) for h in headers])
        yield output.getvalue()
        output.seek(0)
        output.truncate(0)

        async for sub in cursor:
            vals = sub.get("values") or {}
            row = [
                _fb_csv_safe(sub.get("created_at", "")),
                _fb_csv_safe(sub.get("name", "")),
                _fb_csv_safe(sub.get("email", "")),
                _fb_csv_safe(sub.get("phone", "")),
                _fb_csv_safe(sub.get("ip", "")),
            ]
            for f in flds:
                row.append(_fb_csv_safe(vals.get(f.get("key", ""), "")))
            writer.writerow(row)
            yield output.getvalue()
            output.seek(0)
            output.truncate(0)

    filename = f"form-{d.get('slug', 'export')}-v{d.get('version', 1)}.csv"
    return StreamingResponse(
        generate(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )


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
