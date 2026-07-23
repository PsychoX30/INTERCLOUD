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
"""
from __future__ import annotations

# Hardcoded defaults (asset-CDN URLs). Kept in one place so PDF and email
# render pipelines share the same fallback.
_DEFAULT_LOGO_DARK = (
    "https://customer-assets-lxgj4vgw.emergentagent.net/"
    "job_portal-straight-line/artifacts/40f397oz_logo_anang-02-1-1536x1536-1.png"
)
_DEFAULT_LOGO_LIGHT = (
    "https://intercloud-digital.com/wp-content/uploads/2024/07/Mask-group.png"
)
_DEFAULT_FAVICON      = _DEFAULT_LOGO_DARK  # blue-on-white variant scales well
_DEFAULT_EMAIL_BANNER = ""                  # opt-in

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
