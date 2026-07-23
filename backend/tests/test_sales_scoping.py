"""Regression: verify Sales role can only see/modify their assigned clients'
invoices, CRM entries, and follow-ups. Also verifies that admin_mail_send
requires per-user SMTP setup and returns HTTP 400 when unconfigured.

These tests hit the real running FastAPI service through the preview URL
(REACT_APP_BACKEND_URL) so they exercise the same routing/serialization
path the frontend uses.
"""
from __future__ import annotations
import os
import re
import time
import pytest
import requests


API = os.environ.get("REACT_APP_BACKEND_URL") or (
    # fall back to reading the frontend env file when pytest is invoked
    # without inheriting the preview env
    (lambda p: next((l.split("=", 1)[1].strip().strip('"')
                     for l in open(p) if l.startswith("REACT_APP_BACKEND_URL=")), ""))
    ("/app/frontend/.env")
)
ADMIN_EMAIL = "admin@intercloud-digital.com"
ADMIN_PASS  = "AdminIntercloud2026!"


def _login(email: str, password: str) -> str:
    r = requests.post(f"{API}/api/portal/auth/login",
                      json={"email": email, "password": password}, timeout=15)
    r.raise_for_status()
    return r.json()["token"]


def _hdr(tok: str) -> dict:
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def _mkuser(admin_tok: str, **overrides) -> dict:
    stamp = str(int(time.time() * 1000))
    payload = {
        "email": f"user{stamp}@example.com",
        "password": "Passw0rd!",
        "name": f"User {stamp}",
        "role": "client",
    }
    payload.update(overrides)
    r = requests.post(f"{API}/api/portal/admin/users",
                      json=payload, headers=_hdr(admin_tok), timeout=15)
    r.raise_for_status()
    return r.json()


@pytest.fixture(scope="module")
def admin_tok() -> str:
    return _login(ADMIN_EMAIL, ADMIN_PASS)


@pytest.fixture(scope="module")
def scoped_env(admin_tok: str):
    """Create Client A + Client B + Sales(assigned only A) + one invoice each,
    one follow-up each. Returns a dict of ids for the tests to use."""
    a = _mkuser(admin_tok, name="Alpha Client", company="Alpha Co")
    b = _mkuser(admin_tok, name="Beta Client",  company="Beta Co")
    sales = _mkuser(admin_tok,
                    email=f"sales{int(time.time()*1000)}@example.com",
                    name="Sales Scoped",
                    role="sales",
                    assigned_client_ids=[a["id"]])

    def _mkinv(uid, desc, amt):
        r = requests.post(
            f"{API}/api/portal/admin/invoices",
            json={"user_id": uid,
                  "items": [{"description": desc, "quantity": 1,
                             "unit_price": amt, "total": amt}],
                  "tax_percent": 11, "due_date": "2026-12-31"},
            headers=_hdr(admin_tok), timeout=15)
        r.raise_for_status()
        return r.json()

    inv_a = _mkinv(a["id"], "Alpha item", 100000)
    inv_b = _mkinv(b["id"], "Beta item",  200000)

    # Fetch auto-mirrored CRM rows for the two clients so we can create
    # follow-ups against them.
    all_crm = requests.get(f"{API}/api/portal/admin/crm",
                           headers=_hdr(admin_tok), timeout=15).json()
    crm_a = next(c for c in all_crm if c.get("user_id") == a["id"])
    crm_b = next(c for c in all_crm if c.get("user_id") == b["id"])

    def _mkfu(crm_id, name, task):
        r = requests.post(
            f"{API}/api/portal/admin/followups",
            json={"customer_id": crm_id, "customer_name": name,
                  "task": task, "due_date": "2026-08-01"},
            headers=_hdr(admin_tok), timeout=15)
        r.raise_for_status()
        return r.json()

    fu_a = _mkfu(crm_a["id"], crm_a["name"], "Follow Alpha")
    fu_b = _mkfu(crm_b["id"], crm_b["name"], "Follow Beta")

    sales_tok = _login(sales["email"], "Passw0rd!")
    return {
        "a": a, "b": b, "sales": sales,
        "sales_tok": sales_tok,
        "inv_a": inv_a, "inv_b": inv_b,
        "crm_a": crm_a, "crm_b": crm_b,
        "fu_a": fu_a, "fu_b": fu_b,
    }


# ============================================================
# Sales invoices scoping
# ============================================================
def test_sales_invoices_only_assigned(scoped_env):
    rows = requests.get(f"{API}/api/portal/admin/invoices",
                        headers=_hdr(scoped_env["sales_tok"]), timeout=15).json()
    assert isinstance(rows, list)
    numbers = [r["number"] for r in rows]
    assert scoped_env["inv_a"]["number"] in numbers, "Sales should see Alpha invoice"
    assert scoped_env["inv_b"]["number"] not in numbers, "Sales must NOT see Beta invoice"


# ============================================================
# Sales CRM scoping
# ============================================================
def test_sales_crm_only_assigned(scoped_env, admin_tok):
    rows = requests.get(f"{API}/api/portal/admin/crm",
                        headers=_hdr(scoped_env["sales_tok"]), timeout=15).json()
    assert isinstance(rows, list)
    ids = {r["id"] for r in rows}
    assert scoped_env["crm_a"]["id"] in ids
    assert scoped_env["crm_b"]["id"] not in ids


def test_sales_crm_cannot_edit_others(scoped_env):
    r = requests.put(f"{API}/api/portal/admin/crm/{scoped_env['crm_b']['id']}",
                     json={"notes": "leak"},
                     headers=_hdr(scoped_env["sales_tok"]), timeout=15)
    assert r.status_code == 403


def test_sales_crm_cannot_delete_others(scoped_env):
    r = requests.delete(f"{API}/api/portal/admin/crm/{scoped_env['crm_b']['id']}",
                        headers=_hdr(scoped_env["sales_tok"]), timeout=15)
    assert r.status_code == 403


# ============================================================
# Sales follow-ups scoping
# ============================================================
def test_sales_followups_only_assigned(scoped_env):
    rows = requests.get(f"{API}/api/portal/admin/followups",
                        headers=_hdr(scoped_env["sales_tok"]), timeout=15).json()
    tasks = [r["task"] for r in rows]
    assert "Follow Alpha" in tasks
    assert "Follow Beta" not in tasks


def test_sales_followup_create_requires_own_customer(scoped_env):
    """Sales creating a follow-up against Client B's CRM must be rejected."""
    r = requests.post(f"{API}/api/portal/admin/followups",
                      json={"customer_id": scoped_env["crm_b"]["id"],
                            "customer_name": scoped_env["crm_b"]["name"],
                            "task": "sneaky", "due_date": "2026-08-05"},
                      headers=_hdr(scoped_env["sales_tok"]), timeout=15)
    assert r.status_code == 403


def test_sales_followup_cannot_delete_others(scoped_env):
    r = requests.delete(
        f"{API}/api/portal/admin/followups/{scoped_env['fu_b']['id']}",
        headers=_hdr(scoped_env["sales_tok"]), timeout=15)
    assert r.status_code == 403


# ============================================================
# admin_mail_send — per-user SMTP required
# ============================================================
def test_mail_send_requires_personal_smtp(scoped_env):
    """A staff member with no email_settings.smtp must receive 400."""
    r = requests.post(f"{API}/api/portal/admin/mail/send",
                      json={"to": "someone@example.com",
                            "subject": "Ping", "body": "Hi"},
                      headers=_hdr(scoped_env["sales_tok"]), timeout=15)
    assert r.status_code == 400
    detail = r.json().get("detail", "")
    assert re.search(r"SMTP", detail, re.I), f"expected SMTP hint, got: {detail!r}"


# ============================================================
# Admin still sees everything
# ============================================================
def test_admin_sees_everything(scoped_env, admin_tok):
    invs = requests.get(f"{API}/api/portal/admin/invoices",
                        headers=_hdr(admin_tok), timeout=15).json()
    assert scoped_env["inv_a"]["number"] in [i["number"] for i in invs]
    assert scoped_env["inv_b"]["number"] in [i["number"] for i in invs]

    fus = requests.get(f"{API}/api/portal/admin/followups",
                       headers=_hdr(admin_tok), timeout=15).json()
    tasks = [f["task"] for f in fus]
    assert "Follow Alpha" in tasks and "Follow Beta" in tasks
