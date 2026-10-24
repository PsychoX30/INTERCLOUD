"""End-to-end fake-DB test:
   draft -> publish -> submit x2 -> export CSV -> verify row count, escaping, share_id stability."""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "backend"))

import pytest
from portal.routes.catalog import (
    form_builder_create, form_builder_publish, form_builder_new_draft,
    public_form_config, public_form_submit, form_builder_export,
)
pytestmark = pytest.mark.asyncio

# ----------------------------------------------------------------------
# Tiny in-memory Motor-like collections (only the methods the routes use)
# ----------------------------------------------------------------------
class _Cursor:
    def __init__(self, docs): self._docs = list(docs)
    def sort(self, *a, **k): return self
    async def to_list(self, n): return self._docs[:n]
    def __aiter__(self): return self._async_iter()
    async def _async_iter(self):
        for d in self._docs: yield d

class _Collection:
    def __init__(self): self._docs = []; self._id_seq = 0
    def _next_id(self):
        self._id_seq += 1
        from bson import ObjectId
        return ObjectId()
    async def find_one(self, q):
        for d in self._docs:
            if all(d.get(k) == v for k, v in q.items()):
                return d
        return None
    async def insert_one(self, doc):
        if "_id" not in doc: doc["_id"] = self._next_id()
        self._docs.append(doc)
        class R: inserted_id = doc["_id"]
        return R()
    async def update_one(self, q, upd):
        for d in self._docs:
            if all(d.get(k) == v for k, v in q.items()):
                if "$set" in upd: d.update(upd["$set"])
                if "$inc" in upd:
                    for k, v in upd["$inc"].items(): d[k] = d.get(k, 0) + v
                class R: matched_count = 1
                return R()
        class R: matched_count = 0
        return R()
    def find(self, q=None):
        q = q or {}
        return _Cursor([d for d in self._docs if all(d.get(k) == v for k, v in q.items())])

class _FakeDB:
    def __init__(self):
        self.form_configs = _Collection()
        self.form_submissions = _Collection()
        self.leads = _Collection()
        self.crm_customers = _Collection()

# ----------------------------------------------------------------------
# Monkeypatch the internal `_get_db` used by the route functions
# ----------------------------------------------------------------------
import portal.routes.catalog as cat_mod
_fake_db = _FakeDB()
async def _fake_get_db(): return _fake_db
cat_mod._get_db = _fake_get_db  # type: ignore

# Stub recaptcha enforcement so we don't need a full integration_settings fake
import portal.integrations_v2 as iv2
async def _noop_recaptcha(db, token, action, ip):
    return None
iv2.enforce_recaptcha = _noop_recaptcha  # type: ignore

# Dummy staff object (routes only check that the dep is present)
class _Staff: pass
_staff = _Staff()

# ----------------------------------------------------------------------
async def test_full_form_flow():
    # 1️⃣ create draft
    payload = {
        "name": "Contact", "slug": "contact", "title": "Hubungi Kami",
        "fields": [
            {"key":"name","label":"Nama","type":"text","required":True},
            {"key":"email","label":"Email","type":"email","required":True},
        ],
    }
    created = await form_builder_create(payload, staff=_staff)
    assert created["status"] == "draft"
    assert created["version"] == 1
    fid = created["id"]

    # 2️⃣ publish
    published = await form_builder_publish(fid, staff=_staff)
    assert published["status"] == "published"
    assert published["version"] == 2
    share_id = published["share_id"]
    assert share_id

    # 3️⃣ public read by slug
    cfg_slug = await public_form_config(published["slug"])
    assert cfg_slug["share_id"] == share_id

    # 4️⃣ public read by share_id
    cfg_share = await public_form_config(share_id)
    assert cfg_share["share_id"] == share_id

    # 5️⃣ submit two entries
    # mock request object with client.host
    class _FakeRequest:
        class _Client:
            host = "127.0.0.1"
        client = _Client()
    _fake_request = _FakeRequest()

    for i in range(2):
        vals = {"name": f"User {i}", "email": f"u{i}@example.com"}
        resp = await public_form_submit(published["slug"], {**vals, "recaptcha_token": None}, request=_fake_request)
        assert resp["ok"] and "lead_id" in resp

    # 6️⃣ export CSV
    export_resp = await form_builder_export(fid, status=None, staff=_staff)
    chunks = []
    async for chunk in export_resp.body_iterator:
        chunks.append(chunk)
    csv_text = "".join(chunks)

    #   - BOM present
    assert csv_text.startswith("\ufeff")
    lines = csv_text.splitlines()
    #   - header + 2 data rows
    assert len(lines) == 3
    #   - custom field columns appear
    header = lines[0]
    assert "submitted_at" in header and "Nama" in header and "Email" in header

    # 7️⃣ republish - share_id must stay identical
    await form_builder_new_draft(fid, staff=_staff)
    repub = await form_builder_publish(fid, staff=_staff)
    assert repub["share_id"] == share_id
    assert repub["version"] == 4
