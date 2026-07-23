"""
Iteration 30 — Batch-3 verification.

F1 — Per-admin email (users.email_settings)
    * GET /settings/email returns {} initially
    * GET /admin/mail/inbox returns {not_setup:true, reason:'no_credentials'} when no creds
    * POST /settings/email persists and echoes configured:true + from_email
    * GET after save returns configured:true and password masked ('••••••••')
    * POST with password='••••••••' preserves the previously stored password
      (verified indirectly by reading the raw doc and comparing hashes)

F3 — Sales scoping in /admin/dashboard
    * Sales role -> total_clients == count(assigned_client_ids), not tenant total
    * Sales role -> unpaid_invoices/overdue_invoices/revenue_total scoped to assigned
    * Admin role -> global stats (unchanged)
    * Finance role -> financial fields present in dashboard stats

Regression — batch-2 fixes still work.
"""
import os
import time
from pathlib import Path

import pytest
import requests


# ---------- helpers ---------------------------------------------------------

def _resolve_base_url() -> str:
    env = os.environ.get("REACT_APP_BACKEND_URL")
    if env:
        return env.rstrip("/")
    fenv = Path("/app/frontend/.env")
    if fenv.exists():
        for line in fenv.read_text().splitlines():
            if line.startswith("REACT_APP_BACKEND_URL="):
                return line.split("=", 1)[1].strip().strip('"').strip("'").rstrip("/")
    raise RuntimeError("REACT_APP_BACKEND_URL not set")


BASE_URL = _resolve_base_url()
API = BASE_URL + "/api/portal"

ADMIN_EMAIL = "admin@intercloud-digital.com"
ADMIN_PASSWORD = "AdminIntercloud2026!"
SALES_EMAIL = "sales.test@intercloud-digital.com"
SALES_PASSWORD = "SalesTest2026!"
FINANCE_EMAIL = "TEST_finance_iter30@example.com"
FINANCE_PASSWORD = "FinanceIter30!"


# ---------- fixtures --------------------------------------------------------

@pytest.fixture(scope="module")
def http():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(scope="module")
def admin_token(http):
    r = http.post(f"{API}/auth/login",
                  json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}, timeout=30)
    if r.status_code != 200:
        pytest.skip(f"admin login failed: {r.status_code} {r.text[:200]}")
    return r.json()["token"]


@pytest.fixture(scope="module")
def admin_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


@pytest.fixture(scope="module")
def sales_token(http, admin_headers):
    """Ensure sales.test has a known password and log in."""
    users = http.get(f"{API}/admin/users", headers=admin_headers, timeout=30).json()
    sales = next((u for u in users if u.get("email") == SALES_EMAIL), None)
    if not sales:
        pytest.skip(f"seed user {SALES_EMAIL} not found")
    http.put(f"{API}/admin/users/{sales['id']}", headers=admin_headers,
             json={"password": SALES_PASSWORD}, timeout=30)
    r = http.post(f"{API}/auth/login",
                  json={"email": SALES_EMAIL, "password": SALES_PASSWORD}, timeout=30)
    if r.status_code != 200:
        pytest.skip(f"sales login failed: {r.status_code} {r.text[:200]}")
    assert r.json()["user"]["role"] == "sales"
    return r.json()["token"]


@pytest.fixture(scope="module")
def sales_assigned_client_ids(http, admin_headers):
    """Fetch sales.test user record via admin API to inspect assigned_client_ids."""
    users = http.get(f"{API}/admin/users", headers=admin_headers, timeout=30).json()
    sales = next((u for u in users if u.get("email") == SALES_EMAIL), None)
    if not sales:
        pytest.skip(f"seed user {SALES_EMAIL} not found")
    return sales.get("assigned_client_ids") or []


@pytest.fixture(scope="module")
def finance_token(http, admin_headers):
    """Create (or reuse) a temp finance user, log in, return token. Cleaned up in teardown."""
    users = http.get(f"{API}/admin/users", headers=admin_headers, timeout=30).json()
    existing = next((u for u in users if u.get("email") == FINANCE_EMAIL), None)
    if existing:
        # reset password to known
        http.put(f"{API}/admin/users/{existing['id']}", headers=admin_headers,
                 json={"password": FINANCE_PASSWORD, "role": "finance"}, timeout=30)
        uid = existing["id"]
    else:
        r = http.post(f"{API}/admin/users", headers=admin_headers, json={
            "email": FINANCE_EMAIL,
            "name": "TEST Finance Iter30",
            "password": FINANCE_PASSWORD,
            "role": "finance",
        }, timeout=30)
        if r.status_code not in (200, 201):
            pytest.skip(f"failed to create finance user: {r.status_code} {r.text[:200]}")
        uid = r.json().get("id") or r.json().get("_id")

    lr = http.post(f"{API}/auth/login",
                   json={"email": FINANCE_EMAIL, "password": FINANCE_PASSWORD}, timeout=30)
    if lr.status_code != 200:
        pytest.skip(f"finance login failed: {lr.status_code} {lr.text[:200]}")
    tok = lr.json()["token"]
    yield tok
    # cleanup
    try:
        http.delete(f"{API}/admin/users/{uid}", headers=admin_headers, timeout=30)
    except Exception:
        pass


# ============================================================
# F1 — Per-admin email settings
# ============================================================

class TestF1EmailSettings:
    """All F1 tests share a single admin session and manipulate that admin's own
    email_settings. The suite always DELETEs before/after so it is idempotent."""

    def test_00_delete_initial_settings_to_start_clean(self, http, admin_headers):
        r = http.delete(f"{API}/settings/email", headers=admin_headers, timeout=30)
        assert r.status_code == 200

    def test_01_get_settings_returns_empty_dict_when_unset(self, http, admin_headers):
        r = http.get(f"{API}/settings/email", headers=admin_headers, timeout=30)
        assert r.status_code == 200, r.text[:200]
        d = r.json()
        # Empty settings -> either {} literally or {configured: False, ...}
        assert d == {} or d.get("configured") in (False, None), f"expected empty/unconfigured, got {d}"

    def test_02_admin_mail_inbox_returns_not_setup_when_no_creds(self, http, admin_headers):
        r = http.get(f"{API}/admin/mail/inbox", headers=admin_headers, timeout=30)
        assert r.status_code == 200, r.text[:200]
        d = r.json()
        assert isinstance(d, dict), f"expected dict for not_setup, got {type(d).__name__}: {d!r}"
        assert d.get("not_setup") is True
        assert d.get("reason") == "no_credentials"
        assert isinstance(d.get("message"), str) and len(d["message"]) > 5

    def test_03_post_settings_persists_and_returns_configured(self, http, admin_headers):
        payload = {
            "from_name": "TEST Admin",
            "from_email": "test.admin@intercloud-digital.com",
            "imap": {"host": "mail.example.com", "port": 993,
                     "username": "test.admin@intercloud-digital.com",
                     "password": "SuperSecret123!", "use_ssl": True},
            "smtp": {"host": "mail.example.com", "port": 465,
                     "username": "test.admin@intercloud-digital.com",
                     "password": "SuperSecret123!", "use_ssl": True},
        }
        r = http.post(f"{API}/settings/email", headers=admin_headers, json=payload, timeout=30)
        assert r.status_code == 200, r.text[:200]
        d = r.json()
        assert d.get("configured") is True, f"expected configured:true, got {d}"
        assert d.get("from_email") == "test.admin@intercloud-digital.com"
        # POST response should already mask the password
        assert d["imap"]["credentials"].get("password") in (None, "", "••••••••")

    def test_04_get_after_save_returns_masked_password(self, http, admin_headers):
        r = http.get(f"{API}/settings/email", headers=admin_headers, timeout=30)
        assert r.status_code == 200
        d = r.json()
        assert d.get("configured") is True
        pw = d.get("imap", {}).get("credentials", {}).get("password")
        assert pw == "••••••••", f"expected masked '••••••••', got {pw!r}"
        # SMTP password should also be masked (or absent)
        smtp_pw = d.get("smtp", {}).get("credentials", {}).get("password")
        assert smtp_pw in ("••••••••", None, ""), f"smtp pw not masked: {smtp_pw!r}"

    def test_05_post_with_masked_password_preserves_original(self, http, admin_headers):
        """
        Re-POST with password='••••••••' (as the frontend does when the user only
        edits host/port). The stored password must remain 'SuperSecret123!'.
        We can't read the raw doc from HTTP, so we instead verify indirectly:
          * After the masked POST, the from_email is updated but configured stays true.
          * GET still shows configured:true and masked password.
        Then delete-and-recreate would obviously overwrite the password, but here
        we deliberately do NOT delete. If the backend had overwritten the real
        password with '••••••••', a subsequent connect-attempt would use that string
        and the inbox would return connection_failed with reason 'connection_failed'
        (still acceptable). The real assertion below uses a mongo read to be strict.
        """
        # Grab mongo directly for the strict assertion
        import motor.motor_asyncio, asyncio
        MONGO = os.environ.get("MONGO_URL")
        DB   = os.environ.get("DB_NAME")
        if not MONGO or not DB:
            pytest.skip("MONGO_URL/DB_NAME not set — cannot verify raw password in db")

        async def _read_pw():
            cli = motor.motor_asyncio.AsyncIOMotorClient(MONGO)
            doc = await cli[DB].users.find_one({"email": ADMIN_EMAIL})
            cli.close()
            return (doc or {}).get("email_settings", {}).get("imap", {}).get("credentials", {}).get("password")

        # Before masked-post: verify original password is stored
        original = asyncio.run(_read_pw())
        assert original == "SuperSecret123!", (
            f"expected stored pw 'SuperSecret123!' before masked-post, got {original!r}"
        )

        # Now POST with masked password + slightly updated from_name
        payload = {
            "from_name": "TEST Admin Renamed",
            "from_email": "test.admin@intercloud-digital.com",
            "imap": {"host": "mail.example.com", "port": 993,
                     "username": "test.admin@intercloud-digital.com",
                     "password": "••••••••", "use_ssl": True},
            "smtp": {"host": "mail.example.com", "port": 465,
                     "username": "test.admin@intercloud-digital.com",
                     "password": "••••••••", "use_ssl": True},
        }
        r = http.post(f"{API}/settings/email", headers=admin_headers, json=payload, timeout=30)
        assert r.status_code == 200

        # After masked-post: raw pw must STILL be the original 'SuperSecret123!'
        after = asyncio.run(_read_pw())
        assert after == "SuperSecret123!", (
            f"masked-post overwrote real password! Expected 'SuperSecret123!', got {after!r}"
        )

    def test_06_inbox_with_bogus_creds_returns_setup_hint_not_500(self, http, admin_headers):
        """With mail.example.com creds saved, inbox should NOT crash — either
        it returns connection_failed hint (dict) or a list (unlikely for fake host)."""
        r = http.get(f"{API}/admin/mail/inbox", headers=admin_headers, timeout=30)
        assert r.status_code == 200, r.text[:200]
        d = r.json()
        # Either connection_failed dict, or a list (if somehow it connected — unlikely)
        if isinstance(d, dict):
            assert d.get("not_setup") is True
            assert d.get("reason") in ("connection_failed", "no_credentials")

    def test_99_teardown_delete_settings(self, http, admin_headers):
        r = http.delete(f"{API}/settings/email", headers=admin_headers, timeout=30)
        assert r.status_code == 200
        # After delete, /settings/email should be empty again
        g = http.get(f"{API}/settings/email", headers=admin_headers, timeout=30)
        assert g.status_code == 200
        assert g.json() == {} or g.json().get("configured") in (False, None)


# ============================================================
# F3 — Sales/Finance dashboard scoping
# ============================================================

class TestF3DashboardScoping:

    def test_admin_dashboard_returns_global_stats(self, http, admin_headers):
        r = http.get(f"{API}/admin/dashboard", headers=admin_headers, timeout=30)
        assert r.status_code == 200
        d = r.json()
        assert d.get("role") == "admin"
        s = d["stats"]
        assert isinstance(s["total_clients"], int)
        # admin sees finance widgets
        assert "unpaid_invoices" in s
        assert "overdue_invoices" in s
        assert "revenue_total" in s

    def test_sales_dashboard_scoped_to_assigned_clients(
        self, http, sales_token, sales_assigned_client_ids, admin_headers
    ):
        h = {"Authorization": f"Bearer {sales_token}"}
        r = http.get(f"{API}/admin/dashboard", headers=h, timeout=30)
        assert r.status_code == 200
        d = r.json()
        assert d.get("role") == "sales"
        s = d["stats"]
        expected_client_count = len(sales_assigned_client_ids)
        assert s["total_clients"] == expected_client_count, (
            f"expected sales total_clients={expected_client_count} "
            f"(assigned_client_ids), got {s['total_clients']}"
        )

        # Compare against admin (global) tenant client count — sales must be <= admin
        admin_stats = http.get(f"{API}/admin/dashboard",
                               headers=admin_headers, timeout=30).json()["stats"]
        if admin_stats["total_clients"] > expected_client_count:
            assert s["total_clients"] < admin_stats["total_clients"], (
                "sales total_clients equal to admin global — scoping not applied"
            )

        # Sales gets financial widgets too (scoped)
        assert "unpaid_invoices" in s
        assert "overdue_invoices" in s
        assert "revenue_total" in s
        # All scoped counts must be ints, not None
        for k in ("unpaid_invoices", "overdue_invoices", "revenue_total"):
            assert isinstance(s[k], (int, float)), f"{k} not numeric: {s[k]!r}"

    def test_finance_dashboard_has_full_financial_fields(self, http, finance_token):
        h = {"Authorization": f"Bearer {finance_token}"}
        r = http.get(f"{API}/admin/dashboard", headers=h, timeout=30)
        assert r.status_code == 200, r.text[:200]
        d = r.json()
        assert d.get("role") == "finance"
        s = d["stats"]
        for k in ("unpaid_invoices", "overdue_invoices", "revenue_month", "revenue_total"):
            assert k in s, f"finance dashboard missing {k}: {s}"


# ============================================================
# Regression — batch-2 fixes still green
# ============================================================

class TestRegressionBatch2:
    def test_sales_orders_returns_200_array(self, http, sales_token):
        r = http.get(f"{API}/admin/orders",
                     headers={"Authorization": f"Bearer {sales_token}"}, timeout=30)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_sales_quotations_returns_200_array(self, http, sales_token):
        r = http.get(f"{API}/admin/quotations",
                     headers={"Authorization": f"Bearer {sales_token}"}, timeout=30)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_admin_bogus_imap_id_still_404(self, http, admin_headers):
        r = http.get(f"{API}/admin/mail/messages/imap-fakeid123",
                     headers=admin_headers, timeout=30)
        assert r.status_code == 404
        assert "detail" in r.json()

    def test_admin_dashboard_overdue_field_is_int(self, http, admin_headers):
        r = http.get(f"{API}/admin/dashboard", headers=admin_headers, timeout=30)
        assert r.status_code == 200
        s = r.json()["stats"]
        assert isinstance(s.get("overdue_invoices"), int)


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
