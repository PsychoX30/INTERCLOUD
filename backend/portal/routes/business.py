"""Business ops: CRM, projects, content planner, follow-ups, documents, media library, content calendar.

Split from the former monolithic routes.py - behavior preserved 1:1.
"""
import os
import asyncio
import logging
import secrets
import re
import base64
import html as _html
import io
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
from .shared import (_get_db, _iso, _now, _oid, _sales_scope_filter, _sales_visible_crm_ids,
                     _pagination_params, _pagination_response)  # noqa: E402
from .tickets import _deny_creative  # noqa: E402

router = APIRouter()


# ============================================================
# BUSINESS - CRM, Projects, Content Planner, Follow-ups, Documents
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
        "assigned_to": str(d["assigned_to"]) if d.get("assigned_to") else None,
        "assigned_at": _iso(d.get("assigned_at", "")),
        "assignment_expires_at": _iso(d.get("assignment_expires_at", "")),
        "source": d.get("source", ""),
        "created_at": _iso(d.get("created_at", "")),
        "updated_at": _iso(d.get("updated_at", "")),
    }


def _staff_oid(staff: dict):
    """Extract staff ObjectId from either _id (test fixture) or id (real auth).

    Real JWT auth (auth.py line 95) pops _id and creates id string.
    Test fixtures use _id directly. This helper handles both.
    """
    if "_id" in staff:
        return ObjectId(str(staff["_id"]))
    if "id" in staff:
        return ObjectId(str(staff["id"]))
    return None


def _crm_sales_scope_filter(staff: dict) -> dict:
    """Mongo filter restricting CRM visibility for sales.

    Sales can see:
    - clients assigned to them (user_id in assigned_client_ids)
    - the shared lead pool: status prospect/partnership (unclaimed)
    - prospects they currently own (status='assigned', assigned_to=staff id)

    Returns {} for non-sales (no restriction). This is deliberately separate
    from the strict _sales_scope_filter used by billing/orders/tickets.
    """
    if staff.get("role") != "sales":
        return {}
    clauses = []
    assigned = [ObjectId(x) for x in (staff.get("assigned_client_ids") or [])]
    if assigned:
        clauses.append({"user_id": {"$in": assigned}})
    clauses.append({"status": {"$in": ["prospect", "partnership"]}})
    staff_id = _staff_oid(staff)
    if staff_id:
        clauses.append({"assigned_to": staff_id})
    if not clauses:
        return {"_id": None}  # matches nothing
    return {"$or": clauses}



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
async def crm_list(staff=Depends(get_current_staff),
                   skip: int = 0, limit: int = 50, sort: str = "updated_at",
                   order: str = "desc", q: Optional[str] = None,
                   status: Optional[str] = None,
                   paginate: Optional[bool] = None):
    """Server-side pagination + q-search + status filter for CRM.
    Default response stays bare array."""
    _deny_creative(staff)
    db = await _get_db()
    query = _crm_sales_scope_filter(staff)
    if status and status != "all":
        query["status"] = status
    if q:
        query["$or"] = [
            {field: {"$regex": q.strip(), "$options": "i"}}
            for field in ("name", "email", "phone", "company")
        ]
    sort_field = sort if sort in {
        "name", "email", "company", "status", "created_at", "updated_at"
    } else "updated_at"
    direction = 1 if order.lower() == "asc" else -1
    skip_n, limit_n = _pagination_params(skip, limit)
    cursor = db.crm_customers.find(query).sort(sort_field, direction)
    total = 0
    if bool(paginate):
        total = await db.crm_customers.count_documents(query)
        cursor = cursor.skip(skip_n).limit(limit_n if limit_n is not None else 500)
        docs = await cursor.to_list(None)
    else:
        docs = await cursor.to_list(2000)
    # Collect user_ids for enrichment
    uids = [d.get("user_id") for d in docs if d.get("user_id")]
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
    if bool(paginate):
        return _pagination_response(out, total, skip_n, limit_n, True)
    return out


@router.post("/admin/crm")
async def crm_create(payload: dict, staff=Depends(get_current_staff)):
    """Create a CRM row.

    Sales may create:
    - prospects (no user_id, shared pool)
    - CRM rows linked to one of their assigned clients
    """
    db = await _get_db()
    _deny_creative(staff)
    user_id = payload.get("user_id")
    if staff.get("role") == "sales" and user_id:
        assigned = {str(client_id) for client_id in (staff.get("assigned_client_ids") or [])}
        if str(user_id) not in assigned:
            raise HTTPException(status_code=403, detail="CRM client is not assigned to you")
        client = await db.users.find_one({"_id": _oid(str(user_id)), "role": "client"})
        if not client:
            raise HTTPException(status_code=403, detail="CRM target must be an assigned client")

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
    if user_id:
        doc["user_id"] = _oid(str(user_id))
    r = await db.crm_customers.insert_one(doc)
    doc["_id"] = r.inserted_id
    return _serialize_crm(doc)


async def _assert_sales_can_touch_crm(db, staff: dict, cid: str) -> dict:
    """Load a CRM row and 403 if `staff` is a sales user who cannot access it.

    Sales can touch:
    - prospects/partnerships in the shared pool
    - CRM rows linked to their assigned clients
    - prospects currently assigned to them (status='assigned', assigned_to=their id)
    """
    _deny_creative(staff)
    d = await db.crm_customers.find_one({"_id": _oid(cid)})
    if not d:
        raise HTTPException(status_code=404, detail="Not found")
    if staff.get("role") == "sales":
        status = d.get("status", "prospect")
        assigned = {str(x) for x in (staff.get("assigned_client_ids") or [])}
        staff_id = _staff_oid(staff)
        assigned_to = d.get("assigned_to")
        is_shared = status in ("prospect", "partnership")
        is_own_client = (d.get("user_id") and str(d["user_id"]) in assigned)
        is_own_assignment = (
            assigned_to is not None
            and staff_id is not None
            and str(assigned_to) == str(staff_id)
        )
        if not (is_shared or is_own_client or is_own_assignment):
            raise HTTPException(status_code=403, detail="Not your client")
    return d


@router.put("/admin/crm/{cid}")
async def crm_update(cid: str, payload: dict, staff=Depends(get_current_staff)):
    db = await _get_db()
    await _assert_sales_can_touch_crm(db, staff, cid)
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
    await _assert_sales_can_touch_crm(db, staff, cid)
    r = await db.crm_customers.delete_one({"_id": _oid(cid)})
    return {"deleted": r.deleted_count}


# ---------- CRM import/export XLSX ----------
from fastapi import UploadFile as _UploadFile, File as _File  # noqa: E402

_CRM_XLSX_HEADERS = ["Nama", "Nomor Telp", "E-Mail", "Perusahaan", "Jabatan",
                     "Segmen Industri", "Status"]
_CRM_STATUS_EXPORT = {"prospect": "PROSPECT", "partnership": "POSSIBLE PARTNERSHIP",
                      "existing": "EXISTING CLIENT", "ex_client": "EX CLIENT"}


def _crm_status_import(v) -> str:
    s = re.sub(r"[^a-z]+", " ", str(v or "").lower()).strip()
    if not s:
        return ""
    if "partner" in s:
        return "partnership"
    if s.startswith("ex ") or s.startswith("ex") and "exist" not in s:
        return "ex_client"
    if "exist" in s or s in ("client", "customer", "active"):
        return "existing"
    return "prospect"


def _cell_str(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v).strip()


@router.get("/admin/crm/search")
async def crm_search(staff=Depends(get_current_staff),
                    q: Optional[str] = None, limit: int = 20):
    """Lightweight CRM search for autocomplete widgets.

    Returns rows visible to `staff` (CRM shared-pool scope). Search matches
    name, email, phone, and company case-insensitively. Always returns a list.
    """
    _deny_creative(staff)
    db = await _get_db()
    query = _crm_sales_scope_filter(staff)
    if q and q.strip():
        query["$or"] = [
            {field: {"$regex": q.strip(), "$options": "i"}}
            for field in ("name", "email", "phone", "company")
        ]
    limit_n = max(1, min(int(limit or 20), 100))
    docs = await db.crm_customers.find(query).sort("updated_at", -1).to_list(limit_n)
    out = []
    for d in docs:
        s = _serialize_crm(d)
        out.append({
            "id": s["id"],
            "name": s["name"],
            "email": s["email"],
            "phone": s["phone"],
            "company": s["company"],
            "status": s["status"],
            "assigned_to": s["assigned_to"],
        })
    return out


async def _crm_export_queryset(db, staff: dict) -> list:
    """Rows visible to `staff` for CRM export, using the CRM shared-pool scope."""
    q = _crm_sales_scope_filter(staff)
    return await db.crm_customers.find(q).sort("name", 1).to_list(20000)


@router.get("/admin/crm/export.xlsx")
async def crm_export_xlsx(staff=Depends(get_current_staff)):
    """Export Customer DB ke .xlsx dengan format template Database Marketing
    (Nama, Nomor Telp, E-Mail, Perusahaan, Jabatan, Segmen Industri, Status)."""
    _deny_creative(staff)
    db = await _get_db()
    docs = await _crm_export_queryset(db, staff)

    import io
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment
    from openpyxl.utils import get_column_letter
    wb = Workbook()
    ws = wb.active
    ws.title = "Database Marketing"
    header_fill = PatternFill("solid", fgColor="1E7145")
    status_style = {"prospect": ("9DC3E6", "000000"), "partnership": ("FFD966", "000000"),
                    "existing": ("A9D08E", "000000"), "ex_client": ("FF0000", "FFFFFF")}
    for col, h in enumerate(_CRM_XLSX_HEADERS, start=1):
        c = ws.cell(row=1, column=col, value=h)
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = header_fill
        c.alignment = Alignment(horizontal="center")
    for i, w in enumerate([24, 18, 32, 36, 40, 26, 24], start=1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = "A2"
    for r, d in enumerate(docs, start=2):
        ws.cell(row=r, column=1, value=d.get("name", ""))
        ws.cell(row=r, column=2, value=d.get("phone", ""))
        ws.cell(row=r, column=3, value=d.get("email", ""))
        ws.cell(row=r, column=4, value=d.get("company", ""))
        ws.cell(row=r, column=5, value=d.get("position", ""))
        ws.cell(row=r, column=6, value=d.get("industry", ""))
        st = d.get("status", "prospect")
        c = ws.cell(row=r, column=7, value=_CRM_STATUS_EXPORT.get(st, str(st).upper()))
        fill, fg = status_style.get(st, (None, None))
        if fill:
            c.fill = PatternFill("solid", fgColor=fill)
            c.font = Font(bold=True, color=fg)
            c.alignment = Alignment(horizontal="center")
    buf = io.BytesIO()
    wb.save(buf)
    from fastapi.responses import Response
    return Response(
        content=buf.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="customer-database.xlsx"'})


@router.post("/admin/crm/import")
async def crm_import_xlsx(file: _UploadFile = _File(...), staff=Depends(get_current_staff)):
    """Import kontak dari .xlsx (format Database Marketing). Header dicocokkan
    fleksibel (Nama/Name, Nomor Telp/Phone, E-Mail, Perusahaan/Company, Jabatan,
    Segmen Industri, Status); tanpa header -> urutan kolom A-G. Upsert by email
    (fallback: nama+telepon)."""
    _deny_creative(staff)
    if staff.get("role") == "sales":
        # XLSX rows have no portal client ID, so they cannot be proven to fall
        # within a sales user's assigned-client scope.
        raise HTTPException(
            status_code=403,
            detail="Sales cannot import unscoped CRM contacts",
        )
    db = await _get_db()
    raw = await file.read()
    if len(raw) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File terlalu besar (maks 10 MB)")
    import io
    import openpyxl
    try:
        wb = openpyxl.load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
    except Exception:
        raise HTTPException(status_code=400, detail="File bukan .xlsx yang valid")
    ws = wb.active
    all_rows = []
    for row in ws.iter_rows(values_only=True):
        all_rows.append(list(row or []))
        if len(all_rows) > 20000:
            raise HTTPException(status_code=400, detail="Maksimal 20.000 baris per import")

    def _col_key(h):
        h = str(h or "").strip().lower()
        if not h:
            return None
        if "nama" in h or h == "name":
            return "name"
        if "telp" in h or "phone" in h or "telepon" in h or h in ("hp", "wa"):
            return "phone"
        if "mail" in h:
            return "email"
        if "perusahaan" in h or "company" in h:
            return "company"
        if "jabatan" in h or "position" in h or "title" in h:
            return "position"
        if "industri" in h or "industry" in h or "segmen" in h:
            return "industry"
        if "status" in h:
            return "status"
        return None

    # Cari baris header di 10 baris pertama (template punya baris judul dulu)
    col_map, start_idx = None, 0
    for i, row in enumerate(all_rows[:10]):
        keys = {}
        for ci, cell in enumerate(row):
            k = _col_key(cell)
            if k and k not in keys:
                keys[k] = ci
        if "name" in keys and ("email" in keys or "phone" in keys):
            col_map, start_idx = keys, i + 1
            break
    if col_map is None:
        # Tanpa header: pakai posisi kolom A-G sesuai template
        col_map = {"name": 0, "phone": 1, "email": 2, "company": 3,
                   "position": 4, "industry": 5, "status": 6}

    created = updated = skipped = 0
    errors = []
    for rn, row in enumerate(all_rows[start_idx:], start=start_idx + 1):
        try:
            vals = {k: _cell_str(row[ci]) if ci < len(row) else ""
                    for k, ci in col_map.items()}
            name = vals.get("name", "")
            email = vals.get("email", "").lower()
            if not name and not email:
                skipped += 1
                continue
            status = _crm_status_import(vals.get("status"))
            fields = {k: vals.get(k, "") for k in
                      ("name", "phone", "company", "position", "industry")}
            fields["email"] = email
            query = {"email": email} if email else {"name": name, "phone": vals.get("phone", "")}
            existing = await db.crm_customers.find_one(query)
            if existing:
                upd = {k: v for k, v in fields.items() if v}
                if status:
                    upd["status"] = status
                upd["updated_at"] = _now()
                await db.crm_customers.update_one({"_id": existing["_id"]}, {"$set": upd})
                updated += 1
            else:
                await db.crm_customers.insert_one({
                    **fields, "status": status or "prospect", "notes": "",
                    "source": "xlsx_import",
                    "created_at": _now(), "updated_at": _now()})
                created += 1
        except Exception as e:
            errors.append({"row": rn, "error": str(e)[:120]})
            if len(errors) >= 20:
                break
    await log_audit(db, actor=staff, action="crm.import_xlsx", category="crm",
                    target_type="crm", target_id="bulk", target_label=file.filename or "xlsx",
                    metadata={"created": created, "updated": updated, "skipped": skipped,
                              "errors": len(errors)})
    return {"ok": True, "created": created, "updated": updated,
            "skipped": skipped, "errors": errors,
            "total_rows": max(0, len(all_rows) - start_idx)}


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
async def projects_list(staff=Depends(get_current_staff),
                        skip: int = 0, limit: int = 50, sort: str = "updated_at",
                        order: str = "desc", status: Optional[str] = None,
                        paginate: Optional[bool] = None):
    """Server-side pagination + status filter for projects. Default stays bare array."""
    db = await _get_db()
    query = {"status": status} if status and status != "all" else {}
    sort_field = sort if sort in {
        "name", "customer_name", "owner", "status", "priority", "progress",
        "start_date", "target_date", "created_at", "updated_at"
    } else "updated_at"
    direction = 1 if order.lower() == "asc" else -1
    skip_n, limit_n = _pagination_params(skip, limit)
    cursor = db.projects.find(query).sort(sort_field, direction)
    total = 0
    if bool(paginate):
        total = await db.projects.count_documents(query)
        cursor = cursor.skip(skip_n).limit(limit_n if limit_n is not None else 500)
        docs = await cursor.to_list(None)
    else:
        docs = await cursor.to_list(1000)
    items = [_serialize_project(d) for d in docs]
    return _pagination_response(items, total, skip_n, limit_n, True) if bool(paginate) else items


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
async def content_list(staff=Depends(get_current_staff),
                       skip: int = 0, limit: int = 50, sort: str = "publish_date",
                       order: str = "asc", paginate: Optional[bool] = None):
    """Server-side pagination for content planner. Default stays bare array."""
    db = await _get_db()
    sort_field = sort if sort in {
        "title", "channel", "type", "status", "owner", "publish_date", "created_at"
    } else "publish_date"
    direction = 1 if order.lower() == "asc" else -1
    skip_n, limit_n = _pagination_params(skip, limit)
    cursor = db.content_plan.find({}).sort(sort_field, direction)
    total = 0
    if bool(paginate):
        total = await db.content_plan.count_documents({})
        cursor = cursor.skip(skip_n).limit(limit_n if limit_n is not None else 500)
        docs = await cursor.to_list(None)
    else:
        docs = await cursor.to_list(1000)
    items = [_serialize_content(d) for d in docs]
    return _pagination_response(items, total, skip_n, limit_n, True) if bool(paginate) else items


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
        "owner_id": str(d.get("owner_id", "")) if d.get("owner_id") else None,
        "owner_role": d.get("owner_role", ""),
        "notes": _normalize_note_threads(d.get("notes")),
        "role_tags": [t["value"] for t in _normalize_tags(d.get("role_tags")) if t["scope"] == "role"],
        "tags": _normalize_tags(d.get("tags") or d.get("role_tags")),
        "assignee_role": d.get("assignee_role", ""),
        "approvals": [_serialize_approval(a) for a in (d.get("approvals") or [])],
        "deal_action": d.get("deal_action"),
        "deal_registration_link": d.get("deal_registration_link", ""),
        "created_at": _iso(d.get("created_at", "")),
    }


async def _followup_visibility_filter(db, staff: dict) -> dict:
    """Return a Mongo filter restricting follow-ups to those the staff can see.

    Visible if:
      - staff is admin/owner (super user)
      - staff is the owner (owner_id matches)
      - any tag matches the staff (role scope or user scope)
    Returns {} for no restriction (admin/owner).
    Returns None for zero visible (e.g. sales with no matches).
    """
    role = str(staff.get("role") or "").strip().lower()
    staff_id = str(staff.get("id") or staff.get("_id") or "").strip()

    # Admin/owner see everything
    if role in {"admin", "owner"}:
        return {}

    # Build OR clauses for visibility
    or_clauses = []

    # 1) Owner match
    if staff_id:
        or_clauses.append({"owner_id": staff_id})

    # 2) Tag match: role scope. Include legacy role_tags until old documents
    # have been migrated, otherwise an existing finance-tagged task disappears.
    if role in _FOLLOWUP_ROLES:
        or_clauses.append({"tags": {"$elemMatch": {"scope": "role", "value": role}}})
        or_clauses.append({"role_tags": role})

    # 3) Tag match: user scope
    if staff_id:
        or_clauses.append({"tags": {"$elemMatch": {"scope": "user", "value": staff_id}}})

    if not or_clauses:
        # Should not happen for known roles, but safe fallback
        return {"_id": {"$in": []}}  # matches nothing

    return {"$or": or_clauses}


async def _sales_followup_filter(db, staff: dict) -> dict | None:
    """Return a Mongo filter that restricts follow-ups to CRM rows the sales
    staff can access. Returns {} for non-sales. Returns None if the caller is
    a sales user with zero visible CRM rows (endpoint should short-circuit).

    Kept for backward compatibility; new visibility logic lives in
    _followup_visibility_filter.
    """
    if staff.get("role") != "sales":
        return {}
    ids = await _sales_visible_crm_ids(db, staff)
    if not ids:
        return None
    return {"customer_id": {"$in": ids}}


async def _assert_sales_can_touch_followup(db, staff: dict, fid: str) -> dict:
    d = await db.followups.find_one({"_id": _oid(fid)})
    if not d:
        raise HTTPException(status_code=404, detail="Not found")
    role = str(staff.get("role") or "").strip().lower()
    # Admin/owner can touch everything
    if role in {"admin", "owner"}:
        return d
    # Owner can touch their own follow-up
    staff_id = str(staff.get("id") or staff.get("_id") or "").strip()
    owner_id = str(d.get("owner_id") or "").strip()
    if staff_id and owner_id and staff_id == owner_id:
        return d
    # Tagged user can touch
    tags = _normalize_tags(d.get("tags") or d.get("role_tags"))
    if _is_followup_tagged_for(staff, tags):
        return d
    # Sales scoping: backward compat with CRM visibility
    if role == "sales":
        visible = await _sales_visible_crm_ids(db, staff) or []
        cust_id = d.get("customer_id")
        if cust_id and any(str(cust_id) == str(x) for x in visible):
            return d
    raise HTTPException(status_code=403, detail="Not your follow-up")


@router.get("/admin/followups")
async def followups_list(staff=Depends(get_current_staff),
                         skip: int = 0, limit: int = 50, sort: str = "due_date",
                         order: str = "asc", done: Optional[bool] = None,
                         paginate: Optional[bool] = None):
    """Server-side pagination for follow-ups with done filter.

    Visibility: admin/owner see all; others see only their own + tagged tasks
    (role scope or user scope). Sales scoping via _sales_followup_filter is
    combined for legacy CRM visibility.
    """
    _deny_creative(staff)
    db = await _get_db()
    q = await _followup_visibility_filter(db, staff)
    if q is None:
        return []
    # For sales: add CRM-scoped follow-ups via $or so they also see follow-ups
    # on prospects they claimed even if those follow-ups weren't explicitly tagged.
    # This is a UNION of (tagged/owner) + (CRM customer in their scope).
    if str(staff.get("role") or "").lower() == "sales":
        legacy = await _sales_followup_filter(db, staff)
        if legacy is None:
            return []
        if legacy:  # non-empty dict → OR with existing query
            q = {"$or": [q, legacy]}
    if done is not None:
        q["done"] = done
    sort_field = sort if sort in {
        "customer_name", "task", "channel", "due_date", "done", "owner", "created_at"
    } else "due_date"
    direction = 1 if order.lower() == "asc" else -1
    skip_n, limit_n = _pagination_params(skip, limit)
    cursor = db.followups.find(q).sort(sort_field, direction)
    total = 0
    if bool(paginate):
        total = await db.followups.count_documents(q)
        cursor = cursor.skip(skip_n).limit(limit_n if limit_n is not None else 500)
        docs = await cursor.to_list(None)
    else:
        docs = await cursor.to_list(1000)
    items = [_serialize_followup(d) for d in docs]
    return _pagination_response(items, total, skip_n, limit_n, True) if bool(paginate) else items


@router.get("/admin/followups/taggable-staff")
async def followups_taggable_staff(staff=Depends(get_current_staff)):
    """Staff accounts grouped by role, for the follow-up tag picker.

    Returns only roles that are actually taggable on a follow-up, so the UI
    cannot offer a role that the visibility filter would never match.
    """
    _deny_creative(staff)
    db = await _get_db()
    cursor = db.users.find(
        {"role": {"$in": sorted(_FOLLOWUP_ROLES)}},
        {"_id": 1, "name": 1, "email": 1, "role": 1},
    )
    groups: dict[str, list] = {role: [] for role in sorted(_FOLLOWUP_ROLES)}
    async for u in cursor:
        role = str(u.get("role") or "").strip().lower()
        if role not in groups:
            continue
        groups[role].append({
            "id": str(u["_id"]),
            "name": u.get("name") or u.get("email") or "(tanpa nama)",
            "email": u.get("email", ""),
            "role": role,
        })
    for role in groups:
        groups[role].sort(key=lambda x: x["name"].lower())
    return {
        "roles": sorted(_FOLLOWUP_ROLES),
        "staff_by_role": groups,
    }


_PROSPECT_ASSIGNMENT_DAYS = 5

# Roles that can be tagged on / own a follow-up task.
# Aligned with STAFF_ROLES in auth.py — "noc" does not exist as a user role.
# "owner" and "ticket_only" and "creative" are excluded: owner is a super-admin
# synonym for admin, ticket_only is read-only, creative is content-scoped.
_FOLLOWUP_ROLES = {"sales", "support", "finance", "admin"}


def _clean_role_tags(value) -> list:
    """Validate a role_tags payload into a de-duplicated ordered list.

    Kept for backward-compatibility: old payloads may still send role_tags.
    New code should use the structured ``tags`` field instead.
    """
    if not isinstance(value, list):
        raise HTTPException(status_code=400, detail="role_tags harus berupa list")
    out = []
    for raw in value:
        role = str(raw or "").strip().lower()
        if role not in _FOLLOWUP_ROLES:
            raise HTTPException(status_code=400, detail=f"Invalid role tag: {raw}")
        if role not in out:
            out.append(role)
    return out


def _normalize_tags(raw, *, strict: bool = False) -> list:
    """Normalize tag storage into a list of structured tag dicts.

    Each tag: {"scope": "role"|"user", "value": str, "label": str}

    Legacy ``role_tags`` (list of role strings) is migrated to
    ``[{"scope": "role", "value": role, "label": role}]``.

    ``strict=True`` is for request payloads: an unusable tag is a client error
    and raises 400 rather than being silently dropped, so a typo'd role can
    never quietly leave a division unable to see the task. ``strict=False``
    is for reading stored documents, where an unknown tag left over from an
    older schema must not break the read path.
    """
    if raw is None:
        return []
    if not isinstance(raw, list):
        if strict:
            raise HTTPException(status_code=400, detail="tags harus berupa list")
        return []
    out = []
    seen = set()
    for entry in raw:
        scope = value = label = None
        if isinstance(entry, str):
            scope, value = "role", entry.strip().lower()
            label = value
        elif isinstance(entry, dict):
            scope = str(entry.get("scope") or "").strip().lower()
            value = str(entry.get("value") or "").strip()
            label = str(entry.get("label") or value).strip()
        else:
            if strict:
                raise HTTPException(status_code=400, detail=f"Invalid tag: {entry!r}")
            continue
        if scope not in ("role", "user") or not value:
            if strict:
                raise HTTPException(status_code=400, detail=f"Invalid tag: {entry!r}")
            continue
        if scope == "role" and value.lower() not in _FOLLOWUP_ROLES:
            if strict:
                raise HTTPException(status_code=400, detail=f"Invalid role tag: {value}")
            continue
        key = (scope, value.lower())
        if key in seen:
            continue
        seen.add(key)
        out.append({"scope": scope, "value": value, "label": label or value})
    return out


def _is_followup_tagged_for(staff: dict, tags: list) -> bool:
    """Check whether a staff member is covered by any of the given tags.

    - role scope: matches if the tag value equals the staff role
    - user scope: matches if the tag value equals the staff id
    """
    my_role = str(staff.get("role") or "").strip().lower()
    my_id = str(staff.get("id") or staff.get("_id") or "").strip()
    for tag in tags:
        scope = tag.get("scope")
        val = str(tag.get("value") or "").strip()
        if scope == "role" and val.lower() == my_role:
            return True
        if scope == "user" and val == my_id:
            return True
    return False


def _serialize_approval(a: dict) -> dict:
    """Serialize an approval sub-document for API response."""
    return {
        "id": str(a.get("id") or a.get("_id") or ""),
        "requested_by": a.get("requested_by", ""),
        "requested_by_id": str(a["requested_by_id"]) if a.get("requested_by_id") else None,
        "requested_role": a.get("requested_role", ""),
        "target_role": a.get("target_role", ""),
        "target_user_id": str(a["target_user_id"]) if a.get("target_user_id") else None,
        "message": a.get("message", ""),
        "status": a.get("status", "pending"),
        "responded_by": a.get("responded_by", ""),
        "responded_at": _iso(a.get("responded_at", "")),
        "response_note": a.get("response_note", ""),
        "created_at": _iso(a.get("created_at", "")),
    }


# ---------- Close-deal registration token ----------
import jwt as _jwt  # noqa: E402
from portal.auth import _secret as _jwt_secret, JWT_ALGORITHM as _jwt_alg  # noqa: E402

_CRM_TOKEN_TTL_DAYS = 7


def _make_crm_registration_token(crm_id: str) -> str:
    """Sign a short-lived JWT carrying the CRM row id for close-deal registration."""
    payload = {
        "crm_id": str(crm_id),
        "exp": datetime.now(timezone.utc) + timedelta(days=_CRM_TOKEN_TTL_DAYS),
        "type": "crm_register",
    }
    return _jwt.encode(payload, _jwt_secret(), algorithm=_jwt_alg)


def _verify_crm_registration_token(token: str) -> str:
    """Decode and validate a close-deal registration token.

    Returns the crm_id. Raises HTTPException(400) on invalid/expired tokens.
    """
    try:
        data = _jwt.decode(token, _jwt_secret(), algorithms=[_jwt_alg])
    except Exception:
        raise HTTPException(status_code=400, detail="Token registrasi tidak valid")
    if data.get("type") != "crm_register" or not data.get("crm_id"):
        raise HTTPException(status_code=400, detail="Token registrasi tidak valid")
    return str(data["crm_id"])


async def expire_overdue_assignments(db, now_iso: str | None = None) -> int:
    """Release expired prospect assignments back to the shared pool.

    Only rows with status='assigned' AND assignment_expires_at < now are
    touched; existing clients / shared leads are never modified. Intended to
    run as a scheduled job; returns the number of released rows.
    """
    now_value = now_iso or datetime.now(timezone.utc).isoformat()
    result = await db.crm_customers.update_many(
        {"status": "assigned", "assignment_expires_at": {"$lt": now_value}},
        {"$set": {
            "status": "prospect",
            "assigned_to": None,
            "assigned_at": None,
            "assignment_expires_at": None,
            "updated_at": now_value,
        }},
    )
    return getattr(result, "modified_count", 0)


async def sync_crm_after_registration(db, *, crm_token: str, new_user_id,
                                       reg_email: str, reg_name: str = "") -> None:
    """After a user registers with a close-deal crm_token, sync the CRM row.

    If the registered email/name matches the CRM row, the row is upgraded to
    'existing' and linked to the new user_id. If there's a mismatch (different
    person using the link), the original CRM row is left untouched — the new
    user is simply a new customer, not a silent merge.
    """
    crm_id_str = _verify_crm_registration_token(crm_token)
    crm = await db.crm_customers.find_one({"_id": _oid(crm_id_str)})
    if not crm:
        return
    crm_email = (crm.get("email") or "").lower().strip()
    crm_name = (crm.get("name") or "").strip()
    reg_email_norm = (reg_email or "").lower().strip()
    reg_name_norm = (reg_name or "").strip()
    email_match = crm_email and crm_email == reg_email_norm
    name_match = (not crm_name) or (not reg_name_norm) or crm_name == reg_name_norm
    if email_match and name_match:
        now = datetime.now(timezone.utc)
        await db.crm_customers.update_one(
            {"_id": crm["_id"]},
            {"$set": {
                "status": "existing",
                "user_id": new_user_id,
                "assigned_to": None,
                "assigned_at": None,
                "assignment_expires_at": None,
                "updated_at": now.isoformat(),
            }},
        )


async def crm_register_prefill(staff, token: str) -> dict:
    """Public endpoint: validate a crm_token and return CRM data for prefill.

    Returns {name, email, phone, company}. Raises HTTPException(400) if token
    is invalid/expired or CRM row not found.
    """
    crm_id = _verify_crm_registration_token(token)
    db = await _get_db()
    crm = await db.crm_customers.find_one({"_id": _oid(crm_id)})
    if not crm:
        raise HTTPException(status_code=400, detail="Token registrasi tidak valid")
    return {
        "name": crm.get("name", ""),
        "email": crm.get("email", ""),
        "phone": crm.get("phone", ""),
        "company": crm.get("company", ""),
    }


def _normalize_note_threads(raw) -> dict:
    """Normalize stored notes into an append-only thread per role.

    Two shapes exist on disk:
      legacy: {"sales": "free text"}          -> one synthetic legacy entry
      thread: {"sales": [{author, text, at}]} -> passed through

    Threads are append-only by design: no endpoint rewrites or deletes an
    entry, so one division can never edit another division's feedback.
    """
    out = {role: [] for role in sorted(_FOLLOWUP_ROLES)}
    if not isinstance(raw, dict):
        return out
    for raw_role, value in raw.items():
        role = str(raw_role or "").strip().lower()
        if role not in _FOLLOWUP_ROLES:
            continue
        if isinstance(value, str):
            text = value.strip()
            if text:
                out[role].append({
                    "author": "",
                    "author_role": role,
                    "text": text,
                    "at": "",
                    "legacy": True,
                })
            continue
        if isinstance(value, list):
            for entry in value:
                if not isinstance(entry, dict):
                    continue
                text = str(entry.get("text") or "").strip()
                if not text:
                    continue
                out[role].append({
                    "author": str(entry.get("author") or ""),
                    "author_role": str(entry.get("author_role") or role),
                    "text": text,
                    "at": _iso(entry.get("at", "")),
                    "legacy": bool(entry.get("legacy", False)),
                })
    return out


def _note_author_role(staff: dict) -> str:
    """Role bucket a staff member is allowed to post notes into.

    A user posts as their own role only. Nobody -- admin included -- may
    write into another division's thread, which is what the old editable
    per-role textarea allowed.
    """
    role = str(staff.get("role") or "").strip().lower()
    if role not in _FOLLOWUP_ROLES:
        raise HTTPException(
            status_code=403,
            detail=f"Role '{role}' tidak dapat menulis catatan follow-up",
        )
    return role


@router.post("/admin/followups")
async def followups_create(payload: dict, staff=Depends(get_current_staff)):
    db = await _get_db()
    _deny_creative(staff)
    cust_id = _oid(payload["customer_id"]) if payload.get("customer_id") else None
    if staff.get("role") == "sales":
        visible = await _sales_visible_crm_ids(db, staff) or []
        if not (cust_id and any(str(cust_id) == str(x) for x in visible)):
            raise HTTPException(
                status_code=403,
                detail="Follow-up harus untuk pelanggan yang dapat Anda akses",
            )
    # Atomic claim: prospect must be prospect/partnership (unclaimed) or
    # already assigned to this staff. Prevents double-claim by another sales.
    if cust_id:
        crm = await db.crm_customers.find_one({"_id": cust_id})
        if crm and crm.get("status") == "assigned":
            assigned_to = crm.get("assigned_to")
            staff_id = _staff_oid(staff)
            if staff.get("role") == "sales" and (
                not assigned_to
                or not staff_id
                or str(assigned_to) != str(staff_id)
            ):
                raise HTTPException(
                    status_code=403,
                    detail="Prospect ini sedang di-assign ke sales lain",
                )
        # Claim the prospect: only "prospect" status (not partnership) is claimable.
        # The status guard lives in the filter so two concurrent sales cannot
        # both win the claim -- the loser matches zero documents.
        if crm and crm.get("status") == "prospect":
            now_dt = datetime.now(timezone.utc)
            expires = now_dt + timedelta(days=_PROSPECT_ASSIGNMENT_DAYS)
            claimed = await db.crm_customers.update_one(
                {"_id": cust_id, "status": "prospect"},
                {"$set": {
                    "status": "assigned",
                    "assigned_to": _staff_oid(staff),
                    "assigned_at": now_dt.isoformat(),
                    "assignment_expires_at": expires.isoformat(),
                    "updated_at": now_dt.isoformat(),
                }},
            )
            if not getattr(claimed, "modified_count", 0):
                raise HTTPException(
                    status_code=403,
                    detail="Prospect ini baru saja di-assign ke sales lain",
                )
        elif crm and crm.get("status") == "assigned" and _staff_oid(staff):
            # Already assigned to this sales — renew the expiry timer
            now_dt = datetime.now(timezone.utc)
            expires = now_dt + timedelta(days=_PROSPECT_ASSIGNMENT_DAYS)
            await db.crm_customers.update_one(
                {"_id": cust_id},
                {"$set": {
                    "assigned_at": now_dt.isoformat(),
                    "assignment_expires_at": expires.isoformat(),
                    "updated_at": now_dt.isoformat(),
                }},
            )
    doc = {
        "customer_id": cust_id,
        "customer_name": payload.get("customer_name", ""),
        "task": payload.get("task", ""),
        "channel": payload.get("channel", "whatsapp"),
        "due_date": payload.get("due_date", ""),
        "done": False,
        "owner": payload.get("owner", staff.get("name", "")),
        "owner_id": str(staff.get("id") or staff.get("_id") or ""),
        "owner_role": str(staff.get("role") or "").lower(),
        "tags": _normalize_tags(payload.get("tags") or payload.get("role_tags"), strict=True),
        # Mirror role tags into the legacy field so old clients / filters that
        # still read role_tags keep working until full migration.
        "role_tags": [t["value"] for t in _normalize_tags(payload.get("tags") or payload.get("role_tags"), strict=True) if t["scope"] == "role"],
        "created_at": _now(),
    }
    r = await db.followups.insert_one(doc)
    doc["_id"] = r.inserted_id
    return _serialize_followup(doc)


@router.put("/admin/followups/{fid}")
async def followups_update(fid: str, payload: dict, staff=Depends(get_current_staff)):
    db = await _get_db()
    _deny_creative(staff)
    d = await _assert_sales_can_touch_followup(db, staff, fid)
    upd = {}
    MAPPED = {"task", "channel", "due_date", "done", "owner", "customer_name"}
    for k, v in payload.items():
        if k in MAPPED:
            upd[k] = v
        elif k == "notes":
            # Notes are append-only threads now. Rewriting them through the
            # generic update endpoint is what let one division overwrite
            # another division's feedback, so it is refused outright.
            raise HTTPException(
                status_code=400,
                detail="Catatan tidak bisa diubah lewat update. "
                       "Gunakan POST /admin/followups/{id}/notes untuk menambah catatan.",
            )
        elif k in ("tags", "role_tags"):
            # Tags gate visibility, so removing one silently hides the task from
            # a division that still owes work on it. Tags are therefore
            # append-only until the task is actually finished: either marked
            # done, or closed as a deal.
            incoming = _normalize_tags(v, strict=True)
            existing = _normalize_tags(d.get("tags") or d.get("role_tags"))
            finishing = payload.get("done") is True
            unlocked = (
                finishing
                or bool(d.get("done"))
                or d.get("deal_action") == "close_deal"
            )
            if not unlocked:
                incoming_keys = {(t["scope"], t["value"].lower()) for t in incoming}
                removed = [
                    t for t in existing
                    if (t["scope"], t["value"].lower()) not in incoming_keys
                ]
                if removed:
                    names = ", ".join(f"{t['scope']}:{t['label']}" for t in removed)
                    raise HTTPException(
                        status_code=400,
                        detail=(
                            "Tag tidak bisa dihapus sebelum task selesai "
                            f"(mark as done atau close deal). Tag terkunci: {names}"
                        ),
                    )
            upd["tags"] = incoming
            # Keep the legacy field in sync so older clients still read roles.
            upd["role_tags"] = [
                t["value"] for t in incoming if t["scope"] == "role"
            ]
        elif k == "assignee_role":
            role = str(v or "").strip().lower()
            if role not in _FOLLOWUP_ROLES:
                raise HTTPException(status_code=400, detail=f"Invalid assignee role: {v}")
            upd["assignee_role"] = role
    if not upd:
        raise HTTPException(status_code=400, detail="Tidak ada field yang valid untuk diupdate")
    await db.followups.update_one({"_id": _oid(fid)}, {"$set": upd})
    # If this follow-up has a linked CRM prospect, renew or release it.
    cust_id = d.get("customer_id")
    if cust_id:
        crm = await db.crm_customers.find_one({"_id": cust_id})
        if crm and crm.get("status") == "assigned":
            if payload.get("done") is True:
                # Release prospect back to shared pool
                now_dt = datetime.now(timezone.utc)
                await db.crm_customers.update_one(
                    {"_id": cust_id},
                    {"$set": {
                        "status": "prospect",
                        "assigned_to": None,
                        "assigned_at": None,
                        "assignment_expires_at": None,
                        "updated_at": now_dt.isoformat(),
                    }},
                )
            else:
                # Any other update renews the 5-day timer
                now_dt = datetime.now(timezone.utc)
                expires = now_dt + timedelta(days=_PROSPECT_ASSIGNMENT_DAYS)
                await db.crm_customers.update_one(
                    {"_id": cust_id},
                    {"$set": {
                        "assigned_at": now_dt.isoformat(),
                        "assignment_expires_at": expires.isoformat(),
                        "updated_at": now_dt.isoformat(),
                    }},
                )
    updated = await db.followups.find_one({"_id": _oid(fid)})
    return _serialize_followup(updated)


@router.get("/register/crm-prefill")
async def crm_register_prefill_route(token: str):
    """Public: validate a close-deal crm_token and return prefill data."""
    return await crm_register_prefill(staff=None, token=token)


@router.post("/admin/followups/{fid}/close-deal")
async def followup_close_deal(fid: str, staff=Depends(get_current_staff)):
    """Mark a follow-up as close-deal and generate a 7-day registration link."""
    db = await _get_db()
    _deny_creative(staff)
    fu = await _assert_sales_can_touch_followup(db, staff, fid)
    cust_id = fu.get("customer_id")
    if not cust_id:
        raise HTTPException(status_code=400, detail="Follow-up tidak memiliki customer CRM")
    crm = await db.crm_customers.find_one({"_id": cust_id})
    if not crm:
        raise HTTPException(status_code=404, detail="Customer CRM tidak ditemukan")
    token = _make_crm_registration_token(str(cust_id))
    frontend_base = (os.environ.get("PORTAL_FRONTEND_URL") or "https://intercloud-digital.com").rstrip("/")
    path = f"/portal/register?crm_token={quote(token)}"
    link = f"{frontend_base}{path}"
    now = _now()
    update = {
        "deal_action": "close_deal",
        "deal_registration_link": link,
        "deal_closed_at": now,
        "deal_closed_by": staff.get("name") or staff.get("email") or "staff",
        "updated_at": now,
    }
    await db.followups.update_one({"_id": _oid(fid)}, {"$set": update})
    return {**update, "crm_id": str(cust_id)}


@router.post("/admin/followups/{fid}/approval")
async def followup_approval_request(fid: str, payload: dict,
                                    staff=Depends(get_current_staff)):
    """Request an approval from another role/user. Pending request is appended."""
    db = await _get_db()
    _deny_creative(staff)
    await _assert_sales_can_touch_followup(db, staff, fid)
    target_role = str(payload.get("target_role") or "").strip().lower()
    target_user_id = payload.get("target_user_id")
    if target_role not in _FOLLOWUP_ROLES:
        raise HTTPException(status_code=400, detail=f"Invalid target role: {target_role}")
    approval = {
        "id": ObjectId(),
        "requested_by": staff.get("name") or staff.get("email") or "staff",
        "requested_by_id": _staff_oid(staff),
        "requested_role": staff.get("role", ""),
        "target_role": target_role,
        "target_user_id": _oid(target_user_id) if target_user_id else None,
        "message": payload.get("message", ""),
        "status": "pending",
        "responded_by": "",
        "responded_at": "",
        "response_note": "",
        "created_at": _now(),
    }
    await db.followups.update_one(
        {"_id": _oid(fid)},
        {"$push": {"approvals": approval}, "$set": {"updated_at": _now()}},
    )
    return _serialize_approval(approval)


@router.put("/admin/followups/{fid}/approval/{aid}")
async def followup_approval_respond(fid: str, aid: str, payload: dict,
                                    staff=Depends(get_current_staff)):
    """Accept or reject a pending approval.

    The caller must be the target role (or admin). Accepting/rejecting a
    non-pending approval is a no-op that surfaces the existing state.
    """
    db = await _get_db()
    _deny_creative(staff)
    # NOTE: no _assert_sales_can_touch_followup here. Responding to an approval
    # is authorized by being the *target* of that approval (target role or
    # target user), which is checked below. A finance/support reviewer is
    # frequently NOT tagged on the follow-up itself, so requiring touch access
    # would make it impossible for them to answer the very request addressed
    # to them.
    fu = await db.followups.find_one({"_id": _oid(fid)})
    if not fu:
        raise HTTPException(status_code=404, detail="Follow-up not found")
    approvals = fu.get("approvals") or []
    target = None
    for a in approvals:
        if str(a.get("id")) == aid:
            target = a
            break
    if not target:
        raise HTTPException(status_code=404, detail="Approval not found")
    if target.get("status") != "pending":
        raise HTTPException(status_code=400, detail="Approval sudah direspon")
    caller_role = staff.get("role", "")
    if caller_role not in ("admin",) and caller_role != target.get("target_role"):
        # Allow targeted user if specified
        target_user = target.get("target_user_id")
        if not target_user or str(target_user) != str(_staff_oid(staff) or ""):
            raise HTTPException(
                status_code=403,
                detail="Anda tidak berhak merespon approval ini",
            )
    response = str(payload.get("response") or "").lower() if isinstance(payload, dict) else ""
    if response not in ("accepted", "rejected"):
        raise HTTPException(status_code=400, detail="response harus 'accepted' atau 'rejected'")
    note = payload.get("note", "") if isinstance(payload, dict) else ""
    now = _now()
    # Update the approval in-place in the array, then persist the whole array.
    target["status"] = response
    target["responded_by"] = staff.get("name") or staff.get("email") or "staff"
    target["responded_at"] = now
    target["response_note"] = note
    await db.followups.update_one(
        {"_id": _oid(fid)},
        {"$set": {"approvals": approvals, "updated_at": now}},
    )
    return _serialize_approval(target)


@router.delete("/admin/followups/{fid}")
async def followups_delete(fid: str, staff=Depends(get_current_staff)):
    # Deletion is deliberately restricted by role, not assignment/tag ownership:
    # support must be able to remove operational follow-ups even if it is not
    # personally assigned or tagged on them.
    if staff.get("role") not in {"admin", "owner", "support"}:
        raise HTTPException(status_code=403, detail="Only admin, owner, and support can delete follow-ups")
    db = await _get_db()
    r = await db.followups.delete_one({"_id": _oid(fid)})
    return {"deleted": r.deleted_count}


@router.post("/admin/followups/{fid}/notes")
async def followup_notes_add(fid: str, payload: dict, staff=Depends(get_current_staff)):
    """Append one note to the caller's own role thread.

    This is intentionally the only way to write a follow-up note: threads
    are append-only, and the author role is always derived from the
    authenticated caller, never from the request body. That is what
    guarantees admin (or any other role) cannot edit or inject content
    into another division's thread.
    """
    db = await _get_db()
    _deny_creative(staff)
    d = await _assert_sales_can_touch_followup(db, staff, fid)
    text = str((payload or {}).get("text") or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Catatan tidak boleh kosong")
    author_role = _note_author_role(staff)
    entry = {
        "author": staff.get("name") or staff.get("email") or "staff",
        "author_role": author_role,
        "text": text,
        "at": _now(),
        "legacy": False,
    }
    threads = _normalize_note_threads(d.get("notes"))
    threads[author_role].append(entry)
    await db.followups.update_one(
        {"_id": _oid(fid)},
        {"$set": {"notes": threads, "updated_at": _now()}},
    )
    return {"notes": threads}


# ---------- Documents (metadata + file upload lokal) ----------
from pathlib import Path as _DocPath  # noqa: E402


DOCS_DIR = _DocPath(__file__).resolve().parent.parent.parent / "uploads" / "documents"
PREVIEW_DIR = DOCS_DIR / "_preview"


def _ensure_preview_dir() -> None:
    try:
        PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass


# ---------- LibreOffice Office->PDF conversion ----------
def _find_soffice() -> str:
    for cand in ("/usr/bin/soffice", "/usr/lib/libreoffice/program/soffice.bin",
                 "/usr/bin/libreoffice", "/opt/libreoffice/program/soffice"):
        if _DocPath(cand).exists():
            return cand
    import shutil as _sh
    return _sh.which("soffice") or _sh.which("libreoffice") or ""


_OFFICE_EXT = {
    "docx": ".docx", "xlsx": ".xlsx", "pptx": ".pptx",
    "odt": ".odt", "ods": ".ods", "odp": ".odp",
    "doc": ".doc", "xls": ".xls", "ppt": ".ppt", "rtf": ".rtf",
}


def _convert_office_to_pdf(src: "_DocPath", kind: str, timeout_s: int = 120) -> "bytes | None":
    """Render an Office/ODF file to PDF with LibreOffice headless.

    Returns the produced PDF bytes (read before the temp dir is cleaned up)
    or None when LibreOffice is unavailable or the conversion fails.
    Callers must degrade to the HTML renderer.
    """
    soffice = _find_soffice()
    if not soffice:
        return None
    ext = _OFFICE_EXT.get(kind)
    if not ext:
        return None
    import subprocess as _sp
    import tempfile as _tf
    try:
        with _tf.TemporaryDirectory(prefix="docprev_") as tmp:
            work = _DocPath(tmp)
            src_copy = work / ("input" + ext)
            src_copy.write_bytes(src.read_bytes())
            env = {"HOME": str(work), "PATH": "/usr/bin:/bin:/usr/local/bin",
                   "LC_ALL": "C.UTF-8", "LANG": "C.UTF-8"}
            _sp.run(
                [soffice, "--headless", "--norestore", "--invisible",
                 "--nodefault", "--nolockcheck", "--convert-to", "pdf",
                 "--outdir", str(work), str(src_copy)],
                check=False, capture_output=True, timeout=timeout_s, env=env,
            )
            produced = work / ("input.pdf")
            if produced.exists() and produced.stat().st_size > 0:
                return produced.read_bytes()  # read BEFORE temp dir cleanup
    except Exception:
        return None
    return None


def _cached_preview_pdf(doc_id: str, src: "_DocPath", src_mtime: float, kind: str) -> "_DocPath | None":
    """Return a cached converted PDF for this document, converting on miss."""
    _ensure_preview_dir()
    out = PREVIEW_DIR / f"{doc_id}.pdf"
    try:
        if out.exists() and out.stat().st_mtime >= src_mtime and out.stat().st_size > 0:
            return out
    except Exception:
        pass
    pdf_bytes = _convert_office_to_pdf(src, kind)
    if pdf_bytes is None:
        return None
    try:
        out.write_bytes(pdf_bytes)
    except Exception:
        return None
    return out


_DOC_ALLOWED_TYPES = {
    "application/pdf",
    "image/png", "image/jpeg", "image/webp", "image/gif",
    "audio/mpeg", "audio/ogg", "audio/wav", "audio/mp4",
    "video/mp4", "video/webm", "video/ogg", "video/quicktime",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.oasis.opendocument.text",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.oasis.opendocument.spreadsheet",
    "application/vnd.ms-powerpoint",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/vnd.oasis.opendocument.presentation",
    "application/zip", "application/x-zip-compressed", "text/plain", "text/csv",
}


_DOC_MAX_BYTES = 15 * 1024 * 1024  # 15 MB


def _serialize_doc(d):
    sw = d.get("share_with") or {}
    return {
        "id": str(d["_id"]),
        "title": d.get("title", ""),
        "category": d.get("category", "contract"),
        "customer_name": d.get("customer_name", ""),
        "url": d.get("url", ""),
        "notes": d.get("notes", ""),
        "filename": d.get("filename", ""),
        "size_bytes": d.get("size_bytes", 0),
        "has_file": bool(d.get("stored_name")),
        "folder": d.get("folder", ""),
        "shared": bool(d.get("shared", False)),
        "owner_id": str(d["owner_id"]) if d.get("owner_id") else None,
        "owner_name": d.get("owner_name", ""),
        "created_at": _iso(d.get("created_at", "")),
        "folder_id": str(d["folder_id"]) if d.get("folder_id") else None,
        "folder_path": d.get("folder_path", ""),
        "content_type": d.get("content_type", ""),
        "uploaded_by": d.get("uploaded_by", ""),
        "share_with": {
            "users": [str(u) for u in (sw.get("users") or [])],
            "divisions": list(sw.get("divisions") or []),
            "roles": list(sw.get("roles") or []),
        },
        "acl": d.get("acl") or [],
        "can_manage": False,  # filled by caller when staff known
    }


def _require_internal_document_access(staff: dict) -> None:
    """Compatibility hook; document authorization is evaluated per document.

    Role-wide denial would prevent a Sales/Creative user from opening a document
    explicitly shared to that user, division, or role. Endpoint-level checks use
    ``_doc_can_read`` and ``_doc_can_manage`` instead.
    """
    return None


def _assert_doc_owner_or_admin(staff: dict, doc: dict) -> None:
    """Write/delete guard.

    - Private documents: only the owner or admin.
    - Shared/common documents: admin only, because they have no individual owner.
    """
    if staff.get("role") == "admin":
        return
    if doc.get("shared"):
        raise HTTPException(status_code=403, detail="Only admin can mutate shared documents")
    owner_id = str(doc.get("owner_id")) if doc.get("owner_id") else None
    if owner_id is None:
        raise HTTPException(status_code=403, detail="Only admin can mutate shared documents")
    if str(staff.get("id")) != owner_id:
        raise HTTPException(status_code=403, detail="Not the document owner")


def _doc_can_read_legacy(staff: dict, doc: dict) -> bool:
    """DEPRECATED — superseded by _effective_perms/_doc_can_read below.
    Kept only for reference; not called."""
    return False



# ============================================================
# Permission resolver (new — ACL + inheritance)
# ============================================================
OVERRIDE_ROLES = {"admin", "owner", "support"}
PERM_LEVELS = ("read", "download", "delete", "manage")


def _staff_oid(staff: dict) -> str:
    return str(staff.get("id") or staff.get("_id") or "")


def _effective_perms(staff: dict, doc: dict, folder_chain: list[dict] | None = None) -> set[str]:
    """Return effective permission set for a staff member against a document.

    Resolution order:
    1. admin/owner/support override  → all perms (support no delete unless configured)
    2. document owner  → all perms
    3. document ACL entries matching staff.id / division / role
    4. folder ACL inheritance (if doc.inherit_folder_acl != False)
    5. legacy share_with / shared flag  → {read, download}
    6. legacy common doc (no owner) + internal role  → {read, download}
    """
    role = (staff.get("role") or "").strip().lower()
    staff_id = _staff_oid(staff)

    # 1. override roles
    if role in OVERRIDE_ROLES:
        if role == "support":
            return {"read", "download", "manage"}
        return set(PERM_LEVELS)

    # 2. owner
    owner_id = doc.get("owner_id")
    if owner_id and str(owner_id) == staff_id:
        return set(PERM_LEVELS)

    perms: set[str] = set()

    # 3. document ACL
    acl = doc.get("acl") or []
    for entry in acl:
        if entry.get("principal_type") == "user" and str(entry.get("principal_id")) == staff_id:
            perms.update(entry.get("perms") or [])
        if entry.get("principal_type") == "division" and (staff.get("division") or "").strip().lower() == str(entry.get("principal_id") or "").strip().lower():
            perms.update(entry.get("perms") or [])
        if entry.get("principal_type") == "role" and role == str(entry.get("principal_id") or "").strip().lower():
            perms.update(entry.get("perms") or [])

    # 4. folder inheritance
    if doc.get("inherit_folder_acl", True) and folder_chain:
        for folder in folder_chain:
            facl = folder.get("acl") or []
            for entry in facl:
                if entry.get("principal_type") == "user" and str(entry.get("principal_id")) == staff_id:
                    perms.update(entry.get("perms") or [])
                if entry.get("principal_type") == "division" and (staff.get("division") or "").strip().lower() == str(entry.get("principal_id") or "").strip().lower():
                    perms.update(entry.get("perms") or [])
                if entry.get("principal_type") == "role" and role == str(entry.get("principal_id") or "").strip().lower():
                    perms.update(entry.get("perms") or [])
            if not folder.get("inherit_parent_acl", True):
                break

    # 5. legacy share_with / shared
    if not perms:
        sw = doc.get("share_with") or {}
        if staff_id and staff_id in [str(u) for u in (sw.get("users") or [])]:
            perms |= {"read", "download"}
        division = (staff.get("division") or "").strip().lower()
        if division and division in [str(d).strip().lower() for d in (sw.get("divisions") or [])]:
            perms |= {"read", "download"}
        if role and role in [str(r).strip().lower() for r in (sw.get("roles") or [])]:
            perms |= {"read", "download"}
        if doc.get("shared"):
            perms |= {"read", "download"}

    # 6. legacy common doc
    if not perms and (owner_id is None or not str(owner_id)):
        if role in {"finance", "support", "ticket_only"}:
            perms |= {"read", "download"}

    return perms


def _doc_can_read(staff: dict, doc: dict) -> bool:
    """Thin wrapper: read access if 'read' in effective perms."""
    return "read" in _effective_perms(staff, doc)


def _doc_can_manage(staff: dict, doc: dict) -> bool:
    """Thin wrapper: manage access if 'manage' in effective perms."""
    return "manage" in _effective_perms(staff, doc)


def _doc_can_download(staff: dict, doc: dict) -> bool:
    return "download" in _effective_perms(staff, doc)


def _doc_can_delete(staff: dict, doc: dict) -> bool:
    return "delete" in _effective_perms(staff, doc)


def _validate_acl_no_clients(acl: list, client_ids: set) -> None:
    """Reject any ACL entry granting a client account (server-side leak guard).

    Local copy — business_overhaul.py imports from this module, so importing
    back would be circular.
    """
    for entry in acl or []:
        if entry.get("principal_type") == "user" and str(entry.get("principal_id")) in client_ids:
            raise HTTPException(status_code=400, detail="Cannot grant document access to a client account")
        if entry.get("principal_type") == "role" and str(entry.get("principal_id") or "").strip().lower() == "client":
            raise HTTPException(status_code=400, detail="Cannot grant document access to the client role")


@router.get("/admin/documents")
async def docs_list(staff=Depends(get_current_staff),
                    skip: int = 0, limit: int = 50, sort: str = "created_at",
                    order: str = "desc", q: Optional[str] = None,
                    folder_id: Optional[str] = None,
                    category: Optional[str] = None,
                    filetype: Optional[str] = None,
                    paginate: Optional[bool] = None):
    """Server-side pagination + q-search for documents. Default stays bare array.

    Visibility: shared/common documents, the caller's own private documents, plus
    documents explicitly shared with the caller's user id / division / role.
    Legacy documents (no owner_id/shared field) stay visible to every staff role
    so nothing that used to be listed disappears after this change.
    """
    _require_internal_document_access(staff)
    db = await _get_db()
    query: dict = {}
    conds: list = []
    if staff.get("role") != "admin":
        role = (staff.get("role") or "").strip().lower()
        conds.append({"$or": [
            {"shared": True},
            {"owner_id": staff.get("id")},
            {"share_with.users": staff.get("id")},
            {"share_with.divisions": (staff.get("division") or "").strip().lower()},
            {"share_with.roles": role},
            # Legacy common docs (no owner) visible only to internal staff,
            # mirroring _doc_can_read. Sales/creative are excluded here.
            *([{"owner_id": None}, {"owner_id": {"$exists": False}}]
              if role in {"finance", "support", "ticket_only"} else []),
        ]})
    if folder_id is not None:
        # "" or "root" means unfiled documents; otherwise a specific folder.
        if folder_id in ("", "root", "null"):
            conds.append({"$or": [{"folder_id": None}, {"folder_id": {"$exists": False}}]})
        else:
            conds.append({"folder_id": folder_id})
    if q:
        conds.append({"$or": [
            {field: {"$regex": re.escape(q.strip()), "$options": "i"}}
            for field in ("title", "category", "customer_name", "notes", "filename")
        ]})
    if category:
        # Exact category filter (case-insensitive, trimmed).
        conds.append({"category": {"$regex": f"^{re.escape(category.strip())}$", "$options": "i"}})
    if filetype:
        # Filetype filter matches against content_type / filename extension.
        # Values: pdf, docx, xlsx, pptx, zip, image, audio, video, other
        _ft = (filetype or "").strip().lower()
        if _ft == "pdf":
            conds.append({"$or": [
                {"content_type": {"$regex": "pdf", "$options": "i"}},
                {"filename": {"$regex": r"\.pdf$", "$options": "i"}},
            ]})
        elif _ft in ("docx", "doc"):
            conds.append({"$or": [
                {"content_type": {"$regex": "wordprocessingml|msword", "$options": "i"}},
                {"filename": {"$regex": r"\.docx?$", "$options": "i"}},
            ]})
        elif _ft in ("xlsx", "xls", "csv"):
            conds.append({"$or": [
                {"content_type": {"$regex": "spreadsheetml|ms-excel|csv", "$options": "i"}},
                {"filename": {"$regex": r"\.(xlsx?|csv)$", "$options": "i"}},
            ]})
        elif _ft in ("pptx", "ppt"):
            conds.append({"$or": [
                {"content_type": {"$regex": "presentationml|ms-powerpoint", "$options": "i"}},
                {"filename": {"$regex": r"\.pptx?$", "$options": "i"}},
            ]})
        elif _ft == "zip":
            conds.append({"$or": [
                {"content_type": {"$regex": "zip|compressed", "$options": "i"}},
                {"filename": {"$regex": r"\.zip$", "$options": "i"}},
            ]})
        elif _ft == "image":
            conds.append({"content_type": {"$regex": "^image/", "$options": "i"}})
        elif _ft == "audio":
            conds.append({"content_type": {"$regex": "^audio/", "$options": "i"}})
        elif _ft == "video":
            conds.append({"content_type": {"$regex": "^video/", "$options": "i"}})
        elif _ft == "other":
            conds.append({"$or": [
                {"content_type": {"$exists": False}},
                {"content_type": None},
                {"content_type": {"$not": {"$regex": "pdf|msword|wordprocessingml|ms-excel|spreadsheetml|csv|ms-powerpoint|presentationml|^image/|^audio/|^video/|zip|compressed", "$options": "i"}}},
            ]})
    if conds:
        query["$and"] = conds
    sort_field = sort if sort in {
        "title", "category", "customer_name", "filename", "size_bytes", "created_at"
    } else "created_at"
    direction = 1 if order.lower() == "asc" else -1
    skip_n, limit_n = _pagination_params(skip, limit)
    cursor = db.documents.find(query).sort(sort_field, direction)
    total = 0
    if bool(paginate):
        total = await db.documents.count_documents(query)
        cursor = cursor.skip(skip_n).limit(limit_n if limit_n is not None else 500)
        docs = await cursor.to_list(None)
    else:
        docs = await cursor.to_list(1000)
    items = []
    for d in docs:
        s = _serialize_doc(d)
        s["can_manage"] = _doc_can_manage(staff, d)
        items.append(s)
    return _pagination_response(items, total, skip_n, limit_n, True) if bool(paginate) else items


@router.get("/admin/documents/facets")
async def docs_facets(staff=Depends(get_current_staff)):
    """Return distinct categories and filetypes for filter dropdowns."""
    _require_internal_document_access(staff)
    db = await _get_db()
    # Only consider documents visible to this staff (reuse same visibility logic)
    query = {}
    if staff.get("role") != "admin":
        role = (staff.get("role") or "").strip().lower()
        query["$or"] = [
            {"shared": True},
            {"owner_id": staff.get("id")},
            {"share_with.users": staff.get("id")},
            {"share_with.divisions": (staff.get("division") or "").strip().lower()},
            {"share_with.roles": role},
        ]
        if role in {"finance", "support", "ticket_only"}:
            query["$or"].append({"owner_id": None})
            query["$or"].append({"owner_id": {"$exists": False}})

    # Distinct categories (non-empty, trimmed)
    cat_docs = await db.documents.find(query, {"category": 1}).to_list(10000)
    categories = sorted({
        (c.get("category") or "").strip()
        for c in cat_docs
        if c.get("category") and c["category"].strip()
    })

    # Distinct filetypes (derive from content_type / filename)
    type_docs = await db.documents.find(query, {"content_type": 1, "filename": 1}).to_list(10000)
    filetypes = set()
    for c in type_docs:
        ct = (c.get("content_type") or "").lower()
        fn = (c.get("filename") or "").lower()
        if "pdf" in ct or fn.endswith(".pdf"):
            filetypes.add("PDF")
        elif "wordprocessingml" in ct or "msword" in ct or fn.endswith(".docx") or fn.endswith(".doc"):
            filetypes.add("DOCX")
        elif "spreadsheetml" in ct or "ms-excel" in ct or "csv" in ct or fn.endswith(".xlsx") or fn.endswith(".xls") or fn.endswith(".csv"):
            filetypes.add("XLSX")
        elif "presentationml" in ct or "ms-powerpoint" in ct or fn.endswith(".pptx") or fn.endswith(".ppt"):
            filetypes.add("PPTX")
        elif "zip" in ct or "compressed" in ct or fn.endswith(".zip"):
            filetypes.add("ZIP")
        elif ct.startswith("image/"):
            filetypes.add("IMAGE")
        elif ct.startswith("audio/"):
            filetypes.add("AUDIO")
        elif ct.startswith("video/"):
            filetypes.add("VIDEO")
        elif ct:
            filetypes.add("LAINNYA")

    return {"categories": categories, "filetypes": sorted(filetypes)}


@router.post("/admin/documents")
async def docs_create(payload: dict, staff=Depends(get_current_staff)):
    _require_internal_document_access(staff)
    db = await _get_db()
    folder = (payload.get("folder") or "").strip()
    shared = bool(payload.get("shared", False))
    folder_id = payload.get("folder_id")
    folder_path = (payload.get("folder_path") or "").strip()
    share_with = payload.get("share_with") or {}
    sw_users = [str(u) for u in (share_with.get("users") or []) if u]
    sw_divisions = [str(d).strip().lower() for d in (share_with.get("divisions") or []) if d]
    sw_roles = [str(r).strip().lower() for r in (share_with.get("roles") or []) if r]
    # If folder is "shared" or shared=True, it's a common document; otherwise
    # it's private to the creator.
    if shared or folder == "shared":
        shared = True
        folder = folder or "shared"
        owner_id = None
    else:
        owner_id = staff.get("id")
        if not folder:
            folder = f"private/{staff.get('id', 'unknown')}"
    # folder_id wins over legacy string when provided (and resolvable)
    if folder_id:
        fid_oid = _oid(str(folder_id))
        if fid_oid is None:
            raise HTTPException(status_code=400, detail="Invalid folder_id")
        f = await db.document_folders.find_one({"_id": fid_oid})
        if not f:
            raise HTTPException(status_code=400, detail="Folder not found")
        folder_id = str(f["_id"])
        folder_path = f.get("path") or folder_path or f.get("name", "")
    doc = {
        "title": payload.get("title", ""),
        "category": payload.get("category", "contract"),
        "customer_name": payload.get("customer_name", ""),
        "url": payload.get("url", ""),
        "notes": payload.get("notes", ""),
        "folder": folder,
        "shared": shared,
        "owner_id": owner_id,
        "owner_name": staff.get("name") or staff.get("email", ""),
        "folder_id": folder_id,
        "folder_path": folder_path,
        "share_with": {"users": sw_users, "divisions": sw_divisions, "roles": sw_roles},
        "created_at": _now(),
    }
    r = await db.documents.insert_one(doc)
    doc["_id"] = r.inserted_id
    s = _serialize_doc(doc)
    s["can_manage"] = _doc_can_manage(staff, doc)
    return s


@router.delete("/admin/documents/{did}")
async def docs_delete(did: str, staff=Depends(get_current_staff)):
    _require_internal_document_access(staff)
    db = await _get_db()
    d = await db.documents.find_one({"_id": _oid(did)})
    if not d:
        raise HTTPException(status_code=404, detail="Document not found")
    if not _doc_can_manage(staff, d):
        raise HTTPException(status_code=403, detail="Only admin or owner can delete this document")
    if d.get("stored_name"):
        try:
            (DOCS_DIR / d["stored_name"]).unlink(missing_ok=True)
        except Exception:
            pass
    r = await db.documents.delete_one({"_id": _oid(did)})
    return {"deleted": r.deleted_count}


@router.get("/documents/file/{did}")
async def docs_file(did: str, staff=Depends(get_current_staff)):
    """Serve dokumen bisnis yang di-upload (URL ber-ObjectId, seperti media)."""
    _require_internal_document_access(staff)
    db = await _get_db()
    d = await db.documents.find_one({"_id": _oid(did)})
    if not d or not d.get("stored_name"):
        raise HTTPException(status_code=404, detail="Document not found")
    if not _doc_can_read(staff, d):
        raise HTTPException(status_code=403, detail="Dokumen ini privat")
    fp = DOCS_DIR / d["stored_name"]
    if not fp.exists():
        raise HTTPException(status_code=404, detail="File missing on disk")
    return FileResponse(fp, media_type=d.get("content_type") or "application/octet-stream",
                        filename=d.get("filename") or d["stored_name"])


# ============================================================
# Document folders — tree, create, rename, delete, auto-migrate
# ============================================================
def _serialize_folder(f: dict) -> dict:
    return {
        "id": str(f["_id"]),
        "name": f.get("name", ""),
        "parent_id": str(f["parent_id"]) if f.get("parent_id") else None,
        "owner_id": str(f["owner_id"]) if f.get("owner_id") else None,
        "owner_name": f.get("owner_name", ""),
        "division": f.get("division", ""),
        "path": f.get("path", ""),
        "is_shared_root": bool(f.get("is_shared_root", False)),
        "is_private_root": bool(f.get("is_private_root", False)),
        "created_at": _iso(f.get("created_at", "")),
    }


def _folder_visible_to(staff: dict, folder: dict) -> bool:
    """Folder visibility mirrors doc visibility: admin all; shared/division
    folders all staff; private folders owner (or users granted via share)."""
    if staff.get("role") == "admin":
        return True
    if folder.get("is_shared_root") or not folder.get("owner_id"):
        return True
    if str(folder.get("owner_id")) == str(staff.get("id")):
        return True
    division = (staff.get("division") or "").strip().lower()
    if folder.get("division") and division == str(folder.get("division")).strip().lower():
        return True
    return False


@router.get("/admin/document-folders")
async def folders_list(staff=Depends(get_current_staff)):
    """Folder tree for the caller (admin sees all incl. private roots)."""
    _require_internal_document_access(staff)
    db = await _get_db()
    folders = await db.document_folders.find({}).sort("path", 1).to_list(2000)
    visible = [f for f in folders if _folder_visible_to(staff, f)]
    by_parent: dict = {}
    for f in visible:
        by_parent.setdefault(str(f.get("parent_id")) if f.get("parent_id") else None, []).append(f)

    def build(parent_key):
        return [_serialize_folder(f) | {"children": build(str(f["_id"]))} for f in by_parent.get(parent_key, [])]

    return build(None)


@router.post("/admin/document-folders")
async def folders_create(payload: dict, staff=Depends(get_current_staff)):
    _require_internal_document_access(staff)
    db = await _get_db()
    name = (payload.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Nama folder wajib diisi")
    if "/" in name:
        raise HTTPException(status_code=400, detail="Nama folder tidak boleh mengandung '/'")
    parent_id = payload.get("parent_id")
    parent = None
    if parent_id:
        p_oid = _oid(str(parent_id))
        if p_oid is None:
            raise HTTPException(status_code=400, detail="Invalid parent_id")
        parent = await db.document_folders.find_one({"_id": p_oid})
        if not parent:
            raise HTTPException(status_code=400, detail="Parent folder not found")
        if not _folder_visible_to(staff, parent):
            raise HTTPException(status_code=403, detail="Parent folder not accessible")
    division = (payload.get("division") or "").strip().lower()
    owner_id = None
    if parent is None and division:
        # division root folder — visible to the whole division
        owner_id = None
    elif parent is not None and parent.get("owner_id"):
        owner_id = parent.get("owner_id")
        division = division or parent.get("division", "")
    elif staff.get("role") != "admin":
        # non-admin without a parent: personal folder
        owner_id = staff.get("id")
    # admins may create top-level folders owned by themselves unless a
    # division or shared root is chosen
    path = f"{parent.get('path', '').rstrip('/')}/{name}" if parent else name
    folder = {
        "name": name,
        "parent_id": parent["_id"] if parent else None,
        "owner_id": owner_id,
        "owner_name": staff.get("name") or staff.get("email", ""),
        "division": division,
        "path": path,
        "created_at": _now(),
    }
    r = await db.document_folders.insert_one(folder)
    folder["_id"] = r.inserted_id
    return _serialize_folder(folder)


@router.patch("/admin/document-folders/{fid}")
async def folders_rename(fid: str, payload: dict, staff=Depends(get_current_staff)):
    _require_internal_document_access(staff)
    db = await _get_db()
    f = await db.document_folders.find_one({"_id": _oid(fid)})
    if not f:
        raise HTTPException(status_code=404, detail="Folder not found")
    is_owner = f.get("owner_id") and str(f.get("owner_id")) == str(staff.get("id"))
    if staff.get("role") != "admin" and not is_owner:
        raise HTTPException(status_code=403, detail="Only admin or owner can rename this folder")
    name = (payload.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Nama folder wajib diisi")
    if "/" in name:
        raise HTTPException(status_code=400, detail="Nama folder tidak boleh mengandung '/'")
    old_path = f.get("path", "")
    parent_path = old_path.rsplit("/", 1)[0] if "/" in old_path else ""
    new_path = f"{parent_path}/{name}" if parent_path else name
    await db.document_folders.update_one({"_id": f["_id"]}, {"$set": {"name": name, "path": new_path}})
    # cascade path rename to descendants and documents
    async for child in db.document_folders.find({"path": {"$regex": f"^{re.escape(old_path)}/"}}):
        new_child_path = new_path + child["path"][len(old_path):]
        await db.document_folders.update_one({"_id": child["_id"]}, {"$set": {"path": new_child_path}})
    await db.documents.update_many(
        {"folder_path": {"$regex": f"^{re.escape(old_path)}(/|$)"}},
        {"$set": {"folder_path": {
            "$concat": [new_path, {"$substr": ["$folder_path", len(old_path), -1]}]
        }}},
    )
    f["name"] = name
    f["path"] = new_path
    return _serialize_folder(f)


@router.delete("/admin/document-folders/{fid}")
async def folders_delete(fid: str, staff=Depends(get_current_staff)):
    _require_internal_document_access(staff)
    db = await _get_db()
    f = await db.document_folders.find_one({"_id": _oid(fid)})
    if not f:
        raise HTTPException(status_code=404, detail="Folder not found")
    is_owner = f.get("owner_id") and str(f.get("owner_id")) == str(staff.get("id"))
    if staff.get("role") != "admin" and not is_owner:
        raise HTTPException(status_code=403, detail="Only admin or owner can delete this folder")
    if f.get("is_shared_root") or f.get("is_private_root"):
        raise HTTPException(status_code=400, detail="Root folder tidak dapat dihapus")
    docs_in_folder = await db.documents.count_documents({"folder_id": str(f["_id"])})
    subfolders = await db.document_folders.count_documents({"path": {"$regex": f"^{re.escape(f.get('path', ''))}/"}})
    if docs_in_folder > 0 or subfolders > 0:
        raise HTTPException(status_code=400, detail="Folder tidak kosong")
    await db.document_folders.delete_one({"_id": f["_id"]})
    return {"deleted": 1}


@router.post("/admin/documents/migrate-folders")
async def docs_migrate_folders(staff=Depends(get_current_admin)):
    """Auto-migrate legacy documents to folder roots. Creates:
    - a shared root folder (is_shared_root)
    - a private root folder per owner (is_private_root)
    and writes folder_id + folder_path on every document that lacks them.
    Idempotent: safe to run multiple times.
    """
    db = await _get_db()
    shared_root = await db.document_folders.find_one({"is_shared_root": True})
    if not shared_root:
        r = await db.document_folders.insert_one({
            "name": "Shared", "parent_id": None, "owner_id": None,
            "owner_name": "system", "division": "",
            "path": "Shared", "is_shared_root": True, "created_at": _now(),
        })
        shared_root = await db.document_folders.find_one({"_id": r.inserted_id})
    shared_root_id = str(shared_root["_id"])

    # group legacy docs by owner
    owners: dict = {}
    async for d in db.documents.find({"folder_id": {"$in": [None, ""]}}):
        owners.setdefault(str(d.get("owner_id") or "shared"), []).append(d)

    migrated = 0
    for owner_key, docs in owners.items():
        if owner_key == "shared":
            fid, fpath = shared_root_id, "Shared"
        else:
            pf = await db.document_folders.find_one({"is_private_root": True, "owner_id": owner_key})
            if not pf:
                uname = (docs[0].get("owner_name") or owner_key)
                r = await db.document_folders.insert_one({
                    "name": f"Private ({uname})", "parent_id": None, "owner_id": owner_key,
                    "owner_name": uname, "division": "",
                    "path": f"Private ({uname})", "is_private_root": True, "created_at": _now(),
                })
                fid = str(r.inserted_id)
            else:
                fid = str(pf["_id"])
            fpath = pf["path"] if pf else f"Private ({docs[0].get('owner_name') or owner_key})"
        for d in docs:
            await db.documents.update_one(
                {"_id": d["_id"]},
                {"$set": {"folder_id": fid, "folder_path": fpath}},
            )
            migrated += 1
    return {"migrated": migrated, "owners": len(owners), "shared_root_id": shared_root_id}


# ============================================================
# Document edit / move / share
# ============================================================
@router.patch("/admin/documents/{did}")
async def docs_update(did: str, payload: dict, staff=Depends(get_current_staff)):
    _require_internal_document_access(staff)
    db = await _get_db()
    d = await db.documents.find_one({"_id": _oid(did)})
    if not d:
        raise HTTPException(status_code=404, detail="Document not found")
    if not _doc_can_manage(staff, d):
        raise HTTPException(status_code=403, detail="Only admin or owner can edit this document")
    upd: dict = {}
    for field in ("title", "category", "customer_name", "url", "notes"):
        if field in payload:
            upd[field] = payload.get(field) or ""
    if "share_with" in payload:
        sw = payload.get("share_with") or {}
        upd["share_with"] = {
            "users": [str(u) for u in (sw.get("users") or []) if u],
            "divisions": [str(x).strip().lower() for x in (sw.get("divisions") or []) if x],
            "roles": [str(x).strip().lower() for x in (sw.get("roles") or []) if x],
        }
    if "acl" in payload:
        acl = payload.get("acl") or []
        # validate client exclusion
        client_ids = set()
        user_ids = [str(e.get("principal_id")) for e in acl if e.get("principal_type") == "user"]
        if user_ids:
            oids = [_oid(u) for u in user_ids if _oid(u)]
            async for u in db.users.find({"_id": {"$in": oids}, "role": "client"}):
                client_ids.add(str(u["_id"]))
        _validate_acl_no_clients(acl, client_ids)
        upd["acl"] = acl
    if "folder_id" in payload:
        fid = payload.get("folder_id")
        if fid in (None, "", "root"):
            upd["folder_id"] = None
            upd["folder_path"] = ""
        else:
            f_oid = _oid(str(fid))
            if f_oid is None:
                raise HTTPException(status_code=400, detail="Invalid folder_id")
            f = await db.document_folders.find_one({"_id": f_oid})
            if not f:
                raise HTTPException(status_code=400, detail="Folder not found")
            upd["folder_id"] = str(f["_id"])
            upd["folder_path"] = f.get("path", "")
    if not upd:
        raise HTTPException(status_code=400, detail="Nothing to update")
    await db.documents.update_one({"_id": d["_id"]}, {"$set": upd})
    d.update(upd)
    s = _serialize_doc(d)
    s["can_manage"] = _doc_can_manage(staff, d)
    return s


@router.post("/admin/documents/{did}/move")
async def docs_move(did: str, payload: dict, staff=Depends(get_current_staff)):
    """Move document to a folder (folder_id null/"" = unfiled)."""
    _require_internal_document_access(staff)
    db = await _get_db()
    d = await db.documents.find_one({"_id": _oid(did)})
    if not d:
        raise HTTPException(status_code=404, detail="Document not found")
    if not _doc_can_manage(staff, d):
        raise HTTPException(status_code=403, detail="Only admin or owner can move this document")
    fid = payload.get("folder_id")
    if fid in (None, ""):
        await db.documents.update_one({"_id": d["_id"]}, {"$set": {"folder_id": None, "folder_path": ""}})
        d["folder_id"], d["folder_path"] = None, ""
    else:
        f_oid = _oid(str(fid))
        if f_oid is None:
            raise HTTPException(status_code=400, detail="Invalid folder_id")
        f = await db.document_folders.find_one({"_id": f_oid})
        if not f:
            raise HTTPException(status_code=404, detail="Folder not found")
        await db.documents.update_one({"_id": d["_id"]}, {"$set": {"folder_id": str(f["_id"]), "folder_path": f.get("path", "")}})
        d["folder_id"], d["folder_path"] = str(f["_id"]), f.get("path", "")
    s = _serialize_doc(d)
    s["can_manage"] = _doc_can_manage(staff, d)
    return s


# ============================================================
# Document download + preview
# ============================================================
@router.get("/admin/documents/{did}/download")
async def docs_download(did: str, staff=Depends(get_current_staff)):
    _require_internal_document_access(staff)
    db = await _get_db()
    d = await db.documents.find_one({"_id": _oid(did)})
    if not d or not d.get("stored_name"):
        raise HTTPException(status_code=404, detail="Document not found")
    if not _doc_can_read(staff, d):
        raise HTTPException(status_code=403, detail="Dokumen ini privat")
    fp = DOCS_DIR / d["stored_name"]
    if not fp.exists():
        raise HTTPException(status_code=404, detail="File missing on disk")
    return FileResponse(fp, media_type=d.get("content_type") or "application/octet-stream",
                        filename=d.get("filename") or d["stored_name"],
                        headers={"Content-Disposition": f'attachment; filename="{quote(d.get("filename") or d["stored_name"])}"'})


@router.get("/admin/documents/{did}/preview.pdf")
async def docs_preview_pdf(did: str, staff=Depends(get_current_staff)):
    """Serve the LibreOffice-rendered PDF of an Office/ODF document (inline).
    Same ACL as download; 404 when conversion is unavailable."""
    _require_internal_document_access(staff)
    db = await _get_db()
    d = await db.documents.find_one({"_id": _oid(did)})
    if not d or not d.get("stored_name"):
        raise HTTPException(status_code=404, detail="Document not found")
    if not _doc_can_read(staff, d):
        raise HTTPException(status_code=403, detail="Dokumen ini privat")
    fp = DOCS_DIR / d["stored_name"]
    if not fp.exists():
        raise HTTPException(status_code=404, detail="File missing on disk")
    kind = _doc_preview_kind((d.get("content_type") or "").split(";")[0].strip(), d.get("filename") or "")
    if kind not in _OFFICE_EXT:
        raise HTTPException(status_code=400, detail="Bukan dokumen Office")
    loop = asyncio.get_event_loop()
    pdf_path = await loop.run_in_executor(
        None, _cached_preview_pdf, str(d["_id"]), fp, fp.stat().st_mtime, kind
    )
    if pdf_path is None:
        raise HTTPException(status_code=404, detail="Preview PDF tidak tersedia (LibreOffice belum terpasang atau konversi gagal)")
    base = (d.get("filename") or d["stored_name"]).rsplit(".", 1)[0]
    return FileResponse(pdf_path, media_type="application/pdf",
                        headers={"Content-Disposition": f'inline; filename="{quote(base)}.pdf"',
                                 "Cache-Control": "private, max-age=300"})


_DOC_PREVIEW_KIND_BY_TYPE = {
    "application/pdf": "pdf",
    "image/png": "image", "image/jpeg": "image", "image/webp": "image", "image/gif": "image",
    "audio/mpeg": "audio", "audio/ogg": "audio", "audio/wav": "audio", "audio/mp4": "audio",
    "video/mp4": "video", "video/webm": "video", "video/ogg": "video", "video/quicktime": "video",
    "text/plain": "text", "text/csv": "text",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": "pptx",
    "application/vnd.oasis.opendocument.text": "odt",
    "application/vnd.oasis.opendocument.spreadsheet": "ods",
    "application/vnd.oasis.opendocument.presentation": "odp",
}


def _doc_preview_kind(ctype: str, filename: str = "") -> str:
    kind = _DOC_PREVIEW_KIND_BY_TYPE.get((ctype or "").split(";")[0].strip())
    if kind:
        return kind
    ext = (filename.rsplit(".", 1)[-1] or "").lower() if "." in (filename or "") else ""
    return {
        "pdf": "pdf", "png": "image", "jpg": "image", "jpeg": "image", "webp": "image", "gif": "image",
        "mp3": "audio", "ogg": "audio", "wav": "audio", "m4a": "audio",
        "mp4": "video", "webm": "video", "mov": "video",
        "txt": "text", "csv": "text",
        "docx": "docx", "xlsx": "xlsx", "pptx": "pptx", "odt": "odt", "ods": "ods", "odp": "odp",
    }.get(ext, "none")


def _esc(x) -> str:
    return _html.escape(str(x if x is not None else ""))


def _preview_docx_html(raw: bytes) -> str:
    try:
        import docx as _docx_lib
    except ImportError:
        return '<p><i>(Modul python-docx belum ter-install di server)</i></p>'
    buf = io.BytesIO(raw)
    doc = _docx_lib.Document(buf)
    parts = []
    for p in doc.paragraphs:
        text = p.text
        style = (p.style.name or "").lower()
        cls = "docx-h" if "heading" in style else ("docx-bold" if "title" in style else "")
        if text.strip():
            parts.append(f'<p class="{cls}">{_esc(text)}</p>')
    for tbl in doc.tables:
        rows_html = []
        for row in tbl.rows:
            cells = "".join(f"<td>{_esc(c.text)}</td>" for c in row.cells)
            rows_html.append(f"<tr>{cells}</tr>")
        parts.append(f'<table class="docx-table">{"".join(rows_html)}</table>')
    return "\n".join(parts) or "<p><i>(dokumen kosong)</i></p>"


def _xlsx_cell_style(cell) -> str:
    """Inline CSS for a cell: alignment, border, background fill."""
    css = []
    al = cell.alignment
    if al and al.horizontal:
        css.append(f"text-align:{al.horizontal}")
    if al and al.wrap_text:
        css.append("white-space:normal")
    # border detection (openpyxl Side with style != None)
    b = cell.border
    if b:
        for side_name, side in (("top", b.top), ("bottom", b.bottom), ("left", b.left), ("right", b.right)):
            if side and side.style:
                w = {"thin": 1, "medium": 2, "thick": 3, "double": 3}.get(side.style, 1)
                css.append(f"border-{side_name}:{w}px solid #94a3b8")
    # fill
    f = cell.fill
    if f and f.patternType and f.patternType != "none":
        fg = f.fgColor.rgb if f.fgColor and f.fgColor.type == "rgb" else None
        if fg and isinstance(fg, str) and len(fg) == 8:
            css.append(f"background:#{fg[2:]}")
    # font
    fn = cell.font
    if fn:
        if fn.bold:
            css.append("font-weight:700")
        if fn.italic:
            css.append("font-style:italic")
        if fn.color and fn.color.type == "rgb" and fn.color.rgb and len(fn.color.rgb) == 8:
            css.append(f"color:#{fn.color.rgb[2:]}")
    return ";".join(css)


def _xlsx_format_value(v, cell) -> str:
    """Format a cell value using number_format for dates/percent/currency."""
    from datetime import datetime as _dt, date as _date
    if v is None:
        return ""
    if isinstance(v, (_dt, _date)):
        return v.strftime("%d/%m/%Y") if isinstance(v, _dt) else v.strftime("%d/%m/%Y")
    if isinstance(v, (int, float)):
        nf = (cell.number_format or "").lower() if cell else ""
        if "%" in nf:
            return f"{v*100:g}%"
        if "rp" in nf or "#,##0" in nf or "id" in nf:
            return f"{v:,.0f}".replace(",", ".")
        if isinstance(v, float) and v != int(v):
            return f"{v:g}"
        return str(v)
    return _esc(v)


def _preview_xlsx_html(raw: bytes) -> str:
    try:
        import openpyxl
    except ImportError:
        return '<p><i>(Modul openpyxl belum ter-install di server)</i></p>'
    wb = openpyxl.load_workbook(io.BytesIO(raw), data_only=True)
    parts = []
    MAX_ROWS, MAX_COLS = 200, 30
    for ws in wb.worksheets:
        parts.append(f'<h3>{_esc(ws.title)}</h3>')
        parts.append('<table class="sheet-table">')
        # Determine actual used range
        max_row = min(ws.max_row, MAX_ROWS)
        max_col = min(ws.max_column, MAX_COLS)
        # merged cells: build map of (row,col) -> master cell
        merged = {}
        for rng in ws.merged_cells.ranges:
            r1, c1, r2, c2 = rng.min_row, rng.min_col, rng.max_row, rng.max_col
            # Skip ranges entirely outside the view — do NOT clamp their
            # origin into view (would shadow valid cells at the boundary).
            if r1 > max_row or c1 > max_col:
                continue
            # Clip only the far edge (span) to view limits
            r2c = min(r2, max_row)
            c2c = min(c2, max_col)
            for r in range(r1, r2c + 1):
                for c in range(c1, c2c + 1):
                    if (r, c) != (r1, c1):
                        merged[(r, c)] = (r1, c1)
            # store clipped spans for rendering (master entry has len 4)
            merged[(r1, c1)] = (r1, c1, c2c - c1 + 1, r2c - r1 + 1)
        for row in ws.iter_rows(min_row=1, max_row=max_row, max_col=max_col):
            if all(cell.value is None for cell in row):
                continue
            cells_html = []
            for cell in row:
                key = (cell.row, cell.column)
                if key in merged:
                    entry = merged[key]
                    if len(entry) == 2:  # slave cell in a merged range
                        continue
                    # entry is (r1, c1, colspan, rowspan) — clipped to view
                    _, _, colspan, rowspan = entry
                    master = ws.cell(row=entry[0], column=entry[1])
                    style = _xlsx_cell_style(master)
                    val = _xlsx_format_value(master.value, master)
                    attrs = []
                    if colspan > 1:
                        attrs.append(f'colspan="{colspan}"')
                    if rowspan > 1:
                        attrs.append(f'rowspan="{rowspan}"')
                    if style:
                        attrs.append(f'style="{style}"')
                    cells_html.append(f'<td {" ".join(attrs)}>{val}</td>')
                else:
                    style = _xlsx_cell_style(cell)
                    val = _xlsx_format_value(cell.value, cell)
                    if style:
                        cells_html.append(f'<td style="{style}">{val}</td>')
                    elif isinstance(cell.value, (int, float)) and cell.value is not None:
                        cells_html.append(f'<td class="num">{val}</td>')
                    else:
                        cells_html.append(f'<td>{val}</td>')
            parts.append(f'<tr>{"".join(cells_html)}</tr>')
        parts.append('</table>')
    wb.close()
    return "\n".join(parts) or "<p><i>(sheet kosong)</i></p>"


def _preview_pptx_html(raw: bytes) -> str:
    try:
        from pptx import Presentation
    except ImportError:
        return '<p><i>(Modul python-pptx belum ter-install di server)</i></p>'
    prs = Presentation(io.BytesIO(raw))
    parts = []
    for i, slide in enumerate(prs.slides, 1):
        parts.append(f'<div class="slide"><div class="slide-no">Slide {i}</div>')
        texts = []
        for shape in slide.shapes:
            if shape.has_text_frame:
                for para in shape.text_frame.paragraphs:
                    t = "".join(run.text for run in para.runs)
                    if t.strip():
                        texts.append(_esc(t))
        parts.extend(f"<p>{t}</p>" for t in texts)
        parts.append("</div>")
    return "\n".join(parts) or "<p><i>(tidak ada slide)</i></p>"


def _preview_odf_html(raw: bytes, kind: str) -> str:
    try:
        from odf.opendocument import load as _odf_load
        from odf.text import P as _ODF_P, H as _ODF_H
        from odf.table import Table as _ODF_Table, TableRow as _ODF_Tr, TableCell as _ODF_Td
    except ImportError:
        return '<p><i>(Modul odfpy belum ter‑install di server)</i></p>'

    def _odf_text(el):
        """Recursive text extraction from ODF element."""
        texts = []
        for child in el.childNodes:
            if child.nodeType == child.TEXT_NODE:
                texts.append(str(child))
            elif child.nodeType == child.ELEMENT_NODE:
                texts.append(_odf_text(child))
        return "".join(texts)

    o = _odf_load(io.BytesIO(raw))
    parts = []
    for el in o.getElementsByType(_ODF_P):
        t = _odf_text(el).strip()
        if t:
            parts.append(f"<p>{_esc(t)}</p>")
    for h in o.getElementsByType(_ODF_H):
        t = _odf_text(h).strip()
        if t:
            parts.append(f'<p class="docx-h">{_esc(t)}</p>')
    for tbl in o.getElementsByType(_ODF_Table):
        parts.append('<table class="docx-table">')
        for tr in tbl.getElementsByType(_ODF_Tr):
            cells = "".join(
                f"<td>{_esc(_odf_text(c).strip())}</td>"
                for c in tr.getElementsByType(_ODF_Td)
            )
            parts.append(f"<tr>{cells}</tr>")
        parts.append("</table>")
    return "\n".join(parts) or "<p><i>(dokumen kosong)</i></p>"


def _preview_text_html(raw: bytes) -> str:
    try:
        txt = raw.decode("utf-8")
    except UnicodeDecodeError:
        txt = raw.decode("latin-1", errors="replace")
    return f"<pre>{_esc(txt[:200000])}</pre>"


_PREVIEW_PAGE_CSS = """
<style>
body { font-family: system-ui, -apple-system, sans-serif; color: #1e293b; padding: 24px; }
.docx-h { font-weight: 800; font-size: 1.15em; color: #0a2350; margin: 14px 0 4px; }
.docx-bold { font-weight: 700; }
.docx-table, .sheet-table { border-collapse: collapse; margin: 10px 0 18px; }
.docx-table td, .docx-table th, .sheet-table td, .sheet-table th {
  border: 1px solid #cbd5e1; padding: 4px 8px; font-size: 13px; }
.sheet-table { display: block; overflow-x: auto; }
.sheet-table td.num { text-align: right; font-variant-numeric: tabular-nums; }
.slide { border: 1px solid #e2e8f0; border-radius: 10px; padding: 14px; margin: 12px 0; }
.slide-no { font-size: 11px; font-weight: 800; letter-spacing: .08em; color: #f5b120; text-transform: uppercase; }
pre { background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 12px; white-space: pre-wrap; }
</style>
"""


@router.get("/admin/documents/{did}/preview")
async def docs_preview(did: str, staff=Depends(get_current_staff)):
    """Inline preview metadata + HTML for the document. Binary types return
    kind + url so the frontend can embed <img>/<video>/<audio>/<iframe>."""
    _require_internal_document_access(staff)
    db = await _get_db()
    d = await db.documents.find_one({"_id": _oid(did)})
    if not d:
        raise HTTPException(status_code=404, detail="Document not found")
    if not _doc_can_read(staff, d):
        raise HTTPException(status_code=403, detail="Dokumen ini privat")
    ctype = (d.get("content_type") or "").split(";")[0].strip()
    filename = d.get("filename") or ""
    kind = _doc_preview_kind(ctype, filename)
    out = {
        "id": str(d["_id"]),
        "title": d.get("title", ""),
        "filename": filename,
        "content_type": ctype,
        "size_bytes": d.get("size_bytes", 0),
        "kind": kind,
        "file_url": f"/api/portal/documents/file/{d['_id']}",
        "download_url": f"/api/portal/admin/documents/{d['_id']}/download",
        "share_with": d.get("share_with") or {"users": [], "divisions": [], "roles": []},
        "folder_path": d.get("folder_path", ""),
        "owner_name": d.get("owner_name", ""),
    }
    if kind in ("image", "audio", "video", "pdf"):
        return out  # frontend embeds the file_url directly
    if kind == "none":
        return out
    if not d.get("stored_name"):
        out["kind"] = "none"
        return out
    fp = DOCS_DIR / d["stored_name"]
    if not fp.exists():
        raise HTTPException(status_code=404, detail="File missing on disk")

    # --- Office/ODF: render to PDF with LibreOffice for true fidelity ---
    # Google Drive / Nextcloud use the same approach: convert the Office file
    # to PDF server-side, then display it. If LibreOffice is unavailable the
    # HTML extractors below remain as a graceful fallback.
    if kind in _OFFICE_EXT:
        try:
            loop = asyncio.get_event_loop()
            pdf_path = await loop.run_in_executor(
                None, _cached_preview_pdf, str(d["_id"]), fp, fp.stat().st_mtime, kind
            )
        except Exception:
            pdf_path = None
        if pdf_path is not None:
            out["preview_pdf_url"] = f"/api/portal/admin/documents/{d['_id']}/preview.pdf"
            out["render_mode"] = "libreoffice"
            return out
        out["render_mode"] = "html"

    raw = fp.read_bytes()
    try:
        if kind == "docx":
            out["html"] = _preview_docx_html(raw)
        elif kind == "xlsx":
            out["html"] = _preview_xlsx_html(raw)
        elif kind == "pptx":
            out["html"] = _preview_pptx_html(raw)
        elif kind in ("odt", "ods", "odp"):
            out["html"] = _preview_odf_html(raw, kind)
        elif kind == "text":
            out["html"] = _preview_text_html(raw)
        else:
            out["kind"] = "none"
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=f"Gagal membuat preview: {e}")
    return out




@router.get("/admin/utm-links")
async def utm_links_list(staff=Depends(get_current_staff)):
    db = await _get_db()
    docs = await db.utm_links.find({}).sort("created_at", -1).to_list(200)
    return [{"id": str(d["_id"]), "url": d.get("url", ""), "base": d.get("base", ""),
             "params": d.get("params", {}), "label": d.get("label", ""),
             "created_by": d.get("created_by", ""), "created_at": _iso(d.get("created_at", ""))}
            for d in docs]


@router.post("/admin/utm-links")
async def utm_links_create(payload: dict, staff=Depends(get_current_staff)):
    db = await _get_db()
    url = str(payload.get("url", "")).strip()
    if not url.startswith("http"):
        raise HTTPException(status_code=400, detail="URL tidak valid")
    doc = {"url": url, "base": payload.get("base", ""), "params": payload.get("params", {}),
           "label": payload.get("label", ""), "created_by": staff.get("email", ""),
           "created_at": _now()}
    res = await db.utm_links.insert_one(doc)
    return {"ok": True, "id": str(res.inserted_id)}


@router.delete("/admin/utm-links/{lid}")
async def utm_links_delete(lid: str, staff=Depends(get_current_staff)):
    db = await _get_db()
    await db.utm_links.delete_one({"_id": _oid(lid)})
    return {"ok": True}


# ---------- Content calendar: hari libur nasional ----------

ID_HOLIDAYS_2026 = [
    {"date": "2026-01-01", "name": "Tahun Baru Masehi"},
    {"date": "2026-01-16", "name": "Isra Mikraj Nabi Muhammad SAW"},
    {"date": "2026-02-17", "name": "Tahun Baru Imlek 2577"},
    {"date": "2026-03-19", "name": "Hari Suci Nyepi"},
    {"date": "2026-03-20", "name": "Idul Fitri 1447 H (perkiraan)"},
    {"date": "2026-03-21", "name": "Idul Fitri 1447 H (hari kedua)"},
    {"date": "2026-04-03", "name": "Wafat Isa Almasih"},
    {"date": "2026-05-01", "name": "Hari Buruh Internasional"},
    {"date": "2026-05-14", "name": "Kenaikan Isa Almasih"},
    {"date": "2026-05-27", "name": "Idul Adha 1447 H (perkiraan)"},
    {"date": "2026-05-31", "name": "Hari Raya Waisak"},
    {"date": "2026-06-01", "name": "Hari Lahir Pancasila"},
    {"date": "2026-06-16", "name": "Tahun Baru Islam 1448 H"},
    {"date": "2026-08-17", "name": "Hari Kemerdekaan RI"},
    {"date": "2026-08-25", "name": "Maulid Nabi Muhammad SAW"},
    {"date": "2026-12-25", "name": "Hari Raya Natal"},
]


@router.get("/admin/content-calendar/holidays")
async def content_calendar_holidays(year: int = 2026, staff=Depends(get_current_staff)):
    return {"year": year, "holidays": [h for h in ID_HOLIDAYS_2026 if h["date"].startswith(str(year))]}


# ============================================================
# MEDIA LIBRARY - shared assets for the Digital Creative team
# ============================================================
from fastapi import UploadFile, File, Form  # noqa: E402


from fastapi.responses import FileResponse  # noqa: E402


import uuid as _uuid  # noqa: E402


from pathlib import Path as _Path  # noqa: E402


MEDIA_DIR = _Path(__file__).resolve().parent.parent.parent / "uploads" / "media"


_MEDIA_ALLOWED_TYPES = {"image/png", "image/jpeg", "image/webp", "image/gif", "image/svg+xml"}


_MEDIA_MAX_BYTES = 8 * 1024 * 1024  # 8 MB


async def _media_usage(db, media_id: str) -> list:
    """Where is this asset referenced? Scans articles (cover/OG/body) and
    branding/landing settings. Computed live so it never goes stale."""
    needle = f"/media/file/{media_id}"
    used = []
    cur = db.articles.find({"$or": [
        {"cover_image_url": {"$regex": needle}},
        {"og_image_url": {"$regex": needle}},
        {"body_html": {"$regex": needle}},
    ]}, {"title": 1, "slug": 1})
    async for a in cur:
        used.append({"type": "article", "id": str(a["_id"]),
                     "label": a.get("title") or a.get("slug") or "article"})
    async for s in db.settings.find({"key": {"$in": ["branding", "landing_content"]}}):
        if needle in str(s.get("value", "")):
            used.append({"type": "settings", "id": s.get("key"),
                         "label": f"Settings: {s.get('key')}"})
    return used


def _serialize_media(d: dict, used_in=None) -> dict:
    return {
        "id": str(d["_id"]),
        "filename": d.get("filename", ""),
        "url": d.get("url", ""),
        "content_type": d.get("content_type", ""),
        "size_bytes": int(d.get("size_bytes") or 0),
        "alt_text": d.get("alt_text", ""),
        "tags": d.get("tags", []),
        "uploaded_by": d.get("uploaded_by", ""),
        "created_at": d.get("created_at", ""),
        "used_in": used_in if used_in is not None else d.get("used_in", []),
    }


@router.get("/admin/media")
async def media_list(staff=Depends(get_current_staff),
                     tag: Optional[str] = None, q: Optional[str] = None):
    db = await _get_db()
    query: dict = {}
    if tag:
        query["tags"] = tag.strip().lower()
    if q:
        query["$or"] = [
            {"filename": {"$regex": q.strip(), "$options": "i"}},
            {"alt_text": {"$regex": q.strip(), "$options": "i"}},
        ]
    docs = await db.media_assets.find(query).sort("created_at", -1).to_list(500)
    out = []
    for d in docs:
        used = await _media_usage(db, str(d["_id"]))
        if used != d.get("used_in"):
            await db.media_assets.update_one({"_id": d["_id"]}, {"$set": {"used_in": used}})
        out.append(_serialize_media(d, used))
    return out


@router.post("/admin/media")
async def media_upload(file: UploadFile = File(...),
                       alt_text: str = Form(""),
                       tags: str = Form(""),
                       staff=Depends(get_current_staff)):
    db = await _get_db()
    if file.content_type not in _MEDIA_ALLOWED_TYPES:
        raise HTTPException(status_code=400,
                            detail=f"Unsupported type {file.content_type}. Allowed: PNG, JPEG, WebP, GIF, SVG.")
    raw = await file.read()
    if len(raw) > _MEDIA_MAX_BYTES:
        raise HTTPException(status_code=400, detail="File exceeds 8 MB limit")
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    ext = _Path(file.filename or "upload.bin").suffix.lower() or ".bin"
    mid = ObjectId()
    stored_name = f"{mid}{ext}"
    (MEDIA_DIR / stored_name).write_bytes(raw)
    doc = {
        "_id": mid,
        "filename": file.filename or stored_name,
        "stored_name": stored_name,
        "url": f"/api/portal/media/file/{mid}",
        "content_type": file.content_type,
        "size_bytes": len(raw),
        "alt_text": (alt_text or "").strip(),
        "tags": sorted({t.strip().lower() for t in (tags or "").split(",") if t.strip()}),
        "uploaded_by": staff["email"],
        "used_in": [],
        "created_at": _now(),
    }
    await db.media_assets.insert_one(doc)
    return _serialize_media(doc)


@router.post("/admin/documents/upload")
async def docs_upload(file: UploadFile = File(...), title: str = Form(""),
                      category: str = Form("contract"), customer_name: str = Form(""),
                      notes: str = Form(""), shared: str = Form(""),
                      folder_id: str = Form(""), share_with: str = Form(""),
                      staff=Depends(get_current_staff)):
    """UAT-003: upload dokumen lokal (drag & drop) selain link URL."""
    _require_internal_document_access(staff)
    db = await _get_db()
    is_shared = shared.lower() in ("true", "1", "yes", "on")
    if is_shared:
        folder = "shared"
        owner_id = None
    else:
        folder = f"private/{staff.get('id', 'unknown')}"
        owner_id = staff.get("id")
    ctype = file.content_type or "application/octet-stream"
    if ctype not in _DOC_ALLOWED_TYPES:
        raise HTTPException(status_code=400,
                            detail=f"Tipe file {ctype} tidak didukung. Gunakan PDF, Word, Excel, PowerPoint, OpenDocument, gambar, audio, video, ZIP, atau teks.")
    raw = await file.read()
    if len(raw) > _DOC_MAX_BYTES:
        raise HTTPException(status_code=400, detail="Ukuran file melebihi 15 MB")
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    did = ObjectId()
    ext = _DocPath(file.filename or "dokumen.bin").suffix.lower() or ".bin"
    stored_name = f"{did}{ext}"
    (DOCS_DIR / stored_name).write_bytes(raw)
    resolved_folder_id, resolved_folder_path = None, ""
    if (folder_id or "").strip():
        f_oid = _oid(folder_id.strip())
        if f_oid is None:
            raise HTTPException(status_code=400, detail="Invalid folder_id")
        f = await db.document_folders.find_one({"_id": f_oid})
        if not f:
            raise HTTPException(status_code=400, detail="Folder not found")
        resolved_folder_id, resolved_folder_path = str(f["_id"]), f.get("path", "")
    sw_users, sw_divisions, sw_roles = [], [], []
    if (share_with or "").strip():
        try:
            import json as _json
            sw = _json.loads(share_with)
            sw_users = [str(u) for u in (sw.get("users") or []) if u]
            sw_divisions = [str(d).strip().lower() for d in (sw.get("divisions") or []) if d]
            sw_roles = [str(r).strip().lower() for r in (sw.get("roles") or []) if r]
        except Exception:
            pass
    doc = {
        "_id": did,
        "title": (title or "").strip() or (file.filename or "Dokumen"),
        "category": category or "contract",
        "customer_name": customer_name or "",
        "url": f"/api/portal/documents/file/{did}",
        "notes": notes or "",
        "filename": file.filename or stored_name,
        "stored_name": stored_name,
        "content_type": ctype,
        "size_bytes": len(raw),
        "uploaded_by": staff["email"],
        "created_at": _now(),
        "folder": folder,
        "shared": is_shared,
        "owner_id": owner_id,
        "owner_name": staff.get("name") or staff.get("email", ""),
        "folder_id": resolved_folder_id,
        "folder_path": resolved_folder_path,
        "share_with": {"users": sw_users, "divisions": sw_divisions, "roles": sw_roles},
    }
    await db.documents.insert_one(doc)
    s = _serialize_doc(doc)
    s["can_manage"] = _doc_can_manage(staff, doc)
    return s


@router.put("/admin/media/{mid}")
async def media_update(mid: str, payload: dict, staff=Depends(get_current_staff)):
    db = await _get_db()
    d = await db.media_assets.find_one({"_id": _oid(mid)})
    if not d:
        raise HTTPException(status_code=404, detail="Media not found")
    upd: dict = {}
    if "alt_text" in payload:
        upd["alt_text"] = (payload.get("alt_text") or "").strip()
    if "tags" in payload:
        raw_tags = payload.get("tags") or []
        if isinstance(raw_tags, str):
            raw_tags = raw_tags.split(",")
        upd["tags"] = sorted({str(t).strip().lower() for t in raw_tags if str(t).strip()})
    if upd:
        await db.media_assets.update_one({"_id": d["_id"]}, {"$set": upd})
    d = await db.media_assets.find_one({"_id": d["_id"]})
    return _serialize_media(d)


@router.delete("/admin/media/{mid}")
async def media_delete(mid: str, staff=Depends(get_current_staff)):
    db = await _get_db()
    d = await db.media_assets.find_one({"_id": _oid(mid)})
    if not d:
        raise HTTPException(status_code=404, detail="Media not found")
    used = await _media_usage(db, mid)
    if used:
        raise HTTPException(status_code=409, detail={
            "message": "Asset is still in use - detach it first.",
            "used_in": used,
        })
    try:
        (MEDIA_DIR / d.get("stored_name", "")).unlink(missing_ok=True)
    except Exception:
        pass
    await db.media_assets.delete_one({"_id": d["_id"]})
    return {"deleted": 1}


@router.get("/media/file/{mid}", include_in_schema=False)
async def media_file(mid: str):
    """Public file serve - media is referenced from public articles."""
    db = await _get_db()
    d = await db.media_assets.find_one({"_id": _oid(mid)})
    if not d:
        raise HTTPException(status_code=404, detail="Media not found")
    fp = MEDIA_DIR / d.get("stored_name", "")
    if not fp.exists():
        raise HTTPException(status_code=404, detail="File missing on disk")
    return FileResponse(fp, media_type=d.get("content_type") or "application/octet-stream",
                        headers={"Cache-Control": "public, max-age=86400"})


# ============================================================
# MEDIA COMMENTS - feedback thread per media asset
# ============================================================
def _serialize_comment(d: dict) -> dict:
    return {
        "id": str(d["_id"]),
        "media_id": str(d.get("media_id", "")),
        "author_id": d.get("author_id", ""),
        "author_name": d.get("author_name", ""),
        "author_role": d.get("author_role", ""),
        "body": d.get("body", ""),
        "created_at": _iso(d.get("created_at", "")),
    }


@router.get("/admin/media/{mid}/comments")
async def media_comment_list(mid: str, staff=Depends(get_current_staff)):
    db = await _get_db()
    docs = await db.media_comments.find({"media_id": mid}).sort("created_at", 1).to_list(500)
    return [_serialize_comment(d) for d in docs]


@router.post("/admin/media/{mid}/comments")
async def media_comment_create(mid: str, payload: dict, staff=Depends(get_current_staff)):
    body = (payload.get("body") or "").strip()
    if not body:
        raise HTTPException(status_code=400, detail="Comment body is required")
    db = await _get_db()
    doc = {
        "media_id": mid,
        "author_id": staff.get("id", ""),
        "author_name": staff.get("name") or staff.get("email", ""),
        "author_role": staff.get("role", ""),
        "body": body,
        "created_at": _now(),
    }
    r = await db.media_comments.insert_one(doc)
    doc["_id"] = r.inserted_id
    return _serialize_comment(doc)


@router.delete("/admin/media/{mid}/comments/{cid}")
async def media_comment_delete(mid: str, cid: str, staff=Depends(get_current_staff)):
    db = await _get_db()
    d = await db.media_comments.find_one({"_id": _oid(cid)})
    if not d:
        raise HTTPException(status_code=404, detail="Comment not found")
    # Author or admin can delete
    if staff.get("role") != "admin" and d.get("author_id") != staff.get("id"):
        raise HTTPException(status_code=403, detail="Only the comment author or admin can delete")
    r = await db.media_comments.delete_one({"_id": _oid(cid)})
    return {"deleted": r.deleted_count}


# ============================================================
# CONTENT CALENDAR - plan articles / campaigns / social posts
# ============================================================
def _serialize_calendar(d: dict) -> dict:
    return {
        "id": str(d["_id"]),
        "source": "calendar",
        "title": d.get("title", ""),
        "type": d.get("type", "article"),
        "scheduled_at": d.get("scheduled_at", ""),
        "status": d.get("status", "draft"),
        "linked_article_id": d.get("linked_article_id"),
        "owner_id": d.get("owner_id"),
        "notes": d.get("notes", ""),
        "created_at": d.get("created_at", ""),
    }


# Mapping Content Planner (content_plan) -> entri Content Calendar agar apa
# yang di-schedule di planner otomatis muncul di kalender.
_PLANNER_TYPE_MAP = {"blog": "article", "email_campaign": "campaign",
                     "instagram": "social_post", "linkedin": "social_post",
                     "youtube": "social_post", "tiktok": "social_post"}
_PLANNER_STATUS_MAP = {"idea": "draft", "draft": "draft",
                       "scheduled": "scheduled", "published": "published"}


def _planner_as_calendar(d: dict) -> dict:
    return {
        "id": f"plan-{d['_id']}",
        "planner_id": str(d["_id"]),
        "source": "planner",
        "title": d.get("title", ""),
        "type": _PLANNER_TYPE_MAP.get(d.get("channel", "blog"), "article"),
        "channel": d.get("channel", "blog"),
        "scheduled_at": f"{d.get('publish_date', '')}T09:00:00",
        "status": _PLANNER_STATUS_MAP.get(d.get("status", "idea"), "draft"),
        "owner": d.get("owner", ""),
        "notes": d.get("hook", ""),
        "created_at": _iso(d.get("created_at", "")),
    }


_CAL_TYPES = {"article", "campaign", "social_post"}


_CAL_STATUSES = {"draft", "scheduled", "published"}


@router.get("/admin/content-calendar")
async def calendar_list(staff=Depends(get_current_staff),
                        date_from: Optional[str] = None,
                        date_to: Optional[str] = None):
    db = await _get_db()
    query: dict = {}
    if date_from or date_to:
        rng: dict = {}
        if date_from: rng["$gte"] = date_from
        if date_to:   rng["$lte"] = date_to + "T23:59:59"
        query["scheduled_at"] = rng
    docs = await db.content_calendar.find(query).sort("scheduled_at", 1).to_list(1000)
    out = [_serialize_calendar(d) for d in docs]
    # Gabungkan item Content Planner yang punya publish_date (yyyy-mm-dd)
    prng: dict = {"$ne": ""}
    if date_from:
        prng["$gte"] = date_from[:10]
    if date_to:
        prng["$lte"] = date_to[:10]
    pdocs = await db.content_plan.find({"publish_date": prng}).sort("publish_date", 1).to_list(1000)
    out.extend(_planner_as_calendar(d) for d in pdocs)
    out.sort(key=lambda x: x.get("scheduled_at") or "")
    return out


@router.post("/admin/content-calendar")
async def calendar_create(payload: dict, staff=Depends(get_current_staff)):
    db = await _get_db()
    title = (payload.get("title") or "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="Title is required")
    ctype = payload.get("type") or "article"
    if ctype not in _CAL_TYPES:
        raise HTTPException(status_code=400, detail=f"type must be one of {sorted(_CAL_TYPES)}")
    status = payload.get("status") or "draft"
    if status not in _CAL_STATUSES:
        raise HTTPException(status_code=400, detail=f"status must be one of {sorted(_CAL_STATUSES)}")
    doc = {
        "title": title,
        "type": ctype,
        "scheduled_at": payload.get("scheduled_at") or _now(),
        "status": status,
        "linked_article_id": payload.get("linked_article_id"),
        "owner_id": staff["id"],
        "notes": payload.get("notes") or "",
        "created_at": _now(),
    }
    r = await db.content_calendar.insert_one(doc)
    doc["_id"] = r.inserted_id
    return _serialize_calendar(doc)


@router.put("/admin/content-calendar/{cid}")
async def calendar_update(cid: str, payload: dict, staff=Depends(get_current_staff)):
    db = await _get_db()
    d = await db.content_calendar.find_one({"_id": _oid(cid)})
    if not d:
        raise HTTPException(status_code=404, detail="Calendar entry not found")
    upd: dict = {}
    for k in ("title", "scheduled_at", "linked_article_id", "notes"):
        if k in payload:
            upd[k] = payload[k]
    if "type" in payload:
        if payload["type"] not in _CAL_TYPES:
            raise HTTPException(status_code=400, detail=f"type must be one of {sorted(_CAL_TYPES)}")
        upd["type"] = payload["type"]
    if "status" in payload:
        if payload["status"] not in _CAL_STATUSES:
            raise HTTPException(status_code=400, detail=f"status must be one of {sorted(_CAL_STATUSES)}")
        upd["status"] = payload["status"]
    if upd:
        await db.content_calendar.update_one({"_id": d["_id"]}, {"$set": upd})
    d = await db.content_calendar.find_one({"_id": d["_id"]})
    return _serialize_calendar(d)


@router.delete("/admin/content-calendar/{cid}")
async def calendar_delete(cid: str, staff=Depends(get_current_staff)):
    db = await _get_db()
    r = await db.content_calendar.delete_one({"_id": _oid(cid)})
    if not r.deleted_count:
        raise HTTPException(status_code=404, detail="Calendar entry not found")
    return {"deleted": 1}


async def _sync_article_calendar(db, article: dict, staff) -> None:
    """When an article is published, upsert its calendar entry to published.
    Fire-and-forget: never blocks the article save."""
    try:
        if not article or article.get("status") != "published":
            return
        aid = str(article["_id"])
        await db.content_calendar.update_one(
            {"linked_article_id": aid},
            {"$set": {"title": article.get("title", ""),
                      "type": "article",
                      "status": "published",
                      "scheduled_at": article.get("published_at") or _now(),
                      "linked_article_id": aid},
             "$setOnInsert": {"owner_id": staff.get("id"), "notes": "",
                               "created_at": _now()}},
            upsert=True,
        )
    except Exception:
        logging.getLogger("portal.calendar").exception("calendar sync failed")
