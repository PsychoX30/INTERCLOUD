"""CVE tracker - NVD API 2.0 ingestion, storage and query engine.

Design notes
------------
* NVD API 2.0 caps ``resultsPerPage`` at 2000 and throttles un-keyed clients
  to 5 requests / 30 s.  The sync loop therefore sleeps ``_THROTTLE_S`` between
  page fetches, retries on 403/429/503 with exponential backoff, and applies
  ``NVD_API_KEY`` (6 s pause instead of 7 s) when configured.
* Schema mirrors the NVD JSON so nothing is lost.  The document ``_id`` is the
  CVE id itself (``CVE-2024-1234``) which makes upserts idempotent and gives us
  a free unique index.
* Sync state lives in ``settings`` under ``key="_id": "cve_sync"`` so the
  background scheduler and the manual "Sync now" button share one cursor.
* A sync that has stored nothing yet lands in a *bootstrap* phase: it walks
  the newest CVEs first (startIndex 0) so the public page is useful after a
  few seconds, and only then sweeps the remainder of the catalogue.

Pure-stdlib parsing helpers live at module level so they can be unit-tested
without a database (see tests/test_cve_tracker.py).
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Optional

log = logging.getLogger("cve_tracker")

NVD_BASE = "https://services.nvd.nist.gov/rest/json/cves/2.0"
PAGE_SIZE = 2000                 # NVD hard maximum for resultsPerPage
MAX_PAGES_PER_RUN = 40           # one scheduled run never exceeds ~80k CVEs
BOOTSTRAP_BUDGET = 60_000        # newest CVEs worth keeping in the hot window
THROTTLE_S = 7.0                 # un-keyed NVD limit is 5 req / 30 s
THROTTLE_KEYED_S = 1.0
REQUEST_TIMEOUT_S = 45.0
MAX_RETRIES = 4
# NOTE: `settings` carries a UNIQUE index on `key` (and the existing rows have
# no `key` field at all, so any new doc without one collides on null). The sync
# cursor therefore lives in its own dedicated collection.
SYNC_COLLECTION = "cve_sync_state"
SYNC_STATE_KEY = "nvd"
COLLECTION = "cve_entries"
NEW_BADGE_HOURS = 24
STATS_DAYS = 7

SEVERITY_ORDER = ["critical", "high", "medium", "low", "none"]

_ID_RE = re.compile(r"^CVE-\d{4}-\d{4,}$", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Parsing helpers (pure - no I/O, unit-testable)
# ---------------------------------------------------------------------------
def parse_nvd_dt(value: Optional[str]) -> Optional[datetime]:
    """NVD timestamps look like ``2024-01-02T03:04:05.123`` (no timezone).

    They are UTC by contract.  Returns a tz-aware UTC datetime or None.
    """
    if not value or not isinstance(value, str):
        return None
    txt = value.strip().replace("Z", "")
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(txt, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _cvss_from_block(block: dict) -> Optional[dict]:
    """Turn one ``cvssMetricVxx`` entry into a flat dict."""
    if not isinstance(block, dict):
        return None
    data = block.get("cvssData") or {}
    score = data.get("baseScore")
    if score is None:
        return None
    try:
        score = float(score)
    except (TypeError, ValueError):
        return None
    sev = (data.get("baseSeverity") or block.get("baseSeverity") or "").strip().lower()
    return {
        "version": data.get("version") or "",
        "source": block.get("source") or "",
        "type": block.get("type") or "",
        "score": round(score, 1),
        "severity": sev,
        "vector": data.get("vectorString") or "",
        "attack_vector": data.get("attackVector") or "",
        "attack_complexity": data.get("attackComplexity") or "",
        "privileges_required": data.get("privilegesRequired") or "",
        "user_interaction": data.get("userInteraction") or "",
        "confidentiality": data.get("confidentialityImpact") or "",
        "integrity": data.get("integrityImpact") or "",
        "availability": data.get("availabilityImpact") or "",
    }


def _pick_primary_cvss(metrics: dict) -> tuple[Optional[dict], Optional[dict]]:
    """Return (primary, secondary) CVSS records.

    Preference order: v4.0 -> v3.1 -> v3.0 -> v2.  Within a version the NVD
    ("Primary") source wins over CNA ("Secondary"), and the highest score wins
    otherwise.  The secondary slot carries the best *remaining* record so the
    UI can show both an NVD score and a vendor score.
    """
    flat: list[dict] = []
    for key in ("cvssMetricV40", "cvssMetricV31", "cvssMetricV30", "cvssMetricV2"):
        for block in metrics.get(key) or []:
            parsed = _cvss_from_block(block)
            if parsed:
                flat.append(parsed)
    if not flat:
        return None, None

    def rank(rec: dict) -> tuple:
        ver = {"4.0": 4, "3.1": 3, "3.0": 2, "2.0": 1}.get(rec["version"], 0)
        is_nvd = 1 if rec["type"].lower() == "primary" else 0
        return (ver, is_nvd, rec["score"])

    flat.sort(key=rank, reverse=True)
    primary = flat[0]
    secondary = None
    for rec in flat[1:]:
        # Only a CVSS of a different provenance adds signal.
        if rec["source"] != primary["source"]:
            secondary = rec
            break
    return primary, secondary


def _cwes(weaknesses: Iterable[dict]) -> list[str]:
    out: list[str] = []
    for w in weaknesses or []:
        for d in (w or {}).get("description") or []:
            val = (d or {}).get("value") or ""
            if val.startswith("CWE-") and val not in out:
                out.append(val)
    return out


def _reference_host(url: str) -> str:
    try:
        return urllib.parse.urlparse(url).hostname or ""
    except Exception:  # noqa: BLE001 - malformed refs are common in NVD
        return ""


def _product_tokens(configurations: Iterable[dict]) -> list[str]:
    """Extract ``vendor:product`` pairs from the CPE match list."""
    tokens: list[str] = []
    for node in configurations or []:
        for match in (node or {}).get("nodes") or []:
            for cpe in (match or {}).get("cpeMatch") or []:
                crit = (cpe or {}).get("criteria") or ""
                parts = crit.split(":")
                # cpe:2.3:part:vendor:product:version:...
                if len(parts) >= 5 and parts[3] not in ("*", "-", ""):
                    tok = f"{parts[3]}:{parts[4]}"
                    if tok not in tokens:
                        tokens.append(tok)
                if len(tokens) >= 12:
                    return tokens
    return tokens


def transform_nvd_vulnerability(entry: dict, fetched_at: Optional[datetime] = None) -> Optional[dict]:
    """Map one ``{"cve": {...}}`` object from NVD onto our storage shape."""
    cve = (entry or {}).get("cve") or {}
    cve_id = (cve.get("id") or "").strip().upper()
    if not _ID_RE.match(cve_id):
        return None

    desc = ""
    for d in cve.get("descriptions") or []:
        if (d or {}).get("lang") == "en":
            desc = (d.get("value") or "").strip()
            break
    if not desc:
        for d in cve.get("descriptions") or []:
            if (d or {}).get("value"):
                desc = (d["value"] or "").strip()
                break

    primary, secondary = _pick_primary_cvss(cve.get("metrics") or {})
    severity = (primary or {}).get("severity") or "unknown"
    score = (primary or {}).get("score")
    if score is None and secondary:
        severity = secondary.get("severity") or severity
        score = secondary.get("score")

    refs = []
    for r in cve.get("references") or []:
        url = (r or {}).get("url")
        if not url:
            continue
        refs.append({
            "url": url,
            "source": (r.get("source") or ""),
            "tags": list(r.get("tags") or []),
            "host": _reference_host(url),
        })
        if len(refs) >= 30:
            break

    published = parse_nvd_dt(cve.get("published"))
    modified = parse_nvd_dt(cve.get("lastModified"))
    now = fetched_at or datetime.now(timezone.utc)

    return {
        "_id": cve_id,
        "cve_id": cve_id,
        "description": desc,
        "published": published,
        "last_modified": modified,
        "vuln_status": cve.get("vulnStatus") or "",
        "source_identifier": cve.get("sourceIdentifier") or "",
        "severity": severity if severity in SEVERITY_ORDER else "unknown",
        "cvss_score": score,
        "cvss_version": (primary or {}).get("version") or "",
        "cvss_vector": (primary or {}).get("vector") or "",
        "cvss_source": (primary or {}).get("source") or "",
        "cvss_secondary": secondary,
        "cvss_all": [r for r in (primary, secondary) if r],
        "cwes": _cwes(cve.get("weaknesses") or []),
        "products": _product_tokens(cve.get("configurations") or []),
        "references": refs,
        "has_exploit_ref": any(
            "Exploit" in (r.get("tags") or []) or "Third Party Advisory" in (r.get("tags") or [])
            for r in refs
        ),
        "fetched_at": now,
    }


# ---------------------------------------------------------------------------
# HTTP layer
# ---------------------------------------------------------------------------
def _nvd_get(params: dict, api_key: str = "") -> dict:
    url = f"{NVD_BASE}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": "INTERCLOUD-CVE-Tracker/1.0"})
    if api_key:
        req.add_header("apiKey", api_key)
    with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_S) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


async def _fetch_page(params: dict, api_key: str = "") -> dict:
    """Blocking NVD call executed on a worker thread with retry/backoff."""
    delay = THROTTLE_S
    last_err: Optional[Exception] = None
    for attempt in range(MAX_RETRIES):
        try:
            return await asyncio.to_thread(_nvd_get, params, api_key)
        except urllib.error.HTTPError as e:
            last_err = e
            if e.code in (403, 429, 503):
                wait = delay * (2 ** attempt)
                log.warning("NVD %s on %s, backing off %.0fs", e.code, params, wait)
                await asyncio.sleep(wait)
                continue
            raise
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            last_err = e
            await asyncio.sleep(delay * (2 ** attempt))
    raise RuntimeError(f"NVD fetch failed after {MAX_RETRIES} attempts: {last_err}")


# ---------------------------------------------------------------------------
# Storage helpers
# ---------------------------------------------------------------------------
async def ensure_indexes(db) -> None:
    coll = db[COLLECTION]
    await coll.create_index("published")
    await coll.create_index("severity")
    await coll.create_index("cvss_score")
    await coll.create_index("fetched_at")
    await coll.create_index([("description", "text"), ("cve_id", "text")],
                            name="cve_text", default_language="none",
                            weights={"description": 1, "cve_id": 10})

async def get_sync_state(db) -> dict:
    doc = await db[SYNC_COLLECTION].find_one({"_id": SYNC_STATE_KEY}) or {}
    return doc.get("state") if isinstance(doc.get("state"), dict) else {}


async def _save_sync_state(db, state: dict) -> None:
    state = dict(state)
    state["updated_at"] = datetime.now(timezone.utc)
    await db[SYNC_COLLECTION].update_one(
        {"_id": SYNC_STATE_KEY},
        {"$set": {"state": state, "updated_at": state["updated_at"]}},
        upsert=True,
    )


async def _upsert_entries(db, docs: list[dict]) -> int:
    if not docs:
        return 0
    from pymongo import ReplaceOne
    ops = [ReplaceOne({"_id": d["_id"]}, d, upsert=True) for d in docs]
    res = await db[COLLECTION].bulk_write(ops, ordered=False)
    return int(getattr(res, "upserted_count", 0) or 0) + int(getattr(res, "modified_count", 0) or 0)


# ---------------------------------------------------------------------------
# Sync engine
# ---------------------------------------------------------------------------
async def run_cve_sync(db, *, max_pages: int = MAX_PAGES_PER_RUN,
                       force_restart: bool = False) -> dict:
    """Advance the NVD cursor by at most ``max_pages`` pages.

    Progress is persisted after every page, so a crash or a restart resumes
    exactly where the previous run stopped.  ``force_restart`` wipes the
    cursor (used by the admin "Rebuild index" action) but keeps the documents.
    """
    import os
    api_key = os.environ.get("NVD_API_KEY", "").strip()
    pause = THROTTLE_KEYED_S if api_key else THROTTLE_S

    state = await get_sync_state(db)
    start = 0 if force_restart else int(state.get("start_index") or 0)
    total_available = int(state.get("total_results") or 0)
    stored_total = int(await db[COLLECTION].estimated_document_count())

    started = datetime.now(timezone.utc)
    processed = 0
    written = 0
    pages = 0
    finished = False
    error = ""

    # NVD paginates in ASCENDING publication order (verified: startIndex=0 is
    # 1988, the tail is today). A forward cursor would serve 1999 entries on a
    # fresh install, so the first page of every run resolves totalResults and
    # the walk then proceeds from the tail backwards.
    if not total_available:
        try:
            probe = await _fetch_page({"resultsPerPage": 1, "startIndex": 0}, api_key)
            total_available = int(probe.get("totalResults") or 0)
            await asyncio.sleep(pause)
        except Exception as e:  # noqa: BLE001
            error = str(e)[:400]
            log.warning("[cve-sync] probe failed: %s", error)

    for page in range(max_pages):
        if total_available:
            remaining = total_available - start
            if remaining <= 0:
                finished = True
                break
            page_size = min(PAGE_SIZE, remaining)
        else:
            page_size = PAGE_SIZE
        offset = max(0, total_available - start - page_size) if total_available else 0
        params = {"resultsPerPage": page_size, "startIndex": offset}
        try:
            payload = await _fetch_page(params, api_key)
        except Exception as e:  # noqa: BLE001 - never let the scheduler die
            error = str(e)[:400]
            log.warning("[cve-sync] page fetch failed at offset=%s: %s", start, error)
            break

        total_available = int(payload.get("totalResults") or total_available or 0)
        vulns = payload.get("vulnerabilities") or []
        # Defensive: NVD is ascending, but never trust ordering for identity.
        vulns.sort(key=lambda v: ((v.get("cve") or {}).get("published") or ""), reverse=True)
        docs = []
        for v in vulns:
            doc = transform_nvd_vulnerability(v)
            if doc:
                docs.append(doc)
        written += await _upsert_entries(db, docs)
        processed += len(vulns)
        start += len(vulns)
        pages += 1

        await _save_sync_state(db, {
            "start_index": start,
            "total_results": total_available,
            "last_error": "",
            "last_page_at": datetime.now(timezone.utc),
        })

        if not vulns or (total_available and start >= total_available):
            finished = True
            break
        if page + 1 < max_pages:
            await asyncio.sleep(pause)
        if start >= BOOTSTRAP_BUDGET:
            # The hub only needs a deep recent window; do not grind the whole
            # catalogue on every install. Operators can raise this explicitly.
            break

    stored_total = int(await db[COLLECTION].estimated_document_count())
    elapsed = (datetime.now(timezone.utc) - started).total_seconds()
    state = await get_sync_state(db)
    state.update({
        "start_index": start if not finished else 0,
        "total_results": total_available,
        "last_run_at": started,
        "last_run_seconds": round(elapsed, 1),
        "last_run_pages": pages,
        "last_run_processed": processed,
        "last_run_written": written,
        "last_error": error,
        "last_completed_at": datetime.now(timezone.utc) if finished else state.get("last_completed_at"),
        "bootstrap_done": bool(state.get("bootstrap_done")) or finished or stored_total > 0,
        "stored_total": stored_total,
    })
    await _save_sync_state(db, state)
    log.info("[cve-sync] pages=%s processed=%s written=%s stored=%s cursor=%s finished=%s",
             pages, processed, written, stored_total, state["start_index"], finished)
    return {
        "pages": pages,
        "processed": processed,
        "written": written,
        "stored_total": stored_total,
        "total_available": total_available,
        "cursor": state["start_index"],
        "finished": finished,
        "elapsed_s": round(elapsed, 1),
        "error": error,
    }


# ---------------------------------------------------------------------------
# Query engine
# ---------------------------------------------------------------------------
def _since(days: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=days)


async def summary_stats(db, *, days: int = STATS_DAYS) -> dict:
    """Card counters for the public page: per-severity + total over N days."""
    coll = db[COLLECTION]
    since = _since(days)
    pipeline = [
        {"$match": {"published": {"$gte": since}}},
        {"$group": {"_id": "$severity", "n": {"$sum": 1}}},
    ]
    rows = await coll.aggregate(pipeline).to_list(20)
    by_sev = {str(r["_id"] or "unknown"): int(r["n"]) for r in rows}
    window_total = sum(by_sev.values())

    total = int(await coll.estimated_document_count())
    new_24h = await coll.count_documents({"published": {"$gte": _since(1)}})

    # Trend: today vs the day before, expressed as a delta percentage.
    today = await coll.count_documents({"published": {"$gte": _since(1)}})
    yesterday_start = _since(2)
    yesterday_end = _since(1)
    yesterday = await coll.count_documents(
        {"published": {"$gte": yesterday_start, "$lt": yesterday_end}})

    state = await get_sync_state(db)
    return {
        "counts": {sev: by_sev.get(sev, 0) for sev in SEVERITY_ORDER},
        "window_days": days,
        "window_total": window_total,
        "total": total,
        "new_24h": new_24h,
        "trend": {"today": today, "yesterday": yesterday,
                  "delta_pct": (round(((today - yesterday) / yesterday) * 100, 1)
                                if yesterday else None)},
        "last_sync_at": _dt_iso(state.get("last_run_at")),
        "last_completed_at": _dt_iso(state.get("last_completed_at")),
        "stored_total": total,
        "total_available": int(state.get("total_results") or 0),
        "last_error": state.get("last_error") or "",
    }


def _dt_iso(value: Any) -> Optional[str]:
    if isinstance(value, datetime):
        # Mongo hands back naive UTC; normalise to explicit UTC.
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat()
    if isinstance(value, str):
        return value
    return None


def build_filter(*, severity: str = "", q: str = "", days: int = 0,
                 kev_only: bool = False, has_exploit: bool = False) -> dict:
    filt: dict = {}
    sev = (severity or "").strip().lower()
    if sev and sev != "all":
        if sev == "unknown":
            filt["severity"] = {"$in": ["unknown", None]}
        elif sev in SEVERITY_ORDER:
            filt["severity"] = sev
    text = (q or "").strip()
    if text:
        if _ID_RE.match(text):
            filt["cve_id"] = text.upper()
        elif len(text) >= 2:
            # Anchored regex on the id list is far cheaper than $text for short
            # product queries; description $regex runs only after that misses.
            filt["$or"] = [
                {"cve_id": {"$regex": re.escape(text), "$options": "i"}},
                {"description": {"$regex": re.escape(text), "$options": "i"}},
                {"products": {"$regex": re.escape(text), "$options": "i"}},
            ]
    if days and days > 0:
        filt["published"] = {"$gte": _since(int(days))}
    if has_exploit:
        filt["has_exploit_ref"] = True
    if kev_only:
        filt["_id"] = {"$in": []}  # no CISA KEV feed wired yet - fail closed
    return filt


SORTS = {
    "newest": [("published", -1)],
    "severity": [("cvss_score", -1), ("published", -1)],
    "cvss": [("cvss_score", -1), ("published", -1)],
    "oldest": [("published", 1)],
}


def serialize_entry(doc: dict, *, now: Optional[datetime] = None) -> dict:
    now = now or datetime.now(timezone.utc)
    published = doc.get("published")
    is_new = False
    if isinstance(published, datetime):
        if published.tzinfo is None:
            published = published.replace(tzinfo=timezone.utc)
        is_new = (now - published) <= timedelta(hours=NEW_BADGE_HOURS)
    return {
        "cve_id": doc.get("cve_id") or doc.get("_id") or "",
        "description": doc.get("description") or "",
        "severity": doc.get("severity") or "unknown",
        "cvss_score": doc.get("cvss_score"),
        "cvss_version": doc.get("cvss_version") or "",
        "cvss_vector": doc.get("cvss_vector") or "",
        "cvss_source": doc.get("cvss_source") or "",
        "cvss_secondary": doc.get("cvss_secondary"),
        "published": _dt_iso(published),
        "last_modified": _dt_iso(doc.get("last_modified")),
        "vuln_status": doc.get("vuln_status") or "",
        "source_identifier": doc.get("source_identifier") or "",
        "cwes": list(doc.get("cwes") or []),
        "products": list(doc.get("products") or [])[:8],
        "references": list(doc.get("references") or [])[:10],
        "has_exploit_ref": bool(doc.get("has_exploit_ref")),
        "is_new": is_new,
    }


async def list_cves(db, *, severity: str = "", q: str = "", days: int = 0,
                    sort: str = "newest", limit: int = 24, skip: int = 0,
                    has_exploit: bool = False) -> dict:
    coll = db[COLLECTION]
    filt = build_filter(severity=severity, q=q, days=days, has_exploit=has_exploit)
    limit = max(1, min(int(limit or 24), 100))
    skip = max(0, int(skip or 0))
    order = SORTS.get((sort or "newest").lower(), SORTS["newest"])
    now = datetime.now(timezone.utc)
    total = await coll.count_documents(filt)
    cursor = coll.find(filt).sort(order).skip(skip).limit(limit)
    rows = await cursor.to_list(limit)
    return {
        "total": total,
        "count": len(rows),
        "skip": skip,
        "limit": limit,
        "results": [serialize_entry(r, now=now) for r in rows],
    }


async def get_cve(db, cve_id: str) -> Optional[dict]:
    doc = await db[COLLECTION].find_one({"_id": (cve_id or "").strip().upper()})
    if not doc:
        return None
    now = datetime.now(timezone.utc)
    # "Affected products" and full references are truncated by serialize_entry.
    full = dict(doc)
    out = serialize_entry(doc, now=now)
    out["references"] = list(full.get("references") or [])
    out["products"] = list(full.get("products") or [])
    out["cvss_all"] = list(full.get("cvss_all") or [])
    out["fetched_at"] = _dt_iso(full.get("fetched_at"))
    return out
