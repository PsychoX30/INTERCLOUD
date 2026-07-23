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


def _svg_datauri(svg: str) -> str:
    """Wrap raw SVG markup as a base64 data URI usable in <img src=...>."""
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode()).decode()


# Wordmark logo — navy "INTERCLOUD" for invoice PDFs, email headers, and
# any white-background surface. This is the SINGLE source-of-truth logo:
# `logo_light` (below) is derived from it at render time by CSS filter
# inversion, so operators only need to upload ONE artwork file for a
# fully-branded portal.
_DEFAULT_LOGO_DARK = _svg_datauri(
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 320 60">'
    '<text x="0" y="45" font-family="Inter,Arial,sans-serif" font-size="40" '
    'font-weight="800" letter-spacing="-1" fill="#0a2350">INTERCLOUD</text></svg>'
)

# By default logo_light is EMPTY — the frontend detects the empty value and
# renders `logo_dark` with `filter: brightness(0) invert(1)`, producing a
# white silhouette of the same artwork. Operators MAY still upload a bespoke
# light-on-dark variant in Admin ▸ Branding if they want a different design
# for dark backgrounds (e.g. tagline in a different colour); the uploaded
# value takes precedence over the auto-invert fallback.
_DEFAULT_LOGO_LIGHT = ""

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
