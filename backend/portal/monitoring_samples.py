"""Time-series graph samples with downsampling tiers.

All functions receive ``db`` as a parameter for consistency.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone

from pymongo import ASCENDING, DESCENDING


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


async def get_graph_data(
    db,
    graph_id: str,
    from_dt: datetime,
    to_dt: datetime,
    *,
    resolution: str = "auto",
) -> list[dict]:
    """Return graph data for chart rendering, auto-selecting tier based on range.

    Tiers:
    - raw: ≤ 6 hours, 60s samples, TTL 7 days
    - hourly: ≤ 7 days, avg/max/min per hour, TTL 90 days
    - daily: > 7 days, avg/max/min per day, TTL 2 years
    """
    span = to_dt - from_dt

    if resolution == "auto":
        if span <= timedelta(hours=6):
            resolution = "raw"
        elif span <= timedelta(days=7):
            resolution = "hourly"
        else:
            resolution = "daily"

    if resolution == "raw":
        coll = db.monitoring_graph_samples_raw
        cursor = coll.find(
            {"graph_id": graph_id, "at": {"$gte": from_dt, "$lte": to_dt}}
        ).sort("at", ASCENDING)
        return await cursor.to_list(length=None)

    elif resolution == "hourly":
        coll = db.monitoring_graph_samples_hourly
        cursor = coll.find(
            {"graph_id": graph_id, "hour": {"$gte": from_dt, "$lte": to_dt}}
        ).sort("hour", ASCENDING)
        return [
            {"at": doc["hour"], "value": doc["avg"], "min": doc["min"], "max": doc["max"]}
            for doc in await cursor.to_list(length=None)
        ]

    else:  # daily
        coll = db.monitoring_graph_samples_daily
        cursor = coll.find(
            {"graph_id": graph_id, "date": {"$gte": from_dt, "$lte": to_dt}}
        ).sort("date", ASCENDING)
        return [
            {"at": doc["date"], "value": doc["avg"], "min": doc["min"], "max": doc["max"]}
            for doc in await cursor.to_list(length=None)
        ]


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