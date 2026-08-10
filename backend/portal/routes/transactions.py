"""Transaction ledger for invoice payment lifecycle and reconciliation."""
from datetime import datetime, timezone
from typing import Optional

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException

from .. import models as m
from ..auth import require_roles
from .shared import _get_db, _iso, _oid, _sales_scope_filter
from .users import _paginate

router = APIRouter()


def _parse_dt(value: Optional[str], field: str):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid {field} date")


def _serialize_transaction(d: dict) -> dict:
    return {
        "id": str(d["_id"]),
        "invoice_id": str(d["invoice_id"]) if d.get("invoice_id") else None,
        "invoice_number": d.get("invoice_number"),
        "user_id": str(d["user_id"]) if d.get("user_id") else None,
        "user_name": d.get("user_name"),
        "customer_name": d.get("customer_name", ""),
        "amount": float(d.get("amount") or 0),
        "method": d.get("method"),
        "status": d.get("status", "pending"),
        "paid_at": _iso(d.get("paid_at")) if d.get("paid_at") else None,
        "verified_at": _iso(d.get("verified_at")) if d.get("verified_at") else None,
        "invoice_date": _iso(d.get("invoice_date")) if d.get("invoice_date") else None,
        "due_date": _iso(d.get("due_date")) if d.get("due_date") else None,
        "reference": d.get("reference"),
        "notes": d.get("notes", ""),
        "source": d.get("source", "auto"),
        "created_at": _iso(d.get("created_at", "")),
        "updated_at": _iso(d.get("updated_at", "")),
    }


@router.get("/admin/transactions")
async def list_transactions(
    staff=Depends(require_roles("admin", "finance", "sales")),
    user_id: Optional[str] = None,
    status: Optional[str] = None,
    method: Optional[str] = None,
    start: Optional[str] = None,
    end: Optional[str] = None,
    page: Optional[int] = None,
    limit: int = 25,
):
    db = await _get_db()
    query = _sales_scope_filter(staff, key="user_id")
    if user_id:
        uid = _oid(user_id)
        if staff.get("role") == "sales" and uid not in [ObjectId(x) for x in staff.get("assigned_client_ids") or []]:
            return _paginate([], page, limit)
        query["user_id"] = uid
    if status:
        query["status"] = status
    if method:
        query["method"] = method
    start_dt, end_dt = _parse_dt(start, "start"), _parse_dt(end, "end")
    if start_dt or end_dt:
        query["created_at"] = {}
        if start_dt:
            query["created_at"]["$gte"] = start_dt.isoformat()
        if end_dt:
            query["created_at"]["$lte"] = end_dt.isoformat()
    docs = await db.transactions.find(query).sort("created_at", -1).to_list(5000)
    return _paginate([_serialize_transaction(d) for d in docs], page, min(max(limit, 1), 200))


@router.get("/admin/transactions/summary")
async def transaction_summary(
    staff=Depends(require_roles("admin", "finance", "sales")),
    start: Optional[str] = None,
    end: Optional[str] = None,
):
    """Reconciliation totals for transactions visible to the current staff role."""
    db = await _get_db()
    query = _sales_scope_filter(staff, key="user_id")
    start_dt, end_dt = _parse_dt(start, "start"), _parse_dt(end, "end")
    if start_dt or end_dt:
        query["created_at"] = {}
        if start_dt:
            query["created_at"]["$gte"] = start_dt.isoformat()
        if end_dt:
            query["created_at"]["$lte"] = end_dt.isoformat()

    rows = await db.transactions.aggregate([
        {"$match": query},
        {"$group": {
            "_id": "$status",
            "count": {"$sum": 1},
            "amount": {"$sum": "$amount"},
        }},
    ]).to_list(100)
    by_status = {
        row["_id"]: {"count": int(row["count"]), "amount": float(row["amount"] or 0)}
        for row in rows
    }
    paid = by_status.get("paid", {"count": 0, "amount": 0.0})
    outstanding = sum(
        float(row["amount"] or 0)
        for row in rows if row["_id"] in {"pending", "unpaid"}
    )
    return {
        "paid_count": paid["count"],
        "paid_amount": paid["amount"],
        "outstanding_amount": outstanding,
        "by_status": by_status,
    }


@router.get("/admin/transactions/{tid}")
async def get_transaction(tid: str, staff=Depends(require_roles("admin", "finance", "sales"))):
    db = await _get_db()
    doc = await db.transactions.find_one({"_id": _oid(tid), **_sales_scope_filter(staff, key="user_id")})
    if not doc:
        raise HTTPException(status_code=404, detail="Transaction not found")
    return _serialize_transaction(doc)


@router.post("/admin/transactions", response_model=m.TransactionOut)
async def create_transaction(payload: m.TransactionIn, staff=Depends(require_roles("admin", "finance"))):
    db = await _get_db()
    invoice_id = _oid(payload.invoice_id) if payload.invoice_id else None
    user_id = _oid(payload.user_id) if payload.user_id else None
    invoice = await db.invoices.find_one({"_id": invoice_id}) if invoice_id else None
    if payload.invoice_id and not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
    if invoice and not user_id:
        user_id = invoice.get("user_id")
    user = await db.users.find_one({"_id": user_id}) if user_id else None
    now = datetime.now(timezone.utc).isoformat()
    doc = {
        "invoice_id": invoice_id,
        "invoice_number": (invoice or {}).get("number"),
        "user_id": user_id,
        "user_name": (user or {}).get("name"),
        "customer_name": payload.customer_name or (user or {}).get("name", ""),
        "amount": float(payload.amount or (invoice or {}).get("total") or 0),
        "method": payload.method or "manual",
        "status": payload.status,
        "paid_at": payload.paid_at or (now if payload.status == "paid" else None),
        "verified_at": payload.verified_at,
        "invoice_date": payload.invoice_date or (invoice or {}).get("created_at"),
        "due_date": payload.due_date or (invoice or {}).get("due_date"),
        "reference": payload.reference,
        "notes": payload.notes,
        "source": "manual",
        "created_at": now,
        "updated_at": now,
    }
    result = await db.transactions.insert_one(doc)
    doc["_id"] = result.inserted_id
    return _serialize_transaction(doc)


@router.post("/admin/transactions/{tid}/verify", response_model=m.TransactionOut)
async def verify_transaction(tid: str, payload: m.TransactionVerifyIn, staff=Depends(require_roles("admin", "finance"))):
    db = await _get_db()
    now = datetime.now(timezone.utc).isoformat()
    result = await db.transactions.update_one(
        {"_id": _oid(tid)},
        {"$set": {"verified_at": now, "verified_by": staff.get("id"), "updated_at": now},
         "$setOnInsert": {},
         **({"$push": {"verification_notes": payload.notes}} if payload.notes else {})},
    )
    if not result.matched_count:
        raise HTTPException(status_code=404, detail="Transaction not found")
    return _serialize_transaction(await db.transactions.find_one({"_id": _oid(tid)}))
