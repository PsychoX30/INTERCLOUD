"""Monitoring foundation: ping-based checks with Mongo lease and transition events.

This is the first phase of the MRTG + Network Map feature. It deliberately
contains no SNMP or graph UI yet; those come after the lease/state/sample
foundation is proven.
"""
import ipaddress
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, Set

from portal.diagnostics import resolve_ip, run_ping  # noqa: F401
from portal.emails import acquire_scheduler_lease, _release_scheduler_lease

logger = logging.getLogger("portal.monitoring")

_DEFAULT_INTERVAL_SECONDS = 300
_MIN_INTERVAL_SECONDS = 30
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
                       timeout: float = 2.0, ttl_seconds: int = 300):
    """Run one ping check if we hold the scheduler lease.

    Writes a ``monitoring_probes`` sample, updates ``monitoring_check_state``,
    and emits a ``monitoring_events`` row only on a confirmed transition
    (up->down or down->up).  The first observation never emits an event to
    avoid storms when a new check is created.
    """
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
            "loss": summary.get("loss_percent"),
        }
        await db.monitoring_probes.insert_one(sample)

        prior = await db.monitoring_check_state.find_one({"check_id": check_id})
        prior_status = prior.get("status") if prior else None

        if up:
            new_status = "up"
            consecutive_failures = 0
        else:
            new_status = "down"
            consecutive_failures = ((prior or {}).get("consecutive_failures") or 0) + 1

        await db.monitoring_check_state.update_one(
            {"check_id": check_id},
            {"$set": {
                "status": new_status,
                "target": validated,
                "last_at": sample["at"],
                "last_rtt_ms": sample["rtt_ms"],
                "consecutive_failures": consecutive_failures,
                "updated_at": datetime.now(timezone.utc),
            }},
            upsert=True,
        )

        event = None
        if prior_status is not None and prior_status != new_status:
            event_doc = {
                "check_id": check_id,
                "target": validated,
                "at": sample["at"],
                "from": prior_status,
                "to": new_status,
            }
            await db.monitoring_events.insert_one(event_doc)
            event = new_status

        return {
            "status": new_status,
            "up": up,
            "event": event,
            "rtt_ms": sample["rtt_ms"],
            "loss": sample["loss"],
        }
    finally:
        try:
            await _release_scheduler_lease(db, lease_id=lease_id, owner=owner)
        except Exception:
            logger.exception("[monitoring] release failed for %s", check_id)


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
            )
            if not result.get("skipped"):
                summary["probed"] += 1
        except Exception:  # noqa: BLE001 - isolate failures per configured check
            summary["errors"] += 1
            logger.exception("[monitoring] probe failed for check %s", check_id)
    return summary
