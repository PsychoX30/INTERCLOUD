"""Read-only monitoring history contract: scoped, bounded, and staff-only."""
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
from bson import ObjectId
from fastapi import HTTPException

from portal.routes import monitoring as routes


class _Cursor:
    def __init__(self, rows):
        self.rows = list(rows)
        self.requested_limit = None

    def sort(self, *_args):
        return self

    def limit(self, value):
        self.requested_limit = value
        return self

    async def to_list(self, value):
        self.requested_limit = value
        return self.rows[:value]


class _Collection:
    def __init__(self, rows=None):
        self.rows = list(rows or [])
        self.queries = []
        self.last_cursor = None

    async def find_one(self, query):
        self.queries.append(query)
        return next((row for row in self.rows if all(row.get(k) == v for k, v in query.items())), None)

    def find(self, query):
        self.queries.append(query)
        self.last_cursor = _Cursor(
            row for row in self.rows if all(row.get(k) == v for k, v in query.items())
        )
        return self.last_cursor


class _Db:
    def __init__(self, *, checks=None, states=None, probes=None, events=None):
        self.monitoring_checks = _Collection(checks)
        self.monitoring_check_state = _Collection(states)
        self.monitoring_probes = _Collection(probes)
        self.monitoring_events = _Collection(events)


@pytest.mark.anyio
async def test_history_returns_selected_state_samples_and_events(monkeypatch):
    oid = ObjectId()
    check_id = str(oid)
    at = datetime(2026, 8, 11, 11, 0, tzinfo=timezone.utc)
    db = _Db(
        checks=[{"_id": oid, "name": "DNS", "target": "8.8.8.8", "enabled": True, "interval_seconds": 60}],
        states=[{"check_id": check_id, "status": "up", "target": "8.8.8.8", "last_at": at,
                 "last_rtt_ms": 2.5, "consecutive_failures": 0, "secret": "must-not-leak"}],
        probes=[{"_id": ObjectId(), "check_id": check_id, "at": at, "up": True,
                 "rtt_ms": 2.5, "loss": 0.0, "resolved_ip": "8.8.8.8", "raw": "must-not-leak"}],
        events=[{"_id": ObjectId(), "check_id": check_id, "at": at, "from": "down", "to": "up",
                 "target": "8.8.8.8", "internal": "must-not-leak"}],
    )
    monkeypatch.setattr(routes, "_get_db", AsyncMock(return_value=db))

    out = await routes.monitoring_check_history(check_id, {"role": "support"}, limit=100)

    assert out["check"]["id"] == check_id
    assert out["state"] == {
        "status": "up", "target": "8.8.8.8", "last_at": at,
        "last_rtt_ms": 2.5, "consecutive_failures": 0,
    }
    assert out["samples"] == [{"at": at, "up": True, "rtt_ms": 2.5, "loss": 0.0,
                                "resolved_ip": "8.8.8.8"}]
    assert set(out["events"][0]) == {"id", "at", "from", "to", "target"}
    assert db.monitoring_probes.queries == [{"check_id": check_id}]
    assert db.monitoring_events.queries == [{"check_id": check_id}]


@pytest.mark.anyio
async def test_history_clamps_limit_and_rejects_missing_check(monkeypatch):
    oid = ObjectId()
    check_id = str(oid)
    db = _Db(checks=[{"_id": oid, "name": "DNS", "target": "8.8.8.8"}])
    monkeypatch.setattr(routes, "_get_db", AsyncMock(return_value=db))

    await routes.monitoring_check_history(check_id, {"role": "admin"}, limit=9999)
    assert db.monitoring_probes.last_cursor.requested_limit == 500
    assert db.monitoring_events.last_cursor.requested_limit == 500

    with pytest.raises(HTTPException) as exc:
        await routes.monitoring_check_history(str(ObjectId()), {"role": "admin"}, limit=10)
    assert exc.value.status_code == 404


@pytest.mark.anyio
async def test_history_invalid_id_fails_before_history_queries(monkeypatch):
    db = _Db()
    monkeypatch.setattr(routes, "_get_db", AsyncMock(return_value=db))

    with pytest.raises(HTTPException) as exc:
        await routes.monitoring_check_history("invalid", {"role": "support"})

    assert exc.value.status_code == 400
    assert db.monitoring_probes.queries == []
    assert db.monitoring_events.queries == []
