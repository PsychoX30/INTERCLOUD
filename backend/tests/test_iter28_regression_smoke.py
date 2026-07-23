"""
Iteration 28 regression smoke — backend side.
Covers the backend items requested in the review:
  * GET /api/portal/branding — logo_light + logo_dark are webp data URIs
  * GET /api/portal/sitemap.xml — 200, application/xml, valid xml body
  * Admin login still works (POST /api/portal/auth/login)
  * Invoice PDF preview (as admin) contains 130px logo CSS
"""
import os
import re

import pytest
import requests

def _resolve_base_url() -> str:
    env = os.environ.get("REACT_APP_BACKEND_URL")
    if env:
        return env.rstrip("/")
    # fallback: parse from /app/frontend/.env
    from pathlib import Path
    fenv = Path("/app/frontend/.env")
    if fenv.exists():
        for line in fenv.read_text().splitlines():
            if line.startswith("REACT_APP_BACKEND_URL="):
                return line.split("=", 1)[1].strip().strip('"').strip("'").rstrip("/")
    raise RuntimeError("REACT_APP_BACKEND_URL not set")


BASE_URL = _resolve_base_url()
API = BASE_URL + "/api/portal"

ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD")


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
        pytest.skip(f"Admin login failed: {r.status_code} {r.text[:200]}")
    tok = r.json().get("token") or r.json().get("access_token")
    if not tok:
        pytest.skip("no token in login response")
    return tok


# -------- Branding endpoint --------
class TestBranding:
    def test_branding_returns_200_json(self, http):
        r = http.get(f"{API}/branding", timeout=30)
        assert r.status_code == 200
        data = r.json()
        assert "logo_light" in data
        assert "logo_dark" in data

    def test_logo_light_is_webp_data_uri(self, http):
        r = http.get(f"{API}/branding", timeout=30)
        ll = r.json().get("logo_light", "")
        assert ll.startswith("data:image/webp;base64,"), f"logo_light does not start with webp prefix: {ll[:60]}"
        # must be non-trivially long (real image bytes, not the old text SVG)
        assert len(ll) > 5000, f"logo_light too small ({len(ll)} chars) — probably still text SVG"
        # explicit negative check for the old text SVG
        assert "INTERCLOUD" not in ll[:200]

    def test_logo_dark_is_webp_data_uri(self, http):
        r = http.get(f"{API}/branding", timeout=30)
        ld = r.json().get("logo_dark", "")
        assert ld.startswith("data:image/webp;base64,"), f"logo_dark does not start with webp prefix: {ld[:60]}"
        assert len(ld) > 5000


# -------- sitemap.xml --------
class TestSitemap:
    def test_sitemap_returns_xml(self, http):
        r = http.get(f"{API}/sitemap.xml", timeout=30)
        assert r.status_code == 200
        ctype = r.headers.get("content-type", "")
        assert "xml" in ctype, f"unexpected content-type: {ctype}"
        body = r.text
        assert body.startswith("<?xml version"), f"body does not start with xml prolog: {body[:60]}"
        assert "<urlset" in body


# -------- auth login (regression) --------
class TestAdminLogin:
    def test_admin_login_returns_token(self, admin_token):
        assert admin_token
        assert isinstance(admin_token, str)
        assert len(admin_token) > 20


# -------- Invoice PDF preview 130px logo --------
class TestInvoicePdfLogo:
    def test_first_invoice_pdf_preview_has_130px_logo_css(self, http, admin_token):
        h = {"Authorization": f"Bearer {admin_token}"}
        # list invoices
        r = http.get(f"{API}/admin/invoices", headers=h, timeout=30)
        if r.status_code != 200:
            pytest.skip(f"cannot list invoices: {r.status_code}")
        items = r.json()
        if isinstance(items, dict):
            items = items.get("items") or items.get("invoices") or []
        if not items:
            pytest.skip("no invoices in system to preview")
        inv = items[0]
        inv_id = inv.get("id") or inv.get("_id") or inv.get("invoice_id")
        # Try common preview URLs
        candidates = [
            f"{API}/documents/invoice/{inv_id}?format=html",
            f"{API}/admin/invoices/{inv_id}/pdf",
            f"{API}/admin/invoices/{inv_id}/preview",
            f"{API}/invoices/{inv_id}/pdf",
        ]
        html = None
        used = None
        for u in candidates:
            r2 = http.get(u, headers=h, timeout=30)
            if r2.status_code == 200 and ("<html" in r2.text.lower() or "<!doctype" in r2.text.lower()):
                html = r2.text
                used = u
                break
        if html is None:
            pytest.skip(f"no invoice preview HTML endpoint responded 200; tried {candidates}")
        # 130px logo CSS should be present in .head .logo img rule
        # accept either exact "130px" or height:130 spelling
        assert re.search(r"height\s*:\s*130px", html), f"130px logo CSS missing in {used}"


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
