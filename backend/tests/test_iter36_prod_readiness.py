"""Iteration 36 - Production readiness tests: no mock provisioning, real integration
tests, user delete, menu catalog sync, honest traffic empty state."""
import os
import requests
import pytest

def _read_env():
    try:
        with open("/app/frontend/.env") as f:
            for ln in f:
                if ln.startswith("REACT_APP_BACKEND_URL="):
                    return ln.split("=", 1)[1].strip()
    except Exception:
        pass
    return os.environ.get("REACT_APP_BACKEND_URL", "")

BASE = _read_env().rstrip("/")
assert BASE, "REACT_APP_BACKEND_URL missing"
API = f"{BASE}/api/portal"

ADMIN = ("admin@intercloud-digital.com", "AdminIntercloud2026!")
CLIENT = ("demo@client.com", "ClientDemo2026!")
SALES = ("sales@intercloud-digital.com", "Sales2026!")
SUPPORT = ("support@intercloud-digital.com", "Support2026!")
TICKET = ("ticket@intercloud-digital.com", "Ticket2026!")


def _login(email, password):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=20)
    assert r.status_code == 200, f"login {email} -> {r.status_code} {r.text[:200]}"
    return r.json()["token"]


def _h(tok):
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture(scope="module")
def admin_tok():
    return _login(*ADMIN)


# --- 1. No-mock live integration test ---
def test_live_test_config_cpanel_bad_host_returns_real_error(admin_tok):
    r = requests.post(
        f"{API}/admin/integrations/test-config",
        headers=_h(admin_tok),
        json={"module": "cpanel", "config": {"hostname": "fake.invalid-host.test", "username": "root", "api_token": "x"}},
        timeout=30,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("ok") is False
    assert "latency_ms" in body
    err = (body.get("error") or body.get("message") or "").lower()
    assert any(k in err for k in ["dns", "resolve", "connect", "timeout", "name", "host", "unreachable", "network", "not known", "errno"]), f"error not real: {body}"


def test_live_test_config_missing_fields(admin_tok):
    r = requests.post(
        f"{API}/admin/integrations/test-config",
        headers=_h(admin_tok),
        json={"module": "cpanel", "config": {}},
        timeout=15,
    )
    assert r.status_code == 200
    body = r.json()
    assert body.get("ok") is False
    msg = (body.get("error") or body.get("message") or "").lower()
    assert "missing required" in msg


# --- 2. No fake provisioning ---
def test_provision_hosting_cpanel_returns_400_not_configured(admin_tok):
    r = requests.post(
        f"{API}/admin/provisioning/hosting/create",
        headers=_h(admin_tok),
        json={"panel": "cpanel", "domain": "x.com", "username": "u1", "password": "p12345678"},
        timeout=30,
    )
    assert r.status_code == 400, f"expected 400, got {r.status_code}: {r.text[:300]}"
    detail = (r.json().get("detail") or "").lower()
    assert "cpanel" in detail or "whm" in detail
    assert "belum aktif" in detail or "belum" in detail or "tidak aktif" in detail


def test_provision_proxmox_returns_400_honest(admin_tok):
    r = requests.post(
        f"{API}/admin/provisioning/proxmox/create",
        headers=_h(admin_tok),
        json={"hostname": "test-vm-iter36"},
        timeout=60,
    )
    assert r.status_code == 400, f"expected 400, got {r.status_code}: {r.text[:400]}"
    detail = (r.json().get("detail") or "").lower()
    assert "proxmox" in detail or "template" in detail or "clone" in detail or "vmid" in detail


# --- 3. Traffic honest empty state ---
def test_client_traffic_returns_available_false_when_no_samples():
    tok = _login(*CLIENT)
    svcs = requests.get(f"{API}/client/services", headers=_h(tok), timeout=15)
    assert svcs.status_code == 200
    items = svcs.json() if isinstance(svcs.json(), list) else svcs.json().get("items", [])
    if not items:
        pytest.skip("no client services")
    sid = items[0].get("id") or items[0].get("_id")
    r = requests.get(f"{API}/client/services/{sid}/traffic", headers=_h(tok), timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "available" in body
    assert "points" in body
    if body["available"] is False:
        assert body["points"] == []


# --- 4. Menu catalog / user delete / access sync ---
def test_menu_catalog_contains_new_keys_no_user_settings(admin_tok):
    r = requests.get(f"{API}/admin/user-access-catalog", headers=_h(admin_tok), timeout=15)
    assert r.status_code == 200, f"{r.status_code} {r.text[:200]}"
    body = r.json()
    keys = set()
    cat = body.get("menu_catalog") or body.get("catalog") or body.get("items") or body
    if isinstance(cat, list):
        for it in cat:
            keys.add(it.get("key") or it.get("id"))
    elif isinstance(cat, dict):
        keys = set(cat.keys())
    for expected in ["form_builder", "status_page", "site_content"]:
        assert expected in keys, f"missing menu {expected} in {sorted(keys)}"
    assert "user_settings" not in keys, "user_settings should have been removed"


def test_admin_can_create_and_delete_user(admin_tok):
    email = "tmpdel-iter36@example.com"
    # cleanup pre-existing
    lst = requests.get(f"{API}/admin/users", headers=_h(admin_tok), timeout=15).json()
    items = lst if isinstance(lst, list) else lst.get("items", [])
    for u in items:
        if u.get("email") == email:
            uid = u.get("id") or u.get("_id")
            requests.delete(f"{API}/admin/users/{uid}", headers=_h(admin_tok), timeout=15)
    # Create
    r = requests.post(
        f"{API}/admin/users",
        headers=_h(admin_tok),
        json={"email": email, "password": "TmpDel2026!", "name": "Tmp Del", "role": "support"},
        timeout=15,
    )
    assert r.status_code in (200, 201), r.text
    created = r.json()
    uid = created.get("id") or created.get("_id") or created.get("user", {}).get("id")
    assert uid, f"no id in {created}"
    # Delete
    d = requests.delete(f"{API}/admin/users/{uid}", headers=_h(admin_tok), timeout=15)
    assert d.status_code in (200, 204), d.text
    # Verify gone
    lst2 = requests.get(f"{API}/admin/users", headers=_h(admin_tok), timeout=15).json()
    items2 = lst2 if isinstance(lst2, list) else lst2.get("items", [])
    assert not any(u.get("email") == email for u in items2)


def test_admin_cannot_delete_self(admin_tok):
    lst = requests.get(f"{API}/admin/users", headers=_h(admin_tok), timeout=15).json()
    items = lst if isinstance(lst, list) else lst.get("items", [])
    me = next((u for u in items if u.get("email") == ADMIN[0]), None)
    assert me, "admin user missing"
    uid = me.get("id") or me.get("_id")
    d = requests.delete(f"{API}/admin/users/{uid}", headers=_h(admin_tok), timeout=15)
    assert d.status_code in (400, 403, 409), f"admin self-delete should be blocked, got {d.status_code}"


# --- 5. Role-based auth smoke ---
@pytest.mark.parametrize("creds", [SALES, SUPPORT, TICKET])
def test_role_logins_work(creds):
    tok = _login(*creds)
    r = requests.get(f"{API}/auth/me", headers=_h(tok), timeout=10)
    assert r.status_code == 200
    assert r.json().get("email") == creds[0]
