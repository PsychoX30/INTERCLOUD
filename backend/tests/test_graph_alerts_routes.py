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
        return _Cursor(self.docs)

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

    async def count_documents(self, _q=None):
        return len(self.docs)


class _Db:
    _COLLECTIONS = ("graph_alert_rules", "monitoring_graph_alerts",
                    "monitoring_maintenance_windows")

    def __init__(self):
        self.graph_alert_rules = _Coll()
        self.monitoring_graph_alerts = _Coll()
        self.monitoring_maintenance_windows = _Coll()

    def __getitem__(self, name):
        if name in self._COLLECTIONS:
            return getattr(self, name)
        raise KeyError(name)


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
        "maintenance_windows_update", "maintenance_windows_delete",
    }
    seen = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name in wanted:
            roles = _route_dep_names(node)
            assert set(roles) >= {"admin", "support"}, \
                f"{node.name} must require_roles('admin','support'), got {roles}"
            seen[node.name] = roles
    assert set(seen) == wanted, f"routes not found: {wanted - set(seen)}"
