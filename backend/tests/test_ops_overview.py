"""Tests for the unified operations read-model (``portal.ops``).

These exercise the pure aggregation function directly with in-memory fakes, so
no MongoDB or live server is required. The contract worth protecting:

* aggregation is read-only (no writes to any collection),
* a DOWN check / device / undelivered alert surfaces in ``attention``,
* ``pending`` is not counted as down,
* unavailable counters come back ``None``, never a confident zero.
"""
import pytest
from datetime import datetime, timezone

from portal import ops as ops_mod


# ---------------------------------------------------------------------------
# Minimal fake collection: enough of the motor surface for the read-model.
# ---------------------------------------------------------------------------
class _FakeCollection:
    def __init__(self, rows=None):
        self.rows = list(rows or [])
        self.writes = []

    def find(self, query=None):
        self._last_query = query or {}
        return self

    def sort(self, *_a, **_k):
        return self

    async def to_list(self, limit=None):
        out = [r for r in self.rows if self._matches(r, getattr(self, "_last_query", {}))]
        return out[:limit] if limit else out

    async def count_documents(self, query=None):
        return sum(1 for r in self.rows if self._matches(r, query or {}))

    async def insert_one(self, doc):
        self.writes.append(("insert", doc))

    async def update_one(self, query, update, upsert=False):
        self.writes.append(("update", query, update))

    @staticmethod
    def _matches(row, query):
        for key, expected in query.items():
            actual = row.get(key)
            if isinstance(expected, dict):
                for op, operand in expected.items():
                    if op == "$ne":
                        if actual == operand:
                            return False
                    elif op == "$gte":
                        if not (actual and actual >= operand):
                            return False
                    elif op == "$lte":
                        if not (actual and actual <= operand):
                            return False
                    elif op == "$in":
                        if actual not in operand:
                            return False
                    elif op == "$exists":
                        present = key in row
                        if present == operand:
                            return False
            else:
                if actual != expected:
                    return False
        return True


class _Db:
    def __init__(self, **collections):
        self.monitoring_checks = collections.get("monitoring_checks", _FakeCollection())
        self.monitoring_check_state = collections.get("monitoring_check_state", _FakeCollection())
        self.monitoring_events = collections.get("monitoring_events", _FakeCollection())
        self.mikrotik_devices = collections.get("mikrotik_devices", _FakeCollection())
        self.noc_device_state = collections.get("noc_device_state", _FakeCollection())
        self.noc_events = collections.get("noc_events", _FakeCollection())
        self.sla_incidents = collections.get("sla_incidents", _FakeCollection())
        self.blocked_ips = collections.get("blocked_ips", _FakeCollection())
        self.security_notifications = collections.get("security_notifications", _FakeCollection())
        self.audit_logs = collections.get("audit_logs", _FakeCollection())


NOW = datetime(2026, 8, 11, 12, 0, tzinfo=timezone.utc)


@pytest.mark.anyio
async def test_overview_aggregates_without_writing():
    db = _Db(
        monitoring_checks=_FakeCollection([
            {"_id": "c1", "enabled": True},
            {"_id": "c2", "enabled": False},
        ]),
        monitoring_check_state=_FakeCollection([
            {"check_id": "c1", "status": "up", "confirmed_status": "up"},
        ]),
    )
    out = await ops_mod.build_ops_overview(db, now=NOW)
    assert out["read_only"] is True
    assert out["summary"]["monitoring"]["checks"] == 2
    assert out["summary"]["monitoring"]["up"] == 1
    assert out["summary"]["monitoring"]["down"] == 0
    assert out["summary"]["monitoring"]["disabled"] == 1
    for coll in db.__dict__.values():
        assert coll.writes == [], "read-model must not write to any collection"


@pytest.mark.anyio
async def test_pending_is_not_counted_as_down():
    db = _Db(
        monitoring_checks=_FakeCollection([{"_id": "c1", "enabled": True}]),
        monitoring_check_state=_FakeCollection([
            {"check_id": "c1", "status": "pending", "confirmed_status": "up"},
        ]),
    )
    out = await ops_mod.build_ops_overview(db, now=NOW)
    m = out["summary"]["monitoring"]
    assert m["pending"] == 1
    assert m["down"] == 0
    assert m["up"] == 0  # pending is its own bucket, never a confirmed up


@pytest.mark.anyio
async def test_down_surfaces_attention():
    db = _Db(
        monitoring_checks=_FakeCollection([{"_id": "c1", "enabled": True}]),
        monitoring_check_state=_FakeCollection([
            {"check_id": "c1", "status": "down", "confirmed_status": "down"},
        ]),
        monitoring_events=_FakeCollection(),
    )
    out = await ops_mod.build_ops_overview(db, now=NOW)
    titles = [a["title"] for a in out["attention"]]
    assert "Monitoring checks down" in titles


@pytest.mark.anyio
async def test_undelivered_and_exhausted_alerts_surface():
    db = _Db(
        monitoring_events=_FakeCollection([
            {"_id": "e1", "notified": False},
            {"_id": "e2", "notify_exhausted": True},
        ]),
    )
    out = await ops_mod.build_ops_overview(db, now=NOW)
    m = out["summary"]["monitoring"]
    assert m["undelivered_alerts"] == 1
    assert m["exhausted_alerts"] == 1
    titles = [a["title"] for a in out["attention"]]
    assert "Undelivered alerts" in titles
    assert "Alerts exhausted" in titles


@pytest.mark.anyio
async def test_unavailable_collection_is_none_not_zero():
    db = _Db()
    db.monitoring_checks = None  # simulate a collection that is not present
    out = await ops_mod.build_ops_overview(db, now=NOW)
    m = out["summary"]["monitoring"]
    assert m["checks"] is None
    assert m["up"] is None
    assert m["down"] is None
    assert out["source_status"]["monitoring"]


@pytest.mark.anyio
async def test_noc_down_surfaces_and_sla_open_counted():
    db = _Db(
        mikrotik_devices=_FakeCollection([{"_id": "d1"}]),
        noc_device_state=_FakeCollection([{"device_id": "d1", "status": "down"}]),
        sla_incidents=_FakeCollection([
            {"status": "open", "started_at": NOW.isoformat()},
            {"status": "resolved", "started_at": NOW.isoformat()},
        ]),
    )
    out = await ops_mod.build_ops_overview(db, now=NOW)
    assert out["summary"]["noc"]["down"] == 1
    assert out["summary"]["sla"]["open_incidents"] == 1
    titles = [a["title"] for a in out["attention"]]
    assert "NOC devices down" in titles
    assert "Open SLA incidents" in titles


@pytest.mark.anyio
async def test_overflowing_collection_reports_unknown_not_partial():
    # Open cardinality cannot be closed from a partial page: if the scan hits
    # its limit, the honest answer is None, not a truncated count.
    db = _Db()
    db.monitoring_checks = _FakeCollection(
        [{"_id": f"c{i}", "enabled": True} for i in range(ops_mod._MAX_CHECKS + 1)]
    )
    out = await ops_mod.build_ops_overview(db, now=NOW)
    assert out["summary"]["monitoring"]["checks"] is None
    assert out["source_status"]["monitoring"]


@pytest.mark.anyio
async def test_active_block_count_handles_datetime_expiry():
    from datetime import timedelta
    db = _Db(
        blocked_ips=_FakeCollection([
            {"ip": "1.2.3.4", "expires_at": NOW + timedelta(hours=1), "unblocked_at": None},
            {"ip": "5.6.7.8", "expires_at": NOW - timedelta(hours=1), "unblocked_at": None},
        ]),
    )
    out = await ops_mod.build_ops_overview(db, now=NOW)
    assert out["summary"]["security"]["active_blocks"] == 1
