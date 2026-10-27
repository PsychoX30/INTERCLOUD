"""Jitsi Meet configuration (public read, admin write)."""
from fastapi import APIRouter, Depends
from pydantic import BaseModel, field_validator
from ..auth import get_current_admin
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
