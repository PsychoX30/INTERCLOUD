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

        # This batch is the exact shape that fabricated a 1,022,898 pps sample:
        # 100 records of 240 packets each, all stamped within 100 ns of one
        # another. Neither clock provides a usable span — the 100 ns stamp
        # spread is compression artefact, and the 0.3 s wait is below the
        # authoritative floor — so the poll must be flagged, not trusted.
        assert result["authoritative"] is False, result
        assert result["sub_span_floor_applied"] > 0

        # The clamp still bounds the rate: 24,000 packets over the 1 s floor.
        assert result["batch_duration_s"] >= GoFlow2Client.MIN_AUTHORITATIVE_SPAN_S
        assert result["batch_pps"] <= 24_000, (
            "240-packet records cannot yield %s pps" % result["batch_pps"])
        # And emphatically not the hundreds-of-thousands fabrication that
        # opened the false incident.
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


def test_peek_does_not_consume_the_poll_cursor():
    """The display path must not steal the detection sweep's records.

    Sharing one cursor made whichever consumer polled second receive zero
    rows: the Sankey view silently fell back to Torch, and the sweep
    intermittently computed a rate over a drained backlog.
    """
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "flows.json")
        client = GoFlow2Client(path)
        _write_records(path, [_rec("1.1.1.1", "157.20.32.10", 10, 1000, 1_000_000_000)])

        first = client.peek()
        assert first["ok"], first
        assert len(first["rows"]) == 1

        # Peeking again returns the same record: the cursor did not move.
        second = client.peek()
        assert len(second["rows"]) == 1

        # And poll() still sees the record, proving peek left the offset alone.
        polled = client.poll()
        assert polled["ok"], polled
        assert len(polled["rows"]) == 1

        # A second poll has nothing left: the sweep consumed it.
        empty = client.poll()
        assert empty["ok"]
        assert len(empty.get("rows") or []) == 0


def test_peek_never_reports_a_sub_second_span():
    """A dense tail can span milliseconds; the displayed rate must not.

    A 0.8 s span turned a routine burst into a 206,787 pps reading, which is
    close enough to the 300,000 pps alert threshold to be misread.
    """
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "flows.json")
        client = GoFlow2Client(path)
        base_ns = 5_000_000_000
        _write_records(path, [
            _rec("1.1.1.1", "157.20.32.10", 100, 100_000, base_ns + i * 1_000_000)
            for i in range(50)
        ])
        result = client.peek()
        assert result["ok"], result
        assert result["batch_duration_s"] >= 2.0, (
            "span collapsed to %s s" % result["batch_duration_s"])
        assert result["min_span_applied"] is True
        # 5000 packets over >=2s cannot be 200k pps.
        assert result["batch_pps"] < 10_000, (
            "sub-second span produced %s pps" % result["batch_pps"])


def test_poll_below_min_span_is_not_authoritative():
    """A nearly-drained cursor must not manufacture a rate.

    Two polls a few milliseconds apart (the scheduler woke, read 8 new records,
    returned) divide a handful of packets by a near-zero interval. That is the
    same error class as the fabricated 1,022,898 pps sample: a tiny numerator
    over a tiny span. Such a poll is labelled non-authoritative so no threshold
    decision can trust it, while its rows still carry topology.
    """
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "flows.json")
        client = GoFlow2Client(path)
        base_ns = 7_000_000_000
        _write_records(path, [_rec("1.1.1.1", "157.20.32.10", 4, 400, base_ns)])

        # Warm the interval clock so the second poll measures a real gap.
        client.poll()

        # Append a burst and poll immediately: the measured interval is tiny.
        _write_records(path, [
            _rec("2.2.2.2", "157.20.32.11", 8, 800, base_ns + 1_000_000)
            for _ in range(3)
        ])
        second = client.poll()

        assert second["ok"], second
        assert second["flow_count"] == 3
        # The floor clamped the span, so the payload is flagged, not trusted.
        assert second["batch_duration_s"] >= GoFlow2Client.MIN_AUTHORITATIVE_SPAN_S
        assert second["authoritative"] is False, (
            "a sub-span poll claimed authority: %s" % second)
        assert all(r["batch_authoritative"] is False for r in second["rows"])
        # 24 packets over a clamped >=1 s span can never look like a flood.
        assert second["batch_pps"] <= 240, (
            "sub-span poll produced %s pps" % second["batch_pps"])


def test_poll_over_min_span_stays_authoritative():
    """The floor must not silently demote normal production polls."""
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "flows.json")
        client = GoFlow2Client(path)
        base_ns = 9_000_000_000
        _write_records(path, [_rec("1.1.1.1", "157.20.32.10", 10, 1000, base_ns)])
        client.poll()

        # Records spread over 5 s of receive stamps widen the span past the
        # floor (backlog guard), which is the normal healthy path.
        _write_records(path, [
            _rec("2.2.2.2", "157.20.32.11", 10, 1000, base_ns + i * 1_000_000_000)
            for i in range(5)
        ])
        second = client.poll()

        assert second["ok"], second
        assert second["batch_duration_s"] >= 4.0, second["batch_duration_s"]
        assert second["authoritative"] is True, second
        assert second["sub_span_floor_applied"] == 0.0


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
