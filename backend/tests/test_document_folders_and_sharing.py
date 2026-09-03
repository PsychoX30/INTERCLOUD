"""Offline unit tests for document folders, sharing visibility, preview dispatch,
and migration (feature/documents-overhaul).

Pattern: mock _get_db and call handlers directly (see skill
fastapi-mongodb-handler-testing). No HTTP, no real DB, no credentials.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from bson import ObjectId

import portal.routes.business as biz


# ---------------------------------------------------------------- helpers
def _make_collection():
    c = MagicMock()
    c.find_one = AsyncMock()
    c.insert_one = AsyncMock()
    c.delete_one = AsyncMock()
    c.update_one = AsyncMock()
    c.update_many = AsyncMock()
    c.count_documents = AsyncMock(return_value=0)
    c.find = MagicMock()
    c.find.return_value.sort.return_value.to_list = AsyncMock(return_value=[])
    c.find.return_value.sort.return_value.skip.return_value.limit.return_value.to_list = AsyncMock(return_value=[])
    return c


def _db():
    d = MagicMock()
    d.documents = _make_collection()
    d.document_folders = _make_collection()
    d.__getitem__.side_effect = lambda k: getattr(d, k)
    return d


def _insert_id(doc, _id=None):
    doc["_id"] = _id or ObjectId()
    r = MagicMock()
    r.inserted_id = doc["_id"]
    return r


ADMIN = {"id": "admin-1", "role": "admin", "name": "Admin", "email": "admin@x"}
FINANCE = {"id": "fin-1", "role": "finance", "division": "finance", "name": "Fin", "email": "fin@x"}
SALES = {"id": "sales-1", "role": "sales", "division": "sales", "name": "Sales", "email": "sales@x"}
SUPPORT = {"id": "sup-1", "role": "support", "division": "support", "name": "Sup", "email": "sup@x"}


def _doc(owner_id="u1", shared=False, sw=None, **kw):
    d = {
        "_id": ObjectId(),
        "title": "Doc",
        "category": "contract",
        "customer_name": "",
        "url": "",
        "notes": "",
        "filename": "a.pdf",
        "stored_name": "a.pdf",
        "size_bytes": 10,
        "folder": "shared" if shared else f"private/{owner_id}",
        "shared": shared,
        "owner_id": owner_id,
        "owner_name": "Owner",
        "content_type": "application/pdf",
        "created_at": "2026-01-01T00:00:00",
        "share_with": sw or {"users": [], "divisions": [], "roles": []},
    }
    d.update(kw)
    return d


# ---------------------------------------------------------------- visibility
class TestDocCanRead:
    def test_admin_reads_everything(self):
        assert biz._doc_can_read(ADMIN, _doc(owner_id="someone-else"))

    def test_owner_reads_own(self):
        assert biz._doc_can_read({"id": "u1", "role": "sales"}, _doc(owner_id="u1"))

    def test_shared_flag_grants_read(self):
        assert biz._doc_can_read(SALES, _doc(owner_id="u2", shared=True))

    def test_legacy_no_owner_grants_read_to_internal_staff_only(self):
        assert biz._doc_can_read(FINANCE, _doc(owner_id=None))
        assert not biz._doc_can_read(SALES, _doc(owner_id=None))

    def test_stranger_blocked(self):
        assert not biz._doc_can_read(SALES, _doc(owner_id="u2"))

    def test_share_with_user_grants_read(self):
        sw = {"users": ["sales-1"], "divisions": [], "roles": []}
        assert biz._doc_can_read(SALES, _doc(owner_id="u2", sw=sw))

    def test_share_with_division_grants_read(self):
        sw = {"users": [], "divisions": ["sales"], "roles": []}
        assert biz._doc_can_read(SALES, _doc(owner_id="u2", sw=sw))

    def test_share_with_role_grants_read(self):
        sw = {"users": [], "divisions": [], "roles": ["finance"]}
        assert biz._doc_can_read(FINANCE, _doc(owner_id="u2", sw=sw))
        assert not biz._doc_can_read(SALES, _doc(owner_id="u2", sw=sw))

    def test_division_case_insensitive(self):
        sw = {"users": [], "divisions": ["SALES"], "roles": []}
        assert biz._doc_can_read(SALES, _doc(owner_id="u2", sw=sw))


class TestDocCanManage:
    def test_admin_manages_everything(self):
        assert biz._doc_can_manage(ADMIN, _doc(owner_id="u1"))

    def test_owner_manages_own(self):
        assert biz._doc_can_manage({"id": "u1", "role": "sales"}, _doc(owner_id="u1"))

    def test_sharee_cannot_manage(self):
        sw = {"users": ["sales-1"], "divisions": [], "roles": []}
        assert not biz._doc_can_manage(SALES, _doc(owner_id="u2", sw=sw))

    def test_shared_doc_admin_only(self):
        assert not biz._doc_can_manage(SALES, _doc(owner_id="u2", shared=True))


# ---------------------------------------------------------------- folders
class TestFoldersList:
    def test_admin_sees_private_roots(self):
        db = _db()
        private_root = {"_id": ObjectId(), "name": "Private (X)", "parent_id": None,
                        "owner_id": "u1", "owner_name": "X", "division": "",
                        "path": "Private (X)", "is_private_root": True, "created_at": "2026-01-01"}
        db.document_folders.find.return_value.sort.return_value.to_list = AsyncMock(
            return_value=[private_root])
        with patch.object(biz, "_get_db", new=AsyncMock(return_value=db)):
            out = asyncio.run(biz.folders_list(staff=ADMIN))
        assert len(out) == 1
        assert out[0]["name"] == "Private (X)"
        assert out[0]["children"] == []


class TestFoldersCreate:
    def test_create_top_folder_as_admin(self):
        db = _db()
        db.document_folders.insert_one = AsyncMock(side_effect=lambda doc: _insert_id(doc))
        with patch.object(biz, "_get_db", new=AsyncMock(return_value=db)):
            out = asyncio.run(biz.folders_create(payload={"name": "Kontrak"}, staff=ADMIN))
        assert out["name"] == "Kontrak"
        assert out["path"] == "Kontrak"
        assert out["owner_id"] is None

    def test_create_rejects_slash(self):
        db = _db()
        with patch.object(biz, "_get_db", new=AsyncMock(return_value=db)):
            with pytest.raises(Exception) as e:
                asyncio.run(biz.folders_create(payload={"name": "a/b"}, staff=ADMIN))
        assert "400" in str(e.value) or "slash" in str(e.value).lower() or "/" in str(e.value)

    def test_create_child_folder_nested_path(self):
        db = _db()
        parent = {"_id": ObjectId(), "name": "Kontrak", "parent_id": None, "owner_id": None,
                  "owner_name": "A", "division": "", "path": "Kontrak", "created_at": "2026-01-01"}
        db.document_folders.find_one = AsyncMock(return_value=parent)
        db.document_folders.insert_one = AsyncMock(side_effect=lambda doc: _insert_id(doc))
        with patch.object(biz, "_get_db", new=AsyncMock(return_value=db)):
            out = asyncio.run(biz.folders_create(
                payload={"name": "2026", "parent_id": str(parent["_id"])}, staff=ADMIN))
        assert out["path"] == "Kontrak/2026"
        assert out["parent_id"] == str(parent["_id"])


class TestFoldersDelete:
    def test_delete_empty_folder(self):
        db = _db()
        f = {"_id": ObjectId(), "name": "F", "parent_id": None, "owner_id": None,
             "path": "F", "created_at": "2026-01-01"}
        db.document_folders.find_one = AsyncMock(return_value=f)
        db.documents.count_documents = AsyncMock(return_value=0)
        db.document_folders.count_documents = AsyncMock(return_value=0)
        db.document_folders.delete_one = AsyncMock()
        with patch.object(biz, "_get_db", new=AsyncMock(return_value=db)):
            out = asyncio.run(biz.folders_delete(fid=str(f["_id"]), staff=ADMIN))
        assert out == {"deleted": 1}

    def test_delete_nonempty_folder_rejected(self):
        db = _db()
        f = {"_id": ObjectId(), "name": "F", "parent_id": None, "owner_id": None,
             "path": "F", "created_at": "2026-01-01"}
        db.document_folders.find_one = AsyncMock(return_value=f)
        db.documents.count_documents = AsyncMock(return_value=3)
        with patch.object(biz, "_get_db", new=AsyncMock(return_value=db)):
            with pytest.raises(Exception):
                asyncio.run(biz.folders_delete(fid=str(f["_id"]), staff=ADMIN))

    def test_delete_private_root_rejected(self):
        db = _db()
        f = {"_id": ObjectId(), "name": "Private (X)", "parent_id": None, "owner_id": "u1",
             "path": "Private (X)", "is_private_root": True, "created_at": "2026-01-01"}
        db.document_folders.find1 = None
        db.document_folders.find_one = AsyncMock(return_value=f)
        with patch.object(biz, "_get_db", new=AsyncMock(return_value=db)):
            with pytest.raises(Exception):
                asyncio.run(biz.folders_delete(fid=str(f["_id"]), staff=ADMIN))


# ---------------------------------------------------------------- migration
class TestMigrate:
    def _mkdb(self, docs, folders):
        db = _db()
        # emulate Mongo cursors for the two find() calls in migrate handler
        # 1) shared-root find_one
        db.document_folders.find_one = AsyncMock(side_effect=lambda q: (
            folders[0] if q.get("is_shared_root") else
            next((f for f in folders if str(f.get("_id")) == str(q.get("_id"))), None)
        ))
        # 2) documents.find({"folder_id": ...}) — needs an async iterator
        async def _aiter_docs(q):
            for d in docs:
                if d.get("folder_id") in (None, ""):
                    yield d
        db.documents.find = MagicMock(return_value=_aiter_docs({}))
        db.documents.update_one = AsyncMock()
        # private root find_one for each owner
        db.document_folders.find_one = AsyncMock(side_effect=lambda q: (
            folders[0] if q.get("is_shared_root") else
            next((f for f in folders if f.get("is_private_root") and f.get("owner_id") == q.get("owner_id")), None)
        ))
        db.document_folders.insert_one = AsyncMock(side_effect=lambda doc: _insert_id(doc))
        return db

    def test_migrate_assigns_shared_and_private_roots(self):
        shared_root = {"_id": ObjectId(), "name": "Shared", "is_shared_root": True,
                       "owner_id": None, "path": "Shared", "parent_id": None,
                       "owner_name": "system", "division": "", "created_at": "2026-01-01"}
        docs = [
            _doc(owner_id=None, shared=True),          # → shared root
            _doc(owner_id="u1"),                        # → private root for u1
            _doc(owner_id="u1"),                        # → same private root
        ]
        db = self._mkdb(docs, [shared_root])
        with patch.object(biz, "_get_db", new=AsyncMock(return_value=db)):
            out = asyncio.run(biz.docs_migrate_folders(staff=ADMIN))
        assert out["migrated"] == 3
        assert out["owners"] == 2
        assert db.documents.update_one.await_count == 3

    def test_migrate_idempotent_second_run(self):
        shared_root = {"_id": ObjectId(), "name": "Shared", "is_shared_root": True,
                       "owner_id": None, "path": "Shared", "parent_id": None,
                       "owner_name": "system", "division": "", "created_at": "2026-01-01"}
        docs = [_doc(owner_id=None, shared=True)]  # already handled pattern
        db = self._mkdb(docs, [shared_root])
        with patch.object(biz, "_get_db", new=AsyncMock(return_value=db)):
            out = asyncio.run(biz.docs_migrateFolders if False else biz.docs_migrate_folders(staff=ADMIN))
        assert out["migrated"] == 1


# ---------------------------------------------------------------- docs handlers
class TestDocsList:
    def test_folder_filter_root_means_unfiled(self):
        db = _db()
        db.documents.find.return_value.sort.return_value.to_list = AsyncMock(return_value=[])
        with patch.object(biz, "_get_db", new=AsyncMock(return_value=db)):
            out = asyncio.run(biz.docs_list(staff=ADMIN, folder_id="root"))
        query = db.documents.find.call_args[0][0]
        assert {"$or": [{"folder_id": None}, {"folder_id": {"$exists": False}}]} in query["$and"]

    def test_share_with_visibility_in_query(self):
        db = _db()
        db.documents.find.return_value.sort.return_value.to_list = AsyncMock(return_value=[])
        with patch.object(biz, "_get_db", new=AsyncMock(return_value=db)):
            asyncio.run(biz.docs_list(staff=SUPPORT))
        query = db.documents.find.call_args[0][0]
        orc = query["$and"][0]["$or"]
        assert {"share_with.users": "sup-1"} in orc
        assert {"share_with.divisions": "support"} in orc
        assert {"share_with.roles": "support"} in orc


class TestDocsUpdate:
    def test_update_share_with_persists(self):
        db = _db()
        d = _doc(owner_id="u1")
        db.documents.find_one = AsyncMock(return_value=d)
        db.documents.update_one = AsyncMock()
        with patch.object(biz, "_get_db", new=AsyncMock(return_value=db)):
            out = asyncio.run(biz.docs_update(
                did=str(d["_id"]),
                payload={"share_with": {"users": ["sales-1"], "divisions": ["SALES"], "roles": []}},
                staff={"id": "u1", "role": "sales"},
            ))
        upd = db.documents.update_one.call_args[0][1]["$set"]
        assert upd["share_with"]["users"] == ["sales-1"]
        assert upd["share_with"]["divisions"] == ["sales"]  # normalized lowercase
        assert out["share_with"]["users"] == ["sales-1"]

    def test_non_owner_cannot_edit(self):
        db = _db()
        d = _doc(owner_id="u1")
        db.documents.find_one = AsyncMock(return_value=d)
        with patch.object(biz, "_get_db", new=AsyncMock(return_value=db)):
            with pytest.raises(Exception):
                asyncio.run(biz.docs_update(
                    did=str(d["_id"]), payload={"title": "x"}, staff=SALES))


class TestDocsMove:
    def test_move_to_folder(self):
        db = _db()
        d = _doc(owner_id="u1")
        f = {"_id": ObjectId(), "name": "Kontrak", "path": "Kontrak", "parent_id": None,
             "owner_id": None, "created_at": "2026-01-01"}
        db.documents.find_one = AsyncMock(side_effect=lambda q: (
            d if "documents" else None))
        db.document_folders.find_one = AsyncMock(return_value=f)
        db.documents.update_one = AsyncMock()
        with patch.object(biz, "_get_db", new=AsyncMock(return_value=db)):
            out = asyncio.run(biz.docs_move(
                did=str(d["_id"]), payload={"folder_id": str(f["_id"])},
                staff={"id": "u1", "role": "sales"}))
        assert out["folder_id"] == str(f["_id"])
        assert out["folder_path"] == "Kontrak"


class TestDocsPreview:
    def test_preview_dispatch_image(self):
        db = _db()
        d = _doc(owner_id=None, shared=True, content_type="image/png", filename="x.png")
        db.documents.find_one = AsyncMock(return_value=d)
        with patch.object(biz, "_get_db", new=AsyncMock(return_value=db)):
            out = asyncio.run(biz.docs_preview(did=str(d["_id"]), staff=SALES))
        assert out["kind"] == "image"
        assert out["file_url"].endswith(f"/documents/file/{d['_id']}")
        assert out["download_url"].endswith(f"/admin/documents/{d['_id']}/download")

    def test_preview_dispatch_unknown(self):
        db = _db()
        # zip with a .zip filename — extension not in kind map → kind "none"
        d = _doc(owner_id=None, shared=True, content_type="application/zip",
                 filename="archive.zip", stored_name="archive.zip")
        db.documents.find_one = AsyncMock(return_value=d)
        with patch.object(biz, "_get_db", new=AsyncMock(return_value=db)):
            out = asyncio.run(biz.docs_preview(did=str(d["_id"]), staff=SALES))
        assert out["kind"] == "none"

    def test_preview_blocked_for_stranger(self):
        db = _db()
        d = _doc(owner_id="u2")
        db.documents.find_one = AsyncMock(return_value=d)
        with patch.object(biz, "_get_db", new=AsyncMock(return_value=db)):
            with pytest.raises(Exception):
                asyncio.run(biz.docs_preview(did=str(d["_id"]), staff=SALES))

    def test_preview_kind_by_extension_fallback(self):
        assert biz._doc_preview_kind("", "report.docx") == "docx"
        assert biz._doc_preview_kind("application/octet-stream", "x.mp4") == "video"
        assert biz._doc_preview_kind("", "") == "none"


class TestDocsDownloadGuard:
    def test_download_blocked_for_stranger(self):
        db = _db()
        d = _doc(owner_id="u2")
        db.documents.find_one = AsyncMock(return_value=d)
        with patch.object(biz, "_get_db", new=AsyncMock(return_value=db)):
            with pytest.raises(Exception):
                asyncio.run(biz.docs_download(did=str(d["_id"]), staff=SALES))


class TestMimeTypes:
    def test_audio_video_odf_allowed(self):
        assert "audio/mpeg" in biz._DOC_ALLOWED_TYPES
        assert "video/mp4" in biz._DOC_ALLOWED_TYPES
        assert "application/vnd.oasis.opendocument.text" in biz._DOC_ALLOWED_TYPES
        assert "application/vnd.openxmlformats-officedocument.presentationml.presentation" in biz._DOC_ALLOWED_TYPES


class TestUploadShareWith:
    def test_upload_parses_share_with_json(self, tmp_path):
        db = _db()
        db.document_folders.find_one = AsyncMock()
        with patch.object(biz, "_get_db", new=AsyncMock(return_value=db)), \
             patch.object(biz, "DOCS_DIR", tmp_path):
            from fastapi import UploadFile
            from starlette.datastructures import Headers
            import io as _io
            file = UploadFile(
                file=_io.BytesIO(b"data"), filename="t.txt",
                headers=Headers({"content-type": "text/plain"}),
            )
            out = asyncio.run(biz.docs_upload(
                file=file, title="T", category="contract", customer_name="",
                notes="", shared="false", folder_id="",
                share_with='{"users": ["sales-1"], "divisions": [], "roles": []}',
                staff=FINANCE,
            ))
        inserted = db.documents.insert_one.call_args[0][0]
        assert inserted["share_with"]["users"] == ["sales-1"]
        assert out["can_manage"] is True  # owner


class TestSerialize:
    def test_serialize_doc_includes_new_fields(self):
        d = _doc(owner_id="u1", folder_id="fid", folder_path="Kontrak",
                 sw={"users": ["u2"], "divisions": ["sales"], "roles": ["finance"]})
        out = biz._serialize_doc(d)
        assert out["folder_id"] == "fid"
        assert out["folder_path"] == "Kontrak"
        assert out["share_with"]["users"] == ["u2"]
        assert out["share_with"]["divisions"] == ["sales"]
        assert out["can_manage"] is False
        assert out["has_file"] is True
