"""Backend tests for MikroTik multi-device support + real RouterOS calls.

Covers:
- Devices CRUD (create/list/get/update/delete) at /admin/mikrotik/devices
- Password NOT overwritten when payload sends password=""
- POST /devices/{id}/test → {ok:false, message} for unreachable device (no 500)
- Live views (interfaces, bgp, system, traffic) return [] / {error} for unreachable
  device — endpoints MUST NOT return 500.
- Looking Glass (ping / traceroute / bgp_route) — validation + graceful ok:false
- Blackhole list/add/remove — validation + graceful ok:false
- Backup list/create — graceful ok:false
- Reboot — 400 without confirm='REBOOT', graceful ok:false with confirm
- Backward compat: legacy integration_settings.mikrotik fallback when no device_id
- RBAC: admin required (403 for client, 401 for no-token) across all endpoints

Test host: 127.0.0.1:8728 → ConnectionRefused (fast, deterministic).
Cleanup: deletes created devices in teardown + disables legacy mikrotik integration.
"""
import os
import time
import pytest
import requests

# Serialize with other suites that mutate integration_settings.mikrotik
# (test_diagnostics_and_security.py) since we also toggle the legacy integration.
pytestmark = pytest.mark.xdist_group("recaptcha_shared")

LOCAL_API = "http://localhost:8001/api/portal"
PUBLIC_API = (os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
              + "/api/portal") if os.environ.get("REACT_APP_BACKEND_URL") else None

ADMIN_EMAIL = "admin@intercloud-digital.com"
ADMIN_PASSWORD = "AdminIntercloud2026!"
CLIENT_EMAIL = "demo@client.com"
CLIENT_PASSWORD = "ClientDemo2026!"


def _login(email, password):
    return requests.post(f"{LOCAL_API}/auth/login",
                         json={"email": email, "password": password},
                         timeout=20)


def _h(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


# ---- fixtures -----------------------------------------------------------

@pytest.fixture(scope="module")
def admin_token():
    r = _login(ADMIN_EMAIL, ADMIN_PASSWORD)
    if r.status_code == 429:
        pytest.skip("Admin login blocked (429). Clear blocked_ips manually.")
    if r.status_code != 200:
        pytest.skip(f"Admin login failed: {r.status_code} {r.text}")
    return r.json()["token"]


@pytest.fixture(scope="module")
def admin_headers(admin_token):
    return _h(admin_token)


@pytest.fixture(scope="module")
def client_token():
    r = _login(CLIENT_EMAIL, CLIENT_PASSWORD)
    if r.status_code != 200:
        pytest.skip(f"Client login failed: {r.status_code} {r.text}")
    return r.json()["token"]


@pytest.fixture(scope="module", autouse=True)
def _ensure_mikrotik_disabled(admin_headers):
    """Ensure legacy /integrations-v2/mikrotik is disabled before + after this
    suite so 'empty array' invariant holds and we don't leak state to other
    suites."""
    def _disable():
        requests.put(f"{LOCAL_API}/admin/integrations-v2/mikrotik",
                     headers=admin_headers,
                     json={"enabled": False, "credentials": {}, "options": {}},
                     timeout=15)
    _disable()
    yield
    _disable()


@pytest.fixture(scope="module")
def device_id(admin_headers):
    """Create a shared test device (host=127.0.0.1:8728 → ConnectionRefused fast).
    Class ordering in xdist is non-deterministic, so we ALWAYS create up front
    and delete at teardown. Tests that verify the create/delete workflow
    themselves use separate ad-hoc devices."""
    payload = {
        "name": "TEST_shared_router",
        "host": "127.0.0.1",
        "port": 8728,
        "username": "TEST_admin",
        "password": "TEST_secret_pw",
        "use_tls": False,
        "site": "TEST_DC1",
        "notes": "shared test device",
    }
    r = requests.post(f"{LOCAL_API}/admin/mikrotik/devices",
                      headers=admin_headers, json=payload, timeout=15)
    assert r.status_code == 200, f"failed to create shared device: {r.text}"
    did = r.json()["id"]
    yield did
    requests.delete(f"{LOCAL_API}/admin/mikrotik/devices/{did}",
                    headers=admin_headers, timeout=15)


@pytest.fixture(scope="module")
def created_devices(admin_headers):
    """Track ad-hoc devices created during the suite; teardown deletes them.
    Kept for possible future use — currently unused (each test class owns its
    device via `device_id` module fixture or `crud_device` class fixture)."""
    ids = []
    yield ids
    for did in ids:
        try:
            requests.delete(f"{LOCAL_API}/admin/mikrotik/devices/{did}",
                            headers=admin_headers, timeout=15)
        except Exception:
            pass


@pytest.fixture(scope="class")
def crud_device(admin_headers):
    """Dedicated device for TestDevicesCrud so it's isolated from the shared
    `device_id` used by other classes (which don't want us mutating password)."""
    payload = {
        "name": "TEST_router1",
        "host": "127.0.0.1",
        "port": 8728,
        "username": "TEST_admin",
        "password": "TEST_secret_pw",
        "use_tls": False,
        "site": "TEST_DC1",
        "notes": "Test device — safe to delete",
    }
    r = requests.post(f"{LOCAL_API}/admin/mikrotik/devices",
                      headers=admin_headers, json=payload, timeout=15)
    assert r.status_code == 200, r.text
    data = r.json()
    yield data
    try:
        requests.delete(f"{LOCAL_API}/admin/mikrotik/devices/{data['id']}",
                        headers=admin_headers, timeout=15)
    except Exception:
        pass


# ============================================================
# 1. DEVICES CRUD
# ============================================================

class TestDevicesCrud:
    def test_01_initial_list_no_legacy(self, admin_headers):
        """When legacy mikrotik integration is DISABLED, the list should not
        include a legacy entry. It might still contain devices from prior
        aborted runs — we only assert the shape and that no legacy row is
        present (id is None + name 'Legacy (Integrations)')."""
        r = requests.get(f"{LOCAL_API}/admin/mikrotik/devices",
                         headers=admin_headers, timeout=15)
        assert r.status_code == 200, r.text
        data = r.json()
        assert isinstance(data, list)
        legacy_rows = [d for d in data if d.get("legacy") is True]
        assert legacy_rows == [], f"Legacy row present with disabled integration: {legacy_rows}"

    def test_02_create_device(self, crud_device):
        data = crud_device
        assert "id" in data and data["id"], data
        assert data["name"] == "TEST_router1"
        assert data["host"] == "127.0.0.1"
        assert data["port"] == 8728
        assert data["username"] == "TEST_admin"
        assert data["use_tls"] is False
        assert data["site"] == "TEST_DC1"
        # CRITICAL: password must NOT be in the response
        assert "password" not in data, f"password leaked in response: {data}"

    def test_03_get_device_via_list(self, admin_headers, crud_device):
        did = crud_device["id"]
        r = requests.get(f"{LOCAL_API}/admin/mikrotik/devices",
                         headers=admin_headers, timeout=15)
        assert r.status_code == 200, r.text
        docs = r.json()
        found = next((d for d in docs if d.get("id") == did), None)
        assert found, f"Created device {did} not returned in list"
        assert "password" not in found, f"password leaked in list: {found}"

    def test_04_create_missing_host_400(self, admin_headers):
        r = requests.post(f"{LOCAL_API}/admin/mikrotik/devices",
                          headers=admin_headers,
                          json={"name": "TEST_bad", "username": "u",
                                "password": "p"},
                          timeout=15)
        assert r.status_code == 400, r.text
        assert "host" in (r.json().get("detail") or "").lower()

    def test_05_update_device_fields(self, admin_headers, crud_device):
        did = crud_device["id"]
        r = requests.put(f"{LOCAL_API}/admin/mikrotik/devices/{did}",
                         headers=admin_headers,
                         json={"name": "TEST_router1_v2",
                               "site": "TEST_DC2",
                               "notes": "renamed"},
                         timeout=15)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["name"] == "TEST_router1_v2"
        assert data["site"] == "TEST_DC2"

    def test_06_update_empty_password_does_not_overwrite(self, admin_headers,
                                                        crud_device):
        """Sending password='' MUST NOT overwrite the stored password."""
        did = crud_device["id"]
        r = requests.put(f"{LOCAL_API}/admin/mikrotik/devices/{did}",
                         headers=admin_headers,
                         json={"password": "", "notes": "empty-pw-ignored"},
                         timeout=15)
        assert r.status_code == 200, r.text
        import asyncio
        from motor.motor_asyncio import AsyncIOMotorClient
        from bson import ObjectId

        async def _read():
            mc = AsyncIOMotorClient(
                os.environ.get("MONGO_URL", "mongodb://localhost:27017"))
            db = mc[os.environ.get("DB_NAME", "intercloud_portal")]
            return await db.mikrotik_devices.find_one({"_id": ObjectId(did)})

        doc = asyncio.run(_read())
        assert doc is not None, "device row disappeared"
        assert doc.get("password") == "TEST_secret_pw", (
            f"Empty password overwrote stored password! got={doc.get('password')!r}")
        assert doc.get("notes") == "empty-pw-ignored"

    def test_07_update_nonempty_password_persists(self, admin_headers,
                                                  crud_device):
        did = crud_device["id"]
        r = requests.put(f"{LOCAL_API}/admin/mikrotik/devices/{did}",
                         headers=admin_headers,
                         json={"password": "TEST_new_pw"},
                         timeout=15)
        assert r.status_code == 200, r.text
        import asyncio
        from motor.motor_asyncio import AsyncIOMotorClient
        from bson import ObjectId

        async def _read():
            mc = AsyncIOMotorClient(
                os.environ.get("MONGO_URL", "mongodb://localhost:27017"))
            db = mc[os.environ.get("DB_NAME", "intercloud_portal")]
            return await db.mikrotik_devices.find_one({"_id": ObjectId(did)})

        doc = asyncio.run(_read())
        assert doc.get("password") == "TEST_new_pw"

    def test_08_update_missing_device_404(self, admin_headers):
        r = requests.put(f"{LOCAL_API}/admin/mikrotik/devices/000000000000000000000000",
                         headers=admin_headers,
                         json={"name": "nope"},
                         timeout=15)
        assert r.status_code == 404, r.text

    def test_09_test_endpoint_returns_ok_false(self, admin_headers,
                                               crud_device):
        did = crud_device["id"]
        r = requests.post(f"{LOCAL_API}/admin/mikrotik/devices/{did}/test",
                          headers=admin_headers, timeout=30)
        # librouteros against 127.0.0.1:8728 must fast-fail with a JSON
        # ok:false, message body — NEVER 500.
        assert r.status_code == 200, r.text
        data = r.json()
        assert data.get("ok") is False, data
        assert "message" in data and data["message"], data


# ============================================================
# 2. LIVE VIEWS — unreachable device → graceful degradation
# ============================================================

class TestLiveViews:
    def test_10_interfaces_returns_empty_list(self, admin_headers,
                                              device_id):
        did = device_id
        r = requests.get(f"{LOCAL_API}/admin/mikrotik/interfaces",
                         headers=admin_headers,
                         params={"device_id": did}, timeout=30)
        assert r.status_code == 200, r.text
        assert r.json() == []

    def test_11_bgp_returns_empty_list(self, admin_headers, device_id):
        did = device_id
        r = requests.get(f"{LOCAL_API}/admin/mikrotik/bgp",
                         headers=admin_headers,
                         params={"device_id": did}, timeout=30)
        assert r.status_code == 200, r.text
        assert r.json() == []

    def test_12_system_returns_error_dict(self, admin_headers, device_id):
        did = device_id
        r = requests.get(f"{LOCAL_API}/admin/mikrotik/system",
                         headers=admin_headers,
                         params={"device_id": did}, timeout=30)
        assert r.status_code == 200, r.text
        data = r.json()
        assert isinstance(data, dict)
        assert "error" in data and data["error"], data

    def test_13_traffic_returns_error_dict(self, admin_headers, device_id):
        did = device_id
        r = requests.get(f"{LOCAL_API}/admin/mikrotik/traffic",
                         headers=admin_headers,
                         params={"device_id": did, "interface": "ether1"},
                         timeout=30)
        assert r.status_code == 200, r.text
        data = r.json()
        assert isinstance(data, dict)
        assert "error" in data, data


# ============================================================
# 3. LOOKING GLASS
# ============================================================

class TestLookingGlass:
    def test_14_ping_unreachable_ok_false(self, admin_headers, device_id):
        did = device_id
        r = requests.post(f"{LOCAL_API}/admin/mikrotik/looking-glass",
                          headers=admin_headers,
                          json={"device_id": did, "tool": "ping",
                                "target": "8.8.8.8"},
                          timeout=30)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data.get("ok") is False, data
        assert "error" in data and data["error"]
        assert data.get("rows") == []

    def test_15_traceroute_unreachable_ok_false(self, admin_headers,
                                                device_id):
        did = device_id
        r = requests.post(f"{LOCAL_API}/admin/mikrotik/looking-glass",
                          headers=admin_headers,
                          json={"device_id": did, "tool": "traceroute",
                                "target": "8.8.8.8"},
                          timeout=30)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data.get("ok") is False, data
        assert data.get("rows") == []

    def test_16_bgp_route_unreachable_ok_false(self, admin_headers,
                                               device_id):
        did = device_id
        r = requests.post(f"{LOCAL_API}/admin/mikrotik/looking-glass",
                          headers=admin_headers,
                          json={"device_id": did, "tool": "bgp_route",
                                "target": "8.8.8.0"},
                          timeout=30)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data.get("ok") is False, data

    def test_17_looking_glass_invalid_tool_400(self, admin_headers,
                                               device_id):
        did = device_id
        r = requests.post(f"{LOCAL_API}/admin/mikrotik/looking-glass",
                          headers=admin_headers,
                          json={"device_id": did, "tool": "xxx",
                                "target": "8.8.8.8"},
                          timeout=15)
        assert r.status_code == 400, r.text
        assert "tool" in (r.json().get("detail") or "").lower()

    def test_18_looking_glass_missing_target_400(self, admin_headers,
                                                 device_id):
        did = device_id
        r = requests.post(f"{LOCAL_API}/admin/mikrotik/looking-glass",
                          headers=admin_headers,
                          json={"device_id": did, "tool": "ping"},
                          timeout=15)
        assert r.status_code == 400, r.text
        assert "target" in (r.json().get("detail") or "").lower()


# ============================================================
# 4. BLACKHOLE
# ============================================================

class TestBlackhole:
    def test_19_blackhole_list_unreachable_empty(self, admin_headers,
                                                 device_id):
        did = device_id
        r = requests.get(f"{LOCAL_API}/admin/mikrotik/blackhole",
                         headers=admin_headers,
                         params={"device_id": did}, timeout=30)
        assert r.status_code == 200, r.text
        assert r.json() == []

    def test_20_blackhole_add_unreachable_ok_false(self, admin_headers,
                                                   device_id):
        did = device_id
        r = requests.post(f"{LOCAL_API}/admin/mikrotik/blackhole",
                          headers=admin_headers,
                          json={"device_id": did,
                                "prefix": "203.0.113.42/32"},
                          timeout=30)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data.get("ok") is False, data
        assert "error" in data

    def test_21_blackhole_add_missing_prefix_400(self, admin_headers,
                                                 device_id):
        did = device_id
        r = requests.post(f"{LOCAL_API}/admin/mikrotik/blackhole",
                          headers=admin_headers,
                          json={"device_id": did, "prefix": ""},
                          timeout=15)
        assert r.status_code == 400, r.text
        assert "prefix" in (r.json().get("detail") or "").lower()

    def test_22_blackhole_remove_unreachable_ok_false(self, admin_headers,
                                                     device_id):
        did = device_id
        r = requests.delete(f"{LOCAL_API}/admin/mikrotik/blackhole/fakerouteid",
                            headers=admin_headers,
                            params={"device_id": did}, timeout=30)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data.get("ok") is False, data
        assert "error" in data


# ============================================================
# 5. BACKUPS
# ============================================================

class TestBackups:
    def test_23_backups_list_unreachable_empty(self, admin_headers,
                                               device_id):
        did = device_id
        r = requests.get(f"{LOCAL_API}/admin/mikrotik/backups",
                         headers=admin_headers,
                         params={"device_id": did}, timeout=30)
        assert r.status_code == 200, r.text
        assert r.json() == []

    def test_24_backups_create_unreachable_ok_false(self, admin_headers,
                                                    device_id):
        did = device_id
        r = requests.post(f"{LOCAL_API}/admin/mikrotik/backups",
                          headers=admin_headers,
                          json={"device_id": did, "name": "TEST_backup"},
                          timeout=30)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data.get("ok") is False, data
        assert "error" in data


# ============================================================
# 6. REBOOT
# ============================================================

class TestReboot:
    def test_25_reboot_without_confirm_400(self, admin_headers,
                                           device_id):
        did = device_id
        r = requests.post(f"{LOCAL_API}/admin/mikrotik/reboot",
                          headers=admin_headers,
                          json={"device_id": did},
                          timeout=15)
        assert r.status_code == 400, r.text
        detail = (r.json().get("detail") or "").lower()
        assert "confirm" in detail and "reboot" in detail, r.text

    def test_26_reboot_wrong_confirm_400(self, admin_headers, device_id):
        did = device_id
        r = requests.post(f"{LOCAL_API}/admin/mikrotik/reboot",
                          headers=admin_headers,
                          json={"device_id": did, "confirm": "yes"},
                          timeout=15)
        assert r.status_code == 400, r.text

    def test_27_reboot_confirmed_unreachable_ok_false(self, admin_headers,
                                                     device_id):
        did = device_id
        r = requests.post(f"{LOCAL_API}/admin/mikrotik/reboot",
                          headers=admin_headers,
                          json={"device_id": did, "confirm": "REBOOT"},
                          timeout=30)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data.get("ok") is False, data
        assert "error" in data


# ============================================================
# 7. BACKWARD COMPAT — legacy integration_settings.mikrotik fallback
# ============================================================

class TestLegacyFallback:
    def test_28_no_device_id_no_integration_400(self, admin_headers):
        """When no device_id is given AND legacy integration is disabled,
        the resolver should raise 400 (Mikrotik not configured)."""
        # Ensure legacy is disabled
        requests.put(f"{LOCAL_API}/admin/integrations-v2/mikrotik",
                     headers=admin_headers,
                     json={"enabled": False, "credentials": {}, "options": {}},
                     timeout=15)
        r = requests.get(f"{LOCAL_API}/admin/mikrotik/interfaces",
                         headers=admin_headers, timeout=15)
        assert r.status_code == 400, r.text
        detail = (r.json().get("detail") or "").lower()
        assert "mikrotik" in detail and "not configured" in detail, r.text

    def test_29_no_device_id_with_legacy_falls_back(self, admin_headers):
        """Enable legacy integration with fake credentials (127.0.0.1:8728) —
        endpoints without device_id must resolve via the legacy fallback and
        return [] (unreachable) — NOT 500 and NOT 400."""
        rp = requests.put(f"{LOCAL_API}/admin/integrations-v2/mikrotik",
                          headers=admin_headers,
                          json={"enabled": True,
                                "credentials": {"host": "127.0.0.1",
                                                "port": 8728,
                                                "username": "legacy",
                                                "password": "legacy"},
                                "options": {}},
                          timeout=15)
        assert rp.status_code == 200, rp.text
        try:
            r = requests.get(f"{LOCAL_API}/admin/mikrotik/interfaces",
                             headers=admin_headers, timeout=30)
            assert r.status_code == 200, r.text
            assert r.json() == []
            # And devices list should now include a legacy row
            rl = requests.get(f"{LOCAL_API}/admin/mikrotik/devices",
                              headers=admin_headers, timeout=15)
            assert rl.status_code == 200
            legacy_rows = [d for d in rl.json() if d.get("legacy") is True]
            assert len(legacy_rows) == 1, rl.json()
            assert legacy_rows[0]["host"] == "127.0.0.1"
        finally:
            # Cleanup — module fixture also disables, but do it here so
            # subsequent tests in this class see disabled state.
            requests.put(f"{LOCAL_API}/admin/integrations-v2/mikrotik",
                         headers=admin_headers,
                         json={"enabled": False, "credentials": {},
                               "options": {}},
                         timeout=15)


# ============================================================
# 8. RBAC — admin required across all mikrotik endpoints
# ============================================================

class TestRbac:
    ENDPOINTS_GET = [
        "/admin/mikrotik/devices",
        "/admin/mikrotik/interfaces",
        "/admin/mikrotik/bgp",
        "/admin/mikrotik/system",
        "/admin/mikrotik/blackhole",
        "/admin/mikrotik/backups",
    ]
    ENDPOINTS_POST = [
        ("/admin/mikrotik/devices", {"host": "x", "username": "x"}),
        ("/admin/mikrotik/looking-glass",
         {"tool": "ping", "target": "8.8.8.8"}),
        ("/admin/mikrotik/blackhole", {"prefix": "203.0.113.1/32"}),
        ("/admin/mikrotik/backups", {}),
        ("/admin/mikrotik/reboot", {"confirm": "REBOOT"}),
    ]

    def test_30_get_endpoints_no_token_401(self):
        for ep in self.ENDPOINTS_GET:
            r = requests.get(f"{LOCAL_API}{ep}", timeout=10)
            assert r.status_code == 401, f"{ep}: {r.status_code} {r.text}"

    def test_31_get_endpoints_client_403(self, client_token):
        for ep in self.ENDPOINTS_GET:
            r = requests.get(f"{LOCAL_API}{ep}",
                             headers=_h(client_token), timeout=10)
            assert r.status_code == 403, f"{ep}: {r.status_code} {r.text}"

    def test_32_post_endpoints_no_token_401(self):
        for ep, body in self.ENDPOINTS_POST:
            r = requests.post(f"{LOCAL_API}{ep}", json=body, timeout=10)
            assert r.status_code == 401, f"{ep}: {r.status_code} {r.text}"

    def test_33_post_endpoints_client_403(self, client_token):
        for ep, body in self.ENDPOINTS_POST:
            r = requests.post(f"{LOCAL_API}{ep}",
                              headers=_h(client_token),
                              json=body, timeout=10)
            assert r.status_code == 403, f"{ep}: {r.status_code} {r.text}"


# ============================================================
# 9. DELETE device (last — cleanup happens through fixture too)
# ============================================================

class TestDeleteDevice:
    def test_34_delete_device(self, admin_headers):
        # Create a dedicated device for this test — isolated from the shared one
        create = requests.post(f"{LOCAL_API}/admin/mikrotik/devices",
                               headers=admin_headers,
                               json={"name": "TEST_to_delete",
                                     "host": "127.0.0.1", "port": 8728,
                                     "username": "u", "password": "p"},
                               timeout=15)
        assert create.status_code == 200, create.text
        did = create.json()["id"]
        r = requests.delete(f"{LOCAL_API}/admin/mikrotik/devices/{did}",
                            headers=admin_headers, timeout=15)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data.get("ok") is True, data
        assert data.get("deleted") == 1, data
        # Verify it's gone
        r2 = requests.get(f"{LOCAL_API}/admin/mikrotik/devices",
                          headers=admin_headers, timeout=15)
        assert r2.status_code == 200
        ids = [d.get("id") for d in r2.json()]
        assert did not in ids

    def test_35_delete_missing_device_zero(self, admin_headers):
        r = requests.delete(f"{LOCAL_API}/admin/mikrotik/devices/000000000000000000000000",
                            headers=admin_headers, timeout=15)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data.get("ok") is True
        assert data.get("deleted") == 0
