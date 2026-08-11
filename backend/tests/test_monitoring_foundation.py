"""Foundation tests for the monitoring module (MRTG-style ping + state).

Grounded in the monitoring-network-map blueprint: reuse run_ping, an atomic
Mongo lease, transition-only events, BSON Date samples, and SSRF-safe target
validation. No SNMP yet — this phase is ping + target validation only.
"""
import pytest
from datetime import datetime, timezone, timedelta

from portal import monitoring


# ---------------------------------------------------------------------------
# Target validation (SSRF guard)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("host", [
    "127.0.0.1", "localhost", "::1", "10.0.0.5", "172.16.0.1",
    "192.168.1.1", "169.254.10.10", "0.0.0.0", "100.64.0.1",
    "224.0.0.1", "ff02::1",
])
def test_reject_private_loopback_linklocal(host):
    with pytest.raises(ValueError):
        monitoring.validate_target(host)


@pytest.mark.parametrize("host", [
    "8.8.8.8", "1.1.1.1", "157.20.32.183", "example.com",
])
def test_accept_public_or_approved(host):
    assert monitoring.validate_target(host) == host


def test_accept_approved_internal():
    assert monitoring.validate_target("10.0.0.5", approved_internal={"10.0.0.5"}) == "10.0.0.5"


# ---------------------------------------------------------------------------
# Ping sweep: lease + state machine + transition-only events
# ---------------------------------------------------------------------------
class _Probes:
    def __init__(self):
        self.rows = []
    async def insert_one(self, doc):
        self.rows.append(doc)


class _State:
    def __init__(self, existing=None):
        self._existing = existing or {}
        self.upserts = []
    async def find_one(self, _q):
        return self._existing.get("doc")
    async def update_one(self, _q, _u, upsert=False):
        self.upserts.append((_q, _u, upsert))


class _Events:
    def __init__(self):
        self.rows = []
    async def insert_one(self, doc):
        self.rows.append(doc)


class _Leases:
    def __init__(self, owner):
        self._owner = owner
    async def find_one_and_update(self, *a, **k):
        return {"owner": self._owner}
    async def find_one(self, _q):
        return {"owner": self._owner}
    async def update_one(self, *a, **k):
        return None


class _Db:
    def __init__(self, owner="host:1"):
        self.monitoring_probes = _Probes()
        self.monitoring_check_state = _State()
        self.monitoring_events = _Events()
        self.scheduler_leases = _Leases(owner)


class _PingResult:
    def __init__(self, up):
        self.up = up


@pytest.mark.anyio
async def test_ping_up_writes_sample_and_state_no_event(monkeypatch):
    db = _Db()
    async def fake_ping(target, **kw):
        return {"tool": "ping", "summary": {
            "count": 3, "received": 3, "lost": 0,
            "loss_percent": 0.0, "avg_ms": 3.2,
        }, "results": []}
    monkeypatch.setattr(monitoring, "run_ping", fake_ping)

    out = await monitoring.probe_target(db, target="8.8.8.8", check_id="c1",
                                        owner="host:1", timeout=2.0)

    assert out["status"] == "up"
    assert out["event"] is None  # no transition on first up
    assert len(db.monitoring_probes.rows) == 1
    assert db.monitoring_probes.rows[0]["check_id"] == "c1"
    assert db.monitoring_probes.rows[0]["rtt_ms"] == 3.2
    assert db.monitoring_probes.rows[0]["loss"] == 0.0
    # BSON Date, not ISO string
    assert isinstance(db.monitoring_probes.rows[0]["at"], datetime)
    assert db.monitoring_probes.rows[0]["at"].tzinfo is not None


@pytest.mark.anyio
async def test_ping_down_emits_transition_event(monkeypatch):
    db = _Db()
    # prior state is up with 0 consecutive failures
    db.monitoring_check_state._existing = {
        "doc": {"check_id": "c1", "status": "up", "consecutive_failures": 0}
    }
    async def fake_ping(target, **kw):
        return {"tool": "ping", "summary": {
            "count": 3, "received": 0, "lost": 3,
            "loss_percent": 100.0, "avg_ms": None,
        }, "results": []}
    monkeypatch.setattr(monitoring, "run_ping", fake_ping)

    out = await monitoring.probe_target(db, target="8.8.8.8", check_id="c1",
                                        owner="host:1", timeout=2.0)

    assert out["status"] == "down"
    assert out["event"] == "down"
    assert len(db.monitoring_events.rows) == 1
    assert db.monitoring_events.rows[0]["check_id"] == "c1"
    assert db.monitoring_events.rows[0]["from"] == "up"
    assert db.monitoring_events.rows[0]["to"] == "down"


@pytest.mark.anyio
async def test_ping_down_without_prior_state_is_not_flap(monkeypatch):
    # First-ever observation is down: no prior up, so no "down" event (avoid
    # alert storm on first sample).
    db = _Db()
    async def fake_ping(target, **kw):
        return {"tool": "ping", "summary": {
            "count": 3, "received": 0, "lost": 3,
            "loss_percent": 100.0, "avg_ms": None,
        }, "results": []}
    monkeypatch.setattr(monitoring, "run_ping", fake_ping)

    out = await monitoring.probe_target(db, target="8.8.8.8", check_id="c1",
                                        owner="host:1", timeout=2.0)
    assert out["status"] == "down"
    assert out["event"] is None
    assert len(db.monitoring_events.rows) == 0


@pytest.mark.anyio
async def test_probe_rejects_hostname_resolving_to_private_ip(monkeypatch):
    db = _Db()
    monkeypatch.setattr(monitoring, "resolve_ip", lambda _host: "127.0.0.1")

    with pytest.raises(ValueError):
        await monitoring.probe_target(
            db, target="public.example", check_id="c1", owner="host:1"
        )


@pytest.mark.anyio
async def test_lease_held_skips_work(monkeypatch):
    db = _Db(owner="other:9")
    async def fake_ping(target, **kw):
        raise AssertionError("must not ping when lease held")
    monkeypatch.setattr(monitoring, "run_ping", fake_ping)

    out = await monitoring.probe_target(db, target="8.8.8.8", check_id="c1",
                                        owner="host:1", timeout=2.0)
    assert out["skipped"] is True
    assert len(db.monitoring_probes.rows) == 0
