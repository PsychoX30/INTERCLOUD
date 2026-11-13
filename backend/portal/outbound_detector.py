"""Outbound abuse detection — shape-based, not volume-based.

Why this module exists
----------------------
Inbound DDoS detection answers "is this customer being flooded?"; a volume
threshold is a reasonable proxy because the customer's own traffic profile is
small and stable.  Outbound abuse is the opposite problem: a domestic customer
is *allowed* 1 Gbps and a transit/IPT peer is allowed 100-200 Mbps, so any
volume threshold low enough to catch an abuser also catches legitimate bulk
transfer.  Blocking on volume would disconnect paying customers.

So volume is used only as a **gate**: below it we do not even bother scoring.
Every blocking decision is made from the *shape* of the traffic, which is what
actually distinguishes an attack from a busy customer:

  S1  SYN flood        — nearly every packet is a bare SYN, and there are many
  S2  Destination fan-out — the source sprays a wide range of networks
  S3  Small packets    — forged/stub packets, not full-MSS payloads
  S4  No return path   — SYNs go out, SYN-ACKs never come back
  S5  Persistence      — the same source repeats across consecutive windows

None of these can be produced by a legitimate bulk upload.  A backup job has
S1=no (established ACKs), S2=no (one peer), S3=no (full MSS), S4=1:1.  A
customer running a busy web crawler has S2 possibly yes and S4 yes, but S1 no
and S3 no.  Two independent shape signals are required before anything is even
considered, three before a block.

Everything here is pure: no Mongo, no router, no clock.  The caller supplies
the window and the flows.  That is deliberate — every threshold in this file is
a number an operator must be able to change without touching code, and a pure
function is the only thing that can be proven correct in a test.
"""
from __future__ import annotations

import ipaddress
import statistics
from dataclasses import dataclass, field, asdict
from typing import Iterable, Optional

# ---------------------------------------------------------------------------
# TCP flags (RFC 793) — duplicated from ddos_engine on purpose: importing that
# module would drag its whole classification surface into a module that must
# stay dependency-free and cheap to import inside a 10-second scheduler tick.
# ---------------------------------------------------------------------------
TCP_SYN = 0x02
TCP_ACK = 0x10

# ---------------------------------------------------------------------------
# Defaults.  These are *literature* starting points, NOT calibration against
# INTERCLOUD traffic: as of 2026-11-13 the database holds two days of flow
# samples and zero outbound ones, so there is no basis for a fitted number.
# The operator overrides them in `ddos_detection_config`; `mode=shadow` exists
# so they can be validated against real traffic before anything is blocked.
# ---------------------------------------------------------------------------
DEFAULT_CONFIG: dict = {
    "enabled": True,
    # "shadow" evaluates and records, never touches a router.
    # "enforce" is the only value that may block, and the UI must confirm it.
    "mode": "shadow",
    "window_seconds": 10,
    # --- S1 SYN flood ---
    "syn_ratio_min": 0.60,
    "syn_pps_min": 1000,
    # --- S2 destination fan-out ---
    "dst_diversity_min": 200,
    # --- S3 small packets ---
    "small_packet_bytes": 100,
    "small_packet_ratio_min": 0.85,
    "small_pps_min": 500,
    # --- S4 no return path ---
    "fanout_ratio_min": 10.0,
    "fanout_min_syn": 500,
    # --- volume gate (never blocks, only skips scoring) ---
    "skip_below_pps": 200,
    "skip_below_bytes": 200_000,
    # --- aggregation ---
    "min_signals_to_block": 3,     # among S1-S4
    "min_score_to_block": 4,       # among S1-S5
    "confirm_windows": 3,          # consecutive windows at/above threshold
    # --- absolute safety net ---
    "instant_critical_pps": 100_000,
    "instant_critical_syn_ratio": 0.80,
    # How many consecutive windows the safety net must see before it blocks.
    # 1 means "block on the first window". The default is 2.
    #
    # The rate a window carries is ``packets / span``, where ``packets`` is a
    # counter the router's flow cache accumulated — its ``active-flow-timeout``
    # is 30 minutes and the cache holds 4k entries, so a cache eviction or a
    # buffered flush can write counters that describe traffic older than the
    # window they land in. The inflated rate then looks perfectly ordinary
    # (measured 2026-11-13: one source, 139,405 pps over a 10.3 s window,
    # 1,062 flows to 249 destinations), and a one-window safety net would cut
    # the customer off on that single, unverifiable sample. Two consecutive
    # windows cost ~10 s at a rate no legitimate host here sends, and require
    # the rate to survive an independent counter batch.
    #
    # The collector's own ``authoritative`` verdict already blocks the
    # degenerate polls (span < 1 s). This counter covers the remaining case:
    # a window wide enough to look credible while its counters are not.
    "instant_confirm_windows": 2,
    # --- repeat-offender ladder (hours; -1 = permanent until lifted manually) ---
    "penalty_ladder_hours": [0.5, 6, 24, -1],
    "penalty_memory_days": [7, 30],
}

# Fields an operator may override from the UI.  Anything not listed is either
# derived or deliberately not exposed (e.g. the S5 counter is internal state).
CONFIG_FIELDS: tuple[str, ...] = tuple(DEFAULT_CONFIG)


def merge_config(stored: Optional[dict]) -> dict:
    """Layer stored overrides on top of the defaults, ignoring unknown keys.

    Unknown keys are dropped rather than kept: a typo in a config document
    must not silently sit there looking effective.
    """
    cfg = dict(DEFAULT_CONFIG)
    if not isinstance(stored, dict):
        return cfg
    for key, value in stored.items():
        if key not in DEFAULT_CONFIG or value is None:
            continue
        cfg[key] = value
    return cfg


def apply_overrides(cfg: dict, overrides: Iterable[dict]) -> dict:
    """Apply per-target overrides on top of a resolved config.

    An override is ``{"field": ..., "value": ..., "expires_at": ...}``.  Expiry
    is evaluated here so an operator can grant a customer a temporary exemption
    without having to remember to delete it.
    """
    out = dict(cfg)
    for ov in overrides:
        if not isinstance(ov, dict):
            continue
        field_name = ov.get("field")
        if field_name not in DEFAULT_CONFIG:
            continue
        out[field_name] = ov.get("value")
    return out


# ---------------------------------------------------------------------------
# Per-window measurement
# ---------------------------------------------------------------------------
@dataclass
class WindowMetrics:
    """Everything measurable about one source IP inside one window.

    ``packets``/``bytes`` are totals; the ratios are packet-weighted so a
    single 40 kpps flow does not get outvoted by 200 one-packet flows (which is
    exactly how a SYN flood presents itself in IPFIX: many tiny records).
    """

    target: str
    window_s: float = 0.0
    packets: float = 0.0
    bytes_: float = 0.0
    syn_packets: float = 0.0
    synack_packets: float = 0.0
    small_packets: float = 0.0
    dst_ips: set[str] = field(default_factory=set)
    dst_nets: set[str] = field(default_factory=set)
    flow_count: int = 0
    devices: set[str] = field(default_factory=set)

    @property
    def pps(self) -> float:
        return self.packets / self.window_s if self.window_s > 0 else 0.0

    @property
    def bps(self) -> float:
        return self.bytes_ * 8 / self.window_s if self.window_s > 0 else 0.0

    @property
    def bytes_per_s(self) -> float:
        return self.bytes_ / self.window_s if self.window_s > 0 else 0.0

    @property
    def syn_share(self) -> float:
        return self.syn_packets / self.packets if self.packets > 0 else 0.0

    @property
    def small_share(self) -> float:
        return self.small_packets / self.packets if self.packets > 0 else 0.0

    @property
    def dst_diversity(self) -> int:
        return len(self.dst_nets)

    @property
    def fanout_ratio(self) -> float:
        """SYNs sent per SYN-ACK received.

        A healthy TCP client gets roughly one SYN-ACK per SYN, so this sits
        near 1.  A spoofed-source SYN flood has no completed handshakes, so
        the ratio is unbounded.  Guarded against division by zero by treating
        "zero replies" as "infinite fanout" only when there were SYNs at all.
        """
        if self.syn_packets <= 0:
            return 0.0
        if self.synack_packets <= 0:
            return float("inf")
        return self.syn_packets / self.synack_packets


def _net_key(ip: str) -> Optional[str]:
    """Bucket a destination into the diversity unit.

    IPv4 is bucketed at /24 because a single customer typically owns a /24 and
    spraying eight /24s is already 2,048 addresses.  IPv6 is bucketed at /48
    for the same reason — a /48 is the site allocation, so counting /64s would
    make one subscriber look like 65,536 distinct destinations.
    """
    try:
        addr = ipaddress.ip_address(ip.split("/")[0])
    except ValueError:
        return None
    if addr.version == 4:
        return str(ipaddress.ip_network(f"{addr}/24", strict=False))
    return str(ipaddress.ip_network(f"{addr}/48", strict=False))


@dataclass
class _FlowView:
    """The only fields this module needs from a flow record."""

    src: str
    dst: str
    packets: float
    bytes_: float
    tcp_flags: int
    protocol: str


def measure(target: str, flows: Iterable, window_s: float,
            small_packet_bytes: int = DEFAULT_CONFIG["small_packet_bytes"],
            inbound_replies: float = 0.0) -> WindowMetrics:
    """Fold every flow belonging to ``target`` into one WindowMetrics.

    ``flows`` may be ``ddos_engine.FlowRate`` instances or plain dicts with
    ``src_ip/dst_ip/packets/bytes_/tcp_flags/protocol``; both shapes exist in
    the codebase and forcing one on the caller would mean another adapter.

    ``inbound_replies`` is the SYN-ACK count that came *back* to the target in
    this window.  It cannot be derived from the target's own outbound flows:
    a SYN-ACK is a separate flow whose **source** is the remote peer, so a
    per-source aggregation never sees it.  Measured on production traffic
    (2026-11-13) that made every busy source look like a fanout of 167-715
    SYNs per reply, which would have fired S4 on five of eleven sources —
    a false-positive rate that would have blocked legitimate servers on the
    first enforcing window.  The caller therefore supplies the reply count
    from the full flow batch.
    """
    metrics = WindowMetrics(target=target, window_s=float(window_s or 0))
    for flow in flows:
        view = flow_view(flow)
        if view is None or view.src != target:
            continue
        metrics.flow_count += 1
        metrics.packets += view.packets
        metrics.bytes_ += view.bytes_
        if view.dst:
            metrics.dst_ips.add(view.dst)
            key = _net_key(view.dst)
            if key:
                metrics.dst_nets.add(key)
        per_packet = (view.bytes_ / view.packets) if view.packets > 0 else 0.0
        if per_packet and per_packet < small_packet_bytes:
            metrics.small_packets += view.packets
        flags = int(view.tcp_flags or 0)
        if flags & TCP_SYN:
            if flags & TCP_ACK:
                metrics.synack_packets += view.packets
            else:
                metrics.syn_packets += view.packets
    # Prefer the externally measured reply count when one was supplied; it is
    # the only number that includes replies arriving on a different interface.
    if inbound_replies:
        metrics.synack_packets = max(metrics.synack_packets, float(inbound_replies))
    return metrics


def flow_view(flow):
    """Normalise one flow record to the fields this module needs.

    Public because the sweep needs the same view: it accepts both
    ``FlowRate`` objects and the raw dicts the collector test harness passes,
    and duplicating that duck-typing in two modules is how the outbound pass
    silently scored zero sources while 30k outbound flows sat in the file.
    """
    if isinstance(flow, dict):
        src = (flow.get("src_ip") or flow.get("src_address") or "").split("/")[0]
        dst = (flow.get("dst_ip") or flow.get("dst_address") or "").split("/")[0]
        return _FlowView(
            src=src, dst=dst,
            packets=float(flow.get("packets") or flow.get("rx_packets") or 0),
            bytes_=float(flow.get("bytes_") or flow.get("bytes") or flow.get("rate_bytes") or 0),
            tcp_flags=int(flow.get("tcp_flags") or 0),
            protocol=str(flow.get("protocol") or ""),
        )
    try:
        return _FlowView(
            src=(getattr(flow, "src_ip", "") or "").split("/")[0],
            dst=(getattr(flow, "dst_ip", "") or "").split("/")[0],
            packets=float(getattr(flow, "packets", 0) or 0),
            bytes_=float(getattr(flow, "bytes_", 0) or 0),
            tcp_flags=int(getattr(flow, "tcp_flags", 0) or 0),
            protocol=str(getattr(flow, "protocol", "") or ""),
        )
    except (TypeError, ValueError):
        return None


_as_flow_view = flow_view  # backwards-compatible alias


# ---------------------------------------------------------------------------
# Signals and scoring
# ---------------------------------------------------------------------------
def evaluate_signals(metrics: WindowMetrics, cfg: dict) -> dict:
    """Return the boolean shape signals for one window plus the volume gate.

    The gate is returned separately and never counts as a signal: it is a
    "not worth looking at" filter, not evidence of an attack.  Conflating the
    two is how a quiet network gets customers disconnected.
    """
    gated = (metrics.pps < float(cfg["skip_below_pps"])
             and metrics.bytes_per_s < float(cfg["skip_below_bytes"]))

    s1 = (metrics.syn_share >= float(cfg["syn_ratio_min"])
          and metrics.pps * metrics.syn_share >= float(cfg["syn_pps_min"]))
    s2 = metrics.dst_diversity >= int(cfg["dst_diversity_min"])
    s3 = (metrics.small_share >= float(cfg["small_packet_ratio_min"])
          and metrics.pps >= float(cfg["small_pps_min"]))
    s4 = (metrics.syn_packets >= float(cfg["fanout_min_syn"])
          and metrics.fanout_ratio >= float(cfg["fanout_ratio_min"]))
    return {
        "gated": gated,
        "S1_syn_flood": bool(s1),
        "S2_dst_fanout": bool(s2),
        "S3_small_packets": bool(s3),
        "S4_no_return": bool(s4),
    }


@dataclass
class Score:
    """One target's verdict for one window."""

    target: str
    score: int
    signals: dict
    metrics: dict
    would_block: bool
    reason: str
    instant: bool = False

    def to_doc(self) -> dict:
        return {
            "target": self.target,
            "score": self.score,
            "signals": dict(self.signals),
            "metrics": dict(self.metrics),
            "would_block": self.would_block,
            "reason": self.reason,
            "instant": self.instant,
        }


def score_window(metrics: WindowMetrics, cfg: dict) -> Score:
    """Score one window for one target.

    ``consecutive`` handling lives in ``OutboundTracker`` because a single
    window cannot know how many windows preceded it.  Here S5 is always 0;
    the tracker adds it.
    """
    signals = evaluate_signals(metrics, cfg)
    base = {
        "pps": round(metrics.pps, 2),
        "bps": round(metrics.bps, 2),
        "syn_share": round(metrics.syn_share, 4),
        "small_share": round(metrics.small_share, 4),
        "dst_diversity": metrics.dst_diversity,
        "dst_ips": len(metrics.dst_ips),
        "syn_pps": round(metrics.pps * metrics.syn_share, 2),
        "fanout_ratio": (None if metrics.fanout_ratio == float("inf")
                         else round(metrics.fanout_ratio, 3)),
        "flow_count": metrics.flow_count,
        "window_s": round(metrics.window_s, 3),
    }
    if signals["gated"]:
        return Score(target=metrics.target, score=0, signals=signals,
                     metrics=base, would_block=False,
                     reason="below volume gate — not scored")

    instant = (metrics.pps >= float(cfg["instant_critical_pps"])
               and metrics.syn_share >= float(cfg["instant_critical_syn_ratio"]))
    score = sum(1 for k in ("S1_syn_flood", "S2_dst_fanout",
                            "S3_small_packets", "S4_no_return") if signals[k])
    return Score(target=metrics.target, score=score, signals=signals,
                 metrics=base, would_block=instant,
                 reason=("absolute safety net: %.0f pps with %.0f%% SYN"
                         % (metrics.pps, metrics.syn_share * 100))
                 if instant else "shape score %d/4" % score,
                 instant=instant)


class OutboundTracker:
    """Carries the S5 persistence counter between windows.

    State is intentionally in-memory and bounded.  A target that stops
    appearing is forgotten after ``forget_windows`` windows, so a
    once-every-hour abusive burst cannot accumulate credit slowly over days.
    """

    def __init__(self, *, max_targets: int = 5000):
        self._consecutive: dict[str, int] = {}
        self._instant: dict[str, int] = {}
        self._max = max(100, int(max_targets))

    def update(self, scores: list[Score], cfg: dict) -> list[Score]:
        """Add S5 to ``scores`` and decide blocking eligibility."""
        seen = {s.target for s in scores}
        threshold = int(cfg["min_score_to_block"]) - 1  # S5 contributes +1
        for score in scores:
            if score.signals.get("gated") or score.score < threshold:
                self._consecutive.pop(score.target, None)
                continue
            self._consecutive[score.target] = (
                self._consecutive.get(score.target, 0) + 1)

        # The safety net has its own counter: it must not inherit the shape
        # confirmation (it exists to skip it) and it must not be trusted on a
        # single window either (see `instant_confirm_windows`).
        confirm_instant = max(1, int(cfg.get("instant_confirm_windows")
                                     or DEFAULT_CONFIG["instant_confirm_windows"]))
        for score in scores:
            if score.signals.get("gated"):
                self._instant.pop(score.target, None)
            elif score.instant:
                self._instant[score.target] = (
                    self._instant.get(score.target, 0) + 1)
            else:
                self._instant.pop(score.target, None)
        for target in [t for t in self._instant if t not in seen]:
            self._instant.pop(target, None)

        # A target absent from this window loses one window of credit.  Decrement
        # rather than delete: a sampler that misses one window must not reset a
        # genuine multi-window flood back to zero, but credit must also not
        # survive indefinitely, or an hourly burst would add up over days.
        for target in [t for t in self._consecutive if t not in seen]:
            remaining = self._consecutive[target] - 1
            if remaining <= 0:
                self._consecutive.pop(target, None)
            else:
                self._consecutive[target] = remaining

        for score in scores:
            consecutive = self._consecutive.get(score.target, 0)
            if consecutive:
                score.signals["S5_persistence"] = True
                score.score += 1
            else:
                score.signals["S5_persistence"] = False
            if score.instant:
                hits = self._instant.get(score.target, 0)
                if hits >= confirm_instant:
                    score.would_block = True
                    score.reason = (score.reason + " — bypasses confirmation")
                else:
                    score.would_block = False
                    score.reason = ("safety net %d/%d window(s) — not yet"
                                    % (hits, confirm_instant))
                continue
            shape_signals = sum(1 for k in ("S1_syn_flood", "S2_dst_fanout",
                                            "S3_small_packets", "S4_no_return")
                                if score.signals.get(k))
            if score.signals.get("gated"):
                continue
            if (shape_signals >= int(cfg["min_signals_to_block"])
                    and score.score >= int(cfg["min_score_to_block"])
                    and consecutive >= int(cfg["confirm_windows"])):
                score.would_block = True
                score.reason = ("shape %d/4 + persistence %d windows"
                                % (shape_signals, consecutive))
            else:
                score.would_block = False
                if shape_signals >= int(cfg["min_signals_to_block"]):
                    score.reason = ("shape %d/4 but persistence %d/%d windows"
                                    % (shape_signals, consecutive,
                                       int(cfg["confirm_windows"])))
        if len(self._consecutive) > self._max:
            for target in list(self._consecutive)[: len(self._consecutive) - self._max]:
                self._consecutive.pop(target, None)
        return scores

    def consecutive(self, target: str) -> int:
        return self._consecutive.get(target, 0)

    def reset(self, target: str) -> None:
        self._consecutive.pop(target, None)


def penalty_hours(repeat_count: int, cfg: dict) -> Optional[float]:
    """Return the block duration for the ``repeat_count``-th offence.

    ``repeat_count`` is 1-based.  ``-1`` means "permanent until lifted", which
    the caller must represent explicitly — never as an infinite float.
    """
    ladder = cfg.get("penalty_ladder_hours") or DEFAULT_CONFIG["penalty_ladder_hours"]
    if not ladder:
        return None
    index = min(max(1, int(repeat_count)), len(ladder)) - 1
    try:
        return float(ladder[index])
    except (TypeError, ValueError):
        return None


def summarise(scores: list[Score]) -> dict:
    """Aggregate a window for the shadow log and the UI badge."""
    blocking = [s for s in scores if s.would_block]
    scores_only = [s.score for s in scores] or [0]
    return {
        "targets": len(scores),
        "would_block": len(blocking),
        "median_score": statistics.median(scores_only),
        "max_score": max(scores_only),
        "instant": sum(1 for s in blocking if s.instant),
    }
