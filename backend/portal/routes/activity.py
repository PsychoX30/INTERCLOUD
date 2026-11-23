"""Activity log: catatan aktivitas/pekerjaan tim (survey, meeting, visit DC, instalasi).

Terlihat oleh semua role staff (admin panel). Tidak diekspos ke sisi client.
Modul lain (Jitsi meeting, maintenance SLA, content plan, follow-up CRM) menulis
ke koleksi ini lewat ``portal/activity_sync.py`` supaya satu baris aktivitas
mewakili satu pekerjaan nyata, bukan empat tempat berbeda.
"""
import logging
from datetime import datetime, timezone
from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from bson import ObjectId
from bson.errors import InvalidId
from pydantic import BaseModel, Field, field_validator

from ..audit import log_audit
from ..auth import get_current_staff, STAFF_ROLES
from .shared import _get_db, _now, _oid

router = APIRouter()
_log = logging.getLogger("portal.activity")

COLL = "activities"

KINDS = ("survey", "meeting", "visit_dc", "installation", "maintenance",
         "content", "followup", "other")
STATUSES = ("planned", "in_progress", "done", "cancelled")

# Sumber otomatis: aktivitas yang dibuat oleh modul lain. Baris ber-`source`
# selain "manual" tidak boleh dibuat/dihapus lewat endpoint manual, tapi tetap
# bisa di-start/end/update dari halaman Activity.
SOURCE_MANUAL = "manual"


class ActivityIn(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    kind: Literal["survey", "meeting", "visit_dc", "installation",
                  "maintenance", "content", "followup", "other"] = "other"
    description: str = ""
    location: str = ""
    scheduled_start: Optional[str] = None
    scheduled_end: Optional[str] = None
    owner_id: Optional[str] = None
    owner_name: str = ""
    status: Literal["planned", "in_progress", "done", "cancelled"] = "planned"
    notes: str = ""
    customer_id: Optional[str] = None
    customer_name: str = ""
    tags: List[str] = []

    @field_validator("title")
    @classmethod
    def _title_clean(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("title must not be blank")
        return v[:200]

    @field_validator("scheduled_start", "scheduled_end")
    @classmethod
    def _ts_clean(cls, v):
        if v in (None, ""):
            return None
        return _norm_ts(str(v))

    @field_validator("tags")
    @classmethod
    def _tags_clean(cls, v):
        out = []
        for t in v or []:
            t = str(t or "").strip()[:40]
            if t and t not in out:
                out.append(t)
        return out[:12]


class ActivityUpdate(BaseModel):
    title: Optional[str] = None
    kind: Optional[Literal["survey", "meeting", "visit_dc", "installation",
                           "maintenance", "content", "followup", "other"]] = None
    description: Optional[str] = None
    location: Optional[str] = None
    scheduled_start: Optional[str] = None
    scheduled_end: Optional[str] = None
    owner_id: Optional[str] = None
    owner_name: Optional[str] = None
    status: Optional[Literal["planned", "in_progress", "done", "cancelled"]] = None
    notes: Optional[str] = None
    customer_id: Optional[str] = None
    customer_name: Optional[str] = None
    tags: Optional[List[str]] = None

    @field_validator("title")
    @classmethod
    def _title_clean(cls, v):
        if v is None:
            return None
        v = (v or "").strip()
        if not v:
            raise ValueError("title must not be blank")
        return v[:200]

    @field_validator("scheduled_start", "scheduled_end")
    @classmethod
    def _ts_clean(cls, v):
        if v in (None, ""):
            return None
        return _norm_ts(str(v))


def _norm_ts(value: str) -> str:
    """Normalisasi ke ISO-8601 UTC. Terima ``YYYY-MM-DD`` dan ``...Z``."""
    s = value.strip()
    if len(s) == 10:
        s = s + "T00:00:00"
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise ValueError(f"timestamp tidak valid: {value}")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def _minutes_between(start, end) -> Optional[int]:
    if not start or not end:
        return None
    try:
        a = datetime.fromisoformat(str(start).replace("Z", "+00:00"))
        b = datetime.fromisoformat(str(end).replace("Z", "+00:00"))
    except ValueError:
        return None
    delta = (b - a).total_seconds() / 60.0
    if delta < 0:
        return None
    return int(round(delta))


def _serialize(doc: dict) -> dict:
    if not doc:
        return {}
    out = {
        "id": str(doc.get("_id", "")),
        "title": doc.get("title", ""),
        "kind": doc.get("kind", "other"),
        "description": doc.get("description", ""),
        "location": doc.get("location", ""),
        "scheduled_start": doc.get("scheduled_start"),
        "scheduled_end": doc.get("scheduled_end"),
        "started_at": doc.get("started_at"),
        "ended_at": doc.get("ended_at"),
        "status": doc.get("status", "planned"),
        "owner_id": doc.get("owner_id"),
        "owner_name": doc.get("owner_name", ""),
        "created_by": doc.get("created_by", ""),
        "created_by_name": doc.get("created_by_name", ""),
        "customer_id": doc.get("customer_id"),
        "customer_name": doc.get("customer_name", ""),
        "tags": doc.get("tags") or [],
        "notes": doc.get("notes", ""),
        "source": doc.get("source", SOURCE_MANUAL),
        "source_id": doc.get("source_id"),
        "source_label": doc.get("source_label", ""),
        "link_url": doc.get("link_url", ""),
        "created_at": doc.get("created_at"),
        "updated_at": doc.get("updated_at"),
    }
    out["duration_minutes"] = _minutes_between(out["started_at"], out["ended_at"])
    out["is_running"] = out["status"] == "in_progress" and bool(out["started_at"]) and not out["ended_at"]
    return out


def _actor_id(staff: dict) -> str:
    return str(staff.get("id") or staff.get("_id") or "")


def _actor_name(staff: dict) -> str:
    return staff.get("name") or staff.get("email") or ""


def _require_staff(staff: dict) -> None:
    role = str(staff.get("role") or "").strip().lower()
    if role not in STAFF_ROLES:
        raise HTTPException(status_code=403, detail="Activity log hanya untuk staf internal")


def _find(doc_id: str) -> dict:
    try:
        return {"_id": ObjectId(doc_id)}
    except (InvalidId, TypeError):
        raise HTTPException(status_code=404, detail="Activity not found")


async def _load(db, doc_id: str) -> dict:
    doc = await db[COLL].find_one(_find(doc_id))
    if not doc:
        raise HTTPException(status_code=404, detail="Activity not found")
    return doc


# ── meta ─────────────────────────────────────────────────────────
@router.get("/admin/activities/meta")
async def activities_meta(staff=Depends(get_current_staff)):
    _require_staff(staff)
    db = await _get_db()
    staff_rows = await db.users.find(
        {"role": {"$in": sorted(STAFF_ROLES)}, "active": {"$ne": False}},
        {"name": 1, "email": 1, "role": 1, "division": 1},
    ).sort("name", 1).to_list(500)
    return {
        "kinds": list(KINDS),
        "statuses": list(STATUSES),
        "staff": [
            {"id": str(r["_id"]), "name": r.get("name") or r.get("email") or "",
             "email": r.get("email", ""), "role": r.get("role", ""),
             "division": r.get("division", "")}
            for r in staff_rows
        ],
    }


# ── list ─────────────────────────────────────────────────────────
@router.get("/admin/activities")
async def activities_list(
    status: str = "",
    kind: str = "",
    source: str = "",
    owner_id: str = "",
    date_from: str = "",
    date_to: str = "",
    q: str = "",
    page: int = 1,
    limit: int = 50,
    staff=Depends(get_current_staff),
):
    _require_staff(staff)
    db = await _get_db()

    page = max(1, int(page or 1))
    limit = max(1, min(int(limit or 50), 200))

    filt: dict = {}
    if status and status in STATUSES:
        filt["status"] = status
    if kind and kind in KINDS:
        filt["kind"] = kind
    if source:
        filt["source"] = source
    if owner_id:
        filt["owner_id"] = owner_id
    if q:
        rx = {"$regex": str(q)[:80], "$options": "i"}
        filt["$or"] = [{"title": rx}, {"description": rx}, {"location": rx},
                       {"owner_name": rx}, {"customer_name": rx}]
    if date_from or date_to:
        # Rentang memakai jadwal bila ada, kalau tidak waktu aktual.
        rng = {}
        if date_from:
            rng["$gte"] = _norm_ts(date_from) if len(date_from) > 10 else date_from + "T00:00:00+00:00"
        if date_to:
            rng["$lte"] = _norm_ts(date_to) if len(date_to) > 10 else date_to + "T23:59:59+00:00"
        filt["$and"] = filt.get("$and", []) + [{
            "$or": [
                {"scheduled_start": rng},
                {"started_at": rng},
            ]
        }]

    total = await db[COLL].count_documents(filt)
    cursor = (db[COLL].find(filt)
              .sort([("status", 1), ("scheduled_start", -1), ("created_at", -1)])
              .skip((page - 1) * limit).limit(limit))
    rows = await cursor.to_list(limit)
    return {
        "results": [_serialize(r) for r in rows],
        "total": total,
        "page": page,
        "limit": limit,
    }


@router.get("/admin/activities/{aid}")
async def activities_get(aid: str, staff=Depends(get_current_staff)):
    _require_staff(staff)
    db = await _get_db()
    return {"activity": _serialize(await _load(db, aid))}


# ── create ───────────────────────────────────────────────────────
@router.post("/admin/activities")
async def activities_create(payload: ActivityIn, request: Request,
                            staff=Depends(get_current_staff)):
    _require_staff(staff)
    db = await _get_db()
    now = _now()
    doc = payload.model_dump()
    doc["title"] = doc["title"].strip()
    doc["owner_id"] = doc.get("owner_id") or _actor_id(staff)
    doc["owner_name"] = (doc.get("owner_name") or "").strip() or _actor_name(staff)
    doc["source"] = SOURCE_MANUAL
    doc["source_id"] = None
    doc["created_by"] = _actor_id(staff)
    doc["created_by_name"] = _actor_name(staff)
    doc["started_at"] = None
    doc["ended_at"] = None
    doc["created_at"] = now
    doc["updated_at"] = now
    if doc["status"] == "in_progress":
        doc["started_at"] = now
    if doc["status"] == "done":
        doc["ended_at"] = now

    r = await db[COLL].insert_one(doc)
    doc["_id"] = r.inserted_id
    await log_audit(
        db, actor=staff, action="activity.create", category="operations",
        target_type="activity", target_id=str(r.inserted_id),
        target_label=doc["title"], after={"kind": doc["kind"], "status": doc["status"]},
        request=request,
    )
    return _serialize(doc)


# ── update ───────────────────────────────────────────────────────
@router.put("/admin/activities/{aid}")
async def activities_update(aid: str, payload: ActivityUpdate, request: Request,
                            staff=Depends(get_current_staff)):
    _require_staff(staff)
    db = await _get_db()
    existing = await _load(db, aid)

    upd = payload.model_dump(exclude_unset=True)
    if not upd:
        raise HTTPException(status_code=400, detail="No fields to update")
    for key in ("owner_name", "customer_name", "description", "location", "notes"):
        if key in upd and upd[key] is not None:
            upd[key] = str(upd[key]).strip()

    # Status diubah manual: jaga konsistensi started_at/ended_at supaya durasi
    # tidak pernah negatif dan "mark as done" selalu punya waktu selesai.
    if "status" in upd:
        now = _now()
        st = upd["status"]
        if st == "in_progress" and not existing.get("started_at"):
            upd["started_at"] = now
        if st == "in_progress":
            upd["ended_at"] = None
        if st == "done":
            upd["started_at"] = existing.get("started_at") or now
            upd["ended_at"] = existing.get("ended_at") or now
        if st == "planned":
            upd["started_at"] = None
            upd["ended_at"] = None

    upd["updated_at"] = _now()
    await db[COLL].update_one({"_id": existing["_id"]}, {"$set": upd})
    doc = await db[COLL].find_one({"_id": existing["_id"]})
    await log_audit(
        db, actor=staff, action="activity.update", category="operations",
        target_type="activity", target_id=str(existing["_id"]),
        target_label=doc.get("title", ""),
        before={"status": existing.get("status"), "title": existing.get("title")},
        after={"status": doc.get("status"), "title": doc.get("title")},
        request=request,
    )
    return _serialize(doc)


# ── start / end / cancel ─────────────────────────────────────────
@router.post("/admin/activities/{aid}/start")
async def activities_start(aid: str, request: Request, staff=Depends(get_current_staff)):
    """Mulai aktivitas. Idempoten: start ganda tidak mereset waktu mulai."""
    _require_staff(staff)
    db = await _get_db()
    existing = await _load(db, aid)
    if existing.get("status") == "done":
        raise HTTPException(status_code=409, detail="Activity sudah selesai")
    if existing.get("status") == "cancelled":
        raise HTTPException(status_code=409, detail="Activity sudah dibatalkan")

    now = _now()
    started = existing.get("started_at") or now
    await db[COLL].update_one(
        {"_id": existing["_id"]},
        {"$set": {"status": "in_progress", "started_at": started,
                  "ended_at": None, "updated_at": now,
                  "started_by": _actor_id(staff)}},
    )
    doc = await db[COLL].find_one({"_id": existing["_id"]})
    await log_audit(
        db, actor=staff, action="activity.start", category="operations",
        target_type="activity", target_id=str(existing["_id"]),
        target_label=doc.get("title", ""), request=request,
    )
    return _serialize(doc)


@router.post("/admin/activities/{aid}/end")
async def activities_end(aid: str, request: Request, staff=Depends(get_current_staff)):
    """Selesai (mark as done). Kalau belum pernah start, waktu mulai diisi sekarang."""
    _require_staff(staff)
    db = await _get_db()
    existing = await _load(db, aid)
    if existing.get("status") == "cancelled":
        raise HTTPException(status_code=409, detail="Activity sudah dibatalkan")

    now = _now()
    started = existing.get("started_at") or now
    await db[COLL].update_one(
        {"_id": existing["_id"]},
        {"$set": {"status": "done", "started_at": started, "ended_at": now,
                  "updated_at": now, "ended_by": _actor_id(staff)}},
    )
    doc = await db[COLL].find_one({"_id": existing["_id"]})
    await log_audit(
        db, actor=staff, action="activity.end", category="operations",
        target_type="activity", target_id=str(existing["_id"]),
        target_label=doc.get("title", ""),
        after={"duration_minutes": _minutes_between(started, now)}, request=request,
    )
    return _serialize(doc)


@router.post("/admin/activities/{aid}/cancel")
async def activities_cancel(aid: str, request: Request, staff=Depends(get_current_staff)):
    _require_staff(staff)
    db = await _get_db()
    existing = await _load(db, aid)
    now = _now()
    await db[COLL].update_one(
        {"_id": existing["_id"]},
        {"$set": {"status": "cancelled", "ended_at": existing.get("ended_at") or now,
                  "updated_at": now}},
    )
    doc = await db[COLL].find_one({"_id": existing["_id"]})
    await log_audit(
        db, actor=staff, action="activity.cancel", category="operations",
        target_type="activity", target_id=str(existing["_id"]),
        target_label=doc.get("title", ""), request=request,
    )
    return _serialize(doc)


# ── delete ───────────────────────────────────────────────────────
@router.delete("/admin/activities/{aid}")
async def activities_delete(aid: str, request: Request, staff=Depends(get_current_staff)):
    """Hapus aktivitas. Hanya pembuat atau admin; entri otomatis terikat sumber."""
    _require_staff(staff)
    db = await _get_db()
    existing = await _load(db, aid)
    role = str(staff.get("role") or "").lower()
    if role != "admin" and str(existing.get("created_by") or "") != _actor_id(staff):
        raise HTTPException(status_code=403, detail="Hanya admin atau pembuat aktivitas")
    r = await db[COLL].delete_one({"_id": existing["_id"]})
    if not r.deleted_count:
        raise HTTPException(status_code=404, detail="Activity not found")
    await log_audit(
        db, actor=staff, action="activity.delete", category="operations",
        target_type="activity", target_id=str(existing["_id"]),
        target_label=existing.get("title", ""), severity="warning", request=request,
    )
    return {"deleted": r.deleted_count}
