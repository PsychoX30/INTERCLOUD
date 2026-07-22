"""Regression tests for mail send/inbox honouring v2 SMTP/IMAP integrations."""
import os
import pytest
import requests

API = os.environ.get("PORTAL_API_BASE") or "http://localhost:8001/api/portal"


def _h(t):
    return {"Authorization": f"Bearer {t}"}


@pytest.fixture(scope="module")
def admin_token():
    r = requests.post(f"{API}/auth/login", json={
        "email": os.environ["ADMIN_EMAIL"], "password": os.environ["ADMIN_PASSWORD"]})
    return r.json()["token"]


def _reset(admin_token, provider):
    requests.put(f"{API}/admin/integrations-v2/{provider}",
                 headers=_h(admin_token),
                 json={"enabled": False, "credentials": {}, "options": {}})


# ---------- /admin/mail/inbox with IMAP unreachable ----------
class TestMailInboxIMAPFallback:
    def test_inbox_gracefully_falls_back_when_imap_unreachable(self, admin_token):
        # Configure IMAP with an unreachable host
        requests.put(f"{API}/admin/integrations-v2/imap",
                     headers=_h(admin_token),
                     json={"enabled": True,
                           "credentials": {"host": "imap.example.com",
                                           "port": 993,
                                           "username": "u@example.com",
                                           "password": "s"},
                           "options": {"use_ssl": True, "mailbox": "INBOX",
                                       "fetch_limit": 10}})
        r = requests.get(f"{API}/admin/mail/inbox", headers=_h(admin_token))
        # Must NOT crash — either seed fallback or an empty list.
        assert r.status_code == 200, r.text
        rows = r.json()
        assert isinstance(rows, list)
        _reset(admin_token, "imap")


# ---------- /admin/mail/send with v2 SMTP flags ----------
class TestMailSendPaths:
    def test_send_smtp_disabled_uses_legacy_or_queue(self, admin_token):
        _reset(admin_token, "smtp")
        r = requests.post(f"{API}/admin/mail/send",
                          headers=_h(admin_token),
                          json={"to": "someone@example.com",
                                "subject": "Test disabled",
                                "body": "hello"})
        assert r.status_code == 200, r.text
        d = r.json()
        assert "delivered_via" in d
        # Legacy path or explicit "not configured" queue path
        assert d["delivered_via"] in ("smtp-mock",
                                      "queued (SMTP not configured)") or \
               d["delivered_via"].startswith("queued") or \
               d["delivered_via"] == "smtp-mock"

    def test_send_smtp_enabled_unreachable_marks_failed(self, admin_token):
        requests.put(f"{API}/admin/integrations-v2/smtp",
                     headers=_h(admin_token),
                     json={"enabled": True,
                           "credentials": {"host": "smtp.example.com",
                                           "port": 587, "username": "u",
                                           "password": "p"},
                           "options": {"from_email": "u@example.com",
                                       "from_name": "Intercloud",
                                       "use_tls": True, "use_ssl": False}})
        r = requests.post(f"{API}/admin/mail/send",
                          headers=_h(admin_token),
                          json={"to": "someone@example.com",
                                "subject": "Test enabled",
                                "body": "hello"})
        assert r.status_code == 200, r.text
        d = r.json()
        assert d.get("delivered") is False
        assert str(d.get("delivered_via", "")).startswith("smtp-failed")
        _reset(admin_token, "smtp")
