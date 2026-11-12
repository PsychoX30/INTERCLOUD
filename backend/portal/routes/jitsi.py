"""Jitsi Meet configuration (public read, admin write) + meeting registry."""
import html

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import HTMLResponse
from bson import ObjectId
from pydantic import BaseModel, field_validator
from pymongo.errors import DuplicateKeyError

from ..audit import log_audit
from ..auth import get_current_admin
from ..jitsi_meetings import (
    COLL,
    DEFAULT_DURATION_MIN,
    JitsiConfigError,
    admin_projection,
    build_invitation_text,
    can_join,
    create_meeting,
    end_meeting,
    find_by_invite,
    find_by_room_name,
    join_url,
    list_meetings,
    meeting_state,
    mint_token,
    public_projection,
    room_name,
    rotate_invite,
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

# Meet sendiri di meet.intercloud-digital.com. Link undangan yang dibagikan
# admin HARUS menunjuk ke host itu, bukan ke apex: apex /meet/:slug hanyalah
# halaman React yang menukar ?k= jadi JWT lalu redirect, dan mengharapkan
# penerima mendarat di situ membuat link terlihat seperti halaman portal.
# Join langsung ke Meet dengan ?jwt= di hash tetap bekerja, dan /meet/:slug di
# apex dipertahankan sebagai redirector untuk tautan lama yang sudah tersebar.
PORTAL_BASE = "https://intercloud-digital.com/portal"
MEET_BASE = "https://meet.intercloud-digital.com"
MEET_JOIN_BASE = "https://intercloud-digital.com/meet"


class MeetingCreateIn(BaseModel):
    title: str
    slug: str | None = None
    starts_at: str | None = None
    duration_min: int = DEFAULT_DURATION_MIN
    lobby: bool = True
    # Nama pembuat rapat yang tampil di badan undangan. Opsional; kalau kosong
    # undangan memakai `created_by` (email admin) supaya tidak pernah blank.
    host_name: str | None = None

    @field_validator("title")
    @classmethod
    def _title_required(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("title must not be blank")
        return v[:120]

    @field_validator("host_name")
    @classmethod
    def _host_name_clean(cls, v):
        if v is None:
            return None
        return (v or "").strip()[:80]


def _invite_url(slug: str, key: str) -> str:
    """Undangan yang dibagikan.

    Tetap di apex `/meet/:slug?k=` — dan itu memang disengaja. Hanya halaman
    React di apex yang menukar ``?k=`` menjadi JWT lewat ``/api/portal/jitsi/join``;
    host Meet tidak memproses ``?k=`` sama sekali (tidak ada handler, dan
    ``branding/index.html`` hanya punya form nama room). Menaruh ``?k=`` di
    host Meet menghasilkan tautan mati yang membuka Meet tanpa token.

    Jadi tautan berbagi = gerbang undangan di apex; Meet sendiri hanya dibuka
    setelah token ditukar. Lihat ``jitsi_meetings.join_url`` untuk hop kedua.
    """
    return f"{MEET_JOIN_BASE}/{slug}?k={key}"


def _invitation_text(meeting: dict, invite_url: str) -> str:
    """Badan undangan siap-kirim untuk disalin admin."""
    return build_invitation_text(
        host_name=meeting.get("host_name") or meeting.get("created_by") or "",
        title=meeting.get("title", ""),
        starts_at=meeting.get("starts_at"),
        duration_min=meeting.get("duration_min", DEFAULT_DURATION_MIN),
        url=invite_url,
    )


def _is_oid(value) -> bool:
    try:
        ObjectId(str(value))
        return True
    except Exception:
        return False


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
            host_name=payload.host_name,
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
    out["invite_text"] = _invitation_text(doc, out["invite_url"])
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



@router.post("/admin/jitsi/meetings/{meeting_id}/rotate-invite")
async def jitsi_meeting_rotate_invite(meeting_id: str, admin=Depends(get_current_admin)):
    """Terbitkan invite_key BARU untuk rapat yang masih aktif.

    Tautan lama langsung mati. Rapat yang sudah `ended` -> 404, konsisten
    dengan `end`. Status rapat tidak berubah.
    """
    db = await _get_db()
    rotated = await rotate_invite(db, meeting_id)
    if not rotated:
        raise HTTPException(status_code=404, detail="Meeting not found")
    key, slug = rotated
    await log_audit(
        db,
        actor=admin,
        action="jitsi.meeting_invite_rotate",
        category="system",
        target_type="jitsi_meeting",
        target_id=meeting_id,
        severity="warning",
    )
    invite_url = _invite_url(slug, key)
    listing = await db[COLL].find_one({"_id": ObjectId(meeting_id)}) if _is_oid(meeting_id) else None
    return {
        "invite_key": key,
        "invite_url": invite_url,
        # Teks undangan harus ikut di sini: setelah rotasi, tautan lama mati,
        # jadi admin butuh badan undangan baru untuk dikirim ulang.
        "invite_text": _invitation_text(listing, invite_url) if listing else "",
    }


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


_ROOM_AUTH_REFUSAL_HTML = """<!DOCTYPE html>
<html lang="id">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>Rapat tidak ditemukan | INTERCLOUD Meet</title>
<style>
  :root {{ color-scheme: dark; }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; min-height: 100vh; display: flex; align-items: center;
    justify-content: center; padding: 24px;
    background: #0B1220; color: #E6EDF7;
    font-family: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
  }}
  .card {{
    width: 100%; max-width: 460px; padding: 40px 32px; text-align: center;
    background: #111C2E; border: 1px solid #1E2E45; border-radius: 16px;
  }}
  .mark {{
    width: 56px; height: 56px; margin: 0 auto 22px; border-radius: 50%;
    display: flex; align-items: center; justify-content: center;
    background: rgba(239, 68, 68, .12); border: 1px solid rgba(239, 68, 68, .35);
    font-size: 26px; color: #F87171; font-weight: 700;
  }}
  h1 {{ margin: 0 0 12px; font-size: 21px; font-weight: 650; letter-spacing: -.2px; }}
  p {{ margin: 0 0 10px; font-size: 14.5px; line-height: 1.6; color: #93A4BC; }}
  .hint {{ margin-top: 22px; padding-top: 20px; border-top: 1px solid #1E2E45; font-size: 13px; }}
  .hint b {{ color: #C7D5E8; font-weight: 600; }}
  a {{ color: #60A5FA; text-decoration: none; }}
  a:hover {{ text-decoration: underline; }}
</style>
</head>
<body>
  <div class="card">
    <div class="mark">!</div>
    <h1>Tautan rapat tidak dikenali</h1>
    <p>Ruangan <code>{room}</code> tidak terdaftar di portal INTERCLOUD,
       atau sudah berakhir.</p>
    <p class="hint">Rapat hanya bisa diikuti lewat <b>tautan undangan</b>
       yang diterbitkan portal. Hubungi penyelenggara rapat untuk
       mendapatkan tautan yang benar, atau <a href="https://intercloud-digital.com">kembali ke portal</a>.</p>
  </div>
</body>
</html>"""


def _wants_html(request: Request) -> bool:
    """Apakah pemanggil ini browser (butuh halaman) atau klien API (butuh JSON)?"""
    # Browser navigasi selalu mengirim Accept berisi text/html. Jitsi sendiri
    # tidak memakai fetch untuk tokenAuthUrl — ia melakukan window.location.href,
    # sehingga selalu datang sebagai navigasi dokumen.
    return "text/html" in (request.headers.get("accept") or "").lower()


@router.get("/jitsi/room-exists")
async def jitsi_room_exists(room: str = Query("", max_length=128)):
    """Probe ringan untuk nginx: apakah /<room> ini milik portal?

    Dipakai oleh ``auth_request`` nginx sebelum menyajikan index.html Jitsi.
    Tanpa ini, pengunjung melihat UI konferensi penuh lebih dulu dan baru
    ditolak setelah menekan Join — membingungkan dan menyesatkan.

    Status 403, BUKAN 404: ``auth_request`` hanya menerima 2xx/401/403. Balasan
    404 membuat nginx menganggap modulnya error dan mengirim 500 ke pengunjung.
    """
    db = await _get_db()
    meeting = await find_by_room_name(db, room)
    if not meeting or not can_join(meeting):
        raise HTTPException(status_code=403, detail="Rapat tidak ditemukan")
    return Response(status_code=204)


@router.get("/jitsi/room-auth")
async def jitsi_room_auth(
    request: Request,
    room: str = Query("", max_length=128),
    name: str = Query("", max_length=256),
):
    """Penjaga `tokenAuthUrl`: room ini milik portal, atau bukan.

    Dipasang sebagai ``tokenAuthUrl`` di config.js, jadi browser memanggilnya
    SETIAP kali seseorang membuka /<room>. Inilah lapisan yang menghentikan
    orang mengetik slug karangan seperti ``/tes``: room yang tidak terdaftar
    tidak akan pernah mendapat token, sehingga Prosody menolaknya.

    Sengaja TIDAK membocorkan apakah slug tertentu ada — jawaban untuk room
    tak dikenal seragam, dan tidak ada pembedaan antara "tidak terdaftar"
    dengan "sudah berakhir".
    """
    db = await _get_db()
    meeting = await find_by_room_name(db, room)

    if not meeting:
        # 404 + payload seragam. Jangan bedakan "tidak ada" dari "sudah
        # berakhir" di sini; keduanya harus terlihat sama dari luar.
        if _wants_html(request):
            # `room` disisipkan sebagai teks, jadi harus di-escape: ini satu-
            # satunya nilai yang berasal dari address bar pengunjung.
            return HTMLResponse(
                _ROOM_AUTH_REFUSAL_HTML.format(room=html.escape(room[:64] or "?")),
                status_code=404,
            )
        raise HTTPException(status_code=404, detail="Rapat tidak ditemukan")

    if not can_join(meeting):
        if _wants_html(request):
            return HTMLResponse(
                _ROOM_AUTH_REFUSAL_HTML.format(room=html.escape(room[:64] or "?")),
                status_code=404,
            )
        raise HTTPException(
            status_code=403,
            detail=f"Rapat tidak dapat diikuti (status: {meeting_state(meeting)})",
        )

    try:
        token = mint_token(meeting, display_name=name)
    except JitsiConfigError as exc:
        raise HTTPException(status_code=503, detail="Jitsi belum siap") from exc
    except ValueError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    return {
        "room": room_name(meeting["slug"]),
        "token": token,
        "url": join_url(meeting["slug"], token),
    }
