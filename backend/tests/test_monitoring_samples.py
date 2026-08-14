"""Regression tests for RRD-like graph data consolidation."""
from datetime import datetime, timedelta, timezone

import pytest

from portal.monitoring_samples import get_graph_data

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
    def __init__(self, raw=(), hourly=(), daily=()):
        self.monitoring_graph_samples_raw = Collection(raw, "at")
        self.monitoring_graph_samples_hourly = Collection(hourly, "hour")
        self.monitoring_graph_samples_daily = Collection(daily, "date")


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
        Db(raw=raw, hourly=hourly), "g", start, start + timedelta(days=8)
    )

    assert resolution == "daily"
    assert [(row["at"], row["value"]) for row in data] == [
        (start, 20.0),
        (start + timedelta(days=1), 60.0),
    ]
