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
        # Must NOT crash — a list, or the per-user not_setup hint.
        assert r.status_code == 200, r.text
        rows = r.json()
        assert isinstance(rows, list) or (isinstance(rows, dict) and rows.get("not_setup"))
        _reset(admin_token, "imap")


# ---------- /admin/mail/send honours the CALLER's personal SMTP ----------
# (Mail became per-user in the personal-mailbox phase: global v2 SMTP flags
#  no longer drive /admin/mail/send — the caller's Settings ▸ Email does.)
BARE_EMAIL = "mailtest-bare@intercloud-digital.com"
BARE_PASS = "MailBare2026!"


@pytest.fixture(scope="module")
def bare_staff_token(admin_token):
    """A staff account with NO personal SMTP/IMAP configured."""
    users = requests.get(f"{API}/admin/users", headers=_h(admin_token)).json()
    hit = next((u for u in users if u.get("email") == BARE_EMAIL), None)
    if hit:
        requests.put(f"{API}/admin/users/{hit['id']}", headers=_h(admin_token),
                     json={"password": BARE_PASS, "role": "support"})
        uid = hit["id"]
    else:
        r = requests.post(f"{API}/admin/users", headers=_h(admin_token), json={
            "email": BARE_EMAIL, "password": BARE_PASS,
            "name": "Mail Bare", "role": "support"})
        uid = r.json()["id"]
    # Wipe any personal mail settings left over from previous runs
    import pymongo
    from bson import ObjectId
    db = pymongo.MongoClient(os.environ["MONGO_URL"])[os.environ.get("DB_NAME", "intercloud")]
    db.users.update_one({"_id": ObjectId(uid)}, {"$unset": {"email_settings": ""}})
    r = requests.post(f"{API}/auth/login", json={"email": BARE_EMAIL, "password": BARE_PASS})
    return r.json()["token"]


class TestMailSendPaths:
    def test_send_without_personal_smtp_returns_actionable_400(self, bare_staff_token):
        r = requests.post(f"{API}/admin/mail/send",
                          headers=_h(bare_staff_token),
                          json={"to": "someone@example.com",
                                "subject": "Test disabled",
                                "body": "hello"})
        assert r.status_code == 400, r.text
        assert "SMTP" in r.json().get("detail", "")

    def test_send_with_unreachable_personal_smtp_returns_502(self, bare_staff_token):
        # Point the bare user's PERSONAL SMTP at an unreachable host
        r = requests.post(f"{API}/settings/email",
                          headers=_h(bare_staff_token),
                          json={"from_name": "Mail Bare",
                                "from_email": "bare@example.com",
                                "smtp": {"host": "smtp.invalid.example.com",
                                          "port": 587, "username": "u",
                                          "password": "p", "use_ssl": False}})
        assert r.status_code == 200, r.text
        r = requests.post(f"{API}/admin/mail/send",
                          headers=_h(bare_staff_token),
                          json={"to": "someone@example.com",
                                "subject": "Test enabled",
                                "body": "hello"})
        assert r.status_code == 502, r.text
        assert "SMTP kirim gagal" in r.json().get("detail", "")
