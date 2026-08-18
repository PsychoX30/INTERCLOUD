"""Tests for GoFlow2Client — parses JSON flow lines from goflow2 output.

goflow2 writes JSON lines to a file (or stdout). Each line is a flow record
with fields like: src_addr, dst_addr, proto, src_port, dst_port, bytes, packets.

The backend polls this file every ~30s, parses new lines, and returns
normalized flow dicts matching the same shape as MikrotikClient.torch() output
so the detection sweep can consume both sources uniformly.

No live goflow2 process, no network — tests use temp files with canned JSON.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest

from portal.integrations_v2 import GoFlow2Client


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def flow_file(tmp_path):
    """Create a temp file with goflow2 JSON lines."""
    f = tmp_path / "flows.json"
    f.write_text("")
    return f


@pytest.fixture
def client(flow_file):
    return GoFlow2Client(flow_path=str(flow_file))


# ---------------------------------------------------------------------------
# Sample goflow2 JSON records (based on actual goflow2 output format)
# ---------------------------------------------------------------------------
GOFLOW_UDP_FLOOD = {
    "type": "NETFLOW_V9",
    "time_received_ns": 1681583295157626000,
    "sequence_num": 2999,
    "sampling_rate": 1,
    "sampler_address": "157.20.32.254",
    "time_flow_start_ns": 1681583295000000000,
    "time_flow_end_ns": 1681583295100000000,
    "bytes": 1500000,
    "packets": 10000,
    "src_addr": "8.8.8.8",
    "dst_addr": "157.20.32.50",
    "etype": "IPv4",
    "proto": "UDP",
    "src_port": 12345,
    "dst_port": 53,
}

GOFLOW_TCP_SYN = {
    "type": "NETFLOW_V9",
    "time_received_ns": 1681583295157626000,
    "sampling_rate": 1,
    "sampler_address": "157.20.32.254",
    "bytes": 800,
    "packets": 100,
    "src_addr": "203.0.113.9",
    "dst_addr": "157.20.32.77",
    "etype": "IPv4",
    "proto": "TCP",
    "src_port": 9999,
    "dst_port": 443,
}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

# 1. Parse single flow from JSON lines
def test_parse_single_flow(client, flow_file):
    flow_file.write_text(json.dumps(GOFLOW_UDP_FLOOD) + "\n")
    result = client.poll()
    assert result["ok"] is True
    assert result["flow_count"] == 1
    flow = result["rows"][0]
    assert flow["src_address"] == "8.8.8.8"
    assert flow["dst_address"] == "157.20.32.50"
    assert flow["protocol"] == "udp"
    assert flow["src_port"] == "12345"
    assert flow["dst_port"] == "53"
    assert flow["rx_packets"] == 10000
    assert flow["tx_packets"] == 0


# 2. Parse multiple flows
def test_parse_multiple_flows(client, flow_file):
    flow_file.write_text(
        json.dumps(GOFLOW_UDP_FLOOD) + "\n" +
        json.dumps(GOFLOW_TCP_SYN) + "\n"
    )
    result = client.poll()
    assert result["ok"] is True
    assert result["flow_count"] == 2


# 3. Missing file → ok=False, not crash
def test_missing_file():
    c = GoFlow2Client(flow_path="/nonexistent/path/flows.json")
    result = c.poll()
    assert result["ok"] is False
    assert "error" in result


# 4. Empty file → ok=True, zero flows
def test_empty_file(client, flow_file):
    result = client.poll()
    assert result["ok"] is True
    assert result["flow_count"] == 0
    assert result["rows"] == []


# 5. Malformed JSON line → skipped, other lines still parsed
def test_malformed_line_skipped(client, flow_file):
    flow_file.write_text(
        "not valid json\n" +
        json.dumps(GOFLOW_UDP_FLOOD) + "\n"
    )
    result = client.poll()
    assert result["ok"] is True
    assert result["flow_count"] == 1


# 6. Protocol normalized to lowercase
def test_protocol_lowercased(client, flow_file):
    flow_file.write_text(json.dumps(GOFLOW_TCP_SYN) + "\n")
    result = client.poll()
    assert result["rows"][0]["protocol"] == "tcp"


# 7. Bytes converted to rate (bps) and packets to pps
def test_bytes_and_packets_converted(client, flow_file):
    flow = dict(GOFLOW_UDP_FLOOD)
    # 1.5MB over 1 second = 1.5 Mbps = 1500000 bytes/s
    flow["time_flow_start_ns"] = 1681583295000000000
    flow["time_flow_end_ns"] = 1681583295100000000  # 100ms = 0.1s
    flow_file.write_text(json.dumps(flow) + "\n")
    result = client.poll()
    f = result["rows"][0]
    # packets per second = 10000 / 0.1 = 100000 pps
    assert f["rx_packets"] > 0
    assert f["rx_rate"] > 0


# 8. Sampler address preserved as device identifier
def test_sampler_address_preserved(client, flow_file):
    flow_file.write_text(json.dumps(GOFLOW_UDP_FLOOD) + "\n")
    result = client.poll()
    assert result["rows"][0].get("sampler_address") == "157.20.32.254"


# 9. Incremental read — only new lines since last poll
def test_incremental_read(client, flow_file):
    flow_file.write_text(json.dumps(GOFLOW_UDP_FLOOD) + "\n")
    r1 = client.poll()
    assert r1["flow_count"] == 1
    # Second poll without new data → zero new flows
    r2 = client.poll()
    assert r2["flow_count"] == 0
    # Append new flow
    with open(flow_file, "a") as f:
        f.write(json.dumps(GOFLOW_TCP_SYN) + "\n")
    r3 = client.poll()
    assert r3["flow_count"] == 1


# 10. Sampling rate applied to packets/bytes
def test_sampling_rate_applied(client, flow_file):
    flow = dict(GOFLOW_UDP_FLOOD)
    flow["sampling_rate"] = 100
    flow_file.write_text(json.dumps(flow) + "\n")
    result = client.poll()
    f = result["rows"][0]
    # Actual packets = 10000 * 100 = 1000000
    assert f["rx_packets"] == 1000000


def test_zero_duration_records_use_batch_span_for_pps(client, flow_file):
    """Instantaneous RouterOS records are counts, not one-second rates."""
    first = dict(GOFLOW_TCP_SYN)
    first.update({
        "packets": 100,
        "time_received_ns": 1_000_000_000,
        "time_flow_start_ns": 1_000_000_000,
        "time_flow_end_ns": 1_000_000_000,
    })
    second = dict(first)
    second["time_received_ns"] = 11_000_000_000
    second["time_flow_start_ns"] = 11_000_000_000
    second["time_flow_end_ns"] = 11_000_000_000
    flow_file.write_text(json.dumps(first) + "\n" + json.dumps(second) + "\n")

    rows = client.poll()["rows"]

    # 100 packets per record over the observed 10-second batch = 10 pps,
    # not 100 pps per record as the old one-second fallback reported.
    assert [row["pps"] for row in rows] == [10, 10]
    assert sum(row["pps"] for row in rows) == 20
    assert sum(row["rx_packets"] for row in rows) == 200


def test_valid_flow_duration_takes_precedence_over_batch_span(client, flow_file):
    flow = dict(GOFLOW_UDP_FLOOD)
    flow.update({
        "packets": 100,
        "time_flow_start_ns": 1_000_000_000,
        "time_flow_end_ns": 3_000_000_000,
        "time_received_ns": 50_000_000_000,
    })
    flow_file.write_text(json.dumps(flow) + "\n")

    row = client.poll()["rows"][0]

    assert row["pps"] == 50
