"""Runtime branding — resolves logo / favicon / email banner from Mongo.

Values live in the `settings` collection under key=`branding` with shape:
    {
      "logo_light":   "<url or data-uri>",   # for dark backgrounds (header/footer)
      "logo_dark":    "<url or data-uri>",   # for white backgrounds (invoice/quotation/email)
      "favicon":      "<url or data-uri>",
      "email_banner": "<url or data-uri>",
    }

Missing keys fall through to the hardcoded DEFAULTS. This lets ops upload
new artwork in Admin ▸ Branding without redeploying.

We ship *inline SVG data URIs* as defaults so the portal renders correctly
on any host without any external asset dependency — no dead-link 404s, no
CORS, no CDN outages. Operators are expected to upload their real brand
assets via Admin ▸ Branding on first boot.
"""
from __future__ import annotations
import base64
import os
from pathlib import Path


_ASSETS_DIR = Path(__file__).parent / "assets"


def _svg_datauri(svg: str) -> str:
    """Wrap raw SVG markup as a base64 data URI usable in <img src=...>."""
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode()).decode()


def _file_datauri(filename: str, mime: str) -> str:
    """Read a bundled artwork file and return its data URI. Returns "" if
    the file is missing so we always fall through to another default."""
    p = _ASSETS_DIR / filename
    if not p.is_file():
        return ""
    return f"data:{mime};base64," + base64.b64encode(p.read_bytes()).decode()


# Wordmark logo — navy artwork for invoice PDFs, email headers, and any
# white-background surface. Loaded from the bundled `assets/logo_dark.webp`
# (the official Intercloud Digital Inovasi navy artwork). Falls back to an
# SVG wordmark placeholder if the file is missing so the portal always has
# a renderable default. Operators may still upload a bespoke variant via
# Admin ▸ Branding — that upload takes precedence.
_DEFAULT_LOGO_DARK = _file_datauri("logo_dark.webp", "image/webp") or _svg_datauri(
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 320 60">'
    '<text x="0" y="45" font-family="Inter,Arial,sans-serif" font-size="40" '
    'font-weight="800" letter-spacing="-1" fill="#0a2350">INTERCLOUD</text></svg>'
)

# Light-on-dark logo — loaded from the bundled `assets/logo_light.webp`
# (the official Intercloud Digital Inovasi white artwork). Falls back to
# empty if the file is missing, which triggers the frontend's auto-invert
# behaviour on logo_dark. Operators may still upload a bespoke variant via
# Admin ▸ Branding — that upload takes precedence over this default.
_DEFAULT_LOGO_LIGHT = _file_datauri("logo_light.webp", "image/webp")

# Favicon — 64×64 rounded navy tile with a gold "I" glyph.
_DEFAULT_FAVICON = _svg_datauri(
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
    '<rect width="64" height="64" rx="12" fill="#0a2350"/>'
    '<text x="32" y="46" text-anchor="middle" font-family="Inter,Arial,sans-serif" '
    'font-size="42" font-weight="900" fill="#f5b120">I</text></svg>'
)

_DEFAULT_EMAIL_BANNER = ""  # opt-in

DEFAULTS = {
    "logo_light":   _DEFAULT_LOGO_LIGHT,
    "logo_dark":    _DEFAULT_LOGO_DARK,
    "favicon":      _DEFAULT_FAVICON,
    "email_banner": _DEFAULT_EMAIL_BANNER,
}

BRANDING_KEYS = tuple(DEFAULTS.keys())


async def get_branding(db) -> dict:
    """Return the merged {defaults, DB overrides} dict."""
    if db is None:
        return dict(DEFAULTS)
    doc = await db.settings.find_one({"key": "branding"})
    value = (doc or {}).get("value") or {}
    return {k: (value.get(k) or DEFAULTS[k]) for k in BRANDING_KEYS}


async def get_logo_dark(db) -> str:
    b = await get_branding(db)
    return b["logo_dark"]


async def get_logo_light(db) -> str:
    b = await get_branding(db)
    return b["logo_light"]
