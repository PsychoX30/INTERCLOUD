"""Unit tests for the Jitsi meeting registry; no MongoDB or network."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import jwt
import pytest
from bson import ObjectId

from portal import jitsi_meetings as jm

# 64 hex chars: bentuk yang akan dihasilkan `openssl rand -hex 32` di produksi.
# Secret < 32 byte memicu InsecureKeyLengthWarning dan menandatangani HMAC
# dengan kunci lemah.
SECRET = "0123456789abcdef" * 4


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
    def __init__(self):
        self.rows = []

    async def insert_one(self, doc):
        stored = dict(doc)
        # ObjectId asli, bukan string: end_meeting() membandingkan lewat
        # ObjectId(str(meeting_id)) dan string tidak akan pernah cocok.
        stored["_id"] = ObjectId("507f1f77bcf86cd799439011")
        self.rows.append(stored)
        return SimpleNamespace(inserted_id=stored["_id"])

    async def find_one(self, query):
        for row in self.rows:
            if row.get("invite_key_hash") == query.get("invite_key_hash"):
                if query.get("status", {}).get("$ne") == "ended" and row.get("status") == "ended":
                    continue
                return dict(row)
        return None

    def find(self, query):
        rows = self.rows
        if query.get("status", {}).get("$ne") == "ended":
            rows = [r for r in rows if r.get("status") != "ended"]
        return FakeCursor(rows)

    async def update_one(self, query, update):
        for row in self.rows:
            if row.get("_id") == query.get("_id"):
                row.update(update.get("$set", {}))
                for key in update.get("$unset", {}):
                    row.pop(key, None)
                return SimpleNamespace(matched_count=1)
        return SimpleNamespace(matched_count=0)


class FakeDB:
    def __init__(self):
        self.collections = {jm.COLL: FakeCollection()}

    def __getitem__(self, name):
        return self.collections[name]


def _now():
    return datetime(2026, 1, 2, 12, 0, tzinfo=timezone.utc)


def _meeting(**overrides):
    base = {
        "slug": "weekly-team",
        "title": "Weekly team",
        "starts_at": _now().isoformat(),
        "ends_at": (_now() + timedelta(minutes=60)).isoformat(),
        "duration_min": 60,
        "status": "scheduled",
    }
    base.update(overrides)
    return base


def test_validate_slug_accepts_contract_and_rejects_invalid_values():
    assert jm.validate_slug("abc-123") == "abc-123"
    assert jm.validate_slug("  abc-123  ") == "abc-123"
    # Huruf besar dinormalisasi, BUKAN ditolak: user mengetiknya dari UI/URL.
    # Yang penting hasilnya tetap memenuhi kontrak ^[a-z0-9][a-z0-9-]{2,40}$.
    assert jm.validate_slug("Weekly-Team") == "weekly-team"
    assert jm.validate_slug("UPPER") == "upper"
    for value in ("ab", "a", "", "-abc", "abc-", "has space", "ab_c", "a" * 42):
        with pytest.raises(ValueError):
            jm.validate_slug(value)


def test_duration_is_bounded_and_invalid_input_uses_default():
    assert jm.clamp_duration(1) == jm.MIN_DURATION_MIN
    assert jm.clamp_duration(999) == jm.MAX_DURATION_MIN
    assert jm.clamp_duration("bad") == jm.DEFAULT_DURATION_MIN


@pytest.mark.asyncio
async def test_create_stores_hash_only_and_returns_plaintext_once():
    db = FakeDB()
    created = await jm.create_meeting(
        db,
        title="Weekly team",
        created_by="admin@example.com",
        starts_at=_now(),
        duration_min=999,
        slug="weekly-team",
        now=_now(),
    )
    stored = db[jm.COLL].rows[0]
    assert created["invite_key"]
    assert "invite_key" not in stored
    assert stored["invite_key_hash"] == jm.hash_invite(created["invite_key"])
    assert stored["duration_min"] == jm.MAX_DURATION_MIN


@pytest.mark.asyncio
async def test_old_invite_stops_working_after_end_and_hash_rotates():
    db = FakeDB()
    created = await jm.create_meeting(
        db, title="Weekly team", created_by="admin", slug="weekly-team", now=_now()
    )
    old_hash = db[jm.COLL].rows[0]["invite_key_hash"]
    assert await jm.find_by_invite(db, created["invite_key"])
    assert await jm.end_meeting(db, created["_id"], "admin", now=_now())
    assert db[jm.COLL].rows[0]["invite_key_hash"] != old_hash
    assert await jm.find_by_invite(db, created["invite_key"]) is None


def test_public_projection_does_not_disclose_slug_or_invite_hash():
    projected = jm.public_projection(_meeting(invite_key_hash="secret-hash"), _now())
    assert set(projected) == {"title", "starts_at", "ends_at", "duration_min", "state"}
    assert "slug" not in projected
    assert "invite_key_hash" not in projected


def test_meeting_state_honors_ended_and_expiry():
    assert jm.meeting_state(_meeting(status="ended"), _now()) == "ended"
    expired = _meeting(ends_at=(_now() - timedelta(minutes=16)).isoformat())
    assert jm.meeting_state(expired, _now()) == "expired"
    scheduled = _meeting(starts_at=(_now() + timedelta(minutes=16)).isoformat())
    assert jm.meeting_state(scheduled, _now()) == "scheduled"


def test_token_claims_and_moderator_flag(monkeypatch):
    # Anchor ke waktu nyata: jwt.decode memverifikasi `exp` dengan jam dinding,
    # jadi tanggal fiktif 2026-01-02 membuat token selalu "expired" dan yang
    # teruji jadi kegagalan verifikasi, bukan klaim token.
    monkeypatch.setenv("JITSI_APP_SECRET", SECRET)
    now = datetime.now(timezone.utc)
    meeting = _meeting(
        starts_at=now.isoformat(),
        ends_at=(now + timedelta(minutes=60)).isoformat(),
    )
    token = jm.mint_token(meeting, moderator=True, display_name="Anang", now=now)
    claims = jwt.decode(
        token,
        SECRET,
        algorithms=["HS256"],
        audience="jitsi",
        issuer=jm.APP_ID,
    )
    assert claims["aud"] == "jitsi"
    assert claims["iss"] == jm.APP_ID
    assert claims["sub"] == jm.DOMAIN
    assert claims["room"] == "Intercloud-weekly-team"
    assert claims["context"]["user"] == {"name": "Anang", "moderator": True}
    assert claims["exp"] == int((now + timedelta(minutes=75)).timestamp())


def test_token_without_moderator_flag_is_guest(monkeypatch):
    monkeypatch.setenv("JITSI_APP_SECRET", SECRET)
    # Anchor waktu nyata, sama seperti test klaim token: `_meeting()` default
    # memakai 2026-01-02 sehingga rapat terhitung sudah berakhir dan
    # mint_token menolaknya sebelum moderator sempat diperiksa.
    now = datetime.now(timezone.utc)
    token = jm.mint_token(
        _meeting(
            starts_at=now.isoformat(),
            ends_at=(now + timedelta(minutes=60)).isoformat(),
        ),
        now=now,
    )
    claims = jwt.decode(token, SECRET, algorithms=["HS256"], audience="jitsi",
                        issuer=jm.APP_ID)
    assert claims["context"]["user"]["moderator"] is False
    assert claims["context"]["user"]["name"] == "Tamu"


def test_expired_meeting_cannot_be_minted(monkeypatch):
    monkeypatch.setenv("JITSI_APP_SECRET", SECRET)
    now = datetime.now(timezone.utc)
    dead = _meeting(
        starts_at=(now - timedelta(hours=3)).isoformat(),
        ends_at=(now - timedelta(hours=2)).isoformat(),
    )
    with pytest.raises(ValueError):
        jm.mint_token(dead, now=now)


def test_can_join_only_inside_the_join_window(monkeypatch):
    monkeypatch.setenv("JITSI_APP_SECRET", SECRET)
    now = datetime.now(timezone.utc)

    # Rapat 3 minggu ke depan: tautan undangan BELUM boleh ditukar jadi token.
    far = _meeting(
        starts_at=(now + timedelta(days=21)).isoformat(),
        ends_at=(now + timedelta(days=21, minutes=60)).isoformat(),
    )
    assert jm.meeting_state(far, now) == "scheduled"
    assert jm.can_join(far, now) is False

    # 5 menit sebelum mulai: sudah boleh (masuk grace 15 menit).
    soon = _meeting(
        starts_at=(now + timedelta(minutes=5)).isoformat(),
        ends_at=(now + timedelta(minutes=65)).isoformat(),
    )
    assert jm.can_join(soon, now) is True

    # Lewat grace 15 menit setelah berakhir: tidak boleh.
    over = _meeting(
        starts_at=(now - timedelta(hours=2)).isoformat(),
        ends_at=(now - timedelta(minutes=16)).isoformat(),
    )
    assert jm.can_join(over, now) is False

    # Sudah diakhiri admin: tidak boleh, walau jadwal masih di depan.
    assert jm.can_join(_meeting(status="ended"), now) is False


def test_missing_jitsi_secret_is_explicit_error(monkeypatch, tmp_path):
    monkeypatch.delenv("JITSI_APP_SECRET", raising=False)
    monkeypatch.setattr(jm, "SECRET_PATH", str(tmp_path / "missing-secret"))
    with pytest.raises(jm.JitsiConfigError):
        jm._app_secret()


def test_room_name_is_namespaced():
    assert jm.room_name("weekly-team") == "Intercloud-weekly-team"


def test_join_url_contains_token_in_hash():
    """Klien jitsi-meet membaca token dari hash "#jwt=" (W7: hash dulu, lalu
    search). "jitsi_meeting_token" tidak dikenal app.bundle.min.js (0 hit)."""
    url = jm.join_url("weekly-team", "abc.jwt")
    assert url == "https://meet.intercloud-digital.com/Intercloud-weekly-team#jwt=abc.jwt"


def test_join_url_token_is_raw_not_quoted():
    """Konstruktor URL SSO di bundle memakai JSON.stringify(o) sehingga nilai
    dibungkus kutip; HS256 atas nilai berkutip akan gagal. Token wajib mentah."""
    url = jm.join_url("weekly-team", "abc.jwt")
    assert '"' not in url
    assert url.endswith("#jwt=abc.jwt")
