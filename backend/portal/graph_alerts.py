"""Graph alert evaluation, debounce, maintenance suppression, and dispatch.

Phase 3 of the monitoring upgrade. Deliberately a separate module from
``monitoring_graphs`` (already ~1000 lines) so the alert logic stays testable
without importing the SNMP stack.

Design decisions (locked in the plan, 2026-09-30_145758):

* **In-process evaluator.** Evaluation runs inside the existing graph sweep
  (every 20s). No extra worker, no extra service to babysit.
* **Debounce by ``consecutive``.** A rule fires only after N consecutive
  breaching polls (default 2). A single flapping sample must never page anyone.
* **Transition-only dispatch.** Alerts fire on the transition into breach and
  resolve on the transition back to healthy. A steady breach is *not*
  re-notified on every poll.
* **Maintenance windows suppress dispatch, never evaluation.** During a window
  the alert row is still written (with ``suppressed: True``) so the history is
  honest, but no notification leaves the building.
* **Never break polling.** Every function here swallows its own exceptions;
  a broken alert rule must not stop samples from being stored.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger("portal.graph_alerts")

ALERTS_COLLECTION = "monitoring_graph_alerts"
STATE_COLLECTION = "monitoring_graph_alert_state"
WINDOWS_COLLECTION = "monitoring_maintenance_windows"
RULES_COLLECTION = "graph_alert_rules"

# Alert history is narrative, not a metric: 90d matches the hourly archive.
ALERTS_TTL_SECONDS = 90 * 86400

_COMPARATORS = {
    ">": lambda a, b: a > b,
    ">=": lambda a, b: a >= b,
    "<": lambda a, b: a < b,
    "<=": lambda a, b: a <= b,
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_dt(value) -> Optional[datetime]:
    """Tolerant ISO/datetime parser. Returns aware UTC datetime or None."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _as_float(value) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def rule_breached(rule: dict, *, value, state: str) -> bool:
    """Pure predicate: does this sample breach the rule?

    ``metric == "state"`` ignores the value and breaches whenever the poll did
    not succeed — that is the "graph is dead" alert, the one that matters most
    because a flatlined graph used to be indistinguishable from an idle one.
    """
    metric = str(rule.get("metric") or "bps")
    if metric == "state":
        return str(state or "") != "ok"
    if value is None:
        return False
    current = _as_float(value)
    threshold = _as_float(rule.get("threshold"))
    if current is None or threshold is None:
        return False
    op = _COMPARATORS.get(str(rule.get("comparator") or ">"))
    if op is None:
        return False
    return bool(op(current, threshold))


def _window_covers(window: dict, graph_id: str, when: datetime) -> bool:
    start = _parse_dt(window.get("starts_at"))
    end = _parse_dt(window.get("ends_at"))
    if start is None or end is None:
        return False
    if not (start <= when <= end):
        return False
    scoped = [str(g) for g in (window.get("graph_ids") or [])]
    if scoped and graph_id not in scoped:
        return False
    return True


async def active_maintenance(db, *, graph_id: str, now: Optional[datetime] = None) -> Optional[dict]:
    """Return the first enabled maintenance window currently covering ``graph_id``."""
    when = now or _now()
    try:
        docs = await db[WINDOWS_COLLECTION].find({"enabled": True}).to_list(200)
    except Exception:  # noqa: BLE001 - suppression is best-effort
        logger.debug("[alerts] maintenance lookup failed", exc_info=True)
        return None
    for window in docs or []:
        if _window_covers(window, graph_id, when):
            return window
    return None


async def _load_state(db, rule_id: str, graph_id: str) -> dict:
    try:
        doc = await db[STATE_COLLECTION].find_one({"rule_id": rule_id, "graph_id": graph_id})
    except Exception:  # noqa: BLE001
        logger.debug("[alerts] state read failed", exc_info=True)
        return {}
    return doc or {}


async def _save_state(db, rule_id: str, graph_id: str, **fields) -> None:
    try:
        await db[STATE_COLLECTION].update_one(
            {"rule_id": rule_id, "graph_id": graph_id},
            {"$set": {**fields, "updated_at": _now()}},
            upsert=True,
        )
    except Exception:  # noqa: BLE001
        logger.debug("[alerts] state write failed", exc_info=True)


def _alert_doc(rule: dict, graph: dict, *, value, state: str, error: str,
               now: datetime, suppressed: bool) -> dict:
    return {
        "rule_id": str(rule.get("_id") or ""),
        "rule_name": rule.get("name", ""),
        "graph_id": str(graph.get("_id") or ""),
        "graph_name": graph.get("display_name") or graph.get("name", ""),
        "target": graph.get("target", ""),
        "metric": rule.get("metric", "bps"),
        "comparator": rule.get("comparator", ">"),
        "threshold": rule.get("threshold", 0),
        "severity": rule.get("severity", "warning"),
        "value": value,
        "state": state,
        "error": (error or "")[:200],
        "fired_at": now,
        "resolved_at": None,
        "dispatched": not suppressed,
        "suppressed": suppressed,
    }


async def evaluate_graph_alerts(db, *, graph: dict, state: str, value=None,
                                error: str = "", now: Optional[datetime] = None) -> dict:
    """Evaluate every enabled rule against one poll result.

    Called from ``_record_graph_status`` so all poll paths (success, baseline,
    SNMP error, ping) are covered by a single hook.
    """
    result: dict = {"fired": [], "resolved": [], "suppressed": []}
    if db is None or not graph:
        return result
    graph_id = str(graph.get("_id") or "")
    if not graph_id:
        return result
    when = now or _now()

    try:
        rules = await db[RULES_COLLECTION].find({"enabled": True}).to_list(200)
    except Exception:  # noqa: BLE001 - advisory, never break polling
        logger.debug("[alerts] rule lookup failed", exc_info=True)
        return result

    for rule in rules or []:
        rule_id = str(rule.get("_id") or "")
        if not rule_id:
            continue
        scope = str(rule.get("graph_id") or "")
        if scope and scope != graph_id:
            continue

        breach = rule_breached(rule, value=value, state=state)
        st = await _load_state(db, rule_id, graph_id)
        consecutive = int(st.get("consecutive") or 0)
        active = bool(st.get("active"))
        needed = max(1, int(rule.get("consecutive") or 2))

        if breach:
            consecutive += 1
            if not active and consecutive >= needed:
                window = await active_maintenance(db, graph_id=graph_id, now=when)
                suppressed = window is not None
                alert = _alert_doc(rule, graph, value=value, state=state, error=error,
                                   now=when, suppressed=suppressed)
                try:
                    ins = await db[ALERTS_COLLECTION].insert_one(dict(alert))
                    alert["_id"] = getattr(ins, "inserted_id", None)
                except Exception:  # noqa: BLE001
                    logger.debug("[alerts] alert insert failed", exc_info=True)
                if suppressed:
                    alert["maintenance_window"] = window.get("name", "")
                    result["suppressed"].append(alert)
                    logger.info("[alerts] suppressed %s on %s (maintenance: %s)",
                                rule.get("name"), graph_id, window.get("name"))
                else:
                    try:
                        await dispatch_graph_alert(db, alert=alert, rule=rule, graph=graph)
                    except Exception:  # noqa: BLE001 - dispatch must not break the sweep
                        logger.debug("[alerts] dispatch failed", exc_info=True)
                    result["fired"].append(alert)
                    logger.warning("[alerts] FIRED %s on graph %s (value=%s state=%s)",
                                   rule.get("name"), graph_id, value, state)
                active = True
            await _save_state(db, rule_id, graph_id, consecutive=consecutive,
                              active=active, last_value=value, last_state=state)
        else:
            if active:
                try:
                    await db[ALERTS_COLLECTION].update_one(
                        {"rule_id": rule_id, "graph_id": graph_id, "resolved_at": None},
                        {"$set": {"resolved_at": when}},
                    )
                except Exception:  # noqa: BLE001
                    logger.debug("[alerts] resolve update failed", exc_info=True)
                result["resolved"].append({"rule_id": rule_id, "graph_id": graph_id,
                                           "rule_name": rule.get("name", "")})
                logger.info("[alerts] RESOLVED %s on graph %s", rule.get("name"), graph_id)
            consecutive = 0
            active = False
            await _save_state(db, rule_id, graph_id, consecutive=0, active=False,
                              last_value=value, last_state=state)

    return result


def _subject(alert: dict) -> str:
    sev = str(alert.get("severity", "warning")).upper()
    metric = alert.get("metric", "bps")
    if metric == "state":
        detail = f"poll state={alert.get('state', '')}"
    else:
        detail = f"{alert.get('value', 0)} {alert.get('comparator', '>')} {alert.get('threshold', 0)}"
    return (f"[GRAPH {sev}] {alert.get('graph_name', '')} — "
            f"{alert.get('rule_name', '')} ({detail})")


def _body(alert: dict, graph: dict) -> str:
    return (
        f"<h2 style='color:#dc2626;margin:0 0 8px 0'>Grafik monitoring melewati ambang</h2>"
        f"<table style='width:100%;border-collapse:collapse;font-size:13px'>"
        f"<tr><td>Grafik</td><td><b>{alert.get('graph_name', '')}</b></td></tr>"
        f"<tr><td>Target</td><td>{alert.get('target', '')}</td></tr>"
        f"<tr><td>Rule</td><td>{alert.get('rule_name', '')}</td></tr>"
        f"<tr><td>Metrik</td><td>{alert.get('metric', '')}</td></tr>"
        f"<tr><td>Nilai</td><td>{alert.get('value', '')}</td></tr>"
        f"<tr><td>Ambang</td><td>{alert.get('comparator', '')} {alert.get('threshold', '')}</td></tr>"
        f"<tr><td>Severity</td><td>{alert.get('severity', '')}</td></tr>"
        f"<tr><td>State</td><td>{alert.get('state', '')} {alert.get('error', '')}</td></tr>"
        f"<tr><td>Waktu</td><td>{alert.get('fired_at', '')}</td></tr>"
        f"</table>"
    )


async def dispatch_graph_alert(db, *, alert: dict, rule: dict, graph: dict) -> list:
    """Send a graph alert to every notif channel subscribed to the ``graph`` event.

    Mirrors ``dispatch_ddos_notifications`` on purpose: one channel model, one
    delivery log shape, so operators learn the system once.
    """
    from . import integrations_v2 as iv2
    from .emails import deliver, wrap_html

    channels = await db.notif_channels.find(
        {"enabled": True, "events": {"$in": ["graph", "alerts"]}}).to_list(50)
    subject = _subject(alert)
    body = _body(alert, graph)
    text = (f"{subject}\nTarget: {alert.get('target', '')}\n"
            f"Nilai: {alert.get('value', '')} | Ambang: {alert.get('comparator', '')} "
            f"{alert.get('threshold', '')}\nSeverity: {alert.get('severity', '')}")
    notified: list[str] = []

    for ch in channels or []:
        target = ch.get("target", "")
        status = "skipped"
        if ch.get("type") == "email":
            try:
                r = await deliver(db, to_email=target, subject=subject,
                                  body_html=wrap_html(body), event_key="graph_alert")
                status = r.get("status", "failed")
            except Exception:  # noqa: BLE001
                status = "failed"
        elif ch.get("type") == "telegram":
            try:
                settings = await iv2.get_settings(db, "telegram")
                if settings and settings.get("enabled"):
                    chat_id = target if target and not target.startswith("@") else None
                    res = await iv2.TelegramNotifier(settings).send(text, chat_id=chat_id)
                    status = "sent" if res.get("ok") else "failed"
                else:
                    status = "skipped"
            except Exception:  # noqa: BLE001
                status = "failed"
        elif ch.get("type") == "webhook":
            try:
                import httpx as _hx
                payload = {"text": subject, "alert": {
                    "graph_id": alert.get("graph_id", ""), "graph_name": alert.get("graph_name", ""),
                    "target": alert.get("target", ""), "rule": alert.get("rule_name", ""),
                    "metric": alert.get("metric", ""), "value": alert.get("value"),
                    "threshold": alert.get("threshold"), "comparator": alert.get("comparator", ""),
                    "severity": alert.get("severity", ""), "state": alert.get("state", ""),
                    "fired_at": str(alert.get("fired_at", ""))}}
                async with _hx.AsyncClient(timeout=8.0) as c:
                    r = await c.post(target, json=payload)
                status = "sent" if r.status_code < 300 else f"failed ({r.status_code})"
            except Exception:  # noqa: BLE001
                status = "failed"

        # Single delivery-log shape (shared with the DDoS dispatcher). There is
        # no separate log_notification helper; write the row directly so a
        # missing helper can never silently swallow a dispatch.
        try:
            await db.ddos_notify_log.insert_one({
                "incident_id": alert.get("graph_id", ""), "target": alert.get("target", ""),
                "channel_type": ch.get("type", ""), "channel_target": target,
                "subject": subject, "status": status,
                "at": _now().isoformat(), "event": "graph_alert"})
        except Exception:  # noqa: BLE001
            logger.debug("[alerts] notify log write failed", exc_info=True)
        notified.append(f"{ch.get('type')}:{target}")

    if notified and alert.get("_id") is not None:
        try:
            await db[ALERTS_COLLECTION].update_one({"_id": alert["_id"]},
                                                   {"$set": {"notified": notified}})
        except Exception:  # noqa: BLE001
            logger.debug("[alerts] notified stamp failed", exc_info=True)
    return notified
