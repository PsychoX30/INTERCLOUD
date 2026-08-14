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
    """
    if span <= timedelta(hours=6):
        return "raw"
    elif span <= timedelta(days=7):
        return "hourly"
    else:
        return "daily"


def _bucket_start(dt: datetime, tier: str) -> datetime:
    """Truncate *dt* to the start of its bucket for the given tier."""
    if tier == "raw":
        return dt
    elif tier == "hourly":
        return dt.replace(minute=0, second=0, microsecond=0)
    else:  # daily
        return dt.replace(hour=0, minute=0, second=0, microsecond=0)


def _consolidate(samples: list[dict], tier: str) -> list[dict]:
    """On-the-fly consolidation of raw/finer samples into bucketed points.

    Groups by bucket start, computes avg/min/max per bucket — same math
    as the background rollup, but done at read time so charts always
    have data even before the scheduled downsample runs.
    """
    if tier == "raw":
        return samples

    buckets: dict[datetime, list[float]] = defaultdict(list)
    for s in samples:
        at = s["at"]
        if isinstance(at, str):
            at = datetime.fromisoformat(at.replace("Z", "+00:00"))
        v = s.get("value")
        if isinstance(v, (int, float)):
            buckets[_bucket_start(at, tier)].append(float(v))

    result = []
    for bucket_start in sorted(buckets):
        vals = buckets[bucket_start]
        if not vals:
            continue
        result.append({
            "at": bucket_start,
            "value": sum(vals) / len(vals),
            "min": min(vals),
            "max": max(vals),
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

    # Overlay archives by target bucket, from coarsest to finest. A finer tier
    # replaces the same bucket from a coarser tier, preventing duplicate points
    # while filling recent buckets that the scheduled rollup has not produced.
    by_bucket: dict[datetime, dict] = {}

    if resolution == "daily":
        for point in await _fetch_daily():
            by_bucket[_bucket_start(point["at"], "daily")] = point
        for point in _consolidate(await _fetch_hourly(), "daily"):
            by_bucket[point["at"]] = point

    if resolution == "hourly":
        for point in await _fetch_hourly():
            by_bucket[_bucket_start(point["at"], "hourly")] = point

    for point in _consolidate(await _fetch_raw(), resolution):
        by_bucket[point["at"]] = point

    return [by_bucket[key] for key in sorted(by_bucket)], resolution


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