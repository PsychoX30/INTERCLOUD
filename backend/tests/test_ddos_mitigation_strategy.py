"""Test select_mitigation_strategy — pure logic, no router, no DB.

Policy (post-QA, fail-closed):
  - alert-only        : no automatic action.
  - local_blackhole   : /32 destination blackhole on our own router.
  - bgp_rtbh          : NOT auto-selected. Destination RTBH still requires a
                        verified provider routing policy (community, RouterOS
                        version/syntax, a non-destructive output-filter policy,
                        and proven rollback). A routing filter chain defaults to
                        reject on RouterOS; auto-attaching a one-rule RTBH chain
                        could withdraw every other announced prefix. So the
                        automatic detector never emits bgp_rtbh — it degrades to
                        local_blackhole for volumetric floods and alert for
                        everything else, until an operator has explicitly
                        validated the upstream capability.

Rules:
  1. No scope_prefixes      -> alert (never act on unknown targets).
  2. severity low/medium    -> alert.
  3. severity high/critical + volumetric -> local_blackhole (local drop only).
  4. severity high/critical + non-volumetric / unknown -> alert.
     - inbound: blackholing the victim's own address disconnects the customer
       without addressing the cause.
     - outbound: dropping an internal *source* by destination blackhole does not
       stop egress; source filtering needs provider-side uRPF/S-RTBH (RFC 5635
       §4), which is not modeled/verified. So outbound is alert too.
"""

from __future__ import annotations
import pytest

from portal.ddos_guard import select_mitigation_strategy


# 1. Critical + volumetric, upstream peer "available" -> local_blackhole
#    (bgp_rtbh is deliberately NOT auto-selected until verified).
def test_critical_volumetric_degrades_to_local():
    strategy = select_mitigation_strategy(
        severity="critical",
        attack_type="UDP Flood",
        scope_prefixes=["157.20.32.0/24"],
        upstream_peer_available=True,
    )
    assert strategy == "local_blackhole"


# 2. Critical + volumetric, no upstream peer -> local_blackhole
def test_critical_volumetric_falls_back_to_local():
    strategy = select_mitigation_strategy(
        severity="critical",
        attack_type="UDP Flood",
        scope_prefixes=["157.20.32.0/24"],
        upstream_peer_available=False,
    )
    assert strategy == "local_blackhole"


# 3. High + DNS Amplification -> local_blackhole (volumetric, no auto-BGP)
def test_high_dns_amplification_degrades_to_local():
    strategy = select_mitigation_strategy(
        severity="high",
        attack_type="DNS Amplification",
        scope_prefixes=["157.20.32.0/24"],
        upstream_peer_available=True,
    )
    assert strategy == "local_blackhole"


# 4. High + HTTP Flood (inbound) -> alert only.
def test_high_http_flood_inbound_alert_only():
    strategy = select_mitigation_strategy(
        severity="high",
        attack_type="HTTP Flood",
        scope_prefixes=["157.20.32.0/24"],
        upstream_peer_available=True,
        direction="inbound",
    )
    assert strategy == "alert"


# 5. Medium -> alert only
def test_medium_alert_only():
    strategy = select_mitigation_strategy(
        severity="medium",
        attack_type="UDP Flood",
        scope_prefixes=["157.20.32.0/24"],
        upstream_peer_available=True,
    )
    assert strategy == "alert"


# 6. Medium TCP SYN -> alert only
def test_medium_syn_flood_alert_only():
    strategy = select_mitigation_strategy(
        severity="medium",
        attack_type="SYN Flood",
        scope_prefixes=["157.20.32.0/24"],
        upstream_peer_available=False,
    )
    assert strategy == "alert"


# 7. Low -> alert only
def test_low_alert_only():
    strategy = select_mitigation_strategy(
        severity="low",
        attack_type="Traffic Anomaly",
        scope_prefixes=["157.20.32.0/24"],
        upstream_peer_available=True,
    )
    assert strategy == "alert"


# 8. High Traffic Anomaly -> local_blackhole (volumetric, no auto-BGP)
def test_high_traffic_anomaly_degrades_to_local():
    strategy = select_mitigation_strategy(
        severity="high",
        attack_type="Traffic Anomaly",
        scope_prefixes=["157.20.32.0/24"],
        upstream_peer_available=True,
    )
    assert strategy == "local_blackhole"


# 9. Critical SYN Flood inbound, no upstream -> alert (victim protection)
def test_critical_syn_flood_no_upstream_inbound_alert():
    strategy = select_mitigation_strategy(
        severity="critical",
        attack_type="SYN Flood",
        scope_prefixes=["157.20.32.0/24"],
        upstream_peer_available=False,
        direction="inbound",
    )
    assert strategy == "alert"


# 9b. Critical SYN Flood outbound -> alert (source filtering needs uRPF,
#     not modeled). NOT local_blackhole: a destination blackhole of our own
#     source does not stop egress.
def test_critical_syn_flood_outbound_alert():
    strategy = select_mitigation_strategy(
        severity="critical",
        attack_type="SYN Flood",
        scope_prefixes=["157.20.32.0/24"],
        upstream_peer_available=False,
        direction="outbound",
    )
    assert strategy == "alert"


# 10. No scope_prefixes -> alert only
def test_no_scope_alert_only():
    strategy = select_mitigation_strategy(
        severity="critical",
        attack_type="UDP Flood",
        scope_prefixes=[],
        upstream_peer_available=True,
    )
    assert strategy == "alert"


# 11. Volumetric types -> local_blackhole (no auto-BGP), regardless of peer.
@pytest.mark.parametrize("atk", [
    "UDP Flood",
    "DNS Amplification",
    "Traffic Anomaly",
])
def test_volumetric_types_local_blackhole(atk):
    strategy = select_mitigation_strategy(
        severity="critical",
        attack_type=atk,
        scope_prefixes=["157.20.32.0/24"],
        upstream_peer_available=True,
    )
    assert strategy == "local_blackhole"


# 12. Non-volumetric inbound -> alert
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


# 12b. Non-volumetric outbound -> alert (source filtering not modeled)
@pytest.mark.parametrize("atk", [
    "HTTP Flood",
    "SYN Flood",
])
def test_non_volumetric_types_outbound_alert(atk):
    strategy = select_mitigation_strategy(
        severity="high",
        attack_type=atk,
        scope_prefixes=["157.20.32.0/24"],
        upstream_peer_available=True,
        direction="outbound",
    )
    assert strategy == "alert"


def test_non_volumetric_inbound_is_alert_only():
    r = select_mitigation_strategy(
        "critical", "HTTP Flood", ["157.20.32.0/24"], True, direction="inbound")
    assert r == "alert"


def test_non_volumetric_outbound_is_alert_only():
    """Outbound source RTBH needs uRPF; not modeled -> alert, not drop."""
    r = select_mitigation_strategy(
        "critical", "HTTP Flood", ["157.20.32.0/24"], True, direction="outbound")
    assert r == "alert"


def test_non_volumetric_outbound_without_peer_is_alert():
    r = select_mitigation_strategy(
        "high", "SYN Flood", ["157.20.32.0/24"], False, direction="outbound")
    assert r == "alert"


def test_direction_defaults_to_inbound_safe():
    """Existing callers that omit direction keep the safe behavior."""
    r = select_mitigation_strategy("critical", "Unknown", ["157.20.32.0/24"], True)
    assert r == "alert"


def test_volumetric_inbound_degrades_to_local_not_bgp():
    r = select_mitigation_strategy(
        "critical", "UDP Flood", ["157.20.32.0/24"], True, direction="inbound")
    assert r == "local_blackhole"


def test_bgp_rtbh_is_never_auto_selected():
    """Fail-closed: the automatic detector must not emit bgp_rtbh until the
    upstream routing policy is explicitly verified by an operator."""
    for sev in ("high", "critical"):
        for atk in ("UDP Flood", "DNS Amplification", "Traffic Anomaly",
                    "HTTP Flood", "SYN Flood", "Unknown"):
            for d in ("inbound", "outbound"):
                for peer in (True, False):
                    r = select_mitigation_strategy(
                        sev, atk, ["157.20.32.0/24"], peer, direction=d)
                    assert r != "bgp_rtbh", \
                        f"bgp_rtbh auto-selected for {sev}/{atk}/{d}/peer={peer}"
