"""Regression: IMAPConnectionError distinguishes connect-failure from empty
inbox, and admin_mail_inbox surfaces the reason in its response.

Also verifies the new `cover_image_alt` field round-trips through the
Article API so the SEO alt text set in the editor lands on the public
`<img alt=…>`.
"""
from __future__ import annotations
import os
import re
import time
import pytest
import requests

from backend.portal import integrations_v2 as iv2


API = os.environ.get("REACT_APP_BACKEND_URL") or (
    (lambda p: next((l.split("=", 1)[1].strip().strip('"')
                     for l in open(p) if l.startswith("REACT_APP_BACKEND_URL=")), ""))
    ("/app/frontend/.env")
)
ADMIN_EMAIL = "admin@intercloud-digital.com"
ADMIN_PASS  = "AdminIntercloud2026!"


def _login(email: str, password: str) -> str:
    r = requests.post(f"{API}/api/portal/auth/login",
                      json={"email": email, "password": password}, timeout=15)
    r.raise_for_status()
    return r.json()["token"]


def _hdr(tok: str) -> dict:
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def admin_tok() -> str:
    return _login(ADMIN_EMAIL, ADMIN_PASS)


# ============================================================
# IMAP error distinction
# ============================================================
def test_imap_connection_error_raised_for_bogus_host():
    """Unit-level: fetch_recent must raise IMAPConnectionError, not swallow
    the exception, when the mailbox is unreachable."""
    settings = {
        "credentials": {"host": "bogus-imap.invalid.example.com",
                        "port": 993, "username": "x", "password": "y"},
        "options": {"use_ssl": True, "mailbox": "INBOX", "fetch_limit": 5},
    }
    with pytest.raises(iv2.IMAPConnectionError) as exc:
        iv2.IMAPClient(settings).fetch_recent()
    # error message must include a diagnostic type name
    assert "IMAP" in str(exc.value)


def test_admin_mail_inbox_reports_connection_failed(admin_tok: str):
    """Save bogus IMAP creds on the admin account; hitting /admin/mail/inbox
    should return the actionable `connection_failed` payload (not `no_credentials`
    and not a misleading empty list)."""
    # Save bogus IMAP + SMTP so `configured` path triggers
    save = requests.post(
        f"{API}/api/portal/settings/email",
        json={
            "from_name": "Test", "from_email": "test@example.com",
            "imap": {"host": "bogus-imap.invalid.example.com", "port": 993,
                     "username": "x", "password": "y", "use_ssl": True},
            "smtp": {"host": "bogus-smtp.invalid.example.com", "port": 465,
                     "username": "x", "password": "y", "use_ssl": True},
        },
        headers=_hdr(admin_tok), timeout=15,
    )
    save.raise_for_status()

    try:
        r = requests.get(f"{API}/api/portal/admin/mail/inbox",
                         headers=_hdr(admin_tok), timeout=30)
        assert r.status_code == 200
        body = r.json()
        assert isinstance(body, dict), f"expected dict, got {type(body)}: {body}"
        assert body.get("not_setup") is True
        assert body.get("reason") == "connection_failed", (
            f"expected reason=connection_failed, got {body.get('reason')} "
            f"(full body: {body})")
        assert re.search(r"tidak bisa terhubung|IMAP", body.get("message", ""), re.I)
    finally:
        # Clean up so we don't leave the admin with bogus creds
        requests.delete(f"{API}/api/portal/settings/email",
                        headers=_hdr(admin_tok), timeout=15)


def test_admin_mail_inbox_reports_no_credentials(admin_tok: str):
    """After clearing email_settings, the inbox endpoint should say
    `no_credentials`, not `connection_failed`."""
    # ensure cleared
    requests.delete(f"{API}/api/portal/settings/email",
                    headers=_hdr(admin_tok), timeout=15)
    r = requests.get(f"{API}/api/portal/admin/mail/inbox",
                     headers=_hdr(admin_tok), timeout=15)
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body, dict)
    assert body.get("reason") == "no_credentials"


# ============================================================
# Article SEO: cover_image_alt round-trip
# ============================================================
def test_article_cover_image_alt_persists(admin_tok: str):
    slug = f"seo-alt-test-{int(time.time())}"
    payload = {
        "title": "SEO Alt Test",
        "slug": slug,
        "excerpt": "regression",
        "body_html": "<p>body</p>",
        "cover_image_url": "https://example.com/cover.jpg",
        "cover_image_alt": "Datacenter rack in Jakarta with Intercloud branding",
        "status": "draft",
    }
    r = requests.post(f"{API}/api/portal/admin/articles",
                      json=payload, headers=_hdr(admin_tok), timeout=15)
    assert r.status_code in (200, 201), r.text
    created = r.json()
    aid = created["id"]
    try:
        assert created.get("cover_image_alt") == payload["cover_image_alt"]
        # Round-trip via GET
        got = requests.get(f"{API}/api/portal/admin/articles/{aid}",
                           headers=_hdr(admin_tok), timeout=15).json()
        assert got.get("cover_image_alt") == payload["cover_image_alt"]
    finally:
        requests.delete(f"{API}/api/portal/admin/articles/{aid}",
                        headers=_hdr(admin_tok), timeout=15)


# ============================================================
# Favicon + apple-touch-icon are served
# ============================================================
def test_favicon_svg_served():
    r = requests.get(f"{API}/favicon.svg", timeout=15)
    assert r.status_code == 200
    ct = r.headers.get("content-type", "")
    assert "svg" in ct or "xml" in ct, f"unexpected content-type: {ct}"
    assert b"<svg" in r.content[:200]


def test_apple_touch_icon_served():
    r = requests.get(f"{API}/apple-touch-icon.svg", timeout=15)
    assert r.status_code == 200
    assert b"<svg" in r.content[:200]
