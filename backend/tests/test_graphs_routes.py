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

    async def to_list(self, _limit):
        return self.rows


class _Graphs:
    def __init__(self):
        self.rows = []
        self.inserted = []
        self.updated = []
        self.deleted = []

    def find(self, _query=None, **_kw):
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


class _Samples:
    def __init__(self):
        self.inserted = []


class _DummyColl:
    """Minimal collection that handles find() for downsampling queries."""
    def __init__(self):
        self.docs = []

    def find(self, _query=None, **_kw):
        return _Cursor(self.docs)


class _Db:
    def __init__(self):
        self.monitoring_graphs = _Graphs()
        self.monitoring_graph_samples_raw = _Samples()
        self.monitoring_graph_samples_hourly = _DummyColl()
        self.monitoring_graph_samples_daily = _DummyColl()


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
