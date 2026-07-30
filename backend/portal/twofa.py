"""TOTP 2FA helpers (pyotp + qrcode). Secrets encrypted at rest with Fernet."""
import base64
import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from io import BytesIO

import bcrypt
import jwt
import pyotp
import qrcode

from .auth import _secret, JWT_ALGORITHM

ISSUER = "Intercloud Portal"
MFA_TTL_MINUTES = 5


def _fernet():
    from cryptography.fernet import Fernet
    key = base64.urlsafe_b64encode(hashlib.sha256(_secret().encode()).digest())
    return Fernet(key)


def new_totp_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def encrypt_secret(plain: str) -> str:
    return _fernet().encrypt(plain.encode()).decode()


def decrypt_secret(token: str) -> str:
    return _fernet().decrypt(token.encode()).decode()


def provisioning_uri(secret_b32: str, email: str) -> str:
    return pyotp.TOTP(secret_b32).provisioning_uri(name=email, issuer_name=ISSUER)


def verify_totp(secret_b32: str, code: str) -> bool:
    try:
        return pyotp.TOTP(secret_b32).verify(str(code).strip(), valid_window=1)
    except Exception:
        return False


def qr_data_url(uri: str) -> str:
    buf = BytesIO()
    qrcode.make(uri).save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def new_recovery_codes(n: int = 10):
    plaintext, docs = [], []
    for _ in range(n):
        raw = secrets.token_hex(5)
        plaintext.append(raw)
        docs.append({"hash": bcrypt.hashpw(raw.encode(), bcrypt.gensalt()).decode(), "used": False})
    return plaintext, docs


def check_recovery_code(code: str, docs: list) -> int:
    """Return index of matching unused recovery code, or -1."""
    raw = str(code).strip().lower()
    for i, rc in enumerate(docs or []):
        if not rc.get("used") and bcrypt.checkpw(raw.encode(), rc["hash"].encode()):
            return i
    return -1


def make_mfa_token(user_id: str) -> str:
    payload = {"sub": user_id, "type": "mfa_challenge",
               "exp": datetime.now(timezone.utc) + timedelta(minutes=MFA_TTL_MINUTES)}
    return jwt.encode(payload, _secret(), algorithm=JWT_ALGORITHM)


def decode_mfa_token(token: str) -> str:
    data = jwt.decode(token, _secret(), algorithms=[JWT_ALGORITHM])
    if data.get("type") != "mfa_challenge":
        raise ValueError("wrong token type")
    return data["sub"]
