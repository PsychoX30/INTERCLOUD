"""Duitku payment round-trip — create-transaction, signed callback, idempotency.

Covers the hard-constraint contract:
  * valid signed callback (HMAC-SHA256 per current POP docs) marks the invoice
    paid exactly once: status=paid, payment_method="duitku", paid_at set;
  * services suspended for non-payment of that invoice flip back to active;
  * the payment_received email fires exactly once;
  * duplicate callback delivery is a no-op ({duplicate: true});
  * invalid signature → 4xx and the invoice is NOT mutated;
  * legacy MD5 signature still accepted (Duitku migration window);
  * Midtrans/Xendit are refused while `enable_extra_payment_gateways` is off.

Credentials are read from the `integrations` collection at runtime — never
hardcoded here. Tests skip cleanly when Duitku isn't configured.
"""
from __future__ import annotations
import os
import hmac
import hashlib
import uuid
from datetime import datetime, timezone, timedelta

import pytest
import requests
from pymongo import MongoClient

API = (os.environ.get("REACT_APP_BACKEND_URL") or "http://localhost:8001").rstrip("/") + "/api/portal"
ADMIN_EMAIL = "admin@intercloud-digital.com"
ADMIN_PASS = "AdminIntercloud2026!"

_db = MongoClient(os.environ.get("MONGO_URL", "mongodb://localhost:27017"))[
    os.environ.get("DB_NAME", "intercloud_portal")]

_duitku_row = _db.integrations.find_one({"module": "duitku", "status": "enabled"})
pytestmark = pytest.mark.skipif(
    not (_duitku_row and (_duitku_row.get("config") or {}).get("api_key")),
    reason="Duitku integration not configured in this environment")

from portal.secretbox import dec_value as _dec  # decrypt at-rest encrypted secrets

MC = _dec(((_duitku_row or {}).get("config") or {}).get("merchant_code", ""))
KEY = _dec(((_duitku_row or {}).get("config") or {}).get("api_key", ""))


def _login(email, pw):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": pw}, timeout=15)
    r.raise_for_status()
    return r.json()["token"]


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}"}


def _hmac_sig(amount: str, order_id: str) -> str:
    return hmac.new(KEY.encode(), f"{MC}{amount}{order_id}".encode(), hashlib.sha256).hexdigest()


def _md5_sig(amount: str, order_id: str) -> str:
    return hashlib.md5(f"{MC}{amount}{order_id}{KEY}".encode()).hexdigest()


@pytest.fixture(scope="module")
def admin_tok():
    return _login(ADMIN_EMAIL, ADMIN_PASS)


@pytest.fixture(scope="module")
def client_user(admin_tok):
    email = f"pytest-duitku-{uuid.uuid4().hex[:8]}@example.com"
    r = requests.post(f"{API}/admin/users", headers=_hdr(admin_tok), timeout=15,
                      json={"name": "Pytest Duitku", "email": email,
                            "password": "PytestDuitku2026!", "role": "client"})
    assert r.status_code in (200, 201), r.text
    doc = _db.users.find_one({"email": email})
    yield doc
    _db.services.delete_many({"user_id": doc["_id"]})
    _db.invoices.delete_many({"user_id": doc["_id"]})
    requests.delete(f"{API}/admin/users/{doc['_id']}", headers=_hdr(admin_tok), timeout=15)


def _make_invoice(admin_tok, client_user, amount=15000, tag="duitku"):
    due = (datetime.now(timezone.utc) + timedelta(days=7)).date().isoformat()
    r = requests.post(f"{API}/admin/invoices", headers=_hdr(admin_tok), timeout=15, json={
        "user_id": str(client_user["_id"]),
        "items": [{"description": f"pytest {tag}", "qty": 1,
                   "unit_price": amount, "total": amount}],
        "tax_percent": 0, "due_date": due, "notes": f"pytest-{tag}"})
    assert r.status_code == 200, r.text
    return r.json()


def test_happy_path_callback_marks_paid_and_reactivates(admin_tok, client_user):
    inv = _make_invoice(admin_tok, client_user)
    # Plant a service suspended for non-payment of THIS invoice
    svc_id = _db.services.insert_one({
        "user_id": client_user["_id"], "product_id": "x", "product_name": "VPS T",
        "category": "vps", "name": "pytest-suspended", "status": "suspended",
        "suspended_at": datetime.now(timezone.utc).isoformat(),
        "suspended_reason": f"invoice {inv['number']} overdue >8d",
        "start_date": "2026-01-01", "next_renewal": "2099-01-01",
        "price_monthly": 15000, "config": {},
        "created_at": datetime.now(timezone.utc).isoformat()}).inserted_id

    amount = str(int(inv["total"]))
    mails_before = _db.email_logs.count_documents({"event_key": "payment_received"})
    form = {"merchantCode": MC, "amount": amount, "merchantOrderId": inv["number"],
            "resultCode": "00", "reference": "PYTESTREF1",
            "signature": _hmac_sig(amount, inv["number"])}
    r = requests.post(f"{API}/webhooks/duitku", data=form, timeout=20)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "paid"
    assert body["reactivated_services"] == 1

    d = _db.invoices.find_one({"number": inv["number"]})
    assert d["status"] == "paid"
    assert d["payment_method"] == "duitku"
    assert d["paid_at"]
    svc = _db.services.find_one({"_id": svc_id})
    assert svc["status"] == "active"
    assert "suspended_reason" not in svc
    assert svc["reactivated_reason"].startswith(f"invoice {inv['number']}")
    assert _db.email_logs.count_documents({"event_key": "payment_received"}) == mails_before + 1

    # ---- duplicate delivery: must not double-fire anything ----
    r2 = requests.post(f"{API}/webhooks/duitku", data=form, timeout=20)
    assert r2.status_code == 200
    assert r2.json().get("duplicate") is True
    assert _db.email_logs.count_documents({"event_key": "payment_received"}) == mails_before + 1


def test_invalid_signature_rejected_without_mutation(admin_tok, client_user):
    inv = _make_invoice(admin_tok, client_user, amount=12000, tag="badsig")
    amount = str(int(inv["total"]))
    form = {"merchantCode": MC, "amount": amount, "merchantOrderId": inv["number"],
            "resultCode": "00", "reference": "PYTESTBAD",
            "signature": "0" * 64}
    r = requests.post(f"{API}/webhooks/duitku", data=form, timeout=20)
    assert r.status_code == 400
    d = _db.invoices.find_one({"number": inv["number"]})
    assert d["status"] == "unpaid"
    assert d.get("paid_at") is None


def test_legacy_md5_signature_accepted(admin_tok, client_user):
    inv = _make_invoice(admin_tok, client_user, amount=10000, tag="md5")
    amount = str(int(inv["total"]))
    form = {"merchantCode": MC, "amount": amount, "merchantOrderId": inv["number"],
            "resultCode": "00", "reference": "PYTESTMD5",
            "signature": _md5_sig(amount, inv["number"])}
    r = requests.post(f"{API}/webhooks/duitku", data=form, timeout=20)
    assert r.status_code == 200
    assert r.json()["status"] == "paid"


def test_failed_result_code_does_not_mark_paid(admin_tok, client_user):
    inv = _make_invoice(admin_tok, client_user, amount=11000, tag="failed")
    amount = str(int(inv["total"]))
    form = {"merchantCode": MC, "amount": amount, "merchantOrderId": inv["number"],
            "resultCode": "02", "reference": "PYTESTFAIL",
            "signature": _hmac_sig(amount, inv["number"])}
    r = requests.post(f"{API}/webhooks/duitku", data=form, timeout=20)
    assert r.status_code == 200
    assert r.json()["status"] == "failed"
    assert _db.invoices.find_one({"number": inv["number"]})["status"] == "unpaid"


def test_extra_gateways_blocked_by_policy(admin_tok, client_user):
    inv = _make_invoice(admin_tok, client_user, amount=9000, tag="policy")
    client_tok = _login(client_user["email"], "PytestDuitku2026!")
    for provider in ("midtrans", "xendit"):
        r = requests.post(f"{API}/client/invoices/{inv['id']}/pay-online?provider={provider}",
                          headers=_hdr(client_tok), timeout=15)
        assert r.status_code == 400, r.text
        assert "Duitku" in r.json()["detail"]


def test_client_pay_online_returns_production_url(admin_tok, client_user):
    inv = _make_invoice(admin_tok, client_user, amount=15000, tag="payurl")
    client_tok = _login(client_user["email"], "PytestDuitku2026!")
    r = requests.post(f"{API}/client/invoices/{inv['id']}/pay-online?provider=duitku",
                      headers=_hdr(client_tok), timeout=45)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("payment_url", "").startswith("https://")
    d = _db.invoices.find_one({"number": inv["number"]})
    assert d.get("payment_link") == body["payment_url"]
    assert d.get("payment_provider") == "duitku"
