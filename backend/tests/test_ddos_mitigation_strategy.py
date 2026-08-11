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


# 4. High severity + HTTP Flood → local blackhole even with upstream peer
#    (HTTP is L7, not volumetric at link level, BGP RTBH is overkill)
def test_high_http_flood_prefers_local():
    strategy = select_mitigation_strategy(
        severity="high",
        attack_type="HTTP Flood",
        scope_prefixes=["157.20.32.0/24"],
        upstream_peer_available=True,
    )
    assert strategy == "local_blackhole"


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


# 9. Critical SYN Flood + no upstream → local_blackhole
def test_critical_syn_flood_no_upstream():
    strategy = select_mitigation_strategy(
        severity="critical",
        attack_type="SYN Flood",
        scope_prefixes=["157.20.32.0/24"],
        upstream_peer_available=False,
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


# 12. Non-volumetric types → local_blackhole (even with upstream peer)
@pytest.mark.parametrize("atk", [
    "HTTP Flood",
    "SYN Flood",
])
def test_non_volumetric_types_local_blackhole(atk):
    strategy = select_mitigation_strategy(
        severity="high",
        attack_type=atk,
        scope_prefixes=["157.20.32.0/24"],
        upstream_peer_available=True,
    )
    assert strategy == "local_blackhole"