"""Graph alert evaluator + dispatch tests (phase 3).

State-machine coverage:
* debounce: fires only after N consecutive breaches (default 2)
* single-sample flap does not fire
* transition-only: steady breach does not re-notify
* resolve: first healthy sample closes the open alert
* maintenance window suppresses dispatch but still records history (honest)
* state metric breaches when poll state != ok (dead graph)
* scope: rule with graph_id only evaluates that graph
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from bson import ObjectId

from portal import graph_alerts as ga


class _Cursor:
    def __init__(self, docs):
        self._docs = list(docs)

    def sort(self, *_a, **_kw):
        return self

    async def to_list(self, _n=None):
        return list(self._docs)

    def __aiter__(self):
        self._it = iter(self._docs)
        return self

    async def __anext__(self):
        try:
            return next(self._it)
        except StopIteration:
            raise StopAsyncIteration


class _Coll:
    def __init__(self, docs=None):
        self.docs = list(docs or [])
        self.inserted = []
        self.updated = []
        self.queries = []

    def find(self, query=None, *_a, **_kw):
        self.queries.append(query or {})
        return _Cursor(self.docs)

    async def find_one(self, query=None, *_a, **_kw):
        self.queries.append(query or {})
        needle = query or {}
        for d in self.docs:
            if all(d.get(k) == v for k, v in needle.items()):
                return d
        return None

    async def insert_one(self, doc):
        self.inserted.append(doc)
        return type("R", (), {"inserted_id": ObjectId()})()

    async def update_one(self, query, update, upsert=False):
        """Behave like Mongo: update the FIRST matching doc, insert only when
        upsert=True and nothing matched. (Appending on every call would make
        _load_state read a stale doc and silently break the state machine.)"""
        self.updated.append((query, update, upsert))
        for d in self.docs:
            if all(d.get(k) == v for k, v in (query or {}).items()):
                d.update(update.get("$set", {}))
                return type("R", (), {"matched_count": 1})()
        if upsert:
            self.docs.append({**(query or {}), **update.get("$set", {})})
        return type("R", (), {"matched_count": 0})()


class FakeDb:
    def __init__(self, rules=None, windows=None):
        self.graph_alert_rules = _Coll(rules or [])
        self.monitoring_graph_alerts = _Coll()
        self.monitoring_graph_alert_state = _Coll()
        self.monitoring_maintenance_windows = _Coll(windows or [])
        self.notif_channels = _Coll()
        self.ddos_notify_log = _Coll()

    def __getitem__(self, name):
        return {
            ga.RULES_COLLECTION: self.graph_alert_rules,
            ga.ALERTS_COLLECTION: self.monitoring_graph_alerts,
            ga.STATE_COLLECTION: self.monitoring_graph_alert_state,
            ga.WINDOWS_COLLECTION: self.monitoring_maintenance_windows,
        }.get(name, _Coll())


def _rule(**over):
    base = {
        "_id": ObjectId(),
        "name": "In above 80%",
        "metric": "bps",
        "comparator": ">",
        "threshold": 80_000_000.0,
        "consecutive": 2,
        "severity": "warning",
        "enabled": True,
        "graph_id": "",
    }
    base.update(over)
    return base


def _graph(**over):
    base = {"_id": ObjectId(), "name": "eth0 In", "display_name": "eth0 In",
            "target": "10.0.0.1", "type": "snmp_traffic_in"}
    base.update(over)
    return base


NOW = datetime.now(timezone.utc)


def test_single_breach_does_not_fire():
    db = FakeDb(rules=[_rule()])
    result = asyncio.run(ga.evaluate_graph_alerts(
        db, graph=_graph(), state="ok", value=90_000_000.0, now=NOW))
    assert result == {"fired": [], "resolved": [], "suppressed": []}
    assert db.monitoring_graph_alerts.inserted == []
    state = db.monitoring_graph_alert_state.docs[0]
    assert state["consecutive"] == 1
    assert state["active"] is False


def test_second_consecutive_breach_fires():
    db = FakeDb(rules=[_rule()])
    g = _graph()
    asyncio.run(ga.evaluate_graph_alerts(db, graph=g, state="ok", value=90_000_000.0, now=NOW))
    result = asyncio.run(ga.evaluate_graph_alerts(
        db, graph=g, state="ok", value=95_000_000.0, now=NOW + timedelta(seconds=20)))
    assert len(result["fired"]) == 1
    alert = result["fired"][0]
    assert alert["value"] == 95_000_000.0
    assert alert["dispatched"] is True
    assert db.monitoring_graph_alerts.inserted
    state = db.monitoring_graph_alert_state.docs[-1]
    assert state["consecutive"] == 2
    assert state["active"] is True


def test_steady_breach_does_not_refire():
    db = FakeDb(rules=[_rule()])
    g = _graph()
    asyncio.run(ga.evaluate_graph_alerts(db, graph=g, state="ok", value=90e6, now=NOW))
    asyncio.run(ga.evaluate_graph_alerts(db, graph=g, state="ok", value=95e6, now=NOW + timedelta(seconds=20)))
    # 10 more breaches
    for i in range(10):
        asyncio.run(ga.evaluate_graph_alerts(
            db, graph=g, state="ok", value=100e6, now=NOW + timedelta(seconds=20 * (i + 3))))
    assert len(db.monitoring_graph_alerts.inserted) == 1
    assert db.monitoring_graph_alert_state.docs[-1]["active"] is True


def test_resolve_closes_alert():
    db = FakeDb(rules=[_rule()])
    g = _graph()
    asyncio.run(ga.evaluate_graph_alerts(db, graph=g, state="ok", value=90e6, now=NOW))
    asyncio.run(ga.evaluate_graph_alerts(db, graph=g, state="ok", value=95e6, now=NOW + timedelta(seconds=20)))
    result = asyncio.run(ga.evaluate_graph_alerts(
        db, graph=g, state="ok", value=10e6, now=NOW + timedelta(seconds=40)))
    assert result["resolved"]
    assert db.monitoring_graph_alerts.updated[0][1]["$set"]["resolved_at"] is not None
    state = db.monitoring_graph_alert_state.docs[-1]
    assert state["active"] is False
    assert state["consecutive"] == 0


def test_maintenance_suppresses_dispatch_but_records_history():
    db = FakeDb(
        rules=[_rule()],
        windows=[{
            "_id": ObjectId(),
            "name": "Maintenance malam",
            "starts_at": NOW - timedelta(minutes=10),
            "ends_at": NOW + timedelta(hours=2),
            "graph_ids": [],
            "enabled": True,
        }],
    )
    g = _graph()
    asyncio.run(ga.evaluate_graph_alerts(db, graph=g, state="ok", value=90e6, now=NOW))
    result = asyncio.run(ga.evaluate_graph_alerts(
        db, graph=g, state="ok", value=95e6, now=NOW + timedelta(seconds=20)))
    assert len(result["suppressed"]) == 1
    assert result["fired"] == []
    alert = db.monitoring_graph_alerts.inserted[0]
    assert alert["suppressed"] is True
    assert alert["dispatched"] is False
    assert db.notif_channels.queries == []  # no dispatch call at all


def test_window_outside_period_does_not_suppress():
    db = FakeDb(
        rules=[_rule()],
        windows=[{
            "_id": ObjectId(),
            "name": "Besok",
            "starts_at": NOW + timedelta(days=1),
            "ends_at": NOW + timedelta(days=1, hours=2),
            "graph_ids": [],
            "enabled": True,
        }],
    )
    g = _graph()
    asyncio.run(ga.evaluate_graph_alerts(db, graph=g, state="ok", value=90e6, now=NOW))
    result = asyncio.run(ga.evaluate_graph_alerts(
        db, graph=g, state="ok", value=95e6, now=NOW + timedelta(seconds=20)))
    assert len(result["fired"]) == 1


def test_state_metric_fires_on_dead_graph():
    rule = _rule(metric="state", threshold=0, comparator=">=")
    db = FakeDb(rules=[rule])
    g = _graph()
    # First error is only a candidate; the debounce needs N consecutive breaches.
    first = asyncio.run(ga.evaluate_graph_alerts(
        db, graph=g, state="error", error="timeout", value=None, now=NOW))
    assert first["fired"] == []
    result = asyncio.run(ga.evaluate_graph_alerts(
        db, graph=g, state="error", error="timeout", value=None, now=NOW + timedelta(seconds=20)))
    assert len(result["fired"]) == 1
    assert result["fired"][0]["state"] == "error"
    assert result["fired"][0]["error"] == "timeout"


def test_state_metric_healthy_sample_never_fires():
    rule = _rule(metric="state", threshold=0, comparator=">=")
    db = FakeDb(rules=[rule])
    g = _graph()
    for i in range(5):
        result = asyncio.run(ga.evaluate_graph_alerts(
            db, graph=g, state="ok", value=None, now=NOW + timedelta(seconds=20 * i)))
        assert result["fired"] == []


def test_rule_scoped_to_other_graph_ignored():
    db = FakeDb(rules=[_rule(graph_id=str(ObjectId()))])
    g = _graph()
    asyncio.run(ga.evaluate_graph_alerts(db, graph=g, state="ok", value=95e6, now=NOW))
    # no alert state row ever created (rule didn't apply)
    assert db.monitoring_graph_alert_state.docs == []


@pytest.mark.parametrize("metric,threshold,comparator,value,expected", [
    ("bps", 100, ">", 101, True),
    ("bps", 100, ">", 100, False),
    ("bps", 100, ">=", 100, True),
    ("pps", 1_000_000, "<", 999_999, True),
    ("bps", 100, "<=", 100, True),
])
def test_rule_breached_predicate(metric, threshold, comparator, value, expected):
    rule = _rule(metric=metric, threshold=threshold, comparator=comparator)
    assert ga.rule_breached(rule, value=value, state="ok") is expected