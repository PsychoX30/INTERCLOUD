"""Pure unit tests for portal.security.compute_threat_score.

Deterministic, no DB, no network. Each dimension must independently be able
to raise the level, and the score must stay bounded in 0..100.
"""
import pytest

from portal.security import compute_threat_score


def score(**kw):
    base = dict(failures=0, distinct_ips=1, distinct_emails=1, threshold=10)
    base.update(kw)
    return compute_threat_score(**base)


def test_no_failures_is_low():
    r = score(failures=0)
    assert r["score"] == 0
    assert r["level"] == "low"


def test_normal_noise_is_low():
    r = score(failures=2, threshold=10)
    assert r["level"] == "low"
    assert 0 < r["score"] < 40


def test_volume_burst_is_high():
    """Crossing the block threshold on its own is a HIGH signal."""
    r = score(failures=50, threshold=10)
    assert r["level"] == "high"
    assert r["score"] == 100


def test_enumeration_many_emails_one_ip_is_high():
    """Password spraying: one source IP, many targeted accounts."""
    r = score(failures=8, distinct_emails=6, distinct_ips=1, threshold=10)
    assert r["level"] == "high"
    assert r["enumeration"] >= 0.67


def test_distributed_many_ips_one_email_is_high():
    """Distributed brute force: one account, many source IPs."""
    r = score(failures=8, distinct_ips=6, distinct_emails=1, threshold=10)
    assert r["level"] == "high"
    assert r["distribution"] >= 0.67


def test_score_is_bounded():
    r = score(failures=10000, distinct_ips=9999, distinct_emails=9999, threshold=1)
    assert 0 <= r["score"] <= 100


def test_components_present_and_floats():
    r = score(failures=5)
    for key in ("score", "level", "volume", "enumeration", "distribution"):
        assert key in r, f"missing {key}"
    assert isinstance(r["score"], int)
    assert r["level"] in ("low", "medium", "high")


def test_zero_threshold_does_not_divide_by_zero():
    r = score(failures=3, threshold=0)
    assert 0 <= r["score"] <= 100


@pytest.mark.parametrize("failures,threshold", [(0, 10), (1, 10), (10, 10), (100, 10)])
def test_monotonic_in_failures(failures, threshold):
    assert score(failures=failures, threshold=threshold)["score"] >= 0