"""Backend tests for Google reCAPTCHA v3 integration on portal auth endpoints.

All tests are grouped inside a single class so pytest-xdist's default loadscope
scheduler pins them to a single worker — they mutate shared server-side state
(the integration_settings doc for provider='recaptcha') and must run sequentially.
"""
import os
import uuid
import pytest
import requests


API = os.environ.get("PORTAL_API_BASE") or "http://localhost:8001/api/portal"
API = API.rstrip("/")

ADMIN_EMAIL = "admin@intercloud-digital.com"
ADMIN_PASSWORD = "AdminIntercloud2026!"

FAKE_SITE_KEY = "6LcFakeSiteKeyForTests1234567890ABCDEF"
FAKE_SECRET_KEY = "6LcSecretKeyForTests1234567890ABCDEFGH"


def _login_admin():
    r = requests.post(f"{API}/auth/login", json={
        "email": ADMIN_EMAIL, "password": ADMIN_PASSWORD,
    }, timeout=15)
    if r.status_code != 200:
        pytest.skip(f"Admin login failed: {r.status_code} {r.text}")
    return r.json()["token"]


def _admin_headers(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _disable_recaptcha(headers):
    return requests.put(
        f"{API}/admin/integrations-v2/recaptcha",
        headers=headers,
        json={"enabled": False, "credentials": {}, "options": {}},
        timeout=15,
    )


def _enable_recaptcha(headers, site_key=FAKE_SITE_KEY, secret_key=FAKE_SECRET_KEY):
    return requests.put(
        f"{API}/admin/integrations-v2/recaptcha",
        headers=headers,
        json={
            "enabled": True,
            "credentials": {"site_key": site_key, "secret_key": secret_key},
            "options": {"min_score": 0.5, "verify_action": True},
        },
        timeout=15,
    )


def _wipe_recaptcha(headers):
    return requests.delete(f"{API}/admin/integrations-v2/recaptcha", headers=headers, timeout=15)


class TestRecaptchaAuth:
    """Grouped as a single class → single xdist worker under loadscope."""

    @pytest.fixture(scope="class", autouse=True)
    def admin_token(self):
        return _login_admin()

    @pytest.fixture(scope="class")
    def headers(self, admin_token):
        return _admin_headers(admin_token)

    @pytest.fixture(autouse=True, scope="class")
    def wipe_and_restore(self, headers):
        # Wipe at the start so we begin from a clean, disabled state.
        _wipe_recaptcha(headers)
        yield
        # Final teardown — leave disabled so subsequent iterations aren't blocked.
        _disable_recaptcha(headers)

    # ---------- 1. GET /auth/config public / disabled default ----------
    def test_01_auth_config_disabled_by_default(self, headers):
        _disable_recaptcha(headers)   # ensure disabled
        r = requests.get(f"{API}/auth/config", timeout=10)
        assert r.status_code == 200, r.text
        data = r.json()
        assert "recaptcha" in data
        rc = data["recaptcha"]
        assert rc.get("enabled") is False
        assert rc.get("site_key") is None
        # Secret must NEVER appear in this response
        assert "secret_key" not in rc
        assert "secret" not in str(data).lower()

    # ---------- 2. Schema contains recaptcha with expected shape ----------
    def test_02_schema_has_recaptcha(self, headers):
        r = requests.get(f"{API}/admin/integrations-v2/schema", headers=headers, timeout=10)
        assert r.status_code == 200, r.text
        schema = r.json()
        assert "recaptcha" in schema
        rc = schema["recaptcha"]
        assert rc.get("category") == "security"
        cred_keys = {c["key"] for c in rc.get("credentials", [])}
        assert cred_keys == {"site_key", "secret_key"}, cred_keys
        opt_keys = {o["key"] for o in rc.get("options", [])}
        assert {"min_score", "expected_hostname", "verify_action"} <= opt_keys, opt_keys

    # ---------- 3. PUT persists + secrets masked on GET ----------
    def test_03_put_persists_and_masks_secrets(self, headers):
        put = _enable_recaptcha(headers)
        assert put.status_code == 200, put.text
        saved = put.json()
        creds = saved.get("credentials") or {}
        assert saved.get("enabled") is True
        assert creds.get("site_key") == ""
        assert creds.get("site_key_masked", "").startswith("6LcF")
        assert creds.get("secret_key") == ""
        assert creds.get("secret_key_masked", "").startswith("6LcS")
        assert FAKE_SECRET_KEY not in put.text
        assert FAKE_SITE_KEY not in put.text

        lst = requests.get(f"{API}/admin/integrations-v2", headers=headers, timeout=10)
        assert lst.status_code == 200, lst.text
        rc = lst.json().get("recaptcha") or {}
        rc_creds = rc.get("credentials") or {}
        assert rc.get("enabled") is True
        assert rc_creds.get("site_key") == ""
        assert rc_creds.get("site_key_masked", "").startswith("6LcF")
        assert rc_creds.get("secret_key") == ""
        assert rc_creds.get("secret_key_masked", "").startswith("6LcS")
        assert FAKE_SECRET_KEY not in lst.text
        assert FAKE_SITE_KEY not in lst.text
        # Cleanup for next tests
        _disable_recaptcha(headers)

    # ---------- 4. Fail-open when disabled ----------
    def test_04_login_without_token_works_when_disabled(self, headers):
        _disable_recaptcha(headers)
        r = requests.post(f"{API}/auth/login", json={
            "email": ADMIN_EMAIL, "password": ADMIN_PASSWORD,
        }, timeout=15)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data.get("token")
        assert data["user"]["email"] == ADMIN_EMAIL

    def test_05_register_without_token_works_when_disabled(self, headers):
        _disable_recaptcha(headers)
        uniq = uuid.uuid4().hex[:10]
        email = f"TEST_recap_reg_{uniq}@example.com"
        r = requests.post(f"{API}/auth/register", json={
            "email": email,
            "password": "TestPass2026!",
            "name": "TEST Recaptcha Reg",
            "phone": "+62-000",
            "company": "TESTCO",
        }, timeout=20)
        assert r.status_code == 200, r.text
        assert r.json().get("token")
        # Cleanup — delete the created user
        try:
            uid = r.json()["user"]["id"]
            requests.delete(f"{API}/admin/users/{uid}", headers=headers, timeout=10)
        except Exception:
            pass

    def test_06_forgot_password_without_token_works_when_disabled(self, headers):
        _disable_recaptcha(headers)
        r = requests.post(f"{API}/auth/forgot-password", json={
            "email": ADMIN_EMAIL,
        }, timeout=15)
        assert r.status_code in (200, 202), r.text
        assert "recaptcha" not in r.text.lower()

    # ---------- 5. Enforcement when enabled ----------
    def test_07_auth_config_exposes_site_key_when_enabled(self, headers):
        r_en = _enable_recaptcha(headers)
        assert r_en.status_code == 200
        r = requests.get(f"{API}/auth/config", timeout=10)
        assert r.status_code == 200, r.text
        rc = r.json().get("recaptcha") or {}
        assert rc.get("enabled") is True
        assert rc.get("site_key") == FAKE_SITE_KEY
        assert "secret_key" not in rc
        assert FAKE_SECRET_KEY not in r.text

    def test_08_login_missing_token_blocked(self, headers):
        _enable_recaptcha(headers)
        r = requests.post(f"{API}/auth/login", json={
            "email": ADMIN_EMAIL, "password": ADMIN_PASSWORD,
        }, timeout=15)
        assert r.status_code == 400, r.text
        body = r.text.lower()
        assert "recaptcha" in body and "missing" in body

    def test_09_login_garbage_token_blocked(self, headers):
        _enable_recaptcha(headers)
        r = requests.post(f"{API}/auth/login", json={
            "email": ADMIN_EMAIL,
            "password": ADMIN_PASSWORD,
            "recaptcha_token": "deadbeef" * 8,
        }, timeout=25)
        assert r.status_code != 200, r.text
        assert r.status_code in (400, 403, 502), r.text
        # Must not leak into the pre-recaptcha password error path
        assert "invalid email or password" not in r.text.lower()

    def test_10_register_missing_token_blocked(self, headers):
        _enable_recaptcha(headers)
        email = f"TEST_recap_block_{uuid.uuid4().hex[:8]}@example.com"
        r = requests.post(f"{API}/auth/register", json={
            "email": email, "password": "TestPass2026!", "name": "TEST Blocked",
        }, timeout=15)
        assert r.status_code == 400, r.text
        assert "recaptcha" in r.text.lower()

    def test_11_forgot_password_missing_token_blocked(self, headers):
        _enable_recaptcha(headers)
        r = requests.post(f"{API}/auth/forgot-password", json={
            "email": ADMIN_EMAIL,
        }, timeout=15)
        assert r.status_code == 400, r.text
        assert "recaptcha" in r.text.lower()

    # ---------- 6. Disable again → immediately reflected ----------
    def test_12_disable_reflected_immediately(self, headers):
        _enable_recaptcha(headers)
        r1 = requests.get(f"{API}/auth/config", timeout=10)
        assert r1.status_code == 200
        assert r1.json()["recaptcha"]["enabled"] is True

        r2 = _disable_recaptcha(headers)
        assert r2.status_code == 200, r2.text

        r3 = requests.get(f"{API}/auth/config", timeout=10)
        assert r3.status_code == 200
        rc = r3.json()["recaptcha"]
        assert rc["enabled"] is False
        assert rc["site_key"] is None

        # Login works again without token
        r4 = requests.post(f"{API}/auth/login", json={
            "email": ADMIN_EMAIL, "password": ADMIN_PASSWORD,
        }, timeout=15)
        assert r4.status_code == 200, r4.text
        assert r4.json().get("token")

    # ---------- 7. Backward compatibility ----------
    def test_13_login_payload_without_recaptcha_field(self, headers):
        _disable_recaptcha(headers)
        payload = {"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}
        assert "recaptcha_token" not in payload
        r = requests.post(f"{API}/auth/login", json=payload, timeout=15)
        assert r.status_code == 200, r.text
