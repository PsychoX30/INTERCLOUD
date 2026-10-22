"""Test select_mitigation_strategy — pure logic, no router, no DB.

Policy: never interface-shutdown, never raw firewall as primary. The only
automated mitigation paths are:
  - local /32 blackhole (drop at router, reduces CPU but link still saturated)
  - upstream BGP community RTBH (drop at upstream, protects link bandwidth)
  - alert-only (no automatic action)

The strategy selection depends on severity, attack type, and available
upstream BGP peers.
"""

from __future__ import annotations
import pytest

# We import the module directly — it has no DB or router dependency.
from portal.ddos_guard import select_mitigation_strategy


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------

# 1. Critical + volumetric → BGP RTBH when upstream peer available
def test_critical_volumetric_prefers_bgp_rtbh():
    strategy = select_mitigation_strategy(
        severity="critical",
        attack_type="UDP Flood",
        scope_prefixes=["157.20.32.0/24"],
        upstream_peer_available=True,
    )
    assert strategy == "bgp_rtbh"


# 2. Critical + volumetric → local blackhole when NO upstream peer
def test_critical_volumetric_falls_back_to_local():
    strategy = select_mitigation_strategy(
        severity="critical",
        attack_type="UDP Flood",
        scope_prefixes=["157.20.32.0/24"],
        upstream_peer_available=False,
    )
    assert strategy == "local_blackhole"


# 3. High severity + DNS Amplification → BGP RTBH (DNS amp is volumetric)
def test_high_dns_amplification_prefers_bgp_rtbh():
    strategy = select_mitigation_strategy(
        severity="high",
        attack_type="DNS Amplification",
        scope_prefixes=["157.20.32.0/24"],
        upstream_peer_available=True,
    )
    assert strategy == "bgp_rtbh"


# 4. High severity + HTTP Flood (inbound) → alert only.
#    Superseded policy: an inbound L7 flood must NOT auto-blackhole the victim's
#    own address — that disconnects the customer without fixing the cause.
#    HTTP floods need rate-limit/WAF/edge controls. See QA finding #5.
def test_high_http_flood_inbound_alert_only():
    strategy = select_mitigation_strategy(
        severity="high",
        attack_type="HTTP Flood",
        scope_prefixes=["157.20.32.0/24"],
        upstream_peer_available=True,
        direction="inbound",
    )
    assert strategy == "alert"


# 5. Medium severity → alert only, NO automatic mitigation
def test_medium_alert_only():
    strategy = select_mitigation_strategy(
        severity="medium",
        attack_type="UDP Flood",
        scope_prefixes=["157.20.32.0/24"],
        upstream_peer_available=True,
    )
    assert strategy == "alert"


# 6. Medium severity TCP SYN → alert only
def test_medium_syn_flood_alert_only():
    strategy = select_mitigation_strategy(
        severity="medium",
        attack_type="SYN Flood",
        scope_prefixes=["157.20.32.0/24"],
        upstream_peer_available=False,
    )
    assert strategy == "alert"


# 7. Low severity → alert only
def test_low_alert_only():
    strategy = select_mitigation_strategy(
        severity="low",
        attack_type="Traffic Anomaly",
        scope_prefixes=["157.20.32.0/24"],
        upstream_peer_available=True,
    )
    assert strategy == "alert"


# 8. High severity Traffic Anomaly + upstream available → BGP RTBH
def test_high_traffic_anomaly_bgp_rtbh():
    strategy = select_mitigation_strategy(
        severity="high",
        attack_type="Traffic Anomaly",
        scope_prefixes=["157.20.32.0/24"],
        upstream_peer_available=True,
    )
    assert strategy == "bgp_rtbh"


# 9. Critical SYN Flood + no upstream → alert only (inbound victim protection)
def test_critical_syn_flood_no_upstream_inbound_alert():
    strategy = select_mitigation_strategy(
        severity="critical",
        attack_type="SYN Flood",
        scope_prefixes=["157.20.32.0/24"],
        upstream_peer_available=False,
        direction="inbound",
    )
    assert strategy == "alert"


# 9b. Critical SYN Flood outbound + no upstream → local blackhole of our source
def test_critical_syn_flood_outbound_local():
    strategy = select_mitigation_strategy(
        severity="critical",
        attack_type="SYN Flood",
        scope_prefixes=["157.20.32.0/24"],
        upstream_peer_available=False,
        direction="outbound",
    )
    assert strategy == "local_blackhole"


# 10. No scope_prefixes → alert only (don't blackhole unknown targets)
def test_no_scope_alert_only():
    strategy = select_mitigation_strategy(
        severity="critical",
        attack_type="UDP Flood",
        scope_prefixes=[],
        upstream_peer_available=True,
    )
    assert strategy == "alert"


# 11. Volumetric attack types only — verify the classification
@pytest.mark.parametrize("atk", [
    "UDP Flood",
    "DNS Amplification",
    "Traffic Anomaly",
])
def test_volumetric_types_are_recognized(atk):
    strategy = select_mitigation_strategy(
        severity="critical",
        attack_type=atk,
        scope_prefixes=["157.20.32.0/24"],
        upstream_peer_available=True,
    )
    assert strategy == "bgp_rtbh"


# 12. Non-volumetric types, inbound → alert only (victim must not be dropped)
@pytest.mark.parametrize("atk", [
    "HTTP Flood",
    "SYN Flood",
])
def test_non_volumetric_types_inbound_alert(atk):
    strategy = select_mitigation_strategy(
        severity="high",
        attack_type=atk,
        scope_prefixes=["157.20.32.0/24"],
        upstream_peer_available=True,
        direction="inbound",
    )
    assert strategy == "alert"


# 12b. Same types, outbound → our attacking source IS mitigated
@pytest.mark.parametrize("atk", [
    "HTTP Flood",
    "SYN Flood",
])
def test_non_volumetric_types_outbound_mitigated(atk):
    strategy = select_mitigation_strategy(
        severity="high",
        attack_type=atk,
        scope_prefixes=["157.20.32.0/24"],
        upstream_peer_available=True,
        direction="outbound",
    )
    assert strategy == "bgp_rtbh"

def test_non_volumetric_inbound_is_alert_only():
    """An inbound L7/SYN flood must NOT auto-blackhole the victim."""
    r = select_mitigation_strategy(
        "critical", "HTTP Flood", ["157.20.32.0/24"], True, direction="inbound")
    assert r == "alert"


def test_non_volumetric_outbound_still_mitigates():
    """Outbound target is our own attacking source -> drop it."""
    r = select_mitigation_strategy(
        "critical", "HTTP Flood", ["157.20.32.0/24"], True, direction="outbound")
    assert r == "bgp_rtbh"


def test_non_volumetric_outbound_without_peer_is_local():
    r = select_mitigation_strategy(
        "high", "SYN Flood", ["157.20.32.0/24"], False, direction="outbound")
    assert r == "local_blackhole"


def test_direction_defaults_to_inbound_safe():
    """Existing callers that omit direction keep the safe behavior."""
    r = select_mitigation_strategy("critical", "Unknown", ["157.20.32.0/24"], True)
    assert r == "alert"


def test_volumetric_inbound_still_uses_rtbh():
    r = select_mitigation_strategy(
        "critical", "UDP Flood", ["157.20.32.0/24"], True, direction="inbound")
    assert r == "bgp_rtbh"
