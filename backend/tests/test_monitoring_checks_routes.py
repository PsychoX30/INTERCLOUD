"""Route-level regressions for the monitoring check registry."""
from unittest.mock import AsyncMock

import pytest
from bson import ObjectId
from fastapi import HTTPException

from portal.routes import monitoring as routes


class _Cursor:
    def __init__(self, rows):
        self.rows = rows

    def sort(self, *_args):
        return self

    async def to_list(self, _limit):
        return self.rows


class _Checks:
    def __init__(self):
        self.rows = []
        self.inserted = []
        self.updated = []
        self.deleted = []

    def find(self, _query):
        return _Cursor(self.rows)

    async def insert_one(self, doc):
        self.inserted.append(doc)
        return type("Result", (), {"inserted_id": ObjectId()})()

    async def find_one(self, query):
        wanted = query.get("_id")
        return next((r for r in self.rows if r.get("_id") == wanted), None)

    async def update_one(self, query, update):
        self.updated.append((query, update))
        wanted = query.get("_id")
        row = next((r for r in self.rows if r.get("_id") == wanted), None)
        if row is not None:
            row.update(update.get("$set", {}))
        return type("Result", (), {"matched_count": int(row is not None)})()

    async def delete_one(self, query):
        self.deleted.append(query)
        return type("Result", (), {"deleted_count": 1})()


class _Db:
    def __init__(self):
        self.monitoring_checks = _Checks()


@pytest.fixture
def db(monkeypatch):
    value = _Db()
    monkeypatch.setattr(routes, "_get_db", AsyncMock(return_value=value))
    return value


@pytest.mark.anyio
async def test_create_ping_check_persists_validated_public_target(db):
    out = await routes.monitoring_check_create(
        {"name": "DNS", "target": "8.8.8.8", "interval_seconds": 60},
        {"role": "admin", "email": "admin@example.test"},
    )

    assert out["name"] == "DNS"
    assert out["target"] == "8.8.8.8"
    assert out["enabled"] is True
    assert out["interval_seconds"] == 60
    assert db.monitoring_checks.inserted[0]["type"] == "ping"


@pytest.mark.anyio
async def test_create_ping_check_accepts_10s_interval(db):
    out = await routes.monitoring_check_create(
        {"name": "Fast", "target": "8.8.8.8", "interval_seconds": 10},
        {"role": "admin", "email": "admin@example.test"},
    )
    assert out["interval_seconds"] == 10


@pytest.mark.anyio
async def test_create_ping_check_rejects_sub_10s_interval(db):
    with pytest.raises(HTTPException) as exc:
        await routes.monitoring_check_create(
            {"name": "TooFast", "target": "8.8.8.8", "interval_seconds": 9},
            {"role": "admin", "email": "admin@example.test"},
        )
    assert exc.value.status_code == 400
    assert db.monitoring_checks.inserted == []


@pytest.mark.anyio
async def test_create_ping_check_rejects_private_target(db):
    with pytest.raises(HTTPException) as exc:
        await routes.monitoring_check_create(
            {"name": "metadata", "target": "127.0.0.1"},
            {"role": "admin"},
        )
    assert exc.value.status_code == 400
    assert db.monitoring_checks.inserted == []


@pytest.mark.anyio
async def test_update_revalidates_new_target(db):
    check_id = str(ObjectId())
    db.monitoring_checks.rows = [{"_id": ObjectId(check_id), "name": "DNS", "target": "8.8.8.8"}]

    with pytest.raises(HTTPException) as exc:
        await routes.monitoring_check_update(
            check_id, {"target": "10.0.0.1"}, {"role": "admin"}
        )
    assert exc.value.status_code == 400
    assert db.monitoring_checks.updated == []


@pytest.mark.anyio
async def test_create_rejects_non_boolean_enabled_value(db):
    with pytest.raises(HTTPException) as exc:
        await routes.monitoring_check_create(
            {"name": "DNS", "target": "8.8.8.8", "enabled": "false"},
            {"role": "admin"},
        )
    assert exc.value.status_code == 400
    assert db.monitoring_checks.inserted == []


@pytest.mark.anyio
async def test_create_rejects_hostname_resolving_to_internal_ip(db, monkeypatch):
    """Registry must fail fast on unsafe hostnames, not only at probe time."""
    monkeypatch.setattr(routes, "resolve_ip", lambda _host: "10.10.10.10")

    with pytest.raises(HTTPException) as exc:
        await routes.monitoring_check_create(
            {"name": "evil", "target": "internal.example"},
            {"role": "admin"},
        )
    assert exc.value.status_code == 400
    assert db.monitoring_checks.inserted == []


@pytest.mark.anyio
async def test_update_rejects_hostname_resolving_to_internal_ip(db, monkeypatch):
    monkeypatch.setattr(routes, "resolve_ip", lambda _host: "127.0.0.1")
    check_id = str(ObjectId())
    db.monitoring_checks.rows = [{"_id": ObjectId(check_id), "name": "DNS", "target": "8.8.8.8"}]

    with pytest.raises(HTTPException) as exc:
        await routes.monitoring_check_update(
            check_id, {"target": "internal.example"}, {"role": "admin"}
        )
    assert exc.value.status_code == 400
    assert db.monitoring_checks.updated == []


@pytest.mark.anyio
async def test_create_dns_failure_returns_400_not_500(db, monkeypatch):
    def _dns_failure(_host):
        raise ValueError("DNS resolution failed for nope.invalid")

    monkeypatch.setattr(routes, "resolve_ip", _dns_failure)
    with pytest.raises(HTTPException) as exc:
        await routes.monitoring_check_create(
            {"name": "bad", "target": "nope.invalid"},
            {"role": "admin"},
        )
    assert exc.value.status_code == 400
    assert db.monitoring_checks.inserted == []


@pytest.mark.anyio
async def test_update_rejects_non_boolean_enabled_value(db):
    check_id = str(ObjectId())
    db.monitoring_checks.rows = [{"_id": ObjectId(check_id), "name": "DNS", "target": "8.8.8.8"}]

    with pytest.raises(HTTPException) as exc:
        await routes.monitoring_check_update(
            check_id, {"enabled": "false"}, {"role": "admin"}
        )
    assert exc.value.status_code == 400
    assert db.monitoring_checks.updated == []


@pytest.mark.anyio
async def test_update_unknown_check_returns_404(db):
    db.monitoring_checks.update_one = AsyncMock(return_value=type("Result", (), {"matched_count": 0})())

    with pytest.raises(HTTPException) as exc:
        await routes.monitoring_check_update(
            str(ObjectId()), {"name": "nope"}, {"role": "admin"}
        )
    assert exc.value.status_code == 404


@pytest.mark.anyio
async def test_update_invalid_check_id_returns_400_before_database_write(db):
    with pytest.raises(HTTPException) as exc:
        await routes.monitoring_check_update(
            "not-an-object-id", {"name": "nope"}, {"role": "admin"}
        )
    assert exc.value.status_code == 400
    assert db.monitoring_checks.updated == []


@pytest.mark.anyio
async def test_update_serializes_response_json(db):
    check_id = str(ObjectId())
    db.monitoring_checks.rows = [{
        "_id": ObjectId(check_id), "name": "DNS", "target": "8.8.8.8",
        "type": "ping", "enabled": True, "interval_seconds": 60,
        "created_at": None, "updated_at": None,
    }]

    out = await routes.monitoring_check_update(
        check_id, {"interval_seconds": 120}, {"role": "admin"}
    )
    assert out["id"] == check_id
    assert out["name"] == "DNS"
    assert out["target"] == "8.8.8.8"
    assert out["interval_seconds"] == 120
    assert out["created_at"] is None


@pytest.mark.anyio
async def test_create_serializes_response_json(db):
    out = await routes.monitoring_check_create(
        {"name": "DNS", "target": "8.8.8.8", "interval_seconds": 60},
        {"role": "admin"},
    )
    assert isinstance(out["id"], str)
    assert out["target"] == "8.8.8.8"
    assert out["type"] == "ping"
    assert out["enabled"] is True


@pytest.mark.anyio
async def test_delete_unknown_check_returns_404(db):
    db.monitoring_checks.delete_one = AsyncMock(return_value=type("Result", (), {"deleted_count": 0})())
    with pytest.raises(HTTPException) as exc:
        await routes.monitoring_check_delete(str(ObjectId()), {"role": "admin"})
    assert exc.value.status_code == 404


@pytest.mark.anyio
async def test_invalid_check_id_returns_400_before_database_write(db):
    with pytest.raises(HTTPException) as exc:
        await routes.monitoring_check_delete("not-an-object-id", {"role": "admin"})
    assert exc.value.status_code == 400
    assert db.monitoring_checks.deleted == []


@pytest.mark.anyio
async def test_manual_run_probes_persisted_target_with_unique_owner(db, monkeypatch):
    check_id = str(ObjectId())
    db.monitoring_checks.rows = [{
        "_id": ObjectId(check_id), "name": "DNS", "target": "8.8.8.8",
        "type": "ping", "enabled": True, "interval_seconds": 60,
    }]
    calls = []

    async def fake_probe(db_arg, *, target, check_id, owner, timeout=2.0):
        calls.append((db_arg, target, check_id, owner, timeout))
        return {"status": "up", "up": True, "event": None, "rtt_ms": 1.2, "loss": 0.0}

    monkeypatch.setattr(routes, "probe_target", fake_probe)
    out = await routes.monitoring_check_run(check_id, {"role": "admin", "id": "a1"})

    assert out["status"] == "up"
    assert calls[0][0] is db
    assert calls[0][1:3] == ("8.8.8.8", check_id)
    assert calls[0][3].startswith("manual:a1:")


@pytest.mark.anyio
async def test_manual_run_unknown_check_returns_404_without_probe(db, monkeypatch):
    probe = AsyncMock()
    monkeypatch.setattr(routes, "probe_target", probe)

    with pytest.raises(HTTPException) as exc:
        await routes.monitoring_check_run(str(ObjectId()), {"role": "admin"})

    assert exc.value.status_code == 404
    probe.assert_not_awaited()
