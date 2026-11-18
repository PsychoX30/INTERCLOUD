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
import copy
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
# Landing-content defaults - the CMS overrides these keys.
# ============================================================
# ------------------------------------------------------------------
# Landing page composition (section order + visibility)
# ------------------------------------------------------------------
# The landing page is a stack of independent section components, each already
# carrying `id` / `data-cms-section` anchors. This tuple is the canonical set
# and the shipped order. The CMS may REORDER or HIDE these; it can never add a
# key, so a payload cannot conjure a section the frontend has no component for.
#
# Lives here rather than in `routes/cms.py` because this module owns
# LANDING_CONTENT_DEFAULT and `routes/cms.py` imports from it - the reverse
# import would be circular.
LANDING_SECTIONS = (
    "navbar", "hero", "features", "infra", "services", "guide",
    "pricing", "pop", "partners", "testimonials", "faqsec", "leadform",
    "cta", "footer",
)

# Chrome sections stay pinned: navbar first, footer last. Hiding either is a
# trap rather than a design - with no menu a visitor cannot navigate, and the
# CMS preview pane is too narrow for the mistake to be obvious before saving.
# `visible: false` on these is accepted and then overridden, so a payload never
# fails; it just cannot hide the page's own frame.
LANDING_PINNED_FIRST = ("navbar",)
LANDING_PINNED_LAST = ("footer",)


def default_layout() -> list:
    """Every section, visible, in the shipped order."""
    return [{"key": k, "visible": True} for k in LANDING_SECTIONS]


def resolve_layout(saved) -> list:
    """Reconcile a stored `layout` against the canonical section set.

    Wire shape is an ORDERED LIST - the array position IS the display order:

        [{"key": "hero", "visible": true},
         {"key": "services", "visible": false}, ...]

    A list beats integer order fields: no duplicate ranks to resolve, no gaps to
    renumber, and reordering is a splice instead of a re-index.

    Unknown keys are dropped, the first occurrence of a key wins, and any
    canonical section missing from the payload is appended in the shipped order
    and left visible. That last rule is what stops a settings document written
    before a section existed from silently erasing that section.
    """
    rows = saved if isinstance(saved, list) else []
    visible: dict = {}
    ordered: list = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        key = item.get("key")
        if not isinstance(key, str) or key not in LANDING_SECTIONS:
            continue
        if key in visible:
            continue
        # `is not False` rather than a truthiness test: a payload that omits
        # `visible`, or sends "false" as a string, must not silently hide a
        # section. Only an explicit boolean False hides.
        visible[key] = item.get("visible") is not False
        ordered.append(key)
    for key in LANDING_SECTIONS:
        if key not in visible:
            visible[key] = True
            ordered.append(key)
    for key in LANDING_PINNED_FIRST:
        visible[key] = True
    for key in LANDING_PINNED_LAST:
        visible[key] = True
    middle = [k for k in ordered
              if k not in LANDING_PINNED_FIRST and k not in LANDING_PINNED_LAST]
    final = list(LANDING_PINNED_FIRST) + middle + list(LANDING_PINNED_LAST)
    return [{"key": k, "visible": visible[k]} for k in final]


LANDING_CONTENT_DEFAULT: dict = {
    # i18n dict overrides - anything you want to change lives here as
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
    # Image overrides keyed by slot id. Only URLs are stored (media-library
    # path or absolute http/https), never base64 - keeps this doc small.
    # { "<slot>": {"url": "...", "alt_id": "...", "alt_en": "..."} }
    "images": {},
    # Structured, admin-editable lists. Each entry is a list of objects whose
    # display strings are {id,en} pairs. An empty list means "use the shipped
    # default from mock/data.js / the component" so a blank CMS never blanks
    # the page.
    #   services:     [{icon, title:{id,en}, desc:{id,en}, bullets:[{id,en}], start_price}]
    #   testimonials: [{quote:{id,en}, name, role:{id,en}, rating, avatar}]
    #   partners:     [{name, domain, logo}]
    #   stats:        [{value, label:{id,en}}]        (hero stat badges)
    #   hero_terms:   [{text:{id,en}}]                (hero sentence highlights)
    #   footer_links: [{group:{id,en}, items:[{label:{id,en}, href}]}]
    "lists": {
        "services": [],
        "testimonials": [],
        "partners": [],
        "stats": [],
        "hero_terms": [],
        "footer_links": [],
    },
    # Display order + visibility of the landing sections. Resolved against
    # LANDING_SECTIONS on read, so a document written before a section existed
    # renders that section in its shipped position instead of dropping it.
    "layout": default_layout(),
}


async def get_landing_content(db) -> dict:
    if db is None:
        return copy.deepcopy(LANDING_CONTENT_DEFAULT)
    doc = await db.settings.find_one({"key": "landing_content"})
    value = (doc or {}).get("value") or {}
    # Shallow-merge with defaults so callers always see the full shape. `lists`
    # is merged per-key so a CMS that predates a new list key still resolves it
    # to the empty default instead of KeyError.
    saved_lists = value.get("lists") if isinstance(value.get("lists"), dict) else {}
    lists = {
        key: (saved_lists.get(key) if isinstance(saved_lists.get(key), list) else [])
        for key in LANDING_CONTENT_DEFAULT["lists"]
    }
    return {
        "overrides": value.get("overrides") or {},
        "faqs":      value.get("faqs") or [],
        "contact":   value.get("contact") or {},
        "images":    value.get("images") or {},
        "lists":     lists,
        # Always resolved, never passed through raw: the frontend renders this
        # order verbatim, so it must be complete and canonical even when the
        # stored document predates a section or was edited by hand.
        "layout":    resolve_layout(value.get("layout")),
    }
