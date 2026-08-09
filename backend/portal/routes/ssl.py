"""SSL: RNA.id/RDASH SSL certificate resale.

Catalog, pricing, order creation, and post-payment provisioning.
All prices are RNA base prices with portal-side markup applied.
"""
import logging
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from bson import ObjectId

from .. import models as m
from .. import integrations_v2 as iv2
from ..auth import get_current_user, get_current_admin, require_roles
from ..audit import log_audit
from ..secretbox import enc_value as _sb_enc, dec_value as _sb_dec
from .shared import _get_db, _get_setting_value, _insert_numbered, _iso, _now, _oid  # noqa: E402

router = APIRouter()


async def _rna_client(db):
    s = await iv2.get_settings(db, "rna")
    if s and s.get("enabled"):
        return iv2.RdashClient(s)
    return None


_SSL_PRICING_KEY = "ssl_pricing"
_SSL_DEFAULT_MARKUP_PCT = 7.0


async def _ssl_markup_pct(db) -> float:
    """Return the SSL-specific markup percentage, or domain markup as fallback."""
    doc = await db.settings.find_one({"key": _SSL_PRICING_KEY})
    if doc and doc.get("value", {}).get("markup_pct") is not None:
        return float(doc["value"]["markup_pct"])
    # Fallback: inherit the domain markup so the two stay in sync when SSL markup
    # has never been explicitly configured.
    domain_doc = await db.settings.find_one({"key": "domain_pricing"})
    if domain_doc and domain_doc.get("value", {}).get("markup_pct") is not None:
        return float(domain_doc["value"]["markup_pct"])
    return _SSL_DEFAULT_MARKUP_PCT


# ---------------------------------------------------------------------------
#  Client endpoints
# ---------------------------------------------------------------------------

@router.get("/client/ssl/products")
async def client_ssl_catalog(request: Request, user=Depends(get_current_user)):
    """Return SSL product catalog with portal-side marked-up prices."""
    db = await _get_db()
    rna = await _rna_client(db)
    if not rna:
        return {"products": [], "source": "offline"}
    try:
        raw = await rna.ssl_prices(limit=50)
        markup = await _ssl_markup_pct(db)
        priced = rna.ssl_prices_with_markup(raw, markup_pct=markup)
        return {"products": priced, "source": "rna"}
    except Exception as e:
        logging.getLogger("portal.ssl").warning("SSL catalog fetch failed: %s", e)
        return {"products": [], "source": "error", "error": str(e)[:200]}


@router.post("/client/ssl/orders")
async def client_ssl_order(payload: m.SSLOrderIn, request: Request,
                           user=Depends(get_current_user)):
    """Create a pending SSL certificate order.  Provisioning runs after the
    linked invoice is paid (same pattern as domain registration)."""
    db = await _get_db()
    rna = await _rna_client(db)
    if not rna:
        raise HTTPException(503, "Integrasi RNA.id belum aktif.")

    # Resolve product price from RNA
    raw = await rna.ssl_prices(limit=50)
    markup = await _ssl_markup_pct(db)
    priced = rna.ssl_prices_with_markup(raw, markup_pct=markup)
    product = next((p for p in priced if p["product_id"] == payload.product_id), None)
    if not product:
        raise HTTPException(400, "Produk SSL tidak ditemukan.")

    period_key = str(payload.period_months)
    price = product["terms"].get(period_key)
    if not price:
        raise HTTPException(400, f"Periode {payload.period_months} bulan tidak tersedia untuk produk ini.")

    tax_percent = float(await _get_setting_value(db, "default_tax_percent", 11.0))
    tax = round(price * tax_percent / 100.0, 2)
    due = (datetime.now(timezone.utc) + timedelta(days=3)).date().isoformat()

    # RDASH requires complete administrative + technical contacts. Source them
    # from the authenticated user's persisted profile and fail before invoicing
    # when the profile is incomplete (never submit placeholder/empty contacts).
    profile = await db.users.find_one({"_id": ObjectId(user["id"])}) or {}
    full_name = str(profile.get("name") or "").strip()
    name_parts = full_name.split(None, 1)
    first_name = name_parts[0] if name_parts else ""
    last_name = name_parts[1] if len(name_parts) > 1 else first_name
    contact = {
        "firstname": first_name,
        "lastname": last_name,
        "organization": str(profile.get("company") or full_name).strip(),
        "address": str(profile.get("address_line1") or "").strip(),
        "phone": str(profile.get("phone") or "").strip(),
        "title": str(profile.get("attention") or "Owner").strip(),
        "email": str(profile.get("email") or "").strip(),
        "city": str(profile.get("city") or "").strip(),
        "country": "ID",
        "postal_code": str(profile.get("postal_code") or "").strip(),
    }
    missing = [key for key, value in contact.items() if not value]
    if missing:
        labels = {"firstname": "nama", "lastname": "nama belakang", "organization": "perusahaan",
                  "address": "alamat", "phone": "telepon", "email": "email", "city": "kota",
                  "postal_code": "kode pos"}
        raise HTTPException(400, "Lengkapi profil sebelum membeli SSL: " + ", ".join(labels.get(x, x) for x in missing))
    if payload.dcv_method == "email" and not payload.dcv_email:
        raise HTTPException(400, "Email validasi wajib diisi untuk metode DCV email.")

    # Store encrypted CSR and a contact snapshot used after invoice payment.
    order_doc = {
        "user_id": ObjectId(user["id"]),
        "product_id": payload.product_id,
        "product_name": product["name"],
        "domain": payload.domain.strip().lower(),
        "period_months": payload.period_months,
        "dcv_method": payload.dcv_method,
        "dcv_email": payload.dcv_email,
        "contact": contact,
        "csr_code_enc": _sb_enc(payload.csr_code),
        "status": "pending",
        "provider_order_id": None,
        "provider_status": None,
        "certificate": None,
        "price": price,
        "invoice_id": None,
        "created_at": _now(),
    }
    r = await db.ssl_orders.insert_one(order_doc)

    inv = await _insert_numbered(db, "invoices", "INV", {
        "user_id": ObjectId(user["id"]),
        "items": [{
            "description": f"SSL {product['name']} - {payload.domain} ({payload.period_months} bulan)",
            "qty": 1, "price": price, "total": price,
        }],
        "subtotal": price, "tax_percent": tax_percent, "tax_amount": tax,
        "total": round(price + tax, 2), "due_date": due, "status": "unpaid",
        "payment_method": None, "paid_at": None,
        "notes": f"SSL {product['name']} untuk {payload.domain} - diproses otomatis setelah pembayaran.",
        "ssl_order_id": str(r.inserted_id), "ssl_order": True, "created_at": _now(),
    })
    await db.ssl_orders.update_one({"_id": r.inserted_id}, {"$set": {"invoice_id": str(inv["_id"])}})
    await log_audit(db, actor=user, action="ssl.order_created", category="ssl",
                    target_type="ssl_order", target_id=str(r.inserted_id),
                    target_label=payload.domain,
                    metadata={"product": product["name"], "period": payload.period_months,
                              "invoice": inv["number"], "total": inv["total"]},
                    request=request)
    return {"ok": True, "order_id": str(r.inserted_id), "invoice_id": str(inv["_id"]),
            "number": inv["number"], "total": inv["total"], "due_date": due}


@router.get("/client/ssl/orders")
async def client_ssl_orders(user=Depends(get_current_user)):
    db = await _get_db()
    orders = await db.ssl_orders.find({"user_id": ObjectId(user["id"])}).sort("created_at", -1).to_list(500)
    return {"orders": [_serialize_ssl_order(o) for o in orders]}


@router.get("/client/ssl/orders/{oid}")
async def client_ssl_order_detail(oid: str, user=Depends(get_current_user)):
    db = await _get_db()
    order = await db.ssl_orders.find_one({"_id": _oid(oid), "user_id": ObjectId(user["id"])})
    if not order:
        raise HTTPException(404, "Order SSL tidak ditemukan.")
    return _serialize_ssl_order(order)


# ---------------------------------------------------------------------------
#  Admin endpoints
# ---------------------------------------------------------------------------

@router.get("/admin/ssl/markup")
async def admin_ssl_markup_get(admin=Depends(get_current_admin)):
    """Return the SSL-specific markup. Restricted to role=admin."""
    db = await _get_db()
    doc = await db.settings.find_one({"key": _SSL_PRICING_KEY})
    configured = bool(doc and doc.get("value", {}).get("markup_pct") is not None)
    return {"markup_pct": await _ssl_markup_pct(db), "configured": configured}


@router.post("/admin/ssl/markup")
async def admin_ssl_markup_set(payload: dict, request: Request,
                               admin=Depends(get_current_admin)):
    """Set SSL markup independently from domain markup. Admin only."""
    try:
        markup = float(payload.get("markup_pct"))
    except (TypeError, ValueError):
        raise HTTPException(400, "markup_pct wajib berupa angka")
    if markup < 0 or markup > 100:
        raise HTTPException(400, "markup_pct harus 0-100")

    db = await _get_db()
    previous = await _ssl_markup_pct(db)
    await db.settings.update_one(
        {"key": _SSL_PRICING_KEY},
        {"$set": {"value": {"markup_pct": markup, "updated_at": _now(),
                             "updated_by": str(admin["id"])}}},
        upsert=True,
    )
    await log_audit(
        db, actor=admin, action="ssl.markup_updated", category="ssl",
        target_type="setting", target_id=_SSL_PRICING_KEY,
        target_label="SSL pricing markup",
        before={"markup_pct": previous}, after={"markup_pct": markup},
        request=request,
    )
    return {"ok": True, "markup_pct": markup}

@router.get("/admin/ssl/orders")
async def admin_ssl_orders(admin=Depends(get_current_admin)):
    db = await _get_db()
    orders = await db.ssl_orders.find().sort("created_at", -1).to_list(500)
    return {"orders": [_serialize_ssl_order(o) for o in orders]}


@router.put("/admin/ssl/orders/{oid}/status")
async def admin_ssl_order_status(oid: str, payload: m.SSLStatusIn,
                                 request: Request, admin=Depends(get_current_admin)):
    db = await _get_db()
    order = await db.ssl_orders.find_one({"_id": _oid(oid)})
    if not order:
        raise HTTPException(404, "Order SSL tidak ditemukan.")
    await db.ssl_orders.update_one({"_id": _oid(oid)}, {"$set": {"status": payload.status}})
    await log_audit(db, actor=admin, action="ssl.status_updated", category="ssl",
                    target_type="ssl_order", target_id=oid,
                    target_label=order.get("domain", ""),
                    metadata={"old_status": order.get("status"), "new_status": payload.status},
                    request=request)
    return {"ok": True, "status": payload.status}


# ---------------------------------------------------------------------------
#  Provisioning helper (called from billing hook)
# ---------------------------------------------------------------------------

async def _provision_ssl_order(db, inv: dict) -> bool:
    """Submit a pending SSL order to RDASH after invoice payment. Idempotent."""
    if not inv.get("ssl_order"):
        return False
    try:
        order = await db.ssl_orders.find_one({"_id": _oid(inv["ssl_order_id"]), "status": "pending"})
    except Exception:
        return False
    if not order:
        return False

    rna = await _rna_client(db)
    if not rna:
        await db.ssl_orders.update_one({"_id": order["_id"]}, {"$set": {
            "provision_note": "Integrasi RNA.id belum aktif - submit manual ke registrar.",
        }})
        return False

    # Resolve RNA customer (uses same fallback as domain registration)
    from .domains import _resolve_rna_customer  # noqa: E402
    try:
        cust = await _resolve_rna_customer(db, rna, order.get("user_id"))
        customer_id = cust["customer_id"]
    except Exception:
        customer_id = "35284"

    csr_code = _sb_dec(order.get("csr_code_enc") or "")
    contact = order.get("contact") or {}
    try:
        res = await rna.ssl_order_create(
            ssl_product_id=int(order["product_id"]),
            customer_id=int(customer_id),
            dcv_method=order.get("dcv_method", "dns"),
            dcv_email=order.get("dcv_email") or "",
            period=order["period_months"],
            csr_code=csr_code,
            admin_firstname=contact.get("firstname", ""),
            admin_lastname=contact.get("lastname", ""),
            admin_organization=contact.get("organization", ""),
            admin_address=contact.get("address", ""),
            admin_phone=contact.get("phone", ""),
            admin_title=contact.get("title", "Owner"),
            admin_email=contact.get("email", ""),
            admin_city=contact.get("city", ""),
            admin_country=contact.get("country", "ID"),
            admin_postal_code=contact.get("postal_code", ""),
            tech_firstname=contact.get("firstname", ""),
            tech_lastname=contact.get("lastname", ""),
            tech_organization=contact.get("organization", ""),
            tech_address=contact.get("address", ""),
            tech_phone=contact.get("phone", ""),
            tech_title=contact.get("title", "Owner"),
            tech_email=contact.get("email", ""),
            tech_city=contact.get("city", ""),
            tech_country=contact.get("country", "ID"),
            tech_postal_code=contact.get("postal_code", ""),
        )
        # SSL issuance is asynchronous — stay pending until the provider reports
        # certificate issued. The admin status endpoint flips to active when
        # download() returns a real cert.
        await db.ssl_orders.update_one({"_id": order["_id"]}, {"$set": {
            "status": "pending",
            "provider_order_id": str(res.get("id") or ""),
            "provider_status": res.get("status") or "pending",
            "provision_note": "Order diterima RNA.id (RDASH), sertifikat diterbitkan setelah validasi domain.",
        }})
        return True
    except Exception as e:
        await db.ssl_orders.update_one({"_id": order["_id"]}, {"$set": {
            "provision_note": f"SSL provisioning gagal: {str(e)[:150]}. Perlu tindak lanjut manual.",
        }})
        return False


# ---------------------------------------------------------------------------
#  Serializer
# ---------------------------------------------------------------------------

def _serialize_ssl_order(o: dict) -> dict:
    return {
        "id": str(o["_id"]),
        "user_id": str(o.get("user_id", "")),
        "product_id": o.get("product_id", ""),
        "product_name": o.get("product_name", ""),
        "domain": o.get("domain", ""),
        "period_months": o.get("period_months"),
        "dcv_method": o.get("dcv_method", "dns"),
        "dcv_email": o.get("dcv_email"),
        "status": o.get("status", "pending"),
        "provider_order_id": o.get("provider_order_id"),
        "provider_status": o.get("provider_status"),
        "price": o.get("price", 0),
        "invoice_id": o.get("invoice_id"),
        "provision_note": o.get("provision_note", ""),
        "created_at": _iso(o.get("created_at", "")),
    }