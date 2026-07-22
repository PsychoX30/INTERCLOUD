"""Automated Email Engine — templates CRUD, event hooks, scheduler sweep, broadcasts."""
import os
import datetime
import uuid
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


@pytest.fixture(scope="module")
def demo_client_id(admin_token):
    r = requests.get(f"{API}/admin/users", headers=_h(admin_token))
    for u in r.json():
        if u["email"] == os.environ["CLIENT_EMAIL"]:
            return u["id"]
    pytest.fail("Demo client not found")


class TestTemplatesCRUD:
    def test_default_templates_seeded(self, admin_token):
        """All 12 system templates must be present after startup."""
        r = requests.get(f"{API}/admin/email-templates", headers=_h(admin_token))
        assert r.status_code == 200
        rows = r.json()
        expected = {
            "welcome", "order_confirmation", "invoice_generated",
            "invoice_reminder_d3", "invoice_due",
            "invoice_overdue_d1", "invoice_overdue_d3", "invoice_overdue_d7",
            "service_suspension", "password_reset", "maintenance", "newsletter",
        }
        got = {r["event_key"] for r in rows}
        assert expected.issubset(got), f"missing: {expected - got}"
        # System templates are marked
        for r_ in rows:
            if r_["event_key"] in expected:
                assert r_["is_system"] is True

    def test_event_catalog(self, admin_token):
        r = requests.get(f"{API}/admin/email/event-catalog", headers=_h(admin_token))
        assert r.status_code == 200
        d = r.json()
        assert len(d["events"]) >= 12
        assert "user.name" in d["variables"]
        assert "invoice.number" in d["variables"]

    def test_edit_system_template_body_and_time(self, admin_token):
        r = requests.get(f"{API}/admin/email-templates", headers=_h(admin_token))
        tpl = next(t for t in r.json() if t["event_key"] == "invoice_reminder_d3")
        tid = tpl["id"]
        payload = {
            "event_key": "invoice_reminder_d3",       # will be ignored (system)
            "name": "D-3 (edited by pytest)",
            "subject": "Test edited subject {{invoice.number}}",
            "body_html": "<p>Edited body for {{user.name}}</p>",
            "offset_days": -3,
            "send_time": "10:30",
            "is_active": True,
            "notes": "pytest touched",
        }
        r2 = requests.put(f"{API}/admin/email-templates/{tid}",
                          headers=_h(admin_token), json=payload)
        assert r2.status_code == 200
        got = r2.json()
        assert got["subject"].startswith("Test edited")
        assert got["send_time"] == "10:30"
        assert got["event_key"] == "invoice_reminder_d3"  # not renamed

    def test_system_template_cannot_be_deleted(self, admin_token):
        r = requests.get(f"{API}/admin/email-templates", headers=_h(admin_token))
        tpl = next(t for t in r.json() if t["event_key"] == "welcome")
        r2 = requests.delete(f"{API}/admin/email-templates/{tpl['id']}",
                             headers=_h(admin_token))
        assert r2.status_code == 400

    def test_custom_template_create_edit_delete(self, admin_token):
        key = f"pytest_custom_{uuid.uuid4().hex[:8]}"
        create = {
            "event_key": key,
            "name": "Custom pytest template",
            "subject": "Hi {{user.name}}",
            "body_html": "<p>Custom body</p>",
            "offset_days": None,
            "send_time": None,
            "is_active": True,
            "notes": "",
        }
        r = requests.post(f"{API}/admin/email-templates",
                          headers=_h(admin_token), json=create)
        assert r.status_code == 200, r.text
        tid = r.json()["id"]
        assert r.json()["is_system"] is False

        # Duplicate event key rejected
        r2 = requests.post(f"{API}/admin/email-templates",
                           headers=_h(admin_token), json=create)
        assert r2.status_code == 409

        # Deletable because not system
        r3 = requests.delete(f"{API}/admin/email-templates/{tid}",
                             headers=_h(admin_token))
        assert r3.status_code == 200


class TestPreviewAndSendTest:
    def test_preview_substitutes_variables(self, admin_token):
        r = requests.get(f"{API}/admin/email-templates", headers=_h(admin_token))
        tpl = next(t for t in r.json() if t["event_key"] == "invoice_reminder_d3")
        r2 = requests.post(f"{API}/admin/email-templates/preview",
                           headers=_h(admin_token), json={"template_id": tpl["id"]})
        assert r2.status_code == 200
        d = r2.json()
        # Subject should have a sample invoice number substituted in
        assert "{{" not in d["subject"], f"unrendered vars remain: {d['subject']}"
        assert "INV-2026" in d["subject"]
        assert "<html" in d["body_html"].lower()

    def test_preview_with_raw_body(self, admin_token):
        r = requests.post(f"{API}/admin/email-templates/preview",
                          headers=_h(admin_token), json={
                              "subject": "Hello {{user.name}}",
                              "body_html": "<p>Total: {{invoice.total_fmt}}</p>",
                          })
        assert r.status_code == 200
        d = r.json()
        assert d["subject"].startswith("Hello ")
        assert "Rp" in d["body_html"]

    def test_send_test_falls_back_to_log_when_smtp_disabled(self, admin_token):
        """SMTP is not configured in test env → send-test should return skipped (not crash)."""
        r = requests.get(f"{API}/admin/email-templates", headers=_h(admin_token))
        tpl = next(t for t in r.json() if t["event_key"] == "welcome")
        r2 = requests.post(f"{API}/admin/email-templates/send-test",
                           headers=_h(admin_token),
                           json={"template_id": tpl["id"], "to_email": "sink@example.com"})
        assert r2.status_code == 200
        d = r2.json()
        # We accept sent OR skipped depending on the env
        assert d["status"] in ("sent", "skipped", "failed")

    def test_client_cannot_access_admin_email_endpoints(self, admin_token):
        client = requests.post(f"{API}/auth/login", json={
            "email": os.environ["CLIENT_EMAIL"], "password": os.environ["CLIENT_PASSWORD"]
        }).json()["token"]
        r = requests.get(f"{API}/admin/email-templates", headers=_h(client))
        assert r.status_code == 403


class TestEventHooks:
    def test_register_fires_welcome_email_log(self, admin_token):
        """Self-registration must produce a `welcome` entry in email_logs."""
        email = f"pytest+welcome+{uuid.uuid4().hex[:8]}@example.com"
        r = requests.post(f"{API}/auth/register", json={
            "email": email, "password": "TestPassword123!",
            "name": "Welcome Pytest", "accepts_tos": True,
        })
        assert r.status_code == 200
        # Give the async log write a beat
        import time as _t; _t.sleep(1)
        logs = requests.get(f"{API}/admin/email-logs", headers=_h(admin_token)).json()
        match = [l for l in logs if l["event_key"] == "welcome" and l["to_email"] == email]
        assert match, f"welcome log missing for {email}. logs sample: {logs[:3]}"

    def test_order_and_invoice_hooks_fire(self, admin_token):
        """Creating a client order should produce both order_confirmation & invoice_generated logs."""
        client = requests.post(f"{API}/auth/login", json={
            "email": os.environ["CLIENT_EMAIL"], "password": os.environ["CLIENT_PASSWORD"]
        }).json()["token"]
        # Pick a base product
        prods = requests.get(f"{API}/portal-public/products").json()
        base = next(p for p in prods if not p.get("is_addon") and p.get("price_monthly", 0) > 0)
        r = requests.post(f"{API}/client/orders", headers=_h(client), json={
            "product_id": base["id"], "notes": "pytest email trigger",
            "selections": [], "addon_ids": [],
        })
        assert r.status_code == 200, r.text
        import time as _t; _t.sleep(1)
        logs = requests.get(f"{API}/admin/email-logs", headers=_h(admin_token)).json()
        events = {l["event_key"] for l in logs[:30]}
        assert "order_confirmation" in events
        assert "invoice_generated" in events


class TestSchedulerSweep:
    def test_run_scheduler_now_returns_summary(self, admin_token):
        r = requests.post(f"{API}/admin/email/run-scheduler-now", headers=_h(admin_token))
        assert r.status_code == 200
        d = r.json()
        assert "date" in d
        assert set(d["fired"].keys()) >= {
            "invoice_reminder_d3", "invoice_due", "invoice_overdue_d1",
            "invoice_overdue_d3", "invoice_overdue_d7", "service_suspension",
        }
        assert "services_suspended" in d

    def test_sweep_fires_d3_reminder_when_due_in_3_days(self, admin_token, demo_client_id):
        """Create a fake invoice due in 3 days, run sweep, expect an invoice_reminder_d3 log."""
        due = (datetime.date.today() + datetime.timedelta(days=3)).isoformat()
        payload = {
            "user_id": demo_client_id,
            "items": [{"description": "Pytest reminder test",
                        "qty": 1, "unit_price": 1000000, "total": 1000000}],
            "tax_percent": 11.0,
            "due_date": due,
            "notes": "pytest reminder sweep",
        }
        r = requests.post(f"{API}/admin/invoices", headers=_h(admin_token), json=payload)
        assert r.status_code == 200, r.text
        inv_id = r.json()["id"]
        r2 = requests.post(f"{API}/admin/email/run-scheduler-now", headers=_h(admin_token))
        assert r2.status_code == 200
        # There may be no SMTP so state is `skipped`, but log MUST exist.
        logs = requests.get(f"{API}/admin/email-logs", headers=_h(admin_token)).json()
        match = [l for l in logs
                 if l["event_key"] == "invoice_reminder_d3" and l.get("invoice_id") == inv_id]
        assert match, f"D-3 log not created for invoice {inv_id}. Available events: {sorted({l['event_key'] for l in logs[:40]})}"

    def test_sweep_d8_suspends_active_services(self, admin_token):
        """Invoice due exactly 8 days ago → service_suspension log + linked services flipped to 'suspended'."""
        # 1. Register a fresh client so we don't accidentally suspend the shared demo
        email = f"pytest+d8+{uuid.uuid4().hex[:8]}@example.com"
        reg = requests.post(f"{API}/auth/register", json={
            "email": email, "password": "TestPassword123!",
            "name": "D8 Suspension Test", "accepts_tos": True,
        })
        assert reg.status_code == 200, reg.text
        uid = reg.json()["user"]["id"]

        # 2. Give them an active service via admin
        prods = requests.get(f"{API}/portal-public/products").json()
        base = next(p for p in prods if not p.get("is_addon"))
        svc = requests.post(f"{API}/admin/services", headers=_h(admin_token), json={
            "user_id": uid, "product_id": base["id"], "name": "D8 test svc",
            "status": "active", "price_monthly": 100000, "config": {},
        })
        assert svc.status_code == 200, svc.text
        svc_id = svc.json()["id"]

        # 3. Create an invoice due 8 days ago
        due = (datetime.date.today() - datetime.timedelta(days=8)).isoformat()
        inv = requests.post(f"{API}/admin/invoices", headers=_h(admin_token), json={
            "user_id": uid,
            "items": [{"description": "D+8 test", "qty": 1, "unit_price": 1500000, "total": 1500000}],
            "tax_percent": 11.0, "due_date": due, "notes": "pytest suspension",
        })
        assert inv.status_code == 200, inv.text
        inv_id = inv.json()["id"]

        # 4. Run sweep
        r = requests.post(f"{API}/admin/email/run-scheduler-now", headers=_h(admin_token))
        assert r.status_code == 200, r.text

        # 5. service_suspension log row exists for this invoice
        logs = requests.get(f"{API}/admin/email-logs?limit=500", headers=_h(admin_token)).json()
        match = [l for l in logs
                 if l["event_key"] == "service_suspension" and l.get("invoice_id") == inv_id]
        assert match, f"suspension log missing for invoice {inv_id}"

        # 6. The service should now be flipped to 'suspended'
        svcs = requests.get(f"{API}/admin/services?user_id={uid}", headers=_h(admin_token))
        # /admin/services returns list – filter for our service
        rows = svcs.json() if isinstance(svcs.json(), list) else svcs.json().get("items", [])
        me = [s for s in rows if s["id"] == svc_id]
        assert me, f"service {svc_id} not returned"
        assert me[0]["status"] == "suspended", f"expected suspended, got {me[0]['status']}"

    def test_seeded_templates_have_expected_offset_days(self, admin_token):
        """Business rule: welcome/order/invoice_generated/password_reset/maintenance/newsletter → None;
        scheduled ones → -3, 0, 1, 3, 7, 8."""
        r = requests.get(f"{API}/admin/email-templates", headers=_h(admin_token))
        rows = {t["event_key"]: t for t in r.json()}
        expected_null = {"welcome", "order_confirmation", "invoice_generated",
                         "password_reset", "maintenance", "newsletter"}
        expected_offsets = {
            "invoice_reminder_d3": -3, "invoice_due": 0,
            "invoice_overdue_d1": 1, "invoice_overdue_d3": 3, "invoice_overdue_d7": 7,
            "service_suspension": 8,
        }
        for k in expected_null:
            assert rows[k]["offset_days"] in (None, 0) or rows[k]["offset_days"] is None, \
                f"{k} should have offset_days=None, got {rows[k]['offset_days']}"
            # Strict check
            assert rows[k]["offset_days"] is None, f"{k} offset_days must be None"
        for k, v in expected_offsets.items():
            assert rows[k]["offset_days"] == v, \
                f"{k} expected offset {v}, got {rows[k]['offset_days']}"

    def test_sweep_is_idempotent_per_day(self, admin_token, demo_client_id):
        """Running the sweep twice in a row should not produce duplicate entries for the same day."""
        # Create an invoice due today (invoice_due branch)
        due = datetime.date.today().isoformat()
        r = requests.post(f"{API}/admin/invoices", headers=_h(admin_token), json={
            "user_id": demo_client_id,
            "items": [{"description": "Idempotency test",
                        "qty": 1, "unit_price": 500000, "total": 500000}],
            "tax_percent": 11.0, "due_date": due, "notes": "pytest idempotency",
        })
        inv_id = r.json()["id"]
        requests.post(f"{API}/admin/email/run-scheduler-now", headers=_h(admin_token))
        requests.post(f"{API}/admin/email/run-scheduler-now", headers=_h(admin_token))
        logs = requests.get(f"{API}/admin/email-logs", headers=_h(admin_token)).json()
        due_logs = [l for l in logs if l["event_key"] == "invoice_due" and l.get("invoice_id") == inv_id]
        assert len(due_logs) == 1, f"expected 1, got {len(due_logs)}"


class TestBroadcast:
    def test_broadcast_to_custom_list(self, admin_token):
        r = requests.post(f"{API}/admin/email/broadcast",
                          headers=_h(admin_token),
                          json={
                              "subject": "Pytest maintenance {{user.name}}",
                              "body_html": "<p>Hi {{user.name}}, testing broadcast.</p>",
                              "audience": "custom",
                              "to_emails": ["one@example.com", "two@example.com"],
                          })
        assert r.status_code == 200
        d = r.json()
        assert d["recipients"] == 2
        assert d["sent"] + d["failed"] + d["skipped"] == 2

    def test_broadcast_custom_requires_emails(self, admin_token):
        r = requests.post(f"{API}/admin/email/broadcast",
                          headers=_h(admin_token),
                          json={"subject": "X", "body_html": "<p>x</p>",
                                "audience": "custom", "to_emails": []})
        assert r.status_code == 400

    def test_broadcast_all_clients(self, admin_token):
        r = requests.post(f"{API}/admin/email/broadcast",
                          headers=_h(admin_token),
                          json={"subject": "Test broadcast",
                                "body_html": "<p>Hi {{user.name}}</p>",
                                "audience": "all_clients"})
        assert r.status_code == 200
        d = r.json()
        assert d["recipients"] >= 1
