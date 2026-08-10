"""CMS: branding, landing content, articles, sitemap, SEO render, public status page.

Split from the former monolithic routes.py - behavior preserved 1:1.
"""
import os
import asyncio
import logging
import secrets
import re
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket
from bson import ObjectId
from datetime import datetime, timezone, timedelta
from typing import List, Optional

from .. import models as m
from ..auth import (
    verify_password, hash_password, create_access_token,
    get_current_user, get_current_admin, get_current_staff, get_current_content,
    get_current_kb_author,
    require_roles, sales_can_access,
    STAFF_ROLES, FINANCE_ROLES, BILLING_ROLES, CATALOG_ROLES,
    OPS_ROLES, USER_MGMT_ROLES, TICKET_ROLES, CONTENT_ROLES,
)
from ..audit import log_audit, serialize as _serialize_audit
from ..secretbox import (dec_value as _sb_dec, enc_value as _sb_enc,
                         decrypt_config as _sb_dec_config)
from .. import integrations_v2 as iv2
from .business import _sync_article_calendar  # noqa: E402
from .noc import _noc_uptime_window  # noqa: E402
from .shared import _get_db, _iso, _now, _oid  # noqa: E402
from fastapi.responses import HTMLResponse  # noqa: E402
from portal.branding import BRANDING_KEYS as _BRANDING_KEYS  # noqa: E402
from portal.branding import get_branding as _get_branding_dict  # noqa: E402
from portal.security import PUBLIC_STATUS_LIMIT  # noqa: E402
from portal.security import limiter as _rl_limiter  # noqa: E402

router = APIRouter()


# ============================================================
# Branding endpoints (Admin ▸ Branding)
# ============================================================
@router.get("/branding")
async def branding_get():
    """Public read - landing/emails/frontend fetch the current branding."""
    db = await _get_db()
    return await _get_branding_dict(db)


@router.post("/admin/branding")
async def branding_set(payload: dict, admin=Depends(get_current_admin)):
    """Update one or more branding fields. Payload example:
        { "logo_dark": "data:image/png;base64,....",
          "favicon":   "https://cdn.example.com/favicon.png" }
    Only the four known keys (logo_light, logo_dark, favicon, email_banner)
    are stored; unknown keys are dropped for safety.
    """
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Body must be a JSON object")
    incoming = {k: v for k, v in payload.items() if k in _BRANDING_KEYS and isinstance(v, str)}
    # data-URI size sanity: refuse anything over 4 MB to keep the settings doc small
    for k, v in list(incoming.items()):
        if v.startswith("data:") and len(v) > 4 * 1024 * 1024:
            raise HTTPException(status_code=413, detail=f"{k}: image is larger than 4 MB")
    if not incoming:
        raise HTTPException(status_code=400, detail="No valid branding fields provided")
    db = await _get_db()
    existing = await db.settings.find_one({"key": "branding"}) or {}
    merged = dict(existing.get("value") or {})
    merged.update(incoming)
    await db.settings.update_one(
        {"key": "branding"},
        {"$set": {"value": merged, "updated_at": datetime.now(timezone.utc).isoformat()}},
        upsert=True,
    )
    return await _get_branding_dict(db)


@router.delete("/admin/branding/{key}")
async def branding_reset(key: str, admin=Depends(get_current_admin)):
    """Reset one field to its hardcoded default."""
    if key not in _BRANDING_KEYS:
        raise HTTPException(status_code=400, detail=f"Unknown branding key: {key}")
    db = await _get_db()
    existing = await db.settings.find_one({"key": "branding"}) or {}
    merged = dict(existing.get("value") or {})
    merged.pop(key, None)
    await db.settings.update_one(
        {"key": "branding"},
        {"$set": {"value": merged, "updated_at": datetime.now(timezone.utc).isoformat()}},
        upsert=True,
    )
    return await _get_branding_dict(db)


# ============================================================
# Landing-page CMS
# ============================================================
from portal.backups import (
    get_landing_content as _get_landing_content,
    LANDING_CONTENT_DEFAULT as _LANDING_DEFAULT,
    run_mongodump as _run_mongodump,
    run_mongorestore as _run_mongorestore,
)


@router.get("/landing-content")
async def landing_content_get():
    """Public - Landing page fetches on mount and merges overrides on top of
    the shipped i18n dict + hardcoded FAQ list."""
    db = await _get_db()
    return await _get_landing_content(db)


@router.post("/admin/landing-content")
async def landing_content_set(payload: dict, admin=Depends(get_current_admin)):
    """Replace the landing-content JSON. Body:
        {
          "overrides": {"hero.h1a": {"id": "...", "en": "..."}},
          "faqs":      [{"q": {"id": "...", "en": "..."},
                          "a": {"id": "...", "en": "..."}}, ...],
          "contact":   {"phone": "...", "email": "...", "address_id": "...", ...}
        }
    Unknown top-level keys are ignored. Any missing top-level key is set to
    an empty dict/list so the page never crashes on missing shape."""
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Body must be a JSON object")
    clean = {
        "overrides": payload.get("overrides") if isinstance(payload.get("overrides"), dict) else {},
        "faqs":      payload.get("faqs")      if isinstance(payload.get("faqs"), list)      else [],
        "contact":   payload.get("contact")   if isinstance(payload.get("contact"), dict)   else {},
    }
    # 128 KB cap on the whole doc - plenty for a landing page's worth of text.
    approx = len(str(clean))
    if approx > 128 * 1024:
        raise HTTPException(status_code=413,
                            detail=f"landing-content is {approx // 1024} KB; cap is 128 KB")
    db = await _get_db()
    await db.settings.update_one(
        {"key": "landing_content"},
        {"$set": {"value": clean, "updated_at": datetime.now(timezone.utc).isoformat()}},
        upsert=True,
    )
    return await _get_landing_content(db)


@router.delete("/admin/landing-content")
async def landing_content_reset(admin=Depends(get_current_admin)):
    """Wipe all landing overrides - Landing renders the shipped defaults."""
    db = await _get_db()
    await db.settings.update_one(
        {"key": "landing_content"},
        {"$set": {"value": {"overrides": {}, "faqs": [], "contact": {}},
                  "updated_at": datetime.now(timezone.utc).isoformat()}},
        upsert=True,
    )
    return dict(_LANDING_DEFAULT)


# ============================================================
# Articles / CMS - admin editor + public listing + search
# ============================================================
import re as _re_slug  # noqa: E402


def _slugify(text: str) -> str:
    s = (text or "").lower().strip()
    s = _re_slug.sub(r"[^a-z0-9]+", "-", s)
    s = _re_slug.sub(r"-+", "-", s).strip("-")
    return s[:80] or "article"


def _norm_tags(tags):
    out = []
    seen = set()
    for t in tags or []:
        s = _slugify(str(t))
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    return out


def _serialize_article(d: dict, *, include_body: bool = True) -> dict:
    out = {
        "id": str(d["_id"]),
        "title": d.get("title", ""),
        "slug": d.get("slug", ""),
        "excerpt": d.get("excerpt", ""),
        "cover_image_url": d.get("cover_image_url", ""),
        "cover_image_alt": d.get("cover_image_alt", ""),
        "video_url": d.get("video_url", ""),
        "author_name": d.get("author_name", ""),
        "tags": d.get("tags", []),
        "category": d.get("category", ""),
        "type": d.get("type", "blog"),
        "kb_section": d.get("kb_section", ""),
        "status": d.get("status", "draft"),
        "published_at": d.get("published_at"),
        "meta_title": d.get("meta_title", ""),
        "meta_description": d.get("meta_description", ""),
        "meta_keywords": d.get("meta_keywords", []),
        "og_image_url": d.get("og_image_url", ""),
        "is_featured": bool(d.get("is_featured", False)),
        "view_count": int(d.get("view_count", 0)),
        "created_at": _iso(d.get("created_at", "")),
        "updated_at": _iso(d.get("updated_at", "")),
    }
    if include_body:
        out["body_html"] = d.get("body_html", "")
    return out


async def _ensure_article_indexes(db):
    try:
        await db.articles.create_index("slug", unique=True)
    except Exception:
        pass
    try:
        # Text index for search (title, excerpt, body, tags)
        await db.articles.create_index([
            ("title", "text"), ("excerpt", "text"),
            ("body_html", "text"), ("tags", "text"),
        ], default_language="english", name="articles_text_idx")
    except Exception:
        pass


# Allowlist HTML sanitizer for user-authored rich text (article body). Neutralizes
# stored XSS: strips <script>/<style>/<iframe>, on* handlers, javascript: URLs, etc.
# Applied server-side so it protects even if the browser CSP allows inline scripts.
_ALLOWED_HTML_TAGS = {
    "p", "br", "hr", "span", "div", "a", "b", "strong", "i", "em", "u", "s",
    "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "li", "blockquote",
    "code", "pre", "img", "figure", "figcaption", "table", "thead", "tbody",
    "tfoot", "tr", "th", "td", "sub", "sup", "mark", "small",
}


_ALLOWED_HTML_ATTRS = {
    "a": {"href", "title", "target"},
    "img": {"src", "alt", "title", "width", "height", "loading"},
    "*": {"class"},
}


def _sanitize_article_html(html: str) -> str:
    if not html:
        return ""
    import nh3
    return nh3.clean(
        html,
        tags=_ALLOWED_HTML_TAGS,
        attributes=_ALLOWED_HTML_ATTRS,
        url_schemes={"http", "https", "mailto", "tel"},
        link_rel="noopener noreferrer nofollow",
    )


async def _unique_slug(db, base: str, ignore_id: Optional[str] = None) -> str:
    slug = _slugify(base)
    i = 1
    candidate = slug
    while True:
        q = {"slug": candidate}
        if ignore_id:
            q["_id"] = {"$ne": _oid(ignore_id)}
        exists = await db.articles.find_one(q)
        if not exists:
            return candidate
        i += 1
        candidate = f"{slug}-{i}"


# ---- Admin CRUD ----
@router.get("/admin/articles")
async def admin_articles_list(status: str = "", q: str = "", tag: str = "",
                              type: str = "",
                              staff=Depends(get_current_staff)):
    db = await _get_db()
    await _ensure_article_indexes(db)
    filt: dict = {}
    if status in ("draft", "published", "archived"):
        filt["status"] = status
    if type in ("blog", "kb"):
        filt["type"] = type
    if tag:
        filt["tags"] = _slugify(tag)
    if q:
        filt["$text"] = {"$search": q}
    docs = await db.articles.find(filt).sort("updated_at", -1).to_list(500)
    return [_serialize_article(d, include_body=False) for d in docs]


@router.get("/admin/articles/{aid}")
async def admin_article_get(aid: str, staff=Depends(get_current_staff)):
    db = await _get_db()
    d = await db.articles.find_one({"_id": _oid(aid)})
    if not d:
        raise HTTPException(status_code=404, detail="Article not found")
    return _serialize_article(d)


@router.post("/admin/articles")
async def admin_article_create(payload: m.ArticleIn, admin=Depends(get_current_kb_author)):
    db = await _get_db()
    # Support staff may author KB articles only; blog/marketing stays admin+creative.
    if admin.get("role") == "support" and payload.type != "kb":
        raise HTTPException(status_code=403, detail="Support may only author knowledge-base articles")
    await _ensure_article_indexes(db)
    now = _now()
    slug_base = payload.slug or payload.title
    slug = await _unique_slug(db, slug_base)
    doc = payload.model_dump()
    doc.update({
        "slug": slug,
        "body_html": _sanitize_article_html(doc.get("body_html", "")),
        "tags": _norm_tags(payload.tags),
        "meta_keywords": _norm_tags(payload.meta_keywords),
        "author_name": payload.author_name or admin["name"],
        "created_at": now,
        "updated_at": now,
        "view_count": 0,
    })
    if payload.status == "published" and not payload.published_at:
        doc["published_at"] = now
    r = await db.articles.insert_one(doc)
    doc["_id"] = r.inserted_id
    await _sync_article_calendar(db, doc, admin)
    return _serialize_article(doc)


@router.put("/admin/articles/{aid}")
async def admin_article_update(aid: str, payload: m.ArticleIn,
                               admin=Depends(get_current_kb_author)):
    db = await _get_db()
    existing = await db.articles.find_one({"_id": _oid(aid)})
    if not existing:
        raise HTTPException(status_code=404, detail="Article not found")
    # Support may only edit KB articles, and cannot change a KB article to blog.
    if admin.get("role") == "support":
        if existing.get("type", "blog") != "kb" or payload.type != "kb":
            raise HTTPException(status_code=403, detail="Support may only edit knowledge-base articles")
    upd = payload.model_dump()
    upd["body_html"] = _sanitize_article_html(upd.get("body_html", ""))
    upd["tags"] = _norm_tags(payload.tags)
    upd["meta_keywords"] = _norm_tags(payload.meta_keywords)
    upd["updated_at"] = _now()
    # slug: only regenerate if changed or blank
    incoming_slug = payload.slug or payload.title
    if _slugify(incoming_slug) != existing.get("slug"):
        upd["slug"] = await _unique_slug(db, incoming_slug, ignore_id=aid)
    else:
        upd["slug"] = existing["slug"]
    # First-publish → stamp published_at
    if payload.status == "published" and not existing.get("published_at") and not payload.published_at:
        upd["published_at"] = _now()
    await db.articles.update_one({"_id": _oid(aid)}, {"$set": upd})
    d2 = await db.articles.find_one({"_id": _oid(aid)})
    await _sync_article_calendar(db, d2, admin)
    return _serialize_article(d2)


@router.delete("/admin/articles/{aid}")
async def admin_article_delete(aid: str, admin=Depends(get_current_kb_author)):
    db = await _get_db()
    existing = await db.articles.find_one({"_id": _oid(aid)})
    if not existing:
        raise HTTPException(status_code=404, detail="Article not found")
    if admin.get("role") == "support":
        raise HTTPException(status_code=403, detail="Support cannot delete articles")
    r = await db.articles.delete_one({"_id": _oid(aid)})
    return {"deleted": r.deleted_count}


@router.get("/admin/articles-tags")
async def admin_articles_tags(staff=Depends(get_current_staff)):
    """Return all tags used across articles with a count (for suggestions)."""
    db = await _get_db()
    pipeline = [
        {"$unwind": "$tags"},
        {"$group": {"_id": "$tags", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
    ]
    rows = await db.articles.aggregate(pipeline).to_list(500)
    return [{"tag": r["_id"], "count": r["count"]} for r in rows]


# ---- Public endpoints (unauthenticated) ----
@router.get("/public/articles")
async def public_articles_list(q: str = "", tag: str = "",
                               type: str = "blog",
                               limit: int = 24, skip: int = 0):
    db = await _get_db()
    await _ensure_article_indexes(db)
    filt: dict = {"status": "published"}
    if type in ("blog", "kb"):
        filt["type"] = type
    if tag:
        filt["tags"] = _slugify(tag)
    projection = None
    sort = [("published_at", -1)]
    if q:
        filt["$text"] = {"$search": q}
        projection = {"score": {"$meta": "textScore"}}
        sort = [("score", {"$meta": "textScore"}), ("published_at", -1)]
    cursor = db.articles.find(filt, projection).sort(sort).skip(max(0, skip)).limit(max(1, min(limit, 100)))
    docs = await cursor.to_list(200)
    total = await db.articles.count_documents(filt)
    return {
        "total": total,
        "count": len(docs),
        "results": [_serialize_article(d, include_body=False) for d in docs],
    }


@router.get("/public/articles/tags")
async def public_articles_tags():
    """Return every tag that appears on at least one published article."""
    db = await _get_db()
    pipeline = [
        {"$match": {"status": "published"}},
        {"$unwind": "$tags"},
        {"$group": {"_id": "$tags", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
    ]
    rows = await db.articles.aggregate(pipeline).to_list(500)
    return [{"tag": r["_id"], "count": r["count"]} for r in rows]


@router.get("/public/articles/{slug}")
async def public_article_detail(slug: str):
    db = await _get_db()
    d = await db.articles.find_one({"slug": slug, "status": "published"})
    if not d:
        raise HTTPException(status_code=404, detail="Article not found")
    # Track a view; ignore if it fails.
    try:
        await db.articles.update_one({"_id": d["_id"]}, {"$inc": {"view_count": 1}})
    except Exception:
        pass
    d["view_count"] = int(d.get("view_count", 0)) + 1
    # Sibling: 3 most recent published, excluding this one.
    related_cursor = db.articles.find(
        {"status": "published", "_id": {"$ne": d["_id"]},
         **({"tags": {"$in": d.get("tags", [])}} if d.get("tags") else {})},
    ).sort("published_at", -1).limit(3)
    related = [_serialize_article(x, include_body=False) for x in await related_cursor.to_list(3)]
    return {"article": _serialize_article(d), "related": related}


# ============================================================
# Sitemap - dynamic XML for search engines
# ============================================================
_SITEMAP_STATIC_ROUTES = [
    ("", "1.0", "daily"),                # /
    ("articles", "0.9", "daily"),         # /articles
    ("status", "0.5", "hourly"),          # /status - public uptime page
    ("legal/terms", "0.3", "yearly"),
    ("legal/aup", "0.3", "yearly"),
    ("legal/sla", "0.3", "yearly"),
]


_SITEMAP_ORIGINS = ("https://intercloud-digital.com",)


@router.get("/sitemap.xml", include_in_schema=False)
@_rl_limiter.limit(PUBLIC_STATUS_LIMIT)
async def sitemap_xml(request: Request):
    """Serve a Google-friendly sitemap covering static routes + all
    published articles. Cache-friendly (5-min public cache)."""
    from fastapi.responses import Response as _R
    db = await _get_db()
    origin = _SITEMAP_ORIGINS[0]
    urls: list[str] = []

    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    for path, prio, freq in _SITEMAP_STATIC_ROUTES:
        loc = f"{origin}/{path}" if path else f"{origin}/"
        urls.append(
            "  <url>\n"
            f"    <loc>{loc}</loc>\n"
            f"    <lastmod>{now_iso}</lastmod>\n"
            f"    <changefreq>{freq}</changefreq>\n"
            f"    <priority>{prio}</priority>\n"
            "  </url>"
        )

    # Published articles
    try:
        cur = db.articles.find({"status": "published"},
                               {"slug": 1, "updated_at": 1, "published_at": 1}
                               ).sort("published_at", -1).limit(5000)
        async for row in cur:
            slug = row.get("slug")
            if not slug:
                continue
            lm = row.get("updated_at") or row.get("published_at") or ""
            lm = (str(lm)[:10]) or now_iso
            urls.append(
                "  <url>\n"
                f"    <loc>{origin}/articles/{slug}</loc>\n"
                f"    <lastmod>{lm}</lastmod>\n"
                "    <changefreq>weekly</changefreq>\n"
                "    <priority>0.7</priority>\n"
                "  </url>"
            )
    except Exception as e:
        logging.getLogger("portal.sitemap").warning(f"sitemap articles fetch failed: {e}")

    body = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + "\n".join(urls) +
        "\n</urlset>\n"
    )
    return _R(content=body, media_type="application/xml",
              headers={"Cache-Control": "public, max-age=300"})


# ============================================================
# SEO - dynamic rendering for crawlers / link-preview bots
# ============================================================
# Non-JS crawlers (WhatsApp/Telegram/Facebook/Twitter/Slack/Discord link
# unfurlers and some search bots) never execute the SPA, so per-article
# meta tags set client-side are invisible to them. nginx rewrites bot
# requests for /articles/<slug> to this endpoint (see install.sh).
@router.get("/seo/render/articles/{slug}", include_in_schema=False)
@_rl_limiter.limit(PUBLIC_STATUS_LIMIT)
async def seo_render_article(slug: str, request: Request):
    import html as _html
    import json as _json
    db = await _get_db()
    a = await db.articles.find_one({"slug": slug, "status": "published"})
    if not a:
        raise HTTPException(status_code=404, detail="Article not found")
    origin = _SITEMAP_ORIGINS[0]
    title = (a.get("meta_title") or a.get("title") or "").strip()
    desc = (a.get("meta_description") or a.get("excerpt") or "").strip()[:300]
    image = a.get("og_image_url") or a.get("cover_image_url") or f"{origin}/og-image.png"
    canonical = f"{origin}/articles/{slug}"
    ld = _json.dumps({
        "@context": "https://schema.org",
        "@type": "Article",
        "headline": a.get("title") or title,
        "description": desc,
        "image": [image],
        "datePublished": a.get("published_at") or "",
        "dateModified": a.get("updated_at") or "",
        "author": {"@type": "Organization",
                    "name": a.get("author_name") or "PT Intercloud Digital Inovasi"},
        "publisher": {"@type": "Organization",
                       "name": "PT Intercloud Digital Inovasi",
                       "logo": {"@type": "ImageObject", "url": f"{origin}/og-logo.png"}},
        "mainEntityOfPage": canonical,
    }, ensure_ascii=False)
    e = _html.escape
    body_html = f"""<!doctype html>
<html lang="id"><head>
<meta charset="utf-8">
<title>{e(title)} - Intercloud</title>
<meta name="description" content="{e(desc)}">
<link rel="canonical" href="{e(canonical)}">
<meta property="og:type" content="article">
<meta property="og:title" content="{e(title)}">
<meta property="og:description" content="{e(desc)}">
<meta property="og:image" content="{e(image)}">
<meta property="og:url" content="{e(canonical)}">
<meta property="og:site_name" content="PT. Intercloud Digital Inovasi">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{e(title)}">
<meta name="twitter:description" content="{e(desc)}">
<meta name="twitter:image" content="{e(image)}">
<script type="application/ld+json">{ld}</script>
</head><body>
<h1>{e(a.get('title') or title)}</h1>
<p>{e(desc)}</p>
<a href="{e(canonical)}">Baca artikel lengkap di intercloud-digital.com</a>
</body></html>"""
    return HTMLResponse(content=body_html,
                        headers={"Cache-Control": "public, max-age=300"})


# ============================================================
# PUBLIC STATUS PAGE
# ============================================================
_DEFAULT_STATUS_GROUPS = [
    {"key": "core_network",  "label": "Core Network"},
    {"key": "customer_edge", "label": "Customer Edge"},
    {"key": "peering",       "label": "Peering & Transit"},
]


@router.get("/public/status")
@_rl_limiter.limit(PUBLIC_STATUS_LIMIT)
async def public_status_page(request: Request):
    """Customer-friendly uptime snapshot with NO device names/IPs leaked.

    Devices are bucketed by their `status_group` field (default:
    customer_edge). Which groups are visible + their display labels come
    from `settings.status_page.groups`; falls back to defaults."""
    db = await _get_db()
    doc = await db.settings.find_one({"key": "status_page"}) or {}
    cfg = doc.get("value") or {}
    groups = cfg.get("groups") or _DEFAULT_STATUS_GROUPS
    company = cfg.get("company") or "Intercloud Digital Inovasi"
    incident_note = cfg.get("incident_note") or ""

    devices = await db.mikrotik_devices.find({}, {"status_group": 1}).to_list(1000)
    dev_group: dict = {d["_id"]: (d.get("status_group") or "customer_edge") for d in devices}

    now = datetime.now(timezone.utc)
    since_24h = (now - timedelta(hours=24)).isoformat()

    out_groups = []
    any_degraded = False
    any_operational = False
    for grp in groups:
        gkey = grp["key"]
        dev_ids = [did for did, gk in dev_group.items() if gk == gkey]
        base = {"device_id": {"$in": dev_ids}} if dev_ids else {"device_id": None}
        total = await db.noc_probes.count_documents({**base, "at": {"$gte": since_24h}})
        up = await db.noc_probes.count_documents({**base, "at": {"$gte": since_24h}, "ok": True})
        uptime_24h = round((up / total) * 100, 2) if total else None
        # 30d window uses daily rollups + recent raw samples (retention-safe)
        uptime_30d = await _noc_uptime_window(db, dev_ids if dev_ids else [None], 30)
        down_now = await db.noc_device_state.count_documents({
            "device_id": {"$in": dev_ids}, "status": "down",
        }) if dev_ids else 0
        if uptime_24h is None:
            status = "unknown"
        elif down_now > 0:
            status = "degraded"; any_degraded = True
        elif uptime_24h >= 99.0:
            status = "operational"; any_operational = True
        else:
            status = "degraded"; any_degraded = True
        out_groups.append({
            "key": gkey, "label": grp["label"],
            "status": status,
            "uptime_24h_pct": uptime_24h,
            "uptime_30d_pct": uptime_30d,
            "devices_count": len(dev_ids),
        })
    # Overall: degraded takes precedence; otherwise operational only if at
    # least one group is genuinely operational; else unknown.
    if any_degraded:
        overall_status = "degraded"
    elif any_operational:
        overall_status = "operational"
    else:
        overall_status = "unknown"
    return {
        "company": company,
        "generated_at": now.isoformat(),
        "overall_status": overall_status,
        "groups": out_groups,
        "incident_note": incident_note,
    }


@router.get("/admin/status-page/config")
async def status_page_config_get(admin=Depends(get_current_admin)):
    db = await _get_db()
    doc = await db.settings.find_one({"key": "status_page"}) or {}
    return doc.get("value") or {"groups": _DEFAULT_STATUS_GROUPS,
                                 "company": "Intercloud Digital Inovasi",
                                 "incident_note": ""}


@router.put("/admin/status-page/config")
async def status_page_config_put(payload: dict, request: Request, admin=Depends(get_current_admin)):
    db = await _get_db()
    before_doc = await db.settings.find_one({"key": "status_page"}) or {}
    value = {
        "groups": payload.get("groups") or _DEFAULT_STATUS_GROUPS,
        "company": (payload.get("company") or "Intercloud Digital Inovasi").strip(),
        "incident_note": (payload.get("incident_note") or "").strip(),
    }
    await db.settings.update_one({"key": "status_page"},
                                 {"$set": {"key": "status_page", "value": value,
                                           "updated_at": _now()}}, upsert=True)
    await log_audit(db, actor=admin, action="status_page.config_update", category="system",
                    target_type="settings", target_label="Status Page",
                    before=before_doc.get("value"), after=value,
                    severity="info", request=request)
    return value
