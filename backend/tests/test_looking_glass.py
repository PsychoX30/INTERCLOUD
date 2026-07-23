"""Wire-level tests for the Looking Glass upgrades:

- BGP route lookup now uses `rawCmd('/ip/route/print', '?dst-address=…')`
  with longest-prefix scan (was: full-table dump + startswith filter that
  never matched a covering prefix like 103.133.20.0/24 for the IP
  103.133.20.5).
- ping/traceroute accept optional `src_address` and forward it as
  `src-address=…` to the router.
"""
from __future__ import annotations
from librouteros.api import Api
from librouteros.protocol import compose_word
from tests.test_mikrotik_signature import FakeProtocol, _encode
from portal.integrations_v2 import MikrotikClient


def _client_with(proto):
    api = Api(proto)
    c = MikrotikClient({"credentials": {"host": "x", "username": "u", "password": "p"}})
    c._connect = lambda: api  # type: ignore
    return c


def test_ping_forwards_src_address():
    fake = FakeProtocol(replies=[[("!re", {"host": "8.8.8.8", "time": "12ms"})]])
    c = _client_with(fake)
    out = c.looking_glass(tool="ping", target="8.8.8.8", src_address="10.87.10.45")
    assert out["ok"] is True
    assert fake.sent[0][0] == "/ping"
    assert "=address=8.8.8.8" in fake.sent[0][1]
    assert "=src-address=10.87.10.45" in fake.sent[0][1]
    assert out["src_address"] == "10.87.10.45"


def test_traceroute_forwards_src_address():
    fake = FakeProtocol()
    c = _client_with(fake)
    c.looking_glass(tool="traceroute", target="1.1.1.1", src_address="10.0.0.9")
    assert fake.sent[0][0] == "/tool/traceroute"
    assert "=src-address=10.0.0.9" in fake.sent[0][1]


def test_ping_no_src_address_omits_param():
    fake = FakeProtocol()
    c = _client_with(fake)
    c.looking_glass(tool="ping", target="8.8.8.8")
    # No src-address word should be present
    assert not any(w.startswith("=src-address=") for w in fake.sent[0][1])


class BgpProto(FakeProtocol):
    """Emulates a router that answers longest-prefix-match queries.

    For each `?dst-address=x.x.x.x/LEN` query, returns a hit only when the
    prefix matches an entry in `.rib`.
    """

    def __init__(self, rib):
        super().__init__()
        self.rib = rib  # dict: "10.0.0.0/8" -> {row dict}

    def writeSentence(self, cmd, *words):
        self.sent.append((cmd, tuple(words)))
        # Extract the dst-address query — query words look like
        # `?dst-address=103.133.20.0/24` (only ONE `=`, unlike attribute
        # words which start with `=` and have two).
        candidate = None
        for w in words:
            if w.startswith("?dst-address="):
                candidate = w.split("=", 1)[1]
                break
        hit = self.rib.get(candidate)
        replies = []
        if hit:
            replies.append(("!re", _encode(hit)))
        replies.append(("!done", ()))
        self._pending = replies


def test_bgp_route_lookup_finds_covering_prefix():
    """Given IP 103.133.20.5 and RIB {103.133.20.0/24: {...}}, the /24 must
    be returned. This is the exact user-reported failure."""
    rib = {
        "103.133.20.0/24": {"dst-address": "103.133.20.0/24",
                            "gateway": "10.87.10.1", "bgp": "yes"},
    }
    proto = BgpProto(rib)
    c = _client_with(proto)
    out = c.looking_glass(tool="bgp_route", target="103.133.20.5")
    assert out["ok"] is True, out
    assert len(out["rows"]) == 1
    assert out["rows"][0]["dst-address"] == "103.133.20.0/24"
    assert out["match_prefix"] == "103.133.20.0/24"
    # Ensure the scan actually walked down (issued multiple queries)
    dst_queries = [w for cmd, ws in proto.sent for w in ws if w.startswith("?dst-address=")]
    assert "?dst-address=103.133.20.5/32" in dst_queries
    assert "?dst-address=103.133.20.0/24" in dst_queries


def test_bgp_route_lookup_prefix_input():
    """If the caller supplies a prefix like 103.133.20.0/24, exact match
    must succeed on the first query — no wasteful walk-down."""
    rib = {"103.133.20.0/24": {"dst-address": "103.133.20.0/24"}}
    proto = BgpProto(rib)
    c = _client_with(proto)
    out = c.looking_glass(tool="bgp_route", target="103.133.20.0/24")
    assert out["ok"] is True
    assert out["match_prefix"] == "103.133.20.0/24"
    # First query already hit
    first = proto.sent[0][1]
    assert "?dst-address=103.133.20.0/24" in first


def test_bgp_route_lookup_returns_empty_for_unmatched():
    """Blackhole scenario — no route covers the IP → rows must be empty
    (not startswith-false-positive on unrelated /32s)."""
    proto = BgpProto(rib={})
    c = _client_with(proto)
    out = c.looking_glass(tool="bgp_route", target="192.0.2.5")
    assert out["ok"] is True
    assert out["rows"] == []
    assert out["match_prefix"] is None


def test_bgp_route_lookup_invalid_input():
    proto = BgpProto(rib={})
    c = _client_with(proto)
    out = c.looking_glass(tool="bgp_route", target="not-an-ip")
    assert out["ok"] is False
    assert "Invalid" in out["error"]
    # No queries should have been issued
    assert proto.sent == []
