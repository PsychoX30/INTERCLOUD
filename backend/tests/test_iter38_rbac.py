"""
Iteration 38 - RBAC test suite:
 - Destructive admin user endpoints must be admin-only (403 for finance/sales/support/ticket_only)
 - Finance role can read finance module endpoints (200)
 - Support role can read operations module endpoints (200)
 - Cross-role restrictions still enforced (403)
 - Sankey netflow returns live:false + empty flows when no mikrotik device provides samples
"""
import os
import pytest
import requests

BASE = os.environ["REACT_APP_BACKEND_URL"].rstrip("/") + "/api/portal"

CREDS = {
    "admin":       ("admin@intercloud-digital.com",   "AdminIntercloud2026!"),
    "finance":     ("finance@intercloud-digital.com", "StaffTest2026!"),
    "sales":       ("sales@intercloud-digital.com",   "Sales2026!"),
    "support":     ("support@intercloud-digital.com", "Support2026!"),
    "ticket_only": ("ticket@intercloud-digital.com",  "Ticket2026!"),
}
ADMIN_UID = "6a638caf0e250916b6674e62"


@pytest.fixture(scope="module")
def tokens():
    out = {}
    for role, (email, pw) in CREDS.items():
        r = requests.post(f"{BASE}/auth/login", json={"email": email, "password": pw}, timeout=15)
        assert r.status_code == 200, f"login {role} failed: {r.status_code} {r.text[:200]}"
        out[role] = r.json()["token"]
    return out


def _hdr(t):  return {"Authorization": f"Bearer {t}"}


# ---------- 1. Destructive admin-user endpoints: admin-only ----------
DESTRUCTIVE_CALLS = [
    ("DELETE", f"/admin/users/{ADMIN_UID}",                  None),
    ("POST",   f"/admin/users/{ADMIN_UID}/reset-password",   {"new_password": "ValidPass12345!", "notify_user": False}),
    ("PUT",    f"/admin/users/{ADMIN_UID}",                  {"password": "ValidPass12345!"}),
    ("POST",   f"/admin/users/{ADMIN_UID}/reset-2fa",        {}),
    ("POST",   f"/admin/users",                              {"email": "TEST_rbac@example.com", "password": "ValidPass12345!", "role": "client", "name": "X"}),
]

@pytest.mark.parametrize("role", ["finance", "sales", "support", "ticket_only"])
@pytest.mark.parametrize("method,path,body", DESTRUCTIVE_CALLS)
def test_destructive_admin_endpoints_are_admin_only(tokens, role, method, path, body):
    r = requests.request(method, f"{BASE}{path}", json=body, headers=_hdr(tokens[role]), timeout=15)
    assert r.status_code == 403, f"{role} {method} {path} expected 403, got {r.status_code} {r.text[:180]}"


# ---------- 2. Finance role can access finance module ----------
FINANCE_READ = [
    "/admin/finance/detailed",
    "/admin/finance/reports",
    "/admin/finance/cashflow-forecast",
    "/admin/reports/monthly",
    "/admin/assets",
    "/admin/expenses",
    "/admin/credit-notes",
    "/admin/services",
    "/admin/bank-accounts",
]

@pytest.mark.parametrize("path", FINANCE_READ)
def test_finance_role_can_read_finance_module(tokens, path):
    r = requests.get(f"{BASE}{path}", headers=_hdr(tokens["finance"]), timeout=30)
    assert r.status_code == 200, f"finance {path} expected 200 got {r.status_code} {r.text[:180]}"


# ---------- 3. Support role can access operations module ----------
SUPPORT_READ = [
    "/admin/mikrotik/devices",
    "/admin/noc/devices",
    "/admin/noc/events",
    "/admin/noc/netflow/sankey",
    "/admin/diagnostics/tools",
    "/admin/proxmox/templates",
    "/admin/products",
    "/admin/services",
    "/admin/system/health",
]

@pytest.mark.parametrize("path", SUPPORT_READ)
def test_support_role_can_read_ops_module(tokens, path):
    r = requests.get(f"{BASE}{path}", headers=_hdr(tokens["support"]), timeout=30)
    assert r.status_code == 200, f"support {path} expected 200 got {r.status_code} {r.text[:180]}"


# ---------- 4. Cross-role restrictions still 403 ----------
CROSS_ROLE_FORBIDDEN = [
    ("finance",     "/admin/mikrotik/devices"),
    ("support",     "/admin/finance/detailed"),
    ("ticket_only", "/admin/finance/detailed"),
    ("ticket_only", "/admin/services"),
    ("sales",       "/admin/assets"),
]

@pytest.mark.parametrize("role,path", CROSS_ROLE_FORBIDDEN)
def test_cross_role_forbidden(tokens, role, path):
    r = requests.get(f"{BASE}{path}", headers=_hdr(tokens[role]), timeout=15)
    assert r.status_code == 403, f"{role} {path} expected 403, got {r.status_code} {r.text[:180]}"


# ---------- 5. Sankey has no mock data ----------
def test_sankey_no_mock_data(tokens):
    r = requests.get(f"{BASE}/admin/noc/netflow/sankey", headers=_hdr(tokens["admin"]), timeout=30)
    assert r.status_code == 200
    data = r.json()
    assert "live" in data and "flows" in data
    assert isinstance(data["flows"], list)
    # No dummy IP artifacts (mock data used 203.0.113.10 / VM Web Cluster)
    dump = str(data)
    assert "203.0.113" not in dump
    assert "VM Web Cluster" not in dump
    # If no live sample -> flows must be empty
    if not data.get("live"):
        assert data["flows"] == []


# ---------- 6. Admin still fully functional across combined endpoints ----------
@pytest.mark.parametrize("path", FINANCE_READ + SUPPORT_READ)
def test_admin_can_access_all(tokens, path):
    r = requests.get(f"{BASE}{path}", headers=_hdr(tokens["admin"]), timeout=30)
    assert r.status_code == 200, f"admin {path} expected 200 got {r.status_code} {r.text[:180]}"
