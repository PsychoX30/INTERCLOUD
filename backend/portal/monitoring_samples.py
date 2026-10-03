"""Time-series graph samples with downsampling tiers.

All functions receive ``db`` as a parameter for consistency.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone

from pymongo import ASCENDING, DESCENDING

# Maximum number of raw samples fetched for on-the-fly consolidation.
# Raw TTL is 7 days at ~60s intervals = ~10k docs max per graph, but
# we cap to stay safe with high-frequency polling (20s → ~30k/7d).
_RAW_FETCH_LIMIT = 30_000


async def insert_sample(
    db,
    *,
    graph_id: str,
    at: datetime,
    value: float,
    raw: str = "",
) -> dict:
    """Insert a raw graph sample."""
    doc = {
        "graph_id": graph_id,
        "at": at,
        "value": value,
        "raw": raw,
    }
    await db.monitoring_graph_samples_raw.insert_one(doc)
    return doc


def _resolve_tier(span: timedelta) -> str:
    """Pick the target bucket size for a given time span.

    Mirrors RRDTool's RRA selection: choose the finest archive whose
    step produces a reasonable number of points for the requested range.

    Boundaries (point counts for the preset that lands there):
      ``<= 6h``  -> raw       (20s,  1H  = 180 pts)
      ``<= 2d``  -> fivemin   (5m,   1D  = 288 pts)   LibreNMS-parity
      ``<= 60d`` -> halfhour  (30m,  1W  = 336 pts, 1M = 1440 pts)
      else       -> daily     (1d,   1Y  = 365 pts)

    The 5-minute tier replaces the old 1-hour tier for 1D so the chart has
    the same granularity LibreNMS gets from its ``:1`` RRA. Raw TTL is 7d
    at 20s cadence (~4.3k docs for 1D, well under _RAW_FETCH_LIMIT), so
    on-the-fly consolidation covers 1D-2d without a stored rollup.
    """
    if span <= timedelta(hours=6):
        return "raw"
    elif span <= timedelta(days=2):
        return "fivemin"
    elif span <= timedelta(days=60):
        return "halfhour"
    else:
        return "daily"


def _bucket_start(dt: datetime, tier: str) -> datetime:
    """Truncate *dt* to the start of its bucket for the given tier."""
    if tier == "raw":
        return dt
    elif tier == "fivemin":
        # 5-minute slots: :00, :05, :10 ...
        return dt.replace(minute=(dt.minute // 5) * 5, second=0, microsecond=0)
    elif tier == "halfhour":
        # 30-minute slots: :00 and :30
        return dt.replace(minute=30 if dt.minute >= 30 else 0, second=0, microsecond=0)
    elif tier == "hourly":
        return dt.replace(minute=0, second=0, microsecond=0)
    else:  # daily
        return dt.replace(hour=0, minute=0, second=0, microsecond=0)


def _consolidate(samples: list[dict], tier: str) -> list[dict]:
    """On-the-fly consolidation of raw/finer samples into bucketed points.

    Groups by bucket start, computes avg/min/max per bucket — same math
    as the background rollup, but done at read time so charts always
    have data even before the scheduled downsample runs.

    Input samples may already carry server-computed ``min``/``max`` (hourly and
    daily rollups do). Those are combined as min-of-mins / max-of-maxes, NOT
    recomputed from the ``value`` field: for rollups ``value`` is already an
    average, so recomputing would report the average of averages as the peak
    and silently hide every intra-hour spike in a day/week/month view.
    """
    if tier == "raw":
        return samples

    buckets: dict[datetime, list[float]] = defaultdict(list)
    # Per-bucket extremes carried over from upstream rollups, when present.
    bucket_mins: dict[datetime, list[float]] = defaultdict(list)
    bucket_maxs: dict[datetime, list[float]] = defaultdict(list)
    for s in samples:
        at = s["at"]
        if isinstance(at, str):
            at = datetime.fromisoformat(at.replace("Z", "+00:00"))
        v = s.get("value")
        if isinstance(v, (int, float)):
            buckets[_bucket_start(at, tier)].append(float(v))
        lo, hi = s.get("min"), s.get("max")
        if isinstance(lo, (int, float)):
            bucket_mins[_bucket_start(at, tier)].append(float(lo))
        if isinstance(hi, (int, float)):
            bucket_maxs[_bucket_start(at, tier)].append(float(hi))

    result = []
    for bucket_start in sorted(buckets):
        vals = buckets[bucket_start]
        if not vals:
            continue
        mins = bucket_mins.get(bucket_start) or vals
        maxs = bucket_maxs.get(bucket_start) or vals
        result.append({
            "at": bucket_start,
            "value": sum(vals) / len(vals),
            "min": min(mins),
            "max": max(maxs),
        })
    return result


async def get_graph_data(
    db,
    graph_id: str,
    from_dt: datetime,
    to_dt: datetime,
    *,
    resolution: str = "auto",
) -> tuple[list[dict], str]:
    """Return graph data for chart rendering, auto-selecting tier based on range.

    Uses a hybrid approach inspired by RRDTool:
    1. Select target bucket size (raw / hourly / daily) from the span.
    2. Fetch pre-computed rollups for the target tier (fast for historical data).
    3. If rollups are sparse or missing, fetch raw samples and consolidate
       on-the-fly (covers the gap before the scheduled downsample runs).
    4. For large ranges (> 7 days) where raw has TTL-expired, merge multiple
       tiers: daily rollups for older data + on-the-fly raw for recent data.

    Returns (data_points, resolution_name).
    """
    span = to_dt - from_dt

    if resolution == "auto":
        resolution = _resolve_tier(span)

    async def _fetch_raw(lte: datetime | None = None, gte: datetime | None = None) -> list[dict]:
        query: dict = {"graph_id": graph_id, "at": {"$gte": gte if gte is not None else from_dt}}
        query["at"]["$lte"] = lte if lte is not None else to_dt
        cursor = db.monitoring_graph_samples_raw.find(
            query,
            {"_id": 0, "at": 1, "value": 1},
        ).sort("at", ASCENDING)
        return await cursor.to_list(length=_RAW_FETCH_LIMIT)

    async def _fetch_hourly(lte: datetime | None = None) -> list[dict]:
        query: dict = {"graph_id": graph_id, "hour": {"$gte": from_dt}}
        if lte is not None:
            query["hour"]["$lte"] = lte
        else:
            query["hour"]["$lte"] = to_dt
        cursor = db.monitoring_graph_samples_hourly.find(
            query,
            {"_id": 0, "hour": 1, "avg": 1, "min": 1, "max": 1},
        ).sort("hour", ASCENDING)
        return [
            {"at": doc["hour"], "value": doc["avg"], "min": doc["min"], "max": doc["max"]}
            for doc in await cursor.to_list(length=None)
        ]

    async def _fetch_halfhour(lte: datetime | None = None) -> list[dict]:
        query: dict = {"graph_id": graph_id, "slot": {"$gte": from_dt}}
        if lte is not None:
            query["slot"]["$lte"] = lte
        else:
            query["slot"]["$lte"] = to_dt
        cursor = db.monitoring_graph_samples_halfhour.find(
            query,
            {"_id": 0, "slot": 1, "avg": 1, "min": 1, "max": 1},
        ).sort("slot", ASCENDING)
        return [
            {"at": doc["slot"], "value": doc["avg"], "min": doc["min"], "max": doc["max"]}
            for doc in await cursor.to_list(length=None)
        ]

    async def _fetch_daily(lte: datetime | None = None) -> list[dict]:
        query: dict = {"graph_id": graph_id, "date": {"$gte": from_dt}}
        if lte is not None:
            query["date"]["$lte"] = lte
        else:
            query["date"]["$lte"] = to_dt
        cursor = db.monitoring_graph_samples_daily.find(
            query,
            {"_id": 0, "date": 1, "avg": 1, "min": 1, "max": 1},
        ).sort("date", ASCENDING)
        return [
            {"at": doc["date"], "value": doc["avg"], "min": doc["min"], "max": doc["max"]}
            for doc in await cursor.to_list(length=None)
        ]

    if resolution == "raw":
        return await _fetch_raw(), resolution

    if resolution == "fivemin":
        # No dedicated stored rollup for 5-minute buckets: raw TTL (7d) always
        # covers the <=2d window this tier serves, so on-the-fly
        # consolidation from raw is both sufficient and simplest — exactly
        # the same math _consolidate() already uses for every other tier.
        by_bucket_fivemin: dict[datetime, dict] = {}
        for point in _consolidate(await _fetch_raw(), "fivemin"):
            by_bucket_fivemin[point["at"]] = point
        return [by_bucket_fivemin[key] for key in sorted(by_bucket_fivemin)], resolution

    # Overlay archives by target bucket, from coarsest to finest.  A finer
    # archive always wins over a coarser one for the same bucket, and an
    # archive that only has *partial* coverage must never suppress a coarser
    # archive for the buckets it is missing.  (Pre-fix behaviour gated the
    # fallback on `if not by_bucket`, so the first days the new halfhour
    # rollup produced hid weeks of older hourly history — silent data loss
    # with no error anywhere.)
    by_bucket: dict[datetime, dict] = {}
    resolved_tier = resolution

    if resolution == "daily":
        for point in await _fetch_daily():
            by_bucket[_bucket_start(point["at"], "daily")] = point
        # Finer archives fill only the days the daily rollup has not produced
        # yet; they never replace a day it already covers.  The daily rollup is
        # the designated accumulator for the day — built from all 24 hourly
        # rollups — so it holds the true intra-day peak.  A 30-minute view of
        # the same day sees at most 2 of its 48 slots, so it can only *lower*
        # that peak; a day genuinely covered end-to-end by 30-minute slots would
        # have a daily rollup of its own.
        #
        # Regression: the halfhour loop below wrote unconditionally, so the
        # first days the new 30-minute tier produced replaced stored daily
        # rollups — a 900 bps day peak silently reported as 7.  Same overwrite
        # class already fixed on the hourly path (66bbb01); resolution must not
        # override coverage.
        # halfhour outranks hourly for the days both of them can fill.
        for point in _consolidate(await _fetch_halfhour(), "daily"):
            if point["at"] not in by_bucket:
                by_bucket[point["at"]] = point
        for point in _consolidate(await _fetch_hourly(), "daily"):
            if point["at"] not in by_bucket:
                by_bucket[point["at"]] = point
        if not by_bucket:
            resolved_tier = "daily (raw only)"

    if resolution == "halfhour":
        for point in await _fetch_halfhour():
            by_bucket[_bucket_start(point["at"], "halfhour")] = point
        # The 30-minute archive is new; overlay hourly history so a 1W/1M
        # window renders at 30-minute resolution from day one.  Native slots
        # are the truth for their bucket; hourly-derived fill the gaps.
        had_native = bool(by_bucket)
        for point in _consolidate(await _fetch_hourly(), "halfhour"):
            key = _bucket_start(point["at"], "halfhour")
            if key not in by_bucket:
                by_bucket[key] = point
        if not had_native and by_bucket:
            resolved_tier = "halfhour (from hourly)"

    if resolution == "hourly":
        for point in await _fetch_hourly():
            by_bucket[_bucket_start(point["at"], "hourly")] = point
        # The halfhour rollup only *fills gaps* here, it never replaces a stored
        # hourly rollup.  The hourly rollup is the designated accumulator for
        # the hour, so it holds the true intra-hour peak; two 30-minute slots
        # that partially cover an hour can only lower that peak.  (An
        # unconditional overlay here silently replaced the hour's 900 bps peak
        # with the 12 bps seen so far — the same overwrite class fixed on the
        # daily path.)
        had_native = bool(by_bucket)
        for point in _consolidate(await _fetch_halfhour(), "hourly"):
            key = _bucket_start(point["at"], "hourly")
            if key not in by_bucket:
                by_bucket[key] = point
        if not had_native and by_bucket:
            resolved_tier = "hourly (from 30m)"

    for point in _consolidate(await _fetch_raw(), resolution):
        by_bucket[point["at"]] = point

    return [by_bucket[key] for key in sorted(by_bucket)], resolved_tier


async def ensure_indexes(db):
    """Create TTL indexes and query indexes for graph samples."""

    # Raw samples: TTL 7 days, query by graph_id + time
    await db.monitoring_graph_samples_raw.create_index(
        [("graph_id", ASCENDING), ("at", DESCENDING)]
    )
    await db.monitoring_graph_samples_raw.create_index(
        "at", expireAfterSeconds=7 * 86400
    )

    # Hourly rollups: TTL 90 days, unique per graph_id + hour
    await db.monitoring_graph_samples_hourly.create_index(
        [("graph_id", ASCENDING), ("hour", DESCENDING)], unique=True
    )
    await db.monitoring_graph_samples_hourly.create_index(
        "hour", expireAfterSeconds=90 * 86400
    )

    # Half-hour rollups: TTL 90 days, unique per graph_id + slot
    #
    # 90d, deliberately equal to the hourly TTL and NOT the 200d originally
    # sketched in the plan.  _resolve_tier only routes windows of <=60d to the
    # halfhour archive, so retention past ~60d is storage no read path can ever
    # reach.  90d keeps a 30d safety margin over the widest window that uses it.
    # NOTE the halfhour *width* is what makes 1W/1M usable (336/1440 points);
    # the TTL only needs to outlive the read window, not outlive hourly.
    await db.monitoring_graph_samples_halfhour.create_index(
        [("graph_id", ASCENDING), ("slot", DESCENDING)], unique=True
    )
    await db.monitoring_graph_samples_halfhour.create_index(
        "slot", expireAfterSeconds=90 * 86400
    )

    # Daily rollups: TTL 2 years, unique per graph_id + date
    await db.monitoring_graph_samples_daily.create_index(
        [("graph_id", ASCENDING), ("date", DESCENDING)], unique=True
    )
    await db.monitoring_graph_samples_daily.create_index(
        "date", expireAfterSeconds=730 * 86400
    )


async def downsample_raw_to_hourly(db, before: datetime | None = None) -> dict:
    """Aggregate raw samples into hourly rollups.

    Groups raw samples by (graph_id, hour), computes avg/max/min per hour.
    Returns counts: {raw_processed, hourly_inserted, hourly_upserted}.
    """
    if before is None:
        before = datetime.now(timezone.utc) - timedelta(hours=1)

    raw_coll = db.monitoring_graph_samples_raw
    hourly_coll = db.monitoring_graph_samples_hourly

    cursor = raw_coll.find({"at": {"$lt": before}}).sort("at", ASCENDING)

    groups: dict[str, list[float]] = defaultdict(list)
    for doc in await cursor.to_list(length=None):
        graph_id = doc["graph_id"]
        hour = doc["at"].replace(minute=0, second=0, microsecond=0)
        key = f"{graph_id}_{hour.isoformat()}"
        value = doc.get("value")
        if isinstance(value, (int, float)):
            groups[key].append(float(value))

    raw_processed = 0
    hourly_inserted = 0
    hourly_upserted = 0

    for key, values in groups.items():
        graph_id, hour_str = key.split("_", 1)
        hour = datetime.fromisoformat(hour_str)
        if not values:
            continue

        avg = sum(values) / len(values)
        doc = {
            "graph_id": graph_id,
            "hour": hour,
            "avg": avg,
            "max": max(values),
            "min": min(values),
            "count": len(values),
        }

        result = await hourly_coll.update_one(
            {"graph_id": graph_id, "hour": hour},
            {"$set": doc},
            upsert=True,
        )
        raw_processed += len(values)
        if result.upserted_id:
            hourly_inserted += 1
        else:
            hourly_upserted += 1

    return {
        "raw_processed": raw_processed,
        "hourly_inserted": hourly_inserted,
        "hourly_upserted": hourly_upserted,
    }


async def downsample_raw_to_halfhour(db, before: datetime | None = None) -> dict:
    """Aggregate raw samples into 30-minute rollups.

    Groups raw samples by (graph_id, 30m slot), computes avg/max/min per slot.
    Returns counts: {raw_processed, halfhour_inserted, halfhour_upserted}.
    """
    if before is None:
        before = datetime.now(timezone.utc) - timedelta(minutes=30)

    raw_coll = db.monitoring_graph_samples_raw
    halfhour_coll = db.monitoring_graph_samples_halfhour

    cursor = raw_coll.find({"at": {"$lt": before}}).sort("at", ASCENDING)

    groups: dict[str, list[float]] = defaultdict(list)
    for doc in await cursor.to_list(length=None):
        graph_id = doc["graph_id"]
        slot = _bucket_start(doc["at"], "halfhour")
        key = f"{graph_id}_{slot.isoformat()}"
        value = doc.get("value")
        if isinstance(value, (int, float)):
            groups[key].append(float(value))

    raw_processed = 0
    halfhour_inserted = 0
    halfhour_upserted = 0

    for key, values in groups.items():
        graph_id, slot_str = key.split("_", 1)
        slot = datetime.fromisoformat(slot_str)
        if not values:
            continue

        avg = sum(values) / len(values)
        doc = {
            "graph_id": graph_id,
            "slot": slot,
            "avg": avg,
            "max": max(values),
            "min": min(values),
            "count": len(values),
        }

        result = await halfhour_coll.update_one(
            {"graph_id": graph_id, "slot": slot},
            {"$set": doc},
            upsert=True,
        )
        raw_processed += len(values)
        if result.upserted_id:
            halfhour_inserted += 1
        else:
            halfhour_upserted += 1

    return {
        "raw_processed": raw_processed,
        "halfhour_inserted": halfhour_inserted,
        "halfhour_upserted": halfhour_upserted,
    }


async def downsample_hourly_to_daily(db, before: datetime | None = None) -> dict:
    """Aggregate hourly rollups into daily rollups.

    Groups hourly samples by (graph_id, date), computes avg/max/min per day.
    """
    if before is None:
        before = datetime.now(timezone.utc) - timedelta(days=1)

    hourly_coll = db.monitoring_graph_samples_hourly
    daily_coll = db.monitoring_graph_samples_daily

    cursor = hourly_coll.find({"hour": {"$lt": before}}).sort("hour", ASCENDING)
    docs = await cursor.to_list(length=None)

    groups: dict[str, list[dict]] = defaultdict(list)
    for doc in docs:
        graph_id = doc["graph_id"]
        date = doc["hour"].replace(hour=0, minute=0, second=0, microsecond=0)
        key = f"{graph_id}_{date.isoformat()}"
        groups[key].append(doc)

    hourly_processed = 0
    daily_inserted = 0
    daily_upserted = 0

    for key, hourly_docs in groups.items():
        graph_id, date_str = key.split("_", 1)
        date = datetime.fromisoformat(date_str)
        if not hourly_docs:
            continue

        avgs = [d["avg"] for d in hourly_docs]
        maxs = [d["max"] for d in hourly_docs]
        mins = [d["min"] for d in hourly_docs]
        total_count = sum(d["count"] for d in hourly_docs)

        doc = {
            "graph_id": graph_id,
            "date": date,
            "avg": sum(avgs) / len(avgs),
            "max": max(maxs),
            "min": min(mins),
            "count": total_count,
        }

        result = await daily_coll.update_one(
            {"graph_id": graph_id, "date": date},
            {"$set": doc},
            upsert=True,
        )
        hourly_processed += len(hourly_docs)
        if result.upserted_id:
            daily_inserted += 1
        else:
            daily_upserted += 1

    return {
        "hourly_processed": hourly_processed,
        "daily_inserted": daily_inserted,
        "daily_upserted": daily_upserted,
    }