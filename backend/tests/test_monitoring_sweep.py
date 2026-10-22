"""Tests for executing due, enabled monitoring checks safely."""
from datetime import datetime, timedelta, timezone

import pytest

from portal import monitoring


class _Cursor:
    def __init__(self, rows):
        self.rows = rows

    def sort(self, *_a):
        return self

    async def to_list(self, _limit=None):
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


class _Events:
    """Empty event collection: the retry sweep finds nothing to re-send."""

    def __init__(self, rows=None):
        self.rows = list(rows or [])
        self.updates = []

    def find(self, _query):
        return _Cursor([])

    async def update_one(self, query, update, upsert=False):
        self.updates.append((query, update, upsert))
        return type("R", (), {"matched_count": 0})()


class _Db:
    def __init__(self, checks, states=None, events=None):
        self.monitoring_checks = _Checks(checks)
        self.monitoring_check_state = _States(states or {})
        self.monitoring_events = _Events(events)


EMPTY_RETRY = {"scanned": 0, "sent": 0, "failed": 0, "exhausted": 0}


@pytest.mark.anyio
async def test_sweep_probes_enabled_checks_that_are_due(monkeypatch):
    now = datetime(2026, 8, 11, 11, 0, tzinfo=timezone.utc)
    db = _Db([
        {"_id": "due", "target": "8.8.8.8", "enabled": True, "interval_seconds": 60},
        {"_id": "fresh", "target": "1.1.1.1", "enabled": True, "interval_seconds": 60},
    ], {"fresh": {"last_at": now - timedelta(seconds=30)}})
    calls = []

    async def fake_probe(db, *, target, check_id, owner, timeout,
                         retries=0, check_name=""):
        calls.append((target, check_id, owner, timeout))
        return {"status": "up"}

    monkeypatch.setattr(monitoring, "probe_target", fake_probe)
    out = await monitoring.run_monitoring_probe_sweep(db, owner="host:1", now=now)

    assert calls == [("8.8.8.8", "due", "host:1", 2.0)]
    assert out == {"checked": 2, "probed": 1, "skipped_not_due": 1, "errors": 0,
                   "retried": EMPTY_RETRY}


@pytest.mark.anyio
async def test_sweep_does_not_load_or_probe_disabled_checks(monkeypatch):
    db = _Db([])

    async def fail_probe(*_args, **_kwargs):
        raise AssertionError("disabled check must not be probed")

    monkeypatch.setattr(monitoring, "probe_target", fail_probe)
    out = await monitoring.run_monitoring_probe_sweep(db, owner="host:1")

    assert out == {"checked": 0, "probed": 0, "skipped_not_due": 0, "errors": 0,
                   "retried": EMPTY_RETRY}


@pytest.mark.anyio
async def test_sweep_continues_after_one_check_fails(monkeypatch):
    db = _Db([
        {"_id": "bad", "target": "bad.example", "enabled": True},
        {"_id": "good", "target": "8.8.8.8", "enabled": True},
    ])
    calls = []

    async def fake_probe(db, *, target, check_id, owner, timeout,
                         retries=0, check_name=""):
        calls.append(check_id)
        if check_id == "bad":
            raise RuntimeError("probe broke")
        return {"status": "up"}

    monkeypatch.setattr(monitoring, "probe_target", fake_probe)
    out = await monitoring.run_monitoring_probe_sweep(db, owner="host:1")

    assert calls == ["bad", "good"]
    assert out == {"checked": 2, "probed": 1, "skipped_not_due": 0, "errors": 1,
                   "retried": EMPTY_RETRY}


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

    async def fake_probe(db, *, target, check_id, owner, timeout,
                         retries=0, check_name=""):
        calls.append(check_id)
        return {"status": "up"}

    monkeypatch.setattr(monitoring, "probe_target", fake_probe)
    await monitoring.run_monitoring_probe_sweep(db, owner="host:1", now=now)

    assert calls == ["invalid", "future"]


@pytest.mark.anyio
async def test_sweep_passes_persisted_retries_and_name_to_probe(monkeypatch):
    """The sweep must forward the check's retry policy, not silently use 0."""
    now = datetime(2026, 8, 11, 11, 0, tzinfo=timezone.utc)
    db = _Db([{"_id": "c1", "name": "DNS", "target": "8.8.8.8",
               "enabled": True, "interval_seconds": 60, "retries": 3}])
    seen = {}

    async def fake_probe(db, *, target, check_id, owner, timeout,
                         retries=0, check_name=""):
        seen.update(retries=retries, check_name=check_name)
        return {"status": "up"}

    monkeypatch.setattr(monitoring, "probe_target", fake_probe)
    await monitoring.run_monitoring_probe_sweep(db, owner="host:1", now=now)

    assert seen == {"retries": 3, "check_name": "DNS"}


@pytest.mark.anyio
async def test_sweep_retry_failure_does_not_break_the_probe_summary(monkeypatch):
    now = datetime(2026, 8, 11, 11, 0, tzinfo=timezone.utc)
    db = _Db([{"_id": "c1", "target": "8.8.8.8", "enabled": True,
               "interval_seconds": 60}])

    async def fake_probe(db, *, target, check_id, owner, timeout,
                         retries=0, check_name=""):
        return {"status": "up"}

    async def boom(*a, **k):
        raise RuntimeError("retry exploded")

    monkeypatch.setattr(monitoring, "probe_target", fake_probe)
    monkeypatch.setattr(monitoring, "retry_undelivered_monitoring_alerts", boom)

    out = await monitoring.run_monitoring_probe_sweep(db, owner="host:1", now=now)

    # A broken retry pass must never be reported as a probe error.
    assert out["probed"] == 1
    assert out["errors"] == 0
    assert "retried" not in out
