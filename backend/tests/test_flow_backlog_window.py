"""Reproduce and verify the 2026-11-12 false-DDoS backlog bug.

The incident: `packets=4,230,710` over `window_s=4.136` produced pps=1,022,898
against a threshold of 300,000, opening two critical incidents on a customer IP
that was not under attack. The raw flow records show `packets` max = 240 and a
median of 1, so the packet total was real but the *span* it was divided by was
fabricated by a burst flush of collector timestamps.

These tests pin the corrected behaviour: the poll interval is the span, a burst
can only widen it, and a zero span is reported as non-authoritative instead of
being turned into a rate.
"""
import json
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, "/opt/intercloud-portal/backend")

from portal.integrations_v2 import GoFlow2Client  # noqa: E402


def _write_records(path, records):
    with open(path, "a", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec) + "\n")


def _rec(src, dst, packets, bytes_, ts_ns, proto="TCP"):
    return {
        "type": "NETFLOW_V9",
        "src_addr": src,
        "dst_addr": dst,
        "packets": packets,
        "bytes": bytes_,
        "proto": proto,
        "src_port": 443,
        "dst_port": 50000,
        "tcp_flags": 16,
        "sampling_rate": 0,
        "time_received_ns": ts_ns,
        "time_flow_start_ns": ts_ns,
        "time_flow_end_ns": ts_ns,
        "in_if": 1,
        "out_if": 2,
    }


def test_cold_poll_is_not_authoritative():
    """The first poll has no previous timestamp, so no rate can be derived."""
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "flows.json")
        _write_records(path, [_rec("1.1.1.1", "157.20.32.10", 50, 5000, 1_000_000_000)])
        client = GoFlow2Client(path)
        result = client.poll()
        assert result["ok"], result
        assert result["authoritative"] is False, "cold poll must not claim a rate"
        assert result["batch_duration_s"] == 0.0
        assert result["batch_pps"] == 0.0
        assert all(row["batch_authoritative"] is False for row in result["rows"])


def test_burst_flush_does_not_inflate_rate():
    """A burst of records sharing a tight stamp spread must not divide by 4s.

    This is the production failure: 200k records flushed at once, all stamped
    within seconds, divided by that spread. After the fix the poll interval is
    the span, so the rate reflects the real elapsed time.
    """
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "flows.json")
        client = GoFlow2Client(path)

        # Baseline poll establishes _last_poll_mono.
        _write_records(path, [_rec("1.1.1.1", "157.20.32.10", 10, 1000, 1_000_000_000)])
        first = client.poll()
        assert first["authoritative"] is False

        time.sleep(0.2)

        # Now a burst: 500 records stamped within 4 seconds of each other,
        # 1000 packets each => 500,000 packets total.
        base_ns = 2_000_000_000
        burst = [
            _rec("9.9.9.9", "157.20.32.10", 1000, 1_000_000, base_ns + i * 8_000_000)
            for i in range(500)
        ]
        _write_records(path, burst)
        result = client.poll()

        assert result["ok"], result
        assert result["authoritative"] is True
        total_packets = 500 * 1000
        assert result["batch_duration_s"] > 0.2, (
            "span must be at least the measured poll interval, got %s" % result["batch_duration_s"]
        )
        # The record stamps span 4s, which exceeds the 0.2s wait, so the span
        # widens to ~4s. 500k/4s = 125k pps, NOT 500k/0.2s = 2.5M pps.
        assert result["batch_pps"] < 500_000, (
            "burst flush inflated the rate to %s pps" % result["batch_pps"]
        )
        # Cross-check: batch_pps must equal total/duration.
        expected = total_packets / result["batch_duration_s"]
        assert abs(result["batch_pps"] - expected) < 1.0, (
            "batch_pps %s != total/span %s" % (result["batch_pps"], expected)
        )


def test_records_span_wider_than_interval_widens_the_window():
    """A drained backlog covers more traffic than the wait, so trust the wider span."""
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "flows.json")
        client = GoFlow2Client(path)
        _write_records(path, [_rec("1.1.1.1", "157.20.32.10", 10, 1000, 1_000_000_000)])
        client.poll()
        time.sleep(0.05)

        # Records stamped 60 seconds apart: the backlog spans a minute.
        base_ns = 3_000_000_000
        _write_records(path, [
            _rec("2.2.2.2", "157.20.32.10", 100, 10000, base_ns),
            _rec("2.2.2.2", "157.20.32.10", 100, 10000, base_ns + 60_000_000_000),
        ])
        result = client.poll()
        assert result["batch_duration_s"] >= 59.0, (
            "backlog span must win over a short poll wait, got %s" % result["batch_duration_s"]
        )


def test_packets_per_record_matches_raw_flow_reality():
    """Guards the assumption behind the fix: records carry small counters.

    The production file had max 240 packets and median 1 across 200 records.
    A division that yields hundreds of thousands of pps from such records is
    arithmetically impossible and must be attributed to the span, not the data.
    """
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "flows.json")
        client = GoFlow2Client(path)
        _write_records(path, [_rec("1.1.1.1", "157.20.32.10", 10, 1000, 1_000_000_000)])
        client.poll()
        time.sleep(0.3)

        records = [_rec("3.3.3.3", "157.20.32.10", 240, 216111, 4_000_000_000 + i)
                   for i in range(100)]
        _write_records(path, records)
        result = client.poll()
        assert result["authoritative"] is True
        total = 100 * 240
        # The poll interval (~0.3s) exceeds the 100ns record stamp spread, so
        # the interval wins and every packet is attributed to it.
        expected = round(total / result["batch_duration_s"], 2)
        # tolerance: batch_duration_s is returned rounded to 3dp while
        # batch_pps uses the unrounded value, so a sub-0.1% gap is expected.
        assert abs(result["batch_pps"] - expected) <= expected * 0.01, (
            "batch_pps %s != %s" % (result["batch_pps"], expected))
        # And the resulting rate must be a plausible small number, not the
        # hundreds-of-thousands pps fabrication that opened the false incident.
        assert result["batch_pps"] < 500_000, (
            "240-packet records cannot yield %s pps" % result["batch_pps"])


def test_no_division_by_zero_when_single_record():
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "flows.json")
        client = GoFlow2Client(path)
        _write_records(path, [_rec("1.1.1.1", "157.20.32.10", 5, 500, 1_000_000_000)])
        result = client.poll()
        assert result["ok"]
        assert result["batch_pps"] == 0.0
        # A single-record cold poll still yields the row for topology purposes.
        assert len(result["rows"]) == 1


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if not name.startswith("test_") or not callable(fn):
            continue
        try:
            fn()
            print("PASS %s" % name)
        except AssertionError as exc:
            failures += 1
            print("FAIL %s: %s" % (name, exc))
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print("ERROR %s: %r" % (name, exc))
    print()
    print("failures:", failures)
    sys.exit(1 if failures else 0)
