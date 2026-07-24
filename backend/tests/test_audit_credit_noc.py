"""Regression tests for Phase 1 (Audit Logs), Phase 2 (Credit Notes), Phase 3 (NOC).

Covers:
  * audit_logs are written for billing settings + credit note create/apply
  * credit note create/apply/cancel + settlement of invoice when credit ≥ total
  * PDF endpoint returns valid application/pdf bytes
  * NOC run-poll executes idempotently even with zero devices
  * NOC events + device state expose expected keys
"""
from __future__ import annotations
import os
import uuid
from datetime import datetime, timezone, timedelta

import requests

API = (os.environ.get("REACT_APP_BACKEND_URL") or "http://localhost:8001").rstrip("/") + "/api/portal"
ADMIN_EMAIL = "admin@intercloud-digital.com"
ADMIN_PASS = "AdminIntercloud2026!"


def _login(email, pw):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": pw}, timeout=15)
    r.raise_for_status()
    return r.json()["token"]


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}"}


def _ensure_client(tok) -> str:
    r = requests.get(f"{API}/admin/users", headers=_hdr(tok), timeout=15)
    r.raise_for_status()
    clients = [u for u in r.json() if u.get("role") == "client"]
    if clients:
        return clients[0]["id"]
    email = f"cn+{uuid.uuid4().hex[:8]}@example.com"
    r = requests.post(f"{API}/admin/users", headers=_hdr(tok), json={
        "email": email, "password": "Passw0rd!", "name": "CN Client", "role": "client",
    }, timeout=15)
    r.raise_for_status()
    return r.json()["id"]


# ============================================================
# Audit logs
# ============================================================
def test_audit_logs_billing_settings_update():
    tok = _login(ADMIN_EMAIL, ADMIN_PASS)
    # Nudge billing settings so a row is inserted (revert immediately to keep state)
    original = requests.get(f"{API}/admin/billing/settings", headers=_hdr(tok), timeout=15).json()
    requests.put(f"{API}/admin/billing/settings", headers=_hdr(tok),
                 json={"default_tax_percent": 9.99}, timeout=15)
    requests.put(f"{API}/admin/billing/settings", headers=_hdr(tok),
                 json={"default_tax_percent": original["default_tax_percent"]}, timeout=15)
    r = requests.get(f"{API}/admin/audit-logs?action=billing.settings_update&limit=5",
                     headers=_hdr(tok), timeout=15)
    r.raise_for_status()
    data = r.json()
    assert data["total"] >= 2, data
    latest = data["items"][0]
    assert latest["actor_email"] == ADMIN_EMAIL
    assert latest["category"] == "billing"
    assert latest["ip"]  # ip captured
    assert "before" in latest and "after" in latest


def test_audit_logs_filters():
    tok = _login(ADMIN_EMAIL, ADMIN_PASS)
    r = requests.get(f"{API}/admin/audit-logs?category=billing", headers=_hdr(tok), timeout=15)
    r.raise_for_status()
    for item in r.json()["items"]:
        assert item["category"] == "billing"


def test_audit_logs_facets_shape():
    tok = _login(ADMIN_EMAIL, ADMIN_PASS)
    r = requests.get(f"{API}/admin/audit-logs/facets", headers=_hdr(tok), timeout=15)
    r.raise_for_status()
    facets = r.json()
    assert "categories" in facets
    assert facets["severities"] == ["info", "warning", "critical"]


# ============================================================
# Credit notes
# ============================================================
def test_credit_note_partial_then_full_settle():
    tok = _login(ADMIN_EMAIL, ADMIN_PASS)
    client_id = _ensure_client(tok)
    # Fresh invoice
    due = (datetime.now(timezone.utc) + timedelta(days=14)).date().isoformat()
    r = requests.post(f"{API}/admin/invoices", headers=_hdr(tok), json={
        "user_id": client_id,
        "items": [{"description": "CN test svc", "qty": 1, "unit_price": 200000, "total": 200000}],
        "tax_percent": 0,
        "due_date": due,
    }, timeout=15)
    r.raise_for_status()
    inv = r.json()
    inv_id, inv_total = inv["id"], inv["total"]
    assert inv["status"] == "unpaid"

    # Partial credit — invoice must remain unpaid
    r = requests.post(f"{API}/admin/credit-notes", headers=_hdr(tok), json={
        "invoice_id": inv_id, "amount": 80000, "reason": "partial",
        "auto_apply": True,
    }, timeout=15)
    r.raise_for_status()
    assert r.json()["status"] == "applied"
    # Find the invoice back
    lst = requests.get(f"{API}/admin/invoices", headers=_hdr(tok), timeout=15).json()
    inv_after = next(i for i in lst if i["id"] == inv_id)
    assert inv_after["status"] == "unpaid"

    # Final credit — should push total credit to >= invoice total → paid
    r = requests.post(f"{API}/admin/credit-notes", headers=_hdr(tok), json={
        "invoice_id": inv_id, "amount": inv_total - 80000, "reason": "final",
        "auto_apply": True,
    }, timeout=15)
    r.raise_for_status()
    lst = requests.get(f"{API}/admin/invoices", headers=_hdr(tok), timeout=15).json()
    inv_after = next(i for i in lst if i["id"] == inv_id)
    assert inv_after["status"] == "paid", inv_after
    assert inv_after["payment_method"] == "credit_note"

    # Audit trail: invoice.settled_by_credit must be present
    r = requests.get(f"{API}/admin/audit-logs?action=invoice.settled_by_credit&limit=5",
                     headers=_hdr(tok), timeout=15)
    assert r.status_code == 200
    assert r.json()["total"] >= 1


def test_credit_note_rejects_over_invoice_total():
    tok = _login(ADMIN_EMAIL, ADMIN_PASS)
    client_id = _ensure_client(tok)
    due = (datetime.now(timezone.utc) + timedelta(days=14)).date().isoformat()
    inv = requests.post(f"{API}/admin/invoices", headers=_hdr(tok), json={
        "user_id": client_id,
        "items": [{"description": "small", "qty": 1, "unit_price": 50000, "total": 50000}],
        "tax_percent": 0, "due_date": due,
    }, timeout=15).json()
    r = requests.post(f"{API}/admin/credit-notes", headers=_hdr(tok), json={
        "invoice_id": inv["id"], "amount": 99999999, "reason": "too big",
    }, timeout=15)
    assert r.status_code == 400
    assert "exceeds" in r.text.lower() or "exceed" in r.text.lower()


def test_credit_note_cancel_only_before_apply():
    tok = _login(ADMIN_EMAIL, ADMIN_PASS)
    client_id = _ensure_client(tok)
    due = (datetime.now(timezone.utc) + timedelta(days=14)).date().isoformat()
    inv = requests.post(f"{API}/admin/invoices", headers=_hdr(tok), json={
        "user_id": client_id,
        "items": [{"description": "svc", "qty": 1, "unit_price": 30000, "total": 30000}],
        "tax_percent": 0, "due_date": due,
    }, timeout=15).json()
    cn = requests.post(f"{API}/admin/credit-notes", headers=_hdr(tok), json={
        "invoice_id": inv["id"], "amount": 10000, "reason": "cancel test",
        "auto_apply": False,
    }, timeout=15).json()
    assert cn["status"] == "draft"
    # Cancel while draft — allowed
    r = requests.post(f"{API}/admin/credit-notes/{cn['id']}/cancel",
                      headers=_hdr(tok), timeout=15)
    assert r.status_code == 200

    # Create another, apply it, then cancel — must fail
    cn2 = requests.post(f"{API}/admin/credit-notes", headers=_hdr(tok), json={
        "invoice_id": inv["id"], "amount": 5000, "reason": "cancel-after-apply",
        "auto_apply": True,
    }, timeout=15).json()
    assert cn2["status"] == "applied"
    r = requests.post(f"{API}/admin/credit-notes/{cn2['id']}/cancel",
                      headers=_hdr(tok), timeout=15)
    assert r.status_code == 400


def test_credit_note_pdf_bytes():
    tok = _login(ADMIN_EMAIL, ADMIN_PASS)
    lst = requests.get(f"{API}/admin/credit-notes", headers=_hdr(tok), timeout=15).json()
    if not lst:
        return  # nothing to render — test is a soft-skip
    cn_id = lst[0]["id"]
    r = requests.get(f"{API}/documents/credit-note/{cn_id}?format=pdf&token={tok}",
                     timeout=30)
    assert r.status_code == 200
    assert r.headers.get("content-type", "").startswith("application/pdf")
    assert r.content[:4] == b"%PDF"
    assert len(r.content) > 5000  # non-empty


# ============================================================
# NOC monitoring
# ============================================================
def test_noc_run_poll_idempotent():
    tok = _login(ADMIN_EMAIL, ADMIN_PASS)
    r1 = requests.post(f"{API}/admin/noc/run-poll", headers=_hdr(tok), timeout=30)
    r2 = requests.post(f"{API}/admin/noc/run-poll", headers=_hdr(tok), timeout=30)
    assert r1.status_code == r2.status_code == 200
    assert "probed" in r1.json() and "transitions" in r1.json()


def test_noc_devices_and_events_shape():
    tok = _login(ADMIN_EMAIL, ADMIN_PASS)
    d = requests.get(f"{API}/admin/noc/devices", headers=_hdr(tok), timeout=15)
    assert d.status_code == 200
    for row in d.json():
        assert "status" in row and row["status"] in ("up", "down", "unknown")
        assert "uptime_24h_pct" in row
    e = requests.get(f"{API}/admin/noc/events?limit=10", headers=_hdr(tok), timeout=15)
    assert e.status_code == 200
    assert isinstance(e.json(), list)
