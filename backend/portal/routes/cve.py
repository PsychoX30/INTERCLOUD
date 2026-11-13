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
import logging
import re

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
