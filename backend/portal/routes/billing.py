"""Billing: invoices, quotations, billing settings, bank accounts, payment gateway + webhooks.

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
from .domains import _apply_domain_renewal, _auto_register_domain  # noqa: E402
from .provision import (_provision_order_from_invoice,  # noqa: E402
                        _proxmox_settings_for_service)
from .shared import BILLING_SETTING_DEFAULTS, _EXTRA_PAYMENT_MODULES, _get_db, _get_setting_value, _iso, _load_user, _mark_overdue, _next_number, _now, _oid, _sales_scope_filter, _serialize_invoice, _set_setting_value, _sum_applied_credit  # noqa: E402
from .tickets import _deny_creative  # noqa: E402
from .users import _paginate  # noqa: E402

router = APIRouter()


# Invoices (staff - Sales sees only invoices of their assigned clients)
@router.get("/admin/invoices")
async def admin_list_invoices(staff=Depends(require_roles("admin", "finance")),
                              page: Optional[int] = None, limit: int = 25):
    _deny_creative(staff)
    db = await _get_db()
    await _mark_overdue(db)
    q = _sales_scope_filter(staff, key="user_id")
    docs = await db.invoices.find(q).sort("created_at", -1).to_list(2000)
    return _paginate([await _serialize_invoice(db, d) for d in docs], page, limit)


@router.get("/admin/invoices/{iid}")
async def admin_get_invoice(iid: str, staff=Depends(get_current_staff)):
    _deny_creative(staff)
    db = await _get_db()
    await _mark_overdue(db)
    q = {"_id": _oid(iid), **_sales_scope_filter(staff, key="user_id")}
    d = await db.invoices.find_one(q)
    if not d:
        raise HTTPException(status_code=404, detail="Invoice not found")
    return await _serialize_invoice(db, d)


@router.post("/admin/invoices/{iid}/send")
async def admin_send_invoice(iid: str, staff=Depends(get_current_staff)):
    """Kirim invoice ke klien via email + siapkan link WhatsApp."""
    from portal import emails as _em
    db = await _get_db()
    d = await db.invoices.find_one({"_id": _oid(iid), **_sales_scope_filter(staff, key="user_id")})
    if not d:
        raise HTTPException(status_code=404, detail="Invoice not found")
    u = await db.users.find_one({"_id": d["user_id"]}) or {}
    email_sent = False
    try:
        await _em.on_invoice_generated(db, d, u)
        email_sent = True
    except Exception:
        email_sent = False
    total_str = "Rp " + f"{float(d.get('total') or 0):,.0f}".replace(",", ".")
    text = (f"Halo {u.get('name','')}, invoice {d.get('number','')} sebesar {total_str} "
            f"jatuh tempo {d.get('due_date','')}. Silakan login ke portal untuk membayar: "
            f"{os.environ.get('PORTAL_PUBLIC_URL', '')}/portal/login")
    phone = re.sub(r"[^0-9]", "", u.get("phone") or "")
    if phone.startswith("0"):
        phone = "62" + phone[1:]
    wa_link = f"https://wa.me/{phone}?text={quote(text)}" if phone else None
    return {"ok": True, "email_sent": email_sent, "email": u.get("email", ""),
            "wa_link": wa_link, "message": text}


@router.post("/admin/invoices", response_model=m.InvoiceOut)
async def admin_create_invoice(payload: m.InvoiceIn, admin=Depends(get_current_admin)):
    db = await _get_db()
    u = await _load_user(db, payload.user_id)
    subtotal = sum(i.total for i in payload.items)
    tax_amount = round(subtotal * payload.tax_percent / 100, 2)
    total = round(subtotal + tax_amount, 2)
    number = await _next_number(db, "invoices", "INV")
    doc = {
        "number": number,
        "user_id": u["_id"],
        "items": [i.model_dump() for i in payload.items],
        "subtotal": subtotal,
        "tax_percent": payload.tax_percent,
        "tax_amount": tax_amount,
        "total": total,
        "due_date": payload.due_date,
        "status": "unpaid",
        "payment_method": None,
        "paid_at": None,
        "notes": payload.notes,
        "created_at": _now(),
    }
    r = await db.invoices.insert_one(doc)
    doc["_id"] = r.inserted_id
    return await _serialize_invoice(db, doc)


async def _apply_pending_upgrade(db, inv: dict) -> bool:
    """Terapkan upgrade resource setelah invoice selisih dibayar (idempotent).

    Dipanggil dari semua jalur invoice -> paid (webhook Duitku, admin mark-paid,
    settle via credit note). Best-effort live resize cores/memory di Proxmox."""
    up = inv.get("upgrade")
    sid = inv.get("service_id")
    if not (up and sid):
        return False
    try:
        svc = await db.services.find_one({"_id": ObjectId(sid)})
    except Exception:
        return False
    pending = (svc or {}).get("pending_upgrade")
    if not svc or not pending or pending.get("invoice_id") != str(inv["_id"]):
        return False

    def _num(v):
        try:
            return int(v)
        except (TypeError, ValueError):
            return 0

    cfg = svc.get("config") or {}
    new_cpu = _num(cfg.get("cpu")) + int(up.get("cpu") or 0)
    new_ram = _num(cfg.get("ram_gb")) + int(up.get("ram_gb") or 0)
    new_disk = _num(cfg.get("disk_gb")) + int(up.get("disk_gb") or 0)
    await db.services.update_one(
        {"_id": svc["_id"]},
        {"$set": {"config.cpu": new_cpu, "config.ram_gb": new_ram, "config.disk_gb": new_disk,
                  "config.restart_required": True},
         "$inc": {"price_monthly": float(up.get("monthly_delta") or 0)},
         "$unset": {"pending_upgrade": ""},
         "$push": {"self_service_log": {"at": _now(), "action": "upgrade_applied",
                                         "by": f"billing (invoice {inv.get('number', '')})"}}})
    try:
        s = await _proxmox_settings_for_service(db, svc)
        if s and cfg.get("node") and cfg.get("vmid"):
            body = {}
            if up.get("cpu"):
                body["cores"] = new_cpu
            if up.get("ram_gb"):
                body["memory"] = new_ram * 1024
            if body:
                await iv2.ProxmoxClient(s)._post(
                    f"/nodes/{cfg['node']}/qemu/{int(cfg['vmid'])}/config", body)
    except Exception:
        pass
    return True


@router.put("/admin/invoices/{iid}/status")
async def admin_update_invoice_status(
    iid: str, payload: m.InvoiceStatusIn, admin=Depends(get_current_admin)
):
    db = await _get_db()
    upd = {"status": payload.status}
    if payload.status == "paid":
        upd["paid_at"] = _now()
        upd["payment_method"] = payload.payment_method or "bank_transfer"
        # Atomic transition: klik ganda "confirm payment" tidak boleh memicu
        # provisioning / upgrade dua kali.
        prev = await db.invoices.find_one_and_update(
            {"_id": _oid(iid), "status": {"$ne": "paid"}}, {"$set": upd})
        just_paid = prev is not None
    else:
        await db.invoices.update_one({"_id": _oid(iid)}, {"$set": upd})
        just_paid = False
    d = await db.invoices.find_one({"_id": _oid(iid)})
    if not d:
        raise HTTPException(status_code=404, detail="Invoice not found")

    # Invoice lunas + tertaut order → auto-provision (guard atomic di helper:
    # hanya satu request yang boleh memulai provisioning). Juga berlaku bila
    # invoice SUDAH paid sebelumnya (mis. dilunasi via credit note) tapi order
    # belum pernah diprovision - klik "Verify Payment" admin tetap memicu provisioning.
    if payload.status == "paid" and d.get("status") == "paid" and d.get("order_id"):
        await _provision_order_from_invoice(db, d)

    # Eksekusi upgrade resource yang menunggu pembayaran invoice ini.
    if just_paid:
        await _apply_pending_upgrade(db, d)
        await _auto_register_domain(db, d)
        await _apply_domain_renewal(db, d)

    return await _serialize_invoice(db, d)


# Quotations
async def _serialize_quotation(db, d: dict) -> dict:
    u = await db.users.find_one({"_id": d["user_id"]}) or {}
    return {
        "id": str(d["_id"]),
        "number": d["number"],
        "user_id": str(d["user_id"]),
        "user_name": u.get("name", ""),
        "user_email": u.get("email", ""),
        "items": d.get("items", []),
        "subtotal": d.get("subtotal", 0),
        "tax_amount": d.get("tax_amount", 0),
        "total": d.get("total", 0),
        "valid_until": d.get("valid_until", ""),
        "status": d.get("status", "draft"),
        "created_at": _iso(d.get("created_at", "")),
        "notes": d.get("notes", ""),
        "converted_invoice_id": d.get("converted_invoice_id"),
        "converted_invoice_number": d.get("converted_invoice_number"),
    }


@router.get("/admin/quotations")
async def admin_list_quotations(staff=Depends(require_roles("admin", "sales", "finance"))):
    _deny_creative(staff)
    db = await _get_db()
    q = {}
    if staff["role"] == "sales":
        assigned = [ObjectId(cid) for cid in (staff.get("assigned_client_ids") or [])]
        q = {"user_id": {"$in": assigned}} if assigned else {"_id": None}
    docs = await db.quotations.find(q).sort("created_at", -1).to_list(1000)
    return [await _serialize_quotation(db, d) for d in docs]


@router.post("/admin/quotations", response_model=m.QuotationOut)
async def admin_create_quotation(payload: m.QuotationIn, admin=Depends(get_current_admin)):
    db = await _get_db()
    u = await _load_user(db, payload.user_id)
    subtotal = sum(i.total for i in payload.items)
    tax_amount = round(subtotal * payload.tax_percent / 100, 2)
    total = round(subtotal + tax_amount, 2)
    number = await _next_number(db, "quotations", "QTN")
    doc = {
        "number": number,
        "user_id": u["_id"],
        "items": [i.model_dump() for i in payload.items],
        "subtotal": subtotal,
        "tax_percent": payload.tax_percent,
        "tax_amount": tax_amount,
        "total": total,
        "valid_until": payload.valid_until,
        "status": "draft",
        "notes": payload.notes,
        "created_at": _now(),
    }
    r = await db.quotations.insert_one(doc)
    doc["_id"] = r.inserted_id
    return await _serialize_quotation(db, doc)


@router.put("/admin/quotations/{qid}/status")
async def admin_update_quotation_status(
    qid: str, payload: m.QuotationStatusIn, admin=Depends(get_current_admin)
):
    db = await _get_db()
    await db.quotations.update_one({"_id": _oid(qid)}, {"$set": {"status": payload.status}})
    d = await db.quotations.find_one({"_id": _oid(qid)})
    if not d:
        raise HTTPException(status_code=404, detail="Quotation not found")
    return await _serialize_quotation(db, d)


@router.post("/admin/quotations/{qid}/convert-to-invoice", response_model=m.InvoiceOut)
async def admin_convert_quotation_to_invoice(qid: str, payload: m.QuotationConvertIn,
                                             request: Request, admin=Depends(get_current_admin)):
    """Buat invoice dari quotation (menyalin item/pajak). Idempotent: quotation yang
    sudah dikonversi tidak bisa dikonversi ulang."""
    db = await _get_db()
    q = await db.quotations.find_one({"_id": _oid(qid)})
    if not q:
        raise HTTPException(status_code=404, detail="Quotation not found")
    if q.get("converted_invoice_id"):
        raise HTTPException(status_code=400, detail="Quotation ini sudah dikonversi menjadi invoice")
    due = payload.due_date or (datetime.now(timezone.utc) + timedelta(days=7)).date().isoformat()
    items = q.get("items") or []
    subtotal = sum(float(i.get("total") or 0) for i in items)
    tax_percent = float(q.get("tax_percent") or 0)
    tax_amount = round(subtotal * tax_percent / 100, 2)
    doc = {
        "number": await _next_number(db, "invoices", "INV"),
        "user_id": q["user_id"],
        "items": items,
        "subtotal": subtotal,
        "tax_percent": tax_percent,
        "tax_amount": tax_amount,
        "total": round(subtotal + tax_amount, 2),
        "due_date": due,
        "status": "unpaid",
        "payment_method": None,
        "paid_at": None,
        "notes": q.get("notes") or f"Dibuat dari quotation {q.get('number', '')}.",
        "source_quotation_id": str(q["_id"]),
        "source_quotation_number": q.get("number", ""),
        "created_at": _now(),
    }
    r = await db.invoices.insert_one(doc)
    doc["_id"] = r.inserted_id
    await db.quotations.update_one({"_id": q["_id"]}, {"$set": {
        "status": "accepted", "converted_invoice_id": str(r.inserted_id),
        "converted_invoice_number": doc["number"], "converted_at": _now()}})
    await log_audit(db, actor=admin, action="quotation.convert_to_invoice", category="billing",
                    target_type="quotation", target_id=qid, target_label=q.get("number", ""),
                    metadata={"invoice": doc["number"], "total": doc["total"]}, request=request)
    return await _serialize_invoice(db, doc)


# ============================================================
# BILLING DEFAULTS (admin-editable global settings)
# ============================================================
@router.get("/admin/billing/settings")
async def get_billing_settings(staff=Depends(get_current_staff)):
    """Global billing defaults. `default_tax_percent` is only the *suggested*
    initial PPN % pre-filled into new invoices/quotations and renewal
    auto-invoices - always overridable per document, down to 0."""
    db = await _get_db()
    return {k: await _get_setting_value(db, k, dv)
            for k, dv in BILLING_SETTING_DEFAULTS.items()}


@router.put("/admin/billing/settings")
async def put_billing_settings(payload: dict, request: Request, admin=Depends(get_current_admin)):
    db = await _get_db()
    before = {k: await _get_setting_value(db, k, dv)
              for k, dv in BILLING_SETTING_DEFAULTS.items()}
    if "default_tax_percent" in payload and payload["default_tax_percent"] is not None:
        await _set_setting_value(db, "default_tax_percent",
                                 max(0.0, float(payload["default_tax_percent"])))
    if "renewal_lead_days" in payload and payload["renewal_lead_days"] is not None:
        await _set_setting_value(db, "renewal_lead_days",
                                 max(1, int(payload["renewal_lead_days"])))
    if "enable_extra_payment_gateways" in payload and payload["enable_extra_payment_gateways"] is not None:
        await _set_setting_value(db, "enable_extra_payment_gateways",
                                 bool(payload["enable_extra_payment_gateways"]))
    if "noc_alert_recipients" in payload and payload["noc_alert_recipients"] is not None:
        v = payload["noc_alert_recipients"]
        if isinstance(v, str):
            v = [x for x in v.replace(",", "\n").splitlines()]
        cleaned = [str(x).strip() for x in (v or []) if str(x).strip()]
        await _set_setting_value(db, "noc_alert_recipients", cleaned)
    after = {k: await _get_setting_value(db, k, dv)
             for k, dv in BILLING_SETTING_DEFAULTS.items()}
    if before != after:
        await log_audit(db, actor=admin, action="billing.settings_update", category="billing",
                        target_type="settings", target_label="Billing Defaults",
                        before=before, after=after, severity="info", request=request)
    return after


@router.post("/admin/billing/run-renewal-sweep")
async def run_renewal_sweep_now(admin=Depends(get_current_admin)):
    """Manually trigger the renewal auto-invoice sweep (same job the hourly
    scheduler runs). Idempotent - re-running never duplicates invoices."""
    db = await _get_db()
    from portal import emails as _em
    return await _em.run_renewal_invoice_sweep(db)


# Bank accounts admin CRUD (simple)
@router.get("/admin/bank-accounts")
async def get_bank_accounts(admin=Depends(require_roles("admin", "finance"))):
    db = await _get_db()
    doc = await db.settings.find_one({"key": "bank_accounts"}) or {}
    return doc.get("value") or [
        {"bank": "MANDIRI", "number": "1240011911816", "holder": "INTERCLOUD DIGITAL INOVASI"},
        {"bank": "BCA", "number": "4730862038", "holder": "ANANG MADIA CUGITA"},
    ]


@router.put("/admin/bank-accounts")
async def update_bank_accounts(payload: list, admin=Depends(get_current_admin)):
    db = await _get_db()
    await db.settings.update_one(
        {"key": "bank_accounts"},
        {"$set": {"key": "bank_accounts", "value": payload}},
        upsert=True,
    )
    return payload


# ---------------- Payment gateway - create + webhook ----------------
async def _payment_settings(db, provider: str) -> Optional[dict]:
    """Resolve gateway settings from either storage system:
    1. `integration_settings` (iv2, provider-keyed) - preferred;
    2. the module-hub `integrations` row (admin UI "Add Server" dialog),
       mapped into the iv2 shape. Duitku is the only mapped provider.
    Returns an iv2-shaped dict or None when not configured/enabled."""
    s = await iv2.get_settings(db, provider)
    if s and s.get("enabled") and (s.get("credentials") or {}):
        return s
    row = await db.integrations.find_one({"module": provider, "status": "enabled"})
    if row and provider == "duitku":
        cfg = _sb_dec_config(row.get("config") or {})
        if cfg.get("merchant_code") and cfg.get("api_key"):
            return {
                "provider": "duitku",
                "enabled": True,
                "credentials": {"merchant_code": cfg["merchant_code"],
                                 "api_key": cfg["api_key"]},
                "options": {"callback_url": cfg.get("callback_url") or "",
                            "return_url": cfg.get("return_url") or "",
                            "environment": cfg.get("environment") or "production"},
            }
    return None


async def _create_online_payment(db, request: Request, inv: dict, *, email: str, name: str,
                                 provider: str = "duitku", return_url: str = "") -> dict:
    """Buat transaksi hosted payment di gateway + simpan payment_link di invoice.
    Dipakai oleh flow klien (login) dan flow payment link publik (tanpa login)."""
    s = await _payment_settings(db, provider)
    if not s:
        raise HTTPException(status_code=400, detail=f"{provider} not configured")
    gw = iv2.payment_gateway(provider, s)
    # Potongan credit note: gateway hanya menagih SISA tagihan
    credit_applied = await _sum_applied_credit(db, inv["_id"])
    amount_due = int(round(float(inv.get("total") or 0) - credit_applied))
    if amount_due <= 0:
        raise HTTPException(status_code=400,
                            detail="Tagihan sudah tertutup credit note - tidak ada sisa yang perlu dibayar.")
    # Public base URL resolution: env → request headers (behind ingress).
    base = (os.environ.get("REACT_APP_BACKEND_URL") or "").strip().rstrip("/")
    if not base:
        fwd_host = request.headers.get("x-forwarded-host") or request.headers.get("host") or ""
        fwd_proto = request.headers.get("x-forwarded-proto") or "https"
        base = f"{fwd_proto}://{fwd_host}" if fwd_host else ""
    opts = s.get("options") or {}
    # Callback: explicit integration config wins, else derived from base.
    callback = (opts.get("callback_url") or "").strip()
    if not callback:
        if not base:
            raise HTTPException(status_code=500,
                                detail="Cannot determine public callback URL - set it in the Duitku integration config.")
        callback = f"{base}/api/portal/webhooks/{provider}"
    kwargs = dict(
        invoice_id=inv["number"] or str(inv["_id"]),
        amount_idr=amount_due,
        customer_email=email,
        callback_url=callback,
    )
    if provider == "duitku":
        # returnUrl is REQUIRED by the POP docs.
        r_url = return_url or (opts.get("return_url") or "").strip()
        if not r_url and base:
            r_url = f"{base}/portal/client/invoices"
        kwargs.update(return_url=r_url,
                      customer_name=name or "",
                      expiry_minutes=int(opts.get("expiry_minutes") or 1440))
    try:
        result = await gw.create_payment(**kwargs)
    except Exception as e:
        raise HTTPException(status_code=502,
                            detail=f"Gagal membuat transaksi {provider}: {type(e).__name__}: {e}")
    await db.invoices.update_one(
        {"_id": inv["_id"]},
        {"$set": {"payment_provider": provider, "payment_external_id": result.get("external_id"),
                  "payment_link": result.get("payment_url")}},
    )
    return result


@router.post("/client/invoices/{iid}/pay-online")
async def client_pay_online(iid: str, request: Request, provider: str = "duitku",
                            user=Depends(get_current_user)):
    """Create a hosted payment link for the given invoice (Duitku-only policy)."""
    db = await _get_db()
    if provider not in iv2.PAYMENT_PROVIDERS:
        raise HTTPException(status_code=400, detail="Unknown payment provider")
    if provider in _EXTRA_PAYMENT_MODULES and not bool(
            await _get_setting_value(db, "enable_extra_payment_gateways", False)):
        raise HTTPException(status_code=400,
                            detail="Hanya Duitku yang tersedia sebagai payment gateway.")
    inv = await db.invoices.find_one({"_id": _oid(iid), "user_id": ObjectId(user["id"])})
    if not inv:
        raise HTTPException(status_code=404, detail="Invoice not found")
    if inv.get("status") == "paid":
        raise HTTPException(status_code=400, detail="Invoice already paid")
    return await _create_online_payment(db, request, inv, email=user["email"],
                                        name=user.get("name") or "", provider=provider)


# ---------------- Payment link PUBLIK (tanpa login) ----------------
async def _invoice_by_pay_token(db, token: str) -> dict:
    if not token or len(token) < 16:
        raise HTTPException(status_code=404, detail="Invoice not found")
    inv = await db.invoices.find_one({"pay_token": token})
    if not inv or inv.get("status") == "cancelled":
        raise HTTPException(status_code=404, detail="Invoice not found")
    return inv


@router.get("/portal-public/pay/{token}")
async def public_pay_invoice_view(token: str):
    """Detail tagihan untuk halaman pembayaran publik - diakses via pay_token
    acak (permanen sampai lunas), tanpa autentikasi."""
    db = await _get_db()
    await _mark_overdue(db)
    inv = await _invoice_by_pay_token(db, token)
    u = await db.users.find_one({"_id": inv["user_id"]}) or {}
    bank_doc = await db.settings.find_one({"key": "bank_accounts"}) or {}
    banks = bank_doc.get("value") or [
        {"bank": "MANDIRI", "number": "1240011911816", "holder": "INTERCLOUD DIGITAL INOVASI"},
        {"bank": "BCA", "number": "4730862038", "holder": "ANANG MADIA CUGITA"},
    ]
    duitku_on = bool(await _payment_settings(db, "duitku"))
    credit_applied = await _sum_applied_credit(db, inv["_id"])
    total = float(inv.get("total") or 0)
    return {
        "number": inv.get("number", ""),
        "items": inv.get("items", []),
        "subtotal": inv.get("subtotal", 0),
        "tax_percent": inv.get("tax_percent"),
        "tax_amount": inv.get("tax_amount", 0),
        "total": inv.get("total", 0),
        "credit_applied": credit_applied,
        "amount_due": 0.0 if inv.get("status") == "paid" else max(0.0, total - credit_applied),
        "due_date": inv.get("due_date", ""),
        "status": inv.get("status", "unpaid"),
        "paid_at": inv.get("paid_at"),
        "payment_method": inv.get("payment_method"),
        "client_name": u.get("name", ""),
        "client_company": u.get("company", "") or "",
        "bank_accounts": banks,
        "duitku_enabled": duitku_on,
        "payment_link": inv.get("payment_link") if inv.get("status") != "paid" else None,
    }


@router.post("/portal-public/pay/{token}/pay-online")
async def public_pay_invoice_online(token: str, request: Request):
    """Buat link pembayaran Duitku dari halaman publik (tanpa login)."""
    db = await _get_db()
    inv = await _invoice_by_pay_token(db, token)
    if inv.get("status") == "paid":
        raise HTTPException(status_code=400, detail="Invoice sudah lunas")
    u = await db.users.find_one({"_id": inv["user_id"]}) or {}
    base = (os.environ.get("REACT_APP_BACKEND_URL") or "").strip().rstrip("/")
    return await _create_online_payment(
        db, request, inv, email=u.get("email", ""), name=u.get("name", ""),
        provider="duitku", return_url=f"{base}/pay/{token}" if base else "")


@router.post("/webhooks/{provider}")
async def payment_webhook(provider: str, request: Request):
    """Public webhook. Verifies the gateway signature before touching any invoice.

    Idempotent: the paid-transition only happens once (`status != paid` filter),
    so duplicate callback deliveries never double-fire emails, provisioning or
    service reactivation."""
    db = await _get_db()
    s = await _payment_settings(db, provider)
    if not s:
        raise HTTPException(status_code=404, detail="Unknown gateway")
    raw = await request.body()
    gw = iv2.payment_gateway(provider, s)
    try:
        if provider == "xendit":
            verified = gw.verify_webhook({k.lower(): v for k, v in request.headers.items()}, raw)
        else:
            verified = gw.verify_webhook(raw)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid webhook: {e}")

    if verified["status"] != "paid":
        return {"received": True, "status": verified["status"]}

    inv_no = verified["invoice_id"]
    # ---- Idempotent paid transition (survives duplicate callback delivery) ----
    r = await db.invoices.update_one(
        {"number": inv_no, "status": {"$ne": "paid"}},
        {"$set": {"status": "paid", "paid_at": _now(), "payment_method": provider,
                  "payment_ref": verified.get("external_id")}},
    )
    if not r.modified_count:
        exists = await db.invoices.find_one({"number": inv_no})
        return {"received": True, "status": "paid",
                "duplicate": bool(exists),
                "note": "already processed" if exists else "invoice not found"}

    inv = await db.invoices.find_one({"number": inv_no})
    user = await db.users.find_one({"_id": inv["user_id"]}) if inv else None

    # 1) Payment-received notification email (best-effort, never blocks the ACK)
    if inv and user:
        try:
            from portal import emails as _em
            await _em.on_invoice_paid(db, inv, user)
        except Exception:
            pass

    # 2) Auto-provision the linked order (same hook as manual admin mark-paid)
    if inv and inv.get("order_id"):
        try:
            await _provision_order_from_invoice(db, inv)
        except Exception:
            pass

    # 2b) Eksekusi upgrade resource yang menunggu pembayaran invoice ini
    if inv:
        try:
            await _apply_pending_upgrade(db, inv)
        except Exception:
            pass

    # 2c) Registrasi domain otomatis (RNA.id) untuk invoice registrasi domain
    if inv:
        try:
            await _auto_register_domain(db, inv)
            await _apply_domain_renewal(db, inv)
        except Exception:
            pass

    # 3) Reactivate services suspended for non-payment of THIS invoice
    reactivated = 0
    if inv:
        import re as _re
        ors = [{"user_id": inv["user_id"],
                "suspended_reason": {"$regex": f"invoice {_re.escape(inv_no)} overdue",
                                      "$options": "i"}}]
        if inv.get("service_id"):
            try:
                ors.append({"_id": _oid(inv["service_id"])})
            except Exception:
                pass
        res = await db.services.update_many(
            {"status": "suspended", "$or": ors},
            {"$set": {"status": "active", "reactivated_at": _now(),
                      "reactivated_reason": f"invoice {inv_no} paid via {provider}"},
             "$unset": {"suspended_at": "", "suspended_reason": ""}},
        )
        reactivated = res.modified_count

    return {"received": True, "status": "paid", "reactivated_services": reactivated}
