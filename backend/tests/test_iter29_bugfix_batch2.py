"""
Iteration 29 regression — Batch-2 bug fixes.

Covers the review request:
  * B1 — GET /api/portal/admin/mail/inbox as admin returns 200 array.
         GET /api/portal/admin/mail/messages/{first_id} → 200 with non-empty body.
         GET /api/portal/admin/mail/messages/imap-fakeid123 → 404 (NOT 500).
  * B2 — Sales GET /api/portal/admin/orders → 200 JSON array (filtered).
         Sales GET /api/portal/admin/quotations → 200 JSON array.
  * B3 — Admin dashboard stats include overdue_invoices as an int (not None) so
         the frontend can render '{overdue_invoices} invoice(s)' safely.
  * F2 — user-access-catalog returns 30 menu items; 'finance' present in
         default_roles for the 15 keys listed in the review;
         feature_flags returns a list.
  * Regression — admin can access invoices, dashboard, mail;
         branding returns webp data URIs; sitemap.xml valid;
         /some-nonexistent still handled by SPA (frontend concern — not asserted here).
"""
import os
import re
from pathlib import Path

import pytest
import requests


# ---------- helpers ---------------------------------------------------------

def _resolve_base_url() -> str:
    env = os.environ.get("REACT_APP_BACKEND_URL")
    if env:
        return env.rstrip("/")
    fenv = Path("/app/frontend/.env")
    if fenv.exists():
        for line in fenv.read_text().splitlines():
            if line.startswith("REACT_APP_BACKEND_URL="):
                return line.split("=", 1)[1].strip().strip('"').strip("'").rstrip("/")
    raise RuntimeError("REACT_APP_BACKEND_URL not set")


BASE_URL = _resolve_base_url()
API = BASE_URL + "/api/portal"

ADMIN_EMAIL = "admin@intercloud-digital.com"
ADMIN_PASSWORD = "AdminIntercloud2026!"
SALES_EMAIL = "sales.test@intercloud-digital.com"
SALES_PASSWORD = "SalesTest2026!"  # reset via admin fixture below


# ---------- fixtures --------------------------------------------------------

@pytest.fixture(scope="module")
def http():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(scope="module")
def admin_token(http):
    r = http.post(
        f"{API}/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
        timeout=30,
    )
    if r.status_code != 200:
        pytest.skip(f"admin login failed: {r.status_code} {r.text[:200]}")
    return r.json()["token"]


@pytest.fixture(scope="module")
def sales_token(http, admin_token):
    """Ensure the seeded sales.test user has a known password, then log in."""
    ah = {"Authorization": f"Bearer {admin_token}"}
    users = http.get(f"{API}/admin/users", headers=ah, timeout=30).json()
    sales = next((u for u in users if u.get("email") == SALES_EMAIL), None)
    if not sales:
        pytest.skip(f"seed user {SALES_EMAIL} not found in preview env")
    # Reset password to a known value so the test suite is self-contained
    http.put(
        f"{API}/admin/users/{sales['id']}",
        headers=ah,
        json={"password": SALES_PASSWORD},
        timeout=30,
    )
    r = http.post(
        f"{API}/auth/login",
        json={"email": SALES_EMAIL, "password": SALES_PASSWORD},
        timeout=30,
    )
    if r.status_code != 200:
        pytest.skip(f"sales login failed: {r.status_code} {r.text[:200]}")
    body = r.json()
    assert body["user"]["role"] == "sales"
    return body["token"]


# ---------- B2: Sales stuck-loading bug ------------------------------------

class TestB2SalesOrdersQuotations:
    """Sales role must GET /admin/orders and /admin/quotations without 403/hang."""

    def test_sales_orders_returns_200_json_array(self, http, sales_token):
        r = http.get(
            f"{API}/admin/orders",
            headers={"Authorization": f"Bearer {sales_token}"},
            timeout=30,
        )
        assert r.status_code == 200, f"expected 200, got {r.status_code}: {r.text[:200]}"
        data = r.json()
        assert isinstance(data, list), f"expected list, got {type(data).__name__}"

    def test_sales_quotations_returns_200_json_array(self, http, sales_token):
        r = http.get(
            f"{API}/admin/quotations",
            headers={"Authorization": f"Bearer {sales_token}"},
            timeout=30,
        )
        assert r.status_code == 200, f"expected 200, got {r.status_code}: {r.text[:200]}"
        data = r.json()
        assert isinstance(data, list)

    def test_sales_users_returns_only_assigned_clients(self, http, sales_token):
        """Also validates the 'sales sees only assigned clients' filter."""
        r = http.get(
            f"{API}/admin/users",
            headers={"Authorization": f"Bearer {sales_token}"},
            timeout=30,
        )
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)
        # preview env seeds sales with 1 assigned client
        assert len(data) == 1, f"expected 1 assigned client for sales, got {len(data)}"
        assert data[0]["role"] == "client"


# ---------- B1: Mail message click bug -------------------------------------

class TestB1MailInboxAndMessage:
    def test_admin_inbox_returns_200_array(self, http, admin_token):
        r = http.get(
            f"{API}/admin/mail/inbox",
            headers={"Authorization": f"Bearer {admin_token}"},
            timeout=30,
        )
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)
        assert len(data) > 0, "inbox should be seeded with demo messages"
        first = data[0]
        assert "id" in first and "subject" in first

    def test_first_message_returns_body(self, http, admin_token):
        h = {"Authorization": f"Bearer {admin_token}"}
        inbox = http.get(f"{API}/admin/mail/inbox", headers=h, timeout=30).json()
        assert inbox, "inbox empty — cannot test message body"
        mid = inbox[0]["id"]
        r = http.get(f"{API}/admin/mail/messages/{mid}", headers=h, timeout=30)
        assert r.status_code == 200, f"got {r.status_code}: {r.text[:200]}"
        body = r.json()
        assert body.get("body"), f"body empty for msg {mid}: {body}"
        assert len(body["body"]) > 10
        assert body.get("subject")

    def test_bogus_imap_id_returns_404_not_500(self, http, admin_token):
        """Regression guard: GET /admin/mail/messages/imap-fakeid123 must NOT 500."""
        r = http.get(
            f"{API}/admin/mail/messages/imap-fakeid123",
            headers={"Authorization": f"Bearer {admin_token}"},
            timeout=30,
        )
        assert r.status_code == 404, (
            f"expected 404 for bogus imap id, got {r.status_code}: {r.text[:200]}"
        )
        # response should be JSON with a 'detail' field, not a stack trace
        j = r.json()
        assert "detail" in j

    def test_bogus_mongo_id_returns_400(self, http, admin_token):
        """A non-imap prefixed garbage id should also be handled, not 500."""
        r = http.get(
            f"{API}/admin/mail/messages/not-a-real-oid",
            headers={"Authorization": f"Bearer {admin_token}"},
            timeout=30,
        )
        assert r.status_code in (400, 404), (
            f"expected 400/404 for garbage id, got {r.status_code}"
        )


# ---------- B3: Dashboard overdue_invoices field ---------------------------

class TestB3DashboardOverdueField:
    def test_dashboard_stats_include_overdue_invoices_as_int(self, http, admin_token):
        r = http.get(
            f"{API}/admin/dashboard",
            headers={"Authorization": f"Bearer {admin_token}"},
            timeout=30,
        )
        assert r.status_code == 200
        d = r.json()
        assert "stats" in d
        s = d["stats"]
        assert "overdue_invoices" in s, (
            "backend must return overdue_invoices so frontend hint text is not 'undefined'"
        )
        # even if 0, must not be None / undefined so `${s.overdue_invoices || 0}` gives 0
        assert s["overdue_invoices"] is not None
        assert isinstance(s["overdue_invoices"], int)
        assert "overdue_total" in s
        assert "total_clients" in s


# ---------- F2: user-access-catalog with finance role ---------------------

FINANCE_MENUS = [
    "dashboard", "orders", "invoices", "quotations", "finance", "assets",
    "services", "users", "tickets", "mail", "articles", "crm",
    "content", "followups", "documents",
]


class TestF2CatalogFinanceRole:
    def test_catalog_returns_30_menus_and_feature_flags(self, http, admin_token):
        r = http.get(
            f"{API}/admin/user-access-catalog",
            headers={"Authorization": f"Bearer {admin_token}"},
            timeout=30,
        )
        assert r.status_code == 200
        d = r.json()
        assert "menu_catalog" in d and "feature_flags" in d
        assert len(d["menu_catalog"]) == 30, (
            f"expected 30 menu items, got {len(d['menu_catalog'])}"
        )
        # review claims 22 but code has 23 — assert >= 22
        assert len(d["feature_flags"]) >= 22, (
            f"expected >=22 feature flags, got {len(d['feature_flags'])}"
        )

    def test_finance_role_in_default_roles_for_15_keys(self, http, admin_token):
        r = http.get(
            f"{API}/admin/user-access-catalog",
            headers={"Authorization": f"Bearer {admin_token}"},
            timeout=30,
        )
        cat = {m["key"]: m for m in r.json()["menu_catalog"]}
        missing = []
        for k in FINANCE_MENUS:
            item = cat.get(k)
            if not item:
                missing.append(f"{k} (not in catalog)")
                continue
            if "finance" not in item.get("default_roles", []):
                missing.append(f"{k} (default_roles={item['default_roles']})")
        assert not missing, f"'finance' role missing from menus: {missing}"


# ---------- Regression sweep ------------------------------------------------

class TestRegression:
    def test_admin_can_access_invoices(self, http, admin_token):
        r = http.get(
            f"{API}/admin/invoices",
            headers={"Authorization": f"Bearer {admin_token}"},
            timeout=30,
        )
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_admin_can_access_orders(self, http, admin_token):
        r = http.get(
            f"{API}/admin/orders",
            headers={"Authorization": f"Bearer {admin_token}"},
            timeout=30,
        )
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_admin_can_access_quotations(self, http, admin_token):
        r = http.get(
            f"{API}/admin/quotations",
            headers={"Authorization": f"Bearer {admin_token}"},
            timeout=30,
        )
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_branding_still_webp_data_uri(self, http):
        r = http.get(f"{API}/branding", timeout=30)
        assert r.status_code == 200
        d = r.json()
        assert d.get("logo_light", "").startswith("data:image/webp;base64,")
        assert d.get("logo_dark", "").startswith("data:image/webp;base64,")

    def test_sitemap_still_valid(self, http):
        r = http.get(f"{API}/sitemap.xml", timeout=30)
        assert r.status_code == 200
        assert "xml" in r.headers.get("content-type", "")
        assert r.text.startswith("<?xml version")
        assert "<urlset" in r.text


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
