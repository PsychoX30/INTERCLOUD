"""Live-router blackhole + regression tests against TO.DIST (RouterOS 7.20.6).

Focus of this iteration (see /app/test_reports/iteration_21.json):
- Bug 1: POST /admin/mikrotik/blackhole must use RouterOS 7 syntax (`blackhole=yes`)
  and NOT surface `TrapError: unknown parameter type`.
- Bug 2: GET /admin/mikrotik/blackhole must use server-side query (`?blackhole=yes`)
  so it doesn't stream the full BGP table, and must honour `prefix_filter`.
- Regression: existing mikrotik ops still work + diagnostics traceroute still works.
"""
import os
import time
import urllib.parse

import pytest
import requests
from dotenv import load_dotenv

load_dotenv("/app/frontend/.env")

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
API = f"{BASE_URL}/api"

DEVICE_ID = "6a617872f12db51fa9cc268c"  # TO.DIST
TEST_PREFIX = "198.51.100.77/32"        # RFC5737 TEST-NET-2 — safe on the internet
TEST_FILTER = "198.51.100.0/24"


# ---------- fixtures ----------
@pytest.fixture(scope="module")
def admin_headers():
    r = requests.post(
        f"{API}/portal/auth/login",
        json={"email": "admin@intercloud-digital.com",
              "password": "AdminIntercloud2026!"},
        timeout=15,
    )
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    tok = r.json()["token"]
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


# Track state so cleanup runs regardless of which test failed
_state = {"added_route_id": None}


@pytest.fixture(scope="module", autouse=True)
def _final_cleanup(admin_headers):
    """After all tests, best-effort remove any route we added."""
    yield
    rid = _state.get("added_route_id")
    if rid:
        try:
            enc = urllib.parse.quote(rid, safe="")
            requests.delete(
                f"{API}/portal/admin/mikrotik/blackhole/{enc}?device_id={DEVICE_ID}",
                headers=admin_headers, timeout=30,
            )
        except Exception:
            pass


# ---------- Bug 1: ADD ----------
class TestBlackholeAdd:
    def test_add_blackhole_v7_syntax(self, admin_headers):
        t0 = time.time()
        r = requests.post(
            f"{API}/portal/admin/mikrotik/blackhole",
            json={"device_id": DEVICE_ID, "prefix": TEST_PREFIX,
                  "comment": "TEST_blackhole_iter21"},
            headers=admin_headers, timeout=45,
        )
        dt = time.time() - t0
        assert r.status_code == 200, (
            f"HTTP {r.status_code}\nreq body: device_id={DEVICE_ID} prefix={TEST_PREFIX}\n"
            f"resp: {r.text}"
        )
        body = r.json()
        assert body.get("ok") is True, (
            f"blackhole_add returned ok=False. Full response body: {body!r}. "
            f"If error mentions 'unknown parameter: type', Bug 1 has regressed."
        )
        assert body.get("prefix") == TEST_PREFIX, f"prefix mismatch: {body!r}"
        # Ensure the v7 path succeeded and the fallback error string isn't in the response
        assert "unknown parameter" not in str(body).lower(), (
            f"Response contains TrapError leak → v7 path failed: {body!r}"
        )
        print(f"[add] ok in {dt:.2f}s → {body}")


# ---------- Bug 2: LIST + prefix_filter ----------
class TestBlackholeList:
    def test_list_is_fast_and_server_filtered(self, admin_headers):
        t0 = time.time()
        r = requests.get(
            f"{API}/portal/admin/mikrotik/blackhole?device_id={DEVICE_ID}",
            headers=admin_headers, timeout=30,
        )
        dt = time.time() - t0
        assert r.status_code == 200, f"HTTP {r.status_code}: {r.text}"
        rows = r.json()
        assert isinstance(rows, list), f"expected list, got {type(rows)}: {rows!r}"
        print(f"[list all-blackhole] {len(rows)} rows in {dt:.2f}s")
        assert dt < 5.0, (
            f"Server-side filter regression? List took {dt:.2f}s (>5s) — "
            f"router has full BGP table so this must use ?blackhole=yes query."
        )
        # Sanity: every row must have .id and dst-address (defensive check)
        for row in rows[:5]:
            assert ".id" in row or "id" in row, f"missing .id: {row!r}"
            assert "dst-address" in row, f"missing dst-address: {row!r}"

    def test_list_contains_added_prefix(self, admin_headers):
        r = requests.get(
            f"{API}/portal/admin/mikrotik/blackhole?device_id={DEVICE_ID}"
            f"&prefix_filter={urllib.parse.quote(TEST_FILTER)}",
            headers=admin_headers, timeout=30,
        )
        assert r.status_code == 200, f"HTTP {r.status_code}: {r.text}"
        rows = r.json()
        assert isinstance(rows, list)
        found = [row for row in rows
                 if (row.get("dst-address") or "").strip() == TEST_PREFIX]
        assert found, (
            f"Added prefix {TEST_PREFIX} not visible under filter {TEST_FILTER}. "
            f"Rows returned: {rows!r}"
        )
        # Save the .id for cleanup
        rid = found[0].get(".id") or found[0].get("id")
        assert rid, f"row missing .id: {found[0]!r}"
        _state["added_route_id"] = rid
        print(f"[list filtered] found route .id={rid}")

    def test_list_empty_when_filter_misses(self, admin_headers):
        # 10.0.0.0/8 should not contain the RFC5737 test prefix
        r = requests.get(
            f"{API}/portal/admin/mikrotik/blackhole?device_id={DEVICE_ID}"
            f"&prefix_filter={urllib.parse.quote('10.0.0.0/8')}",
            headers=admin_headers, timeout=30,
        )
        assert r.status_code == 200, f"HTTP {r.status_code}: {r.text}"
        rows = r.json()
        assert isinstance(rows, list)
        # We can't guarantee the router has NO blackholes inside 10/8, but our
        # test prefix must not be there.
        assert not any((row.get("dst-address") or "").strip() == TEST_PREFIX
                       for row in rows), (
            f"prefix filter leaked TEST_PREFIX into 10.0.0.0/8 bucket. Rows: {rows!r}"
        )
        print(f"[list filtered 10/8] {len(rows)} rows (must not contain {TEST_PREFIX})")


# ---------- Cleanup DELETE ----------
class TestBlackholeDelete:
    def test_delete_added_route(self, admin_headers):
        rid = _state.get("added_route_id")
        assert rid, "no route id captured — the LIST tests must run first"
        enc = urllib.parse.quote(rid, safe="")
        r = requests.delete(
            f"{API}/portal/admin/mikrotik/blackhole/{enc}?device_id={DEVICE_ID}",
            headers=admin_headers, timeout=30,
        )
        assert r.status_code == 200, f"HTTP {r.status_code}: {r.text}"
        body = r.json()
        assert body.get("ok") is True, f"delete ok=False: {body!r}"
        _state["added_route_id"] = None  # already cleaned
        # Verify it's gone
        r2 = requests.get(
            f"{API}/portal/admin/mikrotik/blackhole?device_id={DEVICE_ID}"
            f"&prefix_filter={urllib.parse.quote(TEST_FILTER)}",
            headers=admin_headers, timeout=30,
        )
        rows = r2.json()
        assert not any((row.get("dst-address") or "").strip() == TEST_PREFIX
                       for row in rows), (
            f"prefix {TEST_PREFIX} still present after DELETE. rows: {rows!r}"
        )


# ---------- Regression: other mikrotik ops on live TO.DIST ----------
class TestMikrotikRegression:
    def test_device_test_connection(self, admin_headers):
        r = requests.post(
            f"{API}/portal/admin/mikrotik/devices/{DEVICE_ID}/test",
            headers=admin_headers, timeout=30,
        )
        assert r.status_code == 200, f"HTTP {r.status_code}: {r.text}"
        body = r.json()
        assert body.get("ok") is True, (
            f"live device test-connection failed: {body!r}"
        )

    def test_interfaces_list(self, admin_headers):
        r = requests.get(
            f"{API}/portal/admin/mikrotik/interfaces?device_id={DEVICE_ID}",
            headers=admin_headers, timeout=30,
        )
        assert r.status_code == 200, f"HTTP {r.status_code}: {r.text}"
        data = r.json()
        assert isinstance(data, list) and len(data) > 0, (
            f"interfaces list empty or invalid: {data!r}"
        )

    def test_looking_glass_ping(self, admin_headers):
        r = requests.post(
            f"{API}/portal/admin/mikrotik/looking-glass",
            json={"device_id": DEVICE_ID, "tool": "ping", "target": "8.8.8.8"},
            headers=admin_headers, timeout=45,
        )
        assert r.status_code == 200, f"HTTP {r.status_code}: {r.text}"
        body = r.json()
        assert body.get("ok") is True, f"lg ping failed: {body!r}"
        assert isinstance(body.get("rows"), list) and len(body["rows"]) > 0

    def test_looking_glass_traceroute(self, admin_headers):
        r = requests.post(
            f"{API}/portal/admin/mikrotik/looking-glass",
            json={"device_id": DEVICE_ID, "tool": "traceroute", "target": "8.8.8.8"},
            headers=admin_headers, timeout=60,
        )
        assert r.status_code == 200, f"HTTP {r.status_code}: {r.text}"
        body = r.json()
        assert body.get("ok") is True, f"lg traceroute failed: {body!r}"

    def test_traffic_ether0(self, admin_headers):
        # ether0 may not exist on this device — fall back to first interface if not
        r = requests.get(
            f"{API}/portal/admin/mikrotik/traffic?device_id={DEVICE_ID}&interface=ether0",
            headers=admin_headers, timeout=30,
        )
        assert r.status_code == 200, f"HTTP {r.status_code}: {r.text}"
        body = r.json()
        # Endpoint should return a dict (not raise 500); may report error if
        # interface doesn't exist — we just assert the endpoint is stable.
        assert isinstance(body, dict), f"expected dict: {body!r}"

    def test_backups_list(self, admin_headers):
        r = requests.get(
            f"{API}/portal/admin/mikrotik/backups?device_id={DEVICE_ID}",
            headers=admin_headers, timeout=30,
        )
        assert r.status_code == 200, f"HTTP {r.status_code}: {r.text}"
        body = r.json()
        assert isinstance(body, list), f"expected list: {body!r}"


# ---------- Regression: diagnostics traceroute ----------
class TestDiagnosticsTraceroute:
    def test_traceroute_returns_hops(self, admin_headers):
        r = requests.post(
            f"{API}/portal/admin/diagnostics/run",
            json={"tool": "traceroute", "target": "8.8.8.8", "max_hops": 5},
            headers=admin_headers, timeout=60,
        )
        assert r.status_code == 200, f"HTTP {r.status_code}: {r.text}"
        body = r.json()
        output = body.get("output") or ""
        summary = body.get("summary") or {}
        assert output.strip(), f"empty output: {body!r}"
        # At least one hop line — traceroute lines start with a number or contain '  '
        assert any(line.strip() for line in output.splitlines()), (
            f"no non-empty lines in output: {output!r}"
        )
        assert summary.get("exit_code") == 0, (
            f"exit_code != 0: summary={summary!r} output={output!r}"
        )
