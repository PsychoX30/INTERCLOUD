"""Unified operations read-model.

One aggregation layer over the surfaces that already exist — monitoring,
NOC/MikroTik, SLA, security, audit — so an operator gets a single
"what needs attention right now" view instead of opening six pages.

Deliberate design rules:

* **Aggregation, not duplication.**  This module owns no collection of its
  own and writes nothing.  Every number is derived from the owning module's
  data, so there is no second source of truth to keep consistent.
* **A gap is ``None``, never ``0``.**  The collections here are heterogeneous
  (monitoring stores BSON ``datetime``, NOC stores ISO strings, some legacy
  rows omit a field entirely).  If a collection cannot be read, the affected
  counters come back ``None`` so the UI renders "unknown" instead of a
  confident zero.  Reporting ``down: 0`` because the query blew up is exactly
  the silent-defect class this project refuses.
* **Read-only.**  No inserts, no updates, no dispatches, no side effects.

Only the confirmed monitoring status is counted as up/down; ``pending`` is
reported separately because a retry window is *not* an outage.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

logger = logging.getLogger("portal.ops")

# Mirrors the sweep's own bound so the overview can never look at more checks
# than the prober would actually run.
_MAX_CHECKS = 500
_MAX_ROWS = 500

# How fresh an event has to be to still be worth putting in front of a human.
_SLA_LOOKBACK_HOURS = 24 * 7

_AREA_MONITORING = "monitoring"
_AREA_NOC = "noc"
_AREA_SLA = "sla"
_AREA_SECURITY = "security"
_AREA_AUDIT = "audit"

_LEVEL_CRITICAL = "critical"
_LEVEL_WARNING = "warning"
_LEVEL_INFO = "info"


def _as_dt(value: Any) -> Optional[datetime]:
    """Best-effort conversion of the several timestamp shapes we store.

    Returns a tz-aware datetime, or ``None`` when the value is missing or not
    parseable — callers must treat ``None`` as "unknown", never as epoch.
    """
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, (int, float)):
        # BSON dates arrive as datetime, but be forgiving with epoch seconds.
        try:
            return datetime.fromtimestamp(float(value), tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    return None


async def _count(collection, query: dict) -> Optional[int]:
    """``count_documents`` that degrades to ``None`` instead of raising.

    ``count_documents`` is unavailable on some in-memory test fakes, so fall
    back to a bounded materialised count before giving up.
    """
    if collection is None:
        return None
    try:
        return int(await collection.count_documents(query))
    except Exception:  # noqa: BLE001 - try the cursor fallback
        logger.debug("[ops] count_documents unavailable, falling back", exc_info=True)
    try:
        rows = await collection.find(query).to_list(_MAX_ROWS + 1)
    except Exception:  # noqa: BLE001
        logger.debug("[ops] count fallback failed", exc_info=True)
        return None
    if rows is None:
        return 0
    if len(rows) > _MAX_ROWS:
        # Honest answer: we refuse to claim an exact number we did not count.
        return None
    return len(rows)


def _add_attention(items: list, *, level: str, area: str, title: str,
                   detail: str, link: str) -> None:
    items.append({"level": level, "area": area, "title": title,
                  "detail": detail, "link": link})


async def _rows(collection, query: dict, *, sort=None, limit=_MAX_ROWS) -> Optional[list]:
    if collection is None:
        return None
    try:
        cursor = collection.find(query)
        if sort:
            cursor = cursor.sort(*sort)
        rows = await cursor.to_list(limit + 1)
        rows = list(rows or [])
        # A full page means there may be more rows. Do not publish a partial
        # aggregate as exact; fail closed to unknown for open cardinality.
        if len(rows) > limit:
            return None
        return rows
    except Exception:  # noqa: BLE001
        logger.warning("[ops] list query failed", exc_info=True)
        return None


async def build_ops_overview(db, *, now: Optional[datetime] = None) -> dict:
    """Return a bounded, read-only unified operations snapshot."""
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    recent_cutoff = now - timedelta(hours=_SLA_LOOKBACK_HOURS)

    summary = {
        "monitoring": {"checks": None, "up": None, "down": None,
                       "pending": None, "disabled": None,
                       "undelivered_alerts": None, "exhausted_alerts": None},
        "noc": {"devices": None, "up": None, "down": None,
                "unknown": None, "recent_events": None},
        "sla": {"open_incidents": None, "recent_incidents": None},
        "security": {"active_blocks": None, "recent_notifications": None},
        "audit": {"recent_critical": None},
    }
    attention = []
    sources = {}

    # Monitoring: status must be confirmed. `pending` is degraded, not down.
    checks = await _rows(db.monitoring_checks, {}, limit=_MAX_CHECKS)
    states = await _rows(db.monitoring_check_state, {}, limit=_MAX_CHECKS)
    if checks is not None and states is not None:
        state_by_id = {str(row.get("check_id")): row for row in states}
        status_counts = {"up": 0, "down": 0, "pending": 0}
        for check in checks:
            if not check.get("enabled", True):
                continue
            state = state_by_id.get(str(check.get("_id"))) or {}
            confirmed = state.get("confirmed_status")
            if confirmed not in ("up", "down"):
                confirmed = state.get("status")
            if state.get("status") == "pending":
                status_counts["pending"] += 1
            elif confirmed in status_counts:
                status_counts[confirmed] += 1
        summary["monitoring"].update(checks=len(checks), **status_counts,
                                     disabled=sum(1 for c in checks if not c.get("enabled", True)))
        if status_counts["down"]:
            _add_attention(attention, level=_LEVEL_CRITICAL, area=_AREA_MONITORING,
                           title="Monitoring checks down", detail=f"{status_counts['down']} confirmed DOWN",
                           link="/portal/admin/monitoring")
        if status_counts["pending"]:
            _add_attention(attention, level=_LEVEL_WARNING, area=_AREA_MONITORING,
                           title="Monitoring checks pending", detail=f"{status_counts['pending']} awaiting retry confirmation",
                           link="/portal/admin/monitoring")
    else:
        sources[_AREA_MONITORING] = "unknown: checks or state collection unavailable"

    undelivered = await _count(db.monitoring_events, {"notified": False, "notify_exhausted": {"$ne": True}})
    exhausted = await _count(db.monitoring_events, {"notify_exhausted": True})
    summary["monitoring"].update(undelivered_alerts=undelivered, exhausted_alerts=exhausted)
    if undelivered:
        _add_attention(attention, level=_LEVEL_WARNING, area=_AREA_MONITORING,
                       title="Undelivered alerts", detail=f"{undelivered} alert(s) queued for retry",
                       link="/portal/admin/monitoring")
    if exhausted:
        _add_attention(attention, level=_LEVEL_CRITICAL, area=_AREA_MONITORING,
                       title="Alerts exhausted", detail=f"{exhausted} alert(s) need operator review",
                       link="/portal/admin/monitoring")

    # NOC stores state docs separately from device registry.
    devices = await _rows(db.mikrotik_devices, {}, limit=_MAX_CHECKS)
    noc_states = await _rows(db.noc_device_state, {}, limit=_MAX_CHECKS)
    if devices is not None and noc_states is not None:
        state_by_id = {str(row.get("device_id")): row for row in noc_states}
        counts = {"up": 0, "down": 0, "unknown": 0}
        for device in devices:
            state = state_by_id.get(str(device.get("_id"))) or {}
            status = state.get("status")
            counts[status if status in ("up", "down") else "unknown"] += 1
        summary["noc"].update(devices=len(devices), **counts)
        if counts["down"]:
            _add_attention(attention, level=_LEVEL_CRITICAL, area=_AREA_NOC,
                           title="NOC devices down", detail=f"{counts['down']} device(s) reported DOWN",
                           link="/portal/admin/noc")
    else:
        sources[_AREA_NOC] = "unknown: device registry or state unavailable"
    noc_events = await _count(db.noc_events, {"at": {"$gte": recent_cutoff.isoformat()}})
    summary["noc"]["recent_events"] = noc_events

    # SLA incident timestamps are ISO strings; do not compare with BSON dates.
    # Status enum is open|resolved|postmortem (models.SLAIncidentIn), so only
    # ``open`` is an unresolved incident — ``postmortem`` is already closed.
    sla_open = await _count(db.sla_incidents, {"status": "open"})
    sla_recent = await _count(db.sla_incidents, {"started_at": {"$gte": recent_cutoff.isoformat()}})
    summary["sla"].update(open_incidents=sla_open, recent_incidents=sla_recent)
    if sla_open:
        _add_attention(attention, level=_LEVEL_WARNING, area=_AREA_SLA,
                       title="Open SLA incidents", detail=f"{sla_open} incident(s) still open",
                       link="/portal/admin/sla")

    # Security ban records can have BSON datetime or string expiry. Count exact
    # active rows in a bounded scan to handle mixed legacy shapes correctly.
    blocks = await _rows(db.blocked_ips, {}, limit=_MAX_ROWS)
    if blocks is None:
        sources[_AREA_SECURITY] = "unknown: blocked IP collection unavailable"
    else:
        active_blocks = 0
        for row in blocks:
            expiry = _as_dt(row.get("expires_at"))
            unblocked = row.get("unblocked_at")
            if expiry and expiry > now and not unblocked:
                active_blocks += 1
        summary["security"]["active_blocks"] = active_blocks if len(blocks) <= _MAX_ROWS else None
        if active_blocks:
            _add_attention(attention, level=_LEVEL_INFO, area=_AREA_SECURITY,
                           title="Active IP blocks", detail=f"{active_blocks} block(s) active",
                           link="/portal/admin/security")
    sec_recent = await _count(db.security_notifications, {"created_at": {"$gte": recent_cutoff.isoformat()}})
    summary["security"]["recent_notifications"] = sec_recent

    audit_critical = await _count(db.audit_logs, {"severity": "critical", "created_at": {"$gte": recent_cutoff.isoformat()}})
    summary["audit"]["recent_critical"] = audit_critical
    if audit_critical:
        _add_attention(attention, level=_LEVEL_WARNING, area=_AREA_AUDIT,
                       title="Critical audit entries", detail=f"{audit_critical} critical entry/entries in the last 7 days",
                       link="/portal/admin/audit-log")

    # Never coerce a query/collection failure into zero. Query-level unknowns
    # are exposed explicitly so the UI can distinguish unavailable from empty.
    for area, values in summary.items():
        if any(value is None for value in values.values()):
            sources.setdefault(area, "unknown: one or more counters unavailable")

    priority = {_LEVEL_CRITICAL: 0, _LEVEL_WARNING: 1, _LEVEL_INFO: 2}
    attention.sort(key=lambda item: (priority.get(item["level"], 3), item["area"], item["title"]))
    return {
        "generated_at": now.isoformat(),
        "lookback_hours": _SLA_LOOKBACK_HOURS,
        "summary": summary,
        "attention": attention[:100],
        "source_status": sources,
        "read_only": True,
    }
