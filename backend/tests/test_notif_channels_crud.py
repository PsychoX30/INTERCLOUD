"""Offline unit tests for /admin/noc/notif-channels CRUD + role gates.

Follows fastapi-mongodb-handler-testing pattern: mock _get_db, call handlers
directly, no live HTTP / real DB / credentials.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from bson import ObjectId

import portal.routes.noc as noc_mod
import portal.models as m


# ----------------------------------------------------------------------
# Fixtures
# ----------------------------------------------------------------------
ADMIN_STAFF = {"email": "admin@test.local", "roles": ["admin"]}
SUPPORT_STAFF = {"email": "support@test.local", "roles": ["support"]}
GUEST_STAFF = {"email": "guest@test.local", "roles": ["viewer"]}


def _make_collection():
    c = MagicMock()
    c.find_one = AsyncMock()
    c.insert_one = AsyncMock()
    c.delete_one = AsyncMock()
    c.update_one = AsyncMock()
    c.find = MagicMock()
    cursor = MagicMock()
    cursor.sort.return_value = cursor
    cursor.to_list = AsyncMock()
    c.find.return_value = cursor
    return c


@pytest.fixture
def db():
    d = MagicMock()
    d.notif_channels = _make_collection()
    d.ddos_notify_log = _make_collection()
    # Route db["collection"] -> attribute
    d.__getitem__.side_effect = lambda k: getattr(d, k)
    return d


def _insert_id(doc, _id=None):
    doc["_id"] = _id or ObjectId()
    r = MagicMock()
    r.inserted_id = doc["_id"]
    return r


def _now():
    return datetime.now(timezone.utc)


def _iso(dt):
    if isinstance(dt, datetime):
        return dt.isoformat()
    return ""


# ----------------------------------------------------------------------
# Helpers to call handlers directly (bypass HTTP / auth middleware)
# ----------------------------------------------------------------------
async def _list(db, admin=ADMIN_STAFF):
    with patch.object(noc_mod, "_get_db", new=AsyncMock(return_value=db)):
        with patch.object(noc_mod, "log_audit", new=AsyncMock()):
            return await noc_mod.noc_notif_channels_list(admin=admin)


async def _create(db, payload: m.NotifChannelIn, admin=ADMIN_STAFF):
    with patch.object(noc_mod, "_get_db", new=AsyncMock(return_value=db)):
        with patch.object(noc_mod, "log_audit", new=AsyncMock()):
            return await noc_mod.noc_notif_channels_create(payload=payload, request=MagicMock(), admin=admin)


async def _update(db, cid: str, payload: m.NotifChannelIn, admin=ADMIN_STAFF):
    with patch.object(noc_mod, "_get_db", new=AsyncMock(return_value=db)):
        with patch.object(noc_mod, "log_audit", new=AsyncMock()):
            return await noc_mod.noc_notif_channels_update(cid=cid, payload=payload, request=MagicMock(), admin=admin)


async def _delete(db, cid: str, admin=ADMIN_STAFF):
    with patch.object(noc_mod, "_get_db", new=AsyncMock(return_value=db)):
        with patch.object(noc_mod, "log_audit", new=AsyncMock()):
            return await noc_mod.noc_notif_channels_delete(cid=cid, admin=admin)


# ----------------------------------------------------------------------
# Tests
# ----------------------------------------------------------------------
class TestNotifChannelsList:
    @pytest.mark.asyncio
    async def test_list_admin(self, db):
        ch1 = {"_id": ObjectId(), "type": "email", "target": "a@b.c", "events": ["ddos"], "enabled": True, "created_at": _now()}
        ch2 = {"_id": ObjectId(), "type": "webhook", "target": "http://x", "events": ["graph"], "enabled": True, "created_at": _now()}
        db.notif_channels.find.return_value.to_list.return_value = [ch1, ch2]

        out = await _list(db)
        assert len(out) == 2
        assert out[0]["type"] == "email"
        assert out[1]["events"] == ["graph"]
        db.notif_channels.find.assert_called_once_with({})

    @pytest.mark.asyncio
    async def test_list_support(self, db):
        db.notif_channels.find.return_value.to_list.return_value = []
        out = await _list(db, admin=SUPPORT_STAFF)
        assert out == []

class TestNotifChannelsCreate:
    @pytest.mark.asyncio
    async def test_create_admin(self, db):
        db.notif_channels.insert_one.side_effect = lambda doc: _insert_id(doc)
        payload = m.NotifChannelIn(type="webhook", target="http://hook", events=["graph"], enabled=True)

        out = await _create(db, payload)
        assert out["type"] == "webhook"
        assert out["target"] == "http://hook"
        assert out["events"] == ["graph"]
        assert "id" in out
        db.notif_channels.insert_one.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_create_support(self, db):
        db.notif_channels.insert_one.side_effect = lambda doc: _insert_id(doc)
        payload = m.NotifChannelIn(type="email", target="s@t.local", events=["ddos"], enabled=True)

        out = await _create(db, payload, admin=SUPPORT_STAFF)
        assert out["type"] == "email"

class TestNotifChannelsUpdate:
    @pytest.mark.asyncio
    async def test_update_admin(self, db):
        oid = ObjectId()
        existing = {"_id": oid, "type": "email", "target": "old@x", "events": ["ddos"], "enabled": True, "created_at": _now()}
        updated = {**existing, "target": "new@x", "events": ["graph"]}
        db.notif_channels.find_one.return_value = updated
        db.notif_channels.update_one.return_value = MagicMock(matched_count=1)

        payload = m.NotifChannelIn(type="email", target="new@x", events=["graph"], enabled=True)
        out = await _update(db, str(oid), payload)
        assert out["target"] == "new@x"
        assert out["events"] == ["graph"]
        db.notif_channels.update_one.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_update_not_found(self, db):
        db.notif_channels.find_one.return_value = None
        db.notif_channels.update_one.return_value = MagicMock(matched_count=0)
        payload = m.NotifChannelIn(type="email", target="x@y", events=["ddos"], enabled=True)
        with pytest.raises(Exception) as exc:
            await _update(db, str(ObjectId()), payload)
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_update_support(self, db):
        oid = ObjectId()
        updated = {"_id": oid, "type": "webhook", "target": "http://y", "events": ["graph"], "enabled": True, "created_at": _now()}
        db.notif_channels.find_one.return_value = updated
        db.notif_channels.update_one.return_value = MagicMock(matched_count=1)

        payload = m.NotifChannelIn(type="webhook", target="http://y", events=["graph"], enabled=True)
        out = await _update(db, str(oid), payload, admin=SUPPORT_STAFF)
        assert out["target"] == "http://y"

class TestNotifChannelsDelete:
    @pytest.mark.asyncio
    async def test_delete_admin(self, db):
        db.notif_channels.delete_one.return_value = MagicMock(deleted_count=1)
        out = await _delete(db, str(ObjectId()))
        assert out["deleted"] == 1

    @pytest.mark.asyncio
    async def test_delete_support(self, db):
        db.notif_channels.delete_one.return_value = MagicMock(deleted_count=1)
        out = await _delete(db, str(ObjectId()), admin=SUPPORT_STAFF)
        assert out["deleted"] == 1

# ----------------------------------------------------------------------
# Role-gate contract test (ensures all 4 endpoints require admin|support)
# ----------------------------------------------------------------------
def test_all_endpoints_have_require_roles():
    import ast, inspect
    source = inspect.getsource(noc_mod)
    tree = ast.parse(source)
    endpoints = [
        "noc_notif_channels_list",
        "noc_notif_channels_create",
        "noc_notif_channels_update",
        "noc_notif_channels_delete",
    ]
    for name in endpoints:
        node = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == name)
        roles = []
        for default in list(node.args.defaults) + list(node.args.kw_defaults):
            call = default
            if isinstance(call, ast.Call) and getattr(call.func, "id", "") == "Depends":
                call = call.args[0] if call.args else None
            if isinstance(call, ast.Call) and getattr(call.func, "id", "") == "require_roles":
                roles.extend(getattr(arg, "value", "") for arg in call.args)
        assert set(roles) == {"admin", "support"}, f"{name} roles={roles}"


# ----------------------------------------------------------------------
# Serialization round-trip (model <-> handler)
# ----------------------------------------------------------------------
class TestNotifChannelModelRoundtrip:
    @pytest.mark.asyncio
    async def test_model_matches_handler_output(self, db):
        db.notif_channels.insert_one.side_effect = lambda doc: _insert_id(doc)
        payload = m.NotifChannelIn(type="telegram", target="-100123456", events=["graph", "ddos"], enabled=False)
        out = await _create(db, payload)

        assert out["type"] == "telegram"
        assert out["target"] == "-100123456"
        assert out["events"] == ["graph", "ddos"]
        assert out["enabled"] is False
        assert "id" in out
        assert "created_at" in out