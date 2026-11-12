"""DDoS detection engine — flow-grounded, baseline-aware.

Replaces the sum-of-rates heuristic that made production incidents
unknowable (a reported 17,007,965 pps is more than any 10G link can
deliver; the old code summed every flow's PPS into one number).

Design contract
---------------
1. **Rates are absolute, not per-flow.**  A Torch row carries a rate
   already.  A goflow2 record carries *counts* over a batch window, so the
   batch is collapsed: total packets / observed wall-clock span.  Summing
   per-record ``packets/window`` truncates to 0 (packets=1 over 21 s).
2. **Aggregation is a peak, not a sum.**  Multiple records for the same
   (direction, target) inside one batch belong to the *same* physical
   traffic; adding them double-counts.  We take the busiest slice, which
   is what every operational flow tool (akvorado, fastnetmon) displays.
3. **Detection needs a baseline.**  A single sample above a threshold is
   not evidence of an attack: nightly backups, video calls and CDN syncs
   all spike.  We compare the current bucket against the trailing median
   and refuse to fire unless the deviation is both absolutely large
   (rule threshold) and statistically unusual (robust z-score on MAD).
4. **Attack type comes from evidence.**  ``tcp_flags`` and ``dst_port``
   decide the label.  A flow *from* port 53 is not a DNS amplification;
   an amplified flood arrives *at* a service port from a spoofed source.
"""
from __future__ import annotations

import ipaddress
import math
import statistics
from dataclasses import dataclass, field
from typing import Iterable, Optional

# ---------------------------------------------------------------------------
# TCP flag bits (RFC 793)
# ---------------------------------------------------------------------------
TCP_FIN = 0x01
TCP_SYN = 0x02
TCP_RST = 0x04
TCP_PSH = 0x08
TCP_ACK = 0x10
TCP_URG = 0x20
TCP_ECE = 0x40
TCP_CWR = 0x80

# Ports that are reflexively abused as amplifiers.  A flood whose
# *destination* port is one of these, with a small packet size, is
# characteristic of a reflection/amplification attack.
AMPLIFICATION_PORTS: dict[int, str] = {
    53: "DNS Amplification",
    123: "NTP Amplification",
    161: "SNMP Amplification",
    389: "LDAP Amplification",
    1900: "SSDP Amplification",
    5353: "mDNS Amplification",
    11211: "Memcached Amplification",
    19: "Chargen Amplification",
    17: "QOTD Amplification",
    27015: "Steam Amplification",
}

# Service ports that indicate an application-layer flood when hammered.
HTTP_PORTS = {80, 443, 8080, 8443, 8000, 8001}
SERVICE_FLOOD_PORTS: dict[int, str] = {
    22: "SSH Brute Force Flood",
    25: "SMTP Flood",
    143: "IMAP Flood",
    3306: "MySQL Flood",
    5432: "PostgreSQL Flood",
    6379: "Redis Flood",
    27017: "MongoDB Flood",
}

# Mean payload size below this (bytes/packet) with a flood of packets
# suggests forged/spoofed traffic — real bulk transfer sends full MSS.
SMALL_PACKET_BYTES = 200


@dataclass
class FlowRate:
    """A flow normalised to absolute per-second rates."""

    src_ip: str
    dst_ip: str
    protocol: str
    src_port: int
    dst_port: int
    tcp_flags: int
    pps: float
    bps: float
    packets: float
    bytes_: float
    sampled: bool = False
    device: str = ""
    in_if: int = 0
    out_if: int = 0

    @property
    def bytes_per_packet(self) -> float:
        return self.bytes_ / self.packets if self.packets > 0 else 0.0

    @property
    def is_syn(self) -> bool:
        """A pure SYN: SYN set, ACK clear. SYN+ACK is a reply, not a flood."""
        return bool(self.tcp_flags & TCP_SYN) and not bool(self.tcp_flags & TCP_ACK)

    @property
    def is_rst(self) -> bool:
        return bool(self.tcp_flags & TCP_RST)


def classify_attack_type(rate: FlowRate, direction: str = "inbound") -> str:
    """Label a flood from its own evidence.

    Order matters.  The old classifier tested ``src_port`` first, so any
    flow that merely *originated* from port 53 — i.e. every legitimate DNS
    reply — was called a "DNS Amplification".  Amplification is defined by
    what arrives at the victim, so the destination port is authoritative.
    """
    proto = (rate.protocol or "").lower()
    dst_port = rate.dst_port
    src_port = rate.src_port

    if proto in ("icmp", "icmpv6"):
        return "ICMP Flood"

    if proto == "udp":
        # Reflection/amplification: flood lands on the amplifier's service
        # port.  Check the destination first, and only fall back to the
        # source port when the direction is inbound and the destination is
        # an ephemeral high port (the victim's NAT pinhole).
        if dst_port in AMPLIFICATION_PORTS:
            return AMPLIFICATION_PORTS[dst_port]
        if direction == "outbound" and src_port in AMPLIFICATION_PORTS:
            return f"{AMPLIFICATION_PORTS[src_port]} (egress)"
        return "UDP Flood"

    if proto.startswith("tcp"):
        # SYN flood: pure SYNs at a service port, small payload.
        if rate.is_syn:
            return "SYN Flood"
        if dst_port in HTTP_PORTS or src_port in HTTP_PORTS:
            # A flood served *from* :443 onto the victim's ephemeral port is
            # still an HTTP(S) flood; the old code only looked at dst_port
            # and mislabelled every server-initiated response flood.
            return "HTTP Flood"
        if dst_port in SERVICE_FLOOD_PORTS:
            return SERVICE_FLOOD_PORTS[dst_port]
        # A flood of tiny TCP packets that are not SYNs and not a service
        # port is most likely ACK/PSH rubbish or a fragmented attack.
        if rate.bytes_per_packet and rate.bytes_per_packet < SMALL_PACKET_BYTES:
            return "TCP Flags Flood"
        return "TCP Flood"

    if proto in ("gre", "esp", "ah", "ipsec"):
        return "Tunnel Flood"

    if proto in ("igmp",):
        return "IGMP Flood"

    return "Traffic Anomaly"


def severity_from_ratio(ratio: float) -> str:
    """Map observed/typical ratio to a severity band."""
    if ratio >= 10:
        return "critical"
    if ratio >= 4:
        return "high"
    if ratio >= 2:
        return "medium"
    return "low"


def robust_zscore(values: list[float], current: float) -> float:
    """Deviation of ``current`` from the median, scaled by MAD.

    MAD (median absolute deviation) is preferred over standard deviation
    because a single historical attack inside the baseline window inflates
    stdev so much that the next attack looks normal.  Median + MAD keeps
    the baseline resistant to contamination.

    Returns 0.0 when there is not enough history or the baseline is flat,
    so callers must combine this with an absolute threshold.
    """
    clean = [v for v in values if v is not None and v >= 0]
    if len(clean) < 5:
        return 0.0
    med = statistics.median(clean)
    deviations = [abs(v - med) for v in clean]
    mad = statistics.median(deviations)
    # 1.4826 scales MAD to be a consistent estimator of sigma for a
    # normal distribution; without it the z-scores are systematically low.
    sigma = 1.4826 * mad
    if sigma <= 0:
        # Flat baseline: any movement away from it is infinitely unusual.
        # Scale by the median so a 0 baseline does not divide by zero, and
        # cap the score so callers comparing magnitudes do not see noise
        # amplified without bound.
        if med <= 0:
            return 0.0 if current <= 0 else 99.0
        return min(99.0, abs(current - med) / med * 3.0)
    return abs(current - med) / sigma


@dataclass
class DetectionConfig:
    """Tunables for one evaluation pass."""

    # Absolute floor inherited from the operator's threshold rule.
    threshold_pps: float = 0.0
    threshold_bps: float = 0.0
    metric: str = "pps"
    # A bucket must beat BOTH the rule threshold and this multiple of the
    # baseline before it counts as an attack.
    baseline_multiplier: float = 3.0
    # ...and this robust z-score, when a baseline exists at all.
    min_zscore: float = 6.0
    # Require this many consecutive breaching buckets unless the traffic
    # is cataclysmic.  A one-shot spike is usually a measurement artefact.
    confirm_buckets: int = 2
    # A bucket this many times over threshold bypasses confirmation.
    instant_critical_multiplier: float = 5.0


@dataclass
class TargetStats:
    """Traffic observed for one (direction, target) inside a batch.

    Two different numbers matter and confusing them is what broke the old
    detector:

    ``peak_*``
        The busiest *single record*.  Useful for spotting one elephant flow.

    ``rate_*``
        The target's actual throughput: **all** its records' counters
        summed, divided by the wall-clock span of the batch.  This is the
        only number that means "packets per second arriving at this
        customer".

    A target with 175 flows of one packet each is NOT 0 pps.  Taking a
    peak over records divides a single packet by a 20-second window and
    truncates to zero, which is exactly how the production UI ended up
    showing ``pps=0`` while flows were flowing.  ``aggregate_targets``
    receives the window so ``rate_*`` can be computed correctly.
    """

    direction: str
    target: str
    peak_pps: float = 0.0
    peak_bps: float = 0.0
    total_packets: float = 0.0
    total_bytes: float = 0.0
    window_s: float = 0.0
    representative: Optional[FlowRate] = None
    flow_count: int = 0
    devices: set[str] = field(default_factory=set)

    @property
    def rate_pps(self) -> float:
        """Average packets/second for this target over the batch window."""
        if self.window_s > 0:
            return self.total_packets / self.window_s
        return self.peak_pps

    @property
    def rate_bps(self) -> float:
        """Average bits/second for this target over the batch window."""
        if self.window_s > 0:
            return self.total_bytes * 8 / self.window_s
        return self.peak_bps

    def merge(self, rate: FlowRate) -> None:
        """Fold one flow into the aggregate statistics.

        Counters accumulate; peaks track the single busiest record.  The
        representative is the largest flow by packet count, which is the
        best evidence for the attack-type classifier (a 1-packet ACK is not
        a SYN flood even if it is the only flow seen).
        """
        self.flow_count += 1
        self.total_packets += rate.packets
        self.total_bytes += rate.bytes_
        if rate.pps > self.peak_pps:
            self.peak_pps = rate.pps
        if rate.bps > self.peak_bps:
            self.peak_bps = rate.bps
        if self.representative is None or rate.packets > self.representative.packets:
            self.representative = rate
        if rate.device:
            self.devices.add(rate.device)


def _in_prefixes(ip: str, nets: list) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return any(addr in n for n in nets)


def classify_direction(src_ip: str, dst_ip: str, prefixes: list[str]) -> Optional[str]:
    """Return inbound / outbound / internal / None for a flow.

    ``internal`` means both ends are ours — a lateral flood, which no
    internet-facing RTBH can help with and which must never trigger an
    upstream announcement.
    """
    try:
        nets = [ipaddress.ip_network(p, strict=False) for p in prefixes]
    except ValueError:
        return None
    if not nets:
        return None
    src_in = _in_prefixes(src_ip, nets)
    dst_in = _in_prefixes(dst_ip, nets)
    if src_in and dst_in:
        return "internal"
    if not src_in and dst_in:
        return "inbound"
    if src_in and not dst_in:
        return "outbound"
    return None


def aggregate_targets(
    rates: Iterable[FlowRate],
    prefixes: list[str],
    window_s: float = 0.0,
) -> dict[tuple[str, str], TargetStats]:
    """Group flow rates by (direction, protected target).

    ``window_s`` is the wall-clock span the records cover.  It is required
    for ``rate_pps``/``rate_bps`` to mean anything: with it, a target's
    throughput is its summed packet counters over that span, which is the
    only definition that survives a batch of one-packet flows.  Callers that
    omit it fall back to per-record peaks (correct for Torch, where every
    row already carries a rate).
    """
    buckets: dict[tuple[str, str], TargetStats] = {}
    for rate in rates:
        direction = classify_direction(rate.src_ip, rate.dst_ip, prefixes)
        if direction is None:
            continue
        # Interior traffic is recorded for visibility but is never a
        # candidate for internet-facing mitigation; callers filter it.
        target = rate.dst_ip if direction == "inbound" else rate.src_ip
        key = (direction, target)
        stats = buckets.get(key)
        if stats is None:
            stats = buckets[key] = TargetStats(direction=direction, target=target,
                                               window_s=window_s)
        stats.merge(rate)
    return buckets


@dataclass
class Verdict:
    """Outcome of one target evaluation."""

    direction: str
    target: str
    metric_value: float
    metric: str
    threshold: float
    baseline: float
    ratio: float
    zscore: float
    attack_type: str
    severity: str
    breaching: bool
    reason: str
    stats: TargetStats


def evaluate_target(
    stats: TargetStats,
    history: list[float],
    config: DetectionConfig,
) -> Verdict:
    """Decide whether one target is under attack.

    ``history`` is the trailing series of the same metric for this target,
    oldest first, excluding the current bucket.

    The evaluated value is the target's *rate* (all its records summed over
    the batch window), not the busiest single record.  A customer receiving
    50 kpps spread over 5,000 one-packet flows is under the same load as
    one receiving 50 kpps in a single elephant flow; only the summed rate
    reflects that.
    """
    value = stats.rate_bps if config.metric == "bps" else stats.rate_pps
    threshold = (config.threshold_bps if config.metric == "bps"
                 else config.threshold_pps)
    clean_history = [float(v) for v in history if v is not None]
    baseline = statistics.median(clean_history) if len(clean_history) >= 5 else 0.0
    zscore = robust_zscore(clean_history, value)
    ratio = (value / baseline) if baseline > 0 else (
        float("inf") if value > 0 else 0.0)

    attack_type = "Traffic Anomaly"
    if stats.representative is not None:
        attack_type = classify_attack_type(stats.representative, stats.direction)

    severity = severity_from_ratio(ratio if math.isfinite(ratio) else 99.0)

    # --- gate 1: absolute floor from the operator's rule ------------------
    if threshold <= 0:
        return Verdict(
            direction=stats.direction, target=stats.target, metric_value=value,
            metric=config.metric, threshold=threshold, baseline=baseline,
            ratio=ratio, zscore=zscore, attack_type=attack_type,
            severity="low", breaching=False,
            reason="rule threshold not configured (0) — nothing can breach it",
            stats=stats)

    if value <= threshold:
        return Verdict(
            direction=stats.direction, target=stats.target, metric_value=value,
            metric=config.metric, threshold=threshold, baseline=baseline,
            ratio=ratio, zscore=zscore, attack_type=attack_type,
            severity=severity, breaching=False,
            reason=f"{value:,.0f} {config.metric} <= threshold {threshold:,.0f}",
            stats=stats)

    # --- gate 2: is this unusual for THIS target? -------------------------
    # With no usable history we cannot claim anomalous, but an absolute
    # breach of a configured catastrophic threshold still counts; the
    # caller enforces confirmation so a single warm-up bucket cannot fire.
    has_baseline = len(clean_history) >= 5 and baseline > 0
    if has_baseline:
        if value < baseline * config.baseline_multiplier:
            return Verdict(
                direction=stats.direction, target=stats.target,
                metric_value=value, metric=config.metric, threshold=threshold,
                baseline=baseline, ratio=ratio, zscore=zscore,
                attack_type=attack_type, severity=severity, breaching=False,
                reason=(f"{value:,.0f} {config.metric} over threshold but only "
                        f"{ratio:.2f}x baseline median ({baseline:,.0f}); "
                        f"needs {config.baseline_multiplier:.1f}x"),
                stats=stats)
        if zscore < config.min_zscore:
            return Verdict(
                direction=stats.direction, target=stats.target,
                metric_value=value, metric=config.metric, threshold=threshold,
                baseline=baseline, ratio=ratio, zscore=zscore,
                attack_type=attack_type, severity=severity, breaching=False,
                reason=(f"{value:,.0f} {config.metric} over threshold but "
                        f"z-score {zscore:.1f} < {config.min_zscore}; "
                        f"baseline is noisy"),
                stats=stats)

    return Verdict(
        direction=stats.direction, target=stats.target, metric_value=value,
        metric=config.metric, threshold=threshold, baseline=baseline,
        ratio=ratio, zscore=zscore, attack_type=attack_type,
        severity=severity, breaching=True,
        reason=(f"{value:,.0f} {config.metric} > threshold {threshold:,.0f}"
                + (f", {ratio:.1f}x baseline median" if has_baseline else
                   ", no baseline history yet")),
        stats=stats)
