"""CRM ↔ Order/Invoice enrichment tests."""
import os
import time
import requests

API = os.environ.get("PORTAL_API_BASE") or "http://localhost:8001/api/portal"


def _h(t: str) -> dict:
    return {"Authorization": f"Bearer {t}"}


def _admin_token() -> str:
    r = requests.post(f"{API}/auth/login", json={
        "email": os.environ["ADMIN_EMAIL"], "password": os.environ["ADMIN_PASSWORD"],
    })
    r.raise_for_status()
    return r.json()["token"]


class TestCrmEnrichment:
    def test_crm_rows_have_enrichment_fields(self):
        rows = requests.get(f"{API}/admin/crm", headers=_h(_admin_token())).json()
        assert len(rows) >= 1
        for r in rows:
            # Every row must ship every enrichment field
            for k in ("latest_order", "active_orders_count", "in_progress_count",
                      "won_orders_count", "lifetime_value", "is_warm"):
                assert k in r, f"missing {k} on CRM row {r.get('email')}"
            assert isinstance(r["active_orders_count"], int)
            assert isinstance(r["in_progress_count"], int)
            assert isinstance(r["won_orders_count"], int)
            assert isinstance(r["lifetime_value"], (int, float))
            assert isinstance(r["is_warm"], bool)

    def test_demo_client_has_orders_and_ltv(self):
        rows = requests.get(f"{API}/admin/crm", headers=_h(_admin_token())).json()
        demo = next((r for r in rows if r["email"] == os.environ["CLIENT_EMAIL"].lower()), None)
        assert demo is not None
        assert demo["latest_order"] is not None
        # Seed created invoices and orders for the demo client
        assert demo["lifetime_value"] > 0
        assert demo["active_orders_count"] >= 1

    def test_warm_flag_reflects_in_progress_count(self):
        rows = requests.get(f"{API}/admin/crm", headers=_h(_admin_token())).json()
        for r in rows:
            assert r["is_warm"] == (r["in_progress_count"] > 0)

    def test_unlinked_prospect_has_empty_enrichment(self):
        rows = requests.get(f"{API}/admin/crm", headers=_h(_admin_token())).json()
        # Prospects without a user_id (or without any orders) should have zeros
        no_orders = [r for r in rows if not r.get("latest_order")]
        for r in no_orders:
            assert r["active_orders_count"] == 0
            assert r["in_progress_count"] == 0
            assert r["won_orders_count"] == 0
            assert r["lifetime_value"] == 0
            assert r["is_warm"] is False

    def test_latest_order_has_expected_shape(self):
        rows = requests.get(f"{API}/admin/crm", headers=_h(_admin_token())).json()
        for r in rows:
            lo = r.get("latest_order")
            if lo is None:
                continue
            for k in ("id", "status", "product_name", "created_at"):
                assert k in lo, f"latest_order missing {k}"
