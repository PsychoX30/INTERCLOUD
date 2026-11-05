"""Route-layer tests for the Jitsi meeting registry (no MongoDB, no network).

Kenapa monkeypatch, bukan `dependency_overrides`: route memanggil
`db = await _get_db()` secara LANGSUNG, bukan `Depends(_get_db)`. Override
dependency untuk `_get_db` karena itu no-op, dan test akan menembak Mongo dev
yang nyata sambil tetap terlihat hijau. Yang di-override hanya
`get_current_admin`, karena itu memang dipakai lewat `Depends`.

`log_audit` menulis lewat `db.audit_logs` (akses atribut) sementara registry
memakai `db[COLL]` (akses item). `FakeDB` menyediakan keduanya; tanpa
`__getattr__`, `log_audit` menelan AttributeError-nya sendiri (best-effort by
design) dan assert audit akan lolos atas koleksi kosong.
"""
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from bson import ObjectId
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pymongo.errors import DuplicateKeyError

from portal import jitsi_meetings as jm
from portal.routes import jitsi as jitsi_routes

# 64 hex chars — bentuk `openssl rand -hex 32`. Secret < 32 byte ditolak
# `_app_secret()` dengan JitsiConfigError (dan PyJWT memperingatkan kunci lemah).
SECRET = "0123456789abcdef" * 4
ADMIN = {"id": "64b000000000000000000001", "email": "admin@example.com", "role": "admin"}


class FakeCursor:
    def __init__(self, rows):
        self.rows = list(rows)

    def sort(self, *_args):
        return self

    def limit(self, count):
        self.rows = self.rows[:count]
        return self

    async def to_list(self, length=None):
        return self.rows[:length] if length is not None else self.rows


class FakeCollection:
    """Menegakkan unique index seperti Mongo nyata.

    Tanpa ini `DuplicateKeyError` tidak pernah muncul, route menjawab 200, dan
    test 409 jadi hijau palsu.
    """

    def __init__(self, unique_fields=()):
        self.rows = []
        self.unique_fields = tuple(unique_fields)

    async def insert_one(self, doc):
        for field in self.unique_fields:
            value = doc.get(field)
            if value is None:
                continue
            if any(r.get(field) == value for r in self.rows):
                raise DuplicateKeyError(f"E11000 duplicate key error index: {field}")
        stored = dict(doc)
        stored["_id"] = ObjectId()
        self.rows.append(stored)
        return _Result(inserted_id=stored["_id"])

    @staticmethod
    def _matches(row, query):
        for field, want in query.items():
            if isinstance(want, dict) and "$ne" in want:
                if row.get(field) == want["$ne"]:
                    return False
            elif row.get(field) != want:
                return False
        return True

    async def find_one(self, query):
        for row in self.rows:
            if self._matches(row, query):
                return dict(row)
        return None

    def find(self, query):
        return FakeCursor([dict(r) for r in self.rows if self._matches(r, query)])

    async def update_one(self, query, update):
        for row in self.rows:
            if row.get("_id") == query.get("_id"):
                row.update(update.get("$set", {}))
                for key in update.get("$unset", {}):
                    row.pop(key, None)
                return _Result(matched_count=1)
        return _Result(matched_count=0)


class _Result:
    def __init__(self, **kw):
        self.__dict__.update(kw)


class FakeDB:
    def __init__(self):
        object.__setattr__(
            self,
            "_cols",
            {
                jm.COLL: FakeCollection(unique_fields=("active_slug", "invite_key_hash")),
                "audit_logs": FakeCollection(),
            },
        )

    def __getitem__(self, name):
        return self._cols[name]

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        try:
            return object.__getattribute__(self, "_cols")[name]
        except KeyError as exc:
            raise AttributeError(name) from exc


@pytest.fixture
def db():
    return FakeDB()


@pytest.fixture
async def client(db, monkeypatch, tmp_path):
    monkeypatch.setenv("JITSI_APP_SECRET", SECRET)
    # Isolasi dari /etc/jitsi/meet/jwt_secret mesin ini.
    monkeypatch.setattr(jm, "SECRET_PATH", str(tmp_path / "absent"))

    app = FastAPI()
    app.include_router(jitsi_routes.router, prefix="/api/portal")

    async def _fake_db():
        return db

    monkeypatch.setattr(jitsi_routes, "_get_db", _fake_db)
    app.dependency_overrides[jitsi_routes.get_current_admin] = lambda: ADMIN

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


CREATE = "/api/portal/admin/jitsi/meetings"
JOIN = "/api/portal/jitsi/join"


async def _create(client, **payload):
    body = {"title": "Weekly team"}
    body.update(payload)
    return await client.post(CREATE, json=body)


# --------------------------------------------------------------------------- #
# create
# --------------------------------------------------------------------------- #
async def test_create_returns_plaintext_invite_only_in_this_response(client):
    resp = await _create(client, slug="weekly-team")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["slug"] == "weekly-team"
    assert data["room"] == "Intercloud-weekly-team"
    assert data["invite_key_set"] is True
    assert data["invite_key"]
    assert "invite_key_hash" not in data
    # Apex /meet/<slug> — penerimanya belum ada (Fase 3), tapi bentuk URL-nya
    # dikunci di sini supaya tidak diam-diam berubah jadi domain lain.
    assert data["invite_url"].startswith("https://intercloud-digital.com/meet/")
    assert data["invite_url"].endswith(f"weekly-team?k={data['invite_key']}")


async def test_admin_list_never_leaks_invite_key_or_hash(client):
    await _create(client, slug="weekly-team")
    resp = await client.get(CREATE)
    assert resp.status_code == 200, resp.text
    items = resp.json()["items"]
    assert len(items) == 1
    row = items[0]
    assert "invite_key" not in row
    assert "invite_key_hash" not in row
    assert row["invite_key_set"] is True


async def test_duplicate_slug_after_lowercase_is_409(client):
    assert (await _create(client, slug="Weekly-Team")).status_code == 200
    resp = await _create(client, slug="weekly-team")
    assert resp.status_code == 409, resp.text
    assert "slug" in resp.json()["detail"].lower()


async def test_blank_title_is_422(client):
    resp = await client.post(CREATE, json={"title": "   "})
    assert resp.status_code == 422


async def test_duration_is_clamped_not_rejected(client):
    # clamp_duration = max(MIN, min(MAX, v)) -> 9999 jadi 480, bukan 400.
    created = (await _create(client, slug="weekly-team", duration_min=9999)).json()
    assert created["duration_min"] == jm.MAX_DURATION_MIN
    starts = datetime.fromisoformat(created["starts_at"])
    ends = datetime.fromisoformat(created["ends_at"])
    assert starts.tzinfo == timezone.utc
    assert ends - starts == timedelta(minutes=jm.MAX_DURATION_MIN)


# --------------------------------------------------------------------------- #
# join
# --------------------------------------------------------------------------- #
async def test_join_valid_key_mints_hs256_token(client):
    created = (await _create(client, slug="weekly-team")).json()
    resp = await client.get(JOIN, params={"k": created["invite_key"], "name": "Anang"})
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["room"] == "Intercloud-weekly-team"
    assert data["slug"] == "weekly-team"

    claims = jwt.decode(
        data["token"], SECRET, algorithms=["HS256"], audience="jitsi", issuer=jm.APP_ID
    )
    assert claims["sub"] == jm.DOMAIN
    assert claims["room"] == "Intercloud-weekly-team"
    assert claims["context"]["user"] == {"name": "Anang", "moderator": False}

    # Token dikirim di FRAGMEN, bukan query string: fragmen tidak ikut terkirim
    # ke server dan tidak masuk access log.
    assert data["url"] == (
        "https://meet.intercloud-digital.com/Intercloud-weekly-team"
        f"#jitsi_meeting_token={data['token']}"
    )


async def test_join_long_display_name_is_truncated_not_rejected(client):
    """Nama 100 karakter: route menerima, mint_token memotong ke 64.

    Inilah jalur yang sebelumnya tidak pernah teruji. `test_jitsi_meetings.py`
    memanggil mint_token langsung, jadi plafon Query di route tidak terlihat di
    sana; dan pemotongan 64 karakter tidak terlihat dari sini selama route
    menolak lebih dulu dengan 422.

    Tautan undangan diklik manusia dari email/chat. Nama panjang harus masuk
    rapat dengan nama terpotong, bukan berhenti di halaman error JSON.
    """
    created = (await _create(client, slug="weekly-team")).json()
    resp = await client.get(
        JOIN, params={"k": created["invite_key"], "name": "x" * 100}
    )
    assert resp.status_code == 200, resp.text
    claims = jwt.decode(
        resp.json()["token"],
        SECRET,
        algorithms=["HS256"],
        audience="jitsi",
        issuer=jm.APP_ID,
    )
    assert claims["context"]["user"]["name"] == "x" * 64


async def test_join_absurdly_long_name_is_422(client):
    """Plafon DoS tetap ada di 256 — bukan tanpa batas.

    Tanpa plafon, `name` multi-kilobyte memaksa JWT meng-encode claim raksasa
    hanya dengan satu permintaan.
    """
    created = (await _create(client, slug="weekly-team")).json()
    resp = await client.get(
        JOIN, params={"k": created["invite_key"], "name": "x" * 300}
    )
    assert resp.status_code == 422, resp.text


async def test_join_blank_name_defaults_to_tamu(client):
    created = (await _create(client, slug="weekly-team")).json()
    data = (await client.get(JOIN, params={"k": created["invite_key"]})).json()
    claims = jwt.decode(
        data["token"], SECRET, algorithms=["HS256"], audience="jitsi", issuer=jm.APP_ID
    )
    assert claims["context"]["user"]["name"] == "Tamu"


async def test_join_unknown_key_is_404(client):
    assert (await client.get(JOIN, params={"k": "deadbeef"})).status_code == 404
    assert (await client.get(JOIN)).status_code == 404


async def test_join_after_end_is_404_because_hash_rotated(client):
    """`end` merotasi invite_key_hash + find_by_invite menyaring status ended.

    Kunci lama tidak lagi menemukan baris apa pun -> 404, BUKAN 403. Jalur 403
    hanya untuk kunci sah yang belum masuk jendela live.
    """
    created = (await _create(client, slug="weekly-team")).json()
    ended = await client.post(f"{CREATE}/{created['id']}/end")
    assert ended.status_code == 200, ended.text
    assert ended.json() == {"ended": True}

    resp = await client.get(JOIN, params={"k": created["invite_key"]})
    assert resp.status_code == 404, resp.text


async def test_join_valid_key_before_window_is_403(client):
    """Jalur 403: kunci SAH tapi rapat masih >15 menit menuju mulai."""
    far = datetime.now(timezone.utc) + timedelta(days=21)
    created = (await _create(client, slug="weekly-team", starts_at=far.isoformat())).json()
    resp = await client.get(JOIN, params={"k": created["invite_key"]})
    assert resp.status_code == 403, resp.text
    assert "scheduled" in resp.json()["detail"]


async def test_join_without_secret_is_503_not_500(client, monkeypatch):
    created = (await _create(client, slug="weekly-team")).json()
    monkeypatch.delenv("JITSI_APP_SECRET", raising=False)
    resp = await client.get(JOIN, params={"k": created["invite_key"]})
    assert resp.status_code == 503, resp.text


async def test_join_with_short_secret_is_503(client, monkeypatch):
    created = (await _create(client, slug="weekly-team")).json()
    # 6 byte < MIN_SECRET_BYTES(32): kunci HS256 lemah harus DITOLAK, bukan
    # dipakai sambil memperingatkan.
    monkeypatch.setenv("JITSI_APP_SECRET", "short")
    resp = await client.get(JOIN, params={"k": created["invite_key"]})
    assert resp.status_code == 503, resp.text


# --------------------------------------------------------------------------- #
# end + lifecycle slug
# --------------------------------------------------------------------------- #
async def test_end_releases_slug_for_reuse(client):
    """Regression: unique index hanya menjaga slug selama rapat aktif."""
    created = (await _create(client, slug="weekly-team")).json()
    assert (
        await client.post(f"{CREATE}/{created['id']}/end")
    ).status_code == 200

    again = await _create(client, slug="weekly-team")
    assert again.status_code == 200, again.text
    assert again.json()["slug"] == "weekly-team"
    assert again.json()["id"] != created["id"]


async def test_end_unknown_id_is_404(client):
    assert (await client.post(f"{CREATE}/{ObjectId()}/end")).status_code == 404
    assert (await client.post(f"{CREATE}/not-an-objectid/end")).status_code == 404


async def test_ended_meeting_hidden_from_admin_list_unless_requested(client):
    created = (await _create(client, slug="weekly-team")).json()
    await client.post(f"{CREATE}/{created['id']}/end")

    assert (await client.get(CREATE)).json()["items"] == []
    with_ended = (await client.get(CREATE, params={"include_ended": True})).json()["items"]
    assert len(with_ended) == 1
    assert with_ended[0]["status"] == "ended"
    assert with_ended[0]["state"] == "ended"


# --------------------------------------------------------------------------- #
# public list + audit
# --------------------------------------------------------------------------- #
async def test_public_list_hides_slug_and_invite(client):
    await _create(client, slug="weekly-team")
    resp = await client.get("/api/portal/jitsi/meetings")
    assert resp.status_code == 200, resp.text
    items = resp.json()["items"]
    assert len(items) == 1
    assert set(items[0]) == set(jm.PUBLIC_MEETING_FIELDS)


async def test_create_and_end_write_audit_rows(client, db):
    created = (await _create(client, slug="weekly-team")).json()
    await client.post(f"{CREATE}/{created['id']}/end")
    actions = [r.get("action") for r in db.audit_logs.rows]
    assert "jitsi.meeting_create" in actions
    assert "jitsi.meeting_end" in actions


async def test_failed_create_writes_no_audit_row(client, db):
    assert (await client.post(CREATE, json={"title": "  "})).status_code == 422
    assert db.audit_logs.rows == []


# --------------------------------------------------------------------------- #
# rotate-invite (Fase 3): plaintext sekali lagi, hash-only, slug dipertahankan
# --------------------------------------------------------------------------- #
ROTATE = "/api/portal/admin/jitsi/meetings/{id}/rotate-invite"


async def test_rotate_invite_kills_old_key_and_issues_new_one(client, db):
    created = (await _create(client, slug="weekly-team")).json()
    old_key = created["invite_key"]
    old_hash = jm.hash_invite(old_key)
    assert (await client.get(JOIN, params={"k": old_key})).status_code == 200

    resp = await client.post(ROTATE.format(id=created["id"]))
    assert resp.status_code == 200, resp.text
    data = resp.json()
    new_key = data["invite_key"]
    assert new_key and new_key != old_key
    assert "invite_key_hash" not in data
    assert data["invite_url"].endswith(f"weekly-team?k={new_key}")

    # Kunci lama mati; kunci baru hidup.
    assert (await client.get(JOIN, params={"k": old_key})).status_code == 404
    assert (await client.get(JOIN, params={"k": new_key})).status_code == 200

    rows = db[jm.COLL].rows
    hashes = {r.get("invite_key_hash") for r in rows}
    assert old_hash not in hashes
    assert jm.hash_invite(new_key) in hashes
    # Plaintext tidak pernah tersimpan sebagai nilai mana pun.
    for r in rows:
        for v in r.values():
            assert v != old_key and v != new_key


async def test_rotate_preserves_active_slug_and_status(client, db):
    created = (await _create(client, slug="weekly-team")).json()
    await client.post(ROTATE.format(id=created["id"]))
    row = next(r for r in db[jm.COLL].rows if str(r["_id"]) == created["id"])
    assert row.get("status") == "scheduled"
    assert row.get("active_slug") == "weekly-team"  # TIDAK di-unset


async def test_rotate_slug_still_claimed_while_active(client):
    created = (await _create(client, slug="weekly-team")).json()
    await client.post(ROTATE.format(id=created["id"]))
    again = await _create(client, slug="weekly-team")
    assert again.status_code == 409, again.text


async def test_rotate_after_end_is_404(client):
    created = (await _create(client, slug="weekly-team")).json()
    await client.post(f"{CREATE}/{created['id']}/end")
    resp = await client.post(ROTATE.format(id=created["id"]))
    assert resp.status_code == 404, resp.text


async def test_rotate_unknown_id_is_404(client):
    assert (await client.post(ROTATE.format(id=ObjectId()))).status_code == 404
    assert (await client.post(ROTATE.format(id="not-an-objectid"))).status_code == 404


async def test_rotate_writes_audit_row(client, db):
    created = (await _create(client, slug="weekly-team")).json()
    await client.post(ROTATE.format(id=created["id"]))
    actions = [r.get("action") for r in db.audit_logs.rows]
    assert actions.count("jitsi.meeting_invite_rotate") == 1
