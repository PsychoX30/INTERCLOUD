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


def test_blackhole_add_uses_positional_cmd():
    c, fake = _client_with_fake()
    out = c.blackhole_add("203.0.113.0/32")
    assert out["ok"] is True, out
    assert fake.sent[0][0] == "/ip/route/add"
    assert "=type=blackhole" in fake.sent[0][1]
    assert "=dst-address=203.0.113.0/32" in fake.sent[0][1]


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
