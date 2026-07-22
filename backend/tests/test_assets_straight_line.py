"""Straight-line asset depreciation tests.

Covers the rewritten AdminAssets endpoints:
  formula: (value - salvage_value) / useful_life_years

Legacy backward-compat via `depreciation_percent` and `useful_life_months`
is exercised too (both should backfill `useful_life_years`).

All routes: /api/portal/admin/assets{,{id}}
Auth: Bearer token from POST /api/portal/auth/login.
"""
import os
import uuid
import datetime
import pytest
import requests


API = os.environ.get("PORTAL_API_BASE") or "http://localhost:8001/api/portal"


def _h(t):
    return {"Authorization": f"Bearer {t}"}


@pytest.fixture(scope="module")
def admin_token():
    r = requests.post(
        f"{API}/auth/login",
        json={
            "email": os.environ["ADMIN_EMAIL"],
            "password": os.environ["ADMIN_PASSWORD"],
        },
        timeout=20,
    )
    assert r.status_code == 200, r.text
    return r.json()["token"]


@pytest.fixture(scope="module")
def created_ids():
    return []


@pytest.fixture(scope="module", autouse=True)
def _cleanup(admin_token, created_ids):
    yield
    # Teardown - delete anything we created
    for aid in created_ids:
        try:
            requests.delete(
                f"{API}/admin/assets/{aid}", headers=_h(admin_token), timeout=10
            )
        except Exception:
            pass


def _create(admin_token, created_ids, **payload):
    payload.setdefault("name", f"TEST_asset_{uuid.uuid4().hex[:8]}")
    payload.setdefault("category", "server")
    r = requests.post(
        f"{API}/admin/assets", headers=_h(admin_token), json=payload, timeout=15
    )
    assert r.status_code == 200, r.text
    body = r.json()
    created_ids.append(body["id"])
    return body


# ---------- Basic auth / health ----------
class TestAuthHealth:
    def test_auth_me_returns_admin(self, admin_token):
        r = requests.get(f"{API}/auth/me", headers=_h(admin_token), timeout=10)
        assert r.status_code == 200, r.text
        me = r.json()
        assert me.get("role") == "admin"
        assert me.get("email", "").lower() == os.environ["ADMIN_EMAIL"].lower()


# ---------- Formula validations ----------
class TestDepreciationFormula:
    def test_validation_case(self, admin_token, created_ids):
        """value=10M, salvage=1M, life=5y, purchase=2020-01-01 → fully depreciated."""
        body = _create(
            admin_token, created_ids,
            value=10_000_000, salvage_value=1_000_000,
            useful_life_years=5, purchase_date="2020-01-01",
        )
        assert body["annual_depreciation"] == 1_800_000, body
        assert body["monthly_depreciation"] == 150_000, body
        assert body["accumulated_depreciation"] == 9_000_000, body
        assert body["book_value"] == 1_000_000, body
        assert body["is_fully_depreciated"] is True, body
        assert body["useful_life_years"] == 5

    def test_zero_salvage(self, admin_token, created_ids):
        body = _create(
            admin_token, created_ids,
            value=10_000_000, salvage_value=0,
            useful_life_years=5, purchase_date="2020-01-01",
        )
        assert body["annual_depreciation"] == 2_000_000, body

    def test_life_one_year(self, admin_token, created_ids):
        body = _create(
            admin_token, created_ids,
            value=6_000_000, salvage_value=0,
            useful_life_years=1, purchase_date="2020-01-01",
        )
        assert body["annual_depreciation"] == 6_000_000, body
        assert body["book_value"] == 0, body
        assert body["is_fully_depreciated"] is True

    def test_mid_year_acquisition_partial(self, admin_token, created_ids):
        """purchase ~1 month before now; assert partial accumulation."""
        today = datetime.date.today()
        # Purchase ~37 days ago -> ideally 1-2 months elapsed
        purchase = (today - datetime.timedelta(days=37)).isoformat()
        body = _create(
            admin_token, created_ids,
            value=12_000_000, salvage_value=0,
            useful_life_years=10, purchase_date=purchase,
        )
        assert body["monthly_depreciation"] == 100_000, body
        assert body["annual_depreciation"] == 1_200_000, body
        assert body["months_elapsed"] in (1, 2), body
        assert 0 < body["accumulated_depreciation"] <= 200_000, body
        assert not body["is_fully_depreciated"]


# ---------- Legacy field migration on input ----------
class TestLegacyInputMigration:
    def test_depreciation_percent_maps_to_useful_life_years(self, admin_token, created_ids):
        """Client sends only depreciation_percent=20 → useful_life_years=5."""
        body = _create(
            admin_token, created_ids,
            value=10_000_000, salvage_value=0,
            depreciation_percent=20, purchase_date="2020-01-01",
        )
        assert body["useful_life_years"] == 5, body
        assert body["annual_depreciation"] == 2_000_000, body

    def test_useful_life_months_maps_to_years(self, admin_token, created_ids):
        body = _create(
            admin_token, created_ids,
            value=10_000_000, salvage_value=0,
            useful_life_months=60, purchase_date="2020-01-01",
        )
        assert body["useful_life_years"] == 5, body
        assert body["annual_depreciation"] == 2_000_000, body


# ---------- CRUD + schedule + list ----------
class TestAssetCrud:
    def test_get_single_returns_schedule(self, admin_token, created_ids):
        body = _create(
            admin_token, created_ids,
            value=10_000_000, salvage_value=1_000_000,
            useful_life_years=5, purchase_date="2020-01-01",
        )
        aid = body["id"]
        r = requests.get(
            f"{API}/admin/assets/{aid}", headers=_h(admin_token), timeout=10
        )
        assert r.status_code == 200, r.text
        detail = r.json()
        sch = detail.get("schedule")
        assert isinstance(sch, list) and len(sch) == 5, detail
        for i, row in enumerate(sch):
            for k in ("period", "year", "depreciation", "accumulated_depreciation", "book_value"):
                assert k in row, row
            assert row["period"] == i + 1
        # Last row book value equals salvage
        assert sch[-1]["book_value"] == 1_000_000
        # First-year depreciation matches straight-line
        assert sch[0]["depreciation"] == 1_800_000

    def test_update_reflects_new_depreciation(self, admin_token, created_ids):
        body = _create(
            admin_token, created_ids,
            value=10_000_000, salvage_value=0,
            useful_life_years=10, purchase_date="2020-01-01",
        )
        aid = body["id"]
        # Change salvage + life
        r = requests.put(
            f"{API}/admin/assets/{aid}",
            headers=_h(admin_token),
            json={"salvage_value": 2_000_000, "useful_life_years": 4},
            timeout=15,
        )
        assert r.status_code == 200, r.text
        upd = r.json()
        assert upd["salvage_value"] == 2_000_000
        assert upd["useful_life_years"] == 4
        assert upd["annual_depreciation"] == 2_000_000  # (10M-2M)/4
        assert abs(upd["monthly_depreciation"] - 2_000_000 / 12) < 0.01

    def test_delete_asset(self, admin_token, created_ids):
        body = _create(
            admin_token, created_ids,
            value=1_000_000, salvage_value=0,
            useful_life_years=5, purchase_date="2020-01-01",
        )
        aid = body["id"]
        r = requests.delete(
            f"{API}/admin/assets/{aid}", headers=_h(admin_token), timeout=10
        )
        assert r.status_code == 200, r.text
        assert r.json().get("deleted") == 1
        # Verify 404 on subsequent GET
        r2 = requests.get(
            f"{API}/admin/assets/{aid}", headers=_h(admin_token), timeout=10
        )
        assert r2.status_code == 404
        # Remove from cleanup list to avoid double-delete
        try:
            created_ids.remove(aid)
        except ValueError:
            pass

    def test_list_includes_new_fields(self, admin_token, created_ids):
        # Ensure at least one asset exists
        _create(
            admin_token, created_ids,
            value=1_000_000, salvage_value=100_000,
            useful_life_years=5, purchase_date="2020-01-01",
        )
        r = requests.get(f"{API}/admin/assets", headers=_h(admin_token), timeout=10)
        assert r.status_code == 200, r.text
        rows = r.json()
        assert isinstance(rows, list) and len(rows) >= 1
        row = rows[0]
        for f in (
            "salvage_value", "useful_life_years",
            "annual_depreciation", "monthly_depreciation", "accumulated_depreciation",
            "book_value",
        ):
            assert f in row, row


# ---------- Finance endpoints reflect new formula ----------
class TestFinanceEndpoints:
    def test_finance_detailed_assets_rows(self, admin_token, created_ids):
        # Seed a known asset
        body = _create(
            admin_token, created_ids,
            value=10_000_000, salvage_value=1_000_000,
            useful_life_years=5, purchase_date="2020-01-01",
        )
        r = requests.get(
            f"{API}/admin/finance/detailed", headers=_h(admin_token), timeout=15
        )
        assert r.status_code == 200, r.text
        d = r.json()
        rows = d.get("assets_rows") or []
        row = next((x for x in rows if x["id"] == body["id"]), None)
        assert row is not None, "created asset should appear in finance/detailed"
        for k in (
            "salvage_value", "useful_life_years",
            "annual_depreciation", "monthly_depreciation", "accumulated_depreciation",
        ):
            assert k in row
        assert row["annual_depreciation"] == 1_800_000
        assert row["monthly_depreciation"] == 150_000

    def test_finance_report_depreciation_matches_accumulated(self, admin_token, created_ids):
        """`/admin/finance/report` computes total_depreciation as
        (total_assets_value - net_book_value). For every asset, that must
        equal its accumulated_depreciation (per-asset invariant).
        We use a per-row invariant (not a sum-vs-sum comparison) because
        parallel workers may add/remove assets between two endpoint calls.
        """
        r = requests.get(
            f"{API}/admin/finance/detailed", headers=_h(admin_token), timeout=15
        )
        assert r.status_code == 200, r.text
        rows = r.json().get("assets_rows", [])
        assert rows, "expected some assets rows"
        for a in rows:
            diff = float(a["value"]) - float(a["book_value"]) - float(a["accumulated_depreciation"])
            assert abs(diff) < 0.05, (
                f"per-asset invariant failed for {a.get('name')}: "
                f"value({a['value']}) - book({a['book_value']}) - accum({a['accumulated_depreciation']}) = {diff}"
            )

    def test_finance_report_shape(self, admin_token):
        """Sanity check: /finance/report returns straight-line fields."""
        r = requests.get(
            f"{API}/admin/finance/report", headers=_h(admin_token), timeout=15
        )
        assert r.status_code == 200, r.text
        d = r.json()
        for k in ("total_assets_value", "net_assets_value", "total_depreciation"):
            assert k in d
        # depreciation must be >= 0 and <= total value
        assert 0 <= float(d["total_depreciation"]) <= float(d["total_assets_value"]) + 0.01
