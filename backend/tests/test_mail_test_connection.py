"""Webmail fix — POST /settings/email/test connection tester + Compose flow.

Covers the bug: IMAP worked but Compose claimed SMTP wasn't set up (frontend
stub). Backend contract verified here:
  * /settings/email/test returns per-protocol {ok, message} for IMAP + SMTP
  * masked "••••••••" passwords fall back to the stored value
  * wrong credentials → HTTP 200 with ok:false (never a 5xx)
  * /admin/mail/send hard-fails 400 with the setup nudge when SMTP missing
"""
from __future__ import annotations
import os
import pytest
import requests

API = os.environ.get("REACT_APP_BACKEND_URL") or (
    (lambda p: next((l.split("=", 1)[1].strip().strip('"')
                     for l in open(p) if l.startswith("REACT_APP_BACKEND_URL=")), ""))
    ("/app/frontend/.env")
)
ADMIN_EMAIL = "admin@intercloud-digital.com"
ADMIN_PASS  = "AdminIntercloud2026!"

# Live mailbox provided by the user for connection testing.
MAIL_HOST = "mail.intercloud-digital.com"
MAIL_USER = "damien@intercloud-digital.com"
MAIL_PASS = "@Mail!234"


def _login(email: str, password: str) -> str:
    r = requests.post(f"{API}/api/portal/auth/login",
                      json={"email": email, "password": password}, timeout=15)
    r.raise_for_status()
    return r.json()["token"]


def _hdr(tok: str) -> dict:
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def _settings_payload(imap_pass: str = MAIL_PASS, smtp_pass: str = MAIL_PASS) -> dict:
    return {
        "from_name": "Damien", "from_email": MAIL_USER,
        "imap": {"host": MAIL_HOST, "port": 993, "username": MAIL_USER,
                 "password": imap_pass, "use_ssl": True},
        "smtp": {"host": MAIL_HOST, "port": 465, "username": MAIL_USER,
                 "password": smtp_pass, "use_ssl": True},
    }


@pytest.fixture(scope="module")
def admin_tok() -> str:
    return _login(ADMIN_EMAIL, ADMIN_PASS)


@pytest.fixture(scope="module", autouse=True)
def saved_settings(admin_tok: str):
    """Persist real creds once for the whole module (restores nothing — the
    admin account is expected to keep the damien mailbox configured)."""
    r = requests.post(f"{API}/api/portal/settings/email",
                      json=_settings_payload(), headers=_hdr(admin_tok), timeout=20)
    assert r.status_code == 200, r.text
    # password must come back masked
    assert set(r.json()["smtp"]["credentials"]["password"]) == {"•"}
    yield


def test_test_endpoint_real_creds_ok(admin_tok: str):
    r = requests.post(f"{API}/api/portal/settings/email/test",
                      json=_settings_payload(), headers=_hdr(admin_tok), timeout=60)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["imap"]["ok"] is True and "993" in body["imap"]["message"]
    assert body["smtp"]["ok"] is True and "465" in body["smtp"]["message"]


def test_test_endpoint_masked_password_falls_back(admin_tok: str):
    r = requests.post(f"{API}/api/portal/settings/email/test",
                      json=_settings_payload("••••••••", "••••••••"),
                      headers=_hdr(admin_tok), timeout=60)
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True


def test_test_endpoint_wrong_password_is_200_not_5xx(admin_tok: str):
    r = requests.post(f"{API}/api/portal/settings/email/test",
                      json=_settings_payload("definitely-wrong", "definitely-wrong"),
                      headers=_hdr(admin_tok), timeout=60)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is False
    assert body["imap"]["ok"] is False and body["imap"]["message"]
    assert body["smtp"]["ok"] is False and body["smtp"]["message"]


def test_test_endpoint_requires_auth():
    r = requests.post(f"{API}/api/portal/settings/email/test",
                      json={}, timeout=15)
    assert r.status_code in (401, 403)


def test_mail_send_delivers_via_smtp(admin_tok: str):
    r = requests.post(f"{API}/api/portal/admin/mail/send",
                      json={"to": MAIL_USER,
                            "subject": "pytest webmail compose regression",
                            "body": "<p>automated regression send</p>"},
                      headers=_hdr(admin_tok), timeout=60)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["delivered"] is True
    assert body["delivered_via"] == "smtp"


def test_mail_send_without_smtp_nudges_setup(admin_tok: str):
    """A staff user with no email_settings must get the 400 setup nudge."""
    # create a throwaway staff user
    import uuid
    email = f"pytest-mail-{uuid.uuid4().hex[:8]}@intercloud-digital.com"
    r = requests.post(f"{API}/api/portal/admin/users",
                      json={"name": "Pytest Mail", "email": email,
                            "password": "PytestMail2026!", "role": "support"},
                      headers=_hdr(admin_tok), timeout=15)
    assert r.status_code in (200, 201), r.text
    uid = r.json().get("id") or r.json().get("_id")
    try:
        tok = _login(email, "PytestMail2026!")
        r2 = requests.post(f"{API}/api/portal/admin/mail/send",
                           json={"to": "x@example.com", "subject": "hi", "body": "b"},
                           headers=_hdr(tok), timeout=20)
        assert r2.status_code == 400
        assert "Silakan setup SMTP" in r2.json()["detail"]
    finally:
        requests.delete(f"{API}/api/portal/admin/users/{uid}",
                        headers=_hdr(admin_tok), timeout=15)
