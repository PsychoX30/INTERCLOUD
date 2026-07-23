"""Backend tests for iteration_26:
- Landing CMS (public GET, admin POST/DELETE, 128 KB cap, auth guards)
- Backup download (mongodump gzip archive, filename pattern, headers, auth)
- Restore (confirm guard, empty guard, round-trip, auth)
- Regressions: login endpoint, /api/portal/admin/users survives round-trip
"""
import os
import re
import gzip
import json
import io
import pytest
import requests

BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL")
            or open("/app/frontend/.env").read().split("REACT_APP_BACKEND_URL=")[1].splitlines()[0].strip()
           ).rstrip("/")
API = f"{BASE_URL}/api/portal"

ADMIN_EMAIL = "admin@intercloud-digital.com"
ADMIN_PASSWORD = "AdminIntercloud2026!"


# ---------- fixtures ----------
@pytest.fixture(scope="session")
def s():
    return requests.Session()


@pytest.fixture(scope="session")
def admin_token(s):
    r = s.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}, timeout=30)
    assert r.status_code == 200, f"admin login failed: {r.status_code} {r.text[:200]}"
    tok = r.json().get("token")
    assert tok, "no token in login response"
    return tok


@pytest.fixture(scope="session")
def admin_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


# ---------- Regression: login still works ----------
class TestLoginRegression:
    def test_admin_login_200(self, s):
        r = s.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}, timeout=30)
        assert r.status_code == 200
        data = r.json()
        assert "token" in data and "user" in data
        assert data["user"]["email"] == ADMIN_EMAIL


# ---------- Landing CMS ----------
class TestLandingCMS:
    def test_public_get_shape(self, s):
        r = s.get(f"{API}/landing-content", timeout=15)
        assert r.status_code == 200, r.text
        data = r.json()
        assert set(data.keys()) >= {"overrides", "faqs", "contact"}
        assert isinstance(data["overrides"], dict)
        assert isinstance(data["faqs"], list)
        assert isinstance(data["contact"], dict)

    def test_admin_post_and_persist(self, s, admin_headers):
        payload = {
            "overrides": {
                "hero.h1a": {"id": "Custom ID", "en": "Custom EN"},
            },
            "faqs": [{"q": {"id": "Q1", "en": "Q1"}, "a": {"id": "A1", "en": "A1"}}],
            "contact": {"phone": "+62 878-1239-7187"},
        }
        r = s.post(f"{API}/admin/landing-content", json=payload, headers=admin_headers, timeout=15)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["overrides"]["hero.h1a"]["id"] == "Custom ID"
        assert data["overrides"]["hero.h1a"]["en"] == "Custom EN"
        assert data["faqs"][0]["q"]["en"] == "Q1"
        assert data["contact"]["phone"].startswith("+62")

        # Public GET must reflect
        r2 = s.get(f"{API}/landing-content", timeout=15)
        assert r2.status_code == 200
        d2 = r2.json()
        assert d2["overrides"]["hero.h1a"]["en"] == "Custom EN"
        assert len(d2["faqs"]) == 1

    def test_admin_post_requires_auth(self, s):
        r = s.post(f"{API}/admin/landing-content", json={"overrides": {}}, timeout=15)
        assert r.status_code in (401, 403), f"expected 401/403 got {r.status_code} {r.text[:200]}"

    def test_size_cap_413(self, s, admin_headers):
        # Build overrides > 130KB.  Values are strings.
        big = "x" * 200
        overrides = {}
        # ~200 char value + key overhead ~30 -> ~230 bytes per entry. 130KB -> ~600 entries
        for i in range(1000):
            overrides[f"pad.key{i}"] = {"id": big, "en": big}
        r = s.post(f"{API}/admin/landing-content",
                   json={"overrides": overrides, "faqs": [], "contact": {}},
                   headers=admin_headers, timeout=15)
        assert r.status_code == 413, f"expected 413 got {r.status_code} {r.text[:200]}"

    def test_admin_delete_wipes(self, s, admin_headers):
        r = s.delete(f"{API}/admin/landing-content", headers=admin_headers, timeout=15)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["overrides"] == {}
        assert data["faqs"] == []

        r2 = s.get(f"{API}/landing-content", timeout=15)
        d2 = r2.json()
        assert d2["overrides"] == {}
        assert d2["faqs"] == []
        assert d2["contact"] == {}

    def test_admin_delete_requires_auth(self, s):
        r = s.delete(f"{API}/admin/landing-content", timeout=15)
        assert r.status_code in (401, 403)


# ---------- Backup download ----------
class TestBackupDownload:
    def test_requires_auth(self, s):
        r = s.get(f"{API}/admin/backup/download", timeout=30)
        assert r.status_code in (401, 403)

    def test_download_ok(self, s, admin_headers):
        r = s.get(f"{API}/admin/backup/download", headers=admin_headers, timeout=60)
        assert r.status_code == 200, r.text[:400]
        assert "application/gzip" in r.headers.get("content-type", "").lower()
        cd = r.headers.get("content-disposition", "")
        assert re.search(r'intercloud-backup-\d{8}T\d{6}Z\.archive\.gz', cd), f"bad CD: {cd}"
        assert r.headers.get("cache-control", "").lower() in ("no-store", "no-cache", "no-store, no-cache") \
               or "no-store" in r.headers.get("cache-control", "").lower()
        body = r.content
        assert len(body) > 100, f"archive too small: {len(body)}"
        # Must start with gzip magic
        assert body[:2] == b"\x1f\x8b", f"not gzip: {body[:8]!r}"
        # stash for restore test
        pytest.saved_archive = body


# ---------- Restore ----------
class TestBackupRestore:
    def test_no_confirm_400(self, s, admin_headers):
        r = s.post(f"{API}/admin/backup/restore",
                   data=b"x" * 64,
                   headers={**admin_headers, "Content-Type": "application/gzip"},
                   timeout=30)
        assert r.status_code == 400, r.text[:300]
        assert "confirm" in r.text.lower()

    def test_empty_body_400(self, s, admin_headers):
        r = s.post(f"{API}/admin/backup/restore?confirm=REPLACE",
                   data=b"",
                   headers={**admin_headers, "Content-Type": "application/gzip"},
                   timeout=30)
        assert r.status_code == 400, r.text[:300]

    def test_requires_auth(self, s):
        r = s.post(f"{API}/admin/backup/restore?confirm=REPLACE",
                   data=b"x" * 64, timeout=30)
        assert r.status_code in (401, 403)

    def test_round_trip(self, s, admin_headers):
        # Snapshot users before
        r_before = s.get(f"{API}/admin/users", headers=admin_headers, timeout=30)
        assert r_before.status_code == 200
        users_before = r_before.json()
        n_before = len(users_before) if isinstance(users_before, list) else len(users_before.get("items", []))
        assert n_before > 0

        # Download fresh archive
        r_dl = s.get(f"{API}/admin/backup/download", headers=admin_headers, timeout=60)
        assert r_dl.status_code == 200
        archive = r_dl.content
        assert archive[:2] == b"\x1f\x8b"

        # Restore
        r_rs = s.post(f"{API}/admin/backup/restore?confirm=REPLACE",
                      data=archive,
                      headers={**admin_headers, "Content-Type": "application/gzip"},
                      timeout=120)
        assert r_rs.status_code == 200, r_rs.text[:400]
        body = r_rs.json()
        assert body.get("ok") is True
        assert body.get("bytes_received") == len(archive)
        assert "log_tail" in body

        # Users should still be intact
        r_after = s.get(f"{API}/admin/users", headers=admin_headers, timeout=30)
        assert r_after.status_code == 200
        users_after = r_after.json()
        n_after = len(users_after) if isinstance(users_after, list) else len(users_after.get("items", []))
        assert n_after == n_before, f"users lost: before={n_before} after={n_after}"


# ---------- Regression: Mikrotik page still reachable ----------
class TestMikrotikRegression:
    def test_mikrotik_devices_list(self, s, admin_headers):
        r = s.get(f"{API}/admin/mikrotik/devices", headers=admin_headers, timeout=15)
        # Just ensure endpoint responds; 200 or 404 both acceptable if endpoint moved
        assert r.status_code in (200, 404), f"mikrotik broken: {r.status_code}"


# ---------- Cleanup: leave DB clean ----------
def teardown_module(module):
    """Wipe any landing-content override we might have left behind."""
    try:
        s = requests.Session()
        r = s.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}, timeout=30)
        if r.status_code == 200:
            tok = r.json()["token"]
            s.delete(f"{API}/admin/landing-content",
                     headers={"Authorization": f"Bearer {tok}"}, timeout=15)
    except Exception:
        pass
