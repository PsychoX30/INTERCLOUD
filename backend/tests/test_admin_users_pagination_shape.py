"""Contract tests for optional /admin/users pagination."""
import pytest
from portal.routes import users


class _UsersCursor:
    def __init__(self, docs):
        self._docs = docs

    def sort(self, *_args):
        return self

    async def to_list(self, _limit):
        return self._docs


class _Db:
    def __init__(self):
        docs = [
            {"_id": object(), "name": "Client A", "email": "a@a.com", "role": "client"},
            {"_id": object(), "name": "Client B", "email": "b@b.com", "role": "client"},
        ]
        self.users = type("_", (), {"find": lambda _self, _query: _UsersCursor(docs)})()


@pytest.fixture
def fake_db(monkeypatch):
    async def get_db():
        return _Db()

    monkeypatch.setattr(users, "_get_db", get_db)


@pytest.mark.anyio
@pytest.mark.parametrize("role", ["sales", "admin"])
async def test_admin_users_without_page_returns_legacy_flat_list(fake_db, role):
    staff = {
        "role": role,
        "assigned_client_ids": [
            "64b000000000000000000001",
            "64b000000000000000000002",
        ],
    }

    result = await users.admin_list_users(staff)

    assert isinstance(result, list)
    assert len(result) == 2
    assert all(item["role"] == "client" for item in result)


@pytest.mark.anyio
@pytest.mark.parametrize("role", ["sales", "admin"])
async def test_admin_users_with_page_returns_paginated_wrapper(fake_db, role):
    staff = {
        "role": role,
        "assigned_client_ids": [
            "64b000000000000000000001",
            "64b000000000000000000002",
        ],
    }

    result = await users.admin_list_users(staff, page=1, limit=1)

    assert result["total"] == 2
    assert result["page"] == 1
    assert result["limit"] == 1
    assert len(result["items"]) == 1
