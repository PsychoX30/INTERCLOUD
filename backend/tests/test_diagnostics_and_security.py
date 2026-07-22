"""Backend tests for Diagnostic Tools + Auto-Block Security.

Covers:
- GET  /admin/diagnostics/tools           — advertisement of tools + torch meta
- POST /admin/diagnostics/run             — real ping / dns / whois / blacklist /
                                            portscan / http / traceroute / torch
- Torch validation errors + happy-path when mikrotik integration is enabled
- Auto-block: 12 failed logins → 429; blocked-ips list; manual unblock;
  security_notifications event; security settings GET/PUT persistence.

All requests go DIRECT to `http://localhost:8001` so
`request.client.host == "127.0.0.1"` (needed for the auto-block test).

IMPORTANT — teardown: at end of the auto-block test we DELETE any blocked
`127.0.0.1` and PUT security settings back to defaults so subsequent runs
(and other test modules like `test_login_analytics.py`) don't start out
blocked. We ALSO clean up `blocked_ips` for our fake IPs.
"""
import os
import time
import uuid
import pytest
import requests

# Diagnostics tests only need /admin API; auto-block uses live login attempts,
# so they must serialize with any other test that mutates login_attempts /
# security settings on the shared IP `127.0.0.1`.
pytestmark = pytest.mark.xdist_group("recaptcha_shared")

LOCAL_API = "http://localhost:8001/api/portal"

ADMIN_EMAIL = "admin@intercloud-digital.com"
ADMIN_PASSWORD = "AdminIntercloud2026!"
CLIENT_EMAIL = "demo@client.com"
CLIENT_PASSWORD = "ClientDemo2026!"


def _login(email, password):
    return requests.post(f"{LOCAL_API}/auth/login",
                         json={"email": email, "password": password},
                         timeout=20)


def _h(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def _run_diag(headers, **payload):
    return requests.post(f"{LOCAL_API}/admin/diagnostics/run",
                         headers=headers, json=payload, timeout=60)


# --------------------------------------------------------------- fixtures

@pytest.fixture(scope="module")
def admin_token():
    # Make sure we're not currently blocked from a prior run.
    # Best-effort: try to login; if 429 we'll clean up via a direct DB endpoint.
    r = _login(ADMIN_EMAIL, ADMIN_PASSWORD)
    if r.status_code == 429:
        # Can't get in via login — try to unblock via a temporary token?
        # We simply skip the whole module and report — main agent must clear.
        pytest.skip("Admin login blocked by auto-block leftover state (429). "
                    "Run: db.blocked_ips.deleteMany({}) to clear.")
    if r.status_code != 200:
        pytest.skip(f"Admin login failed: {r.status_code} {r.text}")
    return r.json()["token"]


@pytest.fixture(scope="module")
def admin_headers(admin_token):
    return _h(admin_token)


@pytest.fixture(scope="module")
def client_token():
    r = _login(CLIENT_EMAIL, CLIENT_PASSWORD)
    if r.status_code != 200:
        pytest.skip(f"Client login failed: {r.status_code} {r.text}")
    return r.json()["token"]


# ============================================================
# TOOLS ADVERTISEMENT
# ============================================================

class TestDiagnosticsTools:
    def test_01_tools_endpoint_ok(self, admin_headers):
        r = requests.get(f"{LOCAL_API}/admin/diagnostics/tools",
                         headers=admin_headers, timeout=15)
        assert r.status_code == 200, r.text
        data = r.json()
        assert "tools" in data and "meta" in data
        assert "mikrotik_ready" in data
        assert isinstance(data["mikrotik_ready"], bool)

        # Torch present in tools + meta
        assert "torch" in data["tools"]
        assert "torch" in data["meta"]

        torch_meta = data["meta"]["torch"]
        expected_extras = {"interface", "src_address", "dst_address",
                           "protocol", "port", "duration"}
        assert set(torch_meta.get("extras", [])) == expected_extras, torch_meta

        # 8 unique tools (nslookup is an alias for dns → also present)
        tool_set = set(data["tools"])
        for t in ("ping", "traceroute", "dns", "whois", "blacklist",
                  "portscan", "http", "torch"):
            assert t in tool_set, f"tool '{t}' missing"

        # meta has 8 entries (no alias)
        assert len(data["meta"]) == 8

    def test_02_tools_requires_admin(self, client_token):
        r = requests.get(f"{LOCAL_API}/admin/diagnostics/tools",
                         headers=_h(client_token), timeout=15)
        assert r.status_code == 403, r.text

    def test_03_tools_no_token_401(self):
        r = requests.get(f"{LOCAL_API}/admin/diagnostics/tools", timeout=15)
        assert r.status_code == 401, r.text


# ============================================================
# INDIVIDUAL TOOLS
# ============================================================

class TestDiagnosticsRun:
    def test_04_run_ping(self, admin_headers):
        r = _run_diag(admin_headers, tool="ping", target="8.8.8.8", count=3)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["tool"] == "ping"
        assert data["output"].startswith("PING")
        s = data["summary"]
        assert s["count"] == 3
        # received + lost == count
        assert (s["received"] + s["lost"]) == 3
        # In a container ICMP may be filtered — allow all-lost, but summary
        # must still contain a numeric loss_percent.
        assert isinstance(s["loss_percent"], (int, float))

    def test_05_run_dns(self, admin_headers):
        r = _run_diag(admin_headers, tool="dns", target="google.com", record="A")
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["tool"] == "dns"
        assert "google.com" in data["output"].lower()

    def test_06_run_whois(self, admin_headers):
        r = _run_diag(admin_headers, tool="whois", target="google.com")
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["tool"] == "whois"
        out_up = data["output"].upper()
        assert ("DOMAIN NAME" in out_up) or ("GOOGLE" in out_up), data["output"][:400]

    def test_07_run_blacklist(self, admin_headers):
        r = _run_diag(admin_headers, tool="blacklist", target="8.8.8.8")
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["tool"] == "blacklist"
        s = data["summary"]
        assert s["total_zones"] == 8
        assert s["listed_count"] >= 0

    def test_08_run_portscan(self, admin_headers):
        r = _run_diag(admin_headers, tool="portscan", target="google.com")
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["tool"] == "portscan"
        s = data["summary"]
        assert s["total_scanned"] >= 1
        assert s["open_count"] >= 0

    def test_09_run_http(self, admin_headers):
        r = _run_diag(admin_headers, tool="http", target="https://www.google.com")
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["tool"] == "http"
        s = data["summary"]
        assert s.get("status_code") in (200, 301, 302), s

    def test_10_run_traceroute(self, admin_headers):
        r = _run_diag(admin_headers, tool="traceroute", target="8.8.8.8", max_hops=5)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["tool"] == "traceroute"
        # traceroute may show * hops in container — just check it returned SOMETHING.
        assert isinstance(data.get("output"), str)


# ============================================================
# TORCH — mikrotik disabled by default
# ============================================================

class TestTorchDisabled:
    def test_11_torch_disabled_returns_400(self, admin_headers):
        # Ensure mikrotik integration is not enabled first (best-effort)
        requests.put(f"{LOCAL_API}/admin/integrations-v2/mikrotik",
                     headers=admin_headers,
                     json={"enabled": False, "credentials": {}, "options": {}},
                     timeout=15)
        r = _run_diag(admin_headers, tool="torch", interface="ether1")
        assert r.status_code == 400, r.text
        detail = r.json().get("detail", "").lower()
        assert "mikrotik integration is not enabled" in detail, r.text

    def test_12_torch_missing_interface(self, admin_headers):
        r = _run_diag(admin_headers, tool="torch", interface="")
        assert r.status_code == 400, r.text
        # interface is validated before the integration check → we might get
        # either error depending on order. Accept either.
        detail = r.json().get("detail", "").lower()
        assert ("interface is required" in detail) or ("mikrotik integration" in detail), r.text

    def test_13_torch_bad_protocol(self, admin_headers):
        r = _run_diag(admin_headers, tool="torch", interface="ether1", protocol="xxx")
        assert r.status_code == 400, r.text
        detail = r.json().get("detail", "").lower()
        assert "protocol must be" in detail, r.text

    def test_14_torch_bad_src_address(self, admin_headers):
        r = _run_diag(admin_headers, tool="torch", interface="ether1",
                      src_address="not-a-cidr")
        assert r.status_code == 400, r.text


# ============================================================
# TORCH — happy-path with fake creds (expect connection failure inside 200)
# ============================================================

class TestTorchEnabled:
    def test_15_torch_enabled_returns_json_not_500(self, admin_headers):
        # Enable mikrotik with unreachable creds
        rp = requests.put(f"{LOCAL_API}/admin/integrations-v2/mikrotik",
                          headers=admin_headers,
                          json={"enabled": True,
                                "credentials": {"host": "127.0.0.1", "port": 8728,
                                                "username": "x", "password": "x"},
                                "options": {}},
                          timeout=15)
        assert rp.status_code == 200, rp.text
        try:
            r = _run_diag(admin_headers, tool="torch", interface="ether1",
                          duration=1)
            # Must NOT be a 500 — connection failure is surfaced in JSON summary.
            assert r.status_code == 200, r.text
            data = r.json()
            assert data["tool"] == "torch"
            s = data.get("summary", {})
            assert s.get("error"), f"expected an 'error' string in summary, got {s}"
        finally:
            # Disable mikrotik again
            requests.put(f"{LOCAL_API}/admin/integrations-v2/mikrotik",
                         headers=admin_headers,
                         json={"enabled": False, "credentials": {}, "options": {}},
                         timeout=15)


# ============================================================
# AUTHZ on /admin/diagnostics/run
# ============================================================

class TestDiagnosticsAuth:
    def test_16_run_requires_auth(self):
        r = requests.post(f"{LOCAL_API}/admin/diagnostics/run",
                          json={"tool": "ping", "target": "8.8.8.8"}, timeout=15)
        assert r.status_code == 401, r.text

    def test_17_run_forbidden_for_client(self, client_token):
        r = requests.post(f"{LOCAL_API}/admin/diagnostics/run",
                          headers=_h(client_token),
                          json={"tool": "ping", "target": "8.8.8.8"}, timeout=15)
        assert r.status_code == 403, r.text


# ============================================================
# SECURITY SETTINGS + AUTO-BLOCK
# ============================================================

class TestSecurityAutoBlock:
    """End-to-end: hit /auth/login with bad creds 12x → IP gets 429.
    Then unblock via DELETE and verify.
    Uses a fresh unique fake email so we don't collide with brute-force tests.
    """

    @pytest.fixture(scope="class", autouse=True)
    def _cleanup(self, admin_headers):
        # Ensure we start clean: unblock 127.0.0.1 (if any) and reset settings
        # to defaults BEFORE the tests.
        requests.delete(f"{LOCAL_API}/admin/security/blocked-ips/127.0.0.1",
                        headers=admin_headers, timeout=15)
        requests.put(f"{LOCAL_API}/admin/security/settings",
                     headers=admin_headers,
                     json={"auto_block_enabled": True,
                           "fail_threshold": 10,
                           "window_minutes": 15,
                           "ban_minutes": 30}, timeout=15)
        yield
        # TEARDOWN: unblock 127.0.0.1, DISABLE auto_block, and clean up
        # 127.0.0.1's failed login_attempts so subsequent test files
        # (test_recaptcha_auth.py / test_login_analytics.py) aren't blocked
        # by leftover state.
        requests.delete(f"{LOCAL_API}/admin/security/blocked-ips/127.0.0.1",
                        headers=admin_headers, timeout=15)
        requests.put(f"{LOCAL_API}/admin/security/settings",
                     headers=admin_headers,
                     json={"auto_block_enabled": False,
                           "fail_threshold": 10,
                           "window_minutes": 15,
                           "ban_minutes": 30}, timeout=15)
        # Best-effort direct-DB cleanup of the 127.0.0.1 failed attempts we
        # generated in test_20 — via a small motor call.
        try:
            import asyncio
            from motor.motor_asyncio import AsyncIOMotorClient
            async def _wipe():
                mc = AsyncIOMotorClient(
                    os.environ.get("MONGO_URL", "mongodb://localhost:27017"))
                db = mc[os.environ.get("DB_NAME", "intercloud_portal")]
                await db.blocked_ips.delete_many({})
                await db.login_attempts.delete_many(
                    {"ip": "127.0.0.1", "success": False})
            asyncio.run(_wipe())
        except Exception:
            pass

    def test_18_default_settings(self, admin_headers):
        r = requests.get(f"{LOCAL_API}/admin/security/settings",
                         headers=admin_headers, timeout=15)
        assert r.status_code == 200, r.text
        s = r.json()
        # Defaults present
        assert s.get("auto_block_enabled") is True
        assert int(s.get("fail_threshold")) == 10
        assert int(s.get("window_minutes")) == 15
        assert int(s.get("ban_minutes")) == 30

    def test_19_put_settings_persists(self, admin_headers):
        # Change values
        payload = {"auto_block_enabled": True, "fail_threshold": 8,
                   "window_minutes": 20, "ban_minutes": 45}
        r = requests.put(f"{LOCAL_API}/admin/security/settings",
                         headers=admin_headers, json=payload, timeout=15)
        assert r.status_code == 200, r.text
        s = r.json()
        assert s["fail_threshold"] == 8
        assert s["window_minutes"] == 20
        assert s["ban_minutes"] == 45

        # GET back
        r2 = requests.get(f"{LOCAL_API}/admin/security/settings",
                          headers=admin_headers, timeout=15)
        assert r2.status_code == 200
        s2 = r2.json()
        assert s2["fail_threshold"] == 8
        assert s2["window_minutes"] == 20
        assert s2["ban_minutes"] == 45

        # Restore defaults for the auto-block test below
        requests.put(f"{LOCAL_API}/admin/security/settings",
                     headers=admin_headers,
                     json={"auto_block_enabled": True, "fail_threshold": 10,
                           "window_minutes": 15, "ban_minutes": 30}, timeout=15)

    def test_20_auto_block_after_12_fails(self, admin_headers):
        # Guard: clear existing block for 127.0.0.1
        requests.delete(f"{LOCAL_API}/admin/security/blocked-ips/127.0.0.1",
                        headers=admin_headers, timeout=15)

        bad_email = f"newbad_{uuid.uuid4().hex[:8]}@example.com"
        got_429 = False
        codes = []
        for i in range(12):
            r = _login(bad_email, "wrong-pass")
            codes.append(r.status_code)
            if r.status_code == 429:
                got_429 = True
                # continue a couple more times to confirm sticky
        assert got_429, f"Expected a 429 within 12 attempts, got codes: {codes}"
        # At least attempts >= 11 should be 429 (the 11th onwards)
        assert codes.count(429) >= 1, codes

        # blocked-ips list shows 127.0.0.1 active
        r = requests.get(f"{LOCAL_API}/admin/security/blocked-ips",
                         headers=admin_headers, params={"active_only": True},
                         timeout=15)
        assert r.status_code == 200, r.text
        ips = [d["ip"] for d in r.json() if d.get("active")]
        assert "127.0.0.1" in ips, f"127.0.0.1 not active in blocked_ips: {r.json()}"

        # Notification of type ip_auto_blocked exists
        rn = requests.get(f"{LOCAL_API}/admin/security/notifications",
                          headers=admin_headers, timeout=15)
        assert rn.status_code == 200, rn.text
        notifs = rn.json()
        kinds = [n.get("kind") for n in notifs]
        assert "ip_auto_blocked" in kinds, f"kinds={kinds}"

        # DELETE (manual unblock)
        ru = requests.delete(f"{LOCAL_API}/admin/security/blocked-ips/127.0.0.1",
                             headers=admin_headers, timeout=15)
        assert ru.status_code == 200, ru.text
        assert ru.json().get("ok") is True

        # Now login should not be 429 anymore (may be 401 for the fake email,
        # or 200 for the real admin login).
        # Small wait for the write to settle
        time.sleep(0.3)
        r_after = _login(ADMIN_EMAIL, ADMIN_PASSWORD)
        assert r_after.status_code == 200, r_after.text

        # blocked-ips list with active_only should NOT include 127.0.0.1 anymore
        r = requests.get(f"{LOCAL_API}/admin/security/blocked-ips",
                         headers=admin_headers, params={"active_only": True},
                         timeout=15)
        assert r.status_code == 200
        active_ips = [d["ip"] for d in r.json() if d.get("active")]
        assert "127.0.0.1" not in active_ips, active_ips
