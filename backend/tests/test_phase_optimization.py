# NB: rate-limit sensitive — this suite exhausts the 10/min login and 5/hour
# register budgets. Do not run twice within one minute. Uses `-o addopts=` to
# disable xdist so ordering is deterministic.

"""Phase 1-4 System-wide Optimisation Tests (Iteration 23).

Coverage:
- Phase 1: GZip compression, lazy chunks, MongoDB indexes
- Phase 2: Security headers, CORS whitelist, rate limits, CSP report, log sanitizer
- Phase 3: robots.txt, sitemap.xml, canonical + JSON-LD
- Phase 4: Reusable UI components exist
- Regression: blackhole prefix_filter, LG ping src_address, diagnostics traceroute

Runs against the external preview URL (REACT_APP_BACKEND_URL). GZip / CORS /
rate-limit / CSP tests also probe the ORIGIN (localhost:8001) to bypass any
Cloudflare edge rewrites, per the review request.
"""
from __future__ import annotations

import gzip
import os
import re
import time
import uuid

import pytest
import requests
import xml.etree.ElementTree as ET

def _read_frontend_url():
    try:
        with open("/app/frontend/.env") as f:
            for line in f:
                if line.startswith("REACT_APP_BACKEND_URL="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    except FileNotFoundError:
        pass
    return None


EXT = (os.environ.get("REACT_APP_BACKEND_URL") or _read_frontend_url() or "").rstrip("/")
assert EXT, "REACT_APP_BACKEND_URL not configured"
ORIGIN = "http://localhost:8001"                # bypass CF for header assertions
ADMIN_EMAIL = "admin@intercloud-digital.com"
ADMIN_PWD   = "AdminIntercloud2026!"


# ----------------------------- shared fixtures -----------------------------
@pytest.fixture(scope="session")
def s():
    sess = requests.Session()
    sess.headers.update({"Accept": "application/json"})
    return sess


@pytest.fixture(scope="session")
def admin_token(s):
    r = s.post(f"{EXT}/api/portal/auth/login",
               json={"email": ADMIN_EMAIL, "password": ADMIN_PWD}, timeout=15)
    if r.status_code != 200:
        pytest.skip(f"admin login failed: {r.status_code} {r.text[:200]}")
    return r.json()["token"]


@pytest.fixture(scope="session")
def admin_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


# ================================================================
# PHASE 1 — GZIP
# ================================================================
class TestPhase1Gzip:
    """Large payloads compressed; small NOT forced to gzip."""

    def test_gzip_engages_on_large_payload_origin(self):
        # /api/portal/public/articles is ~3KB — comfortably > 1KB threshold
        r = requests.get(f"{ORIGIN}/api/portal/public/articles",
                         headers={"Accept-Encoding": "gzip"}, timeout=10)
        assert r.status_code == 200, r.text[:200]
        assert r.headers.get("content-encoding") == "gzip", \
            f"expected gzip, got {r.headers.get('content-encoding')!r}. headers={dict(r.headers)}"
        # requests auto-decompresses; ensure decoded body is non-trivial
        assert len(r.text) > 1024

    def test_gzip_engages_on_large_payload_external(self):
        r = requests.get(f"{EXT}/api/portal/public/articles",
                         headers={"Accept-Encoding": "gzip"}, timeout=15)
        assert r.status_code == 200
        # via CF, gzip should still be present
        assert r.headers.get("content-encoding") == "gzip"

    def test_gzip_not_forced_on_small_payload_origin(self):
        """Per user spec: 'Small responses should NOT be forced to gzip.'
        /api/ returns 25 bytes — smaller than minimum_size=1024. Should be
        served uncompressed."""
        r = requests.get(f"{ORIGIN}/api/",
                         headers={"Accept-Encoding": "gzip"}, timeout=5)
        assert r.status_code == 200
        ce = r.headers.get("content-encoding")
        assert ce != "gzip", (
            f"small 25-byte response was gzip'd — minimum_size=1024 threshold "
            f"NOT respected. Content-Encoding={ce!r}. Body={r.text!r}. "
            f"Likely cause: SecurityHeadersMiddleware (BaseHTTPMiddleware) "
            f"strips Content-Length and streams body with more_body=True on "
            f"the first chunk, forcing GZipResponder into 'streaming' branch."
        )


# ================================================================
# PHASE 1 — Lazy chunks (smoke: landing renders, no admin refs in initial HTML)
# ================================================================
class TestPhase1LazyChunks:
    def test_landing_renders(self):
        r = requests.get(f"{EXT}/", timeout=15)
        assert r.status_code == 200
        # Must at least reference the app entry script
        assert re.search(r"(bundle\.js|main\.[a-z0-9]+\.js)", r.text), \
            "no main entry script in served HTML"

    def test_no_admin_page_in_initial_html(self):
        r = requests.get(f"{EXT}/", timeout=15)
        # These strings would only appear if admin components were inline-bundled
        for needle in ("AdminDashboard", "AdminUsers", "AdminMikrotik"):
            assert needle not in r.text, f"{needle!r} leaked into initial HTML"


# ================================================================
# PHASE 1 — MongoDB indexes (no startup index errors + list APIs 200)
# ================================================================
class TestPhase1Indexes:
    def test_no_index_error_in_startup_log(self):
        try:
            with open("/var/log/supervisor/backend.err.log", "r", errors="replace") as f:
                content = f.read()[-30000:]  # tail
            assert "Index create issue:" not in content, \
                "startup logged 'Index create issue:' — some index creation failed"
        except FileNotFoundError:
            pytest.skip("backend.err.log not available")

    def test_invoice_service_order_lists_do_not_500(self, s, admin_headers):
        for path in ("/api/portal/admin/invoices",
                     "/api/portal/admin/services",
                     "/api/portal/admin/orders"):
            r = s.get(f"{EXT}{path}", headers=admin_headers, timeout=15)
            assert r.status_code < 500, f"{path} → {r.status_code} {r.text[:200]}"


# ================================================================
# PHASE 2 — Security headers
# ================================================================
REQUIRED_SEC_HEADERS = {
    "strict-transport-security":    "max-age=31536000; includeSubDomains; preload",
    "x-content-type-options":       "nosniff",
    "x-frame-options":              "DENY",
    "referrer-policy":              "strict-origin-when-cross-origin",
}


class TestPhase2SecurityHeaders:
    @pytest.mark.parametrize("path", ["/", "/api/portal/public/articles"])
    def test_required_headers_present_origin(self, path):
        r = requests.get(f"{ORIGIN}{path}", timeout=10)
        # accept 200/301/404 — headers must still be attached
        for k, expected in REQUIRED_SEC_HEADERS.items():
            got = r.headers.get(k)
            assert got == expected, f"{path} header {k}={got!r} (want {expected!r})"
        # permissions-policy present (value curated, just assert non-empty)
        assert r.headers.get("permissions-policy"), "permissions-policy missing"
        # CSP report-only present with report-uri
        csp = r.headers.get("content-security-policy-report-only", "")
        assert "report-uri" in csp and "/api/csp-report" in csp, \
            f"CSP report-only missing report-uri /api/csp-report. got={csp[:200]!r}"

    def test_required_headers_external(self):
        r = requests.get(f"{EXT}/api/portal/public/articles", timeout=15)
        for k in REQUIRED_SEC_HEADERS:
            assert r.headers.get(k), f"external missing header {k}"


# ================================================================
# PHASE 2 — CORS whitelist
# ================================================================
class TestPhase2Cors:
    def test_allowed_origin_echoed(self):
        r = requests.options(
            f"{ORIGIN}/api/portal/auth/login",
            headers={"Origin": "https://intercloud-digital.com",
                     "Access-Control-Request-Method": "POST",
                     "Access-Control-Request-Headers": "content-type"},
            timeout=5,
        )
        assert r.status_code in (200, 204), r.text[:200]
        aco = r.headers.get("access-control-allow-origin")
        assert aco == "https://intercloud-digital.com", \
            f"expected echoed origin, got {aco!r}"
        assert r.headers.get("access-control-allow-credentials") == "true"

    def test_disallowed_origin_not_echoed(self):
        r = requests.options(
            f"{ORIGIN}/api/portal/auth/login",
            headers={"Origin": "https://evil.example.com",
                     "Access-Control-Request-Method": "POST"},
            timeout=5,
        )
        aco = r.headers.get("access-control-allow-origin")
        assert aco != "https://evil.example.com"
        assert aco != "*", "wildcard origin returned — whitelist bypass!"


# ================================================================
# PHASE 2 — Rate-limit login (10/minute) & register (5/hour)
# ================================================================
class TestPhase2RateLimit:
    def test_login_rate_limit_returns_429(self):
        # 12 fast POSTs with invalid creds. Expect 10× 401 then 429s.
        codes = []
        retry_after = None
        # Use ORIGIN to avoid CF rate limits interfering
        for i in range(12):
            r = requests.post(f"{ORIGIN}/api/portal/auth/login",
                              json={"email": f"ratelimit_{i}_{uuid.uuid4().hex[:6]}@nope.tld",
                                    "password": "wrong"},
                              timeout=5)
            codes.append(r.status_code)
            if r.status_code == 429:
                retry_after = retry_after or r.headers.get("Retry-After")
        assert 429 in codes, f"no 429 after 12 rapid logins. codes={codes}"
        assert retry_after == "60", f"Retry-After header = {retry_after!r}"

    def test_register_rate_limit_returns_429(self):
        codes = []
        for i in range(8):
            payload = {
                "email": f"reg_{uuid.uuid4().hex[:8]}@example.com",
                "password": "SomePwd!2026",
                "name": "TestUser",
                "company": "T",
                "phone": "+6281234000000",
                "accepts_tos": True,
            }
            r = requests.post(f"{ORIGIN}/api/portal/auth/register",
                              json=payload, timeout=5)
            codes.append(r.status_code)
            if r.status_code == 429:
                break
        assert 429 in codes, f"no 429 after 8 rapid register attempts. codes={codes}"


# ================================================================
# PHASE 2 — CSP report endpoint
# ================================================================
class TestPhase2CspReport:
    def test_csp_report_returns_204(self):
        body = {"csp-report": {"blocked-uri": "inline", "violated-directive": "script-src"}}
        r = requests.post(f"{ORIGIN}/api/csp-report",
                          json=body, timeout=5)
        assert r.status_code == 204

    def test_csp_report_logged_at_warn(self):
        marker = f"cspmark_{uuid.uuid4().hex[:10]}"
        body = {"csp-report": {"blocked-uri": marker}}
        requests.post(f"{ORIGIN}/api/csp-report", json=body, timeout=5)
        time.sleep(0.3)
        # inspect backend log tail
        try:
            with open("/var/log/supervisor/backend.err.log", "r", errors="replace") as f:
                tail = f.read()[-20000:]
            assert marker in tail, "CSP report body not logged"
            assert "WARNING" in tail.split(marker)[0].splitlines()[-1] \
                or "csp-violation" in tail
        except FileNotFoundError:
            pytest.skip("backend log unavailable")


# ================================================================
# PHASE 2 — Log sanitizer (password must not appear in logs)
# ================================================================
class TestPhase2LogSanitizer:
    def test_plaintext_password_not_in_logs(self):
        # Trigger login attempt with a UNIQUE, distinctive password
        secret = f"TESTpwd_{uuid.uuid4().hex}_LEAKcheck"
        requests.post(f"{ORIGIN}/api/portal/auth/login",
                      json={"email": "nope@nope.tld", "password": secret},
                      timeout=5)
        time.sleep(0.3)
        with open("/var/log/supervisor/backend.err.log", "r", errors="replace") as f:
            tail = f.read()[-40000:]
        with open("/var/log/supervisor/backend.out.log", "r", errors="replace") as f:
            tail += "\n" + f.read()[-40000:]
        assert secret not in tail, "plaintext password appeared in logs"


# ================================================================
# PHASE 3 — robots.txt (served by frontend)
# ================================================================
class TestPhase3Robots:
    def test_robots_disallow_portal(self):
        r = requests.get(f"{EXT}/robots.txt", timeout=10)
        assert r.status_code == 200
        assert "Disallow: /portal" in r.text
        assert re.search(r"^Sitemap:\s+\S*/api/portal/sitemap\.xml",
                         r.text, re.M), "no Sitemap: line -> /api/portal/sitemap.xml"


# ================================================================
# PHASE 3 — sitemap.xml
# ================================================================
class TestPhase3Sitemap:
    def test_sitemap_xml_structure(self):
        r = requests.get(f"{EXT}/api/portal/sitemap.xml", timeout=15)
        assert r.status_code == 200
        assert "application/xml" in r.headers.get("content-type", "")
        body = r.text
        # Required static routes
        for path in ("/", "/articles", "/legal/terms", "/legal/aup", "/legal/sla"):
            assert f"<loc>https://intercloud-digital.com{path}</loc>" in body, \
                f"missing sitemap entry for {path}"
        # Parse and verify at least one /articles/<slug> entry
        # (strip namespace via wildcard)
        ns = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
        root = ET.fromstring(body)
        locs = [u.text for u in root.findall(".//s:url/s:loc", ns)]
        assert any(l.startswith("https://intercloud-digital.com/articles/")
                   and l.count("/") >= 4 for l in locs), \
            "no /articles/<slug> entry in sitemap"


# ================================================================
# PHASE 3 — JSON-LD in static index.html
# ================================================================
class TestPhase3JsonLd:
    def test_organization_and_faq_present(self):
        with open("/app/frontend/public/index.html", "r") as f:
            html = f.read()
        assert '"@type": "Organization"' in html
        assert '"@type": "FAQPage"' in html

    def test_canonical_in_static_index_html(self):
        """Per spec: 'Landing page has canonical link (rel=canonical pointing to
        https://intercloud-digital.com/)'."""
        with open("/app/frontend/public/index.html", "r") as f:
            html = f.read()
        # Accept either static <link rel="canonical"> or a client-side helmet
        # (but spec says static is preferred).
        m = re.search(r'<link[^>]+rel=["\']canonical["\'][^>]*>', html, re.I)
        assert m, "no <link rel=canonical> in static index.html"
        assert "https://intercloud-digital.com" in m.group(0), \
            f"canonical href wrong: {m.group(0)}"


# ================================================================
# PHASE 4 — Reusable components importable
# ================================================================
class TestPhase4Components:
    def test_data_table_source_exports(self):
        p = "/app/frontend/src/components/ui/data-table.jsx"
        assert os.path.exists(p)
        src = open(p).read()
        assert re.search(r"export\s+(const|default)\s+DataTable", src) or \
               "export default DataTable" in src, "DataTable export missing"

    def test_skeleton_source_exports(self):
        p = "/app/frontend/src/components/ui/skeleton.jsx"
        assert os.path.exists(p)
        src = open(p).read()
        assert "Skeleton" in src and "export" in src, "Skeleton export missing"


# ================================================================
# CRITICAL — Successful login must not 500 (slowapi header injection bug)
# ================================================================
class TestCriticalLoginRegression:
    def test_admin_login_returns_200(self):
        """Regression: on successful (200) login the slowapi middleware
        must not raise 'parameter `response` must be an instance of
        starlette.responses.Response'."""
        # Wait past rate-limit window from any prior test if hit
        r = requests.post(f"{ORIGIN}/api/portal/auth/login",
                          json={"email": ADMIN_EMAIL, "password": ADMIN_PWD},
                          timeout=10)
        assert r.status_code != 500, (
            f"login endpoint 500: {r.text[:200]!r} — likely slowapi "
            f"headers_enabled=True + BaseHTTPMiddleware ordering bug"
        )
        assert r.status_code == 200, f"login failed: {r.status_code} {r.text[:200]}"
        data = r.json()
        assert "token" in data and "user" in data



DEVICE_ID = "6a617872f12db51fa9cc268c"


class TestRegression:
    def test_blackhole_prefix_filter_fast(self, s, admin_headers):
        t0 = time.perf_counter()
        r = s.get(
            f"{EXT}/api/portal/admin/mikrotik/blackhole",
            params={"device_id": DEVICE_ID, "prefix_filter": "192.0.2.0/24"},
            headers=admin_headers, timeout=15,
        )
        elapsed = time.perf_counter() - t0
        assert r.status_code == 200, r.text[:200]
        assert elapsed < 5.0, f"blackhole list took {elapsed:.1f}s"

    def test_lg_ping_with_src_address(self, s, admin_headers):
        r = s.post(
            f"{EXT}/api/portal/admin/mikrotik/looking-glass",
            json={
                "device_id": DEVICE_ID,
                "tool": "ping",
                "target": "8.8.8.8",
                "src_address": "157.20.32.253",
                "count": 2,
            },
            headers=admin_headers, timeout=20,
        )
        assert r.status_code == 200, r.text[:200]
        data = r.json()
        assert data.get("ok") is True, data
        assert data.get("src_address") == "157.20.32.253"
        assert isinstance(data.get("rows"), list) and len(data["rows"]) > 0

    def test_diagnostics_traceroute_returns_hops(self, s, admin_headers):
        r = s.post(
            f"{EXT}/api/portal/admin/diagnostics/run",
            json={"tool": "traceroute", "target": "1.1.1.1"},
            headers=admin_headers, timeout=45,
        )
        assert r.status_code == 200, r.text[:200]
        data = r.json()
        # tolerate 'output' or 'rows'
        assert (data.get("output") or data.get("rows")), \
            f"traceroute returned no hops: {data}"
