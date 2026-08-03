"""Orders: client order creation, price cart preview, admin order management.

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
from .shared import _get_db, _get_setting_value, _iso, _next_number, _now, _oid  # noqa: E402
from .tickets import _deny_creative  # noqa: E402
from .users import _paginate  # noqa: E402

router = APIRouter()


@router.post("/client/orders")
async def create_order(payload: m.OrderIn, user=Depends(get_current_user)):
    db = await _get_db()
    prod = await db.products.find_one({"_id": _oid(payload.product_id)})
    if not prod or prod.get("is_addon"):
        raise HTTPException(status_code=404, detail="Product not found")

    # Price the cart from the selected options + add-ons.
    selections_data = [s.model_dump() for s in (payload.selections or [])]
    cart = await _price_cart(
        db, product=prod,
        selections=selections_data,
        addon_ids=payload.addon_ids or [],
        tax_percent=float(await _get_setting_value(db, "default_tax_percent", 11.0)),
    )

    # Anti double-submit: klik ganda pada "Confirm & Generate Invoice" tidak
    # boleh membuat order + invoice kedua. Order identik dalam 90 detik terakhir
    # dikembalikan apa adanya.
    dup_cutoff = (datetime.now(timezone.utc) - timedelta(seconds=90)).isoformat()
    dup = await db.orders.find_one({
        "user_id": ObjectId(user["id"]),
        "product_id": prod["_id"],
        "status": {"$in": ["pending_payment", "awaiting_quote"]},
        "created_at": {"$gte": dup_cutoff},
    }, sort=[("created_at", -1)])
    if dup and (dup.get("cart_snapshot") or {}).get("total") == cart["total"]:
        return _serialize_order(dup)

    # 1. Create the order
    doc = {
        "user_id": ObjectId(user["id"]),
        "user_name": user["name"],
        "user_email": user["email"],
        "product_id": prod["_id"],
        "product_name": prod["name"],
        "notes": payload.notes,
        "config": payload.config,
        "selections": selections_data,
        "addon_ids": [ObjectId(x) for x in (payload.addon_ids or [])],
        "cart_snapshot": cart,   # audit - the price shown to the user at confirm time
        "billing_cycle": payload.billing_cycle or prod.get("billing_cycle", "monthly"),
        "status": "pending_payment",
        "assigned_admin_id": None,
        "invoice_id": None,
        "service_id": None,
        "provision_log": [{"at": _now(), "step": "order_created", "message": "Order placed by client."}],
        "created_at": _now(),
    }
    r = await db.orders.insert_one(doc)
    doc["_id"] = r.inserted_id

    # 2. Auto-create an invoice for the order (14-day due window)
    items = []
    # Base line - first billing period
    base_line = cart["base_line"]
    if base_line["monthly"]:
        items.append({
            "description": f"{prod['name']} - first month",
            "qty": 1, "unit_price": base_line["monthly"], "total": base_line["monthly"],
        })
    if base_line["setup"]:
        items.append({
            "description": f"{prod['name']} - setup fee",
            "qty": 1, "unit_price": base_line["setup"], "total": base_line["setup"],
        })
    # Configurable option lines
    for ol in cart["option_lines"]:
        if ol.get("monthly"):
            items.append({
                "description": f"{ol['group_label']}: {ol['choice']} - monthly",
                "qty": 1, "unit_price": ol["monthly"], "total": ol["monthly"],
            })
        if ol.get("setup"):
            items.append({
                "description": f"{ol['group_label']}: {ol['choice']} - setup",
                "qty": 1, "unit_price": ol["setup"], "total": ol["setup"],
            })
    # Add-on lines
    for al in cart["addon_lines"]:
        if al.get("monthly"):
            items.append({
                "description": f"Add-on: {al['name']} - monthly",
                "qty": 1, "unit_price": al["monthly"], "total": al["monthly"],
            })
        if al.get("setup"):
            items.append({
                "description": f"Add-on: {al['name']} - setup",
                "qty": 1, "unit_price": al["setup"], "total": al["setup"],
            })

    if not items:
        # Custom quote / firewall - mark order as needing manual quotation, no auto-invoice
        await db.orders.update_one({"_id": doc["_id"]}, {"$set": {"status": "awaiting_quote"}})
        doc["status"] = "awaiting_quote"
        doc["provision_log"].append({"at": _now(), "step": "awaiting_quote", "message": "Custom-priced product; sales will send a quotation."})
    else:
        line_subtotal = sum(i["total"] for i in items)
        # PPN pre-filled from the admin-editable global default - stored on the
        # invoice and manually overridable afterwards; never recalculated.
        tax_percent = float(await _get_setting_value(db, "default_tax_percent", 11.0))
        tax = round(line_subtotal * tax_percent / 100, 2)
        total = round(line_subtotal + tax, 2)
        due = (datetime.now(timezone.utc) + timedelta(days=14)).date().isoformat()
        number = await _next_number(db, "invoices", "INV")
        inv = {
            "number": number,
            "user_id": ObjectId(user["id"]),
            "items": items,
            "subtotal": line_subtotal,
            "tax_percent": tax_percent,
            "tax_amount": tax,
            "total": total,
            "due_date": due,
            "status": "unpaid",
            "payment_method": None,
            "paid_at": None,
            "notes": f"Auto-generated from order for {prod['name']}.",
            "order_id": str(doc["_id"]),
            "created_at": _now(),
        }
        ir = await db.invoices.insert_one(inv)
        await db.orders.update_one(
            {"_id": doc["_id"]},
            {"$set": {"invoice_id": ir.inserted_id},
             "$push": {"provision_log": {"at": _now(), "step": "invoice_created", "message": f"Invoice {number} generated ({total:,.0f} IDR)."}}},
        )
        doc["invoice_id"] = ir.inserted_id
        doc["provision_log"].append({"at": _now(), "step": "invoice_created", "message": f"Invoice {number} generated ({total:,.0f} IDR)."})

    # Fire order + invoice notification emails in the BACKGROUND - SMTP yang
    # lambat/tidak terjangkau tidak boleh membekukan tombol "Confirm & Generate Invoice".
    order_snapshot = dict(doc)

    async def _order_emails():
        try:
            from portal import emails as _em
            user_doc = await db.users.find_one({"_id": ObjectId(user["id"])}) or {"email": user["email"], "name": user["name"]}
            await _em.on_order_created(db, order_snapshot, user_doc)
            if order_snapshot.get("invoice_id"):
                inv_doc = await db.invoices.find_one({"_id": order_snapshot["invoice_id"]})
                if inv_doc:
                    await _em.on_invoice_generated(db, inv_doc, user_doc, order_doc=order_snapshot)
        except Exception:
            logging.getLogger("portal.orders").exception("order/invoice email dispatch failed")

    asyncio.create_task(_order_emails())

    return _serialize_order(doc)


def _serialize_order(d: dict) -> dict:
    return {
        "id": str(d["_id"]),
        "user_id": str(d["user_id"]),
        "user_name": d.get("user_name", ""),
        "user_email": d.get("user_email", ""),
        "product_id": str(d["product_id"]),
        "product_name": d.get("product_name", ""),
        "notes": d.get("notes", ""),
        "config": d.get("config", {}),
        "status": d.get("status", "pending"),
        "assigned_admin_id": str(d["assigned_admin_id"]) if d.get("assigned_admin_id") else None,
        "invoice_id": str(d["invoice_id"]) if d.get("invoice_id") else None,
        "service_id": str(d["service_id"]) if d.get("service_id") else None,
        "provision_log": d.get("provision_log", []),
        "created_at": _iso(d.get("created_at", "")),
    }


@router.get("/client/orders")
async def client_orders(user=Depends(get_current_user)):
    db = await _get_db()
    docs = await db.orders.find({"user_id": ObjectId(user["id"])}).sort("created_at", -1).to_list(500)
    return [_serialize_order(d) for d in docs]


# ============================================================
# ORDER PREVIEW - build a WHMCS-style price cart WITHOUT persisting
# ============================================================

async def _price_cart(db, *, product: dict, selections: list, addon_ids: list, tax_percent: float = 11.0) -> dict:
    """Compute a full price breakdown from a product + option selections + add-ons."""
    base_monthly = float(product.get("price_monthly") or 0)
    base_setup = float(product.get("setup_fee") or 0)
    lines_options = []      # [{group_key, group_label, choice, monthly, setup}]
    monthly_options_sum = 0.0
    setup_options_sum = 0.0

    groups_by_key = {g.get("key"): g for g in (product.get("option_groups") or [])}
    for sel in (selections or []):
        gk = sel.get("group_key") if isinstance(sel, dict) else sel.group_key
        grp = groups_by_key.get(gk)
        if not grp:
            continue
        gtype = grp.get("type", "dropdown")
        glabel = grp.get("label", gk)
        if gtype == "quantity":
            qty = int((sel.get("quantity") if isinstance(sel, dict) else sel.quantity) or 0)
            if qty <= 0:
                continue
            unit_m = float(grp.get("unit_price_monthly") or 0)
            unit_s = float(grp.get("unit_price_setup") or 0)
            m_total = qty * unit_m
            s_total = qty * unit_s
            unit = grp.get("unit_label") or ""
            lines_options.append({
                "group_key": gk, "group_label": glabel,
                "choice": f"{qty} {unit}".strip(),
                "monthly": m_total, "setup": s_total,
            })
            monthly_options_sum += m_total
            setup_options_sum += s_total
        else:
            labels = (sel.get("option_labels") if isinstance(sel, dict) else sel.option_labels) or []
            for opt_lbl in labels:
                opt = next((o for o in (grp.get("options") or []) if o.get("label") == opt_lbl), None)
                if not opt:
                    continue
                m_delta = float(opt.get("price_monthly_delta") or 0)
                s_delta = float(opt.get("price_setup_delta") or 0)
                lines_options.append({
                    "group_key": gk, "group_label": glabel,
                    "choice": opt_lbl, "monthly": m_delta, "setup": s_delta,
                })
                monthly_options_sum += m_delta
                setup_options_sum += s_delta

    # Add-ons
    addon_lines = []
    if addon_ids:
        addon_docs = await db.products.find({"_id": {"$in": [_oid(x) for x in addon_ids]}, "is_addon": True}).to_list(50)
        for a in addon_docs:
            addon_lines.append({
                "id": str(a["_id"]),
                "name": a["name"],
                "monthly": float(a.get("price_monthly") or 0),
                "setup": float(a.get("setup_fee") or 0),
            })

    subtotal_monthly = base_monthly + monthly_options_sum + sum(x["monthly"] for x in addon_lines)
    setup_total = base_setup + setup_options_sum + sum(x["setup"] for x in addon_lines)
    # First-invoice basis = first month + setup fees
    first_invoice_subtotal = subtotal_monthly + setup_total
    tax_amount = round(first_invoice_subtotal * (tax_percent / 100.0), 2)
    total = round(first_invoice_subtotal + tax_amount, 2)
    return {
        "base_line": {
            "product_name": product["name"],
            "monthly": base_monthly,
            "setup": base_setup,
            "billing_cycle": product.get("billing_cycle", "monthly"),
        },
        "option_lines": lines_options,
        "addon_lines": addon_lines,
        "subtotal_monthly": round(subtotal_monthly, 2),
        "setup_total": round(setup_total, 2),
        "subtotal": round(first_invoice_subtotal, 2),
        "tax_percent": tax_percent,
        "tax_amount": tax_amount,
        "total": total,
    }


@router.post("/orders/preview")
async def order_preview(payload: m.OrderIn, user=Depends(get_current_user)):
    """Compute a full price breakdown for a client's cart WITHOUT creating an order.

    Used by the client's Order → Review step so users can confirm the total
    before we generate an invoice.
    """
    db = await _get_db()
    prod = await db.products.find_one({"_id": _oid(payload.product_id)})
    if not prod or prod.get("is_addon"):
        raise HTTPException(status_code=404, detail="Product not found")
    cart = await _price_cart(
        db, product=prod,
        selections=[s.model_dump() for s in (payload.selections or [])],
        addon_ids=payload.addon_ids or [],
        tax_percent=float(await _get_setting_value(db, "default_tax_percent", 11.0)),
    )
    return cart


# Orders
@router.get("/admin/orders")
async def admin_list_orders(staff=Depends(require_roles("admin", "sales", "finance")),
                            page: Optional[int] = None, limit: int = 25):
    _deny_creative(staff)
    db = await _get_db()
    q = {}
    if staff["role"] == "sales":
        # Sales sees only orders belonging to clients they're assigned to.
        assigned = [ObjectId(cid) for cid in (staff.get("assigned_client_ids") or [])]
        q = {"user_id": {"$in": assigned}} if assigned else {"_id": None}  # empty result if unassigned
    docs = await db.orders.find(q).sort("created_at", -1).to_list(1000)
    return _paginate([_serialize_order(d) for d in docs], page, limit)


@router.put("/admin/orders/{oid}/status")
async def admin_update_order_status(
    oid: str, payload: m.OrderStatusUpdateIn, admin=Depends(get_current_admin)
):
    """Manually move an order between statuses. Auto-provisioning primarily
    happens when the linked invoice is marked paid, but admins can still nudge
    the state machine (e.g. mark rejected)."""
    db = await _get_db()
    upd = {"status": payload.status}
    if payload.status == "assigned":
        upd["assigned_admin_id"] = ObjectId(admin["id"])
    await db.orders.update_one(
        {"_id": _oid(oid)},
        {"$set": upd,
         "$push": {"provision_log": {"at": _now(), "step": f"admin_set_{payload.status}",
                                      "message": f"Admin set status to {payload.status}."}}},
    )
    d = await db.orders.find_one({"_id": _oid(oid)})
    # Reject: invoice tertaut ikut ditutup agar tidak menggantung berstatus
    # unpaid/paid. Sudah paid -> refunded (uang harus dikembalikan), selain itu -> cancelled.
    if payload.status == "rejected" and d and d.get("invoice_id"):
        inv = await db.invoices.find_one({"_id": d["invoice_id"]})
        if inv and inv.get("status") not in ("cancelled", "refunded"):
            new_status = "refunded" if inv.get("status") == "paid" else "cancelled"
            await db.invoices.update_one({"_id": inv["_id"]}, {"$set": {"status": new_status}})
            await db.orders.update_one({"_id": d["_id"]}, {"$push": {"provision_log": {
                "at": _now(), "step": f"invoice_{new_status}",
                "message": f"Invoice {inv.get('number', '')} ditandai {new_status} karena order ditolak."}}})
            d = await db.orders.find_one({"_id": d["_id"]})
    return _serialize_order(d)


@router.post("/admin/orders/{oid}/provision")
async def admin_order_provision(oid: str, admin=Depends(get_current_admin)):
    """Jalankan/ulangi auto-provisioning manual dari menu Orders admin.
    Syarat: invoice tertaut sudah lunas. Aman diulang - tidak membuat service ganda."""
    from .provision import _auto_provision, _vps_provision_task
    db = await _get_db()
    d = await db.orders.find_one({"_id": _oid(oid)})
    if not d:
        raise HTTPException(status_code=404, detail="Order not found")
    if d.get("status") == "rejected":
        raise HTTPException(status_code=400, detail="Order sudah ditolak - tidak bisa diprovision.")
    inv = await db.invoices.find_one({"_id": d["invoice_id"]}) if d.get("invoice_id") else None
    if not inv or inv.get("status") != "paid":
        raise HTTPException(status_code=400,
                            detail="Invoice order ini belum lunas - verifikasi pembayaran terlebih dahulu.")
    if not d.get("service_id"):
        # Belum pernah ada service (mis. percobaan sebelumnya gagal total) - jalankan penuh.
        await db.orders.update_one({"_id": d["_id"]}, {
            "$set": {"status": "payment_verified", "provisioning_started": True},
            "$push": {"provision_log": {"at": _now(), "step": "manual_provision_triggered",
                                        "message": f"Auto-provision dijalankan manual oleh {admin.get('name', 'admin')}."}}})
        order = await db.orders.find_one({"_id": d["_id"]})
        await _auto_provision(db, order)
        return {"ok": True, "message": "Auto-provisioning dijalankan - pantau provision log."}
    svc = await db.services.find_one({"_id": _oid(str(d["service_id"]))})
    cfg = (svc or {}).get("config") or {}
    if svc and svc.get("category") in ("vps", "cloud") and cfg.get("provision_status") != "provisioned":
        await db.services.update_one({"_id": svc["_id"]},
                                     {"$set": {"config.provision_status": "provisioning"}})
        await db.orders.update_one({"_id": d["_id"]}, {"$push": {"provision_log": {
            "at": _now(), "step": "manual_provision_retry",
            "message": f"Provisioning VM diulang manual oleh {admin.get('name', 'admin')}."}}})
        asyncio.create_task(_vps_provision_task(db, d["_id"], svc["_id"]))
        return {"ok": True, "message": "Provisioning VM diulang di background - pantau provision log."}
    raise HTTPException(status_code=400, detail="Service order ini sudah selesai diprovision.")


# Client can flag a bank-transfer payment as sent; admin still needs to confirm.
@router.post("/client/orders/{oid}/confirm-transfer")
async def client_confirm_transfer(oid: str, payload: dict, user=Depends(get_current_user)):
    db = await _get_db()
    o = await db.orders.find_one({"_id": _oid(oid), "user_id": ObjectId(user["id"])})
    if not o:
        raise HTTPException(status_code=404, detail="Order not found")
    await db.orders.update_one(
        {"_id": o["_id"]},
        {"$set": {"status": "awaiting_verification"},
         "$push": {"provision_log": {"at": _now(), "step": "transfer_declared",
                                      "message": f"Client declared bank transfer. Ref: {payload.get('reference','-')}"}}},
    )
    d = await db.orders.find_one({"_id": o["_id"]})
    return _serialize_order(d)


@router.put("/admin/orders/{oid}")
async def admin_update_order(oid: str, payload: dict, staff=Depends(get_current_staff)):
    """Ubah detail pesanan (catatan + konfigurasi) sebelum/di tengah provisioning."""
    db = await _get_db()
    d = await db.orders.find_one({"_id": _oid(oid)})
    if not d:
        raise HTTPException(status_code=404, detail="Order not found")
    upd = {}
    if "notes" in payload:
        upd["notes"] = str(payload["notes"])
    if isinstance(payload.get("config"), dict):
        cfg = d.get("config") or {}
        cfg.update({k: v for k, v in payload["config"].items() if isinstance(k, str)})
        upd["config"] = cfg
    if not upd:
        raise HTTPException(status_code=400, detail="Tidak ada perubahan")
    upd["updated_at"] = _now()
    await db.orders.update_one({"_id": d["_id"]}, {
        "$set": upd,
        "$push": {"provision_log": {"at": _now(), "step": "order_updated",
                                    "message": f"Pesanan diubah oleh {staff.get('name','staff')}."}},
    })
    d = await db.orders.find_one({"_id": d["_id"]})
    return _serialize_order(d)
