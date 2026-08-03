"""Iteration 37 - Test 4 new features:
1. Proxmox template list + auto-discover clone
2. Credit note PDF preview
3. Traffic source mapping
4. Welcome onboarding email on user create
"""
import os
import time
import pytest
import requests

def _backend_url():
    v = os.environ.get("REACT_APP_BACKEND_URL")
    if not v:
        try:
            with open("/app/frontend/.env") as f:
                for line in f:
                    if line.startswith("REACT_APP_BACKEND_URL="):
                        v = line.split("=", 1)[1].strip()
        except OSError:
            v = "http://127.0.0.1:8001"
    return v


BASE = _backend_url().rstrip("/") + "/api/portal"
ADMIN_EMAIL = "admin@intercloud-digital.com"
ADMIN_PW = "AdminIntercloud2026!"


@pytest.fixture(scope="module")
def admin_token():
    r = requests.post(f"{BASE}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PW}, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()["token"]


@pytest.fixture(scope="module")
def h(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


# ---------- Feature 1: Proxmox templates ----------
def test_proxmox_templates_returns_200_with_empty_list(h):
    r = requests.get(f"{BASE}/admin/proxmox/templates", headers=h, timeout=60)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "templates" in body
    assert "configured_vmid" in body
    assert isinstance(body["templates"], list)
    print("templates:", body["templates"], "configured_vmid:", body["configured_vmid"])


def test_proxmox_create_no_template_returns_400_indonesian(h):
    # GUARD: bila cluster punya template, endpoint akan meng-CLONE VM NYATA.
    # Test ini hanya valid untuk cluster tanpa template - skip agar tidak
    # pernah membuat VM sungguhan di server production.
    tpl = requests.get(f"{BASE}/admin/proxmox/templates", headers=h, timeout=60)
    if tpl.status_code == 200 and (tpl.json() or {}).get("templates"):
        pytest.skip("Cluster punya template - create akan clone VM nyata, dilewati")
    r = requests.post(
        f"{BASE}/admin/provisioning/proxmox/create",
        headers=h,
        json={"hostname": "tpl-test-vm"},
        timeout=90,
    )
    assert r.status_code == 400, f"{r.status_code}: {r.text}"
    detail = (r.json().get("detail") or "").lower()
    assert "tidak ada template" in detail or "template vm" in detail, r.text


# ---------- Feature 3: Credit Note preview ----------
def test_credit_note_preview_pdf_bytes(h):
    inv = requests.get(f"{BASE}/admin/invoices", headers=h, timeout=30)
    assert inv.status_code == 200
    lst = inv.json()
    items = lst if isinstance(lst, list) else lst.get("items") or lst.get("invoices") or []
    if not items:
        pytest.skip("No invoices to preview credit note against")
    invoice_id = items[0].get("id") or items[0].get("_id")
    assert invoice_id

    r = requests.post(
        f"{BASE}/admin/credit-notes/preview",
        headers=h,
        json={"invoice_id": invoice_id, "amount": 75000, "reason": "QA preview"},
        timeout=60,
    )
    assert r.status_code == 200, r.text
    assert "application/pdf" in r.headers.get("content-type", "")
    assert r.content[:4] == b"%PDF", r.content[:20]


def test_credit_note_preview_zero_amount_400(h):
    inv = requests.get(f"{BASE}/admin/invoices", headers=h, timeout=30)
    lst = inv.json()
    items = lst if isinstance(lst, list) else lst.get("items") or lst.get("invoices") or []
    if not items:
        pytest.skip("No invoices")
    invoice_id = items[0].get("id") or items[0].get("_id")
    r = requests.post(
        f"{BASE}/admin/credit-notes/preview",
        headers=h,
        json={"invoice_id": invoice_id, "amount": 0, "reason": "x"},
        timeout=30,
    )
    assert r.status_code == 400, r.text


def test_credit_note_preview_bad_invoice_400(h):
    r = requests.post(
        f"{BASE}/admin/credit-notes/preview",
        headers=h,
        json={"invoice_id": "does-not-exist-xxx", "amount": 1000, "reason": "x"},
        timeout=30,
    )
    assert r.status_code == 400, r.text


# ---------- Feature 2: Traffic source mapping ----------
def test_traffic_source_set_and_clear(h):
    # Get a service
    svcs = requests.get(f"{BASE}/admin/services", headers=h, timeout=30)
    assert svcs.status_code == 200
    lst = svcs.json()
    items = lst if isinstance(lst, list) else lst.get("items") or lst.get("services") or []
    if not items:
        pytest.skip("No services available")
    sid = items[0].get("id") or items[0].get("_id")

    # Get a mikrotik device
    devs = requests.get(f"{BASE}/admin/mikrotik/devices", headers=h, timeout=30)
    assert devs.status_code == 200, devs.text
    dl = devs.json()
    dev_items = dl if isinstance(dl, list) else dl.get("items") or dl.get("devices") or []
    if not dev_items:
        pytest.skip("No mikrotik devices")
    device_id = dev_items[0].get("id") or dev_items[0].get("_id")

    # Set traffic source
    r = requests.put(
        f"{BASE}/admin/services/{sid}/traffic-source",
        headers=h,
        json={"device_id": device_id, "interface": "ether1"},
        timeout=60,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("ok") is True
    assert body.get("interface") == "ether1"
    assert "sample" in body  # may be null

    # Verify via detail
    det = requests.get(f"{BASE}/admin/services/{sid}/detail", headers=h, timeout=30)
    assert det.status_code == 200, det.text
    cfg = (det.json().get("config") or {})
    assert cfg.get("traffic_device_id") == device_id
    assert cfg.get("traffic_interface") == "ether1"

    # Clear
    r2 = requests.put(f"{BASE}/admin/services/{sid}/traffic-source", headers=h, json={}, timeout=30)
    assert r2.status_code == 200, r2.text
    body2 = r2.json()
    assert body2.get("ok") is True
    assert body2.get("cleared") is True

    det2 = requests.get(f"{BASE}/admin/services/{sid}/detail", headers=h, timeout=30)
    cfg2 = (det2.json().get("config") or {})
    assert "traffic_device_id" not in cfg2 or cfg2.get("traffic_device_id") in (None, "")
    assert "traffic_interface" not in cfg2 or cfg2.get("traffic_interface") in (None, "")


# ---------- Feature 4: Welcome onboarding email ----------
def test_welcome_email_logged_on_user_create(h):
    email = "qa-onboard@example.com"
    # Ensure user doesn't already exist - try to delete first
    try:
        lst = requests.get(f"{BASE}/admin/users", headers=h, timeout=30).json()
        users = lst if isinstance(lst, list) else lst.get("items") or lst.get("users") or []
        for u in users:
            if u.get("email") == email:
                uid = u.get("id") or u.get("_id")
                requests.delete(f"{BASE}/admin/users/{uid}", headers=h, timeout=30)
    except Exception:
        pass

    r = requests.post(
        f"{BASE}/admin/users",
        headers=h,
        json={"email": email, "password": "Tmp12345678!", "name": "QA Onboard", "role": "client"},
        timeout=30,
    )
    assert r.status_code in (200, 201), r.text
    created = r.json()
    uid = created.get("id") or created.get("_id")
    assert uid

    # Give scheduler a moment
    time.sleep(2)

    # Try email logs endpoint
    logs_found = None
    logs_resp = requests.get(f"{BASE}/admin/email-logs", headers=h, timeout=30)
    if logs_resp.status_code == 200:
        d = logs_resp.json()
        items = d if isinstance(d, list) else d.get("items") or d.get("logs") or []
        for it in items:
            if it.get("to_email") == email and it.get("event_key") == "welcome":
                logs_found = it
                break

    if logs_found is None:
        # Fallback: query mongo directly
        from pymongo import MongoClient
        mongo_url = os.environ.get("MONGO_URL")
        db_name = os.environ.get("DB_NAME")
        cli = MongoClient(mongo_url)
        db = cli[db_name]
        logs_found = db.email_logs.find_one({"to_email": email, "event_key": "welcome"})

    assert logs_found is not None, "No welcome email log found for created user"
    subj = logs_found.get("subject") or ""
    assert subj.lower().startswith("selamat datang di intercloud"), f"unexpected subject: {subj!r}"
    # status skipped is OK (no SMTP in dev)
    print("welcome email status:", logs_found.get("status"))

    # Cleanup
    d = requests.delete(f"{BASE}/admin/users/{uid}", headers=h, timeout=30)
    assert d.status_code in (200, 204), d.text
