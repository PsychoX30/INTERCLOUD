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

    data, resolution = await get_graph_data(
        Db(raw=raw), "g", start, start + timedelta(hours=7), resolution="hourly"
    )

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

    data, _ = await get_graph_data(
        Db(raw=raw, hourly=hourly), "g", start, start + timedelta(hours=7), resolution="hourly"
    )

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
    assert _resolve_tier(timedelta(hours=24)) == "fivemin"
    assert _resolve_tier(timedelta(days=2)) == "fivemin"
    assert _resolve_tier(timedelta(days=7)) == "halfhour"
    assert _resolve_tier(timedelta(days=30)) == "halfhour"
    assert _resolve_tier(timedelta(days=365)) == "daily"


def test_bucket_start_fivemin_truncates_to_five_minute_slot():
    from portal.monitoring_samples import _bucket_start

    dt = datetime(2026, 1, 1, 10, 7, 42, 500, tzinfo=UTC)
    assert _bucket_start(dt, "fivemin") == datetime(2026, 1, 1, 10, 5, tzinfo=UTC)
    dt2 = datetime(2026, 1, 1, 10, 0, 1, tzinfo=UTC)
    assert _bucket_start(dt2, "fivemin") == datetime(2026, 1, 1, 10, 0, tzinfo=UTC)


@pytest.mark.anyio
async def test_day_range_consolidates_raw_into_five_minute_buckets():
    """A 1D window renders at 5-minute resolution from raw (LibreNMS-like),
    not the coarse 1-hour tier."""
    start = datetime(2026, 1, 1, tzinfo=UTC)
    raw = [
        {"graph_id": "g", "at": start + timedelta(minutes=1), "value": 10.0},
        {"graph_id": "g", "at": start + timedelta(minutes=3), "value": 30.0},
        {"graph_id": "g", "at": start + timedelta(minutes=6), "value": 50.0},
        {"graph_id": "g", "at": start + timedelta(minutes=9), "value": 70.0},
    ]

    data, resolution = await get_graph_data(
        Db(raw=raw), "g", start, start + timedelta(hours=24)
    )

    assert resolution == "fivemin"
    assert [(row["at"], row["value"]) for row in data] == [
        (start, 20.0),
        (start + timedelta(minutes=5), 60.0),
    ]


@pytest.mark.anyio
async def test_fivemin_peak_matches_bucket_average_not_raw_spike():
    """LibreNMS parity: its finest data point is the 300s RRA step, so MAX
    never sees a sub-5-minute spike. Our fivemin tier must therefore report
    the bucket average as both avg and max — a 20s outlier inside the bucket
    must NOT become the reported Maximum. (User decision: MAX from the
    5-minute bucket, not from raw 20s samples.)"""
    start = datetime(2026, 1, 1, tzinfo=UTC)
    raw = [
        {"graph_id": "g", "at": start + timedelta(seconds=20), "value": 10.0},
        {"graph_id": "g", "at": start + timedelta(seconds=40), "value": 20.0},
        # a 20-second spike that LibreNMS would never observe
        {"graph_id": "g", "at": start + timedelta(minutes=1), "value": 900.0},
        {"graph_id": "g", "at": start + timedelta(minutes=2), "value": 30.0},
    ]

    data, resolution = await get_graph_data(
        Db(raw=raw), "g", start, start + timedelta(hours=24)
    )

    assert resolution == "fivemin"
    row = data[0]
    assert row["value"] == 240.0          # (10+20+900+30)/4
    assert row["max"] == 240.0, "MAX must be the 5-minute bucket, not the 20s spike"
    assert row["min"] == 240.0, "MIN must match the same 5-minute data point"


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


# ---------------------------------------------------------------------------
# Partial-archive fallback (silent data loss)
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_partially_filled_halfhour_archive_still_fills_older_hours_from_hourly():
    """A *partially* rolled halfhour archive must not suppress the fallback.

    Regression: the read path only fell back to a coarser archive when the
    requested tier returned *nothing* (``if not by_bucket``).  The halfhour
    rollup is new, so a 30d window right after deploy has a few days of
    halfhour slots and 25+ days of hourly history.  The old code rendered the
    few halfhour days and silently dropped every older day — the chart looked
    "almost empty" with no error anywhere.
    """
    start = datetime(2026, 1, 1, tzinfo=UTC)
    halfhour = [
        {"graph_id": "g", "slot": start + timedelta(days=29), "avg": 90.0,
         "min": 88.0, "max": 92.0},
    ]
    hourly = [
        {"graph_id": "g", "hour": start + timedelta(hours=1), "avg": 10.0,
         "min": 8.0, "max": 12.0},
        {"graph_id": "g", "hour": start + timedelta(hours=2), "avg": 30.0,
         "min": 28.0, "max": 32.0},
    ]

    data, resolution = await get_graph_data(
        Db(halfhour=halfhour, hourly=hourly), "g", start, start + timedelta(days=30)
    )

    by_at = {row["at"]: row for row in data}
    # older hours come from the hourly archive, bucket-by-bucket
    assert start + timedelta(hours=1) in by_at, "older hourly history was dropped"
    assert start + timedelta(hours=2) in by_at, "older hourly history was dropped"
    assert by_at[start + timedelta(hours=1)]["max"] == 12.0
    # the recent slot comes from the halfhour archive
    assert start + timedelta(days=29) in by_at
    assert by_at[start + timedelta(days=29)]["max"] == 92.0
    assert len(data) == 3, f"expected 3 buckets, got {len(data)}: {sorted(by_at)}"


@pytest.mark.anyio
async def test_partially_filled_hourly_archive_still_fills_recent_hours_from_halfhour():
    """Same partial-archive trap on the hourly path, recent side."""
    start = datetime(2026, 1, 1, tzinfo=UTC)
    hourly = [
        {"graph_id": "g", "hour": start + timedelta(hours=1), "avg": 10.0,
         "min": 8.0, "max": 12.0},
    ]
    halfhour = [
        {"graph_id": "g", "slot": start + timedelta(hours=20), "avg": 60.0,
         "min": 58.0, "max": 62.0},
        {"graph_id": "g", "slot": start + timedelta(hours=20, minutes=30), "avg": 70.0,
         "min": 68.0, "max": 72.0},
    ]

    data, resolution = await get_graph_data(
        Db(hourly=hourly, halfhour=halfhour), "g", start, start + timedelta(days=2),
        resolution="hourly",
    )

    by_at = {row["at"]: row for row in data}
    assert resolution == "hourly"
    assert start + timedelta(hours=1) in by_at, "hourly rollup lost"
    assert start + timedelta(hours=20) in by_at, "recent halfhour data lost"
    # both 30-minute slots collapse into the 20:00 hourly bucket
    assert by_at[start + timedelta(hours=20)]["value"] == 65.0
    assert by_at[start + timedelta(hours=20)]["max"] == 72.0


@pytest.mark.anyio
async def test_partially_filled_daily_archive_keeps_halfhour_backed_days():
    """A few stored daily rollups must not hide days only halfhour can fill."""
    start = datetime(2026, 1, 1, tzinfo=UTC)
    daily = [
        {"graph_id": "g", "date": start, "avg": 5.0, "min": 1.0, "max": 7.0},
    ]
    halfhour = [
        {"graph_id": "g", "slot": start + timedelta(days=40, hours=1), "avg": 100.0,
         "min": 98.0, "max": 900.0},
    ]

    data, resolution = await get_graph_data(
        Db(daily=daily, halfhour=halfhour), "g", start, start + timedelta(days=70)
    )

    by_day = {row["at"]: row for row in data}
    assert resolution == "daily"
    assert by_day[start]["max"] == 7.0, "stored daily rollup must be kept"
    assert start + timedelta(days=40) in by_day, "halfhour-backed day was dropped"
    assert by_day[start + timedelta(days=40)]["max"] == 900.0


@pytest.mark.anyio
async def test_partially_covering_finer_archive_must_not_lower_coarser_peak():
    """Resolution must never override coverage.

    SUPERSEDED ASSERTION (was ``test_finer_archive_wins_over_coarser_for_the_same_bucket``):
    that test asserted a single 30-minute slot for a day (``max=900``) must beat
    a stored daily rollup for the same day (``max=7``), on the reasoning that a
    finer archive holds "more trustworthy extremes".  QA reproduced that
    assumption as a live defect: it let a *partial* 30-minute view overwrite a
    complete day rollup, silently reporting a 900 bps day peak as 7.

    The daily rollup is built from all 24 hourly rollups
    (``downsample_hourly_to_daily``), so its max already covers the whole day;
    one 30-minute slot covers 1/48th of it and can only *lower* that peak.  Both
    are derived from the same raw samples, so a genuinely higher peak in the
    finer archive is a data-consistency bug, not a reason to prefer it.
    """
    start = datetime(2026, 1, 1, tzinfo=UTC)
    # Daily rollup for the day says it peaked at 900; one 30-minute slot of the
    # same day only saw 7.  The partial slot must not erase the day's peak.
    daily = [{"graph_id": "g", "date": start, "avg": 5.0, "min": 1.0, "max": 900.0}]
    halfhour = [
        {"graph_id": "g", "slot": start + timedelta(hours=1), "avg": 10.0,
         "min": 2.0, "max": 7.0},
    ]

    data, _ = await get_graph_data(
        Db(daily=daily, halfhour=halfhour), "g", start, start + timedelta(days=70)
    )

    by_day = {row["at"]: row for row in data}
    assert by_day[start]["max"] == 900.0, (
        "a partially covering finer archive must not lower the coarser day peak"
    )


@pytest.mark.anyio
async def test_halfhour_does_not_overwrite_stored_hourly_rollup_extremes():
    """A 30-minute view must fill *gaps*, not replace the hourly accumulator.

    Regression (introduced by the partial-archive fix, caught on self-review):
    the halfhour overlay on the hourly path wrote unconditionally, so two
    30-minute slots partially covering hour 01:00 replaced that hour's stored
    rollup.  The hourly rollup is the designated accumulator for the hour and
    keeps the true intra-hour peak; a partial 30-minute view can only *lower*
    it.  Here the hourly rollup peaked at 900 while the two halfhour slots
    covering it saw at most 12 — the chart silently reported 12.
    """
    start = datetime(2026, 1, 1, tzinfo=UTC)
    hourly = [
        {"graph_id": "g", "hour": start + timedelta(hours=1), "avg": 10.0,
         "min": 2.0, "max": 900.0},
    ]
    halfhour = [
        {"graph_id": "g", "slot": start + timedelta(hours=1), "avg": 10.0,
         "min": 8.0, "max": 12.0},
        {"graph_id": "g", "slot": start + timedelta(hours=1, minutes=30), "avg": 11.0,
         "min": 9.0, "max": 11.0},
    ]

    data, resolution = await get_graph_data(
        Db(hourly=hourly, halfhour=halfhour), "g", start, start + timedelta(days=2),
        resolution="hourly",
    )

    assert resolution == "hourly"
    row = next(r for r in data if r["at"] == start + timedelta(hours=1))
    assert row["max"] == 900.0, (
        "stored hourly rollup peak was overwritten by a partial 30-minute view"
    )
    assert row["min"] == 2.0
    assert row["value"] == 10.0


@pytest.mark.anyio
async def test_halfhour_still_fills_hours_the_hourly_rollup_missing():
    """...but the same overlay must still fill hours hourly has no data for."""
    start = datetime(2026, 1, 1, tzinfo=UTC)
    hourly = [
        {"graph_id": "g", "hour": start + timedelta(hours=1), "avg": 10.0,
         "min": 8.0, "max": 12.0},
    ]
    halfhour = [
        {"graph_id": "g", "slot": start + timedelta(hours=20), "avg": 60.0,
         "min": 58.0, "max": 62.0},
        {"graph_id": "g", "slot": start + timedelta(hours=20, minutes=30), "avg": 70.0,
         "min": 68.0, "max": 72.0},
    ]

    data, _ = await get_graph_data(
        Db(hourly=hourly, halfhour=halfhour), "g", start, start + timedelta(days=2),
        resolution="hourly",
    )

    by_at = {row["at"]: row for row in data}
    assert by_at[start + timedelta(hours=1)]["max"] == 12.0, "stored hourly rollup kept"
    assert start + timedelta(hours=20) in by_at, "gap hour was not filled"
    assert by_at[start + timedelta(hours=20)]["max"] == 72.0
    assert by_at[start + timedelta(hours=20)]["min"] == 58.0


@pytest.mark.anyio
async def test_daily_rollup_peak_not_overwritten_by_partial_halfhour_slot():
    """Attack (b) — the daily branch replaced a stored daily rollup with the
    30-minute view for the same day, erasing the day's real peak.

    The 30-minute tier is new, so for weeks after deploy a month window has a
    handful of halfhour slots plus complete daily rollups for older days — yet
    the overlay ran unconditionally.  Same overwrite class already fixed on the
    hourly path (66bbb01); the daily path still had `by_bucket[at] = point`.

    A daily rollup covers the whole day (peak 900); a 30-minute slot covers one
    hour and can only *lower* that peak (seen-so-far 7).  Finer archives fill
    gaps, they never replace a coarser archive whose bucket they only partly
    cover.
    """
    start = datetime(2026, 1, 1, tzinfo=UTC)
    daily = [{"graph_id": "g", "date": start, "avg": 12.0, "min": 3.0, "max": 900.0}]
    halfhour = [
        {"graph_id": "g", "slot": start + timedelta(hours=1), "avg": 5.0,
         "min": 5.0, "max": 7.0},
    ]

    data, resolution = await get_graph_data(
        Db(daily=daily, halfhour=halfhour), "g", start, start + timedelta(days=70)
    )

    assert resolution == "daily"
    row = next(r for r in data if r["at"] == start)
    assert row["max"] == 900.0, (
        "stored daily rollup peak was overwritten by a partial 30-minute view"
    )
    assert row["min"] == 3.0
    assert row["value"] == 12.0


@pytest.mark.anyio
async def test_daily_still_fills_days_the_daily_rollup_missing():
    """...but a day the daily rollup has not produced yet must still be filled
    from the finer archives — that gap-fill is the entire reason for the overlay."""
    start = datetime(2026, 1, 1, tzinfo=UTC)
    daily = [{"graph_id": "g", "date": start, "avg": 12.0, "min": 3.0, "max": 900.0}]
    next_day = start + timedelta(days=1)
    halfhour = [
        {"graph_id": "g", "slot": next_day + timedelta(hours=1), "avg": 60.0,
         "min": 58.0, "max": 62.0},
        {"graph_id": "g", "slot": next_day + timedelta(hours=1, minutes=30),
         "avg": 70.0, "min": 68.0, "max": 72.0},
    ]

    data, _ = await get_graph_data(
        Db(daily=daily, halfhour=halfhour), "g", start, start + timedelta(days=70)
    )

    by_at = {row["at"]: row for row in data}
    assert by_at[start]["max"] == 900.0, "stored daily rollup must be kept"
    assert next_day in by_at, "day missing from the daily rollup was not filled"
    assert by_at[next_day]["max"] == 72.0
    assert by_at[next_day]["min"] == 58.0
