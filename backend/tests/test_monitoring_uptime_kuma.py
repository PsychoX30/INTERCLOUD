"""Uptime-Kuma behaviour: confirmed transitions, dedup, and honest uptime.

The pre-existing foundation covered "write a sample and a transition event".
What it did NOT cover is what actually makes Kuma trustworthy:

1. A single lost probe must not page anyone (retries / pending window), and
   only a *confirmed* state change may emit an event — including the second
   failure that finally confirms DOWN.
2. A confirmed transition must actually reach a notification channel, and the
   recorded outcome must be truthful: "attempted" is not "sent".  A channel
   that raises, returns ``skipped`` or a non-2xx webhook response is not
   counted as notified.
3. Uptime must be computed from the *expected* schedule, not from whatever
   samples happen to exist, so a stalled scheduler shows up as gaps instead of
   a fake 100% — and a gap (unknown) must never be reported as DOWN.

Everything here is offline: ping, SMTP, Telegram and webhooks are all faked,
so the suite never touches the network.
"""
import asyncio
import pytest
from datetime import datetime, timedelta, timezone

from portal import monitoring

UTC = timezone.utc
NOW = datetime(2026, 10, 22, 12, 0, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Fakes — deliberately honour the Mongo operators the code relies on, so the
# tests prove the *query* is right instead of relying on the fake ignoring it.
# ---------------------------------------------------------------------------
def _match(row: dict, query: dict) -> bool:
    for key, expected in query.items():
        if key == "$or":
            if not any(_match(row, sub) for sub in expected):
                return False
            continue
        actual = row.get(key)
        if isinstance(expected, dict):
            if "$exists" in expected:
                if (key in row) != bool(expected["$exists"]):
                    return False
                continue
            if "$ne" in expected and actual == expected["$ne"]:
                return False
            if "$gte" in expected and (actual is None or actual < expected["$gte"]):
                return False
            if "$lt" in expected and (actual is None or actual >= expected["$lt"]):
                return False
            if "$lte" in expected and (actual is None or actual > expected["$lte"]):
                return False
            if "$in" in expected:
                # ``events`` is stored as an array on notif channels, so $in
                # means "any element matches"; scalar fields match directly.
                if isinstance(actual, (list, tuple, set)):
                    if not any(item in expected["$in"] for item in actual):
                        return False
                elif actual not in expected["$in"]:
                    return False
            continue
        if actual != expected:
            return False
    return True


class _Cursor:
    def __init__(self, rows):
        self.rows = list(rows)
        self._sort = None
        self._limit = None

    def sort(self, key, direction=1):
        self._sort = (key, direction)
        return self

    def limit(self, value):
        self._limit = value
        return self

    def _materialize(self):
        rows = self.rows
        if self._sort:
            key, direction = self._sort
            rows = sorted(rows, key=lambda r: r.get(key) or datetime.min.replace(tzinfo=UTC),
                          reverse=direction == -1)
        if self._limit is not None:
            rows = rows[:self._limit]
        return rows

    async def to_list(self, length=None):
        rows = self._materialize()
        return rows[:length] if length is not None else rows

    def __aiter__(self):
        return self._gen()

    async def _gen(self):
        for row in self._materialize():
            yield row


class _Collection:
    def __init__(self, rows=None):
        self.rows = list(rows or [])
        self.inserted = []
        self.updates = []

    async def find_one(self, query):
        return next((r for r in self.rows if _match(r, query)), None)

    def find(self, query, _projection=None):
        return _Cursor([r for r in self.rows if _match(r, query)])

    async def insert_one(self, doc):
        if "_id" in doc:
            if any(r.get("_id") == doc["_id"] for r in self.rows):
                from pymongo.errors import DuplicateKeyError
                raise DuplicateKeyError("duplicate _id")
        else:
            doc = {**doc, "_id": f"gen{len(self.rows)}"}
        self.rows.append(doc)
        self.inserted.append(doc)
        return type("R", (), {"inserted_id": doc.get("_id")})()

    async def update_one(self, query, update, upsert=False):
        self.updates.append((query, update, upsert))
        matched = 0
        for row in self.rows:
            if _match(row, query):
                row.update(update.get("$set", {}))
                for k in update.get("$unset", {}):
                    row.pop(k, None)
                matched += 1
        if not matched and upsert:
            doc = {k: v for k, v in query.items() if not isinstance(v, dict)}
            doc.update(update.get("$set", {}))
            self.rows.append(doc)
            matched = 1
        return type("R", (), {"matched_count": matched})()

    def aggregate(self, pipeline):
        # Only the single shape ``_uptime_count_aggregated`` emits is supported:
        # match -> sort -> group-by-slot -> match slot range.
        match_stage = pipeline[0]["$match"]
        rows = [r for r in self.rows if _match(r, match_stage)]
        rows.sort(key=lambda r: r["at"])
        interval = None
        window_start = None
        group = pipeline[2]["$group"]
        slot_expr = group["_id"]
        # The fake recovers the divisor from the pipeline rather than guessing.
        divisor = slot_expr["$toLong"]["$floor"]["$divide"][1]
        interval = divisor / 1000
        window_start = slot_expr["$toLong"]["$floor"]["$divide"][0]["$subtract"][1]
        buckets = {}
        for row in rows:
            slot = int(((row["at"] - window_start).total_seconds()) // interval)
            buckets[slot] = {"_id": slot, "up": row.get("up"), "rtt_ms": row.get("rtt_ms")}
        bounds = pipeline[3]["$match"]["_id"]
        out = [
            b for slot, b in sorted(buckets.items())
            if bounds["$gte"] <= slot < bounds["$lt"]
        ]
        return _Cursor(out)


class _Channels:
    def __init__(self, rows):
        self.rows = rows

    def find(self, query):
        # Honour enabled + $in(events) exactly like Mongo, so the test proves
        # the *query* filters correctly rather than the code post-filtering.
        return _Cursor([r for r in self.rows if _match(r, query)])


class _Leases:
    def __init__(self, owner):
        self._owner = owner

    async def find_one_and_update(self, *a, **k):
        return {"owner": self._owner}

    async def find_one(self, _q):
        return {"owner": self._owner}

    async def update_one(self, *a, **k):
        return None


class _Db:
    def __init__(self, owner="host:1", channels=None, checks=None):
        self.monitoring_probes = _Collection()
        self.monitoring_check_state = _Collection()
        self.monitoring_events = _Collection()
        self.monitoring_checks = _Collection(checks)
        self.notif_channels = _Channels(channels or [])
        self.ddos_notify_log = _Collection()
        self.scheduler_leases = _Leases(owner)


def _ping(up, avg=3.2):
    async def fake(target, **kw):
        return {"tool": "ping", "summary": {
            "count": 3, "received": 3 if up else 0, "lost": 0 if up else 3,
            "loss_percent": 0.0 if up else 100.0,
            "min_ms": 2.8 if up else None,
            "avg_ms": avg if up else None,
            "max_ms": 3.7 if up else None,
        }, "results": []}
    return fake


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """Fail loudly if any test accidentally opens a socket."""

    async def _boom(*a, **k):
        raise AssertionError("tests must not perform real network I/O")

    class _NoHTTP:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, *a, **k):
            return await _boom()

    monkeypatch.setattr(monitoring.httpx, "AsyncClient", _NoHTTP)


# ---------------------------------------------------------------------------
# 1. retries / pending window — no page on a single lost probe
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_single_failure_stays_pending_and_emits_no_event(monkeypatch):
    db = _Db()
    db.monitoring_check_state.rows = [
        {"check_id": "c1", "status": "up", "confirmed_status": "up",
         "consecutive_failures": 0}]
    monkeypatch.setattr(monitoring, "run_ping", _ping(up=False))

    out = await monitoring.probe_target(db, target="8.8.8.8", check_id="c1",
                                        owner="host:1", retries=1)

    assert out["status"] == "pending"
    assert out["confirmed_status"] == "up"
    assert out["event"] is None
    assert db.monitoring_events.inserted == []
    # The failure counter advanced, so the next failure can confirm DOWN.
    assert db.monitoring_check_state.rows[0]["consecutive_failures"] == 1


@pytest.mark.anyio
async def test_second_consecutive_failure_confirms_down_and_dispatches(monkeypatch):
    """Two sequential failed probes with ``retries=1``: pending, then DOWN.

    The original test seeded ``consecutive_failures=0`` and ran ONE probe,
    then asserted DOWN — which only passed against the buggy code that ignored
    the retry window.  The transition must be *earned* by an actual second
    failure.
    """
    db = _Db(channels=[{"type": "email", "target": "ops@example.test",
                        "events": ["monitoring"], "enabled": True}])
    db.monitoring_check_state.rows = [
        {"check_id": "c1", "status": "up", "confirmed_status": "up",
         "consecutive_failures": 0}]
    monkeypatch.setattr(monitoring, "run_ping", _ping(up=False))

    delivered = []

    async def fake_deliver(db, *, to_email, subject, body_html, event_key):
        delivered.append((to_email, subject, event_key, body_html))
        return {"status": "sent"}

    monkeypatch.setattr(monitoring.emails_mod, "deliver", fake_deliver)
    monkeypatch.setattr(monitoring.emails_mod, "wrap_html", lambda h, logo_url=None: h)

    first = await monitoring.probe_target(db, target="8.8.8.8", check_id="c1",
                                          owner="host:1", retries=1, check_name="DNS")
    assert first["status"] == "pending"
    assert first["event"] is None
    assert db.monitoring_events.inserted == []

    second = await monitoring.probe_target(db, target="8.8.8.8", check_id="c1",
                                           owner="host:1", retries=1, check_name="DNS")
    assert second["status"] == "down"
    assert second["event"] == "down"
    assert len(db.monitoring_events.inserted) == 1
    assert db.monitoring_events.inserted[0]["from"] == "up"
    assert db.monitoring_events.inserted[0]["to"] == "down"
    assert db.monitoring_events.inserted[0]["notified"] is True
    assert db.monitoring_events.inserted[0]["notified_channels"] == ["email:ops@example.test"]
    assert delivered[0][0] == "ops@example.test"
    assert delivered[0][1].startswith("[Monitoring] DNS is DOWN")


@pytest.mark.anyio
async def test_third_failure_does_not_re_emit_down_event(monkeypatch):
    """Once confirmed DOWN, further failures must not re-page."""
    db = _Db()
    db.monitoring_check_state.rows = [
        {"check_id": "c1", "status": "down", "confirmed_status": "down",
         "consecutive_failures": 5}]
    monkeypatch.setattr(monitoring, "run_ping", _ping(up=False))

    out = await monitoring.probe_target(db, target="8.8.8.8", check_id="c1",
                                        owner="host:1", retries=1)

    assert out["status"] == "down"
    assert out["event"] is None
    assert db.monitoring_events.inserted == []


@pytest.mark.anyio
async def test_recovery_from_pending_is_not_a_recovery_event(monkeypatch):
    """Recovering out of PENDING must not fire a duplicate 'up' event."""
    db = _Db()
    db.monitoring_check_state.rows = [
        {"check_id": "c1", "status": "pending", "confirmed_status": "up",
         "consecutive_failures": 1}]
    monkeypatch.setattr(monitoring, "run_ping", _ping(up=True))

    out = await monitoring.probe_target(db, target="8.8.8.8", check_id="c1",
                                        owner="host:1", retries=1)

    assert out["status"] == "up"
    assert out["confirmed_status"] == "up"
    assert out["event"] is None
    assert db.monitoring_events.inserted == []


@pytest.mark.anyio
async def test_recovery_from_confirmed_down_emits_one_event(monkeypatch):
    db = _Db()
    db.monitoring_check_state.rows = [
        {"check_id": "c1", "status": "down", "confirmed_status": "down",
         "consecutive_failures": 3}]
    monkeypatch.setattr(monitoring, "run_ping", _ping(up=True))
    monkeypatch.setattr(monitoring, "dispatch_monitoring_alert",
                        _stub_dispatch(["email:ops@example.test"]))

    out = await monitoring.probe_target(db, target="8.8.8.8", check_id="c1",
                                        owner="host:1", retries=1)

    assert out["status"] == "up"
    assert out["event"] == "up"
    assert len(db.monitoring_events.inserted) == 1
    assert db.monitoring_events.inserted[0]["to"] == "up"


@pytest.mark.anyio
async def test_retries_zero_confirms_down_on_first_failure(monkeypatch):
    """Legacy rows default to ``retries=0``: first failure is DOWN."""
    db = _Db()
    db.monitoring_check_state.rows = [
        {"check_id": "c1", "status": "up", "confirmed_status": "up",
         "consecutive_failures": 0}]
    monkeypatch.setattr(monitoring, "run_ping", _ping(up=False))
    monkeypatch.setattr(monitoring, "dispatch_monitoring_alert",
                        _stub_dispatch([]))

    out = await monitoring.probe_target(db, target="8.8.8.8", check_id="c1",
                                        owner="host:1", retries=0)

    assert out["status"] == "down"
    assert out["event"] == "down"


def _stub_dispatch(channels):
    async def _inner(db, *, check, event):
        return list(channels)
    return _inner


# ---------------------------------------------------------------------------
# 2. truthful per-channel delivery
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_transition_dispatches_to_subscribed_channels(monkeypatch):
    channels = [
        {"type": "email", "target": "ops@example.test", "events": ["monitoring"], "enabled": True},
        {"type": "email", "target": "nope@example.test", "events": ["ddos"], "enabled": True},
        {"type": "email", "target": "off@example.test", "events": ["monitoring"], "enabled": False},
    ]
    db = _Db(channels=channels)
    delivered = []

    async def fake_deliver(db, *, to_email, subject, body_html, event_key):
        delivered.append((to_email, subject, event_key, body_html))
        return {"status": "sent"}

    monkeypatch.setattr(monitoring.emails_mod, "deliver", fake_deliver)
    monkeypatch.setattr(monitoring.emails_mod, "wrap_html", lambda html, logo_url=None: html)

    event = {"check_id": "c1", "target": "8.8.8.8", "at": "now",
             "from": "up", "to": "down"}
    notified = await monitoring.dispatch_monitoring_alert(
        db, check={"name": "DNS", "target": "8.8.8.8"}, event=event)

    # Only enabled channels subscribed to monitoring/uptime/alerts.
    assert notified == ["email:ops@example.test"]
    assert [d[0] for d in delivered] == ["ops@example.test"]
    assert delivered[0][1].startswith("[Monitoring] DNS is DOWN")
    assert delivered[0][2] == "monitoring_alert"
    # Delivery log keeps the shared shape, one row per attempted channel.
    assert len(db.ddos_notify_log.inserted) == 1
    assert db.ddos_notify_log.inserted[0]["event"] == "monitoring_alert"
    assert db.ddos_notify_log.inserted[0]["status"] == "sent"


@pytest.mark.anyio
async def test_skipped_email_is_not_reported_as_notified(monkeypatch):
    """``deliver`` returns status=skipped when SMTP is off — that is not a send."""
    db = _Db(channels=[{"type": "email", "target": "ops@example.test",
                        "events": ["monitoring"], "enabled": True}])

    async def skipped_deliver(db, *, to_email, subject, body_html, event_key):
        return {"status": "skipped", "delivered_via": "log",
                "error": "SMTP integration disabled"}

    monkeypatch.setattr(monitoring.emails_mod, "deliver", skipped_deliver)
    monkeypatch.setattr(monitoring.emails_mod, "wrap_html", lambda h, logo_url=None: h)

    event = {"check_id": "c1", "target": "8.8.8.8", "at": "now",
             "from": "up", "to": "down"}
    notified = await monitoring.dispatch_monitoring_alert(
        db, check={"name": "DNS", "target": "8.8.8.8"}, event=event)

    assert notified == []
    assert db.ddos_notify_log.inserted[0]["status"] == "skipped"


@pytest.mark.anyio
async def test_failed_webhook_is_not_reported_as_notified(monkeypatch):
    db = _Db(channels=[{"type": "webhook", "target": "https://hook.test/x",
                        "events": ["monitoring"], "enabled": True}])

    class _Resp:
        status_code = 503

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, *a, **k):
            return _Resp()

    monkeypatch.setattr(monitoring.httpx, "AsyncClient", _Client)

    event = {"check_id": "c1", "target": "8.8.8.8", "at": "now",
             "from": "up", "to": "down"}
    notified = await monitoring.dispatch_monitoring_alert(
        db, check={"name": "DNS", "target": "8.8.8.8"}, event=event)

    assert notified == []
    assert db.ddos_notify_log.inserted[0]["status"] == "failed (503)"


@pytest.mark.anyio
async def test_successful_webhook_is_reported_as_notified(monkeypatch):
    db = _Db(channels=[{"type": "webhook", "target": "https://hook.test/x",
                        "events": ["uptime"], "enabled": True}])
    posts = []

    class _Resp:
        status_code = 204

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json=None):
            posts.append((url, json))
            return _Resp()

    monkeypatch.setattr(monitoring.httpx, "AsyncClient", _Client)

    event = {"check_id": "c1", "target": "8.8.8.8", "at": "now",
             "from": "up", "to": "down"}
    notified = await monitoring.dispatch_monitoring_alert(
        db, check={"name": "DNS", "target": "8.8.8.8"}, event=event)

    assert notified == ["webhook:https://hook.test/x"]
    assert posts[0][0] == "https://hook.test/x"
    assert posts[0][1]["transition"] == {"from": "up", "to": "down", "at": "now"}


@pytest.mark.anyio
async def test_dispatch_failure_never_loses_the_state_transition(monkeypatch):
    db = _Db(channels=[{"type": "email", "target": "ops@example.test",
                        "events": ["monitoring"], "enabled": True}])
    db.monitoring_check_state.rows = [
        {"check_id": "c1", "status": "up", "confirmed_status": "up",
         "consecutive_failures": 0}]

    async def boom(*a, **k):
        raise RuntimeError("SMTP down")

    monkeypatch.setattr(monitoring.emails_mod, "deliver", boom)
    monkeypatch.setattr(monitoring.emails_mod, "wrap_html", lambda h, logo_url=None: h)
    monkeypatch.setattr(monitoring, "run_ping", _ping(up=False))

    out = await monitoring.probe_target(db, target="8.8.8.8", check_id="c1",
                                        owner="host:1", retries=0)

    # State and event still recorded even though delivery blew up, and the
    # event is honestly stamped as NOT notified so an operator can retry.
    assert out["status"] == "down"
    assert len(db.monitoring_events.inserted) == 1
    assert db.monitoring_events.inserted[0]["notified"] is False
    assert db.monitoring_events.inserted[0]["notified_channels"] == []


@pytest.mark.anyio
async def test_email_body_escapes_operator_supplied_text(monkeypatch):
    """A check named with HTML must not inject markup into the alert email."""
    db = _Db(channels=[{"type": "email", "target": "ops@example.test",
                        "events": ["monitoring"], "enabled": True}])
    captured = {}

    async def fake_deliver(db, *, to_email, subject, body_html, event_key):
        captured["body"] = body_html
        captured["subject"] = subject
        return {"status": "sent"}

    monkeypatch.setattr(monitoring.emails_mod, "deliver", fake_deliver)
    monkeypatch.setattr(monitoring.emails_mod, "wrap_html", lambda h, logo_url=None: h)

    event = {"check_id": "c1", "target": '<script>alert("x")</script>',
             "at": "now", "from": "up", "to": "down"}
    await monitoring.dispatch_monitoring_alert(
        db, check={"name": '<img src=x onerror="alert(1)">',
                   "target": '<script>alert("x")</script>'}, event=event)

    body = captured["body"]
    assert "<img src=x" not in body
    assert "<script>" not in body
    assert "&lt;img src=x" in body
    assert "&lt;script&gt;" in body


# ---------------------------------------------------------------------------
# 3b. bounded retry of undelivered alerts (durability without an outbox)
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_retry_redelivers_event_that_never_landed(monkeypatch):
    """An event stamped notified=False is retried and then marked delivered."""
    db = _Db()
    db.monitoring_events.rows = [{
        "_id": "evt1", "check_id": "c1", "target": "8.8.8.8",
        "at": NOW - timedelta(minutes=5), "from": "up", "to": "down",
        "notified": False, "notify_attempts": 1,
    }]
    monkeypatch.setattr(monitoring, "dispatch_monitoring_alert",
                        _stub_dispatch(["email:ops@example.test"]))

    out = await monitoring.retry_undelivered_monitoring_alerts(db, now=NOW)

    assert out == {"scanned": 1, "sent": 1, "failed": 0, "exhausted": 0}
    row = db.monitoring_events.rows[0]
    assert row["notified"] is True
    assert row["notified_channels"] == ["email:ops@example.test"]
    assert row["notify_attempts"] == 2


@pytest.mark.anyio
async def test_retry_leaves_event_unnotified_when_delivery_still_fails(monkeypatch):
    db = _Db()
    db.monitoring_events.rows = [{
        "_id": "evt1", "check_id": "c1", "target": "8.8.8.8",
        "at": NOW - timedelta(minutes=5), "from": "up", "to": "down",
        "notified": False, "notify_attempts": 0,
    }]
    monkeypatch.setattr(monitoring, "dispatch_monitoring_alert", _stub_dispatch([]))

    out = await monitoring.retry_undelivered_monitoring_alerts(db, now=NOW)

    assert out["sent"] == 0
    assert out["failed"] == 1
    row = db.monitoring_events.rows[0]
    assert row["notified"] is False, "a failed retry must not claim delivery"
    assert row["notify_attempts"] == 1


@pytest.mark.anyio
async def test_retry_gives_up_after_max_attempts(monkeypatch):
    db = _Db()
    db.monitoring_events.rows = [{
        "_id": "evt1", "check_id": "c1", "target": "8.8.8.8",
        "at": NOW - timedelta(minutes=5), "from": "up", "to": "down",
        "notified": False, "notify_attempts": monitoring._MAX_NOTIFY_ATTEMPTS,
    }]
    called = []

    async def should_not_dispatch(db, *, check, event):
        called.append(event)
        return []

    monkeypatch.setattr(monitoring, "dispatch_monitoring_alert", should_not_dispatch)

    out = await monitoring.retry_undelivered_monitoring_alerts(db, now=NOW)

    assert out["exhausted"] == 1
    assert called == [], "an exhausted event must not be dispatched again"
    assert db.monitoring_events.rows[0]["notify_exhausted"] is True


@pytest.mark.anyio
async def test_retry_ignores_already_notified_and_stale_events(monkeypatch):
    db = _Db()
    db.monitoring_events.rows = [
        {"_id": "done", "check_id": "c1", "at": NOW - timedelta(minutes=1),
         "from": "up", "to": "down", "notified": True},
        {"_id": "stale", "check_id": "c1", "at": NOW - timedelta(days=3),
         "from": "up", "to": "down", "notified": False},
    ]
    monkeypatch.setattr(monitoring, "dispatch_monitoring_alert",
                        _stub_dispatch(["email:ops@example.test"]))

    out = await monitoring.retry_undelivered_monitoring_alerts(
        db, now=NOW, max_age_hours=24)

    assert out["scanned"] == 0


@pytest.mark.anyio
async def test_exhausted_backlog_does_not_starve_fresh_events(monkeypatch):
    """Regression: parked events must not consume the retry limit.

    Without the ``notify_exhausted`` filter, a backlog of exhausted rows
    (sorted oldest-first) fills the whole batch and a genuinely new
    undelivered event is never retried — a silent "we tried" that pages
    nobody.  Verified ad-hoc before the fix.
    """
    db = _Db()
    db.monitoring_events.rows = [
        {"_id": f"exhausted-{i}", "check_id": f"c{i}", "target": "8.8.8.8",
         "at": NOW - timedelta(minutes=30), "from": "up", "to": "down",
         "notified": False, "notify_attempts": 5, "notify_exhausted": True}
        for i in range(10)
    ] + [
        {"_id": "fresh-1", "check_id": "cfresh", "target": "1.1.1.1",
         "at": NOW - timedelta(minutes=1), "from": "up", "to": "down",
         "notified": False, "notify_attempts": 0},
    ]
    monkeypatch.setattr(monitoring, "dispatch_monitoring_alert",
                        _stub_dispatch(["email:ops@example.test"]))

    out = await monitoring.retry_undelivered_monitoring_alerts(db, now=NOW, limit=10)

    assert out["scanned"] == 1
    assert out["sent"] == 1
    assert "fresh-1" in {u[0]["_id"] for u in db.monitoring_events.updates}


@pytest.mark.anyio
async def test_retry_is_bounded_per_call(monkeypatch):
    db = _Db()
    db.monitoring_events.rows = [
        {"_id": f"evt{i}", "check_id": "c1", "target": "8.8.8.8",
         "at": NOW - timedelta(minutes=i + 1), "from": "up", "to": "down",
         "notified": False, "notify_attempts": 0}
        for i in range(30)
    ]
    monkeypatch.setattr(monitoring, "dispatch_monitoring_alert",
                        _stub_dispatch(["email:ops@example.test"]))

    out = await monitoring.retry_undelivered_monitoring_alerts(db, now=NOW, limit=5)

    assert out["scanned"] == 5, "a long outage must not produce an alert storm"
    assert out["sent"] == 5


# ---------------------------------------------------------------------------
# 3. honest uptime: expected vs observed; gaps are unknown, not DOWN
# ---------------------------------------------------------------------------
def _mk_db_for_uptime(samples, interval=60, check_id="c1", created_at=None):
    from bson import ObjectId
    oid = ObjectId()
    doc = {"_id": oid, "name": "DNS", "target": "8.8.8.8",
           "interval_seconds": interval, "enabled": True}
    if created_at is not None:
        doc["created_at"] = created_at
    db = _Db(checks=[doc])
    db.monitoring_probes.rows = [
        {"check_id": str(oid), "at": s[0], "up": s[1], "rtt_ms": s[2]} for s in samples
    ]
    return db, str(oid)


@pytest.mark.anyio
async def test_uptime_counts_gaps_as_unknown_not_down():
    """Two UP samples in a 24h/60s window: 1438 unknown slots, zero DOWN."""
    samples = [
        (NOW - timedelta(hours=2), True, 3.0),
        (NOW - timedelta(hours=1), True, 5.0),
    ]
    db, check_id = _mk_db_for_uptime(samples)
    out = await monitoring.uptime_summary(db, check_id=check_id, hours=24, now=NOW)

    assert out["expected"] == 1440
    assert out["up"] == 2
    assert out["down"] == 0, "a missing sample is unknown, never a confirmed DOWN"
    assert out["gaps"] == 1438
    assert out["observed"] == 2
    assert out["uptime_pct"] == 100.0  # of what we actually observed
    assert out["coverage_pct"] < 1.0   # and we barely observed anything
    assert out["uptime_pct_conservative"] < 1.0
    assert out["mode"] == "inline"


@pytest.mark.anyio
async def test_uptime_never_reuses_one_sample_for_many_slots():
    """One sample must not paint 1440 slots green.

    Regression: the previous walker kept ``last_sample`` across slots, so a
    single probe inside the window was counted once per remaining slot.
    """
    db, check_id = _mk_db_for_uptime([(NOW - timedelta(minutes=30), True, 4.0)])
    out = await monitoring.uptime_summary(db, check_id=check_id, hours=24, now=NOW)

    assert out["up"] == 1
    assert out["observed"] == 1
    assert out["gaps"] == 1439


@pytest.mark.anyio
async def test_uptime_full_window_is_100_percent():
    interval = 3600
    samples = [(NOW - timedelta(seconds=(i + 1) * interval), True, 4.0)
               for i in range(24)]
    db, check_id = _mk_db_for_uptime(samples, interval=interval)
    out = await monitoring.uptime_summary(db, check_id=check_id, hours=24, now=NOW)

    assert out["expected"] == 24
    assert out["up"] == 24
    assert out["down"] == 0
    assert out["gaps"] == 0
    assert out["uptime_pct"] == 100.0
    assert out["coverage_pct"] == 100.0
    assert out["avg_rtt_ms"] == 4.0


@pytest.mark.anyio
async def test_uptime_down_samples_reduce_percentage():
    interval = 3600
    samples = []
    for i in range(10):
        samples.append((NOW - timedelta(seconds=(i + 1) * interval), True, 4.0))
    for i in range(10, 24):
        samples.append((NOW - timedelta(seconds=(i + 1) * interval), False, None))
    db, check_id = _mk_db_for_uptime(samples, interval=interval)
    out = await monitoring.uptime_summary(db, check_id=check_id, hours=24, now=NOW)

    assert out["up"] == 10
    assert out["down"] == 14
    assert out["gaps"] == 0
    assert out["uptime_pct"] == round(10 / 24 * 100, 2)
    assert out["uptime_pct_conservative"] == out["uptime_pct"]


@pytest.mark.anyio
async def test_uptime_no_samples_is_all_gaps_with_no_percentage():
    db, check_id = _mk_db_for_uptime([])
    out = await monitoring.uptime_summary(db, check_id=check_id, hours=1, now=NOW)

    assert out["expected"] == 60
    assert out["gaps"] == 60
    assert out["up"] == 0
    assert out["down"] == 0
    assert out["uptime_pct"] is None, "no observations must not read as 0% or 100%"
    assert out["coverage_pct"] == 0.0


@pytest.mark.anyio
async def test_uptime_window_does_not_predate_check_creation():
    """A check created 1h ago owes 60 slots at 60s, not 1440."""
    created = NOW - timedelta(hours=1)
    samples = [(NOW - timedelta(seconds=(i + 1) * 60), True, 2.0) for i in range(60)]
    db, check_id = _mk_db_for_uptime(samples, interval=60, created_at=created)
    out = await monitoring.uptime_summary(db, check_id=check_id, hours=24, now=NOW)

    assert out["expected"] == 60
    assert out["up"] == 60
    assert out["gaps"] == 0
    assert out["uptime_pct"] == 100.0


@pytest.mark.anyio
async def test_uptime_ignores_samples_outside_the_window():
    samples = [
        (NOW - timedelta(hours=30), True, 1.0),   # before window
        (NOW + timedelta(minutes=5), True, 1.0),  # after now
        (NOW - timedelta(minutes=1), True, 2.0),  # inside
    ]
    db, check_id = _mk_db_for_uptime(samples, interval=60)
    out = await monitoring.uptime_summary(db, check_id=check_id, hours=1, now=NOW)

    assert out["up"] == 1
    assert out["expected"] == 60
    assert out["gaps"] == 59


@pytest.mark.anyio
async def test_uptime_large_window_aggregates_instead_of_truncating():
    """>20000 samples must be counted server-side, never silently truncated.

    The old code called ``to_list(20000)``: with 25,000 samples the newest
    5,000 were dropped and the missing tail was reported as gaps, i.e. the
    window was silently mis-measured.  The aggregated path must see them all.
    """
    interval = 10
    hours = 72                      # 72h * 3600 / 10s = 25,920 slots
    total = 25_000
    samples = [(NOW - timedelta(seconds=interval * (total - i)), True, 2.0)
               for i in range(total)]
    db, check_id = _mk_db_for_uptime(samples, interval=interval)
    out = await monitoring.uptime_summary(db, check_id=check_id, hours=hours, now=NOW)

    assert out["mode"] == "aggregated"
    assert out["samples_scanned"] is None  # not materialised inline
    assert out["truncated"] is False
    assert out["expected"] == 72 * 3600 // interval
    assert out["up"] == total, "every one of the 25k samples must be counted"
    assert out["down"] == 0
    assert out["gaps"] == out["expected"] - total
    assert out["coverage_pct"] == round(total / out["expected"] * 100, 2)


@pytest.mark.anyio
async def test_uptime_rejects_out_of_range_hours():
    db, check_id = _mk_db_for_uptime([])
    for bad in (0, -1, 721, 10_000):
        with pytest.raises(ValueError):
            await monitoring.uptime_summary(db, check_id=check_id, hours=bad, now=NOW)


@pytest.mark.anyio
async def test_uptime_rejects_non_integer_hours():
    db, check_id = _mk_db_for_uptime([])
    for bad in ("junk", None, True, 2.5j):
        with pytest.raises(ValueError):
            await monitoring.uptime_summary(db, check_id=check_id, hours=bad, now=NOW)


@pytest.mark.anyio
async def test_uptime_unknown_check_raises():
    from bson import ObjectId
    db = _Db(checks=[])
    with pytest.raises(ValueError):
        await monitoring.uptime_summary(db, check_id=str(ObjectId()), hours=24, now=NOW)


# ---------------------------------------------------------------------------
# 4. helpers
# ---------------------------------------------------------------------------
def test_confirmed_status_tolerates_legacy_rows():
    assert monitoring._confirmed_status(None) is None
    assert monitoring._confirmed_status({"status": "up"}) == "up"
    assert monitoring._confirmed_status({"status": "pending", "confirmed_status": "down"}) == "down"
    assert monitoring._confirmed_status({"status": "pending"}) is None


def test_retries_clamped():
    assert monitoring._check_retries(None) == 0
    assert monitoring._check_retries(3) == 3
    assert monitoring._check_retries(999) == 10
    assert monitoring._check_retries(-5) == 0
    assert monitoring._check_retries("junk") == 0


def test_probe_target_clamps_untrusted_retries(monkeypatch):
    """A hostile/garbage retries value must not widen the retry window."""
    assert monitoring._check_retries("9" * 40) == 10
    assert monitoring._check_retries(None) == 0


# ---------------------------------------------------------------------------
# 5. concurrency: two workers must never page twice for one transition
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_racing_probes_emit_only_one_event(monkeypatch):
    """Two workers observing the same up->down transition page exactly once.

    The per-check lease has a 10s TTL, so a slow probe can let a second worker
    acquire it and reach the transition with the same prior state.  Before the
    compare-and-swap on ``monitoring_check_state`` each worker minted its own
    event id from its own probe timestamp, Mongo saw two distinct ``_id``s, and
    the operator was paged twice.
    """
    db = _Db()
    db.monitoring_check_state.rows = [
        {"check_id": "c1", "status": "up", "confirmed_status": "up",
         "consecutive_failures": 0}]
    monkeypatch.setattr(monitoring, "run_ping", _ping(up=False))

    dispatched = []

    async def counting_dispatch(db, *, check, event):
        dispatched.append(event["_id"])
        return ["email:ops@example.test"]

    monkeypatch.setattr(monitoring, "dispatch_monitoring_alert", counting_dispatch)

    stale = dict(db.monitoring_check_state.rows[0])
    real_find_one = db.monitoring_check_state.find_one
    reads = {"n": 0}

    async def racing_find_one(query):
        reads["n"] += 1
        if reads["n"] == 2:
            # Worker B read its prior state before worker A committed.
            return dict(stale)
        return await real_find_one(query)

    db.monitoring_check_state.find_one = racing_find_one

    a = await monitoring.probe_target(db, target="8.8.8.8", check_id="c1",
                                      owner="host:1", retries=0)
    b = await monitoring.probe_target(db, target="8.8.8.8", check_id="c1",
                                      owner="host:1", retries=0)

    assert a["event"] == "down"
    assert b["event"] is None, "the worker that lost the CAS must not emit an event"
    assert len(db.monitoring_events.rows) == 1, "one transition, one event row"
    assert len(dispatched) == 1, "one transition, one page"


@pytest.mark.anyio
async def test_concurrent_retry_sweeps_dispatch_each_event_once(monkeypatch):
    """A peer retry sweep must not re-page an event another sweep is sending.

    The claim is a short lease on the row, not a compare-and-set on
    ``notify_attempts``: a CAS would still let the peer match the value the
    first worker wrote and dispatch a second copy.
    """
    db = _Db()
    db.monitoring_events.rows = [{
        "_id": "evt1", "check_id": "c1", "target": "8.8.8.8",
        "at": NOW - timedelta(minutes=5), "from": "up", "to": "down",
        "notified": False, "notify_attempts": 0,
    }]

    started = asyncio.Event()
    release = asyncio.Event()
    dispatched = []

    async def slow_dispatch(db, *, check, event):
        dispatched.append(event["_id"])
        started.set()
        await release.wait()
        return ["email:ops@example.test"]

    monkeypatch.setattr(monitoring, "dispatch_monitoring_alert", slow_dispatch)

    first = asyncio.create_task(
        monitoring.retry_undelivered_monitoring_alerts(db, now=NOW))
    await asyncio.wait_for(started.wait(), timeout=5)  # first sweep holds the claim
    # If the claim were missing, the peer sweep would enter ``slow_dispatch``
    # too and block on ``release`` forever — a hung test, not a red one.  The
    # timeout turns that regression into a clean failure.
    second = await asyncio.wait_for(
        monitoring.retry_undelivered_monitoring_alerts(db, now=NOW), timeout=5)
    release.set()
    await asyncio.wait_for(first, timeout=5)

    assert dispatched == ["evt1"], "the event must be paged exactly once"
    assert second["sent"] == 0, "the peer sweep must not report a delivery it did not make"
    assert db.monitoring_events.rows[0]["notified"] is True
    assert db.monitoring_events.rows[0]["notify_attempts"] == 1


@pytest.mark.anyio
async def test_retry_claim_expires_so_a_dead_worker_does_not_block_delivery(monkeypatch):
    """A claim left behind by a crashed worker must not park the event forever."""
    db = _Db()
    db.monitoring_events.rows = [{
        "_id": "evt1", "check_id": "c1", "target": "8.8.8.8",
        "at": NOW - timedelta(minutes=5), "from": "up", "to": "down",
        "notified": False, "notify_attempts": 1,
        # Claimed by a worker that died before it could dispatch or release.
        "notify_claimed_until": NOW - timedelta(minutes=2),
    }]
    monkeypatch.setattr(monitoring, "dispatch_monitoring_alert",
                        _stub_dispatch(["email:ops@example.test"]))

    out = await monitoring.retry_undelivered_monitoring_alerts(db, now=NOW)

    assert out["sent"] == 1
    assert db.monitoring_events.rows[0]["notified"] is True


@pytest.mark.anyio
async def test_failed_event_insert_rolls_back_confirmed_state(monkeypatch):
    """A failed event write must not silently swallow the transition.

    ``probe_target`` commits the CAS on ``monitoring_check_state`` before it
    writes the event row.  If the event insert then fails, and the confirmed
    state were left at ``down``, the next probe would compare against ``down``,
    see no transition, and never page the outage — a silent alert loss.  The
    fix reverts the confirmed state so the NEXT probe re-observes the same
    up->down transition and records it.
    """
    db = _Db()
    db.monitoring_check_state.rows = [
        {"check_id": "c1", "status": "up", "confirmed_status": "up",
         "consecutive_failures": 0}]
    monkeypatch.setattr(monitoring, "run_ping", _ping(up=False))

    dispatched = []

    async def counting_dispatch(db, *, check, event):
        dispatched.append(event["_id"])
        return ["email:ops@example.test"]

    monkeypatch.setattr(monitoring, "dispatch_monitoring_alert", counting_dispatch)

    # Fail the FIRST event insert (simulating a transient Mongo write error),
    # then let subsequent inserts succeed.
    real_insert = db.monitoring_events.insert_one
    fails = {"remaining": 1}

    async def flaky_insert(doc):
        if fails["remaining"] > 0:
            fails["remaining"] -= 1
            raise RuntimeError("simulated transient insert failure")
        return await real_insert(doc)

    db.monitoring_events.insert_one = flaky_insert

    first = await monitoring.probe_target(db, target="8.8.8.8", check_id="c1",
                                          owner="host:1", retries=0)
    # First probe: event insert failed, so no event, no dispatch, and the
    # confirmed state must be rolled back to ``up`` so the transition survives.
    assert first["event"] is None
    assert len(db.monitoring_events.rows) == 0
    assert len(dispatched) == 0
    assert db.monitoring_check_state.rows[0]["confirmed_status"] == "up", \
        "confirmed state must be rolled back so the transition is not lost"

    second = await monitoring.probe_target(db, target="8.8.8.8", check_id="c1",
                                           owner="host:1", retries=0)
    # Second probe re-observes up->down and records it this time.
    assert second["event"] == "down"
    assert len(db.monitoring_events.rows) == 1
    assert len(dispatched) == 1


@pytest.mark.anyio
async def test_claim_is_renewed_while_a_slow_dispatch_runs(monkeypatch):
    """The retry claim must be extended for as long as the dispatch runs.

    A fixed 30s lease is not enough: ``dispatch_monitoring_alert`` walks up to
    50 channels sequentially and one unreachable SMTP host costs the 15s
    ``smtplib`` timeout, so a slow storm outlives the lease and a peer sweep
    would re-claim the row and page a second time.  The heartbeat keeps pushing
    ``notify_claimed_until`` forward until the dispatch returns.
    """
    db = _Db()
    db.monitoring_events.rows = [{
        "_id": "evt1", "check_id": "c1", "target": "8.8.8.8",
        "at": NOW - timedelta(minutes=5), "from": "up", "to": "down",
        "notified": False, "notify_attempts": 0,
    }]

    # Short lease + fast heartbeat so the test finishes in milliseconds.
    monkeypatch.setattr(monitoring, "_NOTIFY_CLAIM_LEASE", timedelta(seconds=0.2))
    monkeypatch.setattr(monitoring, "_NOTIFY_CLAIM_RENEW_SECONDS", 0.02)

    async def slow_dispatch(db, *, check, event):
        await asyncio.sleep(0.3)  # outlives the initial 0.2s lease
        return ["email:ops@example.test"]

    monkeypatch.setattr(monitoring, "dispatch_monitoring_alert", slow_dispatch)

    await monitoring.retry_undelivered_monitoring_alerts(db, now=NOW)

    # Every renewal writes notify_claimed_until for our claim token; without the
    # heartbeat there would be exactly one such write (the initial claim).
    # Note: the initial claim uses the injected ``now`` while renewals use the
    # real clock, so the two are NOT comparable — compare renewals among
    # themselves instead (they must repeat and advance on their own clock).
    leases = [
        u["$set"]["notify_claimed_until"]
        for _q, u, _up in db.monitoring_events.updates
        if isinstance(u.get("$set"), dict) and "notify_claimed_until" in u["$set"]
    ]
    renewals = leases[1:]  # first write is the initial claim
    assert len(renewals) > 2, f"claim was not renewed during dispatch: {leases}"
    assert all(b > a for a, b in zip(renewals, renewals[1:])), \
        f"renewals must advance the lease forward: {renewals}"
    assert db.monitoring_events.rows[0]["notified"] is True


@pytest.mark.anyio
async def test_release_does_not_clobber_a_peer_claim(monkeypatch):
    """Releasing must be scoped to our own claim token.

    If our lease lapsed and a peer legitimately re-claimed the row, our release
    write must not match it — otherwise we would free the peer's claim and let a
    third sweep page again.
    """
    db = _Db()
    db.monitoring_events.rows = [{
        "_id": "evt1", "check_id": "c1", "target": "8.8.8.8",
        "at": NOW - timedelta(minutes=5), "from": "up", "to": "down",
        "notified": False, "notify_attempts": 0,
    }]
    monkeypatch.setattr(monitoring, "dispatch_monitoring_alert",
                        _stub_dispatch(["email:ops@example.test"]))

    real_update = db.monitoring_events.update_one

    async def peer_steals_claim(query, update, upsert=False):
        # Simulate a peer taking the claim over between our claim and release.
        if isinstance(update.get("$set"), dict) and "notify_attempts" in update["$set"]:
            db.monitoring_events.rows[0]["notify_claim_token"] = "peer-token"
        return await real_update(query, update, upsert)

    db.monitoring_events.update_one = peer_steals_claim

    await monitoring.retry_undelivered_monitoring_alerts(db, now=NOW)

    assert db.monitoring_events.rows[0]["notify_claim_token"] == "peer-token", \
        "our release must not unset a claim owned by a peer"
