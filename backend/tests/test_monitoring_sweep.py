"""Tests for executing due, enabled monitoring checks safely."""
from datetime import datetime, timedelta, timezone

import pytest

from portal import monitoring


class _Cursor:
    def __init__(self, rows):
        self.rows = rows

    async def to_list(self, _limit):
        return self.rows


class _Checks:
    def __init__(self, rows):
        self.rows = rows

    def find(self, query):
        assert query == {"enabled": True}
        return _Cursor(self.rows)


class _States:
    def __init__(self, states):
        self.states = states

    async def find_one(self, query):
        return self.states.get(query["check_id"])


class _Db:
    def __init__(self, checks, states=None):
        self.monitoring_checks = _Checks(checks)
        self.monitoring_check_state = _States(states or {})


@pytest.mark.anyio
async def test_sweep_probes_enabled_checks_that_are_due(monkeypatch):
    now = datetime(2026, 8, 11, 11, 0, tzinfo=timezone.utc)
    db = _Db([
        {"_id": "due", "target": "8.8.8.8", "enabled": True, "interval_seconds": 60},
        {"_id": "fresh", "target": "1.1.1.1", "enabled": True, "interval_seconds": 60},
    ], {"fresh": {"last_at": now - timedelta(seconds=30)}})
    calls = []

    async def fake_probe(db, *, target, check_id, owner, timeout):
        calls.append((target, check_id, owner, timeout))
        return {"status": "up"}

    monkeypatch.setattr(monitoring, "probe_target", fake_probe)
    out = await monitoring.run_monitoring_probe_sweep(db, owner="host:1", now=now)

    assert calls == [("8.8.8.8", "due", "host:1", 2.0)]
    assert out == {"checked": 2, "probed": 1, "skipped_not_due": 1, "errors": 0}


@pytest.mark.anyio
async def test_sweep_does_not_load_or_probe_disabled_checks(monkeypatch):
    db = _Db([])

    async def fail_probe(*_args, **_kwargs):
        raise AssertionError("disabled check must not be probed")

    monkeypatch.setattr(monitoring, "probe_target", fail_probe)
    out = await monitoring.run_monitoring_probe_sweep(db, owner="host:1")

    assert out == {"checked": 0, "probed": 0, "skipped_not_due": 0, "errors": 0}


@pytest.mark.anyio
async def test_sweep_continues_after_one_check_fails(monkeypatch):
    db = _Db([
        {"_id": "bad", "target": "bad.example", "enabled": True},
        {"_id": "good", "target": "8.8.8.8", "enabled": True},
    ])
    calls = []

    async def fake_probe(db, *, target, check_id, owner, timeout):
        calls.append(check_id)
        if check_id == "bad":
            raise RuntimeError("probe broke")
        return {"status": "up"}

    monkeypatch.setattr(monitoring, "probe_target", fake_probe)
    out = await monitoring.run_monitoring_probe_sweep(db, owner="host:1")

    assert calls == ["bad", "good"]
    assert out == {"checked": 2, "probed": 1, "skipped_not_due": 0, "errors": 1}


@pytest.mark.anyio
async def test_sweep_treats_invalid_or_future_last_at_as_due(monkeypatch):
    now = datetime(2026, 8, 11, 11, 0, tzinfo=timezone.utc)
    db = _Db([
        {"_id": "invalid", "target": "8.8.8.8", "enabled": True},
        {"_id": "future", "target": "1.1.1.1", "enabled": True},
    ], {
        "invalid": {"last_at": "not-a-date"},
        "future": {"last_at": now + timedelta(hours=1)},
    })
    calls = []

    async def fake_probe(db, *, target, check_id, owner, timeout):
        calls.append(check_id)
        return {"status": "up"}

    monkeypatch.setattr(monitoring, "probe_target", fake_probe)
    await monitoring.run_monitoring_probe_sweep(db, owner="host:1", now=now)

    assert calls == ["invalid", "future"]
