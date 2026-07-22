"""Self-registration + CRM auto-mirror tests."""
import os
import time
import requests
import pytest

API = os.environ.get("PORTAL_API_BASE") or "http://localhost:8001/api/portal"


def _h(t: str) -> dict:
    return {"Authorization": f"Bearer {t}"}


def _admin_token() -> str:
    r = requests.post(f"{API}/auth/login", json={
        "email": os.environ["ADMIN_EMAIL"], "password": os.environ["ADMIN_PASSWORD"],
    })
    r.raise_for_status()
    return r.json()["token"]


class TestRegister:
    def _new_email(self) -> str:
        return f"regtest_{int(time.time()*1000)}_{os.getpid()}@example.co"

    def test_self_registration_happy_path(self):
        email = self._new_email()
        r = requests.post(f"{API}/auth/register", json={
            "email": email,
            "password": "SecurePass123!",
            "name": "Registration Happy",
            "phone": "+62 812-0000-0000",
            "company": "PT Regtest",
            "attention": "Registration Happy",
            "address_line1": "Jl. Test 1",
            "city": "Jakarta",
            "province": "DKI Jakarta",
            "postal_code": "12000",
            "country": "Indonesia",
            "npwp": "12.345.678.9-000.000",
            "industry": "SaaS / Tech Startup",
            "accepts_tos": True,
        })
        assert r.status_code == 200
        body = r.json()
        assert body["user"]["role"] == "client"
        assert body["user"]["email"] == email
        assert body["user"]["npwp"] == "12.345.678.9-000.000"
        assert body["token"]

        # /auth/me works with returned token
        me = requests.get(f"{API}/auth/me", headers=_h(body["token"]))
        assert me.status_code == 200
        assert me.json()["email"] == email

        # CRM auto-mirror is a `prospect` with self_registration source
        crm = requests.get(f"{API}/admin/crm", headers=_h(_admin_token())).json()
        matches = [c for c in crm if c["email"] == email]
        assert len(matches) == 1
        c = matches[0]
        assert c["status"] == "prospect"
        assert c["source"] == "self_registration"
        assert c["user_id"] == body["user"]["id"]

    def test_duplicate_email_returns_409(self):
        email = self._new_email()
        payload = {"email": email, "password": "SecurePass123!", "name": "Dup Test",
                   "accepts_tos": True}
        assert requests.post(f"{API}/auth/register", json=payload).status_code == 200
        assert requests.post(f"{API}/auth/register", json=payload).status_code == 409

    def test_tos_required(self):
        r = requests.post(f"{API}/auth/register", json={
            "email": self._new_email(), "password": "SecurePass123!",
            "name": "No TOS", "accepts_tos": False,
        })
        assert r.status_code == 400

    def test_weak_password_rejected(self):
        r = requests.post(f"{API}/auth/register", json={
            "email": self._new_email(), "password": "abc",
            "name": "Weak Pass", "accepts_tos": True,
        })
        # Pydantic min_length=8 → 422
        assert r.status_code == 422

    def test_admin_create_user_mirrors_to_crm(self):
        email = self._new_email()
        r = requests.post(f"{API}/admin/users", headers=_h(_admin_token()), json={
            "email": email, "password": "SecurePass123!", "name": "Admin Made",
            "role": "client", "company": "PT Adm",
        })
        assert r.status_code == 200
        # CRM row created with admin_registered source, status=existing
        crm = requests.get(f"{API}/admin/crm", headers=_h(_admin_token())).json()
        m = [c for c in crm if c["email"] == email]
        assert len(m) == 1
        assert m[0]["status"] == "existing"
        assert m[0]["source"] == "admin_registered"
        assert m[0]["user_id"] == r.json()["id"]

    def test_admin_create_admin_user_does_not_mirror_to_crm(self):
        """Only client users should get a CRM row — staff should not."""
        email = self._new_email()
        r = requests.post(f"{API}/admin/users", headers=_h(_admin_token()), json={
            "email": email, "password": "SecurePass123!", "name": "Staff Made",
            "role": "sales", "company": "PT Adm",
        })
        assert r.status_code == 200
        crm = requests.get(f"{API}/admin/crm", headers=_h(_admin_token())).json()
        m = [c for c in crm if c["email"] == email]
        assert m == []

    def test_register_endpoint_is_public(self):
        """No auth header required."""
        r = requests.post(f"{API}/auth/register", json={
            "email": self._new_email(), "password": "SecurePass123!",
            "name": "Public Test", "accepts_tos": True,
        })
        assert r.status_code == 200
