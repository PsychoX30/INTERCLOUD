"""End-to-end backend tests for Intercloud Portal.

Covers: auth (5 roles), RBAC (support/sales), client happy path, admin CRUD
(invoices, quotations, products, orders, integrations, mail), traffic report.
"""
import os
import pytest
import requests
from typing import Dict

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://cloud-services-id.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api/portal"

# ------- credentials (from /app/memory/test_credentials.md) -------
CREDS = {
    "admin":       ("admin@intercloud-digital.com", "AdminIntercloud2026!"),
    "client":      ("demo@client.com",              "ClientDemo2026!"),
    "sales":       ("sales@intercloud-digital.com", "Sales2026!"),
    "support":     ("support@intercloud-digital.com","Support2026!"),
    "ticket_only": ("ticket@intercloud-digital.com","Ticket2026!"),
}


# ---------------------------------------------------------------- session helpers
def _login(email: str, password: str) -> Dict:
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=15)
    assert r.status_code == 200, f"Login failed for {email}: {r.status_code} {r.text}"
    return r.json()


@pytest.fixture(scope="session")
def tokens() -> Dict[str, str]:
    out = {}
    users = {}
    for role, (e, p) in CREDS.items():
        j = _login(e, p)
        out[role] = j["token"]
        users[role] = j["user"]
    out["_users"] = users
    return out


def _h(tok: str) -> Dict:
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


# ============================================================ AUTH & IDENTITY
class TestAuth:
    def test_admin_login(self, tokens):
        u = tokens["_users"]["admin"]
        assert u["role"] == "admin"
        assert u["email"] == CREDS["admin"][0]

    def test_client_login_billing_emails(self, tokens):
        u = tokens["_users"]["client"]
        assert u["role"] == "client"
        assert "finance@contoh-digital.co.id" in u.get("billing_emails", [])

    def test_sales_login(self, tokens):
        u = tokens["_users"]["sales"]
        assert u["role"] == "sales"
        # sales must be assigned to at least one client
        assert len(u.get("assigned_client_ids", [])) >= 1

    def test_support_login(self, tokens):
        assert tokens["_users"]["support"]["role"] == "support"

    def test_ticket_only_login(self, tokens):
        assert tokens["_users"]["ticket_only"]["role"] == "ticket_only"

    def test_bad_credentials(self):
        r = requests.post(f"{API}/auth/login", json={"email": "admin@intercloud-digital.com", "password": "wrong"})
        assert r.status_code == 401


# ============================================================ RBAC
class TestRBAC:
    def test_support_dashboard_no_finance(self, tokens):
        r = requests.get(f"{API}/admin/dashboard", headers=_h(tokens["support"]))
        assert r.status_code == 200
        body = r.json()
        assert body["role"] == "support"
        stats = body["stats"]
        # allowed keys
        for k in ("active_services", "open_tickets", "total_clients"):
            assert k in stats, f"Support dashboard missing {k}"
        # forbidden keys
        for k in ("revenue_month", "revenue_total", "overdue_total", "unpaid_invoices", "overdue_invoices", "pending_orders"):
            assert k not in stats, f"Support MUST NOT see {k}"

    def test_admin_dashboard_has_finance(self, tokens):
        r = requests.get(f"{API}/admin/dashboard", headers=_h(tokens["admin"]))
        assert r.status_code == 200
        stats = r.json()["stats"]
        for k in ("revenue_month", "revenue_total", "overdue_total"):
            assert k in stats

    def test_finance_summary_denied_for_support(self, tokens):
        r = requests.get(f"{API}/admin/finance/summary", headers=_h(tokens["support"]))
        assert r.status_code == 403

    def test_finance_summary_ok_for_admin(self, tokens):
        r = requests.get(f"{API}/admin/finance/summary", headers=_h(tokens["admin"]))
        assert r.status_code == 200
        body = r.json()
        for k in ("total_revenue", "outstanding", "paid_invoices", "monthly_series"):
            assert k in body

    def test_sales_users_only_assigned(self, tokens):
        r = requests.get(f"{API}/admin/users", headers=_h(tokens["sales"]))
        assert r.status_code == 200
        users = r.json()
        # sales sees only their assigned clients — expect exactly 1 (demo client)
        assert len(users) == 1, f"Sales must see only assigned clients, got {len(users)}"
        assert users[0]["email"] == CREDS["client"][0]

    def test_admin_users_full(self, tokens):
        r = requests.get(f"{API}/admin/users", headers=_h(tokens["admin"]))
        assert r.status_code == 200
        assert len(r.json()) >= 5


# ============================================================ CLIENT
class TestClient:
    def test_client_dashboard(self, tokens):
        r = requests.get(f"{API}/client/dashboard", headers=_h(tokens["client"]))
        assert r.status_code == 200
        s = r.json()["stats"]
        assert s["overdue_invoices"] >= 1
        assert s["overdue_total"] >= 1665000  # seed overdue = 1_665_000; may grow via tests
        assert s["active_services"] >= 3  # seed=3, may grow via order lifecycle tests
        assert s["open_tickets"] >= 1

    def test_client_invoices(self, tokens):
        r = requests.get(f"{API}/client/invoices", headers=_h(tokens["client"]))
        assert r.status_code == 200
        invs = r.json()
        assert len(invs) >= 3  # 3 seeded; more if prior test runs created some
        statuses = {i["status"] for i in invs}
        assert "overdue" in statuses
        assert "unpaid" in statuses
        assert "paid" in statuses

    def test_client_services(self, tokens):
        r = requests.get(f"{API}/client/services", headers=_h(tokens["client"]))
        assert r.status_code == 200
        svcs = r.json()
        assert len(svcs) >= 3
        cats = {s["category"] for s in svcs}
        # Expect VPS, Hosting, Colocation
        assert cats.intersection({"vps", "hosting", "colocation"}) == {"vps", "hosting", "colocation"}

    def test_traffic_report(self, tokens):
        svcs = requests.get(f"{API}/client/services", headers=_h(tokens["client"])).json()
        sid = svcs[0]["id"]
        r = requests.get(f"{API}/client/services/{sid}/traffic", headers=_h(tokens["client"]))
        assert r.status_code == 200
        j = r.json()
        assert len(j["points"]) == 24
        assert "in_gb" in j["totals"] and "out_gb" in j["totals"]
        assert j["peak_in_mbps"] > 0

    def test_orders_roundtrip(self, tokens):
        # get a product id
        prods = requests.get(f"{API}/admin/products", headers=_h(tokens["admin"])).json()
        pid = prods[0]["id"]
        payload = {"product_id": pid, "notes": "TEST_order", "config": {"foo": "bar"}}
        c = requests.post(f"{API}/client/orders", headers=_h(tokens["client"]), json=payload)
        assert c.status_code == 200, c.text
        oid = c.json()["id"]
        g = requests.get(f"{API}/client/orders", headers=_h(tokens["client"]))
        assert g.status_code == 200
        assert any(o["id"] == oid for o in g.json())

    def test_ticket_flow(self, tokens):
        payload = {"subject": "TEST_ticket", "department": "technical", "priority": "medium", "message": "hello"}
        c = requests.post(f"{API}/client/tickets", headers=_h(tokens["client"]), json=payload)
        assert c.status_code == 200
        tid = c.json()["id"]
        # reply
        r = requests.post(f"{API}/client/tickets/{tid}/replies", headers=_h(tokens["client"]),
                          json={"message": "follow up"})
        assert r.status_code == 200
        assert r.json()["status"] == "awaiting_staff"

    def test_billing_emails_update(self, tokens):
        # get current
        g = requests.get(f"{API}/client/billing-emails", headers=_h(tokens["client"])).json()
        original = g["billing_emails"]
        new_list = original + ["test_extra@contoh-digital.co.id"]
        p = requests.put(f"{API}/client/billing-emails", headers=_h(tokens["client"]),
                         json={"billing_emails": new_list})
        assert p.status_code == 200
        assert "test_extra@contoh-digital.co.id" in [e.lower() for e in p.json()["billing_emails"]]
        # restore
        requests.put(f"{API}/client/billing-emails", headers=_h(tokens["client"]),
                     json={"billing_emails": original})


# ============================================================ ADMIN CRUD
class TestAdminInvoices:
    def test_create_and_pay(self, tokens):
        # find client user id
        users = requests.get(f"{API}/admin/users", headers=_h(tokens["admin"])).json()
        client = next(u for u in users if u["email"] == CREDS["client"][0])
        payload = {
            "user_id": client["id"],
            "items": [{"description": "TEST item", "qty": 1, "unit_price": 100000, "total": 100000}],
            "tax_percent": 11,
            "due_date": "2026-12-31",
            "notes": "TEST_invoice",
        }
        c = requests.post(f"{API}/admin/invoices", headers=_h(tokens["admin"]), json=payload)
        assert c.status_code == 200, c.text
        inv = c.json()
        assert inv["status"] == "unpaid"
        assert inv["total"] == 111000
        # mark paid
        p = requests.put(f"{API}/admin/invoices/{inv['id']}/status", headers=_h(tokens["admin"]),
                         json={"status": "paid", "payment_method": "bank_transfer"})
        assert p.status_code == 200
        assert p.json()["status"] == "paid"
        assert p.json()["paid_at"]


class TestAdminQuotations:
    def test_lifecycle(self, tokens):
        users = requests.get(f"{API}/admin/users", headers=_h(tokens["admin"])).json()
        client = next(u for u in users if u["email"] == CREDS["client"][0])
        payload = {
            "user_id": client["id"],
            "items": [{"description": "TEST quote", "qty": 1, "unit_price": 500000, "total": 500000}],
            "tax_percent": 11,
            "valid_until": "2026-12-31",
        }
        c = requests.post(f"{API}/admin/quotations", headers=_h(tokens["admin"]), json=payload)
        assert c.status_code == 200
        qid = c.json()["id"]
        assert c.json()["status"] == "draft"
        for s in ["sent", "accepted"]:
            r = requests.put(f"{API}/admin/quotations/{qid}/status", headers=_h(tokens["admin"]),
                             json={"status": s})
            assert r.status_code == 200
            assert r.json()["status"] == s


class TestAdminProducts:
    def test_crud(self, tokens):
        payload = {"name": "TEST_Product", "category": "vps", "description": "test", "price_monthly": 100000}
        c = requests.post(f"{API}/admin/products", headers=_h(tokens["admin"]), json=payload)
        assert c.status_code == 200
        pid = c.json()["id"]
        payload["name"] = "TEST_Product_Updated"
        u = requests.put(f"{API}/admin/products/{pid}", headers=_h(tokens["admin"]), json=payload)
        assert u.status_code == 200
        assert u.json()["name"] == "TEST_Product_Updated"
        d = requests.delete(f"{API}/admin/products/{pid}", headers=_h(tokens["admin"]))
        assert d.status_code == 200


class TestAdminOrders:
    def test_lifecycle_auto_creates_service(self, tokens):
        # create fresh order from client
        prods = requests.get(f"{API}/admin/products", headers=_h(tokens["admin"])).json()
        pid = prods[0]["id"]
        o = requests.post(f"{API}/client/orders", headers=_h(tokens["client"]),
                          json={"product_id": pid, "notes": "TEST_lifecycle", "config": {}})
        oid = o.json()["id"]
        # baseline service count
        before = len(requests.get(f"{API}/admin/services", headers=_h(tokens["admin"])).json())
        for status in ["assigned", "provisioning", "active"]:
            r = requests.put(f"{API}/admin/orders/{oid}/status", headers=_h(tokens["admin"]),
                             json={"status": status})
            assert r.status_code == 200
            assert r.json()["status"] == status
        after = len(requests.get(f"{API}/admin/services", headers=_h(tokens["admin"])).json())
        assert after == before + 1, "'active' must auto-create a service"


# ============================================================ INTEGRATIONS
class TestIntegrations:
    def test_modules_registry(self, tokens):
        r = requests.get(f"{API}/admin/integrations/modules", headers=_h(tokens["admin"]))
        assert r.status_code == 200
        modules = r.json()
        keys = {m["key"] for m in modules}
        expected = {"cpanel","plesk","proxmox","mikrotik","duitku","xendit","midtrans","smtp","whois","blacklist","dcim"}
        assert keys == expected, f"missing {expected - keys}, extra {keys - expected}"
        # every module has fields
        for m in modules:
            assert "fields" in m and len(m["fields"]) > 0

    def test_full_crud_and_test_connection(self, tokens):
        # CREATE cpanel with hostname + username + api_token
        payload = {
            "module": "cpanel",
            "name": "TEST_cpanel",
            "status": "disabled",
            "config": {
                "hostname": "whm.test.com", "port": 2087, "protocol": "https",
                "username": "root", "api_token": "SECRET_TOKEN_ABC",
            },
        }
        c = requests.post(f"{API}/admin/integrations", headers=_h(tokens["admin"]), json=payload)
        assert c.status_code == 200
        iid = c.json()["id"]
        # LIST — password should be redacted
        listed = requests.get(f"{API}/admin/integrations", headers=_h(tokens["admin"])).json()
        this = next(x for x in listed if x["id"] == iid)
        assert this["config"]["api_token"] == "••••••••"
        assert this["config"]["hostname"] == "whm.test.com"
        # UPDATE — send placeholder password should NOT overwrite
        upd = {
            "name": "TEST_cpanel_updated", "status": "enabled",
            "config": {**this["config"], "hostname": "whm2.test.com"},
        }
        u = requests.put(f"{API}/admin/integrations/{iid}", headers=_h(tokens["admin"]), json=upd)
        assert u.status_code == 200
        assert u.json()["status"] == "enabled"
        assert u.json()["config"]["hostname"] == "whm2.test.com"
        # TEST
        t = requests.post(f"{API}/admin/integrations/{iid}/test", headers=_h(tokens["admin"]))
        assert t.status_code == 200
        body = t.json()
        assert body["ok"] is True
        assert "latency_ms" in body
        # DELETE
        d = requests.delete(f"{API}/admin/integrations/{iid}", headers=_h(tokens["admin"]))
        assert d.status_code == 200
        assert d.json()["deleted"] == 1

    def test_test_config_missing_required(self, tokens):
        r = requests.post(f"{API}/admin/integrations/test-config", headers=_h(tokens["admin"]),
                          json={"module": "mikrotik", "config": {"hostname": "1.2.3.4"}})
        assert r.status_code == 200
        j = r.json()
        assert j["ok"] is False
        assert "Missing required" in j["message"]


# ============================================================ WEBMAIL
class TestMail:
    def test_inbox_seed(self, tokens):
        r = requests.get(f"{API}/admin/mail/inbox", headers=_h(tokens["admin"]))
        assert r.status_code == 200
        msgs = r.json()
        assert len(msgs) >= 4

    def test_read_and_send(self, tokens):
        inbox = requests.get(f"{API}/admin/mail/inbox", headers=_h(tokens["admin"])).json()
        # find an unread message (if any left after prior runs)
        target = next((m for m in inbox if m["unread"]), inbox[0])
        r = requests.get(f"{API}/admin/mail/messages/{target['id']}", headers=_h(tokens["admin"]))
        assert r.status_code == 200
        # verify unread flag flipped
        inbox2 = requests.get(f"{API}/admin/mail/inbox", headers=_h(tokens["admin"])).json()
        this = next(m for m in inbox2 if m["id"] == target["id"])
        assert this["unread"] is False

        s = requests.post(f"{API}/admin/mail/send", headers=_h(tokens["admin"]),
                          json={"to": "test@example.com", "subject": "TEST subject", "body": "TEST body"})
        assert s.status_code == 200
        assert "delivered" in s.json()
        assert "delivered_via" in s.json()
        # sent list
        sent = requests.get(f"{API}/admin/mail/sent", headers=_h(tokens["admin"])).json()
        assert any(m["subject"] == "TEST subject" for m in sent)


# ============================================================ PAYMENT INFO
class TestPaymentInfo:
    def test_client_payment_info(self, tokens):
        r = requests.get(f"{API}/client/payment-info", headers=_h(tokens["client"]))
        assert r.status_code == 200
        j = r.json()
        assert isinstance(j["bank_accounts"], list) and len(j["bank_accounts"]) >= 2
        accts = {b["bank"]: b["number"] for b in j["bank_accounts"]}
        assert accts.get("MANDIRI") == "1240011911816"
        assert accts.get("BCA") == "4730862038"
        assert "duitku_enabled" in j
