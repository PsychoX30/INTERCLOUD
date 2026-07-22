"""Finance v2 tests: kas_kecil / salaries / sales_fees CRUD, month-lock, xlsx download."""
import os, time, datetime, requests, pytest

API = os.environ.get("PORTAL_API_BASE") or "http://localhost:8001/api/portal"


def _h(t): return {"Authorization": f"Bearer {t}"}


@pytest.fixture(scope="module")
def admin_token():
    r = requests.post(f"{API}/auth/login", json={
        "email": os.environ["ADMIN_EMAIL"], "password": os.environ["ADMIN_PASSWORD"]})
    return r.json()["token"]


CUR_MONTH_ISO = datetime.date.today().replace(day=1).isoformat()  # first of current month


class TestLedgers:
    def _create_and_delete(self, admin_token, kind, extra):
        payload = {"date": CUR_MONTH_ISO, "amount": 12345, **extra, "notes": "pytest"}
        r = requests.post(f"{API}/admin/{kind}", headers=_h(admin_token), json=payload)
        assert r.status_code == 200, r.text
        rid = r.json()["id"]
        assert r.json()["amount"] == 12345
        # Delete
        r2 = requests.delete(f"{API}/admin/{kind}/{rid}", headers=_h(admin_token))
        assert r2.status_code == 200 and r2.json()["deleted"] == 1

    def test_kas_kecil_crud(self, admin_token):
        self._create_and_delete(admin_token, "kas-kecil", {"category": "office", "vendor": "kopi"})

    def test_salaries_crud(self, admin_token):
        self._create_and_delete(admin_token, "salaries", {"employee": "test", "category": "NOC"})

    def test_sales_fees_crud(self, admin_token):
        self._create_and_delete(admin_token, "sales-fees", {"sales_person": "test", "invoice_number": "INV-X"})

    def test_prior_month_insert_rejected(self, admin_token):
        # 2 months ago is definitely locked
        prior = (datetime.date.today().replace(day=1) - datetime.timedelta(days=45)).isoformat()
        r = requests.post(f"{API}/admin/kas-kecil", headers=_h(admin_token),
                          json={"date": prior, "amount": 100, "notes": "should be blocked"})
        assert r.status_code == 403

    def test_client_cannot_write(self, admin_token):
        client = requests.post(f"{API}/auth/login", json={
            "email": os.environ["CLIENT_EMAIL"], "password": os.environ["CLIENT_PASSWORD"]}).json()["token"]
        r = requests.post(f"{API}/admin/kas-kecil", headers=_h(client),
                          json={"date": CUR_MONTH_ISO, "amount": 1})
        assert r.status_code == 403


class TestDetailedAndReports:
    def test_detailed_endpoint_shape(self, admin_token):
        r = requests.get(f"{API}/admin/finance/detailed", headers=_h(admin_token))
        assert r.status_code == 200
        d = r.json()
        for k in ("revenue_rows", "expenses_rows", "kas_kecil_rows", "salaries_rows",
                  "sales_fees_rows", "assets_rows", "totals"):
            assert k in d
        for k in ("revenue", "expenses_recurring", "kas_kecil", "salaries",
                  "sales_fees", "expenses_all", "depreciation_accumulated", "net_profit"):
            assert k in d["totals"]

    def test_monthly_xlsx_download(self, admin_token):
        period = CUR_MONTH_ISO[:7]
        r = requests.get(f"{API}/admin/finance/report/monthly/{period}", headers=_h(admin_token))
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("application/vnd.openxmlformats")
        # xlsx is a zip → starts with PK
        assert r.content[:2] == b"PK"
        assert len(r.content) > 3000
        assert f"Intercloud_Finance_{period}.xlsx" in r.headers.get("content-disposition", "")

    def test_annual_xlsx_download(self, admin_token):
        year = datetime.date.today().year
        r = requests.get(f"{API}/admin/finance/report/annual/{year}", headers=_h(admin_token))
        assert r.status_code == 200
        assert r.content[:2] == b"PK"

    def test_reports_audit_list(self, admin_token):
        # Both monthly + annual should now appear (created by previous tests)
        r = requests.get(f"{API}/admin/finance/reports", headers=_h(admin_token))
        assert r.status_code == 200
        rows = r.json()
        kinds = {r["kind"] for r in rows}
        assert "monthly" in kinds
        assert "annual" in kinds

    def test_annual_reports_stay_locked(self, admin_token):
        r = requests.get(f"{API}/admin/finance/reports", headers=_h(admin_token))
        annuals = [x for x in r.json() if x["kind"] == "annual"]
        for a in annuals:
            assert a["locked"] is True
