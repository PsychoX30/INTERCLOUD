"""Unified Integrations — IMAP, cPanel, Plesk added; Real APIs page merged."""
import os
import pytest
import requests

API = os.environ.get("PORTAL_API_BASE") or "http://localhost:8001/api/portal"


def _h(tok):
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture(scope="module")
def admin_token():
    r = requests.post(f"{API}/auth/login", json={
        "email": os.environ["ADMIN_EMAIL"], "password": os.environ["ADMIN_PASSWORD"]})
    return r.json()["token"]


class TestUnifiedSchema:
    def test_schema_lists_all_providers(self, admin_token):
        r = requests.get(f"{API}/admin/integrations-v2/schema", headers=_h(admin_token))
        assert r.status_code == 200
        keys = set(r.json().keys())
        expected = {"proxmox", "mikrotik", "cpanel", "plesk",
                    "midtrans", "xendit", "duitku", "smtp", "imap"}
        assert expected.issubset(keys), f"missing providers: {expected - keys}"

    def test_schema_has_categories(self, admin_token):
        r = requests.get(f"{API}/admin/integrations-v2/schema", headers=_h(admin_token))
        schema = r.json()
        assert schema["proxmox"]["category"] == "virtualization"
        assert schema["mikrotik"]["category"] == "network"
        assert schema["cpanel"]["category"] == "provisioning"
        assert schema["plesk"]["category"] == "provisioning"
        assert schema["midtrans"]["category"] == "payment"
        assert schema["smtp"]["category"] == "mail"
        assert schema["imap"]["category"] == "mail"

    def test_imap_has_expected_fields(self, admin_token):
        r = requests.get(f"{API}/admin/integrations-v2/schema", headers=_h(admin_token))
        imap = r.json()["imap"]
        cred_keys = {c["key"] for c in imap["credentials"]}
        opt_keys = {o["key"] for o in imap["options"]}
        assert cred_keys == {"host", "port", "username", "password"}
        assert {"use_ssl", "mailbox", "fetch_limit"}.issubset(opt_keys)


class TestIMAPFlow:
    def test_imap_save_masks_password(self, admin_token):
        payload = {
            "enabled": False,
            "credentials": {"host": "imap.example.com", "port": 993,
                            "username": "u@example.com", "password": "supersecret"},
            "options": {"use_ssl": True, "mailbox": "INBOX", "fetch_limit": 25},
        }
        r = requests.put(f"{API}/admin/integrations-v2/imap",
                         headers=_h(admin_token), json=payload)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["credentials"]["password"] == ""  # raw stripped
        assert body["credentials"].get("password_masked", "").endswith("**")

    def test_imap_test_unconfigured_returns_message(self, admin_token):
        # Delete first — v2 upsert with enabled=false is enough to make test path 'not configured' when unset
        # But we already saved above; explicit disable will still return the gaierror. Verify graceful failure.
        payload = {
            "enabled": True,
            "credentials": {"host": "imap.example.com", "port": 993,
                            "username": "u@example.com", "password": "s"},
            "options": {"use_ssl": True, "mailbox": "INBOX"},
        }
        requests.put(f"{API}/admin/integrations-v2/imap",
                     headers=_h(admin_token), json=payload)
        r = requests.post(f"{API}/admin/integrations-v2/imap/test",
                          headers=_h(admin_token))
        assert r.status_code == 200
        assert r.json()["ok"] is False   # gaierror / connection error
        # Reset
        requests.put(f"{API}/admin/integrations-v2/imap",
                     headers=_h(admin_token),
                     json={"enabled": False, "credentials": {}, "options": {}})


class TestCpanelPleskValidation:
    def test_cpanel_test_reports_missing_creds(self, admin_token):
        # Reset to clean slate first (PUT merges secrets — DELETE wipes them).
        requests.delete(f"{API}/admin/integrations-v2/cpanel", headers=_h(admin_token))
        requests.put(f"{API}/admin/integrations-v2/cpanel",
                     headers=_h(admin_token),
                     json={"enabled": True, "credentials": {}, "options": {}})
        r = requests.post(f"{API}/admin/integrations-v2/cpanel/test",
                          headers=_h(admin_token))
        assert r.status_code == 200
        assert r.json()["ok"] is False
        assert "Missing" in r.json()["message"] or "credentials" in r.json()["message"].lower()

    def test_cpanel_test_passes_with_complete_creds(self, admin_token):
        requests.put(f"{API}/admin/integrations-v2/cpanel",
                     headers=_h(admin_token),
                     json={"enabled": True,
                           "credentials": {"host": "https://whm.example.com:2087",
                                           "username": "root", "api_token": "tok"},
                           "options": {}})
        r = requests.post(f"{API}/admin/integrations-v2/cpanel/test",
                          headers=_h(admin_token))
        assert r.status_code == 200
        assert r.json()["ok"] is True
        # cleanup
        requests.put(f"{API}/admin/integrations-v2/cpanel",
                     headers=_h(admin_token),
                     json={"enabled": False, "credentials": {}, "options": {}})

    def test_plesk_test_with_password(self, admin_token):
        requests.put(f"{API}/admin/integrations-v2/plesk",
                     headers=_h(admin_token),
                     json={"enabled": True,
                           "credentials": {"host": "https://plesk.example.com:8443",
                                           "username": "admin", "password": "pw"},
                           "options": {}})
        r = requests.post(f"{API}/admin/integrations-v2/plesk/test",
                          headers=_h(admin_token))
        assert r.status_code == 200
        assert r.json()["ok"] is True
        requests.put(f"{API}/admin/integrations-v2/plesk",
                     headers=_h(admin_token),
                     json={"enabled": False, "credentials": {}, "options": {}})


class TestSMTPTest:
    def test_smtp_test_now_wired(self, admin_token):
        """SMTP test used to return 'No test method'. Now it should attempt a real
        SMTP connect (which will fail against example.com but returns ok=false)."""
        requests.put(f"{API}/admin/integrations-v2/smtp",
                     headers=_h(admin_token),
                     json={"enabled": True,
                           "credentials": {"host": "smtp.example.com", "port": 587,
                                           "username": "u", "password": "p"},
                           "options": {"from_email": "u@example.com",
                                       "from_name": "Intercloud",
                                       "use_tls": True, "use_ssl": False}})
        r = requests.post(f"{API}/admin/integrations-v2/smtp/test",
                          headers=_h(admin_token))
        assert r.status_code == 200
        d = r.json()
        # Success or graceful failure, never a bare "No test method" any more
        assert isinstance(d.get("ok"), bool)
        assert "No test method" not in d["message"]
        # cleanup
        requests.put(f"{API}/admin/integrations-v2/smtp",
                     headers=_h(admin_token),
                     json={"enabled": False, "credentials": {}, "options": {}})


class TestMenuCatalog:
    def test_real_integrations_key_removed(self, admin_token):
        r = requests.get(f"{API}/admin/user-access-catalog", headers=_h(admin_token))
        assert r.status_code == 200
        keys = {m["key"] for m in r.json()["menu_catalog"]}
        assert "real_integrations" not in keys
        # Unified 'integrations' still there
        assert "integrations" in keys


class TestMailInboxHonorsIMAP:
    def test_inbox_falls_back_to_mock_when_imap_disabled(self, admin_token):
        # Ensure IMAP disabled
        requests.put(f"{API}/admin/integrations-v2/imap",
                     headers=_h(admin_token),
                     json={"enabled": False, "credentials": {}, "options": {}})
        r = requests.get(f"{API}/admin/mail/inbox", headers=_h(admin_token))
        assert r.status_code == 200
        rows = r.json()
        assert isinstance(rows, list)
        # mocked messages have no _live flag
        assert all(not m.get("_live") for m in rows)


class TestDeleteEndpoint:
    def test_delete_provider_wipes_settings(self, admin_token):
        # Seed some settings
        requests.put(f"{API}/admin/integrations-v2/duitku",
                     headers=_h(admin_token),
                     json={"enabled": True,
                           "credentials": {"merchant_code": "MC-01", "api_key": "sekret"},
                           "options": {"sandbox": False}})
        before = requests.get(f"{API}/admin/integrations-v2", headers=_h(admin_token)).json()
        assert before["duitku"].get("credentials", {}).get("merchant_code") == "MC-01"

        r = requests.delete(f"{API}/admin/integrations-v2/duitku", headers=_h(admin_token))
        assert r.status_code == 200
        assert r.json()["deleted"] == 1

        after = requests.get(f"{API}/admin/integrations-v2", headers=_h(admin_token)).json()
        # After delete, back to default shape (empty credentials)
        assert not after["duitku"].get("credentials")
        assert after["duitku"].get("enabled") is False

    def test_delete_unknown_provider_404(self, admin_token):
        r = requests.delete(f"{API}/admin/integrations-v2/nonexistent", headers=_h(admin_token))
        assert r.status_code == 404
