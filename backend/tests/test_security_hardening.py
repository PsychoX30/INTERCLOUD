"""Security hardening regression tests: SEC-002 XSS sanitization, SEC-003 Sales RBAC, and login/regression checks."""
import os
import re
import pytest
import requests

BASE = os.environ.get("REACT_APP_BACKEND_URL", "https://repo-analyzer-264.preview.emergentagent.com").rstrip("/")
API = f"{BASE}/api/portal"

ADMIN = ("admin@intercloud-digital.com", "AdminIntercloud2026!")
CLIENT = ("demo@client.com", "ClientDemo2026!")
SALES = ("sales@intercloud-digital.com", "Sales2026!")


def _login(email, password):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=30)
    return r


@pytest.fixture(scope="module")
def admin_token():
    r = _login(*ADMIN)
    assert r.status_code == 200, f"admin login failed: {r.status_code} {r.text}"
    return r.json().get("access_token") or r.json().get("token")


@pytest.fixture(scope="module")
def client_token():
    r = _login(*CLIENT)
    assert r.status_code == 200, f"client login failed: {r.status_code} {r.text}"
    return r.json().get("access_token") or r.json().get("token")


@pytest.fixture(scope="module")
def sales_token():
    r = _login(*SALES)
    assert r.status_code == 200, f"sales login failed: {r.status_code} {r.text}"
    return r.json().get("access_token") or r.json().get("token")


def _h(tok):
    return {"Authorization": f"Bearer {tok}"}


# ------------------------------- Login regression -------------------------------
class TestLoginRegression:
    def test_admin_login(self, admin_token):
        assert admin_token and len(admin_token) > 10

    def test_client_login(self, client_token):
        assert client_token and len(client_token) > 10

    def test_sales_login(self, sales_token):
        assert sales_token and len(sales_token) > 10


# ------------------------------- SEC-002: XSS sanitization ----------------------
MALICIOUS = (
    '<p>Hi <b>x</b></p>'
    '<script>alert(1)</script>'
    '<img src=x onerror=alert(2)>'
    '<a href="javascript:alert(3)">c</a>'
    '<iframe src=evil></iframe>'
    '<h2>Sub</h2><ul><li>item</li></ul>'
)


class TestArticleXSSSanitization:
    created_id = None

    def test_create_article_sanitizes(self, admin_token):
        payload = {
            "title": "TEST_SEC_ARTICLE",
            "slug": "test-sec-article-xss",
            "body_html": MALICIOUS,
            "status": "draft",
            "excerpt": "test",
        }
        r = requests.post(f"{API}/admin/articles", json=payload, headers=_h(admin_token), timeout=30)
        assert r.status_code in (200, 201), f"{r.status_code} {r.text}"
        data = r.json()
        body = data.get("body_html", "")
        assert "<script" not in body.lower(), f"script tag not stripped: {body!r}"
        assert "onerror" not in body.lower(), f"onerror not stripped: {body!r}"
        assert "javascript:" not in body.lower(), f"javascript: URL not stripped: {body!r}"
        assert "<iframe" not in body.lower(), f"iframe not stripped: {body!r}"
        # Safe tags kept
        for tag in ["<p", "<b", "<h2", "<ul", "<li", "<img", "<a"]:
            assert tag in body.lower(), f"safe tag {tag} missing: {body!r}"
        TestArticleXSSSanitization.created_id = data.get("id") or data.get("_id") or data.get("slug")
        assert TestArticleXSSSanitization.created_id, f"no id in response: {data}"

    def test_get_article_stored_sanitized(self, admin_token):
        aid = TestArticleXSSSanitization.created_id
        assert aid
        r = requests.get(f"{API}/admin/articles/{aid}", headers=_h(admin_token), timeout=30)
        assert r.status_code == 200, f"{r.status_code} {r.text}"
        body = r.json().get("body_html", "").lower()
        assert "<script" not in body
        assert "onerror" not in body
        assert "javascript:" not in body
        assert "<iframe" not in body

    def test_update_article_sanitizes(self, admin_token):
        aid = TestArticleXSSSanitization.created_id
        assert aid
        new_payload = {
            "title": "TEST_SEC_ARTICLE",
            "slug": "test-sec-article-xss",
            "body_html": '<p>updated</p><script>alert(99)</script><b>ok</b>',
            "status": "draft",
            "excerpt": "test",
        }
        r = requests.put(f"{API}/admin/articles/{aid}", json=new_payload, headers=_h(admin_token), timeout=30)
        assert r.status_code == 200, f"{r.status_code} {r.text}"
        body = r.json().get("body_html", "").lower()
        assert "<script" not in body, f"script not stripped on update: {body!r}"
        assert "<b" in body and "<p" in body

    def test_cleanup_article(self, admin_token):
        aid = TestArticleXSSSanitization.created_id
        if not aid:
            return
        r = requests.delete(f"{API}/admin/articles/{aid}", headers=_h(admin_token), timeout=30)
        assert r.status_code in (200, 204), f"cleanup failed: {r.status_code} {r.text}"


# ------------------------------- Public article regression ----------------------
class TestPublicArticles:
    def test_public_list(self):
        r = requests.get(f"{API}/public/articles", timeout=30)
        assert r.status_code == 200, f"{r.status_code} {r.text}"
        data = r.json()
        # Might be list or {items:[]}
        items = data if isinstance(data, list) else data.get("items") or data.get("articles") or []
        assert isinstance(items, list)

    def test_public_slug(self):
        r = requests.get(f"{API}/public/articles", timeout=30)
        data = r.json()
        items = data if isinstance(data, list) else data.get("items") or data.get("articles") or []
        published = [a for a in items if (a.get("status") in (None, "published"))]
        if not published:
            pytest.skip("no published articles to test slug fetch")
        slug = published[0].get("slug")
        if not slug:
            pytest.skip("no slug field")
        r2 = requests.get(f"{API}/public/articles/{slug}", timeout=30)
        assert r2.status_code == 200, f"{r2.status_code} {r2.text}"
        body = r2.json()
        assert "title" in body
        assert "body_html" in body


# ------------------------------- SEC-003: Sales RBAC lifecycle ------------------
DEMO_CLIENT_ID = "6a63a0654ee28b6b92ad2806"


def _find_demo_service(admin_token):
    r = requests.get(f"{API}/admin/services", headers=_h(admin_token), timeout=30)
    assert r.status_code == 200, f"{r.status_code} {r.text}"
    data = r.json()
    items = data if isinstance(data, list) else data.get("items") or data.get("services") or []
    # Look for an active demo service
    for it in items:
        uid = it.get("user_id") or ""
        email = (it.get("user_email") or it.get("email") or "").lower()
        status = (it.get("status") or "").lower()
        if (uid == DEMO_CLIENT_ID or "demo@client.com" in email) and status == "active":
            return it
    for it in items:
        uid = it.get("user_id") or ""
        email = (it.get("user_email") or it.get("email") or "").lower()
        if uid == DEMO_CLIENT_ID or "demo@client.com" in email:
            return it
    return None


class TestAdminLifecycle:
    def test_admin_service_requests_list(self, admin_token):
        r = requests.get(f"{API}/admin/service-requests", params={"status": "all"}, headers=_h(admin_token), timeout=30)
        assert r.status_code == 200

    def test_admin_suspend_unsuspend(self, admin_token):
        svc = _find_demo_service(admin_token)
        if not svc:
            pytest.skip("no demo service found")
        sid = svc.get("id") or svc.get("_id") or svc.get("service_id")
        assert sid
        r1 = requests.post(f"{API}/admin/services/{sid}/suspend", json={"reason": "TEST admin regression"}, headers=_h(admin_token), timeout=30)
        assert r1.status_code == 200, f"suspend failed: {r1.status_code} {r1.text}"
        # verify status
        r2 = requests.post(f"{API}/admin/services/{sid}/unsuspend", json={}, headers=_h(admin_token), timeout=30)
        assert r2.status_code == 200, f"unsuspend failed: {r2.status_code} {r2.text}"


class TestSalesRBAC:
    def test_sales_can_list_scoped(self, sales_token):
        r = requests.get(f"{API}/admin/service-requests", headers=_h(sales_token), timeout=30)
        assert r.status_code == 200, f"{r.status_code} {r.text}"
        data = r.json()
        items = data if isinstance(data, list) else data.get("items") or data.get("requests") or []
        # All items should belong to demo client (either by email or user_id)
        for it in items:
            uid = it.get("user_id") or ""
            email = (it.get("user_email") or it.get("email") or "").lower()
            assert (uid == DEMO_CLIENT_ID) or ("demo@client.com" in email), f"sales sees non-demo item: {it}"

    def test_sales_can_suspend_assigned(self, sales_token, admin_token):
        svc = _find_demo_service(admin_token)
        if not svc:
            pytest.skip("no demo service")
        sid = svc.get("id") or svc.get("_id") or svc.get("service_id")
        r1 = requests.post(f"{API}/admin/services/{sid}/suspend", json={"reason": "TEST sales rbac"}, headers=_h(sales_token), timeout=30)
        assert r1.status_code == 200, f"sales suspend failed: {r1.status_code} {r1.text}"
        r2 = requests.post(f"{API}/admin/services/{sid}/unsuspend", json={}, headers=_h(sales_token), timeout=30)
        assert r2.status_code == 200, f"sales unsuspend failed: {r2.status_code} {r2.text}"

    def test_client_cannot_suspend(self, client_token, admin_token):
        svc = _find_demo_service(admin_token)
        if not svc:
            pytest.skip("no demo service")
        sid = svc.get("id") or svc.get("_id") or svc.get("service_id")
        r = requests.post(f"{API}/admin/services/{sid}/suspend", json={"reason": "should be denied"}, headers=_h(client_token), timeout=30)
        assert r.status_code in (401, 403), f"expected 401/403 for client, got {r.status_code} {r.text}"
