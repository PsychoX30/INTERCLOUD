"""Backup / Restore endpoints and landing-content CMS.

- Backup: streams a gzipped BSON archive produced by `mongodump --archive
  --gzip`. Admin-only; carries a filename with timestamp; downloadable.
- Restore: accepts an uploaded archive, runs `mongorestore --archive --gzip
  --drop`, i.e. wipes each collection contained in the dump and reinstates
  the shipped snapshot. Admin-only, double-guarded by a `confirm=true` query
  string parameter to prevent accidental clicks.
- Landing content: a single JSON blob at `settings.landing_content` that
  contains i18n key overrides and FAQ items. Public GET / admin POST.
"""
from __future__ import annotations

import asyncio
import os
import shlex
import subprocess
from datetime import datetime, timezone
from urllib.parse import urlparse


_MONGO_URL = os.environ.get("MONGO_URL")
_DB_NAME   = os.environ.get("DB_NAME")


def _mongo_args() -> list[str]:
    """Build the `--uri`/`--db` flags for mongodump / mongorestore."""
    if not _MONGO_URL:
        raise RuntimeError("MONGO_URL is not set")
    return ["--uri", _MONGO_URL, "--db", _DB_NAME]


async def run_mongodump() -> tuple[bytes, str]:
    """Return (archive_bytes, suggested_filename). Uses --archive --gzip."""
    args = ["/usr/bin/mongodump", *_mongo_args(), "--archive", "--gzip", "--quiet"]
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"mongodump failed (rc={proc.returncode}): "
                           f"{stderr.decode(errors='replace')[:800]}")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return stdout, f"intercloud-backup-{stamp}.archive.gz"


async def run_mongorestore(archive_bytes: bytes, *, drop: bool = True) -> str:
    """Feed the archive into `mongorestore --archive --gzip --drop`.
    Returns the tool's stderr/log so callers can surface any warnings."""
    args = ["/usr/bin/mongorestore", *_mongo_args(),
            "--archive", "--gzip", "--quiet"]
    if drop:
        args.append("--drop")
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate(input=archive_bytes)
    log = (stdout + b"\n" + stderr).decode(errors="replace")
    if proc.returncode != 0:
        raise RuntimeError(f"mongorestore failed (rc={proc.returncode}): {log[:1200]}")
    return log


# ============================================================
# Landing-content defaults — the CMS overrides these keys.
# ============================================================
LANDING_CONTENT_DEFAULT: dict = {
    # i18n dict overrides — anything you want to change lives here as
    # { "<key>": { "id": "...", "en": "..." } }. Empty dict = no overrides.
    "overrides": {},
    # Structured FAQ (public FAQ section reads this if non-empty; otherwise
    # falls back to the hardcoded `faqs` array in mock/data.js).
    "faqs": [],
    # Contact overrides (used by the frontend Footer / CTA if set).
    "contact": {
        # "phone": "+62 878-1239-7187",
        # "email": "support@intercloud-digital.com",
        # "address_id": "...",
        # "address_en": "...",
        # "whatsapp_number": "6287812397187",
    },
}


async def get_landing_content(db) -> dict:
    if db is None:
        return dict(LANDING_CONTENT_DEFAULT)
    doc = await db.settings.find_one({"key": "landing_content"})
    value = (doc or {}).get("value") or {}
    # Shallow-merge with defaults so callers always see the full shape.
    return {
        "overrides": value.get("overrides") or {},
        "faqs":      value.get("faqs") or [],
        "contact":   value.get("contact") or {},
    }
