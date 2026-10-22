"""Chain-attachment contract for BGP RTBH announcements.

Creating a `/routing/filter` rule in the `rtbh-out` chain drops exactly nothing
unless that chain is wired into the BGP peer's output filter. These tests pin
the fail-closed behaviour: `rtbh_announce` must refuse to report success when
the chain is not provably in effect on the matching upstream peer.
"""
import pytest

from portal.integrations_v2 import MikrotikClient


class FakeApi:
    """Minimal librouteros stand-in.

    ``paths`` maps a tuple path -> list of rows. Calling the api object with a
    command path records the call and applies ``set`` mutations to the rows.
    """

    def __init__(self, paths, fail_set=False):
        self.paths = paths
        self.calls = []
        self.closed = False
        self.fail_set = fail_set

    def __call__(self, cmd, **params):
        self.calls.append((cmd, params))
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
    # Already attached -> no mutation of the peer.
    assert [c for c in api.calls if c[0].endswith("/set")] == []


def test_announce_attaches_chain_when_peer_has_no_output_filter():
    peers = [{".id": "*1", "name": "transit-a", "remote-address": "203.0.113.1",
              "output.filter-chain": ""}]
    api = _api(peers)
    res = _client(api).rtbh_announce("157.20.32.44/32", "65535:666", "c",
                                     upstream_name="transit-a")
    assert res["ok"] is True
    sets = [c for c in api.calls if c[0].endswith("/set")]
    assert len(sets) == 1
    assert sets[0][1]["output.filter-chain"] == "rtbh-out"
    assert peers[0]["output.filter-chain"] == "rtbh-out"


def test_announce_fails_closed_when_no_peer_matches_upstream():
    peers = [{".id": "*1", "name": "transit-b", "remote-address": "203.0.113.9",
              "output.filter-chain": ""}]
    res = _client(_api(peers)).rtbh_announce("157.20.32.44/32", "65535:666", "c",
                                             upstream_name="transit-a")
    assert res["ok"] is False
    assert "transit-a" in res["error"]


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


def test_announce_fails_closed_when_attach_is_denied():
    peers = [{".id": "*1", "name": "transit-a", "remote-address": "203.0.113.1",
              "output.filter-chain": ""}]
    res = _client(_api(peers, fail_set=True)).rtbh_announce(
        "157.20.32.44/32", "65535:666", "c", upstream_name="transit-a")
    assert res["ok"] is False
    assert "could not attach chain" in res["error"]
