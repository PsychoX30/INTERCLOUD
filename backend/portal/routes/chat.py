"""Chatwoot widget configuration (public read, admin write)."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from ..auth import get_current_admin
from .shared import _get_db, _get_setting_value, _set_setting_value

router = APIRouter()

CHAT_DEFAULTS = {
    "enabled": False,
    "widget_id": "",          # Chatwoot website_token
    "api_base": "https://chat.intercloud-digital.com",
}


class ChatConfigIn(BaseModel):
    enabled: bool
    widget_id: str = ""
    api_base: str = CHAT_DEFAULTS["api_base"]


@router.get("/chat/config")
async def chat_config_get():
    """Public – dipakai widget di landing / portal."""
    db = await _get_db()
    cfg = await _get_setting_value(db, "chat_config", CHAT_DEFAULTS)
    return cfg


@router.post("/admin/chat/config")
async def chat_config_set(payload: ChatConfigIn, admin=Depends(get_current_admin)):
    """Admin only – simpan config."""
    db = await _get_db()
    await _set_setting_value(db, "chat_config", payload.dict())
    return await _get_setting_value(db, "chat_config", CHAT_DEFAULTS)