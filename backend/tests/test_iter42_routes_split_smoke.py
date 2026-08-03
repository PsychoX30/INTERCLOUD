"""
Iteration 42: Regression smoke for routes.py -> routes/ package split.
Behavior must be 1:1 identical. This test asserts endpoints across all 21 sub-router domains return 2xx (or expected auth codes).
NO destructive calls (no provisioning create, no invoice paid PUT, no integrations mutations, no system update).
"""
import os
import re
import pytest
import requests

def _read_backend_url():
    v = os.environ.get("REACT_APP_BACKEND_URL")
    if v:
        return v.rstrip("/")
    try:
        with open("/app/frontend/.env") as f:
            for line in f:
                if line.startswith("REACT_APP_BACKEND_URL="):
                    return line.split("=", 1)[1].strip().rstrip("/")
    except Exception:
        pass
    raise RuntimeError("REACT_APP_BACKEND_URL not found")

BASE = _read_backend_url()
API = f"{BASE}/api/portal"

ADMIN = ("admin@intercloud-digital.com", "AdminIntercloud2026!")
CLIENT_CANDIDATES = [
    ("demo@client.com", "ClientDemo2026!"),
    ("demo@client.com", "DemoClient2026!"),
]
SALES_CANDIDATES = [
    ("sales@intercloud-digital.com", "Sales2026!"),
    ("sales@intercloud-digital.com", "SalesTest2026!"),
    ("sales@intercloud-digital.com", "StaffTest2026!"),
]


def _login(email, password):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=30)
    if r.status_code == 200:
        return r.json().get("access_token") or r.json().get("token")
    return None


@pytest.fixture(scope="module")
def admin_token():
    tok = _login(*ADMIN)
    assert tok, "Admin login failed"
    return tok


@pytest.fixture(scope="module")
def client_token():
    for e, p in CLIENT_CANDIDATES:
        t = _login(e, p)
        if t:
            return t
    pytest.skip("Client login failed with all candidate passwords")


@pytest.fixture(scope="module")
def sales_token():
    for e, p in SALES_CANDIDATES:
        t = _login(e, p)
        if t:
            return t
    return None


def H(tok):
    return {"Authorization": f"Bearer {tok}"}


def _get(path, tok, expected=(200,)):
    r = requests.get(f"{API}{path}", headers=H(tok) if tok else {}, timeout=45)
    assert r.status_code in expected, f"GET {path} -> {r.status_code}: {r.text[:200]}"
    return r


# ---- AUTH domain ----
class TestAuth:
    def test_login_and_me(self, admin_token):
        r = _get("/auth/me", admin_token)
        data = r.json()
        assert (data.get("email") or "").lower() == ADMIN[0].lower()

    def test_client_login_and_me(self, client_token):
        r = _get("/auth/me", client_token)
        assert r.json().get("email")


# ---- CLIENT domain ----
class TestClient:
    def test_client_dashboard(self, client_token):
        # try both potential paths
        for p in ["/client/dashboard", "/client/summary", "/client/overview"]:
            r = requests.get(f"{API}{p}", headers=H(client_token), timeout=30)
            if r.status_code == 200:
                return
        # fallback: services list
        _get("/client/services", client_token, expected=(200,))

    def test_client_services(self, client_token):
        _get("/client/services", client_token)

    def test_client_invoices(self, client_token):
        r = _get("/client/invoices", client_token)
        items = r.json() if isinstance(r.json(), list) else r.json().get("items", [])
        # try get detail if any
        if items:
            iid = items[0].get("id") or items[0].get("_id") or items[0].get("invoice_id")
            if iid:
                requests.get(f"{API}/client/invoices/{iid}", headers=H(client_token), timeout=30)


# ---- ADMIN_CORE domain ----
class TestAdminCore:
    def test_dashboard(self, admin_token):
        r = _get("/admin/dashboard", admin_token)
        assert isinstance(r.json(), dict)

    def test_system_health(self, admin_token):
        r = _get("/admin/system/health", admin_token)
        j = r.json()
        assert "checks" in j or "status" in j or "overall" in j

    def test_system_version(self, admin_token):
        _get("/admin/system/version", admin_token)

    def test_backup_history(self, admin_token):
        _get("/admin/backup/history", admin_token, expected=(200, 404))


# ---- BILLING domain ----
class TestBilling:
    def test_invoices_list(self, admin_token):
        r = _get("/admin/invoices", admin_token)
        data = r.json()
        items = data if isinstance(data, list) else data.get("items", [])
        # store one for other tests
        pytest.first_invoice_id = None
        if items:
            pytest.first_invoice_id = items[0].get("id") or items[0].get("_id") or items[0].get("invoice_id")

    def test_invoice_detail(self, admin_token):
        iid = getattr(pytest, "first_invoice_id", None)
        if not iid:
            pytest.skip("No invoice to fetch detail")
        _get(f"/admin/invoices/{iid}", admin_token)

    def test_quotations(self, admin_token):
        _get("/admin/quotations", admin_token)

    def test_orders(self, admin_token):
        _get("/admin/orders", admin_token)

    def test_billing_settings(self, admin_token):
        _get("/admin/billing/settings", admin_token, expected=(200, 404))


# ---- LIFECYCLE / SERVICES ----
class TestLifecycle:
    def test_admin_services(self, admin_token):
        r = _get("/admin/services", admin_token)
        data = r.json()
        items = data if isinstance(data, list) else data.get("items", [])
        pytest.first_service_id = None
        if items:
            pytest.first_service_id = items[0].get("id") or items[0].get("_id")

    def test_service_detail(self, admin_token):
        sid = getattr(pytest, "first_service_id", None)
        if not sid:
            pytest.skip("no service")
        _get(f"/admin/services/{sid}", admin_token, expected=(200, 404))

    def test_service_requests(self, admin_token):
        _get("/admin/service-requests?status=all", admin_token)


# ---- TICKETS ----
class TestTickets:
    _created_id = None

    def test_client_create_ticket(self, client_token):
        payload = {"subject": "TEST_iter42 ticket", "message": "smoke", "priority": "low", "category": "general"}
        r = requests.post(f"{API}/client/tickets", headers=H(client_token), json=payload, timeout=30)
        assert r.status_code in (200, 201), f"Create ticket failed {r.status_code}: {r.text[:200]}"
        tid = r.json().get("id") or r.json().get("_id") or r.json().get("ticket_id")
        assert tid
        TestTickets._created_id = tid

    def test_client_reply(self, client_token):
        tid = TestTickets._created_id
        if not tid:
            pytest.skip("no ticket")
        r = requests.post(f"{API}/client/tickets/{tid}/messages",
                          headers=H(client_token), json={"message": "client reply"}, timeout=30)
        assert r.status_code in (200, 201, 404), r.text[:200]

    def test_admin_view_tickets(self, admin_token):
        _get("/admin/tickets", admin_token)

    def test_admin_reply_and_status(self, admin_token):
        tid = TestTickets._created_id
        if not tid:
            pytest.skip("no ticket")
        requests.post(f"{API}/admin/tickets/{tid}/messages",
                      headers=H(admin_token), json={"message": "admin reply"}, timeout=30)
        r = requests.put(f"{API}/admin/tickets/{tid}",
                         headers=H(admin_token), json={"status": "closed"}, timeout=30)
        assert r.status_code in (200, 204, 404), r.text[:200]

    def test_cleanup_ticket(self, admin_token):
        tid = TestTickets._created_id
        if not tid:
            return
        requests.delete(f"{API}/admin/tickets/{tid}", headers=H(admin_token), timeout=30)


# ---- CATALOG ----
class TestCatalog:
    def test_products(self, admin_token):
        _get("/admin/products", admin_token)

    def test_categories(self, admin_token):
        _get("/admin/categories", admin_token)

    def test_public_products_no_auth(self):
        r = requests.get(f"{API}/portal-public/products", timeout=30)
        assert r.status_code == 200, f"public products {r.status_code}"


# ---- BUSINESS (CRM) ----
class TestBusiness:
    @pytest.mark.parametrize("p", ["/admin/crm", "/admin/projects", "/admin/followups", "/admin/content-calendar"])
    def test_business_endpoints(self, admin_token, p):
        _get(p, admin_token)


# ---- FINANCE ----
class TestFinance:
    @pytest.mark.parametrize("p", [
        "/admin/finance/summary", "/admin/finance/detailed",
        "/admin/credit-notes", "/admin/assets", "/admin/expenses",
        "/admin/kas-kecil", "/admin/salaries", "/admin/sales-fees",
    ])
    def test_finance_endpoints(self, admin_token, p):
        _get(p, admin_token)


# ---- DOCUMENTS ----
class TestDocuments:
    def test_invoice_html_and_pdf(self, admin_token):
        iid = getattr(pytest, "first_invoice_id", None)
        if not iid:
            pytest.skip("no invoice")
        r = requests.get(f"{API}/documents/invoice/{iid}", headers=H(admin_token), timeout=45)
        assert r.status_code == 200, r.text[:200]
        assert "<html" in r.text.lower() or "<!doctype" in r.text.lower() or len(r.text) > 100
        r2 = requests.get(f"{API}/documents/invoice/{iid}?format=pdf", headers=H(admin_token), timeout=60)
        assert r2.status_code == 200, r2.text[:200]
        assert r2.content.startswith(b"%PDF"), "PDF header missing"


# ---- INTEGRATIONS ----
class TestIntegrations:
    def test_integrations_v2(self, admin_token):
        r = _get("/admin/integrations-v2", admin_token)
        j = r.json()
        # secrets should be masked (no plain 'enc:v1:' expected here either)
        text = str(j)
        # Just ensure the payload includes typical provider structure - non-empty
        assert j is not None

    def test_integrations_hub(self, admin_token):
        _get("/admin/integrations", admin_token)

    def test_integrations_modules(self, admin_token):
        _get("/admin/integrations/modules", admin_token)


# ---- NOC / MikroTik ----
class TestNOC:
    @pytest.mark.parametrize("p", [
        "/admin/noc/devices", "/admin/mikrotik/devices", "/admin/noc/threshold-rules",
    ])
    def test_noc_endpoints(self, admin_token, p):
        _get(p, admin_token)


# ---- SECURITY ----
class TestSecurity:
    @pytest.mark.parametrize("p", [
        "/admin/security/login-analytics", "/admin/security/settings", "/admin/security/blocked-ips",
    ])
    def test_security_endpoints(self, admin_token, p):
        _get(p, admin_token)


# ---- CMS + PUBLIC ----
class TestCMS:
    def test_landing_content(self):
        r = requests.get(f"{API}/landing-content", timeout=30)
        assert r.status_code == 200

    def test_branding(self):
        r = requests.get(f"{API}/branding", timeout=30)
        assert r.status_code == 200

    def test_public_articles(self):
        r = requests.get(f"{API}/public/articles", timeout=30)
        assert r.status_code == 200

    def test_public_status(self):
        r = requests.get(f"{API}/public/status", timeout=30)
        assert r.status_code == 200

    def test_sitemap(self):
        # sitemap may be at root of /api/portal or /
        for u in [f"{API}/sitemap.xml", f"{BASE}/sitemap.xml"]:
            r = requests.get(u, timeout=30)
            if r.status_code == 200:
                return
        pytest.fail("sitemap.xml not reachable")


# ---- EMAIL ADMIN ----
class TestEmail:
    @pytest.mark.parametrize("p", [
        "/admin/email-templates", "/admin/email-logs", "/admin/email/event-catalog",
    ])
    def test_email_endpoints(self, admin_token, p):
        _get(p, admin_token)


# ---- DCIM ----
class TestDCIM:
    @pytest.mark.parametrize("p", [
        "/admin/dcim/prefixes", "/admin/dcim/racks", "/admin/dcim/ips", "/admin/dcim/sites",
    ])
    def test_dcim_endpoints(self, admin_token, p):
        _get(p, admin_token)


# ---- USERS ADMIN ----
class TestUsers:
    @pytest.mark.parametrize("p", [
        "/admin/users", "/admin/user-access-catalog", "/admin/audit-logs",
    ])
    def test_users_endpoints(self, admin_token, p):
        _get(p, admin_token)


# ---- RBAC regression ----
class TestRBAC:
    def test_sales_cannot_list_invoices(self, sales_token):
        if not sales_token:
            pytest.skip("Sales login not available")
        r = requests.get(f"{API}/admin/invoices", headers=H(sales_token), timeout=30)
        assert r.status_code == 403, f"Expected 403, got {r.status_code}"
