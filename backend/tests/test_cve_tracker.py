"""Regression tests for the CVE tracker parsing / filtering layer.

These are pure-logic tests: no Mongo, no network. They guard the contracts the
public page depends on - severity bucketing, CVSS source preference, the NEW
badge window, and the admin filter builder.
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from portal import cve_tracker as ct  # noqa: E402


def _entry(**over):
    base = {
        "cve": {
            "id": "CVE-2025-1234",
            "sourceIdentifier": "nvd@nist.gov",
            "published": "2025-03-01T10:00:00.000",
            "lastModified": "2025-03-05T08:30:00.000",
            "vulnStatus": "Analyzed",
            "descriptions": [{"lang": "en", "value": "Buffer overflow in Foo RCE."}],
            "metrics": {
                "cvssMetricV31": [{
                    "source": "nvd@nist.gov",
                    "type": "Primary",
                    "cvssData": {
                        "version": "3.1", "baseScore": 9.8,
                        "baseSeverity": "CRITICAL",
                        "vectorString": "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H",
                        "attackVector": "NETWORK",
                    },
                }],
            },
            "weaknesses": [{"description": [{"lang": "en", "value": "CWE-120"}]}],
            "configurations": [{"nodes": [{"cpeMatch": [
                {"criteria": "cpe:2.3:a:acme:foo:1.0:*:*:*:*:*:*:*"}]}]}],
            "references": [{"url": "https://acme.example/advisory",
                            "source": "acme", "tags": ["Vendor Advisory"]}],
        }
    }
    for path, value in over.items():
        node = base["cve"]
        keys = path.split(".")
        for k in keys[:-1]:
            node = node[k]
        node[keys[-1]] = value
    return base


def test_transforms_a_full_nvd_entry():
    doc = ct.transform_nvd_vulnerability(_entry())
    assert doc is not None
    assert doc["_id"] == "CVE-2025-1234"
    assert doc["cve_id"] == "CVE-2025-1234"
    assert doc["severity"] == "critical"
    assert doc["cvss_score"] == 9.8
    assert doc["cvss_version"] == "3.1"
    assert doc["cwes"] == ["CWE-120"]
    assert doc["products"] == ["acme:foo"]
    assert doc["references"][0]["host"] == "acme.example"
    assert doc["published"] == datetime(2025, 3, 1, 10, 0, tzinfo=timezone.utc)


def test_rejects_non_cve_ids():
    assert ct.transform_nvd_vulnerability({"cve": {"id": "GHSA-aaaa"}}) is None
    assert ct.transform_nvd_vulnerability({"cve": {"id": ""}}) is None
    assert ct.transform_nvd_vulnerability({}) is None


def test_nvd_datetime_parsing_variants():
    assert ct.parse_nvd_dt("2024-01-02T03:04:05.123") == datetime(
        2024, 1, 2, 3, 4, 5, 123000, tzinfo=timezone.utc)
    assert ct.parse_nvd_dt("2024-01-02T03:04:05") == datetime(
        2024, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
    assert ct.parse_nvd_dt("2024-01-02") == datetime(2024, 1, 2, tzinfo=timezone.utc)
    assert ct.parse_nvd_dt("") is None
    assert ct.parse_nvd_dt(None) is None
    assert ct.parse_nvd_dt("not-a-date") is None


def test_prefers_nvd_primary_over_cna_secondary():
    entry = _entry(metrics={
        "cvssMetricV31": [
            {"source": "cna@vendor.example", "type": "Secondary",
             "cvssData": {"version": "3.1", "baseScore": 7.5, "baseSeverity": "HIGH"}},
            {"source": "nvd@nist.gov", "type": "Primary",
             "cvssData": {"version": "3.1", "baseScore": 6.1, "baseSeverity": "MEDIUM"}},
        ]
    })
    doc = ct.transform_nvd_vulnerability(entry)
    assert doc["cvss_score"] == 6.1
    assert doc["severity"] == "medium"
    assert doc["cvss_source"] == "nvd@nist.gov"
    # The vendor score is preserved for display, not dropped.
    assert doc["cvss_secondary"]["score"] == 7.5


def test_cvss_v4_beats_v3():
    entry = _entry(metrics={
        "cvssMetricV31": [{"source": "nvd@nist.gov", "type": "Primary",
                           "cvssData": {"version": "3.1", "baseScore": 8.0,
                                        "baseSeverity": "HIGH"}}],
        "cvssMetricV40": [{"source": "nvd@nist.gov", "type": "Primary",
                           "cvssData": {"version": "4.0", "baseScore": 9.3,
                                        "baseSeverity": "CRITICAL"}}],
    })
    doc = ct.transform_nvd_vulnerability(entry)
    assert doc["cvss_version"] == "4.0"
    assert doc["cvss_score"] == 9.3
    assert doc["severity"] == "critical"


def test_missing_metrics_do_not_crash_and_stay_unknown():
    doc = ct.transform_nvd_vulnerability(_entry(metrics={}))
    assert doc["severity"] == "unknown"
    assert doc["cvss_score"] is None
    assert doc["cvss_secondary"] is None


def test_cvss_v2_only_entry_is_still_scored():
    entry = _entry(metrics={"cvssMetricV2": [{
        "source": "nvd@nist.gov", "type": "Primary",
        "cvssData": {"version": "2.0", "baseScore": 10.0,
                     "baseSeverity": "HIGH"}}]})
    doc = ct.transform_nvd_vulnerability(entry)
    assert doc["cvss_score"] == 10.0
    assert doc["cvss_version"] == "2.0"


def test_new_badge_window_is_24h():
    now = datetime(2025, 3, 2, 12, 0, tzinfo=timezone.utc)
    fresh = {"published": now - timedelta(hours=3), "severity": "high"}
    stale = {"published": now - timedelta(hours=30), "severity": "high"}
    assert ct.serialize_entry(fresh, now=now)["is_new"] is True
    assert ct.serialize_entry(stale, now=now)["is_new"] is False
    # Mongo returns naive datetimes; the badge must survive that.
    naive = {"published": (now - timedelta(minutes=10)).replace(tzinfo=None)}
    assert ct.serialize_entry(naive, now=now)["is_new"] is True


def test_build_filter_severity_and_text():
    f = ct.build_filter(severity="Critical")
    assert f["severity"] == "critical"
    assert ct.build_filter(severity="all") == {}
    assert ct.build_filter(severity="") == {}
    # unknown bucket must match legacy docs that stored null
    assert ct.build_filter(severity="unknown")["severity"] == {"$in": ["unknown", None]}

    by_id = ct.build_filter(q="cve-2024-9999")
    assert by_id["cve_id"] == "CVE-2024-9999"

    by_word = ct.build_filter(q="apache")
    assert "$or" in by_word
    assert by_word["$or"][0]["cve_id"]["$regex"] == "apache"


def test_build_filter_regex_input_is_escaped():
    """A query full of regex metacharacters must not become a ReDoS pattern."""
    f = ct.build_filter(q=".*.*.*(a+)+")
    pattern = f["$or"][0]["cve_id"]["$regex"]
    assert "\\." in pattern and "\\(" in pattern


def test_build_filter_days_and_exploit_flags():
    f = ct.build_filter(days=7, has_exploit=True)
    assert "published" in f
    assert f["has_exploit_ref"] is True
    assert ct.build_filter(days=0).get("published") is None
    # KEV is not wired yet - the filter must fail closed, never open.
    assert ct.build_filter(kev_only=True)["_id"] == {"$in": []}


def test_sort_map_covers_ui_options():
    for key in ("newest", "severity", "cvss"):
        assert key in ct.SORTS
    assert ct.SORTS["newest"] == [("published", -1)]


def test_product_token_extraction_is_bounded():
    nodes = [{"nodes": [{"cpeMatch": [
        {"criteria": f"cpe:2.3:a:v{v}:p{v}:1.0:*:*:*:*:*:*:*"} for v in range(40)
    ]}]}]
    assert len(ct._product_tokens(nodes)) == 12
