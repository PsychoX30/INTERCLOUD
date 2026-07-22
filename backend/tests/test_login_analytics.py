"""Backend tests for Login Attempt Analytics dashboard.

Endpoint under test: GET /api/portal/admin/security/login-analytics
Populated by: /auth/login (every attempt logged into `login_attempts` collection)

All tests grouped in a single class so xdist's default loadscope pins them
to one worker — they mutate shared state (login_attempts collection +
integration_settings.recaptcha doc) and must run sequentially.

IMPORTANT (regression note): This suite AND `test_recaptcha_auth.py` both
mutate `integration_settings.recaptcha`. Running the two files together
under `-n 2 --dist loadscope` puts them on DIFFERENT workers → they race.
Always run them SEPARATELY, e.g. two `pytest` invocations. Bundled runs
with `test_assets_straight_line.py` are safe (no shared state).

We call /auth/login against localhost:8001 (not the public URL) so
request.client.host == "127.0.0.1" — this is what the review-request's
top_ips assertion checks. Admin analytics reads (auth-protected) hit the
same localhost URL because it doesn't matter which URL we use — both paths
end up in the same DB.
"""
import os
import uuid
import pytest
import requests


pytestmark = pytest.mark.xdist_group("recaptcha_shared")


# For login attempts + analytics reads we go DIRECT to the backend so
# request.client.host == "127.0.0.1" (the ingress rewrites it to the pod IP).
LOCAL_API = "http://localhost:8001/api/portal"

ADMIN_EMAIL = "admin@intercloud-digital.com"
ADMIN_PASSWORD = "AdminIntercloud2026!"
CLIENT_EMAIL = "demo@client.com"
CLIENT_PASSWORD = "ClientDemo2026!"

FAKE_SITE_KEY = "6LcFakeSiteKeyForTests1234567890ABCDEF"
FAKE_SECRET_KEY = "6LcSecretKeyForTests1234567890ABCDEFGH"


def _login(email, password, extra=None):
    payload = {"email": email, "password": password}
    if extra:
        payload.update(extra)
    return requests.post(f"{LOCAL_API}/auth/login", json=payload, timeout=20)


def _admin_h(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _analytics(headers, window="24h", limit=None):
    params = {"window": window}
    if limit is not None:
        params["limit"] = limit
    return requests.get(
        f"{LOCAL_API}/admin/security/login-analytics",
        headers=headers, params=params, timeout=15,
    )


def _disable_recaptcha(headers):
    return requests.put(
        f"{LOCAL_API}/admin/integrations-v2/recaptcha",
        headers=headers,
        json={"enabled": False, "credentials": {}, "options": {}},
        timeout=15,
    )


def _enable_recaptcha(headers):
    return requests.put(
        f"{LOCAL_API}/admin/integrations-v2/recaptcha",
        headers=headers,
        json={
            "enabled": True,
            "credentials": {"site_key": FAKE_SITE_KEY, "secret_key": FAKE_SECRET_KEY},
            "options": {"min_score": 0.5, "verify_action": True},
        },
        timeout=15,
    )


class TestLoginAnalytics:
    """Aggregation / RBAC / windowing tests for Security > Login Analytics."""

    @pytest.fixture(scope="class", autouse=True)
    def admin_token(self):
        r = _login(ADMIN_EMAIL, ADMIN_PASSWORD)
        if r.status_code != 200:
            pytest.skip(f"Admin login failed: {r.status_code} {r.text}")
        return r.json()["token"]

    @pytest.fixture(scope="class")
    def headers(self, admin_token):
        return _admin_h(admin_token)

    @pytest.fixture(scope="class")
    def client_token(self):
        r = _login(CLIENT_EMAIL, CLIENT_PASSWORD)
        if r.status_code != 200:
            pytest.skip(f"Client login failed: {r.status_code} {r.text}")
        return r.json()["token"]

    @pytest.fixture(autouse=True, scope="class")
    def _cleanup_recaptcha(self, headers):
        _disable_recaptcha(headers)   # ensure disabled before starting
        # Disable auto-block for this suite (brute-force test intentionally
        # generates 3+ failures from 127.0.0.1, which can start to trip the
        # threshold if combined with other test files run before this one).
        _prior = None
        try:
            _prior = requests.get(
                f"{LOCAL_API}/admin/security/settings", headers=headers, timeout=10
            ).json()
            requests.put(
                f"{LOCAL_API}/admin/security/settings", headers=headers,
                json={"auto_block_enabled": False}, timeout=10,
            )
            requests.delete(
                f"{LOCAL_API}/admin/security/blocked-ips/127.0.0.1",
                headers=headers, timeout=10,
            )
        except Exception:
            pass
        yield
        _disable_recaptcha(headers)   # leave disabled
        try:
            if _prior and isinstance(_prior, dict):
                requests.put(
                    f"{LOCAL_API}/admin/security/settings", headers=headers,
                    json={"auto_block_enabled": bool(_prior.get(
                        "auto_block_enabled", True))}, timeout=10,
                )
        except Exception:
            pass

    # ---------- 1. RBAC ----------
    def test_01_analytics_requires_auth(self):
        r = requests.get(f"{LOCAL_API}/admin/security/login-analytics", timeout=10)
        assert r.status_code == 401, r.text

    def test_02_analytics_forbidden_for_client(self, client_token):
        r = _analytics(_admin_h(client_token))
        assert r.status_code == 403, r.text

    def test_03_analytics_ok_for_admin(self, headers):
        r = _analytics(headers)
        assert r.status_code == 200, r.text
        data = r.json()
        # Shape check
        for k in ("window", "since", "totals", "reason_breakdown", "top_ips",
                  "top_emails", "series", "score_distribution", "recent"):
            assert k in data, f"missing key {k} in analytics response"
        for k in ("attempts", "successes", "failures", "success_rate", "recaptcha_blocks"):
            assert k in data["totals"], f"missing totals.{k}"
        assert data["window"] == "24h"

    # ---------- 2. Successful login is logged ----------
    def test_04_successful_admin_login_recorded(self, headers):
        before = _analytics(headers).json()["totals"]
        r = _login(ADMIN_EMAIL, ADMIN_PASSWORD)
        assert r.status_code == 200, r.text
        after = _analytics(headers).json()
        assert after["totals"]["attempts"] >= before["attempts"] + 1
        assert after["totals"]["successes"] >= before["successes"] + 1
        # Most recent entry should be this admin login
        recent = after["recent"]
        assert len(recent) >= 1
        top = recent[0]
        assert top["email"] == ADMIN_EMAIL.lower()
        assert top["success"] is True
        assert top["reason"] == "ok"
        assert top["action"] == "login"

    # ---------- 3. Brute-force failure attempts ----------
    def test_05_brute_force_failures_aggregate(self, headers):
        target_email = "bruteforce@example.com"
        before = _analytics(headers).json()
        before_totals = before["totals"]
        before_reason = {r["reason"]: r["count"] for r in before["reason_breakdown"]}
        before_ip = {r["ip"]: r["count"] for r in before["top_ips"]}
        before_email = {r["email"]: r["count"] for r in before["top_emails"]}

        for _ in range(3):
            r = _login(target_email, "not-the-real-password")
            assert r.status_code == 401, r.text

        after = _analytics(headers).json()
        # Failures increased by >=3
        assert after["totals"]["failures"] >= before_totals["failures"] + 3, (
            f"failures did not increase by 3: before={before_totals}, after={after['totals']}"
        )
        # reason_breakdown: invalid_credentials +>=3
        after_reason = {r["reason"]: r["count"] for r in after["reason_breakdown"]}
        delta = after_reason.get("invalid_credentials", 0) - before_reason.get("invalid_credentials", 0)
        assert delta >= 3, f"invalid_credentials delta = {delta}"

        # top_ips: 127.0.0.1 count grew by >=3
        after_ip = {r["ip"]: r["count"] for r in after["top_ips"]}
        assert "127.0.0.1" in after_ip, f"127.0.0.1 not in top_ips: {after_ip}"
        assert after_ip["127.0.0.1"] - before_ip.get("127.0.0.1", 0) >= 3

        # top_emails: bruteforce@example.com count grew by >=3
        after_email = {r["email"]: r["count"] for r in after["top_emails"]}
        assert target_email in after_email, f"{target_email} not in top_emails: {after_email}"
        assert after_email[target_email] - before_email.get(target_email, 0) >= 3

    # ---------- 4. reCAPTCHA blocks logged ----------
    def test_06_recaptcha_missing_and_failed_logged(self, headers):
        _enable_recaptcha(headers)
        try:
            before = _analytics(headers).json()
            before_blocks = before["totals"]["recaptcha_blocks"]
            before_reason = {r["reason"]: r["count"] for r in before["reason_breakdown"]}

            # (a) No token → recaptcha_missing
            r1 = _login("attacker@example.com", "irrelevant")
            assert r1.status_code == 400, r1.text
            assert "recaptcha" in r1.text.lower()

            # (b) Garbage token → recaptcha_failed OR recaptcha_low_score
            r2 = _login("attacker@example.com", "irrelevant",
                        extra={"recaptcha_token": "deadbeef" * 8})
            assert r2.status_code in (400, 403, 502), r2.text

            after = _analytics(headers).json()
            assert after["totals"]["recaptcha_blocks"] >= before_blocks + 1
            after_reason = {r["reason"]: r["count"] for r in after["reason_breakdown"]}
            # recaptcha_missing +>=1
            delta_missing = after_reason.get("recaptcha_missing", 0) - before_reason.get("recaptcha_missing", 0)
            assert delta_missing >= 1, f"recaptcha_missing delta = {delta_missing}"
            # Second attempt: either recaptcha_failed or recaptcha_low_score bumped
            delta_failed = (after_reason.get("recaptcha_failed", 0) - before_reason.get("recaptcha_failed", 0)) + \
                           (after_reason.get("recaptcha_low_score", 0) - before_reason.get("recaptcha_low_score", 0))
            assert delta_failed >= 1, (
                f"recaptcha_failed+low_score delta = {delta_failed}. "
                f"before={before_reason}, after={after_reason}"
            )
        finally:
            _disable_recaptcha(headers)

    # ---------- 5. Time series bucket counts ----------
    def test_07_series_bucket_counts_24h(self, headers):
        data = _analytics(headers, window="24h").json()
        assert data["window"] == "24h"
        assert len(data["series"]) == 25, f"24h expected 25 hourly buckets, got {len(data['series'])}"

    def test_08_series_bucket_counts_7d(self, headers):
        data = _analytics(headers, window="7d").json()
        assert data["window"] == "7d"
        assert len(data["series"]) == 8, f"7d expected 8 daily buckets, got {len(data['series'])}"

    def test_09_series_bucket_counts_30d(self, headers):
        data = _analytics(headers, window="30d").json()
        assert data["window"] == "30d"
        assert len(data["series"]) == 31, f"30d expected 31 daily buckets, got {len(data['series'])}"

    # ---------- 6. Score distribution ----------
    def test_10_score_distribution_shape(self, headers):
        data = _analytics(headers).json()
        sd = data["score_distribution"]
        assert "buckets" in sd and "total_scored" in sd
        assert len(sd["buckets"]) == 11, f"expected 11 score buckets, got {len(sd['buckets'])}"
        keys = [b["bucket"] for b in sd["buckets"]]
        assert keys == [f"{i/10:.1f}" for i in range(11)]
        assert isinstance(sd["total_scored"], int)
        # total_scored equals sum of bucket counts
        assert sd["total_scored"] == sum(b["count"] for b in sd["buckets"])

    # ---------- 7. Windows don't crash on empty ----------
    def test_11_all_windows_return_valid(self, headers):
        for w in ("24h", "7d", "30d"):
            r = _analytics(headers, window=w)
            assert r.status_code == 200
            d = r.json()
            assert d["window"] == w
            assert isinstance(d["totals"]["attempts"], int)
            assert isinstance(d["series"], list) and len(d["series"]) > 0

    # ---------- 8. Recent limit ----------
    def test_12_recent_limit_default_and_capped(self, headers):
        # Ensure there are >5 attempts already; the brute-force test made 3,
        # the successful login made 1 → guarantee more by doing a couple more.
        for _ in range(3):
            _login(ADMIN_EMAIL, "wrong-password")

        default_data = _analytics(headers).json()
        assert len(default_data["recent"]) <= 100
        # There should be plenty of rows now
        assert len(default_data["recent"]) >= 5

        limited = _analytics(headers, limit=5).json()
        assert len(limited["recent"]) == 5

    # ---------- 9. Unknown window falls back gracefully (no crash) ----------
    def test_13_unknown_window_defaults(self, headers):
        r = _analytics(headers, window="garbage")
        assert r.status_code == 200, r.text
        data = r.json()
        # Server must respond gracefully — series is a list, totals object present.
        assert isinstance(data["series"], list) and len(data["series"]) > 0
        assert isinstance(data["totals"]["attempts"], int)
