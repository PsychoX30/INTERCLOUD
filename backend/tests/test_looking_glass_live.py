"""Iteration-22 live tests for POST /api/portal/admin/mikrotik/looking-glass.

Covers the two fixes reported by the main agent:
 1. BGP Route Lookup now performs a longest-prefix scan and returns the
    covering CIDR for a HOST IP (bug: previous `startswith` filter never
    matched a /24 for a bare /32 host).
 2. Ping/Traceroute accept an optional `src_address` that is forwarded to
    RouterOS as `src-address=…`.

Plus regression coverage on the other mikrotik admin ops.

Requires the live TO.DIST device — id 6a617872f12db51fa9cc268c, RouterOS
7.20.6 at 157.20.32.253:8777. A valid src-address is 157.20.32.253.
"""
from __future__ import annotations
import os
import ipaddress
import time
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    # Fallback: read frontend/.env (test env may not export it)
    try:
        with open("/app/frontend/.env") as f:
            for line in f:
                if line.startswith("REACT_APP_BACKEND_URL="):
                    BASE_URL = line.split("=", 1)[1].strip().rstrip("/")
                    break
    except Exception:
        pass
assert BASE_URL, "REACT_APP_BACKEND_URL must be set"

ADMIN_EMAIL = "admin@intercloud-digital.com"
ADMIN_PASSWORD = "AdminIntercloud2026!"
DEVICE_ID = "6a617872f12db51fa9cc268c"
DEVICE_SRC = "157.20.32.253"

LG_URL = f"{BASE_URL}/api/portal/admin/mikrotik/looking-glass"


@pytest.fixture(scope="module")
def token() -> str:
    r = requests.post(f"{BASE_URL}/api/portal/auth/login",
                      json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
                      timeout=15)
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    tok = r.json().get("token")
    assert tok, "no token in login response"
    return tok


@pytest.fixture(scope="module")
def s(token) -> requests.Session:
    sess = requests.Session()
    sess.headers.update({
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    })
    return sess


# ---------- Bug 1: BGP Route Lookup ----------

class TestBgpRouteLookup:

    def test_bgp_covers_host_ip(self, s):
        """POST tool=bgp_route target=103.133.20.5 must return a covering
        CIDR (rows non-empty, match_prefix set, network contains target IP)."""
        t0 = time.time()
        r = s.post(LG_URL, json={
            "device_id": DEVICE_ID,
            "tool": "bgp_route",
            "target": "103.133.20.5",
        }, timeout=25)
        elapsed = time.time() - t0
        assert r.status_code == 200, f"{r.status_code} {r.text}"
        body = r.json()
        assert body.get("ok") is True, f"expected ok=true, got: {body}"
        rows = body.get("rows") or []
        assert rows, (
            "BGP lookup returned empty rows for host IP 103.133.20.5. "
            f"Full response: {body}"
        )
        match_prefix = body.get("match_prefix")
        assert match_prefix, f"match_prefix missing/null: {body}"
        # containment check
        net = ipaddress.ip_network(match_prefix, strict=False)
        assert ipaddress.ip_address("103.133.20.5") in net, (
            f"match_prefix {match_prefix} does not contain 103.133.20.5"
        )
        # rows[0]['dst-address'] must be a valid CIDR containing the target
        dst0 = rows[0].get("dst-address")
        assert dst0, f"rows[0] missing dst-address: {rows[0]}"
        net0 = ipaddress.ip_network(dst0, strict=False)
        assert ipaddress.ip_address("103.133.20.5") in net0, (
            f"rows[0]['dst-address']={dst0} does not contain 103.133.20.5"
        )
        assert elapsed < 20.0, f"BGP lookup too slow: {elapsed:.1f}s"

    def test_bgp_default_route(self, s):
        """target=0.0.0.0/0 → exact match, match_prefix must equal input."""
        r = s.post(LG_URL, json={
            "device_id": DEVICE_ID,
            "tool": "bgp_route",
            "target": "0.0.0.0/0",
        }, timeout=25)
        assert r.status_code == 200, f"{r.status_code} {r.text}"
        body = r.json()
        assert body.get("ok") is True, body
        assert body.get("match_prefix") == "0.0.0.0/0", body
        assert body.get("rows"), f"expected non-empty rows for default: {body}"

    def test_bgp_invalid_input_graceful(self, s):
        """Invalid IP must return 200 with ok=false + Invalid error message,
        NOT a 500."""
        r = s.post(LG_URL, json={
            "device_id": DEVICE_ID,
            "tool": "bgp_route",
            "target": "not-an-ip",
        }, timeout=15)
        assert r.status_code == 200, f"{r.status_code} {r.text}"
        body = r.json()
        assert body.get("ok") is False, body
        err = body.get("error") or ""
        assert "Invalid" in err, f"expected 'Invalid' in error, got: {body}"


# ---------- Bug 2: Ping/Traceroute src_address ----------

class TestLookingGlassSrcAddress:

    def test_ping_with_src_address(self, s):
        r = s.post(LG_URL, json={
            "device_id": DEVICE_ID,
            "tool": "ping",
            "target": "8.8.8.8",
            "src_address": DEVICE_SRC,
        }, timeout=25)
        assert r.status_code == 200, f"{r.status_code} {r.text}"
        body = r.json()
        assert body.get("ok") is True, body
        assert body.get("src_address") == DEVICE_SRC, (
            f"src_address not echoed: {body}"
        )
        rows = body.get("rows") or []
        assert rows, f"empty ping rows: {body}"
        # At least one row must have a positive/non-null time (real RTT).
        # RouterOS composite format: "14ms562us", "1s200ms", "500us", etc.
        import re
        _UNITS = {"h": 3.6e6, "m": 60000.0, "s": 1000.0, "ms": 1.0, "us": 1e-3, "ns": 1e-6}
        def _row_time(row):
            t = row.get("time")
            if t is None:
                return None
            if isinstance(t, (int, float)):
                return float(t)
            total = 0.0
            for num, unit in re.findall(r"(\d+(?:\.\d+)?)(h|ms|us|ns|s|m)", str(t)):
                total += float(num) * _UNITS.get(unit, 0.0)
            return total if total > 0 else None
        rtts = [_row_time(r_) for r_ in rows]
        good = [x for x in rtts if x is not None and x > 0]
        assert good, f"no positive RTT in rows: {rows}"

    def test_traceroute_with_src_address(self, s):
        r = s.post(LG_URL, json={
            "device_id": DEVICE_ID,
            "tool": "traceroute",
            "target": "1.1.1.1",
            "src_address": DEVICE_SRC,
        }, timeout=45)
        assert r.status_code == 200, f"{r.status_code} {r.text}"
        body = r.json()
        assert body.get("ok") is True, body
        assert body.get("src_address") == DEVICE_SRC, body
        rows = body.get("rows") or []
        assert rows, f"empty traceroute rows: {body}"
        # each row should include an address field (hop IP)
        addrs = [r_.get("address") for r_ in rows]
        assert any(a for a in addrs), (
            f"no hop address field in traceroute rows: {rows[:3]}"
        )

    def test_ping_without_src_address(self, s):
        r = s.post(LG_URL, json={
            "device_id": DEVICE_ID,
            "tool": "ping",
            "target": "8.8.8.8",
        }, timeout=25)
        assert r.status_code == 200, f"{r.status_code} {r.text}"
        body = r.json()
        assert body.get("ok") is True, body
        # src_address should be null / missing / None — never break the flow
        assert not body.get("src_address"), (
            f"src_address should be null when omitted: {body}"
        )
        assert body.get("rows"), f"empty rows: {body}"


# ---------- Regression: other mikrotik ops ----------

class TestMikrotikRegression:

    def test_device_test(self, s):
        r = s.post(f"{BASE_URL}/api/portal/admin/mikrotik/devices/{DEVICE_ID}/test",
                   json={}, timeout=25)
        assert r.status_code == 200, f"{r.status_code} {r.text}"
        body = r.json()
        assert body.get("ok") is True, body

    def test_interfaces_list(self, s):
        r = s.get(f"{BASE_URL}/api/portal/admin/mikrotik/interfaces",
                  params={"device_id": DEVICE_ID}, timeout=25)
        assert r.status_code == 200, f"{r.status_code} {r.text}"
        body = r.json()
        # Response shape: may be {rows:[...]} or list directly
        rows = body.get("rows") if isinstance(body, dict) else body
        assert isinstance(rows, list) and rows, f"no interfaces: {body}"
        assert any(x.get("name") for x in rows), f"no name field: {rows[:2]}"

    def test_traffic(self, s):
        # Pick a real interface first
        r_if = s.get(f"{BASE_URL}/api/portal/admin/mikrotik/interfaces",
                     params={"device_id": DEVICE_ID}, timeout=25)
        assert r_if.status_code == 200
        rows_if = r_if.json().get("rows") if isinstance(r_if.json(), dict) else r_if.json()
        assert rows_if, "no interfaces to sample traffic on"
        iface = rows_if[0]["name"]
        r = s.get(f"{BASE_URL}/api/portal/admin/mikrotik/traffic",
                  params={"interface": iface, "device_id": DEVICE_ID},
                  timeout=25)
        assert r.status_code == 200, f"{r.status_code} {r.text}"
        body = r.json()
        assert body.get("ok") is True or body.get("rx-bits-per-second") is not None \
            or body.get("rows") is not None or body.get("tx-bits-per-second") is not None, (
            f"unexpected traffic payload: {body}"
        )

    def test_blackhole_list(self, s):
        r = s.get(f"{BASE_URL}/api/portal/admin/mikrotik/blackhole",
                  params={"device_id": DEVICE_ID}, timeout=25)
        assert r.status_code == 200, f"{r.status_code} {r.text}"
        body = r.json()
        # Endpoint may return either a bare list or {ok:true, rows:[...]}
        if isinstance(body, list):
            assert True  # bare list is a valid plausible payload
        elif isinstance(body, dict):
            assert body.get("ok") is True or isinstance(body.get("rows"), list), body
        else:
            pytest.fail(f"unexpected type for blackhole payload: {type(body)}")

    def test_backups_list(self, s):
        r = s.get(f"{BASE_URL}/api/portal/admin/mikrotik/backups",
                  params={"device_id": DEVICE_ID}, timeout=25)
        assert r.status_code == 200, f"{r.status_code} {r.text}"
        body = r.json()
        if isinstance(body, list):
            assert True
        elif isinstance(body, dict):
            assert body.get("ok") is True or isinstance(body.get("rows"), list), body
        else:
            pytest.fail(f"unexpected type for backups payload: {type(body)}")
