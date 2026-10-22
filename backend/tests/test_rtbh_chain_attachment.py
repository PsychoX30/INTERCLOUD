"""Chain-attachment contract for BGP RTBH announcements.

Creating a `/routing/filter` rule in the `rtbh-out` chain drops exactly nothing
unless that chain is wired into the BGP peer's output filter.  These tests pin
the fail-closed behaviour: `rtbh_announce` must refuse to report success unless
the chain is *already* an output filter of the matching upstream peer.

It must NEVER attach the chain itself: a RouterOS routing filter chain defaults
to reject, so attaching a chain that only matches the RTBH prefix would withdraw
every other announced prefix (a total outage).
"""
import pytest

from portal.integrations_v2 import MikrotikClient


class FakeApi:
    """Minimal librouteros stand-in.

    ``paths`` maps a tuple path -> list of rows. Calling the api object with a
    command path records the call; ``/add`` appends a row (with a synthesized
    ``.id``) to the parent menu so the read-back can find it, and ``/set``
    applies the mutation to the matching row.
    """

    def __init__(self, paths, fail_set=False):
        self.paths = paths
        self.calls = []
        self.closed = False
        self.fail_set = fail_set

    def __call__(self, cmd, **params):
        self.calls.append((cmd, params))
        if cmd.endswith("/add"):
            base = tuple(cmd.strip("/").split("/")[:-1])
            row = dict(params)
            row[".id"] = f"*{len(self.paths.get(base, [])) + 1}"
            self.paths.setdefault(base, []).append(row)
            return []
        if cmd.endswith("/set"):
            if self.fail_set:
                raise RuntimeError("permission denied")
            base = tuple(cmd.strip("/").split("/")[:-1])
            for row in self.paths.get(base, []):
                if row.get(".id") == params.get(".id"):
                    row.update({k: v for k, v in params.items() if k != ".id"})
        return []

    def path(self, *parts):
        return list(self.paths.get(tuple(parts), []))

    def close(self):
        self.closed = True


def _client(api):
    c = MikrotikClient({"host": "10.0.0.1", "username": "admin", "password": "x"})
    c._connect = lambda: api
    # The fake device models a RouterOS 7 box (the v7 add/rule path); tests
    # that need v6 pass ros_major=6 explicitly. This mirrors a device doc that
    # already stores its version, keeping the "unknown -> refuse" guard honest
    # for the real sweep while letting the chain-attachment contract be tested.
    c._ros_major = 7
    return c


FILTER_RULES = ("routing", "filter", "rule")
CONNECTION = ("routing", "bgp", "connection")


def _api(peers, fail_set=False):
    return FakeApi({FILTER_RULES: [], CONNECTION: peers}, fail_set=fail_set)


def test_announce_succeeds_when_chain_already_attached():
    peers = [{".id": "*1", "name": "transit-a", "remote-address": "203.0.113.1",
              "output.filter-chain": "rtbh-out"}]
    api = _api(peers)
    res = _client(api).rtbh_announce("157.20.32.44/32", "65535:666", "c",
                                     upstream_name="transit-a")
    assert res["ok"] is True
    assert res["attached"] is True
    assert res["peer"] == "transit-a"
    assert res["id"]           # the created rule's .id was read back
    # Already attached -> no mutation of the peer.
    assert [c for c in api.calls if c[0].endswith("/set")] == []


def test_announce_never_auto_attaches_when_peer_has_no_output_filter():
    """The old behaviour auto-attached a reject-by-default chain = outage."""
    peers = [{".id": "*1", "name": "transit-a", "remote-address": "203.0.113.1",
              "output.filter-chain": ""}]
    api = _api(peers)
    res = _client(api).rtbh_announce("157.20.32.44/32", "65535:666", "c",
                                     upstream_name="transit-a")
    assert res["ok"] is False
    assert "defaults to reject" in res["error"] or "no output filter" in res["error"]
    # The peer must be left untouched and nothing must be added to the chain.
    assert peers[0]["output.filter-chain"] == ""
    assert api.paths[FILTER_RULES] == []
    assert [c for c in api.calls if c[0].endswith("/set")] == []


def test_announce_fails_closed_when_no_peer_matches_upstream():
    peers = [{".id": "*1", "name": "transit-b", "remote-address": "203.0.113.9",
              "output.filter-chain": "rtbh-out"}]
    api = _api(peers)
    res = _client(api).rtbh_announce("157.20.32.44/32", "65535:666", "c",
                                     upstream_name="transit-a")
    assert res["ok"] is False
    assert "transit-a" in res["error"]
    # No rule should have been created (peer verified before any write).
    assert api.paths[FILTER_RULES] == []


def test_announce_rejects_substring_upstream_match():
    """'transit' must NOT match 'not-transit' (first-match-wins hazard)."""
    peers = [{".id": "*1", "name": "not-transit", "remote-address": "203.0.113.9",
              "output.filter-chain": "rtbh-out"}]
    api = _api(peers)
    res = _client(api).rtbh_announce("157.20.32.44/32", "65535:666", "c",
                                     upstream_name="transit")
    assert res["ok"] is False
    assert "transit" in res["error"]
    assert api.paths[FILTER_RULES] == []


def test_announce_rejects_ambiguous_upstream_match():
    peers = [
        {".id": "*1", "name": "transit-a", "remote-address": "203.0.113.1",
         "output.filter-chain": "rtbh-out"},
        {".id": "*2", "name": "transit-a", "remote-address": "203.0.113.2",
         "output.filter-chain": "rtbh-out"},
    ]
    api = _api(peers)
    res = _client(api).rtbh_announce("157.20.32.44/32", "65535:666", "c",
                                     upstream_name="transit-a")
    assert res["ok"] is False
    assert "2 BGP peers" in res["error"]
    assert api.paths[FILTER_RULES] == []


def test_announce_refuses_to_overwrite_existing_output_filter():
    peers = [{".id": "*1", "name": "transit-a", "remote-address": "203.0.113.1",
              "output.filter-chain": "customer-out"}]
    api = _api(peers)
    res = _client(api).rtbh_announce("157.20.32.44/32", "65535:666", "c",
                                     upstream_name="transit-a")
    assert res["ok"] is False
    assert "customer-out" in res["error"]
    # The pre-existing policy must be left untouched.
    assert peers[0]["output.filter-chain"] == "customer-out"
    assert [c for c in api.calls if c[0].endswith("/set")] == []


def test_announce_fails_closed_when_no_bgp_peers_readable():
    api = FakeApi({FILTER_RULES: [], CONNECTION: []})
    res = _client(api).rtbh_announce("157.20.32.44/32", "65535:666", "c",
                                     upstream_name="transit-a")
    assert res["ok"] is False
    assert "no BGP" in res["error"]


def test_announce_fails_closed_when_missing_upstream_name():
    peers = [{".id": "*1", "name": "transit-a", "remote-address": "203.0.113.1",
              "output.filter-chain": "rtbh-out"}]
    api = _api(peers)
    res = _client(api).rtbh_announce("157.20.32.44/32", "65535:666", "c",
                                     upstream_name="")
    assert res["ok"] is False
    assert "no upstream name" in res["error"]


def test_announce_fails_closed_when_id_cannot_be_read_back():
    """A rule whose .id cannot be read back can never be withdrawn -> fail."""
    peers = [{".id": "*1", "name": "transit-a", "remote-address": "203.0.113.1",
              "output.filter-chain": "rtbh-out"}]

    class NoReadBackApi(FakeApi):
        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)

        def __call__(self, cmd, **params):
            self.calls.append((cmd, params))
            return []          # add succeeds on the wire, but nothing is stored

    api = NoReadBackApi({FILTER_RULES: [], CONNECTION: peers})
    res = _client(api).rtbh_announce("157.20.32.44/32", "65535:666", "c",
                                     upstream_name="transit-a")
    assert res["ok"] is False
    assert "could not be read back" in res["error"]


def test_announce_uses_bgp_communities_not_bgp_out_community():
    peers = [{".id": "*1", "name": "transit-a", "remote-address": "203.0.113.1",
              "output.filter-chain": "rtbh-out"}]
    api = _api(peers)
    res = _client(api).rtbh_announce("157.20.32.44/32", "65535:666", "c",
                                     upstream_name="transit-a")
    assert res["ok"] is True
    add = [c for c in api.calls if c[0].endswith("/add")][0]
    rule = add[1]["rule"]
    assert "bgp-communities 65535:666" in rule
    assert "bgp-out-community" not in rule


def test_announce_v6_uses_discrete_properties():
    peers = [{".id": "*1", "name": "transit-a", "remote-address": "203.0.113.1",
              "output.filter-chain": "rtbh-out"}]
    api = _api(peers)
    res = _client(api).rtbh_announce("157.20.32.44/32", "65535:666", "c",
                                     upstream_name="transit-a", ros_major=6)
    assert res["ok"] is True
    add = [c for c in api.calls if c[0].endswith("/add")][0]
    assert add[0] == "/routing/filter/add"
    assert "rule" not in add[1]              # v6 has no rule= script param
    assert add[1]["set-bgp-communities"] == "65535:666"


def test_announce_refuses_when_ros_version_unknown():
    """Guessing the syntax produces commands the router rejects."""
    peers = [{".id": "*1", "name": "transit-a", "remote-address": "203.0.113.1",
              "output.filter-chain": "rtbh-out"}]
    api = _api(peers)
    c = MikrotikClient({"host": "10.0.0.1", "username": "admin", "password": "x"})
    c._connect = lambda: api
    # Leave c._ros_major as None (unknown) and do NOT pass ros_major.
    res = c.rtbh_announce("157.20.32.44/32", "65535:666", "c",
                          upstream_name="transit-a")
    assert res["ok"] is False
    assert "unknown" in res["error"]
    assert api.paths[FILTER_RULES] == []   # nothing written
