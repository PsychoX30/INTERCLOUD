"""TDD: Media comments CRUD."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock
from bson import ObjectId
from portal.routes import business as business_routes


# Mock infrastructure
def _matches(doc, query):
    if not query:
        return True
    return all(doc.get(k) == v for k, v in query.items())


class _Cursor:
    def __init__(self, rows):
        self.rows = list(rows)
        self._skip = 0
        self._limit = None
    def sort(self, key, direction=-1):
        self.rows = sorted(self.rows, key=lambda r: r.get(key, ""), reverse=direction == -1)
        return self
    def skip(self, n):
        self._skip = n; return self
    def limit(self, n):
        self._limit = n; return self
    async def to_list(self, _limit):
        s = self._skip or 0
        return self.rows[s:s + (self._limit if self._limit is not None else len(self.rows))]


class _Collection:
    def __init__(self, rows=None):
        self.rows = list(rows or [])
    def find(self, query=None, projection=None):
        return _Cursor([r for r in self.rows if _matches(r, query or {})])
    async def count_documents(self, query=None):
        return len([r for r in self.rows if _matches(r, query or {})])
    async def find_one(self, query=None):
        for r in self.rows:
            if _matches(r, query or {}):
                return r
        return None
    async def insert_one(self, doc):
        doc.setdefault("_id", ObjectId())
        self.rows.append(doc)
        return type("_R", (), {"inserted_id": doc["_id"]})()
    async def update_one(self, query, update):
        for r in self.rows:
            if _matches(r, query or {}):
                r.update((update or {}).get("$set", {}))
                return type("_R", (), {"modified_count": 1, "matched_count": 1})()
        return type("_R", (), {"modified_count": 0, "matched_count": 0})()
    async def delete_one(self, query):
        for i, r in enumerate(self.rows):
            if _matches(r, query or {}):
                self.rows.pop(i)
                return type("_R", (), {"deleted_count": 1})()
        return type("_R", (), {"deleted_count": 0})()


@pytest.mark.anyio
async def test_media_comments_crud(monkeypatch):
    """POST/GET/DELETE /admin/media/{mid}/comments should work for all staff."""
    mid = "66a0b1c2d3e4f5061728394a"

    for role in ["admin", "sales", "creative", "support", "ticket_only"]:
        # Fresh collection per role
        comments = _Collection()

        class FakeDb:
            media_assets = _Collection([{"_id": ObjectId(mid), "stored_name": "test.png"}])
            media_comments = comments

        monkeypatch.setattr(business_routes, "_get_db", AsyncMock(return_value=FakeDb()))
        monkeypatch.setattr(business_routes, "_now", lambda: "2026-08-21T10:00:00Z")

        staff = {"role": role, "email": f"{role}@test.id", "id": "userid", "name": f"{role} User"}

        # POST - create comment
        result = await business_routes.media_comment_create(
            mid=mid, payload={"body": "Bagus desainnya!"}, staff=staff
        )
        assert result["body"] == "Bagus desainnya!"
        assert result["author_id"] == staff["id"]
        assert result["author_name"] == staff["name"]
        assert result["author_role"] == role
        comment_id = result["id"]

        # GET - list comments
        result = await business_routes.media_comment_list(mid=mid, staff=staff)
        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["body"] == "Bagus desainnya!"

        # DELETE - author can delete own
        result = await business_routes.media_comment_delete(
            mid=mid, cid=comment_id, staff=staff
        )
        assert result["deleted"] == 1

        # Verify deleted
        result = await business_routes.media_comment_list(mid=mid, staff=staff)
        assert len(result) == 0


@pytest.mark.anyio
async def test_media_comment_delete_admin_can_delete_any(monkeypatch):
    """Admin can delete any user's comment."""
    mid = "66a0b1c2d3e4f5061728394a"
    comments = _Collection()

    class FakeDb:
        media_assets = _Collection([{"_id": ObjectId(mid), "stored_name": "test.png"}])
        media_comments = comments

    monkeypatch.setattr(business_routes, "_get_db", AsyncMock(return_value=FakeDb()))
    monkeypatch.setattr(business_routes, "_now", lambda: "2026-08-21T10:00:00Z")

    # Creative posts comment
    creative = {"role": "creative", "email": "creative@test.id", "id": "creative1", "name": "Creative User"}
    result = await business_routes.media_comment_create(mid=mid, payload={"body": "Comment"}, staff=creative)
    cid = result["id"]

    # Admin deletes it
    admin = {"role": "admin", "email": "admin@test.id", "id": "admin1", "name": "Admin User"}
    result = await business_routes.media_comment_delete(mid=mid, cid=cid, staff=admin)
    assert result["deleted"] == 1


@pytest.mark.anyio
async def test_media_comment_delete_non_author_non_admin_denied(monkeypatch):
    """Non-author non-admin cannot delete."""
    mid = "66a0b1c2d3e4f5061728394a"
    comments = _Collection()

    class FakeDb:
        media_assets = _Collection([{"_id": ObjectId(mid), "stored_name": "test.png"}])
        media_comments = comments

    monkeypatch.setattr(business_routes, "_get_db", AsyncMock(return_value=FakeDb()))
    monkeypatch.setattr(business_routes, "_now", lambda: "2026-08-21T10:00:00Z")

    creative = {"role": "creative", "email": "creative@test.id", "id": "creative1", "name": "Creative User"}
    result = await business_routes.media_comment_create(mid=mid, payload={"body": "Comment"}, staff=creative)
    cid = result["id"]

    sales = {"role": "sales", "email": "sales@test.id", "id": "sales1", "name": "Sales User"}
    try:
        await business_routes.media_comment_delete(mid=mid, cid=cid, staff=sales)
        assert False, "Should have raised 403"
    except Exception as e:
        assert e.status_code == 403