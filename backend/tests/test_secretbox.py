"""Regression: at-rest encryption of integration secrets (secretbox)."""
import os

os.environ.setdefault("JWT_SECRET", "test-jwt-secret-for-secretbox")

from portal import secretbox as sb  # noqa: E402


def test_roundtrip():
    enc = sb.enc_value("super-secret-token")
    assert enc.startswith(sb.ENC_PREFIX)
    assert enc != "super-secret-token"
    assert sb.dec_value(enc) == "super-secret-token"


def test_plaintext_passthrough():
    assert sb.dec_value("plain-old-value") == "plain-old-value"
    assert sb.dec_value("") == ""
    assert sb.dec_value(None) is None
    assert sb.dec_value(True) is True


def test_enc_idempotent_and_empty():
    enc = sb.enc_value("abc")
    assert sb.enc_value(enc) == enc  # never double-encrypt
    assert sb.enc_value("") == ""
    assert sb.enc_value(None) is None
    assert sb.enc_value(123) == 123


def test_credentials_dict():
    creds = {"host": "https://x:8006", "token_secret": "s3cret", "empty": "", "flag": True}
    enc = sb.encrypt_credentials(creds)
    assert enc["host"].startswith(sb.ENC_PREFIX)
    assert enc["token_secret"].startswith(sb.ENC_PREFIX)
    assert enc["empty"] == ""
    assert enc["flag"] is True
    dec = sb.decrypt_credentials(enc)
    assert dec == creds


def test_bad_ciphertext_returns_empty():
    assert sb.dec_value(sb.ENC_PREFIX + "garbage-token") == ""
