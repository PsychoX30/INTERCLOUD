"""SLA incident tracking and PDF report export.

Internal-first: no public SLA metrics exposed.
"""

import json
import logging
from html import escape
from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from bson import ObjectId

from .. import models as m
from ..auth import (
    get_current_admin, get_current_staff, require_roles,
    STAFF_ROLES, FINANCE_ROLES, OPS_ROLES,
)
from .shared import _get_db, _oid, _now, _sales_scope_filter, _get_setting_value, _set_setting_value
from .documents import _render_pdf_bytes

router = APIRouter()
_log = logging.getLogger("portal.sla")


# ── helpers ──────────────────────────────────────────────────────
def _serialize_incident(doc: dict) -> dict:
    if not doc:
        return {}
    started = doc.get("started_at")
    ended = doc.get("ended_at")
    duration = None
    if started:
        try:
            start_dt = started if isinstance(started, datetime) else datetime.fromisoformat(started.replace("Z", "+00:00"))
            end_dt = ended if (ended and isinstance(ended, datetime)) else (datetime.fromisoformat(ended.replace("Z", "+00:00")) if ended else datetime.now(timezone.utc))
            if start_dt.tzinfo is None:
                start_dt = start_dt.replace(tzinfo=timezone.utc)
            if end_dt.tzinfo is None:
                end_dt = end_dt.replace(tzinfo=timezone.utc)
            duration = max(0, int((end_dt - start_dt).total_seconds() // 60))
        except Exception:
            duration = None

    return {
        "id": str(doc["_id"]),
        "service_id": doc.get("service_id"),
        "device_id": doc.get("device_id"),
        "title": doc.get("title", ""),
        "description": doc.get("description", ""),
        "severity": doc.get("severity", "medium"),
        "started_at": doc.get("started_at", ""),
        "ended_at": doc.get("ended_at"),
        "affected_customers": doc.get("affected_customers", []),
        "status": doc.get("status", "open"),
        "root_cause": doc.get("root_cause", ""),
        "created_by": doc.get("created_by"),
        "notes": doc.get("notes", ""),
        "duration_minutes": duration,
        "created_at": doc.get("created_at", ""),
        "updated_at": doc.get("updated_at", ""),
    }


def _require_sla_reader(role: str) -> None:
    if role not in ("admin", "support", "finance", "sales"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")


def _require_sla_writer(role: str) -> None:
    if role not in ("admin", "support"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")


def _sales_scope_filter_for_incidents(staff: dict) -> dict:
    if staff.get("role") != "sales":
        return {}
    assigned = staff.get("assigned_client_ids") or []
    if not assigned:
        return {"_id": None}
    # affected_customers is stored as a list of user_id strings.
    return {"affected_customers": {"$in": [str(x) for x in assigned]}}


# ── CRUD ──────────────────────────────────────────────────────────
@router.get("/admin/sla/incidents")
async def list_sla_incidents(
    status: Optional[str] = Query(None),
    severity: Optional[str] = Query(None),
    start: Optional[str] = Query(None),
    end: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    admin=Depends(get_current_staff),
):
    _require_sla_reader(admin.get("role"))
    db = await _get_db()
    filt: dict = {}
    if status:
        filt["status"] = status
    if severity:
        filt["severity"] = severity
    if start or end:
        filt["started_at"] = {}
        if start:
            filt["started_at"]["$gte"] = start if "T" in start else start + "T00:00:00"
        if end:
            filt["started_at"]["$lte"] = end if "T" in end else end + "T23:59:59"

    filt.update(_sales_scope_filter_for_incidents(admin))

    total = await db.sla_incidents.count_documents(filt)
    cursor = db.sla_incidents.find(filt).sort("started_at", -1).skip((page - 1) * limit).limit(limit)
    rows = await cursor.to_list(limit)
    return {
        "results": [_serialize_incident(r) for r in rows],
        "total": total,
        "page": page,
        "limit": limit,
    }


@router.get("/admin/sla/incidents/{iid}")
async def get_sla_incident(iid: str, admin=Depends(get_current_staff)):
    _require_sla_reader(admin.get("role"))
    db = await _get_db()
    filt = {"_id": _oid(iid)}
    filt.update(_sales_scope_filter_for_incidents(admin))
    doc = await db.sla_incidents.find_one(filt)
    if not doc:
        raise HTTPException(status_code=404, detail="Incident not found")
    return {"incident": _serialize_incident(doc)}


@router.post("/admin/sla/incidents")
async def create_sla_incident(payload: m.SLAIncidentIn, admin=Depends(get_current_staff)):
    _require_sla_writer(admin.get("role"))
    db = await _get_db()
    now = _now()
    doc = payload.model_dump()
    doc["created_by"] = str(admin.get("id"))
    doc["created_at"] = now
    doc["updated_at"] = now
    r = await db.sla_incidents.insert_one(doc)
    return {"id": str(r.inserted_id)}


@router.put("/admin/sla/incidents/{iid}")
async def update_sla_incident(iid: str, payload: m.SLAIncidentUpdate, admin=Depends(get_current_staff)):
    _require_sla_writer(admin.get("role"))
    db = await _get_db()
    existing = await db.sla_incidents.find_one({"_id": _oid(iid), **_sales_scope_filter_for_incidents(admin)})
    if not existing:
        raise HTTPException(status_code=404, detail="Incident not found")

    update = payload.model_dump(exclude_unset=True)
    if not update:
        raise HTTPException(status_code=400, detail="No fields to update")
    update["updated_at"] = _now()
    await db.sla_incidents.update_one({"_id": existing["_id"], **_sales_scope_filter_for_incidents(admin)}, {"$set": update})
    doc = await db.sla_incidents.find_one({"_id": existing["_id"], **_sales_scope_filter_for_incidents(admin)})
    return {"incident": _serialize_incident(doc)}


@router.delete("/admin/sla/incidents/{iid}")
async def delete_sla_incident(iid: str, admin=Depends(get_current_staff)):
    if admin.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Only admin can delete incidents")
    db = await _get_db()
    r = await db.sla_incidents.delete_one({"_id": _oid(iid)})
    if not r.deleted_count:
        raise HTTPException(status_code=404, detail="Incident not found")
    return {"deleted": r.deleted_count}


# ── Config ────────────────────────────────────────────────────────
@router.get("/admin/sla/config")
async def get_sla_config(admin=Depends(get_current_admin)):
    db = await _get_db()
    target = await _get_setting_value(db, "sla_target_uptime_percent", "99.5")
    raw_mw = await _get_setting_value(db, "sla_excluded_maintenance_windows", "[]")
    auto = await _get_setting_value(db, "auto_create_sla_incidents", "false")

    try:
        maintenance = json.loads(raw_mw)
    except Exception:
        maintenance = []

    return {
        "sla_target_uptime_percent": float(target),
        "sla_excluded_maintenance_windows": maintenance,
        "auto_create_sla_incidents": str(auto).lower() == "true",
    }


@router.put("/admin/sla/config")
async def update_sla_config(payload: m.SLAConfigIn, admin=Depends(get_current_admin)):
    db = await _get_db()
    await _set_setting_value(db, "sla_target_uptime_percent", str(payload.sla_target_uptime_percent))
    await _set_setting_value(db, "sla_excluded_maintenance_windows", json.dumps(payload.sla_excluded_maintenance_windows))
    await _set_setting_value(db, "auto_create_sla_incidents", str(payload.auto_create_sla_incidents).lower())
    return {"ok": True}


# ── PDF Report ────────────────────────────────────────────────────
@router.get("/admin/sla/report/pdf")
async def sla_report_pdf(
    start: str = Query(..., description="YYYY-MM-DD"),
    end: str = Query(..., description="YYYY-MM-DD"),
    admin=Depends(get_current_staff),
):
    _require_sla_reader(admin.get("role"))
    db = await _get_db()

    filt: dict = {"started_at": {"$gte": start, "$lte": end + "T23:59:59"}}
    filt.update(_sales_scope_filter_for_incidents(admin))

    incidents = await db.sla_incidents.find(filt).sort("started_at", 1).to_list(500)
    target = float(await _get_setting_value(db, "sla_target_uptime_percent", "99.5"))

    total_downtime_minutes = 0
    for inc in incidents:
        started = inc.get("started_at")
        ended = inc.get("ended_at")
        if started and ended:
            try:
                s = started if isinstance(started, datetime) else datetime.fromisoformat(started.replace("Z", "+00:00"))
                e = ended if isinstance(ended, datetime) else datetime.fromisoformat(ended.replace("Z", "+00:00"))
                total_downtime_minutes += (e - s).total_seconds() / 60
            except Exception:
                pass

    try:
        period_start = datetime.fromisoformat(start)
        period_end = datetime.fromisoformat(end) + timedelta(days=1)
        total_period_minutes = (period_end - period_start).total_seconds() / 60
        availability = 100 - (total_downtime_minutes / total_period_minutes * 100) if total_period_minutes > 0 else 100.0
    except Exception:
        availability = 100.0
        total_period_minutes = 0

    incident_rows = ""
    for inc in incidents:
        started = inc.get("started_at", "")[:16] if isinstance(inc.get("started_at"), str) else str(inc.get("started_at", ""))[:16]
        ended = inc.get("ended_at", "")[:16] if isinstance(inc.get("ended_at"), str) else (str(inc.get("ended_at", ""))[:16] if inc.get("ended_at") else "-")
        dur = _serialize_incident(inc).get("duration_minutes") or 0
        incident_rows += (
            f"<tr><td>{escape(started)}</td><td>{escape(ended)}</td>"
            f"<td>{escape(str(inc.get('title', '')))}</td>"
            f"<td>{escape(str(inc.get('severity', '')))}</td>"
            f"<td>{dur} min</td><td>{escape(str(inc.get('status', '')))}</td></tr>\n"
        )

    html = f"""<!doctype html>
<html><head><meta charset="utf-8"><title>SLA Report {start} to {end}</title>
<style>
  @page {{ size: A4 landscape; margin: 14mm; }}
  body {{ font-family: -apple-system, 'Segoe UI', Roboto, sans-serif; font-size: 11px; color: #334155; }}
  h1 {{ font-size: 18px; color: #0a2350; margin: 0 0 4px 0; }}
  .meta {{ color: #64748b; margin-bottom: 16px; }}
  .summary {{ display: flex; gap: 24px; margin-bottom: 16px; }}
  .summary .box {{ background: #e5edf5; padding: 12px 16px; border-radius: 8px; }}
  .summary .box .label {{ font-size: 10px; text-transform: uppercase; color: #64748b; }}
  .summary .box .value {{ font-size: 20px; font-weight: 800; color: #0a2350; }}
  table {{ width: 100%; border-collapse: collapse; }}
  th {{ background: #0a2350; color: #fff; padding: 7px 8px; text-align: left; font-size: 10px; text-transform: uppercase; }}
  td {{ padding: 6px 8px; border-bottom: 1px solid #e2e8f0; }}
  .pass {{ color: #22c55e; font-weight: 800; }}
  .fail {{ color: #dc2626; font-weight: 800; }}
</style></head>
<body>
  <h1>SLA Report</h1>
  <div class="meta">Period: {start} &mdash; {end} | Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}</div>
  <div class="summary">
    <div class="box"><div class="label">Target Uptime</div><div class="value">{target}%</div></div>
    <div class="box"><div class="label">Actual Availability</div><div class="value">{availability:.2f}%</div></div>
    <div class="box"><div class="label">Total Incidents</div><div class="value">{len(incidents)}</div></div>
    <div class="box"><div class="label">Total Downtime</div><div class="value">{total_downtime_minutes:.0f} min</div></div>
    <div class="box"><div class="label">SLA Met?</div><div class="value {'pass' if availability >= target else 'fail'}">{'YES' if availability >= target else 'NO'}</div></div>
  </div>
  <table>
    <thead><tr><th>Started</th><th>Ended</th><th>Title</th><th>Severity</th><th>Duration</th><th>Status</th></tr></thead>
    <tbody>{incident_rows}</tbody>
  </table>
</body></html>"""

    pdf_bytes = _render_pdf_bytes(html)
    filename = f"SLA_Report_{start}_{end}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )