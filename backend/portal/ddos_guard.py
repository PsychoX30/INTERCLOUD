"""DDoS mitigation guard — whitelist enforcement + auto-blackhole decision.

Customer-facing services are NATed behind a shared gateway IP. Blackholing
that gateway would take every customer offline. So a whitelist is enforced
at the backend for BOTH the auto-mitigation path and the manual
/admin/mikrotik/blackhole endpoint.

This module is pure/logic-level (no live router, no DB) so it runs anywhere.
"""
from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from typing import Optional


# Default whitelist — infrastructure IPs that must NEVER be blackholed.
# This protects the gateway/loopback/etc but NOT customer host IPs.
DEFAULT_WHITELIST: list[str] = [
    "127.0.0.0/8",          # loopback
    "10.0.0.0/8",           # RFC 1918
    "172.16.0.0/12",        # RFC 1918
    "192.168.0.0/16",       # RFC 1918
    "198.51.100.0/24",      # TEST-NET-1 (RFC 5737)
    "203.0.113.0/24",       # TEST-NET-2 (RFC 5737)
    "192.0.2.0/24",         # TEST-NET-3 (RFC 5737)
    "169.254.0.0/16",       # link-local
    "224.0.0.0/4",          # multicast
    "240.0.0.0/4",          # reserved
    # Our production gateway — blackholing this takes all customers offline
    "157.20.32.1/32",       # upstream gateway
    "157.20.32.254/32",     # NAT gateway
]


@dataclass
class BlackholeVerdict:
    allowed: bool
    reason: str


def normalize_prefix(prefix: str) -> str:
    """Normalize an IP or CIDR to strict CIDR notation (/32 for bare IPs)."""
    prefix = prefix.strip()
    try:
        net = ipaddress.ip_network(prefix, strict=False)
    except ValueError as e:
        raise ValueError(f"Invalid prefix: {prefix}") from e
    return f"{net.network_address}/{net.prefixlen}"


def is_protected(target: str, whitelist: Optional[list[str]] = None) -> bool:
    """Check if a target prefix overlaps any whitelisted network.

    The old implementation reduced ``target`` to its ``network_address`` and
    then tested that single IP for membership.  That let a *wider* CIDR whose
    network address was not itself whitelisted (e.g. ``157.20.32.0/24`` when
    the whitelist holds ``157.20.32.254/32``) slip through, even though it
    contained the protected NAT gateway.  The check must be an **overlap**
    test: any intersection between the target network and a whitelisted
    network means the action could reach a protected address and is refused.
    """
    wl = whitelist or DEFAULT_WHITELIST
    try:
        target_net = ipaddress.ip_network(target, strict=False)
    except ValueError:
        return False

    for wl_prefix in wl:
        try:
            wl_net = ipaddress.ip_network(wl_prefix, strict=False)
        except ValueError:
            continue
        if target_net.version != wl_net.version:
            continue
        if target_net.overlaps(wl_net):
            return True
    return False


def evaluate_auto_blackhole(
    target: str,
    direction: str,
    whitelist: Optional[list[str]] = None,
) -> BlackholeVerdict:
    """Decide whether auto-blackhole is allowed for a given target.

    Outbound attacks: target is the internal source IP.
    Inbound attacks: target is the internal destination IP.
    Both directions must respect the whitelist.
    """
    if direction not in ("inbound", "outbound", "any"):
        return BlackholeVerdict(allowed=False, reason=f"Invalid direction: {direction}")

    if is_protected(target, whitelist):
        return BlackholeVerdict(
            allowed=False,
            reason=f"Target {target} is whitelisted (infrastructure protection)"
        )

    return BlackholeVerdict(allowed=True, reason="Target not whitelisted")


def check_manual_blackhole(
    prefix: str,
    whitelist: Optional[list[str]] = None,
) -> Optional[str]:
    """Validate a manual blackhole request. Returns error string if denied, None if allowed."""
    normalized = normalize_prefix(prefix)
    if is_protected(normalized, whitelist):
        return f"Prefix {normalized} is whitelisted and cannot be blackholed"
    return None


async def load_whitelist(db) -> list[str]:
    """Load custom whitelist from MongoDB. Falls back to DEFAULT_WHITELIST if none stored."""
    try:
        doc = await db.integration_settings.find_one({"_id": "ddos_whitelist"})
        if doc and isinstance(doc.get("prefixes"), list):
            # Validate each entry is a valid CIDR
            valid = []
            for p in doc["prefixes"]:
                try:
                    valid.append(normalize_prefix(p))
                except ValueError:
                    continue
            if valid:
                # Mandatory safety defaults cannot be removed by customization.
                return list(dict.fromkeys(DEFAULT_WHITELIST + valid))
    except Exception:
        pass
    return DEFAULT_WHITELIST


# ---------------------------------------------------------------------------
# Mitigation strategy selection (pure logic)
# ---------------------------------------------------------------------------
# Automated mitigation paths are intentionally limited. Interface shutdown is
# forbidden on this border router because several interfaces carry upstream
# VLAN tags. Raw firewall rules are NOT a primary volumetric mitigation because
# packets still hit the router CPU before being dropped, so the router can die
# before the filter helps.
#
# Allowed strategies:
#   alert          - notify only, no automatic action
#   local_blackhole- /32 blackhole route on the router (reduces CPU, not link)
#   bgp_rtbh       - announce /32 to upstream with a blackhole community
# ---------------------------------------------------------------------------
VOLUMETRIC_ATTACK_TYPES: set[str] = {
    "UDP Flood",
    "DNS Amplification",
    "Traffic Anomaly",
    "ICMP Flood",
    "NTP Amplification",
    "SSDP Amplification",
}

MITIGATION_STRATEGIES: set[str] = {"alert", "local_blackhole", "bgp_rtbh"}


def select_mitigation_strategy(
    severity: str,
    attack_type: str,
    scope_prefixes: list[str],
    upstream_peer_available: bool,
    direction: str = "inbound",
) -> str:
    """Return the best automated mitigation strategy for an incident.

    Selection rules:
      - No scope prefixes → alert only (don't act on unknown targets).
      - Severity medium or low → alert only.
      - Critical or high + volumetric attack + upstream peer available → bgp_rtbh.
      - Critical or high + volumetric attack, no upstream peer → local_blackhole.
      - Critical or high + **non-volumetric** attack (HTTP/SYN flood, unknown):
        never auto-blackhole an inbound target. Blackholing the victim's own
        address disconnects the customer without addressing the cause — L7 and
        SYN floods need rate-limiting/WAF/edge controls, not a route drop.
        Outbound is the exception: the target is our own internal *source*
        attacking somebody else, so dropping it there is the correct action.

    ``direction`` defaults to ``inbound`` so existing callers keep the safe
    behaviour unless they explicitly pass a direction.
    """
    if not scope_prefixes:
        return "alert"

    if severity in ("low", "medium"):
        return "alert"

    if severity in ("critical", "high") and attack_type in VOLUMETRIC_ATTACK_TYPES:
        return "bgp_rtbh" if upstream_peer_available else "local_blackhole"

    # Critical/high non-volumetric (e.g. HTTP/SYN flood) or unknown type.
    if direction == "outbound":
        return "bgp_rtbh" if upstream_peer_available else "local_blackhole"

    return "alert"