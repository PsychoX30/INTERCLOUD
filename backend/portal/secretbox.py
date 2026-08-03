"""At-rest encryption (Fernet/AES) untuk secret integrasi di MongoDB.

Nilai terenkripsi disimpan dengan prefix `enc:v1:`. Nilai plaintext legacy
tetap terbaca (passthrough) sampai dimigrasikan oleh `migrate_at_rest`.
Kunci: env SETTINGS_ENC_KEY (utama) dengan fallback derive dari JWT_SECRET,
keduanya di-derive via SHA-256 -> Fernet. MultiFernet: enkripsi memakai kunci
pertama, dekripsi mencoba semua (aman saat kunci eksplisit ditambahkan belakangan).
"""
from __future__ import annotations

import base64
import hashlib
import logging
import os

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

ENC_PREFIX = "enc:v1:"
PX_SECRET_FIELDS = ("token_secret", "password")
logger = logging.getLogger("portal.secretbox")
_box: MultiFernet | None = None


def _derive(secret: str) -> Fernet:
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest()))


def _get_box() -> MultiFernet:
    global _box
    if _box is None:
        keys = []
        enc_key = (os.environ.get("SETTINGS_ENC_KEY") or "").strip()
        jwt = (os.environ.get("JWT_SECRET") or "").strip()
        if enc_key:
            keys.append(_derive(enc_key))
        if jwt:
            keys.append(_derive(jwt))
        if not keys:
            raise RuntimeError("SETTINGS_ENC_KEY / JWT_SECRET tidak diset - enkripsi secret tidak tersedia")
        _box = MultiFernet(keys)
    return _box


def is_encrypted(value) -> bool:
    return isinstance(value, str) and value.startswith(ENC_PREFIX)


def enc_value(value):
    if not isinstance(value, str) or not value or is_encrypted(value):
        return value
    return ENC_PREFIX + _get_box().encrypt(value.encode()).decode()


def dec_value(value):
    if not is_encrypted(value):
        return value
    try:
        return _get_box().decrypt(value[len(ENC_PREFIX):].encode()).decode()
    except (InvalidToken, ValueError, TypeError):
        logger.warning("Gagal dekripsi secret at-rest (kunci berubah?) - nilai dikosongkan; "
                       "isi ulang kredensial di Admin > Integrations")
        return ""


def encrypt_credentials(creds):
    if not isinstance(creds, dict):
        return creds
    return {k: enc_value(v) for k, v in creds.items()}


def decrypt_credentials(creds):
    if not isinstance(creds, dict):
        return creds
    return {k: dec_value(v) for k, v in creds.items()}


decrypt_config = decrypt_credentials


async def migrate_at_rest(db) -> dict:
    """Enkripsi in-place data plaintext lama. Idempotent (dipanggil tiap startup)."""
    changed = {"integration_settings": 0, "proxmox_servers": 0, "integrations": 0}
    async for d in db.integration_settings.find({}):
        creds = d.get("credentials")
        if isinstance(creds, dict) and any(
                isinstance(v, str) and v and not is_encrypted(v) for v in creds.values()):
            await db.integration_settings.update_one(
                {"_id": d["_id"]}, {"$set": {"credentials": encrypt_credentials(creds)}})
            changed["integration_settings"] += 1
    async for d in db.proxmox_servers.find({}):
        upd = {k: enc_value(d[k]) for k in PX_SECRET_FIELDS
               if isinstance(d.get(k), str) and d.get(k) and not is_encrypted(d.get(k))}
        if upd:
            await db.proxmox_servers.update_one({"_id": d["_id"]}, {"$set": upd})
            changed["proxmox_servers"] += 1
    from .integrations_registry import module_schema, SECRET_FIELD_TYPES
    async for d in db.integrations.find({}):
        cfg = d.get("config")
        schema = module_schema(d.get("module", "")) or {}
        keys = [f["key"] for f in schema.get("fields", []) if f["type"] in SECRET_FIELD_TYPES]
        if isinstance(cfg, dict) and keys:
            upd = {f"config.{k}": enc_value(cfg[k]) for k in keys
                   if isinstance(cfg.get(k), str) and cfg[k] and not is_encrypted(cfg[k])}
            if upd:
                await db.integrations.update_one({"_id": d["_id"]}, {"$set": upd})
                changed["integrations"] += 1
    return changed
