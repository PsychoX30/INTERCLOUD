"""Domains: RNA.id/RDASH whois, availability, order and renewal.

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
from .shared import _get_db, _get_setting_value, _insert_numbered, _iso, _now, _oid  # noqa: E402

router = APIRouter()


# ---------------- Client domains (RNA.id / RDASH) ----------------
_DOMAIN_NAME_RE = re.compile(r"^(?=.{4,253}$)([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,}$")


async def _rna_client(db):
    s = await iv2.get_settings(db, "rna")
    if s and s.get("enabled"):
        return iv2.RdashClient(s)
    return None


async def _rdap_lookup(domain: str) -> dict:
    """Public RDAP fallback (rdap.org) so WHOIS is live even without reseller creds."""
    import httpx
    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as c:
        r = await c.get(f"https://rdap.org/domain/{domain}",
                        headers={"Accept": "application/rdap+json"})
    if r.status_code == 404:
        return {"registered": False, "registrar": "", "status": [], "created": "",
                "updated": "", "expiry": "", "nameservers": [], "dnssec": "unsigned"}
    r.raise_for_status()
    j = r.json()
    events = {e.get("eventAction"): (e.get("eventDate") or "")[:10] for e in j.get("events", [])}
    registrar = ""
    for ent in j.get("entities", []):
        if "registrar" in (ent.get("roles") or []):
            for item in (ent.get("vcardArray") or [None, []])[1]:
                if item and item[0] == "fn" and len(item) > 3:
                    registrar = item[3]
    return {
        "registered": True,
        "registrar": registrar,
        "status": j.get("status") or [],
        "created": events.get("registration", ""),
        "updated": events.get("last changed", ""),
        "expiry": events.get("expiration", ""),
        "nameservers": [n.get("ldhName", "").lower() for n in j.get("nameservers", []) if n.get("ldhName")],
        "dnssec": "signed" if (j.get("secureDNS") or {}).get("delegationSigned") else "unsigned",
    }


@router.get("/client/domains/whois")
async def client_domain_whois(domain: str, user=Depends(get_current_user)):
    db = await _get_db()
    name = domain.strip().lower()
    if not _DOMAIN_NAME_RE.match(name):
        raise HTTPException(status_code=400, detail="Nama domain tidak valid")
    rna = await _rna_client(db)
    if rna:
        try:
            w = await rna.whois(name)
            return {
                "live": True, "source": "rna",
                "domain": w.get("name") or name,
                "registered": not bool(w.get("available")),
                "registrar": w.get("registrar", ""),
                "status": w.get("status") or [],
                "created": (w.get("created_at") or "")[:10],
                "updated": (w.get("updated_at") or "")[:10],
                "expiry": (w.get("expired_at") or "")[:10],
                "registrant": "REDACTED FOR PRIVACY",
                "nameservers": w.get("nameserver") or [],
                "dnssec": w.get("dnssec") or "unsigned",
            }
        except Exception as e:
            logging.getLogger("portal.domains").warning("RNA whois gagal untuk %s: %s", name, e)
    try:
        data = await _rdap_lookup(name)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"WHOIS lookup gagal: {str(e)[:120]}")
    return {"live": True, "source": "rdap", "domain": name,
            "registrant": "REDACTED FOR PRIVACY", **data}


_TLD_PRICES_IDR = {".com": 165000, ".id": 250000, ".co.id": 300000, ".net": 185000,
                   ".org": 175000, ".my.id": 25000, ".web.id": 55000, ".biz.id": 55000}


def _tld_price(name: str) -> int:
    tld = next((t for t in sorted(_TLD_PRICES_IDR, key=len, reverse=True) if name.endswith(t)), None)
    return _TLD_PRICES_IDR.get(tld, 95000)


async def _dns_domain_taken(name: str) -> bool:
    """DNS fallback: NXDOMAIN on the NS query means the domain is very likely available."""
    import dns.asyncresolver
    import dns.resolver
    resolver = dns.asyncresolver.Resolver()
    resolver.lifetime = 4
    try:
        await resolver.resolve(name, "NS")
        return True
    except dns.resolver.NXDOMAIN:
        return False
    except Exception:
        return True


async def _check_domains_availability(db, names: list) -> list:
    """Availability via RNA.id bila aktif; fallback live DNS check."""
    rna = await _rna_client(db)

    async def _one(n: str) -> dict:
        if rna:
            try:
                res = await rna.availability(n)
                item = res[0] if res else {}
                return {"domain": n, "available": bool(item.get("available")), "source": "rna"}
            except Exception:
                pass
        try:
            taken = await _dns_domain_taken(n)
            return {"domain": n, "available": not taken, "source": "dns"}
        except Exception:
            return {"domain": n, "available": None, "source": "dns"}

    out = list(await asyncio.gather(*(_one(n) for n in names)))
    for r in out:
        r["price"] = _tld_price(r["domain"])
    return out


@router.get("/client/domains/suggest")
async def client_domain_suggest(q: str, user=Depends(get_current_user)):
    db = await _get_db()
    base = re.sub(r"[^a-z0-9-]", "", q.strip().lower().split(".")[0])[:40].strip("-")
    if len(base) < 2:
        raise HTTPException(status_code=400, detail="Kata kunci minimal 2 karakter")
    variants = [f"get{base}.com", f"{base}online.com", f"{base}-id.com", f"my{base}.id",
                f"{base}store.com", f"{base}.web.id", f"{base}hq.com", f"{base}.biz.id"]
    results = await _check_domains_availability(db, variants)
    return {"live": True, "query": base, "suggestions": results}


@router.post("/client/domains/order")
async def client_domain_order(payload: m.DomainOrderIn, request: Request, user=Depends(get_current_user)):
    """Order registrasi domain: buat record + invoice; registrasi otomatis jalan saat lunas."""
    db = await _get_db()
    name = payload.domain.strip().lower()
    if not _DOMAIN_NAME_RE.match(name):
        raise HTTPException(status_code=400, detail="Nama domain tidak valid")
    existing = await db.domains.find_one({"domain": name, "status": {"$in": ["pending", "active", "expiring"]}})
    if existing:
        raise HTTPException(status_code=400, detail="Domain sudah terdaftar dalam sistem")
    chk = (await _check_domains_availability(db, [name]))[0]
    if chk["available"] is False:
        raise HTTPException(status_code=400, detail="Domain tidak tersedia untuk registrasi")
    price = _tld_price(name) * payload.years
    tax_percent = float(await _get_setting_value(db, "default_tax_percent", 11.0))
    tax = round(price * tax_percent / 100.0, 2)
    due = (datetime.now(timezone.utc) + timedelta(days=3)).date().isoformat()
    dom = {
        "user_id": ObjectId(user["id"]),
        "domain": name,
        "tld": "." + name.split(".", 1)[1],
        "status": "pending",
        "registrar": "rna",
        "years": payload.years,
        "auto_renew": payload.auto_renew,
        "registered_at": None,
        "expires_at": None,
        "nameservers": [],
        "price": price,
        "invoice_id": None,
        "order_ref": None,
        "created_at": _now(),
    }
    dr = await db.domains.insert_one(dom)
    inv = {
        "user_id": ObjectId(user["id"]),
        "items": [{"description": f"Registrasi domain {name} ({payload.years} tahun)",
                   "qty": 1, "price": price, "total": price}],
        "subtotal": price,
        "tax_percent": tax_percent,
        "tax_amount": tax,
        "total": round(price + tax, 2),
        "due_date": due,
        "status": "unpaid",
        "payment_method": None,
        "paid_at": None,
        "notes": f"Registrasi domain {name} - diproses otomatis setelah pembayaran.",
        "domain_id": str(dr.inserted_id),
        "created_at": _now(),
    }
    inv = await _insert_numbered(db, "invoices", "INV", inv)
    await db.domains.update_one({"_id": dr.inserted_id}, {"$set": {"invoice_id": str(inv["_id"])}})
    await log_audit(db, actor=user, action="client_domain.order_created", category="domains",
                    target_type="domain", target_id=str(dr.inserted_id), target_label=name,
                    metadata={"invoice": inv["number"], "total": inv["total"], "years": payload.years},
                    request=request)
    return {"ok": True, "domain_id": str(dr.inserted_id), "invoice_id": str(inv["_id"]),
            "number": inv["number"], "total": inv["total"], "due_date": due}


async def _auto_register_domain(db, inv: dict) -> bool:
    """Registrasi domain otomatis di RNA.id setelah invoice registrasi lunas. Idempotent
    (hanya memproses domain berstatus pending)."""
    if not inv.get("domain_id"):
        return False
    try:
        dom = await db.domains.find_one({"_id": _oid(inv["domain_id"]), "status": "pending"})
    except Exception:
        return False
    if not dom:
        return False
    now = datetime.now(timezone.utc)
    fallback_expiry = (now + timedelta(days=365 * int(dom.get("years", 1)))).date().isoformat()
    rna = await _rna_client(db)
    if rna:
        try:
            res = await rna.register(dom["domain"], int(dom.get("years", 1)))
            ns = [res.get(f"nameserver_{i}") for i in range(1, 6) if res.get(f"nameserver_{i}")]
            await db.domains.update_one({"_id": dom["_id"]}, {"$set": {
                "status": "active",
                "registered_at": now.date().isoformat(),
                "expires_at": (res.get("expired_at") or "")[:10] or fallback_expiry,
                "nameservers": ns or rna.default_ns,
                "order_ref": str(res.get("id") or ""),
                "provision_note": "Registered live via RNA.id (RDASH).",
            }})
            return True
        except Exception as e:
            await db.domains.update_one({"_id": dom["_id"]}, {"$set": {
                "provision_note": f"Registrasi RNA.id gagal: {str(e)[:150]}. Perlu tindak lanjut manual.",
            }})
            return False
    await db.domains.update_one({"_id": dom["_id"]}, {"$set": {
        "status": "active",
        "registered_at": now.date().isoformat(),
        "expires_at": fallback_expiry,
        "nameservers": ["ns1.intercloud-digital.com", "ns2.intercloud-digital.com"],
        "provision_note": "Integrasi RNA.id belum aktif - dicatat internal, submit manual ke registrar.",
    }})
    return True


@router.post("/client/domains/{did}/renew")
async def client_domain_renew(did: str, payload: m.DomainRenewIn, request: Request,
                              user=Depends(get_current_user)):
    """Order perpanjangan domain: buat invoice; perpanjangan otomatis jalan saat lunas."""
    db = await _get_db()
    dom = await db.domains.find_one({"_id": _oid(did), "user_id": ObjectId(user["id"])})
    if not dom:
        raise HTTPException(status_code=404, detail="Domain tidak ditemukan")
    if dom.get("status") not in ("active", "expiring", "expired"):
        raise HTTPException(status_code=400, detail="Domain belum bisa diperpanjang (masih pending)")
    if dom.get("pending_renewal"):
        raise HTTPException(status_code=400, detail="Masih ada perpanjangan yang menunggu pembayaran")
    name = dom["domain"]
    price = _tld_price(name) * payload.years
    tax_percent = float(await _get_setting_value(db, "default_tax_percent", 11.0))
    tax = round(price * tax_percent / 100.0, 2)
    due = (datetime.now(timezone.utc) + timedelta(days=7)).date().isoformat()
    inv = {
        "user_id": ObjectId(user["id"]),
        "items": [{"description": f"Perpanjangan domain {name} ({payload.years} tahun)",
                   "qty": 1, "price": price, "total": price}],
        "subtotal": price,
        "tax_percent": tax_percent,
        "tax_amount": tax,
        "total": round(price + tax, 2),
        "due_date": due,
        "status": "unpaid",
        "payment_method": None,
        "paid_at": None,
        "notes": f"Perpanjangan domain {name} - diproses otomatis setelah pembayaran.",
        "domain_renewal": {"domain_id": str(dom["_id"]), "years": payload.years},
        "created_at": _now(),
    }
    inv = await _insert_numbered(db, "invoices", "INV", inv)
    await db.domains.update_one({"_id": dom["_id"]}, {"$set": {
        "pending_renewal": {"years": payload.years, "invoice_id": str(inv["_id"]),
                            "requested_at": _now()}}})
    await log_audit(db, actor=user, action="client_domain.renew_requested", category="domains",
                    target_type="domain", target_id=str(dom["_id"]), target_label=name,
                    metadata={"invoice": inv["number"], "total": inv["total"], "years": payload.years},
                    request=request)
    return {"ok": True, "domain_id": str(dom["_id"]), "invoice_id": str(inv["_id"]),
            "number": inv["number"], "total": inv["total"], "due_date": due}


def _add_years(date_str: str, years: int) -> str:
    base = None
    try:
        base = datetime.strptime((date_str or "")[:10], "%Y-%m-%d")
    except Exception:
        base = datetime.now(timezone.utc)
    if base.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc):
        base = datetime.now(timezone.utc)
    try:
        return base.replace(year=base.year + years).date().isoformat()
    except ValueError:
        return base.replace(year=base.year + years, day=28).date().isoformat()


async def _apply_domain_renewal(db, inv: dict) -> bool:
    """Perpanjangan domain otomatis (RNA.id) setelah invoice lunas. Idempotent
    (hanya memproses domain yang pending_renewal-nya menunjuk ke invoice ini)."""
    ren = inv.get("domain_renewal")
    if not ren:
        return False
    try:
        dom = await db.domains.find_one({"_id": _oid(ren["domain_id"]),
                                         "pending_renewal.invoice_id": str(inv["_id"])})
    except Exception:
        return False
    if not dom:
        return False
    years = int(ren.get("years", 1))
    new_expiry = _add_years(dom.get("expires_at") or "", years)
    note = "Integrasi RNA.id belum aktif - perpanjangan dicatat internal, submit manual ke registrar."
    rna = await _rna_client(db)
    if rna and dom.get("order_ref"):
        try:
            res = await rna.renew(dom["order_ref"], years, (dom.get("expires_at") or "")[:10])
            new_expiry = (res.get("expired_at") or "")[:10] or new_expiry
            note = "Renewed live via RNA.id (RDASH)."
        except Exception as e:
            await db.domains.update_one({"_id": dom["_id"]}, {"$set": {
                "provision_note": f"Perpanjangan RNA.id gagal: {str(e)[:150]}. Perlu tindak lanjut manual."}})
            return False
    await db.domains.update_one({"_id": dom["_id"]}, {
        "$set": {"status": "active", "expires_at": new_expiry, "provision_note": note},
        "$unset": {"pending_renewal": ""},
    })
    return True


def _serialize_domain(d: dict) -> dict:
    return {
        "id": str(d["_id"]),
        "domain": d.get("domain", ""),
        "tld": d.get("tld", ""),
        "status": d.get("status", "pending"),
        "registrar": d.get("registrar", "rna"),
        "years": d.get("years", 1),
        "registered_at": d.get("registered_at"),
        "expires_at": d.get("expires_at"),
        "auto_renew": d.get("auto_renew", True),
        "nameservers": d.get("nameservers", []),
        "price": d.get("price", 0),
        "invoice_id": d.get("invoice_id"),
        "pending_renewal": bool(d.get("pending_renewal")),
        "renewal_invoice_id": (d.get("pending_renewal") or {}).get("invoice_id"),
        "provision_note": d.get("provision_note", ""),
        "created_at": _iso(d.get("created_at", "")),
    }


@router.get("/client/domains")
async def client_domains_list(user=Depends(get_current_user)):
    db = await _get_db()
    docs = await db.domains.find({"user_id": ObjectId(user["id"])}).sort("created_at", -1).to_list(500)
    return [_serialize_domain(d) for d in docs]


@router.get("/client/domains/check")
async def client_domain_check(domain: str, user=Depends(get_current_user)):
    """Cek ketersediaan live: nama polos → semua TLD populer; nama ber-TLD → exact match."""
    db = await _get_db()
    raw = domain.strip().lower()
    base = re.sub(r"[^a-z0-9-]", "", raw.split(".")[0])[:63].strip("-")
    if len(base) < 2:
        raise HTTPException(status_code=400, detail="Nama domain minimal 2 karakter")
    if "." in raw and _DOMAIN_NAME_RE.match(raw):
        names = [raw]
    else:
        names = [f"{base}{tld}" for tld in _TLD_PRICES_IDR]
    results = await _check_domains_availability(db, names)
    return {"live": True, "query": raw, "results": results}
