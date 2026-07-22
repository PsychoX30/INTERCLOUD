"""Password lifecycle: change / admin-reset / forgot / reset."""
import os
import re
import time
import requests
import pytest

API = os.environ.get("PORTAL_API_BASE") or "http://localhost:8001/api/portal"
LOG_PATHS = ["/var/log/supervisor/backend.err.log", "/var/log/supervisor/backend.out.log"]


def _h(t: str) -> dict:
    return {"Authorization": f"Bearer {t}"}


@pytest.fixture
def admin_token():
    r = requests.post(f"{API}/auth/login", json={
        "email": os.environ["ADMIN_EMAIL"], "password": os.environ["ADMIN_PASSWORD"],
    })
    r.raise_for_status()
    return r.json()["token"]


def _login(email: str, pw: str):
    return requests.post(f"{API}/auth/login", json={"email": email, "password": pw})


def _pluck_last_token_from_logs() -> str:
    """Grab the most-recent password-reset token the backend logged (used when SMTP is off)."""
    for p in LOG_PATHS:
        try:
            with open(p, "r", errors="ignore") as f:
                text = f.read()
        except FileNotFoundError:
            continue
        matches = re.findall(r"token=([A-Za-z0-9_-]+)", text)
        if matches:
            return matches[-1]
    return ""


class TestSelfChangePassword:
    """Uses a throw-away user so we don't affect other tests / seed logins."""

    @pytest.fixture
    def user(self, admin_token):
        email = f"pwtest_{int(time.time()*1000)}_{os.getpid()}@example.co"
        pw = "InitialPass123!"
        r = requests.post(f"{API}/admin/users", headers=_h(admin_token), json={
            "email": email, "password": pw, "name": "PW Test", "role": "client",
        })
        assert r.status_code == 200
        uid = r.json()["id"]
        yield {"id": uid, "email": email, "password": pw}
        requests.delete(f"{API}/admin/users/{uid}", headers=_h(admin_token))

    def test_wrong_current_password_rejected(self, user):
        tok = _login(user["email"], user["password"]).json()["token"]
        r = requests.post(f"{API}/auth/change-password", headers=_h(tok),
                          json={"current_password": "wrong", "new_password": "NewPass1234!"})
        assert r.status_code == 400
        # Original password still works
        assert _login(user["email"], user["password"]).status_code == 200

    def test_same_password_rejected(self, user):
        tok = _login(user["email"], user["password"]).json()["token"]
        r = requests.post(f"{API}/auth/change-password", headers=_h(tok), json={
            "current_password": user["password"], "new_password": user["password"],
        })
        assert r.status_code == 400

    def test_weak_password_rejected(self, user):
        tok = _login(user["email"], user["password"]).json()["token"]
        r = requests.post(f"{API}/auth/change-password", headers=_h(tok), json={
            "current_password": user["password"], "new_password": "short",
        })
        assert r.status_code == 422

    def test_happy_path_change_password(self, user):
        tok = _login(user["email"], user["password"]).json()["token"]
        new_pw = "ChangedPw2026!"
        r = requests.post(f"{API}/auth/change-password", headers=_h(tok), json={
            "current_password": user["password"], "new_password": new_pw,
        })
        assert r.status_code == 200
        # Old password no longer works
        assert _login(user["email"], user["password"]).status_code == 401
        # New password works
        assert _login(user["email"], new_pw).status_code == 200


class TestAdminReset:
    @pytest.fixture
    def user(self, admin_token):
        email = f"admreset_{int(time.time()*1000)}_{os.getpid()}@example.co"
        pw = "InitialPass123!"
        r = requests.post(f"{API}/admin/users", headers=_h(admin_token), json={
            "email": email, "password": pw, "name": "AdminReset", "role": "client",
        })
        uid = r.json()["id"]
        yield {"id": uid, "email": email, "password": pw}
        requests.delete(f"{API}/admin/users/{uid}", headers=_h(admin_token))

    def test_admin_can_reset_any_user_password(self, admin_token, user):
        new_pw = "AdminSetPw2026!"
        r = requests.post(f"{API}/admin/users/{user['id']}/reset-password", headers=_h(admin_token),
                          json={"new_password": new_pw, "notify_user": False})
        assert r.status_code == 200
        # Old password no longer works, new one does
        assert _login(user["email"], user["password"]).status_code == 401
        assert _login(user["email"], new_pw).status_code == 200

    def test_client_cannot_reset_others_passwords(self, admin_token, user):
        # Log in as a different client and try to reset user2 (should be 403)
        client_tok = _login(os.environ["CLIENT_EMAIL"], os.environ["CLIENT_PASSWORD"]).json()["token"]
        r = requests.post(f"{API}/admin/users/{user['id']}/reset-password", headers=_h(client_tok),
                          json={"new_password": "TryToHack1234!"})
        assert r.status_code == 403


class TestForgotAndResetFlow:
    @pytest.fixture
    def user(self, admin_token):
        email = f"forgot_{int(time.time()*1000)}_{os.getpid()}@example.co"
        pw = "InitialPass123!"
        r = requests.post(f"{API}/admin/users", headers=_h(admin_token), json={
            "email": email, "password": pw, "name": "Forgot Test", "role": "client",
        })
        uid = r.json()["id"]
        yield {"id": uid, "email": email, "password": pw}
        requests.delete(f"{API}/admin/users/{uid}", headers=_h(admin_token))

    def test_forgot_password_is_public_and_neutral(self, user):
        # Existing email
        r = requests.post(f"{API}/auth/forgot-password", json={"email": user["email"]})
        assert r.status_code == 200
        # Non-existing email — same status/message (no enumeration)
        r2 = requests.post(f"{API}/auth/forgot-password", json={"email": "nobody@example.co"})
        assert r2.status_code == 200
        assert r.json()["message"] == r2.json()["message"]

    def test_reset_link_token_works_once(self, user):
        # Trigger a fresh reset
        r = requests.post(f"{API}/auth/forgot-password", json={"email": user["email"]})
        assert r.status_code == 200
        # Give backend a moment to flush the log
        time.sleep(0.5)
        token = _pluck_last_token_from_logs()
        if not token:
            pytest.skip("could not grep reset token from backend log")
        new_pw = "ResetFlowPw2026!"
        r2 = requests.post(f"{API}/auth/reset-password",
                           json={"token": token, "new_password": new_pw})
        assert r2.status_code == 200, r2.text
        # Old pw fails, new pw works
        assert _login(user["email"], user["password"]).status_code == 401
        assert _login(user["email"], new_pw).status_code == 200
        # Second use of same token is rejected
        r3 = requests.post(f"{API}/auth/reset-password",
                           json={"token": token, "new_password": "ShouldFail99!"})
        assert r3.status_code == 400

    def test_reset_rejects_bad_token(self):
        r = requests.post(f"{API}/auth/reset-password",
                          json={"token": "not-a-real-token", "new_password": "Whatever1234!"})
        assert r.status_code == 400
