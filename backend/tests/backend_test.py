"""Intercloud Portal — Backend API pytest suite.

Covers:
- Health
- Auth: register/login/logout/me/forgot-password/reset-password/brute-force lockout
- Categories CRUD (admin) + non-admin 403
- Locations CRUD (admin) + non-admin 403
- Assets CRUD (create/read/update/delete, filters, uniqueness)
- Depreciation formula validation (10M / 1M / 5y => annual 1.8M, monthly 150K)
- Depreciation edge cases (zero salvage, life=1, partial year)
- Schedule generation
- Dashboard summary
- Reports: depreciation + timeline
- Users (admin): list/update/cannot-delete-self/non-admin blocked
- In-use protection for categories/locations
"""
from __future__ import annotations

import os
import time
import uuid
from typing import Optional

import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001").rstrip("/")
API = f"{BASE_URL}/api"

ADMIN_EMAIL = "admin@intercloud.io"
ADMIN_PASSWORD = "admin123"


# ------------------------------------------------------------------- fixtures
@pytest.fixture(scope="session")
def admin_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    r = s.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert r.status_code == 200, f"Admin login failed: {r.status_code} {r.text}"
    data = r.json()
    token = data["access_token"]
    s.headers.update({"Authorization": f"Bearer {token}"})
    return s


@pytest.fixture(scope="session")
def staff_user(admin_session) -> dict:
    """Register a fresh staff user and return {session, id, email}."""
    email = f"TEST_staff_{uuid.uuid4().hex[:10]}@example.com"
    password = "staffpass123"
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    r = s.post(f"{API}/auth/register", json={"email": email, "password": password, "name": "TEST Staff"})
    assert r.status_code == 200, r.text
    data = r.json()
    s.headers.update({"Authorization": f"Bearer {data['access_token']}"})
    return {"session": s, "id": data["user"]["id"], "email": email, "password": password}


# ------------------------------------------------------------------- Health
class TestHealth:
    def test_health_ok(self):
        r = requests.get(f"{API}/health")
        assert r.status_code == 200
        body = r.json()
        assert body.get("status") == "ok"
        assert "time" in body


# ------------------------------------------------------------------- Auth
class TestAuth:
    def test_admin_login_returns_token_and_cookies(self):
        s = requests.Session()
        r = s.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
        assert r.status_code == 200, r.text
        data = r.json()
        assert "access_token" in data and isinstance(data["access_token"], str)
        assert data["user"]["email"] == ADMIN_EMAIL
        assert data["user"]["role"] == "admin"
        # Cookies set
        cookie_names = {c.name for c in s.cookies}
        assert "access_token" in cookie_names
        assert "refresh_token" in cookie_names
        # /auth/me via cookies (no bearer header)
        r2 = s.get(f"{API}/auth/me")
        assert r2.status_code == 200
        assert r2.json()["email"] == ADMIN_EMAIL

    def test_register_new_staff(self):
        # Server lowercases emails; use lowercase to match returned value
        email = f"test_reg_{uuid.uuid4().hex[:10]}@example.com"
        r = requests.post(f"{API}/auth/register", json={"email": email, "password": "abc12345", "name": "TEST Reg"})
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["user"]["email"] == email.lower()
        assert data["user"]["role"] == "staff"
        assert "access_token" in data

    def test_wrong_password_returns_401(self):
        # Use a unique email pattern to avoid interfering with lockout on admin
        r = requests.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": "wrong-pass-xyz"})
        assert r.status_code == 401

    def test_brute_force_lockout_after_5(self):
        """Fresh account: 4 wrong attempts still 401, 5th triggers lockout (5th itself is 401 but next call is 429)."""
        email = f"TEST_brute_{uuid.uuid4().hex[:10]}@example.com"
        # Register
        rr = requests.post(f"{API}/auth/register", json={"email": email, "password": "correctpass", "name": "TEST Brute"})
        assert rr.status_code == 200
        s = requests.Session()
        for i in range(5):
            r = s.post(f"{API}/auth/login", json={"email": email, "password": "bad"})
            # server increments; when attempts reaches 5, locked_until is set and 401 returned for that call
            assert r.status_code == 401, f"attempt {i+1}: {r.status_code} {r.text}"
        # Next attempt should be 429
        r6 = s.post(f"{API}/auth/login", json={"email": email, "password": "bad"})
        assert r6.status_code == 429, f"expected 429 got {r6.status_code} {r6.text}"

    def test_logout_clears_cookies(self):
        s = requests.Session()
        r = s.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
        assert r.status_code == 200
        assert "access_token" in {c.name for c in s.cookies}
        r2 = s.post(f"{API}/auth/logout")
        assert r2.status_code == 200
        # After logout, /auth/me should fail without bearer/cookies
        s.headers.pop("Authorization", None)
        r3 = s.get(f"{API}/auth/me")
        assert r3.status_code == 401

    def test_forgot_and_reset_password(self):
        email = f"TEST_reset_{uuid.uuid4().hex[:10]}@example.com"
        # register
        rr = requests.post(f"{API}/auth/register", json={"email": email, "password": "origpass1", "name": "TEST Reset"})
        assert rr.status_code == 200
        # forgot
        r = requests.post(f"{API}/auth/forgot-password", json={"email": email})
        assert r.status_code == 200
        body = r.json()
        assert body.get("ok") is True
        token = body.get("reset_token")
        assert token, "reset_token missing (dev mode should include it)"
        # reset
        r2 = requests.post(f"{API}/auth/reset-password", json={"token": token, "new_password": "newpass99"})
        assert r2.status_code == 200
        # login with new password
        r3 = requests.post(f"{API}/auth/login", json={"email": email, "password": "newpass99"})
        assert r3.status_code == 200


# ------------------------------------------------------------------- Categories
class TestCategories:
    created_id: Optional[str] = None

    def test_list_categories(self, admin_session):
        r = admin_session.get(f"{API}/categories")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_admin_create_category(self, admin_session):
        name = f"TEST_Cat_{uuid.uuid4().hex[:6]}"
        r = admin_session.post(f"{API}/categories", json={"name": name, "code": "TST", "description": "test"})
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["name"] == name
        assert "id" in d
        TestCategories.created_id = d["id"]

    def test_duplicate_category_returns_400(self, admin_session):
        assert TestCategories.created_id, "requires create test first"
        # fetch existing name
        cats = admin_session.get(f"{API}/categories").json()
        existing = next(c for c in cats if c["id"] == TestCategories.created_id)
        r = admin_session.post(f"{API}/categories", json={"name": existing["name"]})
        assert r.status_code == 400

    def test_non_admin_cannot_create(self, staff_user):
        r = staff_user["session"].post(f"{API}/categories", json={"name": f"TEST_Cat_deny_{uuid.uuid4().hex[:5]}"})
        assert r.status_code == 403

    def test_update_category(self, admin_session):
        assert TestCategories.created_id
        r = admin_session.put(f"{API}/categories/{TestCategories.created_id}",
                              json={"name": f"TEST_Cat_upd_{uuid.uuid4().hex[:5]}", "code": "TST2"})
        assert r.status_code == 200
        assert r.json()["code"] == "TST2"

    def test_delete_category(self, admin_session):
        assert TestCategories.created_id
        r = admin_session.delete(f"{API}/categories/{TestCategories.created_id}")
        assert r.status_code == 200


# ------------------------------------------------------------------- Locations
class TestLocations:
    created_id: Optional[str] = None

    def test_list_locations(self, admin_session):
        r = admin_session.get(f"{API}/locations")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_admin_create_location(self, admin_session):
        r = admin_session.post(f"{API}/locations",
                               json={"name": f"TEST_Loc_{uuid.uuid4().hex[:6]}", "code": "TL1", "address": "Addr"})
        assert r.status_code == 200, r.text
        TestLocations.created_id = r.json()["id"]

    def test_non_admin_cannot_create_location(self, staff_user):
        r = staff_user["session"].post(f"{API}/locations", json={"name": f"TEST_Loc_deny_{uuid.uuid4().hex[:5]}"})
        assert r.status_code == 403

    def test_update_location(self, admin_session):
        assert TestLocations.created_id
        r = admin_session.put(f"{API}/locations/{TestLocations.created_id}",
                              json={"name": f"TEST_Loc_upd_{uuid.uuid4().hex[:5]}", "code": "TL2", "address": "X"})
        assert r.status_code == 200

    def test_delete_location(self, admin_session):
        assert TestLocations.created_id
        r = admin_session.delete(f"{API}/locations/{TestLocations.created_id}")
        assert r.status_code == 200


# ------------------------------------------------------------------- Assets + Depreciation
@pytest.fixture(scope="session")
def taxonomy(admin_session):
    """Create a dedicated category + location for asset tests."""
    cat = admin_session.post(f"{API}/categories",
                             json={"name": f"TEST_AssetCat_{uuid.uuid4().hex[:6]}", "code": "TAC"}).json()
    loc = admin_session.post(f"{API}/locations",
                             json={"name": f"TEST_AssetLoc_{uuid.uuid4().hex[:6]}", "code": "TAL"}).json()
    yield {"category_id": cat["id"], "location_id": loc["id"]}


class TestAssetsAndDepreciation:
    depreciation_asset_id: Optional[str] = None
    generic_asset_id: Optional[str] = None
    generic_asset_code: Optional[str] = None

    def test_create_asset_depreciation_10m_1m_5y(self, admin_session, taxonomy):
        """CRITICAL: cost=10M, salvage=1M, life=5, acq 2020-01-01 => annual=1.8M, monthly=150K, acc>=9M after 5y."""
        code = f"TEST_A_{uuid.uuid4().hex[:8]}"
        payload = {
            "code": code,
            "name": "TEST Depreciation Asset",
            "category_id": taxonomy["category_id"],
            "location_id": taxonomy["location_id"],
            "acquisition_cost": 10000000,
            "salvage_value": 1000000,
            "useful_life_years": 5,
            "acquisition_date": "2020-01-01",
            "status": "active",
        }
        r = admin_session.post(f"{API}/assets", json=payload)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["code"] == code
        dep = d["depreciation"]
        assert dep["annual_depreciation"] == 1800000, dep
        assert dep["monthly_depreciation"] == 150000, dep
        # 2020-01-01 acquisition; today in 2026 => >= 5 years elapsed, fully depreciated
        assert dep["accumulated_depreciation"] == 9000000.0, dep
        assert dep["book_value"] == 1000000.0, dep
        assert dep["is_fully_depreciated"] is True
        TestAssetsAndDepreciation.depreciation_asset_id = d["id"]

    def test_get_asset_includes_schedule(self, admin_session):
        aid = TestAssetsAndDepreciation.depreciation_asset_id
        assert aid
        r = admin_session.get(f"{API}/assets/{aid}")
        assert r.status_code == 200
        body = r.json()
        assert "schedule" in body
        assert isinstance(body["schedule"], list) and len(body["schedule"]) == 5
        # each entry has annual of 1.8M
        for entry in body["schedule"]:
            assert entry["depreciation"] == 1800000.0
        # last entry accumulated equals depreciable base 9M
        assert body["schedule"][-1]["accumulated_depreciation"] == 9000000.0
        assert body["schedule"][-1]["book_value"] == 1000000.0

    def test_depreciation_zero_salvage(self, admin_session):
        code = f"TEST_A_{uuid.uuid4().hex[:8]}"
        r = admin_session.post(f"{API}/assets", json={
            "code": code,
            "name": "TEST Zero Salvage",
            "acquisition_cost": 10000000, "salvage_value": 0, "useful_life_years": 5,
            "acquisition_date": "2020-01-01",
        })
        assert r.status_code == 200
        dep = r.json()["depreciation"]
        assert dep["annual_depreciation"] == 2000000
        assert dep["accumulated_depreciation"] == 10000000.0
        assert dep["book_value"] == 0.0

    def test_depreciation_life_one_year(self, admin_session):
        code = f"TEST_A_{uuid.uuid4().hex[:8]}"
        r = admin_session.post(f"{API}/assets", json={
            "code": code,
            "name": "TEST Life 1yr",
            "acquisition_cost": 1200000, "salvage_value": 0, "useful_life_years": 1,
            "acquisition_date": "2020-01-01",
        })
        assert r.status_code == 200
        dep = r.json()["depreciation"]
        assert dep["annual_depreciation"] == 1200000
        assert dep["monthly_depreciation"] == 100000
        assert dep["is_fully_depreciated"] is True

    def test_depreciation_partial_year_recent_acquisition(self, admin_session):
        """Recent acquisition should yield partial accumulation (< annual)."""
        # Use ~ a few months back from a stable date; use 3 months
        from datetime import date, timedelta
        acq = (date.today().replace(day=1) - timedelta(days=90)).isoformat()
        code = f"TEST_A_{uuid.uuid4().hex[:8]}"
        r = admin_session.post(f"{API}/assets", json={
            "code": code,
            "name": "TEST Partial",
            "acquisition_cost": 12000000, "salvage_value": 0, "useful_life_years": 5,
            "acquisition_date": acq,
        })
        assert r.status_code == 200
        dep = r.json()["depreciation"]
        assert dep["annual_depreciation"] == 2400000
        assert dep["accumulated_depreciation"] < dep["annual_depreciation"]
        assert dep["book_value"] > 0
        assert dep["is_fully_depreciated"] is False

    def test_duplicate_asset_code_returns_400(self, admin_session):
        code = f"TEST_A_{uuid.uuid4().hex[:8]}"
        payload = {
            "code": code, "name": "First", "acquisition_cost": 1000000, "salvage_value": 0,
            "useful_life_years": 3, "acquisition_date": "2022-06-01",
        }
        r1 = admin_session.post(f"{API}/assets", json=payload)
        assert r1.status_code == 200
        r2 = admin_session.post(f"{API}/assets", json=payload)
        assert r2.status_code == 400
        TestAssetsAndDepreciation.generic_asset_id = r1.json()["id"]
        TestAssetsAndDepreciation.generic_asset_code = code

    def test_list_assets_with_filters(self, admin_session, taxonomy):
        r = admin_session.get(f"{API}/assets", params={
            "q": "TEST",
            "category_id": taxonomy["category_id"],
            "page": 1, "page_size": 50,
        })
        assert r.status_code == 200
        body = r.json()
        assert "items" in body and "total" in body
        assert isinstance(body["items"], list)

    def test_update_asset(self, admin_session):
        aid = TestAssetsAndDepreciation.generic_asset_id
        code = TestAssetsAndDepreciation.generic_asset_code
        assert aid and code
        r = admin_session.put(f"{API}/assets/{aid}", json={
            "code": code, "name": "Updated Name",
            "acquisition_cost": 1000000, "salvage_value": 0, "useful_life_years": 3,
            "acquisition_date": "2022-06-01", "status": "in_repair",
        })
        assert r.status_code == 200
        assert r.json()["status"] == "in_repair"
        assert r.json()["name"] == "Updated Name"

    def test_category_in_use_cannot_delete(self, admin_session, taxonomy):
        r = admin_session.delete(f"{API}/categories/{taxonomy['category_id']}")
        assert r.status_code == 400

    def test_location_in_use_cannot_delete(self, admin_session, taxonomy):
        r = admin_session.delete(f"{API}/locations/{taxonomy['location_id']}")
        assert r.status_code == 400

    def test_non_admin_cannot_delete_asset(self, staff_user, admin_session):
        # create asset as admin
        code = f"TEST_A_{uuid.uuid4().hex[:8]}"
        r = admin_session.post(f"{API}/assets", json={
            "code": code, "name": "TEST NoDel",
            "acquisition_cost": 5000000, "salvage_value": 0, "useful_life_years": 4,
            "acquisition_date": "2022-01-01",
        })
        assert r.status_code == 200
        aid = r.json()["id"]
        # staff tries to delete
        rd = staff_user["session"].delete(f"{API}/assets/{aid}")
        assert rd.status_code == 403
        # cleanup as admin
        admin_session.delete(f"{API}/assets/{aid}")


# ------------------------------------------------------------------- Dashboard
class TestDashboard:
    def test_dashboard_summary(self, admin_session):
        r = admin_session.get(f"{API}/dashboard/summary")
        assert r.status_code == 200
        d = r.json()
        for key in ("total_assets", "total_acquisition_cost", "total_accumulated_depreciation",
                    "total_book_value", "category_breakdown", "location_breakdown", "status_breakdown"):
            assert key in d, f"missing {key}"
        assert isinstance(d["category_breakdown"], list)
        assert isinstance(d["location_breakdown"], list)
        assert isinstance(d["status_breakdown"], dict)


# ------------------------------------------------------------------- Reports
class TestReports:
    def test_depreciation_report(self, admin_session):
        r = admin_session.get(f"{API}/reports/depreciation", params={"as_of": "2026-01-01"})
        assert r.status_code == 200
        body = r.json()
        assert "rows" in body and "totals" in body
        assert body["as_of"] == "2026-01-01"
        assert "acquisition_cost" in body["totals"]
        assert "accumulated_depreciation" in body["totals"]
        assert "book_value" in body["totals"]

    def test_timeline_report(self, admin_session):
        r = admin_session.get(f"{API}/reports/timeline", params={"years": 3})
        assert r.status_code == 200
        body = r.json()
        assert "series" in body and isinstance(body["series"], list)
        assert len(body["series"]) >= 3
        for p in body["series"]:
            assert set(p.keys()) >= {"year", "accumulated_depreciation", "book_value"}


# ------------------------------------------------------------------- Users
class TestUsers:
    def test_admin_list_users(self, admin_session):
        r = admin_session.get(f"{API}/users")
        assert r.status_code == 200
        assert isinstance(r.json(), list) and len(r.json()) >= 1

    def test_non_admin_cannot_list_users(self, staff_user):
        r = staff_user["session"].get(f"{API}/users")
        assert r.status_code == 403

    def test_admin_can_update_user(self, admin_session, staff_user):
        uid = staff_user["id"]
        r = admin_session.put(f"{API}/users/{uid}", json={"name": "TEST Staff Updated"})
        assert r.status_code == 200
        assert r.json()["name"] == "TEST Staff Updated"

    def test_admin_cannot_delete_self(self, admin_session):
        me = admin_session.get(f"{API}/auth/me").json()
        r = admin_session.delete(f"{API}/users/{me['id']}")
        assert r.status_code == 400
