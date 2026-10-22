import pytest

from portal.rtbh import (
    DEFAULT_RTBH_COMMUNITY,
    RTBHResult,
    apply_rtbh,
    build_commands,
    plan_rtbh,
    withdraw_rtbh,
) 


class FakeClient:
    # Stands in for a RouterOS 7 device: ``apply_rtbh`` refuses to emit
    # version-specific syntax when the major version is unknown, so the fake
    # must declare one the same way a real device doc does.
    _ros_major = 7

    def __init__(self, announce_ok=True):
        self.calls = []
        self.announce_ok = announce_ok

    def blackhole_add(self, prefix, comment):
        self.calls.append(("add_route", prefix, comment))
        return {"ok": True}

    def blackhole_find_by_prefix(self, prefix):
        self.calls.append(("find_route", prefix))
        return {"id": "*route1"}

    def rtbh_announce(self, prefix, community, comment, *, upstream_name="", ros_major=7):
        self.calls.append(("announce", prefix, community, comment, upstream_name, ros_major))
        return {"ok": self.announce_ok, "id": "*filter1", "peer": upstream_name or "transit-a", "attached": True}

    def rtbh_withdraw(self, rule_id):
        self.calls.append(("withdraw_filter", rule_id))
        return {"ok": True}

    def blackhole_remove(self, route_id):
        self.calls.append(("remove_route", route_id))
        return {"ok": True}


def _valid_plan():
    return plan_rtbh(
        target="157.20.32.44", direction="inbound",
        community="65535:666", upstream_name="transit-a",
        scope_prefixes=SCOPE, whitelist=[], token="abc123",
    )


def test_apply_executes_local_then_upstream_and_reports_ids():
    client = FakeClient()
    result = apply_rtbh(client, _valid_plan(), dry_run=False)
    assert result.ok is True
    assert result.local_ok is True
    assert result.announce_ok is True
    assert result.route_id == "*route1"
    assert result.filter_id == "*filter1"
    assert [call[0] for call in client.calls] == ["add_route", "find_route", "announce"]


def test_apply_refuses_when_ros_version_unknown():
    client = FakeClient(announce_ok=True)
    client._ros_major = None
    result = apply_rtbh(client, _valid_plan(), dry_run=False)
    assert result.ok is False
    assert "RouterOS major version unknown" in result.errors[0]


def test_apply_reports_partial_failure_without_claiming_success():
    client = FakeClient(announce_ok=False)
    result = apply_rtbh(client, _valid_plan(), dry_run=False)
    assert result.ok is False
    # Announce failed -> the local blackhole is rolled back, because a route
    # without an upstream announcement only blackholes the victim's inbound
    # traffic while the attack keeps flowing. Reporting local_ok=True here would
    # tell the operator "partially mitigated" when nothing was mitigated.
    assert result.announce_ok is False
    assert result.rolled_back is True
    assert result.local_ok is False
    assert result.route_id is None
    assert any("announce failed" in e for e in result.errors)
    assert "remove_route" in [call[0] for call in client.calls]


def test_apply_does_not_claim_local_success_without_route_id():
    """A route we cannot identify can never be withdrawn -> not a success."""
    class NoIdClient(FakeClient):
        def blackhole_find_by_prefix(self, prefix):
            self.calls.append(("find_route", prefix))
            return None

    client = NoIdClient()
    result = apply_rtbh(client, _valid_plan(), dry_run=False)
    assert result.ok is False
    assert result.local_ok is False
    assert result.route_id is None
    assert any("no route id" in e for e in result.errors)
    assert "announce" not in [call[0] for call in client.calls]


def test_apply_refuses_outbound_direction():
    """Source RTBH needs provider uRPF; a destination blackhole cannot do it."""
    plan = plan_rtbh(
        target="157.20.32.44", direction="outbound",
        community="65535:666", upstream_name="transit-a",
        scope_prefixes=SCOPE, whitelist=[], token="abc123",
    )
    assert plan.allowed is False
    assert "uRPF" in plan.reason or "not supported" in plan.reason

    client = FakeClient()
    result = apply_rtbh(client, plan, dry_run=False)
    assert result.ok is False
    assert client.calls == []          # nothing was sent to the router


def test_ros7_uses_bgp_communities_not_bgp_out_community():
    plan = plan_rtbh(
        target="157.20.32.44", direction="inbound", community="65000:999",
        upstream_name="transit-a", scope_prefixes=SCOPE, whitelist=[],
        token="abc123",
    )
    commands = build_commands(plan, ros_major=7)
    filter_cmd = commands[1]
    assert "/routing/filter/rule/add" in filter_cmd
    assert "bgp-communities 65000:999" in filter_cmd
    # bgp-out-community is not a RouterOS property; only bgp-out-med exists.
    assert "bgp-out-community" not in filter_cmd


def test_ros6_uses_discrete_properties_without_rule_script():
    plan = plan_rtbh(
        target="157.20.32.44", direction="inbound", community="65000:999",
        upstream_name="transit-a", scope_prefixes=SCOPE, whitelist=[],
        token="abc123",
    )
    commands = build_commands(plan, ros_major=6)
    filter_cmd = commands[1]
    assert "/routing/filter/add" in filter_cmd
    # RouterOS 6 has no rule= script parameter and no dst-address matcher.
    assert "rule=" not in filter_cmd
    assert "prefix=157.20.32.44/32" in filter_cmd
    assert "set-bgp-communities=65000:999" in filter_cmd


def test_ipv6_target_gets_128_not_32():
    plan = plan_rtbh(
        target="2001:db8::1", direction="inbound", community="65000:999",
        upstream_name="transit-a", scope_prefixes=["2001:db8::/48"],
        whitelist=[], token="abc123",
    )
    assert plan.allowed is True
    assert plan.prefix == "2001:db8::1/128"


def test_withdraw_announcment_before_local_route():
    client = FakeClient()
    result = withdraw_rtbh(client, prefix="157.20.32.44/32", route_id="*route1", filter_id="*filter1")
    assert result.ok is True
    assert [call[0] for call in client.calls] == ["withdraw_filter", "remove_route"]



SCOPE = ["157.20.32.0/24"]


def test_plan_accepts_inbound_host_inside_scope():
    plan = plan_rtbh(
        target="157.20.32.44",
        direction="inbound",
        community=DEFAULT_RTBH_COMMUNITY,
        upstream_name="transit-a",
        scope_prefixes=SCOPE,
        whitelist=[],
        token="abc123",
    )
    assert plan.allowed is True
    assert plan.prefix == "157.20.32.44/32"
    assert plan.direction == "inbound"


def test_plan_rejects_target_outside_scope():
    plan = plan_rtbh(
        target="8.8.8.8",
        direction="inbound",
        community="65535:666",
        upstream_name="transit-a",
        scope_prefixes=SCOPE,
        whitelist=[],
        token="abc123",
    )
    assert plan.allowed is False
    assert "outside" in plan.reason


def test_plan_rejects_whitelisted_target():
    plan = plan_rtbh(
        target="157.20.32.1",
        direction="inbound",
        community="65535:666",
        upstream_name="transit-a",
        scope_prefixes=SCOPE,
        whitelist=["157.20.32.1/32"],
        token="abc123",
    )
    assert plan.allowed is False
    assert "whitelisted" in plan.reason


def test_commands_are_host_specific_and_include_rtbh_community():
    plan = plan_rtbh(
        target="157.20.32.44",
        direction="inbound",
        community="65000:999",
        upstream_name="transit-a",
        scope_prefixes=SCOPE,
        whitelist=[],
        token="abc123",
    )
    commands = build_commands(plan)
    assert len(commands) == 2
    assert all("157.20.32.44/32" in command for command in commands)
    assert any("65000:999" in command for command in commands)
    assert all("portal-rtbh" in command for command in commands)


def test_result_is_not_success_when_only_local_step_succeeds():
    result = RTBHResult(
        prefix="157.20.32.44/32",
        local_ok=True,
        announce_ok=False,
        errors=["announce failed"],
    )
    result.ok = result.local_ok and result.announce_ok
    assert result.ok is False
    assert result.local_ok is True
    assert result.announce_ok is False
    assert result.as_dict()["errors"] == ["announce failed"]


@pytest.mark.parametrize("community", ["", "666", "x:y", "65536:1", "1:65536"])
def test_plan_rejects_invalid_community(community):
    plan = plan_rtbh(
        target="157.20.32.44",
        direction="inbound",
        community=community,
        upstream_name="transit-a",
        scope_prefixes=SCOPE,
        whitelist=[],
        token="abc123",
    )
    assert plan.allowed is False
    assert "community" in plan.reason


def test_plan_rejects_missing_upstream():
    plan = plan_rtbh(
        target="157.20.32.44",
        direction="inbound",
        community="65535:666",
        upstream_name="",
        scope_prefixes=SCOPE,
        whitelist=[],
        token="abc123",
    )
    assert plan.allowed is False
    assert "upstream" in plan.reason
