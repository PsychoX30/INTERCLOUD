"""CVE Intelligence Hub - public + admin API surface.

Public (unauthenticated, rate limited):
    GET  /api/portal/public/cve                     list + filter + sort + paging
    GET  /api/portal/public/cve/stats               card counters + last-sync stamp
    GET  /api/portal/public/cve/{cve_id}            one entry with full references
    GET  /api/portal/public/cve-sitemap.xml         sitemap fragment for crawlers

Admin (staff):
    GET  /api/portal/admin/cve/sync-status          cursor, counts, last error
    POST /api/portal/admin/cve/sync                 run one sync batch now
    POST /api/portal/admin/cve/sync/rebuild         reset the cursor, keep documents
"""
import html
import logging
import re
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from ..auth import get_current_staff
from ..security import PUBLIC_STATUS_LIMIT
from ..security import limiter as _rl_limiter
from .shared import _get_db
from .. import cve_tracker as ct

log = logging.getLogger("cve_routes")

router = APIRouter()

_CVE_ID_RE = re.compile(r"^CVE-\d{4}-\d{4,}$", re.IGNORECASE)


@router.get("/public/cve/stats")
@_rl_limiter.limit(PUBLIC_STATUS_LIMIT)
async def public_cve_stats(request: Request, days: int = Query(7, ge=1, le=90)):
    """Card counters for the hub header (Critical/High/Medium/Total + trend)."""
    db = await _get_db()
    return await ct.summary_stats(db, days=days)


@router.get("/public/cve")
@_rl_limiter.limit(PUBLIC_STATUS_LIMIT)
async def public_cve_list(
    request: Request,
    severity: str = Query("", max_length=20),
    q: str = Query("", max_length=120),
    days: int = Query(0, ge=0, le=3650),
    sort: str = Query("newest", max_length=20),
    limit: int = Query(24, ge=1, le=100),
    skip: int = Query(0, ge=0, le=100_000),
    has_exploit: bool = Query(False),
):
    """Paged CVE feed. Mirrors the reference hub: severity filter, three sorts,
    Load-More paging via ``skip``."""
    db = await _get_db()
    await ct.ensure_indexes(db)
    return await ct.list_cves(
        db, severity=severity, q=q, days=days, sort=sort,
        limit=limit, skip=skip, has_exploit=has_exploit,
    )


@router.get("/public/cve-sitemap.xml", include_in_schema=False)
@_rl_limiter.limit(PUBLIC_STATUS_LIMIT)
async def public_cve_sitemap(request: Request, limit: int = Query(2000, ge=1, le=5000)):
    """Standalone sitemap so crawlers can index the new entries individually."""
    from fastapi.responses import Response as _R
    db = await _get_db()
    origin = "https://intercloud-digital.com"
    rows = await db[ct.COLLECTION].find(
        {"published": {"$ne": None}}, {"cve_id": 1, "last_modified": 1}
    ).sort("published", -1).limit(limit).to_list(limit)
    items = [
        "  <url>\n"
        f"    <loc>{origin}/cve/{r['cve_id']}</loc>\n"
        f"    <lastmod>{(r.get('last_modified') or r.get('published')).strftime('%Y-%m-%d') if (r.get('last_modified') or r.get('published')) else ''}</lastmod>\n"
        "    <changefreq>weekly</changefreq>\n"
        "    <priority>0.4</priority>\n"
        "  </url>"
        for r in rows
    ]
    body = ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
            + "\n".join(items) + "\n</urlset>\n")
    return _R(content=body, media_type="application/xml",
              headers={"Cache-Control": "public, max-age=1800"})


@router.get("/public/cve/{cve_id}")
@_rl_limiter.limit(PUBLIC_STATUS_LIMIT)
async def public_cve_detail(request: Request, cve_id: str):
    cid = (cve_id or "").strip()
    if not _CVE_ID_RE.match(cid):
        raise HTTPException(status_code=400, detail="Format CVE harus CVE-YYYY-NNNN")
    db = await _get_db()
    doc = await ct.get_cve(db, cid)
    if not doc:
        raise HTTPException(status_code=404, detail="CVE tidak ditemukan")
    return doc


# ---------------------------------------------------------------- admin ----
@router.get("/admin/cve/sync-status")
async def admin_cve_sync_status(staff=Depends(get_current_staff)):
    db = await _get_db()
    state = await ct.get_sync_state(db)
    stored = int(await db[ct.COLLECTION].estimated_document_count())
    return {
        "stored_total": stored,
        "total_available": int(state.get("total_results") or 0),
        "cursor": int(state.get("start_index") or 0),
        "last_run_at": ct._dt_iso(state.get("last_run_at")),
        "last_completed_at": ct._dt_iso(state.get("last_completed_at")),
        "last_run_pages": state.get("last_run_pages"),
        "last_run_written": state.get("last_run_written"),
        "last_run_seconds": state.get("last_run_seconds"),
        "last_error": state.get("last_error") or "",
        "bootstrap_done": bool(state.get("bootstrap_done")),
    }


@router.post("/admin/cve/sync")
async def admin_cve_sync(staff=Depends(get_current_staff),
                         max_pages: int = Query(2, ge=1, le=10)):
    """Run a short sync batch on demand (the scheduler does the long runs)."""
    db = await _get_db()
    await ct.ensure_indexes(db)
    return await ct.run_cve_sync(db, max_pages=max_pages)


@router.post("/admin/cve/sync/rebuild")
async def admin_cve_rebuild(staff=Depends(get_current_staff)):
    """Reset the NVD cursor to 0. Documents are kept; the next sync re-walks
    the catalogue from the newest entry."""
    db = await _get_db()
    state = await ct.get_sync_state(db)
    state["start_index"] = 0
    await db[ct.SYNC_COLLECTION].update_one(
        {"_id": ct.SYNC_STATE_KEY},
        {"$set": {"state": state}},
        upsert=True,
    )
    return {"ok": True, "cursor": 0, "stored_total":
            int(await db[ct.COLLECTION].estimated_document_count())}


# ------------------------------------------------- CVE -> article ----
_CVE_SEVERITY_LABEL = {
    "critical": "Kritis", "high": "Tinggi", "medium": "Sedang",
    "low": "Rendah", "unknown": "Belum dinilai",
}


def _esc(text: str) -> str:
    return html.escape(str(text or ""), quote=True)


def _cve_article_body(doc: dict) -> str:
    """Build publishable article HTML from a stored CVE document.

    Every field is escaped: NVD descriptions routinely contain vendor-supplied
    markup (``<script>`` in a product name is not theoretical), and this HTML
    is rendered to the public site.
    """
    cve_id = _esc(doc.get("cve_id") or doc.get("_id"))
    severity = (doc.get("severity") or "unknown").lower()
    sev_label = _CVE_SEVERITY_LABEL.get(severity, severity)
    score = doc.get("cvss_score")
    vector = _esc(doc.get("cvss_vector") or "")
    published = doc.get("published")
    pub_txt = published.strftime("%d %B %Y") if hasattr(published, "strftime") else ""

    parts = [
        f"<p><strong>{cve_id}</strong> adalah kerentanan yang terdaftar di NVD"
        + (f" dengan tingkat keparahan <strong>{sev_label}</strong>" if severity != "unknown" else "")
        + (f" (CVSS {score})" if score is not None else "")
        + (f", dipublikasikan {pub_txt}" if pub_txt else "")
        + ".</p>",
    ]

    desc = (doc.get("description") or "").strip()
    if desc:
        parts.append("<h2>Ringkasan</h2>")
        parts.append(f"<p>{_esc(desc)}</p>")

    if score is not None or vector:
        parts.append("<h2>Penilaian</h2>")
        parts.append("<ul>")
        parts.append(f"<li>Keparahan: <strong>{_esc(sev_label)}</strong></li>")
        if score is not None:
            parts.append(f"<li>Skor CVSS: <strong>{_esc(score)}</strong></li>")
        if vector:
            parts.append(f"<li>Vektor: <code>{vector}</code></li>")
        cwes = doc.get("cwes") or []
        if cwes:
            parts.append(f"<li>CWE: {_esc(', '.join(str(c) for c in cwes))}</li>")
        parts.append("</ul>")

    products = [p for p in (doc.get("products") or []) if p][:20]
    if products:
        parts.append("<h2>Produk terdampak</h2>")
        parts.append("<ul>" + "".join(f"<li>{_esc(p)}</li>" for p in products) + "</ul>")

    refs = [r for r in (doc.get("references") or []) if r.get("url")][:15]
    if refs:
        parts.append("<h2>Referensi</h2>")
        items = []
        for r in refs:
            host = _esc(r.get("host") or r["url"])
            items.append(
                f'<li><a href="{_esc(r["url"])}" rel="noopener nofollow" '
                f'target="_blank">{host}</a></li>'
            )
        parts.append("<ul>" + "".join(items) + "</ul>")

    parts.append(
        "<hr/><p><em>Ringkasan ini disusun otomatis dari data NVD. "
        "Selalu rujuk sumber resmi sebelum mengambil tindakan.</em></p>"
    )
    return "".join(parts)


@router.post("/admin/cve/{cve_id}/publish-article")
async def admin_cve_publish_article(cve_id: str, payload: dict | None = None,
                                    staff=Depends(get_current_staff)):
    """Turn one stored CVE into a blog article in a single call.

    Without this, publishing meant copying the CVE by hand into the article
    editor — slow, and the links are long enough that transcriptions rot. The
    body is generated from the stored document; the caller may override the
    title, excerpt, and status.
    """
    db = await _get_db()
    cid = (cve_id or "").strip().upper()
    if not _CVE_ID_RE.match(cid):
        raise HTTPException(status_code=400, detail="Format CVE harus CVE-YYYY-NNNN")
    doc = await ct.get_cve(db, cid)
    if not doc:
        raise HTTPException(status_code=404, detail="CVE tidak ditemukan")

    payload = payload or {}
    sev_label = _CVE_SEVERITY_LABEL.get((doc.get("severity") or "unknown").lower(), "Belum dinilai")
    score = doc.get("cvss_score")
    score_txt = f" (CVSS {score})" if score is not None else ""
    default_title = f"{cid}: kerentanan {sev_label}{score_txt} — apa yang perlu Anda lakukan"

    title = (payload.get("title") or default_title).strip()[:240]
    excerpt = (payload.get("excerpt") or (doc.get("description") or ""))[:500]
    status = payload.get("status") or "draft"
    if status not in ("draft", "published"):
        raise HTTPException(status_code=400, detail="status harus draft atau published")

    # Re-publishing the same CVE must not create a second article; update the
    # existing one instead so the slug stays stable for SEO.
    cve_tag = cid.lower()
    existing = await db.articles.find_one({"cve_id": cid})

    body_html = _cve_article_body(doc)
    tags = sorted({cve_tag, "cve", "keamanan",
                   (doc.get("severity") or "unknown").lower()})
    now = datetime.now(timezone.utc).isoformat()

    fields = {
        "title": title,
        "excerpt": excerpt,
        "body_html": body_html,
        "type": "blog",
        "status": status,
        "tags": tags,
        "cve_id": cid,
        "meta_title": title[:70],
        "meta_description": excerpt[:160],
        "meta_keywords": tags,
        "updated_at": now,
    }
    if status == "published" and not (existing or {}).get("published_at"):
        fields["published_at"] = now

    if existing:
        await db.articles.update_one({"_id": existing["_id"]}, {"$set": fields})
        aid = existing["_id"]
        slug = existing.get("slug") or ""
        action = "updated"
    else:
        from .cms import _unique_slug  # local import: avoids a cycle at module load
        slug = await _unique_slug(db, f"cve-{cve_tag}-ringkasan")
        fields.update({
            "slug": slug,
            "author_name": staff.get("name") or staff.get("email") or "Security Desk",
            "created_at": now,
            "view_count": 0,
        })
        r = await db.articles.insert_one(fields)
        aid = r.inserted_id
        action = "created"

    return {
        "ok": True,
        "action": action,
        "article_id": str(aid),
        "status": status,
        "title": title,
        "slug": slug,
        "url": f"/artikel/{slug}",
        "cve_id": cid,
    }
