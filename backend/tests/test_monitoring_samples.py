"""Regression tests for RRD-like graph data consolidation."""
from datetime import datetime, timedelta, timezone

import pytest

from portal.monitoring_samples import _consolidate, get_graph_data

UTC = timezone.utc


class Cursor:
    def __init__(self, docs):
        self.docs = list(docs)

    def sort(self, key, _direction):
        self.docs.sort(key=lambda doc: doc[key])
        return self

    async def to_list(self, length=None):
        return self.docs if length is None else self.docs[:length]


class Collection:
    def __init__(self, docs, time_key):
        self.docs = docs
        self.time_key = time_key

    def find(self, query, _projection=None):
        bounds = query[self.time_key]
        return Cursor([
            doc for doc in self.docs
            if doc["graph_id"] == query["graph_id"]
            and bounds["$gte"] <= doc[self.time_key] <= bounds["$lte"]
        ])


class Db:
    def __init__(self, raw=(), hourly=(), daily=(), halfhour=()):
        self.monitoring_graph_samples_raw = Collection(raw, "at")
        self.monitoring_graph_samples_hourly = Collection(hourly, "hour")
        self.monitoring_graph_samples_daily = Collection(daily, "date")
        self.monitoring_graph_samples_halfhour = Collection(halfhour, "slot")


@pytest.mark.anyio
async def test_hourly_range_consolidates_raw_when_rollup_is_missing():
    start = datetime(2026, 1, 1, tzinfo=UTC)
    raw = [
        {"graph_id": "g", "at": start + timedelta(minutes=5), "value": 10},
        {"graph_id": "g", "at": start + timedelta(minutes=35), "value": 30},
        {"graph_id": "g", "at": start + timedelta(hours=1, minutes=5), "value": 50},
    ]

    data, resolution = await get_graph_data(Db(raw=raw), "g", start, start + timedelta(hours=7))

    assert resolution == "hourly"
    assert [(row["at"], row["value"], row["min"], row["max"]) for row in data] == [
        (start, 20.0, 10.0, 30.0),
        (start + timedelta(hours=1), 50.0, 50.0, 50.0),
    ]


@pytest.mark.anyio
async def test_raw_consolidation_replaces_same_hour_rollup_without_duplicate_bucket():
    start = datetime(2026, 1, 1, tzinfo=UTC)
    hourly = [{"graph_id": "g", "hour": start, "avg": 1.0, "min": 1.0, "max": 1.0}]
    raw = [
        {"graph_id": "g", "at": start + timedelta(minutes=10), "value": 10.0},
        {"graph_id": "g", "at": start + timedelta(minutes=20), "value": 30.0},
    ]

    data, _ = await get_graph_data(Db(raw=raw, hourly=hourly), "g", start, start + timedelta(hours=7))

    assert len(data) == 1
    assert data[0]["at"] == start
    assert data[0]["value"] == 20.0


@pytest.mark.anyio
async def test_daily_range_falls_back_to_hourly_then_raw_per_day():
    start = datetime(2026, 1, 1, tzinfo=UTC)
    hourly = [
        {"graph_id": "g", "hour": start + timedelta(hours=1), "avg": 10.0, "min": 8.0, "max": 12.0},
        {"graph_id": "g", "hour": start + timedelta(hours=2), "avg": 30.0, "min": 28.0, "max": 32.0},
    ]
    raw = [
        {"graph_id": "g", "at": start + timedelta(days=1, minutes=5), "value": 50.0},
        {"graph_id": "g", "at": start + timedelta(days=1, minutes=35), "value": 70.0},
    ]

    data, resolution = await get_graph_data(
        Db(raw=raw, hourly=hourly), "g", start, start + timedelta(days=70)
    )

    assert resolution == "daily"
    assert [(row["at"], row["value"]) for row in data] == [
        (start, 20.0),
        (start + timedelta(days=1), 60.0),
    ]


@pytest.mark.anyio
async def test_daily_consolidation_preserves_hourly_extremes_not_average_of_averages():
    """Peak must survive hourly -> daily consolidation.

    Regression: the read path recomputed min/max from the hourly ``avg`` values,
    so a 1D/1W/1M view reported the average of averages as the peak and erased
    every intra-hour spike (the "data tidak reliable" symptom).  Hour=1 peaks at
    900 while its average is only 10; the daily rollup must keep 900.
    """
    start = datetime(2026, 1, 1, tzinfo=UTC)
    hourly = [
        {"graph_id": "g", "hour": start + timedelta(hours=1), "avg": 10.0, "min": 2.0, "max": 900.0},
        {"graph_id": "g", "hour": start + timedelta(hours=2), "avg": 30.0, "min": 28.0, "max": 32.0},
    ]

    data, resolution = await get_graph_data(
        Db(hourly=hourly), "g", start, start + timedelta(days=70)
    )

    assert resolution == "daily"
    assert len(data) == 1
    row = data[0]
    assert row["value"] == 20.0          # average still average-of-averages
    assert row["max"] == 900.0, "daily peak must come from hourly max, not hourly avg"
    assert row["min"] == 2.0, "daily trough must come from hourly min"


@pytest.mark.anyio
async def test_daily_consolidation_merges_daily_rollup_with_live_hourly_keeps_peak():
    """Daily view merges stored daily rollups with freshly-consolidated hourly
    data. The fresh part must contribute its true peak, not its average."""
    start = datetime(2026, 1, 1, tzinfo=UTC)
    daily = [
        {"graph_id": "g", "date": start, "avg": 5.0, "min": 1.0, "max": 7.0},
    ]
    hourly = [
        {"graph_id": "g", "hour": start + timedelta(days=1, hours=1), "avg": 10.0, "min": 2.0, "max": 800.0},
        {"graph_id": "g", "hour": start + timedelta(days=1, hours=2), "avg": 30.0, "min": 28.0, "max": 32.0},
    ]

    data, resolution = await get_graph_data(
        Db(hourly=hourly, daily=daily), "g", start, start + timedelta(days=70)
    )

    assert resolution == "daily"
    by_day = {row["at"]: row for row in data}
    assert by_day[start]["max"] == 7.0, "stored daily rollup extremes must be kept"
    assert by_day[start + timedelta(days=1)]["max"] == 800.0, (
        "hourly-sourced day must report the real intra-day peak"
    )


def test_consolidate_uses_upstream_extremes_instead_of_recomputing_from_average():
    """Unit-level guarantee for the read-path consolidation math.

    Input rows already carry server-computed min/max (hourly/daily rollups).
    Consolidating them further must aggregate min-of-mins / max-of-maxes; using
    the `value` (already an average) would hide the spike.
    """
    start = datetime(2026, 1, 1, tzinfo=UTC)
    finer = [
        {"at": start + timedelta(minutes=5), "value": 10.0, "min": 9.0, "max": 11.0},
        {"at": start + timedelta(minutes=35), "value": 30.0, "min": 25.0, "max": 500.0},
    ]

    out = _consolidate(finer, "hourly")

    assert len(out) == 1
    assert out[0]["value"] == 20.0
    assert out[0]["max"] == 500.0
    assert out[0]["min"] == 9.0


# ---------------------------------------------------------------------------
# 30-minute tier (matches LibreNMS RRA AVERAGE:0.5:6:1440 -> 30min x 30d)
# ---------------------------------------------------------------------------
def test_bucket_start_places_halfhour_slots():
    """30-minute slots are :00 and :30, never arbitrary minutes."""
    from portal.monitoring_samples import _bucket_start

    base = datetime(2026, 1, 1, 10, 14, 33, tzinfo=UTC)
    assert _bucket_start(base, "halfhour") == datetime(2026, 1, 1, 10, 0, tzinfo=UTC)
    later = datetime(2026, 1, 1, 10, 45, 1, tzinfo=UTC)
    assert _bucket_start(later, "halfhour") == datetime(2026, 1, 1, 10, 30, tzinfo=UTC)


def test_resolve_tier_maps_presets_to_expected_buckets():
    """The preset -> tier mapping the plan promises (1W/1M now 30-minute)."""
    from portal.monitoring_samples import _resolve_tier

    assert _resolve_tier(timedelta(hours=1)) == "raw"
    assert _resolve_tier(timedelta(hours=24)) == "hourly"
    assert _resolve_tier(timedelta(days=7)) == "halfhour"
    assert _resolve_tier(timedelta(days=30)) == "halfhour"
    assert _resolve_tier(timedelta(days=365)) == "daily"


@pytest.mark.anyio
async def test_month_range_uses_halfhour_rollup_when_present():
    """A 1M window reads the 30-minute archive directly (1440 pts, not 30)."""
    start = datetime(2026, 1, 1, tzinfo=UTC)
    halfhour = [
        {"graph_id": "g", "slot": start + timedelta(minutes=30), "avg": 10.0, "min": 8.0, "max": 12.0},
        {"graph_id": "g", "slot": start + timedelta(hours=1), "avg": 30.0, "min": 28.0, "max": 32.0},
    ]

    data, resolution = await get_graph_data(
        Db(halfhour=halfhour), "g", start, start + timedelta(days=30)
    )

    assert resolution == "halfhour"
    assert [(row["at"], row["value"], row["min"], row["max"]) for row in data] == [
        (start + timedelta(minutes=30), 10.0, 8.0, 12.0),
        (start + timedelta(hours=1), 30.0, 28.0, 32.0),
    ]


@pytest.mark.anyio
async def test_month_range_derives_halfhour_from_hourly_before_rollup_exists():
    """The 30-minute tier is new, so an existing 30d window only has hourly
    history. It must still render at 30-minute resolution instead of silently
    dropping to 30 daily points (the regression this tier fixes)."""
    start = datetime(2026, 1, 1, tzinfo=UTC)
    hourly = [
        {"graph_id": "g", "hour": start, "avg": 10.0, "min": 8.0, "max": 12.0},
        {"graph_id": "g", "hour": start + timedelta(hours=1), "avg": 30.0, "min": 28.0, "max": 32.0},
    ]

    data, resolution = await get_graph_data(
        Db(hourly=hourly), "g", start, start + timedelta(days=30)
    )

    assert resolution == "halfhour (from hourly)"
    # Each hourly rollup becomes a 30-minute bucket at :00 carrying its min/max.
    assert [(row["at"], row["value"], row["max"]) for row in data] == [
        (start, 10.0, 12.0),
        (start + timedelta(hours=1), 30.0, 32.0),
    ]


@pytest.mark.anyio
async def test_daily_fallback_prefers_halfhour_over_hourly():
    """For days the daily rollup has not produced yet, prefer the finer
    30-minute archive over hourly so the gap keeps its real extremes."""
    start = datetime(2026, 1, 1, tzinfo=UTC)
    halfhour = [
        {"graph_id": "g", "slot": start + timedelta(days=1, hours=1), "avg": 10.0, "min": 2.0, "max": 800.0},
        {"graph_id": "g", "slot": start + timedelta(days=1, hours=1, minutes=30), "avg": 30.0, "min": 28.0, "max": 32.0},
    ]

    data, resolution = await get_graph_data(
        Db(halfhour=halfhour), "g", start, start + timedelta(days=70)
    )

    assert resolution == "daily"
    by_day = {row["at"]: row for row in data}
    row = by_day[start + timedelta(days=1)]
    assert row["max"] == 800.0, "30-minute peak must survive into the daily bucket"
    assert row["min"] == 2.0
    assert row["value"] == 20.0
