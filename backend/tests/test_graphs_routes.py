"""Route-level tests for the graph CRUD endpoints.

Mirrors the pattern from test_monitoring_checks_routes.py: mock Mongo collections,
call route functions directly, assert behaviour without importing FastAPI.
"""
from unittest.mock import AsyncMock

import pytest
from bson import ObjectId
from fastapi import HTTPException

from portal.routes import graphs as routes


# ---------------------------------------------------------------------------
# Fake DB
# ---------------------------------------------------------------------------
class _Cursor:
    def __init__(self, rows):
        self.rows = rows

    def sort(self, *_a, **_kw):
        return self

    async def to_list(self, length=None):
        return self.rows

    def __aiter__(self):
        self._it = iter(self.rows)
        return self

    async def __anext__(self):
        try:
            return next(self._it)
        except StopIteration:
            raise StopAsyncIteration


class _Graphs:
    def __init__(self):
        self.rows = []
        self.inserted = []
        self.updated = []
        self.deleted = []

    def find(self, query=None, projection=None, **_kw):
        """Accept the projection arg routes pass positionally
        (db.coll.find(filter, projection)). The fake ignores the filter — tests
        that need filtering override find() explicitly."""
        return _Cursor(self.rows)

    async def insert_one(self, doc):
        self.inserted.append(doc)
        return type("R", (), {"inserted_id": ObjectId()})()

    async def find_one(self, query):
        wanted = query.get("_id")
        row = next((r for r in self.rows if r.get("_id") == wanted), None)
        if row is None:
            return None
        # Simulate visible_roles filtering at the query level
        vr = query.get("visible_roles")
        if vr is not None and vr not in (row.get("visible_roles") or []):
            return None
        # Simulate client_id filtering at the query level
        cid = query.get("client_id")
        if cid is not None and row.get("client_id") != cid:
            return None
        return row

    async def update_one(self, query, update):
        self.updated.append((query, update))
        wanted = query.get("_id")
        row = next((r for r in self.rows if r.get("_id") == wanted), None)
        if row is not None:
            row.update(update.get("$set", {}))
        return type("R", (), {"matched_count": int(row is not None)})()

    async def delete_one(self, query):
        self.deleted.append(query)
        wanted = query.get("_id")
        match = any(r.get("_id") == wanted for r in self.rows)
        if match:
            self.rows = [r for r in self.rows if r.get("_id") != wanted]
        return type("R", (), {"deleted_count": int(match)})()


class _SampleMixin:
    """Shared fake surface for the rollup collections.

    Models the motor collection API used by monitoring_health and the
    downsample sweeps: attribute access is fine for most calls, but
    db[name] indexing must also resolve (health iterates a table of names).
    """
    def __init__(self):
        self.docs = []
        self.indexes = []

    async def estimated_document_count(self):
        return len(self.docs)

    def list_indexes(self):
        """Sync, mirroring motor: routes call `await coll.list_indexes().to_list()`."""
        return _Cursor(self.indexes)

    async def find_one(self, _query=None, _projection=None, **_kwargs):
        return self.docs[-1] if self.docs else None


class _Samples(_SampleMixin):
    def __init__(self):
        super().__init__()
        self.inserted = []


class _DummyColl(_SampleMixin):
    """Minimal collection that also handles find() for downsampling queries."""
    def find(self, _query=None, _projection=None, **_kw):
        return _Cursor(self.docs)


class _Leases:
    def __init__(self, rows=None):
        self.rows = rows or []

    def find(self, _query=None, _projection=None, **_kw):
        return _Cursor(self.rows)


class _Db:
    _COLLECTIONS = ("monitoring_graphs", "monitoring_graph_samples_raw",
                    "monitoring_graph_samples_hourly", "monitoring_graph_samples_daily",
                    "monitoring_graph_samples_halfhour", "scheduler_leases",
                    "graph_alert_rules", "monitoring_graph_alerts",
                    "monitoring_maintenance_windows")

    def __init__(self):
        self.monitoring_graphs = _Graphs()
        self.monitoring_graph_samples_raw = _Samples()
        self.monitoring_graph_samples_hourly = _DummyColl()
        self.monitoring_graph_samples_daily = _DummyColl()
        self.monitoring_graph_samples_halfhour = _DummyColl()
        self.scheduler_leases = _Leases()
        self.graph_alert_rules = _DummyColl()
        self.monitoring_graph_alerts = _DummyColl()
        self.monitoring_maintenance_windows = _DummyColl()

    def __getitem__(self, name):
        """Motor exposes collections via db[name]; mirror it so route code that
        iterates a collection table stays testable."""
        if name in self._COLLECTIONS:
            return getattr(self, name)
        raise KeyError(name)


@pytest.fixture
def db(monkeypatch):
    value = _Db()
    monkeypatch.setattr(routes, "_get_db", AsyncMock(return_value=value))
    return value


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_create_graph_persists_with_defaults(db):
    out = await routes.create_graph(
        {"name": "Core Switch Traffic", "target": "8.8.8.8", "snmp_oid": "1.3.6.1"},
        {"role": "admin", "_id": "admin1"},
    )
    assert out["name"] == "Core Switch Traffic"
    assert out["enabled"] is True
    assert out["visible_roles"] == ["admin", "support"]
    assert out["snmp_community"] == "public"
    assert out["snmp_port"] == 161
    assert db.monitoring_graphs.inserted[0]["visible_roles"] == ["admin", "support"]


@pytest.mark.anyio
async def test_create_graph_with_custom_visible_roles(db):
    out = await routes.create_graph(
        {"name": "Sales Graph", "target": "8.8.8.8", "snmp_oid": "1.3.6.1",
         "visible_roles": ["admin", "sales", "finance"]},
        {"role": "admin"},
    )
    assert out["visible_roles"] == ["admin", "sales", "finance"]


@pytest.mark.anyio
async def test_create_graph_rejects_private_target(db):
    with pytest.raises(HTTPException) as exc:
        await routes.create_graph(
            {"name": "Internal", "target": "10.0.0.1", "snmp_oid": "1.3.6.1"},
            {"role": "admin"},
        )
    assert exc.value.status_code == 400
    assert db.monitoring_graphs.inserted == []


@pytest.mark.anyio
async def test_create_graph_rejects_bad_interval(db):
    with pytest.raises(HTTPException) as exc:
        await routes.create_graph(
            {"name": "Bad", "target": "8.8.8.8", "snmp_oid": "1.3.6.1", "interval_seconds": 5},
            {"role": "admin"},
        )
    assert exc.value.status_code == 400


@pytest.mark.anyio
async def test_create_graph_filters_invalid_roles(db):
    out = await routes.create_graph(
        {"name": "G", "target": "8.8.8.8", "snmp_oid": "1.3.6.1",
         "visible_roles": ["admin", "hacker", "sales"]},
        {"role": "admin"},
    )
    assert out["visible_roles"] == ["admin", "sales"]


@pytest.mark.anyio
async def test_create_graph_empty_roles_defaults_to_admin_support(db):
    out = await routes.create_graph(
        {"name": "G", "target": "8.8.8.8", "snmp_oid": "1.3.6.1", "visible_roles": []},
        {"role": "admin"},
    )
    assert out["visible_roles"] == ["admin", "support"]


# ---------------------------------------------------------------------------
# Update
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_update_graph_visible_roles(db):
    gid = str(ObjectId())
    db.monitoring_graphs.rows = [{
        "_id": ObjectId(gid), "name": "G", "target": "8.8.8.8",
        "visible_roles": ["admin", "support"],
    }]
    out = await routes.update_graph(gid, {"visible_roles": ["admin", "sales"]}, {"role": "admin"})
    assert out["visible_roles"] == ["admin", "sales"]


@pytest.mark.anyio
async def test_update_graph_not_found(db):
    with pytest.raises(HTTPException) as exc:
        await routes.update_graph(str(ObjectId()), {"name": "X"}, {"role": "admin"})
    assert exc.value.status_code == 404


@pytest.mark.anyio
async def test_update_graph_no_fields_400(db):
    gid = str(ObjectId())
    db.monitoring_graphs.rows = [{"_id": ObjectId(gid), "name": "G"}]
    with pytest.raises(HTTPException) as exc:
        await routes.update_graph(gid, {}, {"role": "admin"})
    assert exc.value.status_code == 400


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_delete_graph_success(db):
    gid = str(ObjectId())
    db.monitoring_graphs.rows = [{"_id": ObjectId(gid), "name": "G"}]
    out = await routes.delete_graph(gid, {"role": "admin"})
    assert out["ok"] is True
    assert db.monitoring_graphs.rows == []


@pytest.mark.anyio
async def test_delete_graph_not_found(db):
    with pytest.raises(HTTPException) as exc:
        await routes.delete_graph(str(ObjectId()), {"role": "admin"})
    assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# List — RBAC filtering by visible_roles
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_list_graphs_admin_sees_all(db):
    db.monitoring_graphs.rows = [
        {"_id": ObjectId(), "name": "G1", "target": "8.8.8.8", "visible_roles": ["admin"]},
        {"_id": ObjectId(), "name": "G2", "target": "8.8.8.8", "visible_roles": ["admin", "support"]},
        {"_id": ObjectId(), "name": "G3", "target": "8.8.8.8", "visible_roles": ["admin", "sales"]},
    ]
    out = await routes.list_graphs(staff={"role": "admin"})
    assert len(out) == 3


@pytest.mark.anyio
async def test_list_graphs_support_sees_only_assigned(db):
    db.monitoring_graphs.rows = [
        {"_id": ObjectId(), "name": "G1", "target": "8.8.8.8", "visible_roles": ["admin"]},
        {"_id": ObjectId(), "name": "G2", "target": "8.8.8.8", "visible_roles": ["admin", "support"]},
        {"_id": ObjectId(), "name": "G3", "target": "8.8.8.8", "visible_roles": ["admin", "sales"]},
    ]
    # Mock find to simulate the visible_roles filter at Mongo level
    original_find = db.monitoring_graphs.find
    def filtered_find(query=None, **kw):
        vr = (query or {}).get("visible_roles")
        if vr:
            rows = [r for r in db.monitoring_graphs.rows if vr in (r.get("visible_roles") or [])]
        else:
            rows = list(db.monitoring_graphs.rows)
        return _Cursor(rows)
    db.monitoring_graphs.find = filtered_find

    out = await routes.list_graphs(staff={"role": "support"})
    assert len(out) == 1
    assert out[0]["name"] == "G2"


# ---------------------------------------------------------------------------
# Graph data — RBAC enforcement
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_graph_data_admin_can_access_any(db):
    gid = str(ObjectId())
    db.monitoring_graphs.rows = [{
        "_id": ObjectId(gid), "name": "G", "target": "8.8.8.8",
        "visible_roles": ["admin"],
    }]
    # Mock get_graph_data to avoid needing real samples
    routes.get_graph_data = AsyncMock(return_value=([], "raw"))
    out = await routes.graph_data(
        gid, from_="2026-01-01T00:00:00Z", to="2026-01-02T00:00:00Z",
        staff={"role": "admin"},
    )
    assert out["graph_id"] == gid


@pytest.mark.anyio
async def test_graph_data_support_blocked_if_not_visible(db):
    gid = str(ObjectId())
    db.monitoring_graphs.rows = [{
        "_id": ObjectId(gid), "name": "G", "target": "8.8.8.8",
        "visible_roles": ["admin"],  # support not listed
    }]
    with pytest.raises(HTTPException) as exc:
        await routes.graph_data(
            gid, from_="2026-01-01T00:00:00Z", to="2026-01-02T00:00:00Z",
            staff={"role": "support"},
        )
    assert exc.value.status_code == 404


@pytest.mark.anyio
async def test_graph_data_rejects_invalid_date(db):
    gid = str(ObjectId())
    db.monitoring_graphs.rows = [{
        "_id": ObjectId(gid), "name": "G", "target": "8.8.8.8",
        "visible_roles": ["admin", "support"],
    }]
    with pytest.raises(HTTPException) as exc:
        await routes.graph_data(
            gid, from_="not-a-date", to="2026-01-02T00:00:00Z",
            staff={"role": "admin"},
        )
    assert exc.value.status_code == 400


@pytest.mark.anyio
async def test_graph_data_rejects_from_after_to(db):
    gid = str(ObjectId())
    db.monitoring_graphs.rows = [{
        "_id": ObjectId(gid), "name": "G", "target": "8.8.8.8",
        "visible_roles": ["admin"],
    }]
    with pytest.raises(HTTPException) as exc:
        await routes.graph_data(
            gid, from_="2026-01-03T00:00:00Z", to="2026-01-01T00:00:00Z",
            staff={"role": "admin"},
        )
    assert exc.value.status_code == 400


# ---------------------------------------------------------------------------
# Client isolation
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_client_list_only_own_graphs(db):
    client_oid = ObjectId()
    other_oid = ObjectId()
    db.monitoring_graphs.rows = [
        {"_id": ObjectId(), "name": "Mine", "target": "8.8.8.8",
         "enabled": True, "client_id": client_oid},
        {"_id": ObjectId(), "name": "Other", "target": "8.8.8.8",
         "enabled": True, "client_id": other_oid},
        {"_id": ObjectId(), "name": "Internal", "target": "8.8.8.8",
         "enabled": True, "client_id": None},
    ]
    # Mock find to simulate client_id filter
    def filtered_find(query=None, **kw):
        q = query or {}
        cid = q.get("client_id")
        if cid:
            rows = [r for r in db.monitoring_graphs.rows if r.get("client_id") == cid]
        else:
            rows = list(db.monitoring_graphs.rows)
        return _Cursor(rows)
    db.monitoring_graphs.find = filtered_find

    out = await routes.client_list_graphs(user={"role": "client", "id": str(client_oid)})
    assert len(out) == 1
    assert out[0]["name"] == "Mine"


@pytest.mark.anyio
async def test_client_list_rejects_non_client(db):
    with pytest.raises(HTTPException) as exc:
        await routes.client_list_graphs(user={"role": "admin", "id": str(ObjectId())})
    assert exc.value.status_code == 403


@pytest.mark.anyio
async def test_client_graph_data_rejects_other_client_graph(db):
    my_oid = ObjectId()
    other_oid = ObjectId()
    gid = str(ObjectId())
    db.monitoring_graphs.rows = [{
        "_id": ObjectId(gid), "name": "Other", "target": "8.8.8.8",
        "client_id": other_oid,
    }]
    with pytest.raises(HTTPException) as exc:
        await routes.client_graph_data(
            gid, from_="2026-01-01T00:00:00Z", to="2026-01-02T00:00:00Z",
            user={"role": "client", "id": str(my_oid)},
        )
    assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# Manual run
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_run_graph_manual_not_found(db):
    with pytest.raises(HTTPException) as exc:
        await routes.run_graph_manual(str(ObjectId()), {"role": "admin", "id": "a1"})
    assert exc.value.status_code == 404


@pytest.mark.anyio
async def test_run_graph_manual_success(db, monkeypatch):
    gid = str(ObjectId())
    db.monitoring_graphs.rows = [{
        "_id": ObjectId(gid), "name": "G", "target": "8.8.8.8",
        "type": "snmp_traffic_in", "snmp_oid": "1.3.6.1",
    }]
    # Mock probe_graph to avoid real SNMP calls
    monkeypatch.setattr(routes, "probe_graph", AsyncMock(return_value={"probed": True, "value": 42.0}))
    out = await routes.run_graph_manual(gid, {"role": "admin", "id": "a1"})
    assert out["probed"] is True
    assert out["value"] == 42.0


# ---------------------------------------------------------------------------
# Validation bug regressions
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_create_graph_rejects_unknown_type(db):
    """create_graph must reject unsupported type values with HTTP 400."""
    with pytest.raises(HTTPException) as exc:
        await routes.create_graph(
            {"name": "Bad", "target": "8.8.8.8", "type": "not-a-graph", "snmp_oid": "1.3.6.1"},
            {"role": "admin"},
        )
    assert exc.value.status_code == 400
    assert db.monitoring_graphs.inserted == []


@pytest.mark.anyio
async def test_create_graph_empty_oid_returns_400(db):
    """Empty snmp_oid for an SNMP graph type must return HTTP 400, not 500."""
    with pytest.raises(HTTPException) as exc:
        await routes.create_graph(
            {"name": "Bad", "target": "8.8.8.8", "type": "snmp_cpu", "snmp_oid": ""},
            {"role": "admin"},
        )
    assert exc.value.status_code == 400
    assert db.monitoring_graphs.inserted == []


@pytest.mark.anyio
async def test_create_graph_non_integer_port_returns_400(db):
    """Non-integer snmp_port must return HTTP 400, not 500."""
    with pytest.raises(HTTPException) as exc:
        await routes.create_graph(
            {"name": "Bad", "target": "8.8.8.8", "type": "snmp_cpu",
             "snmp_oid": "1.3.6.1.2.1.25.3.3.1.2.1", "snmp_port": "abc"},
            {"role": "admin"},
        )
    assert exc.value.status_code == 400


@pytest.mark.anyio
async def test_update_graph_rejects_unknown_type(db):
    """update_graph must reject unknown type values with HTTP 400."""
    gid = str(ObjectId())
    db.monitoring_graphs.rows = [{"_id": ObjectId(gid), "name": "G", "target": "8.8.8.8"}]
    with pytest.raises(HTTPException) as exc:
        await routes.update_graph(gid, {"type": "not-a-graph"}, {"role": "admin"})
    assert exc.value.status_code == 400


@pytest.mark.anyio
async def test_update_graph_non_integer_port_returns_400(db):
    """Non-integer snmp_port in update must return HTTP 400, not 500."""
    gid = str(ObjectId())
    db.monitoring_graphs.rows = [{"_id": ObjectId(gid), "name": "G", "target": "8.8.8.8"}]
    with pytest.raises(HTTPException) as exc:
        await routes.update_graph(gid, {"snmp_port": "abc"}, {"role": "admin"})
    assert exc.value.status_code == 400


def test_search_clients_uses_narrow_role_guard():
    """search_clients must use require_roles, not get_current_staff (RBAC gate)."""
    import inspect
    source = inspect.getsource(routes.search_clients)
    assert "get_current_staff" not in source, (
        "search_clients still uses get_current_staff — creative role can list clients"
    )


# ---------------------------------------------------------------------------
# Health endpoint
# ---------------------------------------------------------------------------
from datetime import datetime as _dt, timedelta as _td, timezone as _tz


def _ttl_index_row(time_field="at", expire_after_seconds=None):
    return {"name": f"{time_field}_1", "key": {time_field: 1},
            "expireAfterSeconds": expire_after_seconds}


@pytest.mark.anyio
async def test_health_healthy_when_ttl_and_graphs_fresh(db):
    from portal.routes.graphs import _SAMPLE_COLLECTIONS
    assert _SAMPLE_COLLECTIONS, "health endpoint sources from a non-empty table"

    now = _dt.now(_tz.utc)
    for name, field in _SAMPLE_COLLECTIONS:
        coll = db[name]
        coll.docs = [{field: now}]
        coll.find_one = AsyncMock(return_value={field: now})
        coll.indexes = [_ttl_index_row(field, expire_after_seconds=7 * 86400)]
    db.monitoring_graphs.rows = [{
        "_id": ObjectId(), "name": "VLAN x",
        "interval_seconds": 20, "last_poll_at": now,
        "last_poll_state": "ok", "last_poll_error": "",
    }]
    db.scheduler_leases = _Leases([
        {"_id": "job:graph_sweep", "owner": "me", "expires_at": now + _td(minutes=5)},
    ])

    out = await routes.monitoring_health({"role": "admin", "id": "a"})

    assert out["problems"] == [], out["problems"]
    assert out["healthy"] is True
    assert out["graphs"]["total"] == 1
    assert out["graphs"]["unhealthy"] == 0
    assert out["graphs"]["items"][0]["healthy"] is True
    assert all(c["ttl_ok"] for c in out["collections"])
    assert out["leases"]["active"] == 1


@pytest.mark.anyio
async def test_health_flags_missing_ttl_and_stale_graph(db):
    now = _dt.now(_tz.utc)
    # raw has docs but no TTL index anywhere -> silent unbounded growth
    db.monitoring_graph_samples_raw.docs = [{"at": now}]
    db.monitoring_graph_samples_raw.find_one = AsyncMock(return_value={"at": now})
    db.monitoring_graphs.rows = [{
        "_id": ObjectId(), "name": "Dead",
        "interval_seconds": 20,
        "last_poll_at": now - _td(hours=2),
        "last_poll_state": "error", "last_poll_error": "snmp timeout",
    }]

    out = await routes.monitoring_health({"role": "support", "id": "b"})

    joined = " | ".join(out["problems"])
    assert "no TTL index" in joined, joined
    assert "stalled or in error" in joined, joined
    assert out["healthy"] is False
    assert out["graphs"]["unhealthy"] == 1


@pytest.mark.anyio
async def test_health_support_sees_only_own_graphs(db):
    """RBAC regression (attack a): a support viewer must not learn about — or
    count — graphs outside their visible_roles.

    The old tests invoked monitoring_health directly and the fake find()
    ignored the query, so nothing proved the endpoint applied the same
    visible_roles filter as the listings. This test records the query the
    endpoint sends to Mongo AND filters the fake rows by it, proving both
    the filter is sent and the response cannot leak other graphs."""
    now = _dt.now(_tz.utc)
    own = {"_id": ObjectId(), "name": "Mine", "display_name": "Mine",
           "interval_seconds": 20, "last_poll_at": now,
           "last_poll_state": "ok", "last_poll_error": "",
           "visible_roles": ["admin", "support"]}
    admin_only = {"_id": ObjectId(), "name": "SecretAdmin",
                  "display_name": "SecretAdmin",
                  "interval_seconds": 20,
                  "last_poll_at": now - _td(hours=2),
                  "last_poll_state": "error",
                  "last_poll_error": "snmp timeout",
                  "visible_roles": ["admin"]}
    sales_only = {"_id": ObjectId(), "name": "SalesGraph",
                  "display_name": "SalesGraph",
                  "interval_seconds": 20,
                  "last_poll_at": now - _td(hours=2),
                  "last_poll_state": "error",
                  "last_poll_error": "down",
                  "visible_roles": ["admin", "sales"]}
    db.monitoring_graphs.rows = [own, admin_only, sales_only]

    seen_queries = []

    def filtered_find(query=None, projection=None, **_kw):
        seen_queries.append(query or {})
        rows = db.monitoring_graphs.rows
        vr = (query or {}).get("visible_roles")
        if vr:
            rows = [r for r in rows if vr in (r.get("visible_roles") or [])]
        return _Cursor(rows)

    db.monitoring_graphs.find = filtered_find

    out = await routes.monitoring_health({"role": "support", "id": "b"})

    # The endpoint must push the RBAC filter down to the query layer.
    assert seen_queries and seen_queries[0].get("visible_roles") == "support", (
        f"health query did not carry visible_roles filter: {seen_queries}")
    # Support sees exactly their own graph; the stalled admin/sales graphs
    # never surface in the response nor inflate the unhealthy count.
    assert out["graphs"]["total"] == 1, out["graphs"]
    assert out["graphs"]["items"][0]["name"] == "Mine"
    assert out["graphs"]["unhealthy"] == 0
    names = {i["name"] for i in out["graphs"]["items"]}
    assert "SecretAdmin" not in names, names
    assert "SalesGraph" not in names, names


@pytest.mark.anyio
async def test_health_admin_sees_all_graphs_and_flags_unhealthy(db):
    """Admins are not scoped by visible_roles: they see every graph so global
    health is not masked by the support filter."""
    now = _dt.now(_tz.utc)
    db.monitoring_graphs.rows = [
        {"_id": ObjectId(), "name": "A", "interval_seconds": 20,
         "last_poll_at": now, "last_poll_state": "ok", "last_poll_error": "",
         "visible_roles": ["admin"]},
        {"_id": ObjectId(), "name": "B", "interval_seconds": 20,
         "last_poll_at": now - _td(hours=2), "last_poll_state": "error",
         "last_poll_error": "timeout", "visible_roles": ["admin", "sales"]},
        {"_id": ObjectId(), "name": "C", "interval_seconds": 20,
         "last_poll_at": now - _td(hours=2), "last_poll_state": "error",
         "last_poll_error": "timeout", "visible_roles": ["admin", "support"]},
    ]
    seen_queries = []

    def unfiltered_find(query=None, projection=None, **_kw):
        seen_queries.append(query or {})
        return _Cursor(db.monitoring_graphs.rows)

    db.monitoring_graphs.find = unfiltered_find

    out = await routes.monitoring_health({"role": "admin", "id": "a"})

    assert seen_queries, "health endpoint never queried graphs"
    assert "visible_roles" not in seen_queries[0], seen_queries[0]
    assert out["graphs"]["total"] == 3, out["graphs"]
    assert out["graphs"]["unhealthy"] == 2, out["graphs"]
