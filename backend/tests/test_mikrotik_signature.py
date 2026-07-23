"""Verify MikrotikClient calls librouteros.Api with the correct signature.

The previous bug was calling `api(cmd="/ping", ...)` — but librouteros 4.x
declares `Api.__call__(self, cmd: str, /, **kwargs)` where `cmd` is
POSITIONAL-ONLY, so keyword form raises:

    TypeError: Api.__call__() missing 1 required positional argument: 'cmd'

This test exercises every write/query method against a fake librouteros
`ApiProtocol` so any regression to keyword `cmd=` will crash locally.
"""
from __future__ import annotations
import types
import pytest
from librouteros.api import Api
from librouteros.protocol import compose_word


def _encode(d):
    """dict → tuple of raw =key=value words (what the wire protocol sends)."""
    return tuple(compose_word(k, v) for k, v in d.items())


class FakeProtocol:
    """Records sentences instead of talking to a router. Replays canned replies.

    `replies` is a list of per-call reply lists. Each entry is a list of
    (reply_word, dict-of-attrs). We encode attrs back into wire-format words
    because `Api.readSentence` calls `parse_word` on each word.
    """

    def __init__(self, replies=None):
        self.sent = []
        self._replies = list(replies or [])

    def writeSentence(self, cmd, *words):
        self.sent.append((cmd, tuple(words)))
        rep = self._replies.pop(0) if self._replies else [("!done", {})]
        if not rep or rep[-1][0] != "!done":
            rep = list(rep) + [("!done", {})]
        self._pending = [(rw, _encode(attrs)) for rw, attrs in rep]

    def readSentence(self):
        return self._pending.pop(0)

    def close(self):
        pass


def _client_with_fake(replies=None):
    from portal.integrations_v2 import MikrotikClient
    fake = FakeProtocol(replies=replies)
    api = Api(fake)
    c = MikrotikClient({"credentials": {"host": "1.1.1.1", "username": "u", "password": "p"}})
    # Monkey-patch _connect to return our in-memory Api
    c._connect = lambda: api  # type: ignore
    return c, fake


def test_looking_glass_ping_uses_positional_cmd():
    c, fake = _client_with_fake(replies=[[
        ("!re", {"host": "8.8.8.8", "time": "12ms"}),
        ("!done", {}),
    ]])
    out = c.looking_glass(tool="ping", target="8.8.8.8")
    assert out["ok"] is True, out
    assert fake.sent[0][0] == "/ping"
    assert "=address=8.8.8.8" in fake.sent[0][1]
    assert "=count=5" in fake.sent[0][1]


def test_looking_glass_traceroute_uses_positional_cmd():
    c, fake = _client_with_fake()
    out = c.looking_glass(tool="traceroute", target="1.1.1.1")
    assert out["ok"] is True
    assert fake.sent[0][0] == "/tool/traceroute"


def test_blackhole_add_uses_v7_boolean_first():
    """RouterOS 7 uses `blackhole=yes` flag, not `type=blackhole`."""
    c, fake = _client_with_fake()
    out = c.blackhole_add("203.0.113.0/32")
    assert out["ok"] is True, out
    assert fake.sent[0][0] == "/ip/route/add"
    assert "=blackhole=yes" in fake.sent[0][1]
    assert "=dst-address=203.0.113.0/32" in fake.sent[0][1]
    # Only one command should have been sent — v7 succeeded, no fallback.
    assert len(fake.sent) == 1


def test_blackhole_add_falls_back_to_v6_type():
    """If RouterOS 6 rejects `blackhole` param, fall back to `type=blackhole`."""
    # First writeSentence queues its reply; then Api reads. We need writeSentence
    # for the first (v7) call to succeed but readResponse to raise TrapError.
    from librouteros.exceptions import TrapError

    class RaisingProto(FakeProtocol):
        def __init__(self):
            super().__init__(replies=None)
            self._call = 0

        def writeSentence(self, cmd, *words):
            self._call += 1
            self.sent.append((cmd, tuple(words)))
            if self._call == 1:
                # First call → simulate v7 rejection via a !trap sentence
                self._pending = [
                    ("!trap", _encode({"message": "unknown parameter: blackhole"})),
                    ("!done", ()),
                ]
            else:
                self._pending = [("!done", ())]

        def readSentence(self):
            return self._pending.pop(0)

    from portal.integrations_v2 import MikrotikClient
    proto = RaisingProto()
    api = Api(proto)
    c = MikrotikClient({"credentials": {"host": "x", "username": "u", "password": "p"}})
    c._connect = lambda: api  # type: ignore
    out = c.blackhole_add("192.0.2.0/32")
    assert out["ok"] is True, out
    assert len(proto.sent) == 2
    # Second (fallback) call must include the legacy `type=blackhole`.
    assert "=type=blackhole" in proto.sent[1][1]


def test_blackhole_list_uses_query_filter_and_prefix_narrowing():
    """blackhole_list must issue a rawCmd query — not a full /ip/route dump —
    and honour the optional prefix_filter."""
    from portal.integrations_v2 import MikrotikClient

    routes = [
        {"dst-address": "157.20.32.5/32", "blackhole": "",    "distance": 1, ".id": "*1"},
        {"dst-address": "157.20.33.5/32", "blackhole": "yes", "distance": 1, ".id": "*2"},
        {"dst-address": "10.0.0.1/32",    "blackhole": "",    "distance": 1, ".id": "*3"},
    ]

    class QueryProto(FakeProtocol):
        def writeSentence(self, cmd, *words):
            self.sent.append((cmd, tuple(words)))
            # Only reply when the first (v7) query is issued.
            self._pending = [(("!re"), _encode(r)) for r in routes] + [("!done", ())]

    proto = QueryProto()
    api = Api(proto)
    c = MikrotikClient({"credentials": {"host": "x", "username": "u", "password": "p"}})
    c._connect = lambda: api  # type: ignore

    # Without filter: all 3 rows
    rows = c.blackhole_list()
    assert proto.sent[0][0] == "/ip/route/print"
    assert "?blackhole=yes" in proto.sent[0][1]
    assert len(rows) == 3

    # With CIDR filter: only the /32 inside 157.20.32.0/24
    rows2 = c.blackhole_list(prefix_filter="157.20.32.0/24")
    assert len(rows2) == 1
    assert rows2[0]["dst-address"] == "157.20.32.5/32"


def test_blackhole_remove_uses_positional_cmd():
    c, fake = _client_with_fake()
    out = c.blackhole_remove("*1")
    assert out["ok"] is True
    assert fake.sent[0][0] == "/ip/route/remove"
    assert "=.id=*1" in fake.sent[0][1]


def test_backup_create_uses_positional_cmd():
    c, fake = _client_with_fake()
    out = c.backup_create(name="unit-test")
    assert out["ok"] is True, out
    assert fake.sent[0][0] == "/system/backup/save"
    assert "=name=unit-test" in fake.sent[0][1]


def test_backup_delete_uses_positional_cmd():
    c, fake = _client_with_fake()
    out = c.backup_delete("unit-test.backup")
    assert out["ok"] is True
    assert fake.sent[0][0] == "/file/remove"


def test_reboot_uses_positional_cmd():
    c, fake = _client_with_fake()
    out = c.reboot()
    assert out["ok"] is True
    assert fake.sent[0][0] == "/system/reboot"


def test_traffic_monitor_uses_positional_cmd_and_returns_rx_tx():
    sample = {
        "name": "ether1",
        "rx-bits-per-second": "1024000",
        "tx-bits-per-second": "2048000",
    }
    c, fake = _client_with_fake(replies=[[
        ("!re", sample),
        ("!done", {}),
    ]])
    out = c.traffic_monitor("ether1")
    assert fake.sent[0][0] == "/interface/monitor-traffic"
    assert "=interface=ether1" in fake.sent[0][1]
    assert "=once=" in fake.sent[0][1]   # flag arg
    # librouteros parse_word casts numeric strings to int
    assert out["rx-bits-per-second"] == 1024000
    assert out["tx-bits-per-second"] == 2048000


def test_torch_uses_positional_cmd():
    c, fake = _client_with_fake(replies=[[
        ("!re", {"src-address": "10.0.0.1", "dst-address": "8.8.8.8",
                 "protocol": "tcp", "tx": "100", "rx": "200"}),
        ("!done", {}),
    ]])
    out = c.torch(interface="ether1", duration=2)
    assert out["ok"] is True
    assert fake.sent[0][0] == "/tool/torch"
    assert out["rows"][0]["src_address"] == "10.0.0.1"
    assert out["rows"][0]["tx_rate"] == 100
