"""Submissions database view + richer field kinds.

Covers the behaviour that was missing before: every form has its own queryable
dataset surfaced as table columns/rows, the CSV mirrors those exact columns,
and the new field kinds validate server-side.
"""
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "backend"))

import pytest
from bson import ObjectId

from portal.routes.catalog import (
    form_builder_create, form_builder_update, form_builder_publish,
    form_builder_submissions, form_builder_delete_submission,
    form_builder_export, form_builder_detail, form_builder_toggle_close,
    public_form_config, public_form_submit, _fb_clean_fields,
    _fb_validate_submission,
)
pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------- fake motor
class _Cursor:
    def __init__(self, docs):
        self._docs = list(docs)

    def sort(self, *a, **k):
        return self

    def skip(self, n):
        self._docs = self._docs[int(n):]
        return self

    def limit(self, n):
        self._docs = self._docs[:int(n)]
        return self

    async def to_list(self, n):
        return self._docs[:n]

    def __aiter__(self):
        return self._gen()

    async def _gen(self):
        for d in self._docs:
            yield d


def _match(doc, q):
    for k, v in q.items():
        if k == "$or":
            if not any(_match(doc, sub) for sub in v):
                return False
            continue
        if isinstance(v, dict) and "$regex" in v:
            import re as _re
            cur = doc.get(k)
            if isinstance(cur, list):
                cur = " ".join(str(x) for x in cur)
            if not isinstance(cur, str) or not _re.search(v["$regex"], cur, _re.I):
                return False
            continue
        if isinstance(v, dict) and "$nin" in v:
            if doc.get(k) in v["$nin"]:
                return False
            continue
        if isinstance(v, dict) and "$in" in v:
            if doc.get(k) not in v["$in"]:
                return False
            continue
        if doc.get(k) != v:
            return False
    return True


class _Collection:
    def __init__(self):
        self._docs = []

    async def find_one(self, q, sort=None):
        for d in self._docs:
            if _match(d, q):
                return d
        return None

    async def insert_one(self, doc):
        if "_id" not in doc:
            doc["_id"] = ObjectId()
        self._docs.append(doc)

        class R:
            inserted_id = doc["_id"]
        return R()

    async def update_one(self, q, upd):
        for d in self._docs:
            if _match(d, q):
                d.update(upd.get("$set", {}))
                for k, v in upd.get("$inc", {}).items():
                    d[k] = d.get(k, 0) + v

                class R:
                    matched_count = 1
                return R()

        class R:
            matched_count = 0
        return R()

    async def delete_one(self, q):
        for i, d in enumerate(self._docs):
            if _match(d, q):
                self._docs.pop(i)

                class R:
                    deleted_count = 1
                return R()

        class R:
            deleted_count = 0
        return R()

    async def delete_many(self, q):
        keep = [d for d in self._docs if not _match(d, q)]
        n = len(self._docs) - len(keep)
        self._docs = keep

        class R:
            deleted_count = n
        return R()

    async def count_documents(self, q):
        return sum(1 for d in self._docs if _match(d, q))

    def find(self, q=None, *a, **k):
        q = q or {}
        return _Cursor([d for d in self._docs if _match(d, q)])


class _FakeDB:
    def __init__(self):
        self.form_configs = _Collection()
        self.form_submissions = _Collection()
        self.leads = _Collection()
        self.crm_customers = _Collection()


import portal.routes.catalog as cat_mod  # noqa: E402

_db = _FakeDB()


async def _fake_get_db():
    return _db


cat_mod._get_db = _fake_get_db  # type: ignore

import portal.integrations_v2 as iv2  # noqa: E402


async def _noop_recaptcha(*a, **k):
    return None


iv2.enforce_recaptcha = _noop_recaptcha  # type: ignore


class _Req:
    class _C:
        host = "127.0.0.1"
    client = _C()

    class _H:
        @staticmethod
        def get(k, default=None):
            return {"user-agent": "pytest-agent", "referer": "https://x.test/f"}.get(k, default)
    headers = _H()


class _Staff:
    pass


_staff = _Staff()


def _reset():
    global _db
    _db.__init__()


# --------------------------------------------------------------------- fields
async def test_clean_fields_accepts_rich_kinds():
    fields = _fb_clean_fields([
        {"key": "nama", "label": "Nama", "type": "text", "required": True},
        {"key": "lahir", "label": "Tanggal lahir", "type": "date"},
        {"key": "hadir", "label": "Kehadiran", "type": "radio", "options": ["Hadir", "Tidak"]},
        {"key": "sesi", "label": "Sesi", "type": "multiselect", "options": ["Pagi", "Siang"]},
        {"key": "nilai", "label": "Rating", "type": "rating", "rating_max": 7},
        {"key": "cat", "label": "Catatan", "type": "textarea", "max": 50},
        {"key": "sec", "label": "Bagian 2", "type": "section"},
    ])
    bykey = {f["key"]: f for f in fields}
    assert bykey["lahir"]["type"] == "date"
    assert bykey["hadir"]["options"] == ["Hadir", "Tidak"]
    assert bykey["nilai"]["rating_max"] == 7
    assert bykey["cat"]["max"] == 50
    # section never stores an answer but keeps its position
    assert bykey["sec"]["type"] == "section"


async def test_clean_fields_rejects_duplicate_keys_and_empty_options():
    from fastapi import HTTPException
    with pytest.raises(HTTPException):
        _fb_clean_fields([
            {"key": "a", "label": "A", "type": "text"},
            {"key": "a", "label": "A2", "type": "text"},
        ])
    with pytest.raises(HTTPException):
        _fb_clean_fields([{"key": "p", "label": "Pilih", "type": "select", "options": []}])


async def test_validator_handles_new_kinds():
    fields = _fb_clean_fields([
        {"key": "email", "label": "Email", "type": "email", "required": True},
        {"key": "tanggal", "label": "Tanggal", "type": "date"},
        {"key": "sesi", "label": "Sesi", "type": "multiselect", "options": ["Pagi", "Siang"]},
        {"key": "skor", "label": "Skor", "type": "rating", "rating_max": 5},
        {"key": "umur", "label": "Umur", "type": "number", "min": 17, "max": 99},
    ])
    vals, errs = _fb_validate_submission(fields, {
        "email": "a@b.co", "tanggal": "2026-11-13", "sesi": ["Pagi", "Siang"],
        "skor": "4", "umur": "25",
    })
    assert errs == {}
    assert vals["sesi"] == ["Pagi", "Siang"]
    assert vals["skor"] == 4
    assert vals["umur"] == "25"

    # invalid values surface per-field messages, not a 500
    _, errs2 = _fb_validate_submission(fields, {
        "email": "bad", "tanggal": "13-11-2026", "sesi": ["Malam"],
        "skor": "9", "umur": "10",
    })
    assert set(errs2) == {"email", "tanggal", "sesi", "skor", "umur"}


async def test_unknown_payload_keys_are_dropped():
    fields = _fb_clean_fields([{"key": "nama", "label": "Nama", "type": "text"}])
    vals, _ = _fb_validate_submission(fields, {"nama": "Budi", "is_admin": "true"})
    assert vals == {"nama": "Budi"}


# --------------------------------------------------------- submissions view
async def test_submissions_table_columns_and_rows():
    _reset()
    created = await form_builder_create({
        "name": "Undangan", "slug": "undangan",
        "fields": [
            {"key": "name", "label": "Nama", "type": "text", "required": True},
            {"key": "hadir", "label": "Kehadiran", "type": "radio", "options": ["Ya", "Tidak"]},
            {"key": "jml", "label": "Jumlah tamu", "type": "number"},
            {"key": "sec", "label": "Kontak", "type": "section"},
            {"key": "email", "label": "Email", "type": "email"},
        ],
    }, staff=_staff)
    fid = created["id"]
    await form_builder_publish(fid, staff=_staff)

    for i in range(3):
        await public_form_submit("undangan", {
            "name": f"Tamu {i}", "hadir": "Ya", "jml": str(i + 1),
            "email": f"t{i}@example.com" if i else "",
        }, request=_Req())

    view = await form_builder_submissions(fid, skip=0, limit=25, q=None, status=None, staff=_staff)
    assert view["total"] == 3
    assert len(view["rows"]) == 3
    # section must not become a column
    keys = [c["key"] for c in view["columns"]]
    assert "__created_at" in keys
    assert "sec" not in keys
    assert "hadir" in keys and "jml" in keys

    row = view["rows"][0]
    assert row["values"]["name"].startswith("Tamu")
    assert row["id"]


async def test_submissions_search_and_email_filter():
    _reset()
    created = await form_builder_create({
        "name": "Survei", "slug": "survei",
        "fields": [{"key": "name", "label": "Nama", "type": "text"},
                   {"key": "email", "label": "Email", "type": "email"}],
    }, staff=_staff)
    fid = created["id"]
    await form_builder_publish(fid, staff=_staff)

    await public_form_submit("survei", {"name": "Andi", "email": "andi@x.test"}, request=_Req())
    await public_form_submit("survei", {"name": "Bunga"}, request=_Req())

    hit = await form_builder_submissions(fid, skip=0, limit=25, q="Andi", status=None, staff=_staff)
    assert hit["total"] == 1 and hit["rows"][0]["name"] == "Andi"

    with_email = await form_builder_submissions(fid, skip=0, limit=25, q=None,
                                                status="with_email", staff=_staff)
    assert with_email["total"] == 1


async def test_pagination_slices_rows_but_keeps_total():
    _reset()
    created = await form_builder_create({
        "name": "Absensi", "slug": "absensi",
        "fields": [{"key": "name", "label": "Nama", "type": "text"}],
    }, staff=_staff)
    fid = created["id"]
    await form_builder_publish(fid, staff=_staff)
    for i in range(5):
        await public_form_submit("absensi", {"name": f"P{i}"}, request=_Req())

    page = await form_builder_submissions(fid, skip=0, limit=2, q=None, status=None, staff=_staff)
    assert page["total"] == 5
    assert len(page["rows"]) == 2
    assert page["limit"] == 2


async def test_delete_submission_resyncs_counter():
    _reset()
    created = await form_builder_create({
        "name": "Kontak", "slug": "kontak",
        "fields": [{"key": "name", "label": "Nama", "type": "text"}],
    }, staff=_staff)
    fid = created["id"]
    await form_builder_publish(fid, staff=_staff)
    await public_form_submit("kontak", {"name": "A"}, request=_Req())
    await public_form_submit("kontak", {"name": "B"}, request=_Req())

    view = await form_builder_submissions(fid, skip=0, limit=25, q=None, status=None, staff=_staff)
    sid = view["rows"][0]["id"]
    out = await form_builder_delete_submission(fid, sid, staff=_staff)
    assert out["submissions"] == 1

    detail = await form_builder_detail(fid, staff=_staff)
    assert detail["stats"]["total"] == 1


async def test_export_columns_match_view():
    _reset()
    created = await form_builder_create({
        "name": "Event", "slug": "event",
        "fields": [
            {"key": "name", "label": "Nama", "type": "text"},
            {"key": "sesi", "label": "Sesi", "type": "multiselect", "options": ["Pagi", "Malam"]},
            {"key": "sec", "label": "Bagian", "type": "section"},
        ],
    }, staff=_staff)
    fid = created["id"]
    await form_builder_publish(fid, staff=_staff)
    await public_form_submit("event", {"name": "Rina", "sesi": ["Pagi", "Malam"]}, request=_Req())

    resp = await form_builder_export(fid, status=None, q=None, staff=_staff)
    chunks = []
    async for c in resp.body_iterator:
        chunks.append(c)
    text = "".join(chunks)

    assert text.startswith("\ufeff")
    header = text.splitlines()[0]
    assert "Nama" in header and "Sesi" in header
    assert "Bagian" not in header
    # multiselect flattens to a single CSV cell
    assert "Pagi; Malam" in text


# --------------------------------------------------------- publish controls
async def test_closed_form_rejects_submit_with_410():
    from fastapi import HTTPException
    _reset()
    created = await form_builder_create({
        "name": "Ditutup", "slug": "ditutup",
        "fields": [{"key": "name", "label": "Nama", "type": "text"}],
    }, staff=_staff)
    fid = created["id"]
    await form_builder_publish(fid, staff=_staff)
    await form_builder_toggle_close(fid, {"closed": True, "closed_message": "Sudah selesai"}, staff=_staff)

    cfg = await public_form_config("ditutup")
    assert cfg["closed"] is True
    assert cfg["closed_reason"] == "Sudah selesai"

    with pytest.raises(HTTPException) as ei:
        await public_form_submit("ditutup", {"name": "X"}, request=_Req())
    assert ei.value.status_code == 410


async def test_submission_cap_blocks_after_quota():
    from fastapi import HTTPException
    _reset()
    created = await form_builder_create({
        "name": "Kuota", "slug": "kuota",
        "fields": [{"key": "name", "label": "Nama", "type": "text"}],
    }, staff=_staff)
    fid = created["id"]
    await form_builder_toggle_close(fid, {"submission_cap": 2}, staff=_staff)
    await form_builder_publish(fid, staff=_staff)

    await public_form_submit("kuota", {"name": "A"}, request=_Req())
    await public_form_submit("kuota", {"name": "B"}, request=_Req())
    with pytest.raises(HTTPException) as ei:
        await public_form_submit("kuota", {"name": "C"}, request=_Req())
    assert ei.value.status_code == 410


async def test_delete_form_cascades_submissions():
    _reset()
    created = await form_builder_create({
        "name": "Hapus", "slug": "hapus",
        "fields": [{"key": "name", "label": "Nama", "type": "text"}],
    }, staff=_staff)
    fid = created["id"]
    await form_builder_publish(fid, staff=_staff)
    await public_form_submit("hapus", {"name": "A"}, request=_Req())

    from portal.routes.catalog import form_builder_delete
    out = await form_builder_delete(fid, staff=_staff)
    assert out["submissions_deleted"] == 1
    assert await _db.form_submissions.count_documents({}) == 0
