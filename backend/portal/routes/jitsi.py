"""Jitsi Meet configuration (public read, admin write) + meeting registry."""
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, field_validator
from pymongo.errors import DuplicateKeyError

from ..audit import log_audit
from ..auth import get_current_admin
from ..jitsi_meetings import (
    DEFAULT_DURATION_MIN,
    JitsiConfigError,
    admin_projection,
    can_join,
    create_meeting,
    end_meeting,
    find_by_invite,
    join_url,
    list_meetings,
    meeting_state,
    mint_token,
    public_projection,
    room_name,
)
from .shared import _get_db, _get_setting_value, _set_setting_value

router = APIRouter()

JITSI_DEFAULTS = {
    "enabled": False,
    "domain": "meet.intercloud-digital.com",
    "default_room_prefix": "ic",
    "jwt_secret": "",          # admin-only — NEVER exposed on the public endpoint
}

# Hanya field ini yang boleh keluar tanpa autentikasi.
PUBLIC_JITSI_FIELDS = ("enabled", "domain", "default_room_prefix")


def _clean_str(value, default):
    """Normalisasi nilai string: strip; None/blank -> default.

    Nilai non-string (mis. bool `enabled`) dilewatkan apa adanya supaya False
    tidak berubah jadi default.
    """
    if isinstance(value, str):
        value = value.strip()
        return value if value else default
    if value is None:
        return default
    return value


class JitsiConfigIn(BaseModel):
    enabled: bool
    domain: str = JITSI_DEFAULTS["domain"]
    default_room_prefix: str = JITSI_DEFAULTS["default_room_prefix"]
    jwt_secret: str = ""

    @field_validator("domain", "default_room_prefix")
    @classmethod
    def _non_blank(cls, v: str) -> str:
        """Tolak domain/prefix kosong atau hanya spasi.

        Sebelumnya string kosong tersimpan apa adanya, sehingga save biasa dari
        panel admin bisa merusak URL meet secara permanen.
        """
        v = (v or "").strip()
        if not v:
            raise ValueError("must not be blank")
        return v


def _public_jitsi(cfg) -> dict:
    """Whitelist proyeksi config Jitsi untuk konsumen tanpa auth.

    Menjaga agar `jwt_secret` tidak pernah bocor, apapun isi dokumen di Mongo.
    Tahan dokumen korup (non-dict, nilai None) tanpa melempar 500 di endpoint
    publik.
    """
    if not isinstance(cfg, dict):
        cfg = {}
    out = {k: _clean_str(cfg.get(k), JITSI_DEFAULTS.get(k)) for k in PUBLIC_JITSI_FIELDS}
    secret = cfg.get("jwt_secret")
    if isinstance(secret, str):
        out["jwt_secret_set"] = bool(secret.strip())
    else:
        out["jwt_secret_set"] = bool(secret)
    return out


@router.get("/jitsi/config")
async def jitsi_config_get():
    """Public – dipakai widget di portal. Tidak pernah mengembalikan jwt_secret."""
    db = await _get_db()
    cfg = await _get_setting_value(db, "jitsi_config", JITSI_DEFAULTS)
    return _public_jitsi(cfg)


@router.post("/admin/jitsi/config")
async def jitsi_config_set(payload: JitsiConfigIn, admin=Depends(get_current_admin)):
    """Admin only – simpan config.

    `jwt_secret` kosong berarti PERTAHANKAN secret yang sudah tersimpan,
    bukan menghapusnya (perilaku lama: kosong = overwrite jadi string kosong).
    """
    db = await _get_db()
    current = await _get_setting_value(db, "jitsi_config", JITSI_DEFAULTS)
    if not isinstance(current, dict):
        current = {}
    new_secret = (payload.jwt_secret or "").strip()
    stored_secret = current.get("jwt_secret")
    if not isinstance(stored_secret, str):
        stored_secret = ""
    stored = {
        "enabled": bool(payload.enabled),
        "domain": payload.domain,
        "default_room_prefix": payload.default_room_prefix,
        "jwt_secret": new_secret if new_secret else stored_secret,
    }
    await _set_setting_value(db, "jitsi_config", stored)
    return _public_jitsi(stored)


# --------------------------------------------------------------------------- #
# Registry rapat + penerbit token undangan.
#
# Endpoint config di atas TIDAK disentuh: tests/test_jitsi_contract.py menjaga
# jitsi_config_get (publik, tanpa Depends(admin)) dan jitsi_config_set (admin),
# termasuk perilaku "secret kosong = PERTAHANKAN".
# --------------------------------------------------------------------------- #

# Landing join ada di apex; Meet sendiri di meet.intercloud-digital.com.
PORTAL_BASE = "https://intercloud-digital.com/portal"
MEET_JOIN_BASE = "https://intercloud-digital.com/meet"


class MeetingCreateIn(BaseModel):
    title: str
    slug: str | None = None
    starts_at: str | None = None
    duration_min: int = DEFAULT_DURATION_MIN
    lobby: bool = True

    @field_validator("title")
    @classmethod
    def _title_required(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("title must not be blank")
        return v[:120]


def _invite_url(slug: str, key: str) -> str:
    return f"{MEET_JOIN_BASE}/{slug}?k={key}"


@router.post("/admin/jitsi/meetings")
async def jitsi_meeting_create(payload: MeetingCreateIn, admin=Depends(get_current_admin)):
    """Buat rapat. `invite_key` plaintext dikembalikan HANYA di respons ini."""
    db = await _get_db()
    try:
        doc = await create_meeting(
            db,
            title=payload.title,
            created_by=admin.get("email", ""),
            starts_at=payload.starts_at,
            duration_min=payload.duration_min,
            slug=payload.slug,
            lobby=payload.lobby,
        )
    except ValueError as exc:
        # slug tidak lolos kontrak / di luar rentang.
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except DuplicateKeyError as exc:
        # `Weekly-Team` dan `weekly-team` bertabrakan setelah normalisasi
        # lowercase -> ini konflik, bukan kesalahan server.
        raise HTTPException(status_code=409, detail="slug sudah dipakai") from exc

    out = admin_projection(doc)
    out["invite_key"] = doc["invite_key"]
    out["invite_url"] = _invite_url(doc["slug"], doc["invite_key"])
    await log_audit(
        db,
        actor=admin,
        action="jitsi.meeting_create",
        category="system",
        target_type="jitsi_meeting",
        target_id=out["id"],
        target_label=doc["slug"],
        after={"slug": doc["slug"], "starts_at": doc["starts_at"]},
    )
    return out


@router.get("/admin/jitsi/meetings")
async def jitsi_meetings_admin(
    include_ended: bool = False, limit: int = 100, admin=Depends(get_current_admin)
):
    """Daftar rapat untuk panel admin.

    Wajib lewat `admin_projection`: `list_meetings` mengembalikan dokumen apa
    adanya, termasuk `invite_key_hash` yang tidak boleh keluar.
    """
    db = await _get_db()
    rows = await list_meetings(db, include_ended=include_ended, limit=limit)
    return {"items": [admin_projection(r) for r in rows]}


@router.post("/admin/jitsi/meetings/{meeting_id}/end")
async def jitsi_meeting_end(meeting_id: str, admin=Depends(get_current_admin)):
    """Akhiri rapat: status `ended` + rotate `invite_key` (tautan lama mati)."""
    db = await _get_db()
    if not await end_meeting(db, meeting_id, admin.get("email", "")):
        raise HTTPException(status_code=404, detail="Meeting not found")
    await log_audit(
        db,
        actor=admin,
        action="jitsi.meeting_end",
        category="system",
        target_type="jitsi_meeting",
        target_id=meeting_id,
        severity="warning",
    )
    return {"ended": True}


@router.get("/jitsi/meetings")
async def jitsi_meetings_public():
    """Daftar rapat untuk landing page — tanpa slug, tanpa invite key.

    Kalau slug ikut keluar, siapa pun bisa membuka /Intercloud-<slug> tanpa
    undangan dan seluruh mekanisme invite jadi hiasan.
    """
    db = await _get_db()
    rows = await list_meetings(db, limit=50)
    return {"items": [public_projection(r) for r in rows]}


@router.get("/jitsi/join")
async def jitsi_join(
    k: str = Query("", max_length=256),
    # 256 = penjaga DoS saja. Batas yang mengikat peserta adalah pemotongan
    # 64 karakter di mint_token(); angka itu sengaja TIDAK diduplikasi di
    # layer ini supaya tidak ada dua aturan yang saling menimpa tanpa suara.
    name: str = Query("", max_length=256),
):
    """Tukar `invite_key` menjadi token HS256 berumur pendek.

    Pengunjung di sini SUDAH memegang key yang sah, jadi mengembalikan room
    dan slug bukan kebocoran — itu justru tujuan undangan.
    """
    db = await _get_db()
    meeting = await find_by_invite(db, k)
    if not meeting:
        raise HTTPException(status_code=404, detail="Undangan tidak valid atau sudah dicabut")
    if not can_join(meeting):
        raise HTTPException(
            status_code=403,
            detail=f"Rapat tidak dapat diikuti (status: {meeting_state(meeting)})",
        )
    try:
        token = mint_token(meeting, display_name=name)
    except JitsiConfigError as exc:
        # Secret belum dipasang / terlalu pendek. 503, bukan 500: ini kondisi
        # konfigurasi yang belum siap, bukan bug.
        raise HTTPException(status_code=503, detail="Jitsi belum siap menerima undangan") from exc
    except ValueError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return {
        "room": room_name(meeting["slug"]),
        "slug": meeting["slug"],
        "token": token,
        "url": join_url(meeting["slug"], token),
    }
