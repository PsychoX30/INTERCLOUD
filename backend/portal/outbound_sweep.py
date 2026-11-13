"""Outbound detection sweep — the wiring between flows, config and routers.

Kept out of ``emails.py`` for two reasons: that module is already the largest in
the backend, and this logic must be callable from a test without an APScheduler,
a mailer or a router.

The sweep is deliberately split into *decide* and *act*:

``evaluate_window``   pure — flows in, scores out.  Runs in ``shadow`` mode too.
``persist_scores``    records what was seen, including "would have blocked".
``enforce_decisions`` the only part that writes to a router, reached only when
                      ``mode == "enforce"`` and the score cleared every gate.

That split is what makes a safe rollout possible: ``shadow`` runs the identical
decision path and records ``would_block`` without ever touching an enforcer.
"""
from __future__ import annotations

import asyncio
import ipaddress
import logging
from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional

from . import outbound_detector as detect
from . import outbound_guard as guard

log = logging.getLogger("portal.outbound_sweep")

CONFIG_ID = "outbound-default"
CONFIG_CACHE_S = 30.0
STATE_COLLECTION = "ddos_outbound_state"
SHADOW_COLLECTION = "ddos_outbound_shadow"

_config_cache: dict = {"doc": None, "at": 0.0}
_tracker = detect.OutboundTracker()


async def load_config(db, *, force: bool = False) -> dict:
    """Return the merged outbound config, cached for ``CONFIG_CACHE_S``.

    The cache exists because the sweep runs every 10 seconds across two worker
    processes; without it every tick would issue a Mongo read per worker. 30
    seconds is short enough that an operator's UI change takes effect within
    one sweep-cycle they can see.
    """
    import time
    now = time.monotonic()
    if not force and _config_cache["doc"] is not None and (
            now - _config_cache["at"]) < CONFIG_CACHE_S:
        return _config_cache["doc"]
    stored = None
    try:
        stored = await db.ddos_detection_config.find_one({"_id": CONFIG_ID})
    except Exception:  # noqa: BLE001
        stored = None
    cfg = detect.merge_config(stored)
    _config_cache["doc"] = cfg
    _config_cache["at"] = now
    return cfg


def invalidate_config_cache() -> None:
    _config_cache["doc"] = None
    _config_cache["at"] = 0.0


async def load_overrides(db) -> dict[str, list[dict]]:
    """Per-target overrides, grouped by target, expired rows filtered out."""
    out: dict[str, list[dict]] = {}
    now = datetime.now(timezone.utc)
    try:
        async for row in db.ddos_detection_overrides.find({}):
            expires = row.get("expires_at")
            if isinstance(expires, datetime):
                if expires.tzinfo is None:
                    expires = expires.replace(tzinfo=timezone.utc)
                if expires <= now:
                    continue
            target = str(row.get("target") or "")
            if target:
                out.setdefault(target, []).append(row)
    except Exception:  # noqa: BLE001
        return {}
    return out


def _mine_fn(scope_prefixes: list[str]):
    nets = []
    for raw in scope_prefixes:
        try:
            nets.append(ipaddress.ip_network(raw, strict=False))
        except ValueError:
            continue

    def _mine(ip: str) -> bool:
        try:
            addr = ipaddress.ip_address(ip)
        except ValueError:
            return False
        return any(addr.version == n.version and addr in n for n in nets)

    return _mine, bool(nets)


def outbound_candidates(rate_rows: Iterable, scope_prefixes: list[str]) -> dict[str, list]:
    """Group flows by the *source* IP when the source is ours and the sink is not.

    This is the inverse of inbound aggregation: the protected asset is the
    reputation of the whole network, and the thing that must stop is the packet
    leaving.  Interior traffic (ours to ours) is excluded — lateral abuse is a
    policy problem, not an internet-facing one, and blocking the source would
    cut an internal service.
    """
    _mine, ok = _mine_fn(scope_prefixes)
    if not ok:
        return {}
    buckets: dict[str, list] = {}
    for flow in rate_rows:
        view = detect.flow_view(flow)
        if view is None or not view.src or not view.dst:
            continue
        if not _mine(view.src) or _mine(view.dst):
            continue
        buckets.setdefault(view.src, []).append(flow)
    return buckets


def reply_counts(rate_rows: Iterable, scope_prefixes: list[str]) -> dict[str, float]:
    """SYN-ACK packets that came *back* to each of our IPs in this window.

    Kept separate from :func:`outbound_candidates` because the reply travels in
    the opposite direction: its source is the remote peer, so it can never be
    found by grouping flows by our own address.  Without this, S4 ("SYNs out,
    no SYN-ACKs back") is true for every source that sends any SYNs at all —
    it degenerates into a volume test and would block legitimate servers.
    """
    _mine, ok = _mine_fn(scope_prefixes)
    if not ok:
        return {}
    replies: dict[str, float] = {}
    for flow in rate_rows:
        view = detect.flow_view(flow)
        if view is None or not view.dst or not view.src:
            continue
        if _mine(view.src) or not _mine(view.dst):
            continue
        flags = int(view.tcp_flags or 0)
        if (flags & 0x02) and (flags & 0x10):      # SYN+ACK
            replies[view.dst] = replies.get(view.dst, 0.0) + float(view.packets or 0)
    return replies


def evaluate_window(buckets: dict[str, list], window_s: float, cfg: dict,
                    overrides: Optional[dict] = None,
                    replies: Optional[dict[str, float]] = None) -> list[detect.Score]:
    """Measure and score every outbound source in one window.

    Per-target overrides are applied to the *config* used for that target, so a
    customer with an approved bulk-transfer profile can be tuned without
    loosening the thresholds for everyone else.  ``replies`` carries the
    SYN-ACK counts measured in the opposite direction; see
    :func:`reply_counts`.
    """
    overrides = overrides or {}
    replies = replies or {}
    scores: list[detect.Score] = []
    for target, flows in buckets.items():
        target_cfg = cfg
        if overrides.get(target):
            target_cfg = detect.apply_overrides(cfg, overrides[target])
        metrics = detect.measure(target, flows, window_s,
                                 small_packet_bytes=int(target_cfg["small_packet_bytes"]),
                                 inbound_replies=float(replies.get(target) or 0.0))
        scores.append(detect.score_window(metrics, target_cfg))
    return scores


async def _bump_state(db, target: str, *, consecutive: int, score: int,
                      now: datetime) -> None:
    """Remember the streak so a single noisy window cannot reach the threshold.

    ``target`` is duplicated out of ``_id`` on purpose: every other collection
    stores the address in a field, and a reader that unions incident, shadow and
    state rows should not have to know that this one kept it only in the key.
    """
    await db[STATE_COLLECTION].update_one(
        {"_id": target},
        {"$set": {"target": target, "consecutive": consecutive, "score": score,
                  "updated_at": now}},
        upsert=True,
    )


async def persist_scores(db, scores: list[detect.Score], cfg: dict,
                         now: datetime, *, direction: str = "outbound",
                         authoritative: bool = True) -> dict:
    """Record the window for review, then advance the persistence counter.

    Writes are batched with ``insert_many`` on purpose: the previous sweep
    issued one insert per target and held the event loop for seconds, which is
    what let the collector file grow between ticks.

    Only non-gated targets with at least one signal are stored. Storing all 225
    idle targets every 10 seconds would recreate the 1.49M-row problem, and an
    all-zero row carries no information an operator can act on.
    """
    interest = [s for s in scores if not s.signals.get("gated") and s.score > 0]
    updated: list[detect.Score] = []
    for score in _tracker.update(interest, cfg):
        updated.append(score)
        await _bump_state(db, score.target, consecutive=_tracker.consecutive(score.target),
                          score=score.score, now=now)

    docs = []
    for score in updated:
        doc = score.to_doc()
        doc.update({
            "at": now,
            "direction": direction,
            "mode": cfg.get("mode"),
            "key": f"{direction}:{score.target}",
            "authoritative": bool(authoritative),
        })
        docs.append(doc)
    if docs:
        try:
            await db[SHADOW_COLLECTION].insert_many(docs, ordered=False)
        except Exception:  # noqa: BLE001
            log.exception("[outbound] failed to persist %d shadow rows", len(docs))

    blocking = [s for s in updated if s.would_block]
    return {"scored": len(updated), "would_block": len(blocking),
            "targets": blocking}


async def repeat_count(db, target: str, cfg: dict) -> int:
    """How many times this source was blocked inside the penalty memory.

    The memory window widens with each offence: 7 days for the second offence,
    30 for the third and beyond.  A source that reoffends after the longest
    window is treated as a first offender again, because punishment should not
    accumulate forever over an IP that has since been cleaned.
    """
    memory = cfg.get("penalty_memory_days") or detect.DEFAULT_CONFIG["penalty_memory_days"]
    days = int(memory[min(len(memory) - 1, 1)] if len(memory) > 1 else memory[0])
    cut = datetime.now(timezone.utc) - timedelta(days=max(1, days))
    try:
        return await db.ddos_incidents.count_documents({
            "target": target, "direction": "outbound",
            "auto_block": True, "started_at": {"$gte": cut.isoformat()},
        })
    except Exception:  # noqa: BLE001
        return 0


async def enforce_decisions(db, blocking: list[detect.Score], cfg: dict,
                            devices: list[dict], prefixes: list[dict],
                            *, source: str = "sweep") -> list[dict]:
    """Block each qualifying target on the first enforcer that verifies it.

    Every outcome — success or failure — is written to ``blackhole_log`` with
    the same shape the manual path uses, so one screen shows both.
    """
    from .integrations_v2 import MikrotikClient
    from .ddos_guard import is_protected, load_whitelist

    whitelist = await load_whitelist(db)
    now_iso = datetime.now(timezone.utc).isoformat()
    results = []
    for score in blocking:
        target = score.target
        normalised, error = guard.validate_target(target)
        if error:
            results.append({"target": target, "ok": False, "error": error})
            continue
        if is_protected(normalised, whitelist):
            results.append({"target": target, "ok": False,
                            "error": "whitelisted — refusing to block"})
            continue

        repeat = await repeat_count(db, normalised, cfg) + 1
        hours = detect.penalty_hours(repeat, cfg)
        incident = {
            "target": normalised,
            "direction": "outbound",
            "attack_type": "Outbound Abuse (shape-scored)",
            "severity": "critical" if score.instant else "high",
            "status": "active",
            "action": f"source_block:{hours}h",
            "auto_block": True,
            "score": score.score,
            "signals": score.signals,
            "metrics": score.metrics,
            "reason": score.reason,
            "source": source,
            "started_at": now_iso,
            "last_breach_at": now_iso,
            "notified": [],
        }
        existing = await db.ddos_incidents.find_one({
            "target": normalised, "direction": "outbound",
            "status": {"$in": ["active", "mitigated"]}})
        if existing:
            await db.ddos_incidents.update_one(
                {"_id": existing["_id"]},
                {"$set": {k: incident[k] for k in
                          ("score", "signals", "metrics", "reason",
                           "last_breach_at", "severity")}})
            incident_id = str(existing["_id"])
        else:
            inserted = await db.ddos_incidents.insert_one(incident)
            incident_id = str(inserted.inserted_id)

        outcome = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda t=normalised, h=hours, i=incident_id: guard.enforce_target(
                t, devices, prefixes, hours=h, incident_id=i,
                make_client=MikrotikClient),
        )
        await db.blackhole_log.insert_one({
            "prefix": f"{normalised}/32",
            "action": "add",
            "by": "auto-outbound",
            "source": "auto",
            "device": outcome.get("device") or "",
            "ok": bool(outcome.get("ok")),
            "detail": str(outcome.get("attempts") or outcome.get("error") or "")[:400],
            "at": now_iso,
        })
        if outcome.get("ok"):
            await db.ddos_incidents.update_one(
                {"_id": existing["_id"] if existing else _oid(incident_id)},
                {"$set": {"status": "mitigated",
                          "blocked_device": outcome.get("device"),
                          "blocked_timeout": outcome.get("timeout"),
                          "blocked_at": now_iso,
                          "penalty_hours": hours,
                          "repeat_offence": repeat}})
            _tracker.reset(normalised)
        else:
            await db.ddos_incidents.update_one(
                {"_id": existing["_id"] if existing else _oid(incident_id)},
                {"$set": {"status": "failed", "failure_reason":
                          str(outcome.get("error"))[:300]}})
        results.append({"target": normalised, "ok": bool(outcome.get("ok")),
                        "device": outcome.get("device"),
                        "hours": hours, "repeat": repeat,
                        "error": outcome.get("error")})
    return results


def _oid(value: str):
    from bson import ObjectId
    try:
        return ObjectId(value)
    except Exception:  # noqa: BLE001
        return None


async def run_outbound_sweep(db, rate_rows, window_s: float,
                             devices: list[dict], prefixes: list[dict],
                             *, authoritative: bool = True) -> dict:
    """Full outbound pass for one window.  Safe in any mode.

    Returns a summary the caller merges into the sweep result so the NOC screen
    can show "evaluated 12 sources, 0 would block" even when nothing happened —
    silence is what made the old detector look dead.

    ``authoritative`` comes from the collector, not from this function.  The
    collector derives the window and knows when it cannot vouch for it: a poll
    whose usable span stays under one second (two sweeps back to back, a cold
    start, or a nearly drained cursor) divides a handful of packets by tens of
    milliseconds and invents a rate.  That verdict is accepted here instead of
    being recomputed from ``window_s > 0``, because a clamped window has a
    non-zero value that would otherwise look trustworthy.

    Being authoritative is necessary, not sufficient: the packet counters are
    accumulated by the router's flow cache (``active-flow-timeout`` 30 min,
    4k entries), so a flush can land stale counters in a window that is
    otherwise well formed.  That is what ``instant_confirm_windows`` covers.
    """
    cfg = await load_config(db)
    if not cfg.get("enabled"):
        return {"enabled": False, "scored": 0}
    if window_s is None or float(window_s) <= 0:
        # Without a window, packets cannot become a rate and every score would
        # be a guess. Report it instead of scoring against a zero.
        return {"enabled": True, "skipped": "no authoritative flow window"}
    if not authoritative:
        return {"enabled": True, "skipped": "non-authoritative flow window",
                "authoritative": False, "mode": cfg.get("mode")}

    buckets = outbound_candidates(rate_rows, prefixes)
    if not buckets:
        return {"enabled": True, "mode": cfg.get("mode"), "scored": 0,
                "would_block": 0}

    overrides = await load_overrides(db)
    now = datetime.now(timezone.utc)
    scores = evaluate_window(buckets, float(window_s), cfg, overrides,
                             replies=reply_counts(rate_rows, prefixes))
    summary = await persist_scores(db, scores, cfg, now,
                                   authoritative=authoritative)
    summary["mode"] = cfg.get("mode")
    summary["candidates"] = len(buckets)

    if cfg.get("mode") == "enforce" and summary["targets"]:
        summary["enforced"] = await enforce_decisions(
            db, summary["targets"], cfg, devices, prefixes)
        summary["enforced_ok"] = sum(1 for e in summary["enforced"] if e.get("ok"))
    elif summary["targets"]:
        summary["shadow_only"] = True
    summary.pop("targets", None)
    return summary
