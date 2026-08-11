"""Engine-level tests for the DDoS detection sweep.

These tests exercise the real ``run_ddos_detection_sweep`` logic against a
deterministic in-memory AsyncMockDB and a monkey-patched MikroTikClient that
returns canned Torch flows.  No live router, no network, no MongoDB.

Coverage (10 cases):
 1. Inbound attack: blackholes the internal DESTINATION.
 2. Outbound attack: blackholes the internal SOURCE.
 3. Threshold not breached: no incident opened.
 4. Rolling window: averaged across multiple samples.
 5. Dedup: existing active incident is updated, not duplicated.
 6. Lifecycle: mitigated incident auto-resolves after grace period.
 7. Evidence: incident carries src_ip, dst_ip, protocol, src_port, dst_port.
 8. Whitelist: auto-blackhole denied for gateway IP → incident stays active.
 9. Direction filter: outbound rule ignores inbound traffic.
10. Notification: dispatch_ddos_notifications sends flow evidence.
"""
from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Test infra: in-memory async Mongo-like DB
# ---------------------------------------------------------------------------
class FakeCollection:
    def __init__(self):
        self._docs: list[dict] = []
        self._auto_id = 0

    async def find(self, q=None, *a, **kw):
        q = q or {}
        docs = [d for d in self._docs if self._match(d, q)]
        sort = kw.get("sort")
        if sort:
            key, direction = sort
            docs.sort(key=lambda d: d.get(key, ""), reverse=(direction == -1))
        return docs

    async def find_one(self, q=None, *a, **kw):
        q = q or {}
        for d in self._docs:
            if self._match(d, q):
                return dict(d)
        return None

    async def insert_one(self, doc):
        self._auto_id += 1
        if "_id" not in doc:
            doc["_id"] = f"oid_{self._auto_id}"
        self._docs.append(dict(doc))
        r = MagicMock()
        r.inserted_id = doc["_id"]
        return r

    async def update_one(self, q, update, *a, **kw):
        for d in self._docs:
            if self._match(d, q):
                if "$set" in update:
                    d.update(update["$set"])
                r = MagicMock()
                r.matched_count = 1
                r.modified_count = 1
                return r
        r = MagicMock()
        r.matched_count = 0
        r.modified_count = 0
        return r

    async def delete_many(self, q, *a, **kw):
        before = len(self._docs)
        self._docs = [d for d in self._docs if not self._match(d, q)]
        return MagicMock(deleted_count=before - len(self._docs))

    def _match(self, d, q):
        for k, v in q.items():
            if k == "$or":
                if not any(self._match(d, cond) for cond in v):
                    return False
            elif k == "$in":
                pass
            elif isinstance(v, dict):
                if "$in" in v:
                    if d.get(k) not in v["$in"]:
                        return False
                elif "$gte" in v:
                    if d.get(k, "") < v["$gte"]:
                        return False
                elif "$exists" in v:
                    has = k in d
                    if v["$exists"] and not has:
                        return False
                    if not v["$exists"] and has:
                        return False
                elif "$lt" in v:
                    if d.get(k, "") >= v["$lt"]:
                        return False
            else:
                if d.get(k) != v:
                    return False
        return True


class FakeCursor:
    def __init__(self, docs):
        self._docs = docs
        self._idx = 0

    def sort(self, key, direction):
        self._docs.sort(key=lambda d: d.get(key, ""), reverse=(direction == -1))
        return self

    async def to_list(self, n):
        return self._docs[:n]

    def __aiter__(self):
        self._idx = 0
        return self

    async def __anext__(self):
        if self._idx >= len(self._docs):
            raise StopAsyncIteration
        d = self._docs[self._idx]
        self._idx += 1
        return d


class FakeCollectionWithCursor(FakeCollection):
    def find(self, q=None, *a, **kw):
        q = q or {}
        docs = [d for d in self._docs if self._match(d, q)]
        return FakeCursor(docs)

    def __aiter__(self):
        return FakeCursor(list(self._docs)).__aiter__()

    async def __anext__(self):
        # fallback for any direct iteration
        return (await self.find()).__anext__()


class FakeDB:
    def __init__(self):
        self.ddos_threshold_rules = FakeCollectionWithCursor()
        self.mikrotik_devices = FakeCollectionWithCursor()
        self.ddos_incidents = FakeCollectionWithCursor()
        self.ddos_samples = FakeCollectionWithCursor()
        self.blackhole_log = FakeCollectionWithCursor()
        self.ddos_notify_log = FakeCollectionWithCursor()
        self.notif_channels = FakeCollectionWithCursor()
        self.integration_settings = FakeCollectionWithCursor()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
PROTECTED = "157.20.32.0/24"

def _rule(**kw):
    base = {
        "_id": "rule1", "name": "test-rule", "metric": "pps",
        "threshold": 50_000, "window_s": 300, "action": "alert",
        "direction": "inbound", "scope_prefixes": [PROTECTED],
        "auto_blackhole": False, "enabled": True,
    }
    base.update(kw)
    return base

def _device(name="MT-1", host="10.0.0.1"):
    return {"_id": "dev1", "name": name, "host": host, "port": 8728,
            "username": "admin", "password": "x", "use_tls": False}

def _flow(src, dst, proto="udp", sp="1234", dp="53", pps=80_000, bps=0):
    return {
        "src_address": src, "dst_address": dst, "protocol": proto,
        "src_port": sp, "dst_port": dp,
        "rx_packets": pps, "tx_packets": 0,
        "rx_rate": bps, "tx_rate": 0,
    }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def db():
    d = FakeDB()
    d.ddos_threshold_rules._docs = []
    d.mikrotik_devices._docs = []
    d.ddos_incidents._docs = []
    d.ddos_samples._docs = []
    d.blackhole_log._docs = []
    return d


@pytest.fixture(autouse=True)
def patch_mikrotik(monkeypatch):
    """Replace MikrotikClient.torch and blackhole methods with deterministic stubs."""
    from portal import integrations_v2 as iv2

    class FakeClient:
        def __init__(self, device=None, *a, **kw):
            self.device = device

        def torch(self, interface="ether1", duration="2s", **kw):
            return {"ok": True, "rows": getattr(self, "_flows", [])}

        def list_interfaces(self):
            return [{"name": "ether1", "running": "true", "disabled": "false",
                     "rx-byte": 1000, "tx-byte": 2000}]

        def blackhole_add(self, prefix, *, comment=""):
            return {"ok": True, "prefix": prefix}

        def blackhole_find_by_prefix(self, prefix):
            return {"id": "route-001", "prefix": prefix}

        def blackhole_remove(self, route_id):
            return {"ok": True, "id": route_id}

    monkeypatch.setattr(iv2, "MikrotikClient", FakeClient)
    from portal import emails as _em
    monkeypatch.setattr(_em, "iv2", iv2)
    async def _gs(*a, **kw):
        return None
    monkeypatch.setattr(iv2, "get_settings", _gs)


def _patch_torch_flows(monkeypatch, flows):
    """Inject canned flows into the FakeClient."""
    from portal import integrations_v2 as iv2
    original = iv2.MikrotikClient
    class FakeClientWithFlows(original):
        _flows = flows
    monkeypatch.setattr(iv2, "MikrotikClient", FakeClientWithFlows)
    from portal import emails as _em
    monkeypatch.setattr(_em, "iv2", iv2)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

# 1. Inbound: blackholes internal DESTINATION
async def test_inbound_blackholes_destination(db, monkeypatch):
    db.ddos_threshold_rules._docs = [_rule(action="alert_blackhole", direction="inbound")]
    db.mikrotik_devices._docs = [_device()]
    flows = [_flow("8.8.8.8", "157.20.32.50", proto="udp", dp="53")]
    _patch_torch_flows(monkeypatch, flows)

    from portal.emails import run_ddos_detection_sweep
    result = await run_ddos_detection_sweep(db)
    assert result["incidents_opened"] == 1
    assert result["auto_blackholed"] == 1

    inc = db.ddos_incidents._docs[0]
    assert inc["direction"] == "inbound"
    assert inc["target"] == "157.20.32.50"
    assert inc["status"] == "mitigated"
    assert inc["blackholed_prefix"] == "157.20.32.50/32"


# 2. Outbound: blackholes internal SOURCE
async def test_outbound_blackholes_source(db, monkeypatch):
    db.ddos_threshold_rules._docs = [_rule(action="alert_blackhole", direction="outbound")]
    db.mikrotik_devices._docs = [_device()]
    flows = [_flow("157.20.32.60", "1.1.1.1", proto="tcp", sp="443", dp="80")]
    _patch_torch_flows(monkeypatch, flows)

    from portal.emails import run_ddos_detection_sweep
    result = await run_ddos_detection_sweep(db)
    assert result["incidents_opened"] == 1
    assert result["auto_blackholed"] == 1

    inc = db.ddos_incidents._docs[0]
    assert inc["direction"] == "outbound"
    assert inc["target"] == "157.20.32.60"
    assert inc["blackholed_prefix"] == "157.20.32.60/32"


# 3. Threshold not breached: no incident
async def test_below_threshold_no_incident(db, monkeypatch):
    db.ddos_threshold_rules._docs = [_rule(threshold=200_000)]
    db.mikrotik_devices._docs = [_device()]
    flows = [_flow("8.8.8.8", "157.20.32.50", pps=80_000)]
    _patch_torch_flows(monkeypatch, flows)

    from portal.emails import run_ddos_detection_sweep
    result = await run_ddos_detection_sweep(db)
    assert result["incidents_opened"] == 0
    assert len(db.ddos_incidents._docs) == 0


# 4. Rolling window: averaged across samples
async def test_rolling_window_aggregation(db, monkeypatch):
    db.ddos_threshold_rules._docs = [_rule(threshold=100_000, window_s=300)]
    db.mikrotik_devices._docs = [_device()]
    now = datetime.now(timezone.utc)
    for i in range(3):
        db.ddos_samples._docs.append({
            "at": (now - timedelta(seconds=60 * i)).isoformat(),
            "key": "inbound:157.20.32.50",
            "direction": "inbound", "target": "157.20.32.50",
            "bps": 0, "pps": 120_000,
        })
    flows = [_flow("8.8.8.8", "157.20.32.50", pps=90_000)]
    _patch_torch_flows(monkeypatch, flows)

    from portal.emails import run_ddos_detection_sweep
    result = await run_ddos_detection_sweep(db)
    assert result["incidents_opened"] == 1


# 5. Dedup: existing active incident is updated
async def test_dedup_updates_existing(db, monkeypatch):
    db.ddos_threshold_rules._docs = [_rule()]
    db.mikrotik_devices._docs = [_device()]
    db.ddos_incidents._docs = [{
        "_id": "inc_existing", "target": "157.20.32.50",
        "direction": "inbound", "rule_id": "rule1",
        "status": "active", "src_ip": "", "dst_ip": "",
        "protocol": "", "src_port": "", "dst_port": "",
        "pps": 0, "bps": 0, "notified": [],
    }]
    flows = [_flow("8.8.8.8", "157.20.32.50", pps=80_000)]
    _patch_torch_flows(monkeypatch, flows)

    from portal.emails import run_ddos_detection_sweep
    result = await run_ddos_detection_sweep(db)
    assert result["incidents_opened"] == 0
    assert len(db.ddos_incidents._docs) == 1
    inc = db.ddos_incidents._docs[0]
    assert inc["src_ip"] == "8.8.8.8"


# 6. Lifecycle: mitigated incident auto-resolves after grace
async def test_auto_resolve_after_grace(db, monkeypatch):
    db.ddos_threshold_rules._docs = [_rule(action="alert_blackhole")]
    db.mikrotik_devices._docs = [_device()]
    old_time = (datetime.now(timezone.utc) - timedelta(seconds=600)).isoformat()
    db.ddos_incidents._docs = [{
        "_id": "inc_old", "target": "157.20.32.50",
        "direction": "inbound", "rule_id": "rule1",
        "status": "mitigated", "blackholed_prefix": "157.20.32.50/32",
        "blackhole_route_id": "route-001",
        "device": "MT-1", "last_breach_at": old_time,
        "window_s": 300, "notified": [],
    }]
    _patch_torch_flows(monkeypatch, [])

    from portal.emails import run_ddos_detection_sweep
    result = await run_ddos_detection_sweep(db)
    assert result["auto_resolved"] == 1
    inc = db.ddos_incidents._docs[0]
    assert inc["status"] == "resolved"


# 7. Evidence: incident carries full flow fields
async def test_incident_evidence_fields(db, monkeypatch):
    db.ddos_threshold_rules._docs = [_rule()]
    db.mikrotik_devices._docs = [_device()]
    flows = [_flow("203.0.113.9", "157.20.32.77", proto="tcp",
                   sp="9999", dp="443", pps=80_000)]
    _patch_torch_flows(monkeypatch, flows)

    from portal.emails import run_ddos_detection_sweep
    await run_ddos_detection_sweep(db)
    inc = db.ddos_incidents._docs[0]
    assert inc["src_ip"] == "203.0.113.9"
    assert inc["dst_ip"] == "157.20.32.77"
    assert inc["protocol"] == "tcp"
    assert inc["src_port"] == "9999"
    assert inc["dst_port"] == "443"
    assert inc["direction"] == "inbound"


# 8. Whitelist: auto-blackhole denied for gateway IP
async def test_whitelist_blocks_gateway_blackhole(db, monkeypatch):
    db.ddos_threshold_rules._docs = [_rule(action="alert_blackhole")]
    db.mikrotik_devices._docs = [_device()]
    flows = [_flow("8.8.8.8", "157.20.32.254", pps=80_000)]
    _patch_torch_flows(monkeypatch, flows)

    from portal.emails import run_ddos_detection_sweep
    result = await run_ddos_detection_sweep(db)
    assert result["incidents_opened"] == 1
    assert result["auto_blackholed"] == 0
    inc = db.ddos_incidents._docs[0]
    assert inc["status"] == "active"
    # A denied mitigation intentionally leaves this optional field unset.
    assert inc.get("blackholed_prefix") is None


# 9. Direction filter: outbound rule ignores inbound traffic
async def test_direction_filter_ignores_wrong_direction(db, monkeypatch):
    db.ddos_threshold_rules._docs = [_rule(direction="outbound")]
    db.mikrotik_devices._docs = [_device()]
    flows = [_flow("8.8.8.8", "157.20.32.50", pps=80_000)]
    _patch_torch_flows(monkeypatch, flows)

    from portal.emails import run_ddos_detection_sweep
    result = await run_ddos_detection_sweep(db)
    assert result["incidents_opened"] == 0


# 10. Notification: dispatch sends flow evidence
async def test_notification_contains_flow_evidence(db, monkeypatch):
    from portal.emails import dispatch_ddos_notifications
    db.notif_channels._docs = [
        {"_id": "ch1", "type": "webhook", "target": "http://hook.test",
         "events": "ddos", "enabled": True},
    ]
    incident = {
        "_id": "inc1", "target": "157.20.32.50",
        "src_ip": "8.8.8.8", "dst_ip": "157.20.32.50",
        "protocol": "udp", "src_port": "1234", "dst_port": "53",
        "direction": "inbound", "severity": "high",
        "attack_type": "DNS Amplification", "bps": 0, "pps": 80000,
        "rule_name": "test", "action": "alert", "started_at": "2026-01-01T00:00:00Z",
    }

    captured = {}
    class FakeResponse:
        status_code = 200

    async def fake_post(url, json=None, **kw):
        captured["url"] = url
        captured["payload"] = json
        return FakeResponse()

    import httpx
    class FakeAsyncClient:
        def __init__(self, *a, **kw): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        async def post(self, url, json=None, **kw):
            return await fake_post(url, json=json, **kw)

    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)
    await dispatch_ddos_notifications(db, incident)

    assert "url" in captured
    payload = captured["payload"]
    assert "8.8.8.8" in payload["incident"]["src_ip"]
    assert "157.20.32.50" in payload["incident"]["dst_ip"]
    assert payload["incident"]["protocol"] == "udp"
    assert payload["incident"]["src_port"] == "1234"
    assert payload["incident"]["dst_port"] == "53"
    assert payload["incident"]["direction"] == "inbound"