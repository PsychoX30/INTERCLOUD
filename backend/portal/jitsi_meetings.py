"""Registry rapat Jitsi Meet + penerbit token undangan.

Invarian yang dijaga modul ini:

* Tidak ada room tanpa baris di koleksi ``jitsi_meetings``.
* Yang disimpan hanya ``sha256(invite_key)`` -- kebocoran database tidak
  menghasilkan tautan yang bisa dipakai.
* ``end_meeting`` merotasi hash, sehingga tautan lama mati seketika.
* Token ditandatangani dengan secret Jitsi sendiri (``/etc/jitsi/meet/jwt_secret``
  atau env ``JITSI_APP_SECRET``), BUKAN ``JWT_SECRET`` portal.

Modul ini sengaja tidak mengimpor ``server`` atau ``.shared`` supaya bisa
diuji tanpa env/DB hidup.
"""
from __future__ import annotations

import hashlib
import os
import re
import secrets
import unicodedata
from datetime import datetime, timedelta, timezone

import jwt

COLL = "jitsi_meetings"
APP_ID = "intercloud"
DOMAIN = "meet.intercloud-digital.com"
SECRET_PATH = "/etc/jitsi/meet/jwt_secret"

JOIN_GRACE_MIN = 15
DEFAULT_DURATION_MIN = 60
MAX_DURATION_MIN = 480
MIN_DURATION_MIN = 5

# 3..41 karakter, huruf kecil/angka/strip, tidak diawali/diakhiri strip.
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,39}[a-z0-9]$")

# Field yang boleh keluar tanpa autentikasi. ``slug`` TIDAK termasuk: kalau
# slug bocor, siapa pun bisa membuka /Intercloud-<slug> tanpa invite_key dan
# seluruh mekanisme undangan jadi hiasan.
PUBLIC_MEETING_FIELDS = ("title", "starts_at", "ends_at", "duration_min", "state")


class JitsiConfigError(RuntimeError):
    """Secret Jitsi tidak tersedia / kosong.

    Dibedakan dari error generik supaya route bisa menjawab 503 dan bukan 500
    yang menyembunyikan sebabnya.
    """


# --------------------------------------------------------------------------- #
# secret
# --------------------------------------------------------------------------- #
MIN_SECRET_BYTES = 32


def _app_secret() -> str:
    secret = (os.environ.get("JITSI_APP_SECRET") or "").strip()
    if not secret:
        try:
            with open(SECRET_PATH, "r", encoding="utf-8") as fh:
                secret = fh.read().strip()
        except OSError as exc:
            raise JitsiConfigError(f"secret Jitsi tidak terbaca: {exc}") from exc
    if not secret:
        raise JitsiConfigError("secret Jitsi kosong")
    if len(secret.encode("utf-8")) < MIN_SECRET_BYTES:
        # Token HS256 dengan kunci pendek bisa di-brute-force offline; ini
        # dikunci di sini, bukan hanya diperingatkan.
        raise JitsiConfigError(
            f"secret Jitsi terlalu pendek (<{MIN_SECRET_BYTES} byte)"
        )
    return secret


# --------------------------------------------------------------------------- #
# slug
# --------------------------------------------------------------------------- #
def validate_slug(slug: str) -> str:
    slug = (slug or "").strip().lower()
    if not _SLUG_RE.match(slug):
        raise ValueError(
            "slug harus 3-41 karakter, huruf kecil/angka/strip, "
            "tidak diawali atau diakhiri strip"
        )
    return slug


def slugify(text: str, *, fallback: str = "rapat") -> str:
    """Ubah judul menjadi slug yang lolos validate_slug."""
    raw = unicodedata.normalize("NFKD", (text or "")).encode("ascii", "ignore").decode()
    raw = re.sub(r"[^a-z0-9]+", "-", raw.lower()).strip("-")
    raw = re.sub(r"-{2,}", "-", raw)
    if len(raw) < 3:
        raw = f"{raw}-{secrets.token_hex(3)}" if raw else fallback
    raw = raw[:41].strip("-")
    if len(raw) < 3:
        raw = fallback
    return validate_slug(raw)


def room_name(slug: str) -> str:
    """Namespace room: ``Intercloud-<slug>``.

    Di server publik, nama room tanpa prefiks bisa bentrok dengan room milik
    orang lain di domain yang sama.
    """
    return f"Intercloud-{validate_slug(slug)}"


# --------------------------------------------------------------------------- #
# durasi & waktu
# --------------------------------------------------------------------------- #
def clamp_duration(minutes) -> int:
    try:
        value = int(minutes)
    except (TypeError, ValueError):
        return DEFAULT_DURATION_MIN
    return max(MIN_DURATION_MIN, min(MAX_DURATION_MIN, value))


def _parse(value) -> datetime | None:
    """Terima datetime / ISO string / None. Selalu kembalikan tz-aware UTC."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _iso(value) -> str:
    dt = _parse(value)
    return dt.isoformat() if dt else ""


# --------------------------------------------------------------------------- #
# invite key
# --------------------------------------------------------------------------- #
def hash_invite(key: str) -> str:
    return hashlib.sha256((key or "").encode("utf-8")).hexdigest()


def new_invite_key() -> tuple[str, str]:
    """Kembalikan ``(key_plaintext, hash)``. Plaintext hanya diberikan sekali."""
    key = secrets.token_urlsafe(32)
    return key, hash_invite(key)


# --------------------------------------------------------------------------- #
# state
# --------------------------------------------------------------------------- #
def meeting_state(meeting: dict, now: datetime | None = None) -> str:
    """``scheduled`` | ``live`` | ``expired`` | ``ended``.

    Dihitung dari waktu, bukan dari field ``status`` yang bisa basi. ``ended``
    menang atas segalanya supaya rapat yang diakhiri admin tidak hidup lagi
    hanya karena ``ends_at`` masih di depan.
    """
    now = _parse(now) or datetime.now(timezone.utc)
    if (meeting.get("status") or "") == "ended":
        return "ended"
    starts = _parse(meeting.get("starts_at"))
    ends = _parse(meeting.get("ends_at"))
    if ends and now >= ends + timedelta(minutes=JOIN_GRACE_MIN):
        return "expired"
    if starts and now < starts - timedelta(minutes=JOIN_GRACE_MIN):
        return "scheduled"
    return "live"


def can_join(meeting: dict, now: datetime | None = None) -> bool:
    """True hanya di jendela join ``[starts - grace, ends + grace)``.

    ``scheduled`` BUKAN alasan untuk boleh join -- state itu justru berarti
    rapat masih lebih dari ``JOIN_GRACE_MIN`` menuju mulai. Kalau ``scheduled``
    ikut diloloskan, tautan undangan untuk rapat tiga minggu lagi bisa ditukar
    jadi token sekarang dan seluruh batas waktu undangan jadi hiasan.
    """
    return meeting_state(meeting, now) == "live"


# --------------------------------------------------------------------------- #
# token
# --------------------------------------------------------------------------- #
def mint_token(
    meeting: dict,
    *,
    moderator: bool = False,
    display_name: str = "",
    now: datetime | None = None,
) -> str:
    """Terbitkan JWT HS256 untuk satu peserta.

    ``iss`` harus sama dengan ``app_id`` di VirtualHost Prosody dan ``sub``
    harus domain Meet. Kalau salah, SEMUA token ditolak -- hasilnya identik
    dengan Meet yang mati total dari luar. Karena itu uji positif di gate
    Fase 4 wajib, bukan opsional.
    """
    now = _parse(now) or datetime.now(timezone.utc)
    ends = _parse(meeting.get("ends_at"))
    if ends is None:
        raise ValueError("rapat tanpa ends_at")
    exp = ends + timedelta(minutes=JOIN_GRACE_MIN)
    if exp <= now:
        raise ValueError("rapat sudah berakhir")
    claims = {
        "aud": "jitsi",
        "iss": APP_ID,
        "sub": DOMAIN,
        "room": room_name(meeting["slug"]),
        "iat": int(now.timestamp()),
        "nbf": int((now - timedelta(seconds=30)).timestamp()),  # toleransi skew
        "exp": int(exp.timestamp()),
        "context": {
            "user": {
                "name": (display_name or "Tamu").strip()[:64] or "Tamu",
                "moderator": bool(moderator),
            }
        },
    }
    return jwt.encode(claims, _app_secret(), algorithm="HS256")


def decode_token(token: str) -> dict:
    """Verifikasi token dengan secret sendiri (dipakai test & debugging)."""
    return jwt.decode(
        token,
        _app_secret(),
        algorithms=["HS256"],
        audience="jitsi",
        issuer=APP_ID,
    )


# --------------------------------------------------------------------------- #
# proyeksi
# --------------------------------------------------------------------------- #
def public_projection(meeting: dict, now: datetime | None = None) -> dict:
    """Tanpa slug, tanpa invite_key_hash, tanpa created_by."""
    return {
        "title": meeting.get("title", ""),
        "starts_at": _iso(meeting.get("starts_at")),
        "ends_at": _iso(meeting.get("ends_at")),
        "duration_min": meeting.get("duration_min", DEFAULT_DURATION_MIN),
        "state": meeting_state(meeting, now),
    }


def admin_projection(meeting: dict, now: datetime | None = None) -> dict:
    return {
        "id": str(meeting.get("_id", meeting.get("id", ""))),
        "slug": meeting.get("slug", ""),
        "title": meeting.get("title", ""),
        "starts_at": _iso(meeting.get("starts_at")),
        "ends_at": _iso(meeting.get("ends_at")),
        "duration_min": meeting.get("duration_min", DEFAULT_DURATION_MIN),
        "lobby": bool(meeting.get("lobby", True)),
        "status": meeting.get("status", "scheduled"),
        "state": meeting_state(meeting, now),
        "created_by": meeting.get("created_by", ""),
        "host_name": meeting.get("host_name") or meeting.get("created_by", ""),
        "created_at": _iso(meeting.get("created_at")),
        "ended_at": _iso(meeting.get("ended_at")),
        "ended_by": meeting.get("ended_by") or "",
        "room": room_name(meeting["slug"]) if meeting.get("slug") else "",
        "invite_key_set": bool(meeting.get("invite_key_hash")),
    }


# --------------------------------------------------------------------------- #
# operasi registry
# --------------------------------------------------------------------------- #
async def create_meeting(
    db,
    *,
    title: str,
    created_by: str,
    starts_at=None,
    duration_min=DEFAULT_DURATION_MIN,
    slug: str | None = None,
    lobby: bool = True,
    host_name: str | None = None,
    now: datetime | None = None,
) -> dict:
    """Buat rapat. ``invite_key`` plaintext dikembalikan HANYA di sini."""
    now = _parse(now) or datetime.now(timezone.utc)
    starts = _parse(starts_at) or now
    minutes = clamp_duration(duration_min)
    ends = starts + timedelta(minutes=minutes)

    resolved = validate_slug(slug) if slug else slugify(title)
    key, key_hash = new_invite_key()

    doc = {
        "slug": resolved,
        # Partial unique index tidak memakai `$ne: ended` (operator itu tidak
        # didukung dalam partialFilterExpression). active_slug dihapus saat
        # meeting diakhiri, sehingga slug bisa dipakai ulang.
        "active_slug": resolved,
        "title": (title or "Rapat").strip()[:120] or "Rapat",
        "starts_at": starts.isoformat(),
        "ends_at": ends.isoformat(),
        "duration_min": minutes,
        "lobby": bool(lobby),
        "invite_key_hash": key_hash,
        "status": "scheduled",
        "created_by": created_by,
        # Nama yang tampil di badan undangan. Disimpan terpisah dari
        # `created_by` supaya undangan bisa mencantumkan "Budi Santoso"
        # walaupun akun admin-nya `support@...`.
        "host_name": (host_name or "").strip()[:80] or created_by,
        "created_at": now.isoformat(),
        "ended_at": None,
        "ended_by": None,
    }
    result = await db[COLL].insert_one(dict(doc))
    doc["_id"] = getattr(result, "inserted_id", None)
    doc["invite_key"] = key  # sekali saja
    return doc


async def find_by_invite(db, key: str) -> dict | None:
    """Cari rapat dari invite_key plaintext. Bandingkan lewat hash."""
    if not key or not isinstance(key, str):
        return None
    return await db[COLL].find_one(
        {"invite_key_hash": hash_invite(key), "status": {"$ne": "ended"}}
    )


async def find_by_room_name(db, room: str) -> dict | None:
    """Cari rapat dari nama room (``Intercloud-<slug>``) atau slug mentah.

    Dipakai oleh tokenAuthUrl: browser datang membawa nama room dari address
    bar, dan kita harus memutuskan apakah room itu benar-benar milik portal.

    Room yang TIDAK terdaftar mengembalikan None — itulah yang membuat slug
    karangan seperti ``/tes`` tidak bisa dipakai masuk.
    """
    if not room or not isinstance(room, str):
        return None
    name = room.strip()
    prefix = "Intercloud-"
    if name.lower().startswith(prefix.lower()):
        name = name[len(prefix):]
    try:
        slug = validate_slug(name.lower())
    except ValueError:
        return None
    return await db[COLL].find_one({"slug": slug, "status": {"$ne": "ended"}})


async def list_meetings(db, *, include_ended: bool = False, limit: int = 100) -> list[dict]:
    query: dict = {} if include_ended else {"status": {"$ne": "ended"}}
    cursor = db[COLL].find(query).sort("starts_at", -1).limit(max(1, min(500, limit)))
    return await cursor.to_list(length=max(1, min(500, limit)))


async def end_meeting(db, meeting_id, ended_by: str, now: datetime | None = None) -> bool:
    """Akhiri rapat + rotasi invite_key (tautan lama langsung mati)."""
    from bson import ObjectId

    now = _parse(now) or datetime.now(timezone.utc)
    try:
        oid = ObjectId(str(meeting_id))
    except Exception:
        return False
    _, key_hash = new_invite_key()
    result = await db[COLL].update_one(
        {"_id": oid},
        {
            "$set": {
                "status": "ended",
                "ended_at": now.isoformat(),
                "ended_by": ended_by,
                "invite_key_hash": key_hash,
            },
            # Lepas klaim slug: partial unique index hanya menjaga rapat yang
            # masih aktif, jadi nama rapat lama bisa dipakai lagi setelah
            # diakhiri tanpa melanggar constraint.
            "$unset": {"active_slug": ""},
        },
    )
    return getattr(result, "matched_count", 0) == 1


async def rotate_invite(db, meeting_id):
    """Putar ``invite_key`` tanpa mengubah status/lifecycle rapat.

    Kembalikan ``(key_plaintext, slug)`` sekali lagi, atau ``None`` kalau id
    tidak dikenal atau rapat sudah diakhiri. Tautan lama langsung mati karena
    hash diganti.

    **Tidak** menyentuh ``active_slug`` -- itu hanya tugas ``end_meeting``.
    Rapat yang masih hidup TETAP memegang klaim slug-nya.
    """
    from bson import ObjectId

    try:
        oid = ObjectId(str(meeting_id))
    except Exception:
        return None
    doc = await db[COLL].find_one({"_id": oid})
    if not doc:
        return None
    if (doc.get("status") or "") == "ended":
        # Rapat sudah diakhiri admin: tidak boleh "dihidupkan" lewat rotasi
        # undangan. Konsisten dengan `end` (matched_count -> 404).
        return None
    key, key_hash = new_invite_key()
    # Filter status tetap di `update_one` demi atomisitas di Mongo nyata.
    # (FakeCollection hanya mencocokkan `_id`, jadi keputusan 404 TIDAK boleh
    # bergantung pada filter ini -- pre-read di atas yang memutuskan.)
    result = await db[COLL].update_one(
        {"_id": oid, "status": {"$ne": "ended"}},
        {"$set": {"invite_key_hash": key_hash}},
    )
    if getattr(result, "matched_count", 0) != 1:
        return None
    return key, doc.get("slug", "")



def join_url(slug: str, token: str) -> str:
    # Klien jitsi-meet membaca token lewat hash "#jwt=" (W7(): hash dulu, lalu
    # search) -- app.bundle.min.js, string "jitsi_meeting_token" TIDAK dikenal
    # (0 kemunculan). Token HARUS mentah tanpa kutip: konstruktor URL SSO di
    # bundle memakai JSON.stringify(o) yang menambah kutip dan membuat HS256
    # gagal. Hash, bukan query: tidak masuk access log nginx / Referer.
    return f"https://{DOMAIN}/{room_name(slug)}#jwt={token}"


# --------------------------------------------------------------------------- #
# teks undangan siap-kirim
#
# Admin menyalin blok ini utuh (WhatsApp/email), bukan hanya URL. Formatnya
# disepakati dengan pemilik produk; jangan diubah tanpa persetujuan karena
# orang sudah terbiasa dengan susunannya.
# --------------------------------------------------------------------------- #
_BULAN_ID = (
    "Januari", "Februari", "Maret", "April", "Mei", "Juni",
    "Juli", "Agustus", "September", "Oktober", "November", "Desember",
)
_HARI_ID = ("Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu")


def format_waktu_id(dt: datetime) -> str:
    """``Senin, 12 November 2026 pukul 14.00 WIB``.

    Selalu dikonversi ke WIB (UTC+7) lalu dilabeli WIB. Mencetak zona server
    (UTC) akan membuat penerima datang 7 jam lebih awal.
    """
    from datetime import timedelta as _td, timezone as _tz

    wib = dt.astimezone(_tz(_td(hours=7))) if dt.tzinfo else dt.replace(
        tzinfo=_tz(_td(hours=7))
    )
    return (
        f"{_HARI_ID[wib.weekday()]}, {wib.day} {_BULAN_ID[wib.month - 1]} "
        f"{wib.year} pukul {wib.hour:02d}.{wib.minute:02d} WIB"
    )


def format_durasi_id(minutes) -> str:
    """``90 menit`` / ``1 jam 30 menit`` / ``2 jam``."""
    try:
        total = int(minutes)
    except (TypeError, ValueError):
        total = DEFAULT_DURATION_MIN
    jam, menit = divmod(max(0, total), 60)
    if jam and menit:
        return f"{jam} jam {menit} menit"
    if jam:
        return f"{jam} jam"
    return f"{menit} menit"


def build_invitation_text(
    *,
    host_name: str,
    title: str,
    starts_at,
    duration_min,
    url: str,
) -> str:
    """Badan undangan yang disalin admin.

    ``starts_at`` boleh datetime / ISO string / None. Kalau tidak ada jadwal,
    baris Time diisi penanda supaya admin sadar jadwalnya belum diisi alih-alih
    mencetak string kosong yang terlihat seperti bug.
    """
    starts = _parse(starts_at)
    waktu = format_waktu_id(starts) if starts else "(belum dijadwalkan)"
    host = (host_name or "").strip() or "Admin INTERCLOUD"
    topik = (title or "").strip() or "Rapat Online"

    return (
        "Halo,\n"
        "PT Intercloud Digital Inovasi Mengundang anda kedalam rapat secara online "
        "melalui tautan berikut,\n"
        "\n"
        f"Pembuat Meeting: {host}\n"
        f"Topic: {topik}\n"
        f"Time: {waktu}\n"
        f"Estimasi Durasi: {format_durasi_id(duration_min)}\n"
        "\n"
        f"Meeting Link: {url}\n"
        "\n"
        "Atas Perhatian anda kami ucapkan terima kasih,\n"
        "\n"
        "Best Regards,\n"
        "PT Intercloud Digital Inovasi"
    )
