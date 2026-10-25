"""Jitsi Meet configuration (public read, admin write)."""
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from ..auth import get_current_admin
from .shared import _get_db, _get_setting_value, _set_setting_value

router = APIRouter()

JITSI_DEFAULTS = {
    "enabled": False,
    "domain": "meet.intercloud-digital.com",
    "default_room_prefix": "ic",
    "jwt_secret": "",          # optional – if you use JWT auth on Jitsi
}

class JitsiConfigIn(BaseModel):
    enabled: bool
    domain: str = JITSI_DEFAULTS["domain"]
    default_room_prefix: str = JITSI_DEFAULTS["default_room_prefix"]
    jwt_secret: str = ""

@router.get("/jitsi/config")
async def jitsi_config_get():
    """Public – dipakai widget di portal."""
    db = await _get_db()
    cfg = await _get_setting_value(db, "jitsi_config", JITSI_DEFAULTS)
    return cfg

@router.post("/admin/jitsi/config")
async def jitsi_config_set(payload: JitsiConfigIn, admin=Depends(get_current_admin)):
    """Admin only – simpan config."""
    db = await _get_db()
    await _set_setting_value(db, "jitsi_config", payload.dict())
    return await _get_setting_value(db, "jitsi_config", JITSI_DEFAULTS)