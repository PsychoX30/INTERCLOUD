"""Verify the seed-version refresh: polite English, real Intercloud logo URL in preview."""
import os
import requests
import pytest

API = os.environ.get("PORTAL_API_BASE") or "http://localhost:8001/api/portal"
LOGO_URL_FRAGMENT = "intercloud-digital.com/wp-content/uploads/2024/07/Mask-group.png"


def _h(tok):
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture(scope="module")
def admin_token():
    r = requests.post(f"{API}/auth/login", json={
        "email": os.environ["ADMIN_EMAIL"], "password": os.environ["ADMIN_PASSWORD"]})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def test_welcome_subject_uses_new_wording(admin_token):
    r = requests.get(f"{API}/admin/email-templates", headers=_h(admin_token))
    assert r.status_code == 200
    tpl = next(t for t in r.json() if t["event_key"] == "welcome")
    subj = tpl["subject"]
    assert "Welcome to Intercloud" in subj, f"unexpected subject: {subj}"
    # Body should be polite
    body = tpl["body_html"]
    assert ("Warm regards" in body) or ("Kind regards" in body), \
        f"welcome body not polite: first 200 chars: {body[:200]}"


def test_invoice_generated_subject_includes_due_date(admin_token):
    r = requests.get(f"{API}/admin/email-templates", headers=_h(admin_token))
    tpl = next(t for t in r.json() if t["event_key"] == "invoice_generated")
    assert "due {invoice.due_date}" in tpl["subject"] or "due {{invoice.due_date}}" in tpl["subject"], \
        f"invoice_generated subject: {tpl['subject']}"


def test_preview_body_includes_intercloud_logo_url(admin_token):
    r = requests.get(f"{API}/admin/email-templates", headers=_h(admin_token))
    tpl = next(t for t in r.json() if t["event_key"] == "welcome")
    r2 = requests.post(f"{API}/admin/email-templates/preview",
                       headers=_h(admin_token), json={"template_id": tpl["id"]})
    assert r2.status_code == 200
    body = r2.json()["body_html"]
    assert LOGO_URL_FRAGMENT in body, f"logo URL not embedded in preview. body[:400]={body[:400]}"
    # Old "IC" placeholder should not be there
    assert ">IC<" not in body, "old IC placeholder still present"


def test_all_system_templates_preview_have_logo(admin_token):
    r = requests.get(f"{API}/admin/email-templates", headers=_h(admin_token))
    system_events = [t for t in r.json() if t.get("is_system")]
    assert len(system_events) >= 10
    for tpl in system_events:
        r2 = requests.post(f"{API}/admin/email-templates/preview",
                           headers=_h(admin_token), json={"template_id": tpl["id"]})
        assert r2.status_code == 200, f"preview failed for {tpl['event_key']}"
        assert LOGO_URL_FRAGMENT in r2.json()["body_html"], \
            f"logo missing in preview for {tpl['event_key']}"
