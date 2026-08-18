"""Regression tests for NOC endpoints: pagination, filter, sort.

Endpoints covered:
- GET /admin/noc/events
- GET /admin/noc/blackhole-log
- GET /admin/noc/ddos/incidents

Each endpoint must support:
- skip / limit pagination with total count (paginate=true)
- server-side filtering
- server-side sort (asc / desc)
- backward-compatible array return when paginate=false (default)
"""
from __future__ import annotations
from unittest.mock import AsyncMock
from bson import ObjectId
import pytest

from portal.routes import noc as noc_routes


class _Cursor:
    """Async cursor mock supporting sort, skip, limit, to_list, and async iteration."""
    def __init__(self, rows):
        self.rows = list(rows)
        self._skip = 0
        self._limit = None

    def sort(self, key, direction=-1):
        reverse = direction == -1
        self.rows = sorted(self.rows, key=lambda r: r.get(key, ""), reverse=reverse)
        return self

    def skip(self, n):
        self._skip = n
        return self

    def limit(self, n):
        self._limit = n
        return self

    def _sliced(self):
        start = self._skip or 0
        end = start + (self._limit if self._limit is not None else len(self.rows))
        return self.rows[start:end]

    async def to_list(self, _limit):
        return self._sliced()

    def __aiter__(self):
        self._iter = iter(self._sliced())
        return self

    async def __anext__(self):
        try:
            return next(self._iter)
        except StopIteration:
            raise StopAsyncIteration


class _Collection:
    def __init__(self, rows):
        self.rows = rows

    def find(self, query):
        return _Cursor(self._filtered(query))

    async def count_documents(self, query):
        return len(self._filtered(query))

    def _filtered(self, query):
        if not query:
            return list(self.rows)
        out = []
        for r in self.rows:
            match = True
            for k, v in query.items():
                if k == "$or":
                    match = any(
                        r.get(field, "").lower().find(condition["$regex"].lower()) >= 0
                        for clause in v
                        for field, condition in clause.items()
                        if isinstance(condition, dict) and "$regex" in condition
                    )
                elif isinstance(v, dict) and "$regex" in v:
                    match = r.get(k, "").lower().find(v["$regex"].lower()) >= 0
                else:
                    match = r.get(k) == v
                if not match:
                    break
            if match:
                out.append(r)
        return out


class _Db:
    def __init__(self):
        self.noc_events = _Collection([])
        self.blackhole_log = _Collection([])
        self.ddos_incidents = _Collection([])


@pytest.fixture
def db(monkeypatch):
    value = _Db()
    monkeypatch.setattr(noc_routes, "_get_db", AsyncMock(return_value=value))
    return value


@pytest.fixture
def admin():
    return {"role": "admin", "email": "admin@example.test"}


def _event(i: int, **overrides):
    base = {
        "_id": ObjectId(),
        "device_id": ObjectId(),
        "device_name": f"router-{i}",
        "device_host": f"10.0.0.{i}",
        "type": "device_down" if i % 2 == 0 else "device_up",
        "message": f"Transition {i}",
        "at": f"2026-08-14T{10+i:02d}:00:00Z",
        "email_notified": i % 3 == 0,
    }
    base.update(overrides)
    return base


def _blackhole(i: int, **overrides):
    base = {
        "_id": ObjectId(),
        "prefix": f"157.20.32.{i}/32",
        "action": "add" if i % 2 == 0 else "remove",
        "by": f"actor-{i}",
        "source": "auto" if i % 3 == 0 else "manual",
        "device": "RO.BGP",
        "ok": True,
        "at": f"2026-08-14T{10+i:02d}:00:00Z",
    }
    base.update(overrides)
    return base


def _incident(i: int, **overrides):
    base = {
        "_id": ObjectId(),
        "target": f"157.20.32.{i}",
        "direction": "inbound" if i % 2 == 0 else "outbound",
        "status": "active" if i % 3 != 0 else "resolved",
        "action": "alert_blackhole",
        "mitigation_type": "local_blackhole",
        "started_at": f"2026-08-14T{10+i:02d}:00:00Z",
        "ended_at": None,
        "bps": 1_000_000 * i,
        "pps": 1000 * i,
        "notified": [],
        "blackholed_prefix": f"157.20.32.{i}/32" if i % 2 == 0 else None,
    }
    base.update(overrides)
    return base


# ============================================================
# /admin/noc/events
# ============================================================
@pytest.mark.anyio
async def test_noc_events_pagination_paginated(db, admin):
    """Events: paginate=true returns {items, total, limit, skip}."""
    db.noc_events.rows = [_event(i) for i in range(25)]

    res = await noc_routes.noc_events_list(admin, limit=10, skip=0, paginate=True)
    assert res["total"] == 25
    assert res["limit"] == 10
    assert res["skip"] == 0
    assert len(res["items"]) == 10
    # newest first (at desc)
    assert res["items"][0]["at"] > res["items"][-1]["at"]

    res2 = await noc_routes.noc_events_list(admin, limit=10, skip=10, paginate=True)
    assert res2["total"] == 25
    assert res2["skip"] == 10
    assert len(res2["items"]) == 10
    assert res2["items"][0]["id"] != res["items"][0]["id"]


@pytest.mark.anyio
async def test_noc_events_backward_compat_array(db, admin):
    """Events: default (paginate=false) returns array, not object."""
    db.noc_events.rows = [_event(i) for i in range(3)]
    res = await noc_routes.noc_events_list(admin)
    assert isinstance(res, list)
    assert len(res) == 3


@pytest.mark.anyio
async def test_noc_events_filter_device_id(db, admin):
    """Events: filter by device_id."""
    dev_id = ObjectId()
    db.noc_events.rows = [
        _event(1, device_id=dev_id),
        _event(2, device_id=ObjectId()),
    ]
    res = await noc_routes.noc_events_list(admin, device_id=str(dev_id))
    assert len(res) == 1
    assert res[0]["device_id"] == str(dev_id)


@pytest.mark.anyio
async def test_noc_events_filter_type(db, admin):
    """Events: filter by type (device_up / device_down)."""
    db.noc_events.rows = [
        _event(1, type="device_down"),
        _event(2, type="device_up"),
    ]
    res = await noc_routes.noc_events_list(admin, type="device_down")
    assert len(res) == 1
    assert res[0]["type"] == "device_down"


@pytest.mark.anyio
async def test_noc_events_sort_asc(db, admin):
    """Events: sort=at&order=asc returns oldest first."""
    db.noc_events.rows = [
        _event(5, at="2026-08-14T15:00:00Z"),
        _event(1, at="2026-08-14T11:00:00Z"),
        _event(3, at="2026-08-14T13:00:00Z"),
    ]
    res = await noc_routes.noc_events_list(admin, sort="at", order="asc")
    assert res[0]["at"] < res[-1]["at"]


# ============================================================
# /admin/noc/blackhole-log
# ============================================================
@pytest.mark.anyio
async def test_blackhole_log_pagination_paginated(db, admin):
    """Blackhole log: paginate=true returns {items, total, limit, skip}."""
    db.blackhole_log.rows = [_blackhole(i) for i in range(25)]

    res = await noc_routes.noc_blackhole_log(admin=admin, limit=10, skip=0, paginate=True)
    assert res["total"] == 25
    assert len(res["items"]) == 10
    assert res["items"][0]["at"] > res["items"][-1]["at"]

    res2 = await noc_routes.noc_blackhole_log(admin=admin, limit=10, skip=10, paginate=True)
    assert res2["total"] == 25
    assert len(res2["items"]) == 10


@pytest.mark.anyio
async def test_blackhole_log_backward_compat_array(db, admin):
    """Blackhole log: default returns array."""
    db.blackhole_log.rows = [_blackhole(i) for i in range(3)]
    res = await noc_routes.noc_blackhole_log(admin=admin)
    assert isinstance(res, list)
    assert len(res) == 3


@pytest.mark.anyio
async def test_blackhole_log_search(db, admin):
    """Blackhole log: search by prefix (case-insensitive)."""
    db.blackhole_log.rows = [
        _blackhole(1, prefix="157.20.32.100/32"),
        _blackhole(2, prefix="157.20.32.200/32"),
    ]
    res = await noc_routes.noc_blackhole_log(admin=admin, q="100")
    assert len(res) == 1
    assert "100" in res[0]["prefix"]


@pytest.mark.anyio
async def test_blackhole_log_filter_action(db, admin):
    """Blackhole log: filter by action=add."""
    db.blackhole_log.rows = [
        _blackhole(1, action="add"),
        _blackhole(2, action="remove"),
    ]
    res = await noc_routes.noc_blackhole_log(admin=admin, action="add")
    assert len(res) == 1
    assert res[0]["action"] == "add"


@pytest.mark.anyio
async def test_blackhole_log_filter_source(db, admin):
    """Blackhole log: filter by source=auto."""
    db.blackhole_log.rows = [
        _blackhole(1, source="auto"),
        _blackhole(2, source="manual"),
    ]
    res = await noc_routes.noc_blackhole_log(admin=admin, source="auto")
    assert len(res) == 1
    assert res[0]["source"] == "auto"


# ============================================================
# /admin/noc/ddos/incidents
# ============================================================
@pytest.mark.anyio
async def test_ddos_incidents_pagination_paginated(db, admin):
    """DDoS incidents: paginate=true returns {items, total, limit, skip}."""
    db.ddos_incidents.rows = [_incident(i) for i in range(25)]

    res = await noc_routes.noc_ddos_incidents(admin=admin, limit=10, skip=0, paginate=True)
    assert res["total"] == 25
    assert len(res["items"]) == 10
    assert res["items"][0]["started_at"] > res["items"][-1]["started_at"]

    res2 = await noc_routes.noc_ddos_incidents(admin=admin, limit=10, skip=10, paginate=True)
    assert res2["total"] == 25
    assert len(res2["items"]) == 10


@pytest.mark.anyio
async def test_ddos_incidents_backward_compat_array(db, admin):
    """DDoS incidents: default returns array."""
    db.ddos_incidents.rows = [_incident(i) for i in range(3)]
    res = await noc_routes.noc_ddos_incidents(admin=admin)
    assert isinstance(res, list)
    assert len(res) == 3


@pytest.mark.anyio
async def test_ddos_incidents_filter_status(db, admin):
    """DDoS incidents: filter by status."""
    db.ddos_incidents.rows = [
        _incident(1, status="active"),
        _incident(2, status="resolved"),
    ]
    res = await noc_routes.noc_ddos_incidents(admin=admin, status="active")
    assert len(res) == 1
    assert res[0]["status"] == "active"


@pytest.mark.anyio
async def test_ddos_incidents_sort_asc(db, admin):
    """DDoS incidents: sort=started_at&order=asc returns oldest first."""
    db.ddos_incidents.rows = [
        _incident(5, started_at="2026-08-14T15:00:00Z"),
        _incident(1, started_at="2026-08-14T11:00:00Z"),
        _incident(3, started_at="2026-08-14T13:00:00Z"),
    ]
    res = await noc_routes.noc_ddos_incidents(admin=admin, sort="started_at", order="asc")
    assert res[0]["started_at"] < res[-1]["started_at"]