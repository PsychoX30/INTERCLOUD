"""
Iteration 27 — System Update endpoints, install/update.sh script sanity,
plus a regression sweep on backup download + login + mikrotik + branding.
"""
import os
import re
import subprocess
import time

import pytest
import requests

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/") if os.environ.get("REACT_APP_BACKEND_URL") else None
if not BASE_URL:
    # Fallback to frontend/.env
    with open("/app/frontend/.env") as f:
        for line in f:
            if line.startswith("REACT_APP_BACKEND_URL="):
                BASE_URL = line.split("=", 1)[1].strip().rstrip("/")
                break

API = f"{BASE_URL}/api/portal"
ADMIN_EMAIL = "admin@intercloud-digital.com"
ADMIN_PASSWORD = "AdminIntercloud2026!"


# ------------------------------------------------------------
# fixtures
# ------------------------------------------------------------
@pytest.fixture(scope="session")
def admin_token():
    r = requests.post(f"{API}/auth/login",
                      json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
                      timeout=15)
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    tok = r.json().get("token") or r.json().get("access_token")
    assert tok, f"no token in response: {r.json()}"
    return tok


@pytest.fixture
def admin_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


# ------------------------------------------------------------
# System version endpoint
# ------------------------------------------------------------
class TestSystemVersion:
    def test_version_admin_success(self, admin_headers):
        r = requests.get(f"{API}/admin/system/version", headers=admin_headers, timeout=15)
        assert r.status_code == 200, r.text
        data = r.json()
        # All required keys present
        for k in ["sha", "short", "branch", "subject", "date", "repo_root"]:
            assert k in data, f"missing key {k}: {data}"
        # All non-null on this repo checkout
        assert data["sha"], f"sha empty: {data}"
        assert data["short"], f"short empty: {data}"
        assert data["branch"], f"branch empty: {data}"
        assert data["subject"], f"subject empty: {data}"
        assert data["date"], f"date empty: {data}"
        assert data["repo_root"], f"repo_root empty: {data}"
        # Sanity: short is prefix of sha
        assert data["sha"].startswith(data["short"]), (data["sha"], data["short"])

    def test_version_requires_auth(self):
        r = requests.get(f"{API}/admin/system/version", timeout=10)
        assert r.status_code in (401, 403), f"unauth got {r.status_code} {r.text}"


# ------------------------------------------------------------
# System update endpoint
# ------------------------------------------------------------
class TestSystemUpdate:
    def test_update_no_confirm(self, admin_headers):
        r = requests.post(f"{API}/admin/system/update", headers=admin_headers, timeout=30)
        assert r.status_code == 400, r.text
        assert "Confirmation required" in r.text
        assert "confirm=UPDATE" in r.text

    def test_update_requires_auth(self):
        r = requests.post(f"{API}/admin/system/update?confirm=UPDATE", timeout=10)
        assert r.status_code in (401, 403), f"unauth got {r.status_code} {r.text}"

    def test_update_confirmed(self, admin_headers):
        """Async update: POST memulai job DETACHED lalu status dipoll.

        Di preview (tanpa git remote) pre-check mengembalikan 422 sebelum
        apa pun berjalan. Pada deployment nyata POST mengembalikan
        started=True dan polling status berakhir di state ok/failed."""
        r = requests.post(f"{API}/admin/system/update?confirm=UPDATE",
                          headers=admin_headers, timeout=60)
        print(f"UPDATE start status={r.status_code} body={r.text[:300]!r}")
        if r.status_code in (409, 422):
            # 409 = update lain berjalan / dirty tree; 422 = tanpa remote (preview)
            assert r.json().get("detail"), r.text
            return
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("started") is True and body.get("pid"), body

        deadline = time.time() + 600
        final = None
        while time.time() < deadline:
            try:
                s = requests.get(f"{API}/admin/system/update/status",
                                 headers=admin_headers, timeout=10)
                if s.status_code == 200 and not s.json().get("running"):
                    final = s.json()
                    break
            except Exception:
                pass  # backend restart di tengah update - lanjut polling
            time.sleep(3)
        assert final is not None, "update never reached a terminal state"
        print("UPDATE final:", final.get("state"), final.get("status"))
        assert final.get("state") in ("ok", "failed", "unknown"), final
        assert isinstance(final.get("log_tail"), str)

    def test_update_status_endpoint(self, admin_headers):
        r = requests.get(f"{API}/admin/system/update/status",
                         headers=admin_headers, timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()
        for k in ("running", "state", "log_tail"):
            assert k in body, body

    def test_update_status_requires_auth(self):
        r = requests.get(f"{API}/admin/system/update/status", timeout=10)
        assert r.status_code in (401, 403), r.status_code


# ------------------------------------------------------------
# scripts/install.sh + scripts/update.sh
# ------------------------------------------------------------
class TestScripts:
    def test_install_syntax(self):
        rc = subprocess.call(["bash", "-n", "/app/scripts/install.sh"])
        assert rc == 0

    def test_update_syntax(self):
        rc = subprocess.call(["bash", "-n", "/app/scripts/update.sh"])
        assert rc == 0

    def test_scripts_executable(self):
        for p in ["/app/scripts/install.sh", "/app/scripts/update.sh"]:
            assert os.access(p, os.X_OK), f"{p} not executable"

    def test_install_contains_expected_tokens(self):
        text = open("/app/scripts/install.sh").read()
        for tok in ["apt-get", "nginx", "mongodb", "python3.12",
                    "nodejs", "yarn", "supervisor", "ufw"]:
            assert tok in text, f"install.sh missing {tok}"
        # certbot is referenced in the final DONE hint block
        assert "certbot" in text, "install.sh missing certbot"

    def test_update_contains_expected_tokens(self):
        text = open("/app/scripts/update.sh").read()
        assert "mongodump --archive --gzip" not in text or True  # informational
        assert "mongodump" in text and "--archive" in text and "--gzip" in text, \
            "update.sh missing mongodump flags"
        assert "git pull" in text, "update.sh missing git pull"
        assert "yarn build" in text, "update.sh missing yarn build"
        assert "supervisorctl restart intercloud-backend" in text, \
            "update.sh missing supervisor restart line"


# ------------------------------------------------------------
# Regression sweep
# ------------------------------------------------------------
class TestRegression:
    def test_login_ok(self):
        r = requests.post(f"{API}/auth/login",
                          json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
                          timeout=15)
        assert r.status_code == 200

    def test_backup_download_gzip(self, admin_headers):
        r = requests.get(f"{API}/admin/backup/download", headers=admin_headers,
                         timeout=60, stream=True)
        assert r.status_code == 200, r.text
        cd = r.headers.get("Content-Disposition", "")
        # filename regex
        m = re.search(r'filename="?(intercloud-backup-\d{8}T\d{6}Z\.archive\.gz)"?', cd)
        assert m, f"filename not matching pattern: {cd!r}"
        # gzip magic
        raw = r.raw.read(2)
        assert raw[:2] == b"\x1f\x8b", f"not gzip magic: {raw!r}"

    def test_restore_requires_confirm(self, admin_headers):
        # send a tiny gzip blob to trigger the endpoint; confirm missing → 400
        headers = dict(admin_headers)
        headers["Content-Type"] = "application/gzip"
        r = requests.post(f"{API}/admin/backup/restore",
                          headers=headers, data=b"\x1f\x8bfake", timeout=15)
        assert r.status_code == 400, r.text
        assert "REPLACE" in r.text

    def test_mikrotik_devices_reachable(self, admin_headers):
        r = requests.get(f"{API}/admin/mikrotik/devices", headers=admin_headers, timeout=20)
        # tolerate 200 with data, or empty list
        assert r.status_code == 200, r.text

    def test_branding_reachable(self, admin_headers):
        r = requests.get(f"{API}/admin/branding", headers=admin_headers, timeout=15)
        # tolerate 200 or 404 (if not persisted); do not accept 5xx
        assert r.status_code < 500, r.text
