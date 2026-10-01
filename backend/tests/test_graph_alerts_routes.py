"""Route-level tests: graph alert rules + maintenance windows CRUD (phase 3).

Covers:
* create/list/update/delete round-trip persists the fields the evaluator reads
* RBAC: every endpoint requires the admin/support role (AST contract)
* date validation: ends_at must be after starts_at
* health endpoint surfaces the alerts summary block
"""
from __future__ import annotations

import ast
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from bson import ObjectId
from fastapi import HTTPException

from portal import models as m
from portal.routes import graphs as routes

GRAPHS_FILE = Path(__file__).resolve().parents[1] / "portal/routes/graphs.py"


# ---------------------------------------------------------------------------
# Fake DB
# ---------------------------------------------------------------------------
def _matches(doc, query):
    """Small Mongo-query subset used by the behavioural access-control fakes."""
    query = query or {}
    if "$or" in query and not any(_matches(doc, branch) for branch in query["$or"]):
        return False
    for key, wanted in query.items():
        if key == "$or":
            continue
        actual = doc.get(key)
        if isinstance(wanted, dict) and "$in" in wanted:
            values = wanted["$in"]
            if isinstance(actual, list):
                if not any(v in actual for v in values):
                    return False
            elif actual not in values:
                return False
        elif actual != wanted:
            return False
    return True


class _Cursor:
    def __init__(self, rows):
        self.rows = rows

    def sort(self, *_a, **_kw):
        return self

    async def to_list(self, length=None):
        return list(self.rows)

    def __aiter__(self):
        self._it = iter(self.rows)
        return self

    async def __anext__(self):
        try:
            return next(self._it)
        except StopIteration:
            raise StopAsyncIteration


class _Coll:
    def __init__(self, docs=None):
        self.docs = list(docs or [])

    def find(self, query=None, *_a, **_kw):
        return _Cursor([d for d in self.docs if _matches(d, query)])

    async def find_one(self, query=None, *_a, **_kw):
        wanted = (query or {}).get("_id")
        return next((d for d in self.docs if d.get("_id") == wanted), None)

    async def insert_one(self, doc):
        doc.setdefault("_id", ObjectId())
        self.docs.append(doc)
        return type("R", (), {"inserted_id": doc["_id"]})()

    async def update_one(self, query, update, upsert=False):
        wanted = (query or {}).get("_id")
        row = next((d for d in self.docs if d.get("_id") == wanted), None)
        if row is not None:
            row.update(update.get("$set", {}))
        return type("R", (), {"matched_count": int(row is not None)})()

    async def delete_one(self, query):
        wanted = (query or {}).get("_id")
        before = len(self.docs)
        self.docs = [d for d in self.docs if d.get("_id") != wanted]
        return type("R", (), {"deleted_count": before - len(self.docs)})()

    async def count_documents(self, query=None):
        return sum(1 for d in self.docs if _matches(d, query))


class _SampleColl:
    """Minimal stand-in for the rollup/retention collections monitoring_health
    inspects; empty and index-less so the health verdict stays focused on the
    alerts block under test."""

    def __init__(self, docs=None, indexes=None):
        self.docs = list(docs or [])
        self.indexes = list(indexes or [])

    def find(self, query=None, *_a, **_kw):
        return _Cursor([d for d in self.docs if _matches(d, query)])

    async def estimated_document_count(self):
        return len(self.docs)

    def list_indexes(self):
        return _Cursor(self.indexes)


class _Db:
    _COLLECTIONS = ("graph_alert_rules", "monitoring_graph_alerts",
                    "monitoring_maintenance_windows", "monitoring_graphs",
                    "monitoring_graph_samples_raw", "monitoring_graph_samples_halfhour",
                    "monitoring_graph_samples_hourly", "monitoring_graph_samples_daily",
                    "scheduler_leases")

    def __init__(self):
        self.graph_alert_rules = _Coll()
        self.monitoring_graph_alerts = _Coll()
        self.monitoring_maintenance_windows = _Coll()
        self.monitoring_graphs = _GraphsColl()
        self.monitoring_graph_samples_raw = _SampleColl()
        self.monitoring_graph_samples_halfhour = _SampleColl()
        self.monitoring_graph_samples_hourly = _SampleColl()
        self.monitoring_graph_samples_daily = _SampleColl()
        self.scheduler_leases = _SampleColl()

    def __getitem__(self, name):
        if name in self._COLLECTIONS:
            return getattr(self, name)
        raise KeyError(name)


class _GraphsColl:
    """Fake monitoring_graphs whose read path honours the visible_roles query the
    scoping fix sends (this is what makes the behavioural RBAC tests
    fail-on-mutation: remove the filter from the route and the fake suddenly
    returns admin-only rows).

    The scoped routes resolve visible ids through ``distinct`` so authorization
    cannot silently weaken past a page cap; ``find`` stays for other callers.
    """

    def __init__(self, rows=None):
        self.rows = list(rows or [])
        self.queries = []

    def _visible(self, query=None):
        self.queries.append(query or {})
        rows = self.rows
        vr = (query or {}).get("visible_roles")
        if vr:
            rows = [r for r in rows if vr in (r.get("visible_roles") or [])]
        return rows

    def find(self, query=None, *_a, **_kw):
        return _Cursor(self._visible(query))

    async def distinct(self, key, query=None):
        return [r.get(key) for r in self._visible(query)]


@pytest.fixture
def db(monkeypatch):
    value = _Db()
    monkeypatch.setattr(routes, "_get_db", AsyncMock(return_value=value))
    monkeypatch.setattr(routes, "log_audit", AsyncMock())
    return value


ADMIN = {"role": "admin", "_id": "admin1", "id": "admin1"}


# ---------------------------------------------------------------------------
# Alert rules
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_alert_rule_create_persists_evaluator_fields(db):
    payload = m.GraphAlertRuleIn(name="In above 80M", metric="bps",
                                 comparator=">", threshold=80_000_000,
                                 consecutive=3, severity="critical")
    out = await routes.alert_rules_create(payload, None, ADMIN)
    assert out["name"] == "In above 80M"
    assert out["consecutive"] == 3
    assert out["severity"] == "critical"
    assert out["threshold"] == 80_000_000
    stored = db.graph_alert_rules.docs[0]
    # the evaluator matches rules on the collection + enabled flag
    assert stored["enabled"] is True
    assert stored["metric"] == "bps"


@pytest.mark.anyio
async def test_alert_rule_state_metric_allows_zero_threshold(db):
    payload = m.GraphAlertRuleIn(name="dead graph", metric="state")
    out = await routes.alert_rules_create(payload, None, ADMIN)
    assert out["metric"] == "state"
    assert out["threshold"] == 0


@pytest.mark.anyio
async def test_alert_rules_list_serializes_id(db):
    await routes.alert_rules_create(m.GraphAlertRuleIn(name="r one"), None, ADMIN)
    rows = await routes.alert_rules_list(ADMIN)
    assert len(rows) == 1
    assert rows[0]["id"] == str(db.graph_alert_rules.docs[0]["_id"])


@pytest.mark.anyio
async def test_alert_rule_update_and_delete(db):
    created = await routes.alert_rules_create(m.GraphAlertRuleIn(name="r one"), None, ADMIN)
    upd = await routes.alert_rules_update(
        created["id"], m.GraphAlertRuleIn(name="r two", severity="critical"), None, ADMIN)
    assert upd["name"] == "r two"
    assert upd["severity"] == "critical"
    res = await routes.alert_rules_delete(created["id"], ADMIN)
    assert res["deleted"] == 1


@pytest.mark.anyio
async def test_alert_rule_update_missing_404(db):
    with pytest.raises(HTTPException) as exc:
        await routes.alert_rules_update(
            str(ObjectId()), m.GraphAlertRuleIn(name="nope"), None, ADMIN)
    assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# Maintenance windows
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_maintenance_window_create_and_list(db):
    payload = m.MaintenanceWindowIn(name="Maint malam",
                                    starts_at="2026-10-01T22:00:00+07:00",
                                    ends_at="2026-10-02T02:00:00+07:00")
    out = await routes.maintenance_windows_create(payload, None, ADMIN)
    assert out["name"] == "Maint malam"
    assert out["graph_ids"] == []
    rows = await routes.maintenance_windows_list(ADMIN)
    assert len(rows) == 1


@pytest.mark.anyio
async def test_maintenance_window_rejects_inverted_dates(db):
    payload = m.MaintenanceWindowIn(name="bad",
                                    starts_at="2026-10-02T02:00:00+07:00",
                                    ends_at="2026-10-01T22:00:00+07:00")
    with pytest.raises(HTTPException) as exc:
        await routes.maintenance_windows_create(payload, None, ADMIN)
    assert exc.value.status_code == 422


@pytest.mark.anyio
async def test_maintenance_window_update_and_delete(db):
    created = await routes.maintenance_windows_create(
        m.MaintenanceWindowIn(name="w1", starts_at="2026-10-01T22:00:00+07:00",
                              ends_at="2026-10-02T02:00:00+07:00"), None, ADMIN)
    upd = await routes.maintenance_windows_update(
        created["id"],
        m.MaintenanceWindowIn(name="w1 renamed", starts_at="2026-10-01T23:00:00+07:00",
                              ends_at="2026-10-02T03:00:00+07:00"), None, ADMIN)
    assert upd["name"] == "w1 renamed"
    res = await routes.maintenance_windows_delete(created["id"], ADMIN)
    assert res["deleted"] == 1


# ---------------------------------------------------------------------------
# Alert event history
# ---------------------------------------------------------------------------
class _AlertColl(_Coll):
    """find() honours the query so open_only filtering can be proven."""
    def find(self, query=None, *_a, **_kw):
        rows = self.docs
        if query and "resolved_at" in query:
            rows = [d for d in rows if d.get("resolved_at") is None]
        return _Cursor(rows)


@pytest.mark.anyio
async def test_graph_alerts_list_open_only_filters(monkeypatch):
    value = _Db()
    value.monitoring_graph_alerts = _AlertColl([
        {"_id": ObjectId(), "rule_name": "open one", "fired_at": "2026-10-01T00:00:00+00:00",
         "resolved_at": None, "severity": "critical", "suppressed": False, "dispatched": True},
        {"_id": ObjectId(), "rule_name": "resolved one", "fired_at": "2026-09-30T00:00:00+00:00",
         "resolved_at": "2026-09-30T01:00:00+00:00", "suppressed": False, "dispatched": True},
        {"_id": ObjectId(), "rule_name": "suppressed open", "fired_at": "2026-10-01T02:00:00+00:00",
         "resolved_at": None, "suppressed": True, "dispatched": False},
    ])
    monkeypatch.setattr(routes, "_get_db", AsyncMock(return_value=value))

    all_rows = await routes.graph_alerts_list(False, 50, ADMIN)
    assert len(all_rows) == 3

    open_rows = await routes.graph_alerts_list(True, 50, ADMIN)
    assert {r["rule_name"] for r in open_rows} == {"open one", "suppressed open"}
    # open flag is derived from resolved_at, suppressed is reported honestly
    suppressed = [r for r in open_rows if r["rule_name"] == "suppressed open"][0]
    assert suppressed["open"] is True and suppressed["suppressed"] is True
    assert suppressed["dispatched"] is False


@pytest.mark.anyio
async def test_graph_alerts_list_caps_limit(monkeypatch):
    value = _Db()
    value.monitoring_graph_alerts = _AlertColl(
        [{"_id": ObjectId(), "rule_name": f"r{i}", "resolved_at": None} for i in range(10)])
    monkeypatch.setattr(routes, "_get_db", AsyncMock(return_value=value))
    rows = await routes.graph_alerts_list(False, 0, ADMIN)  # 0 must not mean "no rows"
    assert len(rows) == 10


# ---------------------------------------------------------------------------
# Row-level scoping (behavioural — fails if the visible_roles filter is removed)
# ---------------------------------------------------------------------------
SUPPORT = {"role": "support", "_id": "sup1", "id": "sup1"}


def _graph(gid, *roles):
    return {"_id": ObjectId(gid), "name": f"g-{gid}", "visible_roles": list(roles)}


async def _scoped_db(monkeypatch, graphs):
    value = _Db()
    value.monitoring_graphs = _GraphsColl(graphs)
    monkeypatch.setattr(routes, "_get_db", AsyncMock(return_value=value))
    monkeypatch.setattr(routes, "log_audit", AsyncMock())
    return value


@pytest.mark.anyio
async def test_alert_rules_list_hides_rules_for_invisible_graphs(monkeypatch):
    visible = ObjectId()
    hidden = ObjectId()
    value = await _scoped_db(monkeypatch, [
        _graph(visible, "support"),
        _graph(hidden, "admin"),
    ])
    value.graph_alert_rules.docs = [
        {"_id": ObjectId(), "name": "visible rule", "graph_id": str(visible)},
        {"_id": ObjectId(), "name": "hidden rule", "graph_id": str(hidden)},
        {"_id": ObjectId(), "name": "global rule", "graph_id": ""},
    ]

    support_rows = await routes.alert_rules_list(SUPPORT)
    assert {r["name"] for r in support_rows} == {"visible rule", "global rule"}

    # admin still sees everything (no scoping regression)
    admin_rows = await routes.alert_rules_list(ADMIN)
    assert len(admin_rows) == 3


@pytest.mark.anyio
async def test_maintenance_windows_list_scopes_and_redacts_graph_ids(monkeypatch):
    visible = ObjectId()
    hidden = ObjectId()
    value = await _scoped_db(monkeypatch, [
        _graph(visible, "support"),
        _graph(hidden, "admin"),
    ])
    value.monitoring_maintenance_windows.docs = [
        {"_id": ObjectId(), "name": "visible only", "graph_ids": [str(visible)]},
        {"_id": ObjectId(), "name": "hidden only", "graph_ids": [str(hidden)]},
        {"_id": ObjectId(), "name": "global", "graph_ids": []},
        {"_id": ObjectId(), "name": "mixed", "graph_ids": [str(visible), str(hidden)]},
    ]

    rows = await routes.maintenance_windows_list(SUPPORT)
    assert {r["name"] for r in rows} == {"visible only", "global", "mixed"}
    # a mixed window must not reveal the hidden graph id
    mixed = [r for r in rows if r["name"] == "mixed"][0]
    assert mixed["graph_ids"] == [str(visible)]


@pytest.mark.anyio
async def test_graph_alerts_list_hides_alerts_for_invisible_graphs(monkeypatch):
    visible = ObjectId()
    hidden = ObjectId()
    value = await _scoped_db(monkeypatch, [
        _graph(visible, "support"),
        _graph(hidden, "admin"),
    ])
    value.monitoring_graph_alerts.docs = [
        {"_id": ObjectId(), "rule_name": "mine", "graph_id": str(visible),
         "resolved_at": None},
        {"_id": ObjectId(), "rule_name": "not mine", "graph_id": str(hidden),
         "resolved_at": None},
    ]

    rows = await routes.graph_alerts_list(True, 50, SUPPORT)
    assert {r["rule_name"] for r in rows} == {"mine"}


@pytest.mark.anyio
async def test_visible_graph_ids_not_capped_by_page_size(monkeypatch):
    """Authorization must not silently weaken past an arbitrary page cap."""
    from bson import ObjectId as _Oid
    graphs = [{"_id": _Oid(), "visible_roles": ["support"]} for _ in range(1200)]
    value = _Db()
    value.monitoring_graphs = _GraphsColl(graphs)
    monkeypatch.setattr(routes, "_get_db", AsyncMock(return_value=value))

    ids = await routes._visible_graph_ids(value, SUPPORT)
    assert len(ids) == 1200, "distinct() must return every visible graph, not a capped page"
    assert await routes._visible_graph_ids(value, ADMIN) is None


# ---------------------------------------------------------------------------
# RBAC contract (AST — no FastAPI dependency execution needed)
# ---------------------------------------------------------------------------
def _route_dep_names(func: ast.AsyncFunctionDef) -> list[str]:
    """Roles from `Depends(require_roles("admin","support"))` defaults.

    The dependency is wrapped in Depends(...); reading the default directly
    yields an empty list and the assertion silently passes for the wrong
    reason. Unwrap it (this exact blind spot bit us before).
    """
    names = []
    for arg in list(func.args.defaults) + list(func.args.kw_defaults):
        call = arg
        if isinstance(call, ast.Call) and getattr(call.func, "id", "") == "Depends":
            call = call.args[0] if call.args else None
        if isinstance(call, ast.Call) and getattr(call.func, "id", "") == "require_roles":
            names += [getattr(a, "value", "") for a in call.args]
    return names


def test_alert_and_window_routes_require_admin_or_support():
    tree = ast.parse(GRAPHS_FILE.read_text())
    wanted = {
        "alert_rules_list", "alert_rules_create", "alert_rules_update",
        "alert_rules_delete", "maintenance_windows_list", "maintenance_windows_create",
        "maintenance_windows_update", "maintenance_windows_delete", "graph_alerts_list",
    }
    seen = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name in wanted:
            roles = _route_dep_names(node)
            assert set(roles) >= {"admin", "support"}, \
                f"{node.name} must require_roles('admin','support'), got {roles}"
            seen[node.name] = roles
    assert set(seen) == wanted, f"routes not found: {wanted - set(seen)}"


# --------------------------------------------------------------------------- #
# Row-level scoping: support must not read alerts/rules/windows on graphs
# outside their visible_roles (Dudung FAIL addendum, msg 1555164855567126580).
#
# These tests are fail-on-mutation: the fake monitoring_graphs records the
# query the route sends and filters by visible_roles, so if the scoping code
# is removed the fake suddenly returns admin-only rows and the assertions
# below break.
# --------------------------------------------------------------------------- #
def _support_staff():
    return {"role": "support", "_id": "support1", "id": "support1"}


def _seed_scoped_db():
    value = _Db()
    own_id = ObjectId()
    admin_id = ObjectId()
    value.monitoring_graphs.rows = [
        {"_id": own_id, "name": "Mine", "display_name": "Mine",
         "visible_roles": ["admin", "support"]},
        {"_id": admin_id, "name": "SecretAdmin",
         "display_name": "SecretAdmin",
         "visible_roles": ["admin"]},
    ]
    # alert fired on the admin-only graph — support must never see it
    value.monitoring_graph_alerts.docs = [
        {"_id": ObjectId(), "rule_name": "leak", "graph_id": str(admin_id),
         "graph_name": "SecretAdmin", "resolved_at": None,
         "fired_at": "2026-10-01T00:00:00+00:00", "suppressed": False,
         "dispatched": True},
    ]
    # rule scoped to the admin-only graph — support must never see it
    value.graph_alert_rules.docs = [
        {"_id": ObjectId(), "name": "secret rule", "graph_id": str(admin_id),
         "enabled": True, "metric": "bps", "comparator": ">", "threshold": 1,
         "consecutive": 2, "severity": "critical"},
        {"_id": ObjectId(), "name": "global rule", "graph_id": "",
         "enabled": True, "metric": "state", "consecutive": 2, "severity": "warning"},
    ]
    # maintenance window on the admin-only graph — support must never see it
    value.monitoring_maintenance_windows.docs = [
        {"_id": ObjectId(), "name": "secret window", "graph_ids": [str(admin_id)],
         "starts_at": "2026-10-01T22:00:00+07:00",
         "ends_at": "2026-10-02T02:00:00+07:00", "enabled": True},
        {"_id": ObjectId(), "name": "global window", "graph_ids": [],
         "starts_at": "2026-10-01T22:00:00+07:00",
         "ends_at": "2026-10-02T02:00:00+07:00", "enabled": True},
    ]
    return value


@pytest.mark.anyio
async def test_alert_rules_list_scoped_to_support(monkeypatch):
    value = _seed_scoped_db()
    monkeypatch.setattr(routes, "_get_db", AsyncMock(return_value=value))

    rows = await routes.alert_rules_list(_support_staff())

    names = {r["name"] for r in rows}
    # global rule (empty graph_id) is visible; admin-scoped rule is not
    assert "global rule" in names, names
    assert "secret rule" not in names, names
    # the route must have pushed the RBAC filter down to the query layer
    assert value.monitoring_graphs.queries, "alert_rules_list never queried graphs"
    assert value.monitoring_graphs.queries[0].get("visible_roles") == "support"


@pytest.mark.anyio
async def test_maintenance_windows_list_scoped_to_support(monkeypatch):
    value = _seed_scoped_db()
    monkeypatch.setattr(routes, "_get_db", AsyncMock(return_value=value))

    rows = await routes.maintenance_windows_list(_support_staff())

    names = {r["name"] for r in rows}
    assert "global window" in names, names
    assert "secret window" not in names, names
    assert value.monitoring_graphs.queries[0].get("visible_roles") == "support"


@pytest.mark.anyio
async def test_graph_alerts_list_scoped_to_support(monkeypatch):
    value = _seed_scoped_db()
    monkeypatch.setattr(routes, "_get_db", AsyncMock(return_value=value))

    rows = await routes.graph_alerts_list(False, 50, _support_staff())

    # the admin-only alert must not surface for support
    assert rows == [], [r["graph_name"] for r in rows]
    assert value.monitoring_graphs.queries[0].get("visible_roles") == "support"


@pytest.mark.anyio
async def test_health_alerts_block_scoped_to_support(monkeypatch):
    value = _seed_scoped_db()
    monkeypatch.setattr(routes, "_get_db", AsyncMock(return_value=value))

    out = await routes.monitoring_health(_support_staff())

    alerts = out["alerts"]
    # only the global rule counts; the admin-scoped rule must not
    assert alerts["rules"] == 1, alerts
    # no open alerts on graphs support cannot see
    assert alerts["open"] == 0, alerts
    assert alerts["suppressed_open"] == 0, alerts
    # only the global maintenance window counts
    assert alerts["maintenance_windows"] == 1, alerts
    assert value.monitoring_graphs.queries[0].get("visible_roles") == "support"


@pytest.mark.anyio
async def test_admin_sees_everything(monkeypatch):
    """Admins are not scoped: the same seed must return all rows."""
    value = _seed_scoped_db()
    monkeypatch.setattr(routes, "_get_db", AsyncMock(return_value=value))

    rules = await routes.alert_rules_list(ADMIN)
    windows = await routes.maintenance_windows_list(ADMIN)
    alerts = await routes.graph_alerts_list(False, 50, ADMIN)

    assert {r["name"] for r in rules} == {"secret rule", "global rule"}
    assert {w["name"] for w in windows} == {"secret window", "global window"}
    assert len(alerts) == 1
    assert alerts[0]["graph_name"] == "SecretAdmin"
    # Admin is unrestricted and does not need an auxiliary graph-id lookup.
    assert value.monitoring_graphs.queries == []


# --------------------------------------------------------------------------- #
# Write-side RBAC: support must 404 when creating/updating/deleting objects
# that target an admin-only graph (even if they know the object ID).
# --------------------------------------------------------------------------- #
@pytest.mark.anyio
async def test_alert_rule_create_404_on_hidden_graph(monkeypatch):
    value = _seed_scoped_db()
    monkeypatch.setattr(routes, "_get_db", AsyncMock(return_value=value))
    admin_only_id = str(value.monitoring_graphs.rows[1]["_id"])  # SecretAdmin

    payload = m.GraphAlertRuleIn(name="attempt", metric="bps",
                                 comparator=">", threshold=1,
                                 graph_id=admin_only_id, consecutive=2,
                                 severity="critical")
    try:
        await routes.alert_rules_create(payload, None, _support_staff())
        raise AssertionError("expected 404")
    except HTTPException as exc:
        assert exc.status_code == 404


@pytest.mark.anyio
async def test_alert_rule_update_404_on_hidden_graph(monkeypatch):
    # admin creates a rule on SecretAdmin; support tries to update it
    value = _seed_scoped_db()
    admin_rule_id = str(value.graph_alert_rules.docs[0]["_id"])  # secret rule
    admin_only_id = str(value.monitoring_graphs.rows[1]["_id"])
    monkeypatch.setattr(routes, "_get_db", AsyncMock(return_value=value))

    payload = m.GraphAlertRuleIn(name="updated", metric="state",
                                 graph_id=admin_only_id, consecutive=2,
                                 severity="warning")
    try:
        await routes.alert_rules_update(admin_rule_id, payload, None, _support_staff())
        raise AssertionError("expected 404")
    except HTTPException as exc:
        assert exc.status_code == 404


@pytest.mark.anyio
async def test_alert_rule_delete_404_on_hidden_graph(monkeypatch):
    value = _seed_scoped_db()
    admin_rule_id = str(value.graph_alert_rules.docs[0]["_id"])
    monkeypatch.setattr(routes, "_get_db", AsyncMock(return_value=value))

    try:
        await routes.alert_rules_delete(admin_rule_id, _support_staff())
        raise AssertionError("expected 404")
    except HTTPException as exc:
        assert exc.status_code == 404


@pytest.mark.anyio
async def test_maintenance_window_create_404_on_hidden_graph(monkeypatch):
    value = _seed_scoped_db()
    admin_only_id = str(value.monitoring_graphs.rows[1]["_id"])
    monkeypatch.setattr(routes, "_get_db", AsyncMock(return_value=value))

    payload = m.MaintenanceWindowIn(name="attempt",
                                    starts_at="2026-10-01T22:00:00+07:00",
                                    ends_at="2026-10-02T02:00:00+07:00",
                                    graph_ids=[admin_only_id], enabled=True)
    try:
        await routes.maintenance_windows_create(payload, None, _support_staff())
        raise AssertionError("expected 404")
    except HTTPException as exc:
        assert exc.status_code == 404


@pytest.mark.anyio
async def test_maintenance_window_update_404_on_hidden_graph(monkeypatch):
    value = _seed_scoped_db()
    admin_window_id = str(value.monitoring_maintenance_windows.docs[0]["_id"])
    admin_only_id = str(value.monitoring_graphs.rows[1]["_id"])
    monkeypatch.setattr(routes, "_get_db", AsyncMock(return_value=value))

    payload = m.MaintenanceWindowIn(name="updated",
                                    starts_at="2026-10-01T22:00:00+07:00",
                                    ends_at="2026-10-02T02:00:00+07:00",
                                    graph_ids=[admin_only_id], enabled=True)
    try:
        await routes.maintenance_windows_update(admin_window_id, payload, None, _support_staff())
        raise AssertionError("expected 404")
    except HTTPException as exc:
        assert exc.status_code == 404


@pytest.mark.anyio
async def test_maintenance_window_delete_404_on_hidden_graph(monkeypatch):
    value = _seed_scoped_db()
    admin_window_id = str(value.monitoring_maintenance_windows.docs[0]["_id"])
    monkeypatch.setattr(routes, "_get_db", AsyncMock(return_value=value))

    try:
        await routes.maintenance_windows_delete(admin_window_id, _support_staff())
        raise AssertionError("expected 404")
    except HTTPException as exc:
        assert exc.status_code == 404


# --------------------------------------------------------------------------- #
# Update-move attack: a support staff member who knows an object ID must NOT be
# able to move an admin-only rule/window onto a visible graph via PUT.
# --------------------------------------------------------------------------- #
@pytest.mark.anyio
async def test_alert_rule_update_cannot_move_hidden_rule_to_visible_graph(monkeypatch):
    value = _seed_scoped_db()
    admin_rule_id = str(value.graph_alert_rules.docs[0]["_id"])  # on SecretAdmin
    visible_id = str(value.monitoring_graphs.rows[0]["_id"])     # support-visible
    monkeypatch.setattr(routes, "_get_db", AsyncMock(return_value=value))

    payload = m.GraphAlertRuleIn(name="moved", metric="state",
                                 graph_id=visible_id, consecutive=2,
                                 severity="warning")
    try:
        await routes.alert_rules_update(admin_rule_id, payload, None, _support_staff())
        raise AssertionError("expected 404")
    except HTTPException as exc:
        assert exc.status_code == 404
    # rule must still live on the hidden graph (unchanged)
    assert value.graph_alert_rules.docs[0]["name"] == "secret rule"


@pytest.mark.anyio
async def test_alert_rule_update_cannot_retarget_visible_rule_to_hidden_graph(monkeypatch):
    value = _seed_scoped_db()
    # create a rule on the support-visible graph as admin
    async def _get_db():
        return value
    monkeypatch.setattr(routes, "_get_db", _get_db)
    visible_id = str(value.monitoring_graphs.rows[0]["_id"])
    created = await routes.alert_rules_create(
        m.GraphAlertRuleIn(name="mine", metric="state", graph_id=visible_id,
                           consecutive=2, severity="info"), None, ADMIN)
    hidden_id = str(value.monitoring_graphs.rows[1]["_id"])  # SecretAdmin

    payload = m.GraphAlertRuleIn(name="moved", metric="state",
                                 graph_id=hidden_id, consecutive=2,
                                 severity="warning")
    try:
        await routes.alert_rules_update(created["id"], payload, None, _support_staff())
        raise AssertionError("expected 404")
    except HTTPException as exc:
        assert exc.status_code == 404
    assert value.graph_alert_rules.docs[-1]["graph_id"] == visible_id


@pytest.mark.anyio
async def test_maintenance_window_update_cannot_move_hidden_to_visible(monkeypatch):
    value = _seed_scoped_db()
    admin_window_id = str(value.monitoring_maintenance_windows.docs[0]["_id"])
    visible_id = str(value.monitoring_graphs.rows[0]["_id"])
    monkeypatch.setattr(routes, "_get_db", AsyncMock(return_value=value))

    payload = m.MaintenanceWindowIn(name="moved",
                                    starts_at="2026-10-01T22:00:00+07:00",
                                    ends_at="2026-10-02T02:00:00+07:00",
                                    graph_ids=[visible_id], enabled=True)
    try:
        await routes.maintenance_windows_update(admin_window_id, payload, None, _support_staff())
        raise AssertionError("expected 404")
    except HTTPException as exc:
        assert exc.status_code == 404
    assert value.monitoring_maintenance_windows.docs[0]["name"] == "secret window"
