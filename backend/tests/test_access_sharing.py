"""TDD: client services fix + document/media/calendar role sharing + doc folders."""

from __future__ import annotations

import types
import pytest
from unittest.mock import AsyncMock
from bson import ObjectId

from portal.routes import business as business_routes
from portal.routes import client as client_routes

TEST_OID = "66a0b1c2d3e4f5061728394a"


# ---------------------------------------------------------------------------
# Mock infrastructure (same pattern as test_business_pagination.py)
# ---------------------------------------------------------------------------
def _match_clause(doc, key, cond):
    if key == "$or":
        return any(all(_match_clause(doc, k, v) for k, v in cl.items()) for cl in cond)
    if key == "$and":
        return all(all(_match_clause(doc, k, v) for k, v in cl.items()) for cl in cond)
    if isinstance(cond, dict):
        if "$in" in cond:
            return doc.get(key) in cond["$in"]
        if "$regex" in cond:
            import re as _re
            return _re.search(cond["$regex"], str(doc.get(key) or ""), _re.IGNORECASE) is not None
        if "$exists" in cond:
            return (key in doc) == cond["$exists"]
        return doc.get(key) == cond
    if cond is None and key == "_id":
        return False
    return doc.get(key) == cond


def _matches(doc, query):
    return not query or all(_match_clause(doc, k, v) for k, v in query.items())


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


# ---------------------------------------------------------------------------
# 1 — Client services: missing keys safety
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_client_services_handles_missing_product_id(monkeypatch):
    doc = {
        "_id": ObjectId(),
        "user_id": ObjectId("a" * 24),
        "product_name": "Test VPS",
        "category": "vps",
        "name": "my-vps",
        "status": "active",
        "start_date": "",
        "next_renewal": "",
        "price_monthly": 100000,
        "auto_renew": True,
        "config": {},
    }

    class FakeDb:
        services = _Collection([doc])

    monkeypatch.setattr(client_routes, "_get_db", AsyncMock(return_value=FakeDb()))
    result = await client_routes.client_services(user={"id": "a" * 24, "role": "client"})
    assert len(result) == 1
    assert result[0]["product_id"] is None
    assert result[0]["product_name"] == "Test VPS"


# ---------------------------------------------------------------------------
# 2 — Document read access: all staff
# ---------------------------------------------------------------------------
class TestDocumentAccess:
    def test_creative_no_longer_blocked(self):
        business_routes._require_internal_document_access({"role": "creative"})

    def test_sales_no_longer_blocked(self):
        business_routes._require_internal_document_access({"role": "sales"})


# ---------------------------------------------------------------------------
# 3 — Media: write endpoints open to all staff
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_media_upload_accepts_all_staff_roles(monkeypatch):
    class FakeFile:
        content_type = "image/png"
        filename = "test.png"
        async def read(self):
            return b"\x89PNG\r\n\x1a\n"

    class FakeDb:
        media_assets = _Collection()

    monkeypatch.setattr(business_routes, "_get_db", AsyncMock(return_value=FakeDb()))
    monkeypatch.setattr(business_routes, "_now", lambda: "2026-08-21T00:00:00Z")
    class _FakePath:
        def mkdir(self, *a, **k): pass
        def __truediv__(self, other): return self
        def write_bytes(self, data): pass

    monkeypatch.setattr(business_routes, "MEDIA_DIR", _FakePath())
    monkeypatch.setattr(business_routes, "ObjectId", lambda: ObjectId())

    for role in ["admin", "sales", "support", "creative", "ticket_only", "owner", "finance"]:
        staff = {"role": role, "email": f"{role}@test.id", "id": "userid"}
        result = await business_routes.media_upload(file=FakeFile(), alt_text="", tags="", staff=staff)
        assert result["uploaded_by"] == staff["email"]


@pytest.mark.anyio
async def test_media_update_accepts_all_staff_roles(monkeypatch):
    db_doc = {
        "_id": ObjectId(TEST_OID),
        "filename": "test.png",
        "url": "/api/portal/media/file/" + TEST_OID,
        "content_type": "image/png",
        "size_bytes": 100,
        "alt_text": "",
        "tags": [],
        "uploaded_by": "x@t",
        "used_in": [],
        "created_at": "2026-08-21T00:00:00Z",
        "stored_name": "test.png",
    }

    monkeypatch.setattr(business_routes, "_get_db", AsyncMock(
        return_value=type("D", (), {"media_assets": _Collection([db_doc])})()
    ))

    for role in ["admin", "sales", "creative", "ticket_only"]:
        db_doc["alt_text"] = ""
        staff = {"role": role, "email": f"{role}@test.id", "id": "userid"}
        result = await business_routes.media_update(mid=TEST_OID, payload={"alt_text": "updated"}, staff=staff)
        assert result["alt_text"] == "updated"


@pytest.mark.anyio
async def test_media_delete_accepts_all_staff_roles(monkeypatch):
    monkeypatch.setattr(business_routes, "_media_usage", AsyncMock(return_value=[]))

    for role in ["admin", "sales", "creative", "ticket_only"]:
        db_doc = {"_id": ObjectId(TEST_OID), "stored_name": "test.png"}
        monkeypatch.setattr(business_routes, "_get_db", AsyncMock(
            return_value=type("D", (), {"media_assets": _Collection([db_doc])})()
        ))
        staff = {"role": role, "email": f"{role}@test.id", "id": "userid"}
        result = await business_routes.media_delete(mid=TEST_OID, staff=staff)
        assert result["deleted"] == 1


# ---------------------------------------------------------------------------
# 4 — Calendar: write endpoints open to all staff
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_calendar_crud_accepts_all_staff_roles(monkeypatch):
    for role in ["admin", "sales", "creative", "ticket_only", "support"]:
        db_doc = {
            "_id": ObjectId(),
            "title": "Test",
            "type": "article",
            "scheduled_at": "2026-08-21T09:00:00",
            "status": "draft",
            "notes": "",
            "created_at": "2026-08-21T00:00:00Z",
            "owner_id": "userid",
            "linked_article_id": None,
        }
        cc = _Collection([db_doc])
        monkeypatch.setattr(business_routes, "_get_db", AsyncMock(
            return_value=type("D", (), {"content_calendar": cc, "content_plan": _Collection()})()
        ))
        monkeypatch.setattr(business_routes, "_now", lambda: "2026-08-21T00:00:00Z")
        staff = {"role": role, "email": f"{role}@test.id", "id": "userid"}

        result = await business_routes.calendar_create(
            payload={"title": "Test", "type": "article", "status": "draft",
                     "notes": "", "scheduled_at": "2026-08-21T09:00:00"},
            staff=staff,
        )
        assert result["title"] == "Test"
        created_id = result["id"]

        result = await business_routes.calendar_update(cid=created_id, payload={"title": "Updated"}, staff=staff)
        assert result["title"] == "Updated"

        result = await business_routes.calendar_delete(cid=created_id, staff=staff)
        assert result["deleted"] == 1


# ---------------------------------------------------------------------------
# 5 — Document folders: shared flag + owner/admin delete guard
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_doc_create_sets_folder_shared_owner(monkeypatch):
    """POST /admin/documents should set folder/shared/owner_id based on payload."""
    for role in ["admin", "sales", "creative"]:
        docs = _Collection()

        class FakeDb:
            documents = docs

        monkeypatch.setattr(business_routes, "_get_db", AsyncMock(return_value=FakeDb()))
        monkeypatch.setattr(business_routes, "_now", lambda: "2026-08-21T00:00:00Z")

        staff = {"role": role, "email": f"{role}@test.id", "id": "userid", "name": f"{role} User"}

        # Private doc (no shared flag)
        result = await business_routes.docs_create(
            payload={"title": "Private", "category": "contract", "customer_name": "", "url": "", "notes": ""},
            staff=staff,
        )
        assert result["shared"] is False
        assert result["owner_id"] == staff["id"]
        assert result["folder"].startswith("private/")

        # Shared doc (shared=true)
        result = await business_routes.docs_create(
            payload={"title": "Shared", "category": "contract", "customer_name": "", "url": "", "notes": "", "shared": True},
            staff=staff,
        )
        assert result["shared"] is True
        assert result["owner_id"] is None
        assert result["folder"] == "shared"


@pytest.mark.anyio
async def test_doc_delete_owner_or_admin(monkeypatch):
    """DELETE /admin/documents/{did}: owner or admin only; shared doc admin-only."""
    PRIVATE_OID = "66a0b1c2d3e4f5061728394b"

    def fresh_db():
        return type("D", (), {"documents": _Collection([
            {"_id": ObjectId(TEST_OID), "title": "Shared", "shared": True, "owner_id": None, "folder": "shared"},
            {"_id": ObjectId(PRIVATE_OID), "title": "Private", "shared": False, "owner_id": "owner123", "folder": "private/owner123"},
        ])})()

    # Admin can delete shared
    monkeypatch.setattr(business_routes, "_get_db", AsyncMock(return_value=fresh_db()))
    admin = {"role": "admin", "id": "admin1", "name": "Admin"}
    assert (await business_routes.docs_delete(did=TEST_OID, staff=admin))["deleted"] == 1

    # Admin can delete private
    monkeypatch.setattr(business_routes, "_get_db", AsyncMock(return_value=fresh_db()))
    assert (await business_routes.docs_delete(did=PRIVATE_OID, staff=admin))["deleted"] == 1

    # Owner can delete own private doc
    monkeypatch.setattr(business_routes, "_get_db", AsyncMock(return_value=fresh_db()))
    owner = {"role": "creative", "id": "owner123", "name": "Owner"}
    assert (await business_routes.docs_delete(did=PRIVATE_OID, staff=owner))["deleted"] == 1

    # Non-owner non-admin cannot delete private doc
    monkeypatch.setattr(business_routes, "_get_db", AsyncMock(return_value=fresh_db()))
    sales = {"role": "sales", "id": "sales1", "name": "Sales"}
    with pytest.raises(Exception) as exc_info:
        await business_routes.docs_delete(did=PRIVATE_OID, staff=sales)
    assert exc_info.value.status_code == 403

    # Shared doc (owner_id None): only admin can delete
    monkeypatch.setattr(business_routes, "_get_db", AsyncMock(return_value=fresh_db()))
    with pytest.raises(Exception) as exc_info:
        await business_routes.docs_delete(did=TEST_OID, staff=sales)
    assert exc_info.value.status_code == 403
