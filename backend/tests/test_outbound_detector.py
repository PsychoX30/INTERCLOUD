"""Unit tests for the outbound abuse detector — pure logic, no Mongo.

Each test states the *operational* claim it protects, because the cost of a bug
here is a disconnected customer, not a red build.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from portal import outbound_detector as od  # noqa: E402
from portal import outbound_guard as og  # noqa: E402


def _flow(src, dst, packets=10, bytes_=14000, tcp_flags=od.TCP_ACK, proto="tcp"):
    return {"src_ip": src, "dst_ip": dst, "packets": packets, "bytes_": bytes_,
            "tcp_flags": tcp_flags, "protocol": proto}


CFG = od.merge_config(None)


# ---------------------------------------------------------------------------
# Baseline behaviour: legitimate traffic must never score
# ---------------------------------------------------------------------------
def test_bulk_upload_is_not_an_attack():
    """A 900 Mbps backup to one peer: volume alone must not trigger anything."""
    flows = [_flow("103.28.14.9", "8.8.8.8",
                   packets=60_000, bytes_=90_000_000, tcp_flags=od.TCP_ACK)
             for _ in range(20)]
    metrics = od.measure("103.28.14.9", flows, window_s=10)
    score = od.score_window(metrics, CFG)
    assert metrics.pps == 120_000            # far above every nuisance threshold
    assert score.signals["S1_syn_flood"] is False
    assert score.signals["S3_small_packets"] is False
    assert score.signals["S4_no_return"] is False
    assert score.score <= 1
    assert score.would_block is False


def test_busy_web_crawler_is_not_an_attack():
    """Many destinations, small-ish packets, but completed handshakes.

    This is the closest legitimate shape to a SYN flood: a crawler opens
    thousands of connections to many hosts. It must stay below the blocking
    bar, otherwise every SEO tool on the network gets disconnected.
    """
    flows = []
    for i in range(300):
        dst = f"93.184.{i % 200}.{i % 250 + 1}"
        flows.append(_flow("103.28.14.20", dst, packets=8, bytes_=900,
                           tcp_flags=od.TCP_SYN))
        flows.append(_flow("103.28.14.20", dst, packets=8, bytes_=6000,
                           tcp_flags=od.TCP_SYN | od.TCP_ACK))
    metrics = od.measure("103.28.14.20", flows, window_s=10)
    score = od.score_window(metrics, CFG)
    assert metrics.dst_diversity >= 200          # S2 fires
    assert score.signals["S4_no_return"] is False  # replies came back
    assert score.score < int(CFG["min_score_to_block"])


def test_quiet_target_is_gated_out():
    flows = [_flow("103.28.14.30", "8.8.8.8", packets=1, bytes_=60)]
    metrics = od.measure("103.28.14.30", flows, window_s=10)
    score = od.score_window(metrics, CFG)
    assert score.signals["gated"] is True
    assert score.score == 0


# ---------------------------------------------------------------------------
# Attack shapes
# ---------------------------------------------------------------------------
def _syn_flood(src="103.28.14.50", dsts=400, packets=900, window_s=10):
    flows = []
    for i in range(dsts):
        flows.append(_flow(src, f"45.{i % 250}.{i % 200}.{i % 180 + 1}",
                           packets=packets, bytes_=60, tcp_flags=od.TCP_SYN))
    return flows


def test_s4_needs_a_real_reply_count():
    """S4 must be measured from the opposite direction, not assumed.

    Production evidence (2026-11-13): every busy source looked like a fanout of
    167-715 because SYN-ACK replies are flows whose source is the remote peer
    and therefore never appear in a per-source aggregation. Without the reply
    count, S4 fires on any source that sends SYNs at all.
    """
    flows = _syn_flood(src="103.28.14.70", dsts=50, packets=200)
    measured = od.measure("103.28.14.70", flows, window_s=10)
    assert measured.synack_packets == 0
    assert measured.fanout_ratio == float("inf")

    answered = od.measure("103.28.14.70", flows, window_s=10,
                          inbound_replies=9_000)
    assert answered.synack_packets == 9_000
    assert answered.fanout_ratio < 2
    signals = od.evaluate_signals(answered, CFG)
    assert signals["S4_no_return"] is False


def test_syn_flood_fires_all_shape_signals():
    flows = _syn_flood()
    metrics = od.measure("103.28.14.50", flows, window_s=10)
    signals = od.evaluate_signals(metrics, CFG)
    assert signals["S1_syn_flood"] is True, metrics.syn_share
    assert signals["S2_dst_fanout"] is True
    assert signals["S3_small_packets"] is True
    assert signals["S4_no_return"] is True


def test_instant_safety_net_needs_two_windows_by_default():
    """A 150 kpps SYN volley used to block on its first window.

    One window can still be an artefact (the router flushing buffered
    counters), so the default now confirms twice; the delay costs ~10 s at a
    rate no legitimate host here sends.
    """
    cfg = od.merge_config({"instant_critical_pps": 100_000})
    flows = [_flow("103.28.14.60", f"45.0.{i % 250}.{i % 200 + 1}",
                   packets=30_000, bytes_=60, tcp_flags=od.TCP_SYN)
             for i in range(40)]
    metrics = od.measure("103.28.14.60", flows, window_s=10)
    tracker = od.OutboundTracker()
    first = tracker.update([od.score_window(metrics, cfg)], cfg)[0]
    assert first.instant is True
    assert first.would_block is False
    assert "1/2" in first.reason
    second = tracker.update([od.score_window(metrics, cfg)], cfg)[0]
    assert second.would_block is True
    assert "bypasses confirmation" in second.reason


def test_instant_safety_net_can_still_fire_on_one_window():
    cfg = od.merge_config({"instant_critical_pps": 100_000,
                           "instant_confirm_windows": 1})
    flows = [_flow("103.28.14.60", f"45.0.{i % 250}.{i % 200 + 1}",
                   packets=30_000, bytes_=60, tcp_flags=od.TCP_SYN)
             for i in range(40)]
    metrics = od.measure("103.28.14.60", flows, window_s=10)
    scores = od.OutboundTracker().update([od.score_window(metrics, cfg)], cfg)
    assert scores[0].would_block is True


def test_non_authoritative_window_is_never_scored():
    """A clamped poll must not reach the scorer, let alone the router.

    The gate exists because a sub-second span turns a handful of packets into
    an arbitrary rate, and a clamped window still carries a non-zero
    ``window_s`` that would look trustworthy to a caller that only checked
    ``window_s > 0``. Scoring such a window would let the absolute safety net
    trip on arithmetic rather than on traffic.
    """
    import asyncio
    from portal import outbound_sweep as sweep

    class _Cfg:
        async def find_one(self, *a, **k):
            return {"mode": "enforce", "enabled": True}

    class _DB:
        ddos_detection_config = _Cfg()

    class _Poison:
        def __iter__(self):
            raise AssertionError("flows must not be read for a bad window")

    sweep.invalidate_config_cache()
    out = asyncio.run(sweep.run_outbound_sweep(
        _DB(), _Poison(), 1.0, [], ["157.20.32.0/24"], authoritative=False))
    assert out.get("scored") is None
    assert "non-authoritative" in out.get("skipped", "")


# ---------------------------------------------------------------------------
# Persistence (S5) and confirmation
# ---------------------------------------------------------------------------
def test_block_requires_consecutive_windows():
    cfg = od.merge_config({"confirm_windows": 3})
    flows = _syn_flood()
    tracker = od.OutboundTracker()
    outcomes = []
    for _ in range(4):
        metrics = od.measure("103.28.14.50", flows, window_s=10)
        score = tracker.update([od.score_window(metrics, cfg)], cfg)[0]
        outcomes.append(score.would_block)
    assert outcomes == [False, False, True, True], outcomes


def test_gap_resets_confidence_gradually():
    """One missed window must not reset a flood, but silence must decay."""
    cfg = od.merge_config({"confirm_windows": 2})
    tracker = od.OutboundTracker()
    flows = _syn_flood()
    hot = od.measure("103.28.14.50", flows, window_s=10)
    tracker.update([od.score_window(hot, cfg)], cfg)
    assert tracker.consecutive("103.28.14.50") == 1
    tracker.update([], cfg)          # window with no traffic at all
    assert tracker.consecutive("103.28.14.50") == 0
    tracker.update([], cfg)
    assert tracker.consecutive("103.28.14.50") == 0


def test_penalty_ladder_walks_and_caps():
    cfg = od.merge_config({"penalty_ladder_hours": [0.5, 6, 24, -1]})
    assert od.penalty_hours(1, cfg) == 0.5
    assert od.penalty_hours(2, cfg) == 6
    assert od.penalty_hours(3, cfg) == 24
    assert od.penalty_hours(4, cfg) == -1
    assert od.penalty_hours(99, cfg) == -1   # caps, never crashes


# ---------------------------------------------------------------------------
# Config handling
# ---------------------------------------------------------------------------
def test_unknown_config_keys_are_dropped():
    cfg = od.merge_config({"syn_ratio_min": 0.9, "not_a_field": 1, "mode": "enforce"})
    assert cfg["syn_ratio_min"] == 0.9
    assert cfg["mode"] == "enforce"
    assert "not_a_field" not in cfg


def test_overrides_apply_per_target_only():
    cfg = od.merge_config(None)
    tuned = od.apply_overrides(cfg, [{"field": "syn_ratio_min", "value": 0.95}])
    assert tuned["syn_ratio_min"] == 0.95
    assert cfg["syn_ratio_min"] == od.DEFAULT_CONFIG["syn_ratio_min"]


def test_mode_defaults_to_shadow():
    assert od.DEFAULT_CONFIG["mode"] == "shadow"


# ---------------------------------------------------------------------------
# Guard: target validation and enforcer resolution
# ---------------------------------------------------------------------------
def test_only_host_prefixes_are_accepted():
    assert og.validate_target("103.28.14.9")[0] == "103.28.14.9"
    assert og.validate_target("103.28.14.9/32")[0] == "103.28.14.9"
    assert og.validate_target("103.28.14.0/24")[1] is not None
    assert og.validate_target("not-an-ip")[1] is not None


def _device(name, host, role="enforcer", sites=None, priority=0, enabled=True):
    return {"_id": name, "name": name, "host": host, "collection_role": role,
            "sites": sites or [], "priority": priority, "block_enabled": enabled}


PREFIXES = [
    {"prefix": "103.28.14.0/24", "site": "Cyber 1 - Metta"},
    {"prefix": "103.28.15.0/24", "site": "Cyber 1 - Omni"},
]


def test_most_specific_enforcer_wins():
    """The router closest to the customer enforces, not the border."""
    devices = [_device("CORE", "10.0.0.1"),
               _device("JKT", "10.0.0.2", sites=["Cyber 1 - Metta"])]
    order = og.resolve_enforcers("103.28.14.9", devices, PREFIXES)
    assert order[0].device["name"] == "JKT"
    assert order[0].specificity == 24
    assert order[1].device["name"] == "CORE"


def test_non_enforcer_devices_are_ignored():
    devices = [_device("SWITCH", "10.0.0.9", role="none"),
               _device("EXPORT", "10.0.0.8", role="exporter")]
    assert og.resolve_enforcers("103.28.14.9", devices, PREFIXES) == []


def test_block_disabled_device_is_ignored():
    devices = [_device("JKT", "10.0.0.2", sites=["Cyber 1 - Metta"], enabled=False)]
    assert og.resolve_enforcers("103.28.14.9", devices, PREFIXES) == []


def test_priority_breaks_ties_deterministically():
    devices = [_device("A", "10.0.0.2", sites=["Cyber 1 - Metta"], priority=1),
               _device("B", "10.0.0.3", sites=["Cyber 1 - Metta"], priority=5)]
    order = og.resolve_enforcers("103.28.14.9", devices, PREFIXES)
    assert [c.device["name"] for c in order] == ["B", "A"]


# ---------------------------------------------------------------------------
# Drop-rule placement: a rule that cannot fire is not a block
# ---------------------------------------------------------------------------
class _FakeFilter:
    """Enough of ``/ip/firewall/filter`` to exercise ordering."""

    def __init__(self, rows, move_ok=True):
        self.rows = [dict(r) for r in rows]
        self.move_ok = move_ok
        self._n = 0

    def __iter__(self):
        return iter([dict(r) for r in self.rows])

    def _ids(self):
        return [r[".id"] for r in self.rows]

    def add(self, **params):
        params = dict(params)
        self._n += 1
        row = {".id": f"*{900 + self._n}"}
        anchor = params.pop("place-before", None)
        row.update(params)
        if anchor:
            self.rows.insert(self._ids().index(anchor), row)
        else:
            self.rows.append(row)
        return row[".id"]

    def __call__(self, cmd, **kwargs):
        assert cmd == "move", cmd
        if not self.move_ok:
            raise RuntimeError("no such command prefix")
        row = next(r for r in self.rows if r[".id"] == kwargs[".id"])
        self.rows.remove(row)
        self.rows.insert(self._ids().index(kwargs["destination"]), row)
        return iter(())


class _FakeApi:
    def __init__(self, rows, move_ok=True):
        self.filter = _FakeFilter(rows, move_ok)

    def path(self, *parts):
        assert parts == ("ip", "firewall", "filter"), parts
        return self.filter


def _forward(rows):
    return [(str(r.get("chain")), str(r.get("action"))) for r in rows
            if str(r.get("chain") or "") == "forward"]


def test_drop_rule_is_inserted_above_an_existing_forward_accept():
    """An accept rule already in the chain must never sit above the drop."""
    api = _FakeApi([
        {".id": "*1", "chain": "input", "action": "drop", "protocol": "icmp"},
        {".id": "*2", "chain": "forward", "action": "accept",
         "connection-state": "established,related"},
    ])
    result = og.ensure_drop_rule(api)
    assert result["ok"] is True and result["created"] is True
    assert result["position"] == 0
    assert _forward(api.filter.rows)[0] == ("forward", "drop")


def test_drop_rule_that_drifted_down_is_moved_back_up():
    api = _FakeApi([
        {".id": "*1", "chain": "forward", "action": "accept"},
        {".id": "*2", "chain": "forward", "src-address-list": og.SRCBLOCK_LIST,
         "action": "drop"},
    ])
    result = og.ensure_drop_rule(api)
    assert result["ok"] is True and result["created"] is False
    assert result["moved"] is True and result["position"] == 0
    assert _forward(api.filter.rows)[0] == ("forward", "drop")


def test_shadowed_drop_rule_is_reported_as_a_failure():
    """RouterOS without ``move`` must not be reported as a working block."""
    api = _FakeApi([
        {".id": "*1", "chain": "forward", "action": "accept"},
        {".id": "*2", "chain": "forward", "src-address-list": og.SRCBLOCK_LIST,
         "action": "drop"},
    ], move_ok=False)
    result = og.ensure_drop_rule(api)
    assert result["ok"] is False
    assert result["position"] == 1
    assert "shadow" in result["error"]


# ---------------------------------------------------------------------------
# Block lifecycle against a librouteros-v4-shaped fake
# ---------------------------------------------------------------------------
class _Table:
    """A RouterOS menu: iterate to print, ``add(**p)``, ``remove(*ids)``."""

    def __init__(self):
        self.rows = []
        self._n = 0

    def __iter__(self):
        return iter([dict(r) for r in self.rows])

    def add(self, **params):
        params = dict(params)
        self._n += 1
        row = {".id": f"*{self._n:03d}"}
        anchor = params.pop("place-before", None)
        row.update(params)
        if anchor:
            self.rows.insert([r[".id"] for r in self.rows].index(anchor), row)
        else:
            self.rows.append(row)
        return row[".id"]

    def remove(self, *ids):
        # v4 semantics: ids are positional.  ``.id=`` as a keyword argument is
        # a TypeError, which is exactly the bug this guards against.
        wanted = set(ids)
        self.rows = [r for r in self.rows if r[".id"] not in wanted]

    def __call__(self, cmd, **kwargs):
        raise AssertionError(f"unexpected command {cmd} {kwargs}")


class _FakeRouter:
    def __init__(self):
        self.filter = _Table()
        self.address_list = _Table()

    def path(self, *parts):
        if parts == ("ip", "firewall", "filter"):
            return self.filter
        if parts == ("ip", "firewall", "address-list"):
            return self.address_list
        raise AssertionError(parts)


class _Session:
    def __init__(self, api):
        self.api = api

    def __enter__(self):
        return self.api

    def __exit__(self, *exc):
        return False


class _FakeClient:
    def __init__(self):
        self.api = _FakeRouter()

    def session(self):
        return _Session(self.api)


def test_block_round_trip_writes_reads_and_lifts():
    client = _FakeClient()
    first = og.apply_block(client, "203.0.113.9", hours=0.5, incident_id="t1")
    assert first["ok"] is True and first["verified"] is True
    assert first["timeout"] == "30m" and first["rule_position"] == 0
    assert len(client.api.address_list.rows) == 1

    # Re-blocking the same IP must replace, not duplicate, the entry.
    second = og.apply_block(client, "203.0.113.9", hours=6, incident_id="t2")
    assert second["ok"] is True and second["timeout"] == "360m"
    assert len(client.api.address_list.rows) == 1
    assert second["rule_created"] is False

    lifted = og.remove_block(client, "203.0.113.9")
    assert lifted["ok"] is True and lifted["removed"] == 1
    assert client.api.address_list.rows == []
    # The rule is infrastructure, not a block: it must survive the lift.
    assert _forward(client.api.filter.rows) == [("forward", "drop")]


def test_permanent_block_is_written_without_a_timeout():
    client = _FakeClient()
    result = og.apply_block(client, "203.0.113.9", hours=-1, incident_id="perm")
    assert result["ok"] is True
    assert result["timeout"] == ""
    assert "timeout" not in client.api.address_list.rows[0]
