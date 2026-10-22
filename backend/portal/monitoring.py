"""Monitoring foundation: ping-based checks with Mongo lease and transition events.

This is the first phase of the MRTG + Network Map feature. It deliberately
contains no SNMP or graph UI yet; those come after the lease/state/sample
foundation is proven.
"""
import asyncio
import html as _html
import ipaddress
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional, Set

import httpx
from pymongo.errors import DuplicateKeyError

from portal import emails as emails_mod
from portal import integrations_v2 as iv2
from portal.diagnostics import resolve_ip, run_ping  # noqa: F401
from portal.emails import acquire_scheduler_lease, _release_scheduler_lease


def html_escape(value) -> str:
    """Escape operator-supplied text before it lands in an HTML email body."""
    return _html.escape(str(value if value is not None else ""))


logger = logging.getLogger("portal.monitoring")

_DEFAULT_INTERVAL_SECONDS = 300
_MIN_INTERVAL_SECONDS = 10
_MAX_INTERVAL_SECONDS = 3600


# ---------------------------------------------------------------------------
# Target validation (SSRF guard)
# ---------------------------------------------------------------------------
def validate_target(host: str, *, approved_internal: Optional[Set[str]] = None) -> str:
    """Return the host if it is acceptable for polling.

    Public IPs/hostnames are accepted. Loopback/private/link-local/reserved
    addresses are rejected unless explicitly listed in ``approved_internal``.
    """
    approved_internal = set(approved_internal or set())
    if host in approved_internal:
        return host

    # Try to interpret as an IP address first.
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        addr = None

    if addr is not None:
        if (addr.is_loopback or addr.is_private or addr.is_link_local
                or addr.is_reserved or addr.is_multicast):
            raise ValueError(f"Private/loopback/reserved/multicast target not allowed: {host}")
        # Shared address space (CGNAT, RFC 6598) also rejected by default
        if isinstance(addr, ipaddress.IPv4Address):
            if ipaddress.IPv4Address("100.64.0.0") <= addr <= ipaddress.IPv4Address("100.127.255.255"):
                raise ValueError(f"CGNAT target not allowed: {host}")
        return host

    # Hostname: reject obvious local-only names.
    lowered = host.lower()
    if lowered in {"localhost", "localhost.localdomain"}:
        raise ValueError(f"Local target not allowed: {host}")

    # Accept any other hostname.  DNS resolution is left to the actual probe so
    # that validation stays cheap and side-effect free.
    return host


# ---------------------------------------------------------------------------
# Probe execution
# ---------------------------------------------------------------------------
async def probe_target(db, *, target: str, check_id: str, owner: str,
                       timeout: float = 2.0, ttl_seconds: int = 10,
                       retries: int = 0, check_name: str = ""):
    """Run one ping check if we hold the scheduler lease.

    Writes a ``monitoring_probes`` sample, updates ``monitoring_check_state``,
    and emits a ``monitoring_events`` row only on a confirmed transition
    (up->down or down->up).  The first observation never emits an event to
    avoid storms when a new check is created.

    A failed probe inside the retry window moves the check to ``pending`` and
    emits nothing; only the *confirmed* state transition is an event.  That
    dedup is what stops a single lost ICMP packet from paging anyone.
    """
    retries = _check_retries(retries)
    lease_id = f"job:monitoring:{check_id}"
    acquired, current_owner = await acquire_scheduler_lease(
        db, lease_id=lease_id, owner=owner, ttl_seconds=ttl_seconds)
    if not acquired:
        logger.info("[monitoring] skip %s: held by %r", check_id, current_owner)
        return {"skipped": True, "owner": current_owner}

    try:
        validated = validate_target(target)
        # Resolve once, validate the exact address, and probe that address so a
        # hostname cannot pass validation then rebind to an internal target.
        probe_ip = resolve_ip(validated)
        validate_target(probe_ip)
        result = await run_ping(probe_ip, count=3, timeout=timeout)
        summary = (result or {}).get("summary") or {}
        received = int(summary.get("received") or 0)
        sent = int(summary.get("count") or 0)
        up = received > 0 and sent > 0

        sample = {
            "check_id": check_id,
            "target": validated,
            "resolved_ip": probe_ip,
            "at": datetime.now(timezone.utc),
            "up": up,
            "rtt_ms": summary.get("avg_ms"),
            "rtt_min_ms": summary.get("min_ms"),
            "rtt_max_ms": summary.get("max_ms"),
            "loss": summary.get("loss_percent"),
        }
        await db.monitoring_probes.insert_one(sample)

        prior = await db.monitoring_check_state.find_one({"check_id": check_id})
        prior_confirmed = _confirmed_status(prior)

        # Uptime-Kuma semantics: ``retries`` failed probes must be confirmed
        # before the check is declared DOWN.  During that window the check is
        # ``pending`` — visibly degraded, but not yet an outage, so a single
        # lost ICMP packet cannot page anyone.
        if up:
            new_status = "up"
            consecutive_failures = 0
        else:
            consecutive_failures = ((prior or {}).get("consecutive_failures") or 0) + 1
            new_status = "down" if consecutive_failures > retries else "pending"

        confirmed = new_status if new_status in ("up", "down") else prior_confirmed

        state_set = {
            "status": new_status,
            "confirmed_status": confirmed,
            "target": validated,
            "last_at": sample["at"],
            "last_rtt_ms": sample["rtt_ms"],
            "consecutive_failures": consecutive_failures,
            "retries": retries,
            "updated_at": datetime.now(timezone.utc),
        }

        # Only a change of the *confirmed* state is an event.  Entering
        # ``pending`` is not a transition, and neither is recovering from it —
        # otherwise every flap writes two events and pages twice.
        is_transition = (prior_confirmed is not None and confirmed is not None
                         and prior_confirmed != confirmed)

        if is_transition:
            # Compare-and-swap: the transition belongs to whichever worker
            # moves ``confirmed_status`` away from ``prior_confirmed`` first.
            # The per-check lease can expire mid-probe (slow ping, 10s TTL), so
            # two workers really can reach this point with the same prior
            # state; without the CAS they would emit two events with different
            # timestamps and page twice.  ``matched_count == 1`` is the claim.
            # Legacy rows predate ``confirmed_status`` and only carry
            # ``status`` — the $or keeps them claimable exactly once.
            claim = await db.monitoring_check_state.update_one(
                {"check_id": check_id,
                 "$or": [
                     {"confirmed_status": prior_confirmed},
                     {"confirmed_status": {"$exists": False},
                      "status": prior_confirmed},
                 ]},
                {"$set": state_set},
            )
            claimed = int(getattr(claim, "matched_count", 0) or 0) == 1
            if not claimed:
                # Lost the race: the peer already applied the transition and
                # owns its notification.  Still record this probe's own
                # observation, but never the confirmed state or the event.
                losers = {k: v for k, v in state_set.items()
                          if k not in ("confirmed_status", "status")}
                await db.monitoring_check_state.update_one(
                    {"check_id": check_id}, {"$set": losers})
                logger.info("[monitoring] transition already claimed for %s", check_id)
        else:
            claimed = False
            await db.monitoring_check_state.update_one(
                {"check_id": check_id}, {"$set": state_set}, upsert=True)

        event = None
        notified_channels: list[str] = []
        if is_transition and claimed:
            # Deterministic event id: the same transition observed twice (two
            # workers racing, or a retried probe) can only ever insert once,
            # because Mongo enforces uniqueness on ``_id``.  This is the
            # database-level half of the dedup; the confirmed-state comparison
            # above is the logic-level half.
            transition_key = (f"{check_id}:{prior_confirmed}->{confirmed}:"
                              f"{sample['at'].isoformat()}")
            event_doc = {
                "_id": transition_key,
                "check_id": check_id,
                "target": validated,
                "at": sample["at"],
                "from": prior_confirmed,
                "to": confirmed,
                "notified": False,
            }
            event_written = False
            try:
                await db.monitoring_events.insert_one(event_doc)
                event_written = True
            except DuplicateKeyError:
                # Another worker already recorded this exact transition; it is
                # also already being dispatched there.  Do not page twice.
                logger.info("[monitoring] duplicate transition ignored: %s", transition_key)
            except Exception:  # noqa: BLE001 - compensate, don't lose the alert
                # The CAS already committed ``confirmed_status`` above. If the
                # event write then fails (Mongo hiccup, disk full, etc.) and we
                # do nothing else, the new confirmed state silently "sticks":
                # the next probe compares against it, sees no further
                # transition, and the outage/recovery is never paged — a
                # silent alert loss. Roll the confirmed state back to
                # ``prior_confirmed`` so the NEXT probe observes the same
                # transition again and gets another chance to record+dispatch
                # it. This is a compensating action, not a second CAS: the
                # revert is CONDITIONAL on the row still holding the exact
                # value this probe wrote, so a peer that legitimately advanced
                # the state in the meantime is never clobbered.
                logger.exception(
                    "[monitoring] event insert failed for %s, rolling back "
                    "confirmed state to %r so the transition is retried",
                    check_id, prior_confirmed)
                try:
                    reverted = await db.monitoring_check_state.update_one(
                        {"check_id": check_id, "confirmed_status": confirmed},
                        {"$set": {
                            "status": prior_confirmed,
                            "confirmed_status": prior_confirmed,
                        }},
                    )
                    if int(getattr(reverted, "matched_count", 0) or 0) != 1:
                        logger.error(
                            "[monitoring] rollback skipped for %s: state no "
                            "longer holds %r (peer advanced it)", check_id, confirmed)
                except Exception:  # noqa: BLE001 - best-effort; already logged above
                    logger.exception(
                        "[monitoring] rollback after failed event insert also "
                        "failed for %s", check_id)

            if event_written:
                event = confirmed
                # Immediate dispatch is bounded by the channel query (50
                # channels).  The event is persisted before delivery, so a
                # future worker can retry rows whose ``notified`` remains false.
                try:
                    notified_channels = await dispatch_monitoring_alert(
                        db, check={"name": check_name or check_id, "target": validated},
                        event=event_doc)
                except Exception:  # noqa: BLE001 - never lose the state transition
                    logger.exception("[monitoring] alert dispatch failed for %s", check_id)
                try:
                    await db.monitoring_events.update_one(
                        {"_id": transition_key},
                        {"$set": {
                            "notified": bool(notified_channels),
                            "notified_channels": notified_channels,
                            # The initial immediate delivery is attempt #1.
                            "notify_attempts": 1,
                            "notified_at": datetime.now(timezone.utc) if notified_channels else None,
                        }},
                    )
                except Exception:  # noqa: BLE001
                    logger.debug("[monitoring] notified stamp failed", exc_info=True)

        return {
            "status": new_status,
            "confirmed_status": confirmed,
            "up": up,
            "event": event,
            "notified_channels": notified_channels,
            "rtt_ms": sample["rtt_ms"],
            "loss": sample["loss"],
        }
    finally:
        try:
            await _release_scheduler_lease(db, lease_id=lease_id, owner=owner)
        except Exception:
            logger.exception("[monitoring] release failed for %s", check_id)


# ---------------------------------------------------------------------------
# Confirmed-state helpers
# ---------------------------------------------------------------------------
def _confirmed_status(state: Optional[dict]) -> Optional[str]:
    """Return the last *confirmed* status, tolerating legacy documents.

    Legacy rows only carry ``status``; those were written before ``pending``
    existed, so every historical value is by definition confirmed.
    """
    if not state:
        return None
    confirmed = state.get("confirmed_status")
    if confirmed in ("up", "down"):
        return confirmed
    status = state.get("status")
    if status in ("up", "down"):
        return status
    return None


# ---------------------------------------------------------------------------
# Alert dispatch (transition-only, shared notif-channel model)
# ---------------------------------------------------------------------------
async def dispatch_monitoring_alert(db, *, check: dict, event: dict) -> list:
    """Notify every channel subscribed to the ``monitoring`` event.

    Returns the list of ``type:target`` channels that were **actually
    delivered to**, not merely attempted.  A channel whose ``deliver`` raises
    or returns a non-``sent`` status is logged (``ddos_notify_log`` keeps the
    per-channel status) but excluded from the return value, so the caller can
    stamp ``notified`` truthfully instead of claiming a page went out because
    we tried.

    This deliberately diverges from ``dispatch_graph_alert``, which appends
    every channel regardless of outcome; the monitoring path must be honest
    because ``notified`` drives whether an operator still needs to act.

    ``deliver()`` returns ``status="skipped"`` when SMTP is not configured —
    that is *not* a delivery, so a skipped channel never counts as notified.
    """
    try:
        channels = await db.notif_channels.find(
            {"enabled": True, "events": {"$in": ["monitoring", "alerts", "uptime"]}}
        ).to_list(50)
    except Exception:  # noqa: BLE001
        logger.debug("[monitoring] channel lookup failed", exc_info=True)
        return []

    down = (event.get("to") == "down")
    name = str(check.get("name") or check.get("_id") or "check")
    target = str(check.get("target") or event.get("target") or "")
    verb = "DOWN" if down else "RECOVERED"
    subject = f"[Monitoring] {name} is {verb}"
    text = (f"{subject}\nTarget: {target}\n"
            f"From: {event.get('from')} → To: {event.get('to')}\n"
            f"At: {event.get('at')}")
    color = "#dc2626" if down else "#059669"
    # Check names/targets are operator-supplied, so escape everything that
    # lands in the HTML body.  Without this a check named
    # ``<img src=x onerror=...>`` would be rendered by the mail client.
    safe_name = html_escape(name)
    safe_target = html_escape(target)
    safe_from = html_escape(str(event.get("from") or ""))
    safe_to = html_escape(str(event.get("to") or ""))
    safe_at = html_escape(str(event.get("at") or ""))
    body = (f'<h2 style="color:{color};margin:0 0 8px 0">Check {verb}</h2>'
            f'<p style="margin:0 0 12px 0">Ping check <b>{safe_name}</b> transitioned '
            f'to <b style="color:{color}">{safe_to}</b>.</p>'
            f'<table style="width:100%;border-collapse:collapse;font-size:13px">'
            f'<tr><td style="padding:6px 0;color:#64748b;width:130px">Target</td>'
            f'<td>{safe_target}</td></tr>'
            f'<tr><td style="padding:6px 0;color:#64748b">From</td>'
            f'<td>{safe_from}</td></tr>'
            f'<tr><td style="padding:6px 0;color:#64748b">At</td>'
            f'<td>{safe_at}</td></tr></table>'
            f'<p style="margin-top:16px;font-size:12px;color:#64748b">Alerts fire '
            f'only on confirmed transitions, so you get one message per state '
            f'change (no flap-storm).</p>')

    delivered: list[str] = []
    for ch in channels or []:
        ch_target = ch.get("target", "")
        status = "skipped"
        ctype = ch.get("type")
        ok = False
        if ctype == "email":
            try:
                r = await emails_mod.deliver(
                db, to_email=ch_target, subject=subject,
                body_html=emails_mod.wrap_html(body), event_key="monitoring_alert")
                status = (r or {}).get("status", "failed")
                ok = status == "sent"
            except Exception:  # noqa: BLE001
                logger.debug("[monitoring] email dispatch failed", exc_info=True)
                status = "failed"
        elif ctype == "telegram":
            try:
                settings = await iv2.get_settings(db, "telegram")
                if settings and settings.get("enabled"):
                    chat_id = ch_target if ch_target and not ch_target.startswith("@") else None
                    res = await iv2.TelegramNotifier(settings).send(text, chat_id=chat_id)
                    ok = bool((res or {}).get("ok"))
                    status = "sent" if ok else "failed"
                else:
                    status = "skipped"
            except Exception:  # noqa: BLE001
                logger.debug("[monitoring] telegram dispatch failed", exc_info=True)
                status = "failed"
        elif ctype == "webhook":
            try:
                payload = {"text": subject, "event": "monitoring_alert",
                           "check": {"name": name, "target": target},
                           "transition": {"from": event.get("from"), "to": event.get("to"),
                                          "at": str(event.get("at", ""))}}
                async with httpx.AsyncClient(timeout=8.0) as c:
                    r = await c.post(ch_target, json=payload)
                ok = r.status_code < 300
                status = "sent" if ok else f"failed ({r.status_code})"
            except Exception:  # noqa: BLE001
                logger.debug("[monitoring] webhook dispatch failed", exc_info=True)
                status = "failed"

        # Same delivery-log shape as the DDoS and graph dispatchers.
        try:
            await db.ddos_notify_log.insert_one({
                "incident_id": str(event.get("check_id", "")), "target": target,
                "channel_type": ctype or "", "channel_target": ch_target,
                "subject": subject, "status": status,
                "at": datetime.now(timezone.utc).isoformat(),
                "event": "monitoring_alert"})
        except Exception:  # noqa: BLE001
            logger.debug("[monitoring] notify log write failed", exc_info=True)
        if ok:
            delivered.append(f"{ctype}:{ch_target}")

    return delivered


# ---------------------------------------------------------------------------
# Bounded retry of undelivered transition alerts
# ---------------------------------------------------------------------------
# Design note (durable outbox vs immediate dispatch):
#
# The event row is written *before* any delivery attempt, so a confirmed DOWN
# is never lost to a crash mid-dispatch — that is the durability we actually
# need.  We deliberately do NOT add a separate outbox collection: the event row
# already carries everything a delivery needs (check id, target, from, to, at)
# plus ``notified``/``notify_attempts``, so a second collection would only add
# a second thing to keep consistent.
#
# Delivery is at-least-once, never exactly-once: if the process dies after the
# SMTP/Telegram/webhook hand-off but before ``notified`` is stamped, the retry
# sweep will send it again.  That is the correct trade for alerting (a
# duplicate page is far cheaper than a missed outage) and we do not pretend
# otherwise.
_MAX_NOTIFY_ATTEMPTS = 5
_RETRY_DEFAULT_LIMIT = 10
_RETRY_MAX_AGE_HOURS = 24
# How long a retry-dispatch claim on a single event row is held, and how often
# it is renewed while the dispatch is still running.  A fixed lease alone is not
# enough: ``dispatch_monitoring_alert`` walks up to 50 channels sequentially and
# a single unreachable SMTP host costs the 15s ``smtplib`` timeout, so a slow
# storm can outlast any fixed lease and let a peer double-page.  The heartbeat
# keeps extending OUR claim (matched by token) for as long as we are actually
# dispatching, and a crashed worker stops renewing so its claim expires.
_NOTIFY_CLAIM_LEASE = timedelta(seconds=30)
_NOTIFY_CLAIM_RENEW_SECONDS = 10.0


async def _renew_claim_forever(db, event_id, token: str, stop: "asyncio.Event") -> None:
    """Keep ``notify_claimed_until`` in the future while a dispatch runs."""
    while True:
        try:
            await asyncio.wait_for(stop.wait(), timeout=_NOTIFY_CLAIM_RENEW_SECONDS)
            return
        except asyncio.TimeoutError:
            pass
        except asyncio.CancelledError:
            raise
        try:
            await db.monitoring_events.update_one(
                {"_id": event_id, "notify_claim_token": token},
                {"$set": {"notify_claimed_until":
                          datetime.now(timezone.utc) + _NOTIFY_CLAIM_LEASE}},
            )
        except Exception:  # noqa: BLE001 - a lost renewal only risks a duplicate page
            logger.debug("[monitoring] claim renewal failed", exc_info=True)


async def retry_undelivered_monitoring_alerts(db, *, limit: int = _RETRY_DEFAULT_LIMIT,
                                              max_age_hours: int = _RETRY_MAX_AGE_HOURS,
                                              now: Optional[datetime] = None,
                                              check_names: Optional[dict] = None) -> dict:
    """Re-dispatch a bounded number of transition events that never landed.

    Called from the probe sweep so a transient SMTP/Telegram/webhook outage is
    healed on the next tick without a separate scheduler.  Bounded three ways:

    * at most ``limit`` events per call (no storm after a long outage),
    * only events younger than ``max_age_hours`` (stale pages are noise),
    * at most ``_MAX_NOTIFY_ATTEMPTS`` delivery rounds per event, after which
      the row is marked ``notify_exhausted`` and left for an operator.

    Returns a summary dict; never raises.
    """
    now = _as_utc(now) or datetime.now(timezone.utc)
    try:
        limit = max(1, min(int(limit), 50))
        max_age_hours = max(1, min(int(max_age_hours), 24 * 7))
    except (TypeError, ValueError):
        return {"scanned": 0, "sent": 0, "failed": 0, "exhausted": 0, "error": "bad limit"}

    cutoff = now - timedelta(hours=max_age_hours)
    summary = {"scanned": 0, "sent": 0, "failed": 0, "exhausted": 0}
    try:
        # ``notify_exhausted`` rows are parked for an operator: they must NOT
        # consume the limit.  Without this filter a backlog of exhausted rows
        # (sorted oldest-first) starves genuinely fresh undelivered events —
        # they would never be retried (verified ad-hoc before this fix).
        events = await db.monitoring_events.find(
            {"notified": False, "notify_exhausted": {"$ne": True},
             "at": {"$gte": cutoff}}
        ).sort("at", 1).to_list(limit)
    except Exception:  # noqa: BLE001
        logger.debug("[monitoring] retry scan failed", exc_info=True)
        return summary

    for ev in events or []:
        summary["scanned"] += 1
        attempts = int(ev.get("notify_attempts") or 0)
        if attempts >= _MAX_NOTIFY_ATTEMPTS:
            summary["exhausted"] += 1
            try:
                await db.monitoring_events.update_one(
                    {"_id": ev.get("_id")}, {"$set": {"notify_exhausted": True}})
            except Exception:  # noqa: BLE001
                logger.debug("[monitoring] exhaustion stamp failed", exc_info=True)
            continue

        check_id = str(ev.get("check_id") or "")
        name = (check_names or {}).get(check_id) or check_id or "check"

        # Claim the event before dispatching: concurrent retry sweeps (two
        # workers, or an overlapping tick) must not both page for the same row.
        # A plain compare-and-set on ``notify_attempts`` is NOT a lock — a peer
        # that reads the value we just wrote would match and page too.  So the
        # claim is a short lease: the row is only claimable while no live claim
        # is held, and the lease is released (moved into the past) after the
        # dispatch finishes, whether it succeeded or not.
        claim_filter: dict = {
            "_id": ev.get("_id"),
            "notified": False,
            "notify_exhausted": {"$ne": True},
            "$or": [
                {"notify_claimed_until": {"$lt": now}},
                {"notify_claimed_until": {"$exists": False}},
            ],
        }
        claim_token = uuid.uuid4().hex
        claim = await db.monitoring_events.update_one(
            claim_filter,
            {"$set": {"notify_claimed_until": now + _NOTIFY_CLAIM_LEASE,
                      "notify_claim_token": claim_token}},
        )
        if int(getattr(claim, "matched_count", 0) or 0) != 1:
            # Another worker holds the claim (or already delivered) this row.
            logger.info("[monitoring] retry already claimed: %s", ev.get("_id"))
            continue

        # Renew the claim while dispatching so a slow channel storm cannot let
        # the lease lapse mid-dispatch and hand the row to a peer.
        stop_renew = asyncio.Event()
        renewer = asyncio.create_task(
            _renew_claim_forever(db, ev.get("_id"), claim_token, stop_renew))
        try:
            delivered = await dispatch_monitoring_alert(
                db, check={"name": name, "target": ev.get("target") or ""}, event=ev)
        except Exception:  # noqa: BLE001 - one bad channel must not stop the sweep
            logger.exception("[monitoring] retry dispatch failed for %s", check_id)
            delivered = []
        finally:
            stop_renew.set()
            renewer.cancel()
            try:
                await renewer
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass

        update: dict = {"notify_attempts": attempts + 1,
                        "notify_claimed_until": now - timedelta(seconds=1)}
        if delivered:
            update.update({"notified": True, "notified_channels": delivered,
                           "notified_at": now})
            summary["sent"] += 1
        else:
            update["last_notify_error"] = "no channel delivered"
            summary["failed"] += 1
            if attempts + 1 >= _MAX_NOTIFY_ATTEMPTS:
                update["notify_exhausted"] = True
                summary["exhausted"] += 1
        try:
            # Only release a claim this worker still owns.
            await db.monitoring_events.update_one(
                {"_id": ev.get("_id"), "notify_claim_token": claim_token},
                {"$set": update, "$unset": {"notify_claim_token": ""}})
        except Exception:  # noqa: BLE001
            logger.debug("[monitoring] retry stamp failed", exc_info=True)

    return summary


# ---------------------------------------------------------------------------
# Uptime accounting (Uptime-Kuma style: expected vs observed)
# ---------------------------------------------------------------------------
# Inline walk cap.  A 720h window at the 10s floor owes 259,200 slots and can
# hold as many samples, so we never blindly materialise the cursor: up to this
# many rows we walk them in Python (cheap, exact), above it we switch to a
# server-side ``$group`` so nothing is silently dropped.
_UPTIME_INLINE_SAMPLE_CAP = 20000
_UPTIME_MIN_HOURS = 1
_UPTIME_MAX_HOURS = 720


async def uptime_summary(db, *, check_id: str, hours: int = 24,
                         now: Optional[datetime] = None) -> dict:
    """Compute uptime from the expected schedule vs the samples we observed.

    Honesty rules — these are the reason this function exists:

    * ``expected`` is how many probes the schedule *owed* in the window, not
      how many rows happen to exist.  A stalled scheduler therefore shows up
      as ``gaps`` instead of a fake 100%.
    * A gap is *unknown*, not DOWN.  ``down`` only counts slots in which a
      probe actually ran and failed, so "the service was down" and "nobody
      looked" stay distinguishable.  ``uptime_pct`` is measured over observed
      slots (``None`` when nothing was observed); ``coverage_pct`` says how
      much of the window was observed; ``uptime_pct_conservative`` charges
      gaps as downtime and is the number to quote when in doubt.
    * Each slot is backed by at most one sample — the last sample that falls
      inside it.  A sample is never reused to fill later slots, so one probe
      cannot paint a whole window green.
    * The window never starts before the check was created, so a brand-new
      check is not reported as 0% for hours in which it did not exist.
    * Large windows are handled explicitly: above
      ``_UPTIME_INLINE_SAMPLE_CAP`` samples we aggregate in Mongo and report
      ``mode="aggregated"``; rows are never truncated silently.

    ``now`` is injectable so tests run on a deterministic clock.  ``hours``
    must be an int in 1..720; anything else raises ``ValueError`` instead of
    being silently clamped into a plausible-looking answer.
    """
    hours = _validate_hours(hours)

    doc = await db.monitoring_checks.find_one({"_id": _oid_check(check_id)})
    if doc is None:
        raise ValueError(f"check not found: {check_id}")
    interval = _check_interval(doc.get("interval_seconds"))

    now = _as_utc(now) or datetime.now(timezone.utc)
    requested_start = now - timedelta(hours=hours)
    created_at = _as_utc(doc.get("created_at"))
    window_start = max(requested_start, created_at) if created_at else requested_start
    if window_start > now:
        window_start = now

    # Only fully elapsed intervals are "expected".  The interval we are inside
    # right now has not been missed yet; counting it would open every window
    # with a phantom gap.
    expected_slots = max(0, int((now - window_start).total_seconds() // interval))

    rows = await db.monitoring_probes.find(
        {"check_id": check_id, "at": {"$gte": window_start}}
    ).sort("at", 1).to_list(_UPTIME_INLINE_SAMPLE_CAP + 1)

    if len(rows) > _UPTIME_INLINE_SAMPLE_CAP:
        counted = await _uptime_count_aggregated(
            db, check_id=check_id, window_start=window_start,
            interval=interval, expected_slots=expected_slots)
        mode = "aggregated"
        samples_scanned = None
    else:
        counted = _uptime_count_inline(rows, window_start=window_start,
                                       interval=interval, expected_slots=expected_slots)
        mode = "inline"
        samples_scanned = len(rows)

    up_slots = counted["up"]
    down_slots = counted["down"]
    observed = up_slots + down_slots
    gap_slots = max(0, expected_slots - observed)

    return {
        "check_id": check_id,
        "window_hours": hours,
        "window_start": window_start,
        "window_end": now,
        "interval_seconds": interval,
        "expected": expected_slots,
        "up": up_slots,
        "down": down_slots,
        "gaps": gap_slots,
        "observed": observed,
        "uptime_pct": round(up_slots / observed * 100.0, 2) if observed else None,
        "coverage_pct": round(observed / expected_slots * 100.0, 2) if expected_slots else 0.0,
        "uptime_pct_conservative": (
            round(up_slots / expected_slots * 100.0, 2) if expected_slots else None),
        "avg_rtt_ms": (round(counted["rtt_sum"] / counted["rtt_count"], 2)
                       if counted["rtt_count"] else None),
        "mode": mode,
        "samples_scanned": samples_scanned,
        # Kept for API compatibility.  Streaming/aggregation means no window is
        # ever silently truncated, so this is always False.
        "truncated": False,
    }


def _uptime_count_inline(rows, *, window_start: datetime, interval: int,
                         expected_slots: int) -> dict:
    """Assign each sample to at most one slot and count up/down per slot.

    ``rows`` is ascending by ``at``.  We advance a cursor over the samples and
    over the slots in lockstep, so a sample can only ever be consumed by the
    slot it physically falls into.
    """
    up = down = 0
    rtt_sum = 0.0
    rtt_count = 0
    idx = 0
    n = len(rows)

    for slot in range(expected_slots):
        slot_start = window_start + timedelta(seconds=slot * interval)
        slot_end = slot_start + timedelta(seconds=interval)
        # Drop samples that cannot belong to this or any later slot.
        while idx < n:
            at = _sample_at(rows[idx])
            if at is None or at < slot_start:
                idx += 1
                continue
            break
        if idx >= n:
            break
        at = _sample_at(rows[idx])
        if at >= slot_end:
            # Nothing observed in this slot; the next sample belongs to a
            # later slot.  This is a gap (unknown), not a failure.
            continue
        # Exactly one sample backs this slot: the last one inside it.
        last = rows[idx]
        idx += 1
        while idx < n:
            nxt = _sample_at(rows[idx])
            if nxt is None:
                idx += 1
                continue
            if nxt >= slot_end:
                break
            last = rows[idx]
            idx += 1
        if last.get("up"):
            up += 1
            rtt = last.get("rtt_ms")
            if isinstance(rtt, (int, float)):
                rtt_sum += float(rtt)
                rtt_count += 1
        else:
            down += 1

    return {"up": up, "down": down, "rtt_sum": rtt_sum, "rtt_count": rtt_count}


async def _uptime_count_aggregated(db, *, check_id: str, window_start: datetime,
                                   interval: int, expected_slots: int) -> dict:
    """Count observed slots server-side for windows too large to inline.

    Groups raw samples by slot index and keeps the last sample of each slot,
    matching ``_uptime_count_inline`` exactly.  Memory on the client is one
    row per *observed* slot, never per sample, and no sample is dropped.
    """
    pipeline = [
        {"$match": {"check_id": check_id, "at": {"$gte": window_start}}},
        {"$sort": {"at": 1}},
        {"$group": {
            "_id": {"$toLong": {"$floor": {"$divide": [
                {"$subtract": ["$at", window_start]}, interval * 1000]}}},
            "up": {"$last": "$up"},
            "rtt_ms": {"$last": "$rtt_ms"},
        }},
        {"$match": {"_id": {"$gte": 0, "$lt": expected_slots}}},
    ]
    cursor = db.monitoring_probes.aggregate(pipeline)
    up = down = 0
    rtt_sum = 0.0
    rtt_count = 0
    async for bucket in cursor:
        if bucket.get("up"):
            up += 1
            rtt = bucket.get("rtt_ms")
            if isinstance(rtt, (int, float)):
                rtt_sum += float(rtt)
                rtt_count += 1
        else:
            down += 1
    return {"up": up, "down": down, "rtt_sum": rtt_sum, "rtt_count": rtt_count}


def _validate_hours(value) -> int:
    """Strict hours validation: reject rather than silently clamp."""
    if isinstance(value, bool):
        raise ValueError("hours must be an integer")
    try:
        hours = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("hours must be an integer") from exc
    if not _UPTIME_MIN_HOURS <= hours <= _UPTIME_MAX_HOURS:
        raise ValueError(
            f"hours must be between {_UPTIME_MIN_HOURS} and {_UPTIME_MAX_HOURS}")
    return hours


def _as_utc(value) -> Optional[datetime]:
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _sample_at(sample: dict) -> Optional[datetime]:
    return _as_utc(sample.get("at"))


def _oid_check(check_id: str):
    from bson import ObjectId
    try:
        return ObjectId(check_id)
    except Exception:  # noqa: BLE001 - non-ObjectId synthetic ids in tests
        return check_id


def _state_last_at(value) -> Optional[datetime]:
    """Normalize a persisted probe timestamp; malformed values are unknown."""
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _check_interval(value) -> int:
    """Use a safe interval even for legacy or manually edited documents."""
    try:
        interval = int(value)
    except (TypeError, ValueError):
        interval = _DEFAULT_INTERVAL_SECONDS
    return max(_MIN_INTERVAL_SECONDS, min(_MAX_INTERVAL_SECONDS, interval))


def _check_retries(value) -> int:
    """Confirm-N-failures threshold, clamped to a sane range.

    Zero keeps the legacy behaviour (first failed probe is DOWN) for rows
    written before Uptime-Kuma semantics existed; new checks default to 1.
    """
    try:
        retries = int(value if value is not None else 0)
    except (TypeError, ValueError):
        retries = 0
    return max(0, min(10, retries))


async def run_monitoring_probe_sweep(db, *, owner: str,
                                     now: Optional[datetime] = None,
                                     timeout: float = 2.0) -> dict:
    """Probe each enabled monitoring check that is due.

    A failure in one check is isolated so it cannot stop the remaining checks.
    ``probe_target`` provides a per-check Mongo lease in addition to the outer
    scheduler lease used by ``start_scheduler``.
    """
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    else:
        now = now.astimezone(timezone.utc)

    checks = await db.monitoring_checks.find({"enabled": True}).to_list(500)
    summary = {
        "checked": len(checks),
        "probed": 0,
        "skipped_not_due": 0,
        "errors": 0,
    }
    # Map check_id -> name so a retried alert keeps a human-readable subject.
    check_names = {str(c.get("_id") or ""): str(c.get("name") or "") for c in checks}
    for check in checks:
        check_id = str(check.get("_id") or "")
        target = str(check.get("target") or "").strip()
        try:
            state = await db.monitoring_check_state.find_one({"check_id": check_id})
            last_at = _state_last_at((state or {}).get("last_at"))
            interval = _check_interval(check.get("interval_seconds"))
            if last_at is not None and last_at <= now:
                if last_at + timedelta(seconds=interval) > now:
                    summary["skipped_not_due"] += 1
                    continue

            result = await probe_target(
                db,
                target=target,
                check_id=check_id,
                owner=owner,
                timeout=timeout,
                retries=_check_retries(check.get("retries")),
                check_name=str(check.get("name") or ""),
            )
            if not result.get("skipped"):
                summary["probed"] += 1
        except Exception:  # noqa: BLE001 - isolate failures per configured check
            summary["errors"] += 1
            logger.exception("[monitoring] probe failed for check %s", check_id)

    # Heal transient notification outages: re-dispatch a bounded number of
    # transition events that were persisted but never delivered.  Isolated so a
    # retry problem cannot affect the probe summary.
    try:
        summary["retried"] = await retry_undelivered_monitoring_alerts(
            db, now=now, check_names=check_names)
    except Exception:  # noqa: BLE001
        logger.exception("[monitoring] alert retry sweep failed")
    return summary
