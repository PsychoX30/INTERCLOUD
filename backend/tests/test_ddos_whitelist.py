"""Whitelist guard: critical IPs must never be blackholed (auto or manual).

Customer-facing services are NATed behind a shared gateway IP. Blackholing
that gateway would take every customer offline. So a whitelist is enforced at
the backend for BOTH the auto-mitigation path and the manual /admin/mikrotik/
blackhole endpoint.

These tests are pure/logic-level (no live router, no DB) so they run anywhere.
"""
from __future__ import annotations

import pytest

from portal import ddos_guard as guard


# ---- helper: normalize prefix helpers ----
def test_whitelist_defaults_include_loopback_and_documentation():
    """Default whitelist must never be empty and must include our own
    protected infrastructure by default."""
    wl = guard.DEFAULT_WHITELIST
    assert isinstance(wl, list) and len(wl) > 0
    # 127.0.0.0/8 must always be protected
    assert any("127.0.0.0/8" in p or "127.0.0.1/32" in p for p in wl)


# ---- normalization ----
def test_normalize_prefix_accepts_plain_ip():
    assert guard.normalize_prefix("1.2.3.4") == "1.2.3.4/32"


def test_normalize_prefix_keeps_cidr():
    assert guard.normalize_prefix("1.2.3.0/24") == "1.2.3.0/24"


def test_normalize_prefix_rejects_garbage():
    with pytest.raises(ValueError):
        guard.normalize_prefix("not-an-ip")


# ---- membership ----
def test_whitelisted_exact_ip_is_protected():
    assert guard.is_protected("157.20.32.1/32", ["157.20.32.1/32"])


def test_whitelisted_cidr_contains_host():
    # gateway 157.20.32.254 inside 157.20.32.0/24 must be protected
    assert guard.is_protected("157.20.32.254/32", ["157.20.32.0/24"])


def test_non_whitelisted_ip_not_protected():
    assert not guard.is_protected("203.0.113.9/32", ["157.20.32.0/24"])


def test_external_destination_not_protected():
    assert not guard.is_protected("8.8.8.8/32", ["157.20.32.0/24"])


# ---- containment: a wider CIDR must not be used to bypass the whitelist ----
# Regression for a real safety hole: is_protected() used to test only the
# target's network_address, so a /24 or /16 whose *network address* was not
# itself whitelisted slipped through even though it contained the NAT gateway.
def test_wider_cidr_containing_gateway_is_protected():
    wl = ["157.20.32.1/32", "157.20.32.254/32"]
    # 157.20.32.0/24 contains both gateways -> blackholing it takes everyone down
    assert guard.is_protected("157.20.32.0/24", wl)
    assert guard.is_protected("157.20.0.0/16", wl)
    assert guard.is_protected("157.20.32.0/23", wl)


def test_wider_cidr_bypass_is_blocked_by_manual_guard():
    wl = ["157.20.32.1/32", "157.20.32.254/32"]
    assert guard.check_manual_blackhole("157.20.32.0/24", wl) is not None
    assert guard.check_manual_blackhole("157.20.0.0/16", wl) is not None


def test_wider_cidr_bypass_is_blocked_by_auto_guard():
    verdict = guard.evaluate_auto_blackhole(
        target="157.20.32.0/24", direction="inbound",
        whitelist=["157.20.32.254/32"])
    assert verdict.allowed is False


def test_disjoint_cidr_is_not_protected():
    # A /24 next door must stay actionable, otherwise the guard is useless.
    wl = ["157.20.32.254/32"]
    assert not guard.is_protected("157.20.33.0/24", wl)
    assert not guard.is_protected("157.21.0.0/16", wl)


def test_ipv6_and_ipv4_do_not_crash_or_match():
    # ip_network.overlaps() raises on mixed versions; the guard must not raise.
    assert not guard.is_protected("2001:db8::/32", ["157.20.32.254/32"])
    assert not guard.is_protected("157.20.32.10/32", ["2001:db8::/32"])


# ---- auto-mitigation decision ----
def test_auto_blackhole_denied_for_protected_target():
    verdict = guard.evaluate_auto_blackhole(
        target="157.20.32.254/32",
        direction="inbound",
        whitelist=["157.20.32.0/24"],
    )
    assert verdict.allowed is False
    assert "whitelist" in verdict.reason.lower()


def test_auto_blackhole_allowed_for_normal_target():
    verdict = guard.evaluate_auto_blackhole(
        target="157.20.32.10/32",
        direction="inbound",
        whitelist=["157.20.32.254/32"],
    )
    assert verdict.allowed is True


def test_auto_blackhole_outbound_targets_source_ip():
    # outbound: target is the internal source; must still respect whitelist
    verdict = guard.evaluate_auto_blackhole(
        target="157.20.32.254/32",
        direction="outbound",
        whitelist=["157.20.32.254/32"],
    )
    assert verdict.allowed is False


# ---- manual API guard ----
def test_manual_blackhole_denied_for_protected_prefix():
    err = guard.check_manual_blackhole(prefix="157.20.32.254/32",
                                       whitelist=["157.20.32.0/24"])
    assert err is not None
    assert "whitelist" in err.lower()


def test_manual_blackhole_allowed_for_normal_prefix():
    assert guard.check_manual_blackhole(prefix="203.0.113.9/32",
                                        whitelist=["157.20.32.0/24"]) is None


def test_manual_blackhole_allowed_for_external_prefix():
    # External prefixes (attackers) are fine to blackhole
    assert guard.check_manual_blackhole(prefix="8.8.8.8/32",
                                        whitelist=["157.20.32.0/24"]) is None


# ---- load_whitelist from DB ----
def test_load_whitelist_custom_from_db():
    """load_whitelist loads custom entries from MongoDB when present."""
    import asyncio

    class FakeDBSettings:
        async def find_one(self, query):
            if query.get("_id") == "ddos_whitelist":
                return {"prefixes": ["10.0.0.0/24", "192.168.1.1"]}
            return None

    class FakeDB:
        integration_settings = FakeDBSettings()

    async def run():
        result = await guard.load_whitelist(FakeDB())
        assert "10.0.0.0/24" in result
        assert "192.168.1.1/32" in result  # normalized to CIDR
        assert "157.20.32.1/32" in result  # default gateway still present

    asyncio.run(run())


def test_load_whitelist_fallback_to_default():
    """load_whitelist falls back to DEFAULT_WHITELIST when DB has no doc."""
    import asyncio

    class FakeDBSettings:
        async def find_one(self, query):
            return None

    class FakeDB:
        integration_settings = FakeDBSettings()

    async def run():
        result = await guard.load_whitelist(FakeDB())
        assert result == guard.DEFAULT_WHITELIST

    asyncio.run(run())
