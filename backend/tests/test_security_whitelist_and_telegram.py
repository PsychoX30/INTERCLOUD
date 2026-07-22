"""Backend tests for the Security Dashboard v2 features:

  1) GET  /admin/security/settings — new defaults present
  2) PUT  /admin/security/settings — new fields persist
  3) GET  /admin/integrations-v2/schema — telegram provider
  4) _ip_in_whitelist unit tests (CIDR / exact / hostname / edge cases)
  5) Whitelist prevents auto-block (CRITICAL)
  6) Whitelist short-circuits _is_ip_blocked
  7) auto_block_enabled=false disables auto-block
  8) POST /admin/security/notifications/test — SMTP + Telegram disabled
  9) POST /admin/security/notifications/test — Telegram enabled w/ fake keys
 10) PUT  /admin/integrations-v2/telegram — persists + masks bot_token on GET
 11) DELETE /admin/security/blocked-ips/{ip} → {ok:true, ip}

IMPORTANT SCHEDULING NOTE — the whole /app/backend/pytest.ini uses
`--dist loadscope` (NOT `loadgroup`), which pins tests to a worker by
**class**. Because every mutation-heavy test touches the shared
`settings.security` MongoDB document, we cannot let the classes run
concurrently on separate workers — they'd race. We therefore put every
security-settings-mutating test into a *single* class (TestSecurityV2)
so all of them land on the same worker in serial order.

Teardown at end of module: whitelist=[], auto_block=False (matches the
invariant that the diagnostics teardown leaves behind), telegram
integration deleted, blocked_ips wiped, 127.0.0.1 failed login_attempts
wiped so subsequent suites are unaffected.
"""
import os
import sys
import uuid
import pytest
import requests

pytestmark = pytest.mark.xdist_group("recaptcha_shared")

LOCAL_API = "http://localhost:8001/api/portal"
ADMIN_EMAIL = "admin@intercloud-digital.com"
ADMIN_PASSWORD = "AdminIntercloud2026!"


def _login(email, password):
    return requests.post(f"{LOCAL_API}/auth/login",
                         json={"email": email, "password": password},
                         timeout=20)


def _h(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def _direct_db_wipe(clear_blocks: bool = True, clear_attempts: bool = True):
    """Best-effort direct DB cleanup for 127.0.0.1 state."""
    import asyncio
    from motor.motor_asyncio import AsyncIOMotorClient

    async def _wipe():
        mc = AsyncIOMotorClient(
            os.environ.get("MONGO_URL", "mongodb://localhost:27017"))
        db = mc[os.environ.get("DB_NAME", "intercloud_portal")]
        if clear_blocks:
            await db.blocked_ips.delete_many({})
        if clear_attempts:
            await db.login_attempts.delete_many(
                {"ip": "127.0.0.1", "success": False})

    asyncio.run(_wipe())


def _drop_security_settings():
    import asyncio
    from motor.motor_asyncio import AsyncIOMotorClient

    async def _drop():
        mc = AsyncIOMotorClient(
            os.environ.get("MONGO_URL", "mongodb://localhost:27017"))
        db = mc[os.environ.get("DB_NAME", "intercloud_portal")]
        await db.settings.delete_one({"_id": "security"})

    asyncio.run(_drop())


# --------------------------------------------------------------- fixtures

@pytest.fixture(scope="module")
def admin_token():
    r = _login(ADMIN_EMAIL, ADMIN_PASSWORD)
    if r.status_code == 429:
        try:
            _direct_db_wipe(clear_blocks=True, clear_attempts=True)
        except Exception:
            pass
        r = _login(ADMIN_EMAIL, ADMIN_PASSWORD)
    if r.status_code != 200:
        pytest.skip(f"Admin login failed: {r.status_code} {r.text}")
    return r.json()["token"]


@pytest.fixture(scope="module")
def admin_headers(admin_token):
    return _h(admin_token)


def _reset_security_defaults(admin_headers):
    """Restore invariants expected by neighbouring suites: whitelist empty,
    notify flags on, auto_block ON (that matches DEFAULT_SECURITY_SETTINGS)."""
    requests.put(f"{LOCAL_API}/admin/security/settings",
                 headers=admin_headers,
                 json={"auto_block_enabled": True,
                       "fail_threshold": 10,
                       "window_minutes": 15,
                       "ban_minutes": 30,
                       "notify_emails": [],
                       "whitelist_ips": [],
                       "email_notify_enabled": True,
                       "telegram_notify_enabled": True},
                 timeout=15)


# ============================================================
# UNIT TESTS — no HTTP, no DB. Safe to run on any worker.
# ============================================================
class TestIpInWhitelistUnit:

    @classmethod
    def setup_class(cls):
        sys.path.insert(0, "/app/backend")
        from portal.routes import _ip_in_whitelist  # noqa: E402
        cls._fn = staticmethod(_ip_in_whitelist)

    def test_u1_cidr_match(self):
        assert self._fn("10.5.6.7", ["10.0.0.0/8"]) is True

    def test_u2_cidr_no_match(self):
        assert self._fn("192.168.1.1", ["10.0.0.0/8"]) is False

    def test_u3_exact_ip_match(self):
        assert self._fn("127.0.0.1", ["127.0.0.1"]) is True

    def test_u4_empty_whitelist(self):
        assert self._fn("1.2.3.4", []) is False

    def test_u5_empty_ip(self):
        assert self._fn("", ["10.0.0.0/8"]) is False

    def test_u6_multiple_entries(self):
        assert self._fn("10.5.6.7", ["8.8.8.8", "10.0.0.0/8", "1.1.1.1"]) is True

    def test_u7_hostname_exact_fallback(self):
        assert self._fn("example.com", ["example.com"]) is True
        assert self._fn("example.com", ["other.com"]) is False

    def test_u8_ipv6_in_v6_cidr(self):
        # Extra: verify Python's ipaddress works for IPv6 too.
        assert self._fn("2001:db8::1", ["2001:db8::/32"]) is True


# ============================================================
# All state-mutating tests live in ONE class so loadscope pins
# them to a single worker (avoids races on settings.security).
# Test names are numeric-prefixed to enforce sequential order.
# ============================================================
class TestSecurityV2:

    # ---- setup / teardown ----
    @pytest.fixture(scope="class", autouse=True)
    def _class_lifecycle(self, admin_headers):
        # Fresh start
        _direct_db_wipe(clear_blocks=True, clear_attempts=True)
        try:
            requests.delete(f"{LOCAL_API}/admin/integrations-v2/telegram",
                            headers=admin_headers, timeout=10)
        except Exception:
            pass
        yield
        # Teardown: restore invariants for neighbouring test files
        try:
            requests.delete(f"{LOCAL_API}/admin/integrations-v2/telegram",
                            headers=admin_headers, timeout=10)
        except Exception:
            pass
        try:
            _direct_db_wipe(clear_blocks=True, clear_attempts=True)
        except Exception:
            pass
        # Match the invariant left by test_diagnostics_and_security.py teardown:
        # auto_block=False so subsequent recaptcha/login-analytics suites won't
        # accidentally block 127.0.0.1.
        try:
            requests.put(f"{LOCAL_API}/admin/security/settings",
                         headers=admin_headers,
                         json={"auto_block_enabled": False,
                               "fail_threshold": 10,
                               "window_minutes": 15,
                               "ban_minutes": 30,
                               "notify_emails": [],
                               "whitelist_ips": [],
                               "email_notify_enabled": True,
                               "telegram_notify_enabled": True},
                         timeout=10)
        except Exception:
            pass

    # ---- 1) GET default settings has new fields ----
    def test_01_defaults_include_new_fields(self, admin_headers):
        # Drop settings doc so we see pure DEFAULT_SECURITY_SETTINGS.
        _drop_security_settings()
        r = requests.get(f"{LOCAL_API}/admin/security/settings",
                         headers=admin_headers, timeout=15)
        assert r.status_code == 200, r.text
        s = r.json()
        # Legacy defaults still present
        assert s.get("auto_block_enabled") is True
        assert int(s.get("fail_threshold")) == 10
        assert int(s.get("window_minutes")) == 15
        assert int(s.get("ban_minutes")) == 30
        assert isinstance(s.get("notify_emails"), list)
        # New defaults
        assert s.get("whitelist_ips") == []
        assert s.get("email_notify_enabled") is True
        assert s.get("telegram_notify_enabled") is True

    # ---- 2) PUT persists new fields ----
    def test_02_put_persists_new_fields(self, admin_headers):
        payload = {
            "whitelist_ips": ["1.2.3.4", "10.0.0.0/8"],
            "notify_emails": ["ops@example.com", "sec@example.com"],
            "email_notify_enabled": False,
            "telegram_notify_enabled": False,
        }
        r = requests.put(f"{LOCAL_API}/admin/security/settings",
                         headers=admin_headers, json=payload, timeout=15)
        assert r.status_code == 200, r.text
        s = r.json()
        assert s["whitelist_ips"] == ["1.2.3.4", "10.0.0.0/8"]
        assert set(s["notify_emails"]) == {"ops@example.com", "sec@example.com"}
        assert s["email_notify_enabled"] is False
        assert s["telegram_notify_enabled"] is False

        # GET back verifies persistence
        r2 = requests.get(f"{LOCAL_API}/admin/security/settings",
                          headers=admin_headers, timeout=15)
        s2 = r2.json()
        assert s2["whitelist_ips"] == ["1.2.3.4", "10.0.0.0/8"]
        assert set(s2["notify_emails"]) == {"ops@example.com", "sec@example.com"}
        assert s2["email_notify_enabled"] is False
        assert s2["telegram_notify_enabled"] is False

    def test_03_put_empty_arrays_clear_lists(self, admin_headers):
        r = requests.put(f"{LOCAL_API}/admin/security/settings",
                         headers=admin_headers,
                         json={"whitelist_ips": [], "notify_emails": []},
                         timeout=15)
        assert r.status_code == 200
        s = r.json()
        assert s["whitelist_ips"] == []
        assert s["notify_emails"] == []

    # ---- 3) Schema includes telegram ----
    def test_04_schema_has_telegram(self, admin_headers):
        r = requests.get(f"{LOCAL_API}/admin/integrations-v2/schema",
                         headers=admin_headers, timeout=15)
        assert r.status_code == 200, r.text
        schema = r.json()
        assert "telegram" in schema, list(schema.keys())
        tg = schema["telegram"]
        assert tg.get("category") == "security"
        cred_keys = {c["key"] for c in tg.get("credentials", [])}
        assert cred_keys == {"bot_token", "chat_id"}, cred_keys
        opt_keys = {o["key"] for o in tg.get("options", [])}
        assert "silent" in opt_keys, opt_keys

    # ---- 4) Whitelist prevents auto-block ----
    def test_05_whitelist_prevents_auto_block(self, admin_headers):
        _direct_db_wipe(clear_blocks=True, clear_attempts=True)
        # Enable auto-block with a low threshold; whitelist 127.0.0.1
        r = requests.put(f"{LOCAL_API}/admin/security/settings",
                         headers=admin_headers,
                         json={"auto_block_enabled": True,
                               "fail_threshold": 3,
                               "window_minutes": 15,
                               "ban_minutes": 30,
                               "whitelist_ips": ["127.0.0.1"]},
                         timeout=15)
        assert r.status_code == 200, r.text

        # Snapshot existing ip_auto_blocked notifs for 127.0.0.1
        rn = requests.get(f"{LOCAL_API}/admin/security/notifications",
                          headers=admin_headers, timeout=15)
        baseline = {n.get("id") for n in rn.json()
                    if n.get("kind") == "ip_auto_blocked"
                    and n.get("ip") == "127.0.0.1"}

        bad_email = f"wl_{uuid.uuid4().hex[:8]}@example.com"
        codes = []
        for _ in range(6):
            r = _login(bad_email, "wrong-pass")
            codes.append(r.status_code)
        assert 429 not in codes, f"got 429 despite whitelist: {codes}"

        # No active 127.0.0.1 entry
        r = requests.get(f"{LOCAL_API}/admin/security/blocked-ips",
                         headers=admin_headers,
                         params={"active_only": True}, timeout=15)
        assert r.status_code == 200
        active_ips = [d["ip"] for d in r.json() if d.get("active")]
        assert "127.0.0.1" not in active_ips, r.json()

        # No new ip_auto_blocked notif for 127.0.0.1
        rn2 = requests.get(f"{LOCAL_API}/admin/security/notifications",
                           headers=admin_headers, timeout=15)
        new_127 = [n for n in rn2.json()
                   if n.get("kind") == "ip_auto_blocked"
                   and n.get("ip") == "127.0.0.1"
                   and n.get("id") not in baseline]
        assert new_127 == [], f"unexpected new notifs: {new_127}"

    # ---- 5) Whitelist skips _is_ip_blocked ----
    def test_06_whitelist_skips_is_ip_blocked(self, admin_headers):
        # Whitelist still 127.0.0.1 from previous test. Disable auto-block so
        # no new blocks appear from our own manual block operation below.
        r = requests.put(f"{LOCAL_API}/admin/security/settings",
                         headers=admin_headers,
                         json={"auto_block_enabled": False,
                               "whitelist_ips": ["127.0.0.1"]},
                         timeout=15)
        assert r.status_code == 200

        # Manually block 127.0.0.1
        rb = requests.post(f"{LOCAL_API}/admin/security/blocked-ips",
                           headers=admin_headers,
                           json={"ip": "127.0.0.1", "ban_minutes": 60,
                                 "reason": "test_manual_block"},
                           timeout=15)
        assert rb.status_code == 200, rb.text

        # Login must SUCCEED because whitelist short-circuits _is_ip_blocked
        r_login = _login(ADMIN_EMAIL, ADMIN_PASSWORD)
        assert r_login.status_code == 200, (
            f"admin login blocked though 127.0.0.1 is whitelisted; "
            f"code={r_login.status_code} body={r_login.text}")

        # Cleanup: unblock, drop whitelist
        requests.delete(f"{LOCAL_API}/admin/security/blocked-ips/127.0.0.1",
                        headers=admin_headers, timeout=15)
        requests.put(f"{LOCAL_API}/admin/security/settings",
                     headers=admin_headers,
                     json={"whitelist_ips": []},
                     timeout=15)

    # ---- 6) auto_block_enabled=false disables auto-block ----
    def test_07_auto_block_toggle_off(self, admin_headers):
        _direct_db_wipe(clear_blocks=True, clear_attempts=True)
        r = requests.put(f"{LOCAL_API}/admin/security/settings",
                         headers=admin_headers,
                         json={"auto_block_enabled": False,
                               "fail_threshold": 3,
                               "whitelist_ips": []},
                         timeout=15)
        assert r.status_code == 200

        rn0 = requests.get(f"{LOCAL_API}/admin/security/notifications",
                           headers=admin_headers, timeout=15)
        baseline = {n.get("id") for n in rn0.json()
                    if n.get("kind") == "ip_auto_blocked"
                    and n.get("ip") == "127.0.0.1"}

        bad_email = f"off_{uuid.uuid4().hex[:8]}@example.com"
        codes = []
        for _ in range(5):
            r = _login(bad_email, "wrong-pass")
            codes.append(r.status_code)
        assert 429 not in codes, f"got 429 despite auto_block off: {codes}"

        r = requests.get(f"{LOCAL_API}/admin/security/blocked-ips",
                         headers=admin_headers,
                         params={"active_only": True}, timeout=15)
        active_ips = [d["ip"] for d in r.json() if d.get("active")]
        assert "127.0.0.1" not in active_ips

        rn1 = requests.get(f"{LOCAL_API}/admin/security/notifications",
                           headers=admin_headers, timeout=15)
        new_ids = {n.get("id") for n in rn1.json()
                   if n.get("kind") == "ip_auto_blocked"
                   and n.get("ip") == "127.0.0.1"} - baseline
        assert new_ids == set(), f"unexpected new notif ids: {new_ids}"

    # ---- 7) notifications/test with SMTP + Telegram disabled ----
    def test_08_notifications_test_both_disabled(self, admin_headers):
        # Make sure Telegram is deleted + no recipients
        requests.delete(f"{LOCAL_API}/admin/integrations-v2/telegram",
                        headers=admin_headers, timeout=10)
        requests.put(f"{LOCAL_API}/admin/security/settings",
                     headers=admin_headers,
                     json={"notify_emails": []}, timeout=15)

        r = requests.post(f"{LOCAL_API}/admin/security/notifications/test",
                          headers=admin_headers, json={}, timeout=15)
        assert r.status_code == 200, r.text
        j = r.json()
        assert "email" in j and "telegram" in j
        assert j["email"]["attempted"] is False, j["email"]
        assert j["telegram"]["attempted"] is False, j["telegram"]
        assert j["email"].get("reason"), "email reason missing"
        assert j["telegram"].get("reason"), "telegram reason missing"

    # ---- 8) notifications/test with Telegram enabled + fake keys ----
    def test_09_notifications_test_telegram_fake_keys(self, admin_headers):
        rp = requests.put(f"{LOCAL_API}/admin/integrations-v2/telegram",
                          headers=admin_headers,
                          json={"enabled": True,
                                "credentials": {"bot_token": "fake:key",
                                                "chat_id": "12345"},
                                "options": {"silent": True}},
                          timeout=15)
        assert rp.status_code == 200, rp.text

        r = requests.post(f"{LOCAL_API}/admin/security/notifications/test",
                          headers=admin_headers, json={}, timeout=20)
        # Must NOT be 500 — Telegram rejects fake token but endpoint stays 200.
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["telegram"]["attempted"] is True, j["telegram"]
        assert j["telegram"].get("ok") is False, j["telegram"]
        has_signal = (bool(j["telegram"].get("errors")) or
                      bool((j["telegram"].get("details") or {}).get("message")) or
                      bool(j["telegram"].get("details")))
        assert has_signal, f"expected error signal: {j['telegram']}"

        # Disable telegram (leave persisted config for test_10 to introspect
        # masking is handled by a fresh PUT there).
        requests.delete(f"{LOCAL_API}/admin/integrations-v2/telegram",
                        headers=admin_headers, timeout=15)

    # ---- 9) PUT telegram persists + GET masks bot_token ----
    def test_10_telegram_put_and_masking(self, admin_headers):
        rp = requests.put(f"{LOCAL_API}/admin/integrations-v2/telegram",
                          headers=admin_headers,
                          json={"enabled": True,
                                "credentials": {"bot_token": "12345:ABCDEFGHIJKLMNOP",
                                                "chat_id": "-100999888"},
                                "options": {"silent": True}},
                          timeout=15)
        assert rp.status_code == 200, rp.text
        saved = rp.json()
        creds_saved = saved.get("credentials") or {}
        assert not creds_saved.get("bot_token"), \
            f"bot_token leaked in PUT response: {creds_saved}"
        assert "bot_token_masked" in creds_saved, creds_saved
        assert creds_saved.get("chat_id") == "-100999888"
        assert saved.get("enabled") is True
        assert (saved.get("options") or {}).get("silent") is True

        # GET list also returns masked
        rl = requests.get(f"{LOCAL_API}/admin/integrations-v2",
                          headers=admin_headers, timeout=15)
        assert rl.status_code == 200, rl.text
        all_ints = rl.json()
        assert "telegram" in all_ints
        tg = all_ints["telegram"]
        creds = tg.get("credentials") or {}
        assert not creds.get("bot_token"), f"bot_token leaked on GET: {creds}"
        assert "bot_token_masked" in creds, creds
        assert creds.get("chat_id") == "-100999888"

    # ---- 10) DELETE blocked-ips returns {ok:true, ip} ----
    def test_11_delete_blocked_ips_returns_ok_ip(self, admin_headers):
        fake_ip = "203.0.113.42"
        requests.post(f"{LOCAL_API}/admin/security/blocked-ips",
                      headers=admin_headers,
                      json={"ip": fake_ip, "ban_minutes": 5},
                      timeout=15)
        ru = requests.delete(f"{LOCAL_API}/admin/security/blocked-ips/{fake_ip}",
                             headers=admin_headers, timeout=15)
        assert ru.status_code == 200, ru.text
        body = ru.json()
        assert body.get("ok") is True
        assert body.get("ip") == fake_ip
