"""PDF/HTML document rendering tests for /documents/invoice and /documents/quotation."""
import os
import re
import pytest
import requests

API = os.environ.get("PORTAL_API_BASE") or "http://localhost:8001/api/portal"


def _login(email: str, password: str) -> str:
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password})
    r.raise_for_status()
    return r.json()["token"]


@pytest.fixture(scope="module")
def tokens():
    return {
        "admin": _login(os.environ["ADMIN_EMAIL"], os.environ["ADMIN_PASSWORD"]),
        "client": _login(os.environ["CLIENT_EMAIL"], os.environ["CLIENT_PASSWORD"]),
    }


def _h(t: str) -> dict:
    return {"Authorization": f"Bearer {t}"}


class TestInvoicePdf:
    def test_client_can_view_own_invoice_html(self, tokens):
        invs = requests.get(f"{API}/client/invoices", headers=_h(tokens["client"])).json()
        assert len(invs) >= 1
        iid = invs[0]["id"]
        r = requests.get(f"{API}/documents/invoice/{iid}?token={tokens['client']}")
        assert r.status_code == 200
        assert "text/html" in r.headers.get("content-type", "")
        # Reference layout markers
        html = r.text
        assert "PT. INTERCLOUD DIGITAL INOVASI" in html
        assert "NPWP" in html
        assert "Invoiced To" in html
        assert "Sub Total" in html
        assert "Credit" in html
        assert "PDF Generated on" in html

    def test_client_pdf_download(self, tokens):
        invs = requests.get(f"{API}/client/invoices", headers=_h(tokens["client"])).json()
        iid = invs[0]["id"]
        r = requests.get(f"{API}/documents/invoice/{iid}?format=pdf&token={tokens['client']}")
        assert r.status_code == 200
        assert r.headers.get("content-type") == "application/pdf"
        # Every valid PDF starts with %PDF-
        assert r.content[:5] == b"%PDF-"
        assert len(r.content) > 3000  # non-trivial file
        cd = r.headers.get("content-disposition", "")
        assert "Invoice-" in cd and cd.endswith('.pdf"')

    def test_paid_invoice_has_transactions_table(self, tokens):
        invs = requests.get(f"{API}/admin/invoices", headers=_h(tokens["admin"])).json()
        paid = next((i for i in invs if i["status"] == "paid"), None)
        assert paid is not None
        r = requests.get(f"{API}/documents/invoice/{paid['id']}?token={tokens['admin']}")
        html = r.text
        # PAID ribbon
        assert re.search(r">PAID<", html)
        # Transactions section shown
        assert "Transactions" in html
        assert "Balance" in html
        # No bank block (bank block only for unpaid/overdue)
        assert "Payment — Bank Transfer" not in html

    def test_unpaid_invoice_shows_bank_transfer_panel(self, tokens):
        invs = requests.get(f"{API}/admin/invoices", headers=_h(tokens["admin"])).json()
        unpaid = next((i for i in invs if i["status"] == "unpaid"), None)
        assert unpaid is not None
        r = requests.get(f"{API}/documents/invoice/{unpaid['id']}?token={tokens['admin']}")
        html = r.text
        assert re.search(r">UNPAID<", html)
        assert "Payment — Bank Transfer" in html
        assert "1240011911816" in html   # MANDIRI
        assert "4730862038" in html      # BCA

    def test_client_cannot_read_others_invoice(self, tokens):
        # Client invoice list is their own; verify 403 on a totally random id
        r = requests.get(f"{API}/documents/invoice/000000000000000000000000?token={tokens['client']}")
        # Either 404 (id doesn't exist) or 403 (belongs to someone else) is acceptable — never 200
        assert r.status_code in (403, 404)


class TestQuotationPdf:
    def test_quotation_pdf_when_available(self, tokens):
        qs = requests.get(f"{API}/admin/quotations", headers=_h(tokens["admin"])).json()
        if not qs:
            pytest.skip("no quotations seeded")
        qid = qs[0]["id"]
        r = requests.get(f"{API}/documents/quotation/{qid}?format=pdf&token={tokens['admin']}")
        assert r.status_code == 200
        assert r.headers.get("content-type") == "application/pdf"
        assert r.content[:5] == b"%PDF-"

    def test_client_cannot_access_quotations(self, tokens):
        qs = requests.get(f"{API}/admin/quotations", headers=_h(tokens["admin"])).json()
        if not qs:
            pytest.skip("no quotations seeded")
        qid = qs[0]["id"]
        r = requests.get(f"{API}/documents/quotation/{qid}?token={tokens['client']}")
        assert r.status_code == 403


class TestUserAddressFields:
    def test_me_returns_address_fields(self, tokens):
        r = requests.get(f"{API}/auth/me", headers=_h(tokens["client"]))
        u = r.json()
        for k in ("attention", "address_line1", "city", "province", "postal_code", "country", "npwp"):
            assert k in u, f"missing {k}"
        # Seed backfill
        assert u["country"] == "Indonesia"
        assert u["city"] is not None
