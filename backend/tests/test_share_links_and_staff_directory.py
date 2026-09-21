"""Offline unit tests for the documents foldering/sharing overhaul endpoints.

Covers the NEW endpoints QA flagged as untested:
- staff directory (client exclusion, search/filter, flat picker shape)
- folder v2 CRUD + ACL client-guard
- share-link create / list / revoke
- unlock -> password-verified per-request -> list/download

Pattern: mock _get_db and call handlers directly (fastapi-mongodb-handler-testing).
No HTTP, no real DB, no credentials.
"""
from __future__ import annotations

import asyncio
import hashlib
import os
from unittest.mock import AsyncMock, patch

import pytest
from bson import ObjectId
from fastapi import HTTPException
from starlette.requests import Request

os.environ.setdefault("JWT_SECRET", "test-secret")

from portal.routes import business_overhaul as bo
from portal.routes import staff_directory as sd
from portal.auth import create_share_token, decode_share_token, hash_password


ADMIN = {"id": "admin-1", "role": "admin", "name": "Admin", "email": "admin@x"}
SALES = {"id": "sales-1", "role": "sales", "division": "sales", "name": "Sales", "email": "sales@x"}
CLIENT = {"_id": ObjectId(), "id": str(ObjectId()), "role": "client", "name": "Client", "email": "client@x"}


# --------------------------------------------------------------------------
# Fake MongoDB (async-iterable cursor so `async for u in cursor` works)
# --------------------------------------------------------------------------
class _Cursor:
    def __init__(self, rows):
        self.rows = list(rows)
        self._skip = 0
        self._limit = None

    def sort(self, key, direction=1):
        self.rows = sorted(self.rows, key=lambda r: str(r.get(key, "")), reverse=direction == -1)
        return self

    def skip(self, n):
        self._skip = n
        return self

    def limit(self, n):
        self._limit = n
        return self

    def __aiter__(self):
        self._it = iter(self.rows[self._skip:][:self._limit] if self._limit is not None else self.rows[self._skip:])
        return self

    async def __anext__(self):
        try:
            return next(self._it)
        except StopIteration:
            raise StopAsyncIteration

    async def to_list(self, _n=None):
        return self.rows[self._skip:][:self._limit]


def _matches(doc, query):
    if not query:
        return True
    for k, cond in query.items():
        if k == "$and":
            for clause in cond:
                if not _matches(doc, clause):
                    return False
            continue
        if k == "$or":
            return any(_matches(doc, clause) for clause in cond)
        if isinstance(cond, dict):
            if "$in" in cond:
                if doc.get(k) not in cond["$in"]:
                    return False
                continue
            if "$regex" in cond:
                import re
                if not re.search(cond["$regex"], str(doc.get(k) or ""), re.IGNORECASE):
                    return False
                continue
            if "$exists" in cond:
                if (k in doc) == cond["$exists"]:
                    continue
                return False
        if doc.get(k) != cond:
            return False
    return True


class _Collection:
    def __init__(self, rows=None):
        self.rows = list(rows or [])

    def find(self, query=None, projection=None):
        return _Cursor([r for r in self.rows if _matches(r, query or {})])

    async def find_one(self, query=None):
        for r in self.rows:
            if _matches(r, query or {}):
                return r
        return None

    async def count_documents(self, query=None):
        return len([r for r in self.rows if _matches(r, query or {})])

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


class _Db:
    def __init__(self, users=None, folders=None, docs=None, links=None):
        self.users = _Collection(users)
        self.document_folders = _Collection(folders)
        self.documents = _Collection(docs)
        self.share_links = _Collection(links)


def _folder(**kw):
    f = {"_id": ObjectId(), "name": "Kontrak", "path": "Kontrak", "parent_id": None,
         "owner_id": None, "owner_name": "Admin", "division": "", "acl": [],
         "inherit_parent_acl": True, "kind": "custom", "created_at": "2026-01-01T00:00:00+00:00"}
    f.update(kw)
    return f


def _Req(headers=None, path="/"):
    scope = {"type": "http", "method": "GET",
             "headers": [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()],
             "client": ("127.0.0.1", 12345), "path": path}
    return Request(scope)


# --------------------------------------------------------------------------
# Staff directory
# --------------------------------------------------------------------------
class TestStaffDirectoryUsers:
    def test_excludes_clients(self):
        db = _Db(users=[{"_id": ObjectId(), "name": "A", "email": "a@x", "role": "admin"},
                        {"_id": ObjectId(), "name": "C", "email": "c@x", "role": "client"}])
        with patch.object(sd, "_get_db", new=AsyncMock(return_value=db)):
            out = asyncio.run(sd.staff_directory_users(staff=ADMIN))
        assert len(out["items"]) == 1
        assert out["items"][0]["email"] == "a@x"

    def test_flat_shape(self):
        db = _Db(users=[{"_id": ObjectId(), "name": "A", "email": "a@x", "role": "sales"}])
        with patch.object(sd, "_get_db", new=AsyncMock(return_value=db)):
            out = asyncio.run(sd.staff_directory_users(staff=ADMIN))
        item = out["items"][0]
        assert set(item.keys()) == {"id", "name", "email"}

    def test_search_filter(self):
        db = _Db(users=[{"_id": ObjectId(), "name": "Budi", "email": "budi@x", "role": "sales"},
                        {"_id": ObjectId(), "name": "Anang", "email": "anang@x", "role": "support"}])
        with patch.object(sd, "_get_db", new=AsyncMock(return_value=db)):
            out = asyncio.run(sd.staff_directory_users(staff=ADMIN, q="anang"))
        assert len(out["items"]) == 1
        assert out["items"][0]["name"] == "Anang"


# --------------------------------------------------------------------------
# Share links
# --------------------------------------------------------------------------
class TestShareLinks:
    def _link(self, token_hash, password_hash=None, perms=None, folder_id=None, revoked=False):
        return {"_id": ObjectId(), "folder_id": folder_id or "fid",
                "token_hash": token_hash, "password_hash": password_hash,
                "perms": perms or ["read"], "expires_at": None,
                "created_by": "admin-1", "created_at": "2026-01-01T00:00:00+00:00",
                "revoked": revoked}

    def test_create_share_link_hashes_token(self):
        folder = _folder(owner_id=None)
        db = _Db(folders=[folder])
        db.document_folders.find_one = AsyncMock(return_value=folder)
        with patch.object(bo, "_get_db", new=AsyncMock(return_value=db)), \
             patch.object(bo, "_parent_chain", new=AsyncMock(return_value=[])):
            out = asyncio.run(bo.create_share_link(
                fid=str(folder["_id"]), payload={"password": "Secret123", "perms": ["read", "download"]},
                staff=ADMIN))
        assert out["requires_password"] is True
        assert "password_hash" not in out
        inserted = db.share_links.rows[0]
        assert inserted["token_hash"]
        assert inserted["token_hash"] != out["token"]

    def test_list_share_links(self):
        fid = ObjectId()
        th = hashlib.sha256(b"abc").hexdigest()
        folder = _folder(_id=fid)
        db = _Db(folders=[folder], links=[self._link(th, folder_id=str(fid))])
        db.document_folders.find_one = AsyncMock(return_value=folder)
        with patch.object(bo, "_get_db", new=AsyncMock(return_value=db)), \
             patch.object(bo, "_parent_chain", new=AsyncMock(return_value=[])):
            out = asyncio.run(bo.list_share_links(fid=str(fid), staff=ADMIN))
        assert len(out) == 1
        assert out[0]["requires_password"] is False

    def test_revoke_share_link(self):
        folder = _folder()
        db = _Db(folders=[folder])
        db.document_folders.find_one = AsyncMock(return_value=folder)
        with patch.object(bo, "_get_db", new=AsyncMock(return_value=db)), \
             patch.object(bo, "_parent_chain", new=AsyncMock(return_value=[])):
            out = asyncio.run(bo.revoke_share_link(
                fid=str(folder["_id"]), link_id=str(ObjectId()), staff=ADMIN))
        assert out["revoked"] is True


# --------------------------------------------------------------------------
# Unlock + password-verified per-request
# --------------------------------------------------------------------------
class TestUnlockFlow:
    def _make_link(self, token="tok", password="Secret123", perms=None, folder_id=None):
        th = hashlib.sha256(token.encode()).hexdigest()
        return {"_id": ObjectId(), "folder_id": str(folder_id) if folder_id else "fid",
                "token_hash": th,
                "password_hash": hash_password(password), "perms": perms or ["read"],
                "expires_at": None, "revoked": False}, th

    def test_unlock_wrong_password_401(self):
        link, _ = self._make_link()
        db = _Db(links=[link])
        with patch.object(bo, "_get_db", new=AsyncMock(return_value=db)):
            with pytest.raises(HTTPException) as e:
                asyncio.run(bo.unlock_share_link(_Req(), "tok", {"password": "nope"}))
        assert e.value.status_code == 401

    def test_unlock_returns_share_jwt(self):
        link, th = self._make_link("tok", "Secret123", ["read", "download"])
        db = _Db(links=[link])
        with patch.object(bo, "_get_db", new=AsyncMock(return_value=db)):
            out = asyncio.run(bo.unlock_share_link(_Req(), "tok", {"password": "Secret123"}))
        assert out["perms"] == ["read", "download"]
        data = decode_share_token(out["token"])
        assert data["share_token_hash"] == th

    def test_shared_folder_list_requires_unlock_for_password_link(self):
        link, _ = self._make_link("tok", "Secret123")
        folder = _folder(_id=ObjectId())
        db = _Db(folders=[folder], links=[link], docs=[])
        with patch.object(bo, "_get_db", new=AsyncMock(return_value=db)):
            with pytest.raises(HTTPException) as e:
                asyncio.run(bo.shared_folder_list(_Req(), "tok"))
        assert e.value.status_code == 401

    def test_shared_folder_list_accepts_unlock_jwt(self):
        folder = _folder(_id=ObjectId())
        link, th = self._make_link("tok", "Secret123", folder_id=folder["_id"])
        doc = {"_id": ObjectId(), "title": "D", "folder_id": str(folder["_id"]),
               "share_with": {"users": ["x"]}, "owner_id": "owner", "stored_name": "d.pdf",
               "filename": "d.pdf", "content_type": "application/pdf"}
        db = _Db(folders=[folder], links=[link], docs=[doc])
        jwt = create_share_token(th)
        with patch.object(bo, "_get_db", new=AsyncMock(return_value=db)):
            out = asyncio.run(bo.shared_folder_list(
                _Req(headers={"Authorization": "Bearer " + jwt}), "tok"))
        assert out["documents"][0]["title"] == "D"

    def test_validate_unlock_jwt_bad_token_returns_false(self):
        assert asyncio.run(bo._validate_unlock_jwt(_Req(headers={"Authorization": "Bearer garbage"}), "tok")) is False
        assert asyncio.run(bo._validate_unlock_jwt(_Req(headers={}), "tok")) is False

    def test_validate_unlock_jwt_wrong_hash_false(self):
        jwt = create_share_token("deadbeef")
        assert asyncio.run(bo._validate_unlock_jwt(_Req(headers={"Authorization": "Bearer " + jwt}), "other")) is False


# --------------------------------------------------------------------------
# Folder v2 ACL client-guard
# --------------------------------------------------------------------------
class TestFolderV2:
    def test_update_acl_rejects_client(self):
        client_id = ObjectId()
        folder = _folder(owner_id=None)
        db = _Db(folders=[folder], users=[{"_id": client_id, "role": "client"}])
        db.document_folders.find_one = AsyncMock(return_value=folder)
        with patch.object(bo, "_get_db", new=AsyncMock(return_value=db)), \
             patch.object(bo, "_parent_chain", new=AsyncMock(return_value=[])):
            with pytest.raises(HTTPException) as e:
                asyncio.run(bo.folders_update_v2(
                    fid=str(folder["_id"]),
                    payload={"acl": [{"principal_type": "user",
                                      "principal_id": str(client_id)}]},
                    staff=ADMIN))
        assert e.value.status_code == 400


# --------------------------------------------------------------------------
# Public rate-limit header presence (contract only, no real limiter state)
# --------------------------------------------------------------------------
def test_public_endpoints_have_rate_limit_decorators():
    import inspect
    for name in ("unlock_share_link", "shared_folder_list", "shared_file_download"):
        fn = getattr(bo, name)
        src = inspect.getsource(fn)
        assert "@limiter.limit" in src
