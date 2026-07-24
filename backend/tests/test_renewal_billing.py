"""Renewal auto-invoice sweep — generation, idempotency, cycle advancement.

Contract (see emails.run_renewal_invoice_sweep):
  * active service with next_renewal within `renewal_lead_days` → exactly ONE
    invoice per (service, renewal_period);
  * re-running the sweep never duplicates;
  * invoice: tax_percent pre-filled from settings.default_tax_percent,
    due_date = renewal date, amount = price_monthly × cycle months;
  * services.next_renewal advances by one billing-cycle interval AFTER the
    invoice exists; last_renewal_invoice_id is recorded;
  * services outside the lead window / non-active are untouched.
"""
from __future__ import annotations
import calendar
import os
import uuid
from datetime import datetime, timezone, timedelta, date

import pytest
import requests
from pymongo import MongoClient

API = (os.environ.get("REACT_APP_BACKEND_URL") or "http://localhost:8001").rstrip("/") + "/api/portal"
ADMIN_EMAIL = "admin@intercloud-digital.com"
ADMIN_PASS = "AdminIntercloud2026!"

_db = MongoClient(os.environ.get("MONGO_URL", "mongodb://localhost:27017"))[
    os.environ.get("DB_NAME", "intercloud_portal")]


def _login(email, pw):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": pw}, timeout=15)
    r.raise_for_status()
    return r.json()["token"]


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}"}


def _add_months(date_str: str, months: int) -> str:
    d = datetime.strptime(date_str, "%Y-%m-%d").date()
    y = d.year + (d.month - 1 + months) // 12
    mo = (d.month - 1 + months) % 12 + 1
    day = min(d.day, calendar.monthrange(y, mo)[1])
    return date(y, mo, day).isoformat()


@pytest.fixture(scope="module")
def admin_tok():
    return _login(ADMIN_EMAIL, ADMIN_PASS)


@pytest.fixture(scope="module")
def client_user(admin_tok):
    email = f"pytest-renewal-{uuid.uuid4().hex[:8]}@example.com"
    r = requests.post(f"{API}/admin/users", headers=_hdr(admin_tok), timeout=15,
                      json={"name": "Pytest Renewal", "email": email,
                            "password": "PytestRenewal2026!", "role": "client"})
    assert r.status_code in (200, 201), r.text
    doc = _db.users.find_one({"email": email})
    yield doc
    _db.services.delete_many({"user_id": doc["_id"]})
    _db.invoices.delete_many({"user_id": doc["_id"]})
    requests.delete(f"{API}/admin/users/{doc['_id']}", headers=_hdr(admin_tok), timeout=15)


@pytest.fixture(scope="module", autouse=True)
def billing_defaults(admin_tok):
    """Pin the defaults the assertions rely on (tax 11%, lead 7 days)."""
    r = requests.put(f"{API}/admin/billing/settings", headers=_hdr(admin_tok), timeout=15,
                     json={"default_tax_percent": 11, "renewal_lead_days": 7})
    assert r.status_code == 200, r.text
    yield


def _plant_service(client_user, *, cycle: str, price: float, days_ahead: int,
                   status: str = "active") -> tuple:
    nr = (datetime.now(timezone.utc) + timedelta(days=days_ahead)).date().isoformat()
    sid = _db.services.insert_one({
        "user_id": client_user["_id"], "product_id": "x",
        "product_name": f"Pytest {cycle}", "category": "vps",
        "name": f"pytest-{cycle}-{uuid.uuid4().hex[:6]}", "status": status,
        "billing_cycle": cycle, "start_date": "2026-01-01",
        "next_renewal": nr, "price_monthly": price, "config": {},
        "created_at": datetime.now(timezone.utc).isoformat()}).inserted_id
    return sid, nr


def _run_sweep(admin_tok) -> dict:
    r = requests.post(f"{API}/admin/billing/run-renewal-sweep",
                      headers=_hdr(admin_tok), timeout=60)
    assert r.status_code == 200, r.text
    return r.json()


CYCLES = {"monthly": 1, "quarterly": 3, "annual": 12}


@pytest.mark.parametrize("cycle,months", CYCLES.items())
def test_due_soon_service_generates_exactly_one_invoice(admin_tok, client_user, cycle, months):
    price = 100000.0
    sid, period = _plant_service(client_user, cycle=cycle, price=price, days_ahead=3)
    _run_sweep(admin_tok)

    invs = list(_db.invoices.find({"service_id": str(sid)}))
    assert len(invs) == 1, f"{cycle}: expected 1 invoice, got {len(invs)}"
    inv = invs[0]
    assert inv["renewal_period"] == period
    assert inv["due_date"] == period
    assert inv["subtotal"] == price * months
    assert inv["tax_percent"] == 11
    assert inv["tax_amount"] == round(price * months * 0.11, 2)
    assert inv["status"] == "unpaid"

    svc = _db.services.find_one({"_id": sid})
    assert svc["next_renewal"] == _add_months(period, months), \
        f"{cycle}: next_renewal must advance by {months} month(s)"
    assert svc["last_renewal_invoice_id"] == str(inv["_id"])

    # ---- idempotency: re-run must not duplicate ----
    _run_sweep(admin_tok)
    assert _db.invoices.count_documents({"service_id": str(sid)}) == 1


def test_far_future_and_suspended_services_untouched(admin_tok, client_user):
    far_sid, far_nr = _plant_service(client_user, cycle="monthly", price=50000, days_ahead=60)
    susp_sid, susp_nr = _plant_service(client_user, cycle="monthly", price=50000,
                                       days_ahead=2, status="suspended")
    _run_sweep(admin_tok)
    assert _db.invoices.count_documents({"service_id": {"$in": [str(far_sid), str(susp_sid)]}}) == 0
    assert _db.services.find_one({"_id": far_sid})["next_renewal"] == far_nr
    assert _db.services.find_one({"_id": susp_sid})["next_renewal"] == susp_nr


def test_renewal_invoice_email_logged(admin_tok, client_user):
    sid, period = _plant_service(client_user, cycle="monthly", price=75000, days_ahead=4)
    before = _db.email_logs.count_documents({"event_key": "invoice_generated"})
    _run_sweep(admin_tok)
    after = _db.email_logs.count_documents({"event_key": "invoice_generated"})
    assert after == before + 1, "renewal must fire exactly one invoice_generated email"


def test_billing_settings_roundtrip(admin_tok):
    r = requests.get(f"{API}/admin/billing/settings", headers=_hdr(admin_tok), timeout=15)
    assert r.status_code == 200
    body = r.json()
    assert body["default_tax_percent"] == 11
    assert body["renewal_lead_days"] == 7
    assert body["enable_extra_payment_gateways"] is False
