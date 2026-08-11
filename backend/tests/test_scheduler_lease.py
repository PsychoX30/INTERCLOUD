"""Mongo-backed scheduler lease tests.

APScheduler is an in-process singleton; with multiple Uvicorn workers each
process starts its own scheduler.  A shared Mongo lease must ensure only one
worker actually executes the scheduled work at any given time.
"""
import asyncio
import ast
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pymongo import ReturnDocument


class FakeLeaseCollection:
    """Minimal in-memory async collection backing scheduler leases.

    Mirrors the subset of Motor/PyMongo semantics used by
    :func:`portal.emails.acquire_scheduler_lease`.
    """

    def __init__(self):
        self._docs = {}

    def _matches(self, doc, filter):
        if doc is None:
            return False
        or_clauses = filter.get("$or")
        if not or_clauses:
            return True
        now = datetime.now(timezone.utc)
        for clause in or_clauses:
            if clause.get("owner") == doc.get("owner"):
                return True
            expiry_op = clause.get("expires_at", {})
            if "$lte" in expiry_op and doc.get("expires_at") <= expiry_op["$lte"]:
                return True
            if clause.get("owner") is None and doc.get("owner") is None:
                return True
        return False

    async def find_one_and_update(self, filter, update, *, upsert=False,
                                  return_document=ReturnDocument.BEFORE):
        _id = filter.get("_id")
        existing = self._docs.get(_id)
        set_fields = update.get("$set", {})

        if not self._matches(existing, filter):
            if existing is not None and upsert:
                from pymongo.errors import DuplicateKeyError
                raise DuplicateKeyError("_id collision on upsert")
            if not upsert:
                return None
            existing = {"_id": _id}

        previous = existing.copy()
        new_doc = {**existing, **set_fields}
        self._docs[_id] = new_doc
        return new_doc if return_document == ReturnDocument.AFTER else previous

    async def find_one(self, filter):
        doc = self._docs.get(filter.get("_id"))
        return None if doc is None else doc.copy()

    async def update_one(self, filter, update):
        _id = filter.get("_id")
        doc = self._docs.get(_id)
        if doc is None:
            return None
        if filter.get("owner") is not None and doc.get("owner") != filter.get("owner"):
            return None
        set_fields = update.get("$set", {})
        self._docs[_id] = {**doc, **set_fields}
        return None


class FakeDB:
    def __init__(self):
        self.scheduler_leases = FakeLeaseCollection()


@pytest.fixture
def db():
    return FakeDB()


@pytest.mark.asyncio
async def test_acquire_lease_wins_when_empty(db):
    from portal.emails import acquire_scheduler_lease
    ok, owner = await acquire_scheduler_lease(db, lease_id="test_lease",
                                              owner="worker-a", ttl_seconds=60)
    assert ok is True
    assert owner == "worker-a"


@pytest.mark.asyncio
async def test_second_worker_loses_while_lease_valid(db):
    from portal.emails import acquire_scheduler_lease
    await acquire_scheduler_lease(db, lease_id="test_lease",
                                  owner="worker-a", ttl_seconds=60)
    ok, owner = await acquire_scheduler_lease(db, lease_id="test_lease",
                                              owner="worker-b", ttl_seconds=60)
    assert ok is False
    assert owner == "worker-a"


@pytest.mark.asyncio
async def test_expired_lease_can_be_stolen(db):
    from portal.emails import acquire_scheduler_lease
    await acquire_scheduler_lease(db, lease_id="test_lease",
                                  owner="worker-a", ttl_seconds=-1)
    ok, owner = await acquire_scheduler_lease(db, lease_id="test_lease",
                                              owner="worker-b", ttl_seconds=60)
    assert ok is True
    assert owner == "worker-b"


@pytest.mark.asyncio
async def test_renew_lease_by_same_owner(db):
    from portal.emails import acquire_scheduler_lease
    await acquire_scheduler_lease(db, lease_id="test_lease",
                                  owner="worker-a", ttl_seconds=60)
    first = db.scheduler_leases._docs["test_lease"]["expires_at"]
    await asyncio.sleep(0.01)
    ok, owner = await acquire_scheduler_lease(db, lease_id="test_lease",
                                              owner="worker-a", ttl_seconds=120)
    assert ok is True
    assert owner == "worker-a"
    assert db.scheduler_leases._docs["test_lease"]["expires_at"] > first


@pytest.mark.asyncio
async def test_run_with_lease_executes_when_acquired(db):
    from portal.emails import run_scheduled_with_lease
    calls = []
    async def job():
        calls.append("ran")
        return {"swept": 3}
    result = await run_scheduled_with_lease(
        db, lease_id="job_x", owner="worker-a", ttl_seconds=60, label="job_x", job=job)
    assert result == {"swept": 3}
    assert calls == ["ran"]


@pytest.mark.asyncio
async def test_run_with_lease_skips_when_other_owner_holds(db):
    from portal.emails import acquire_scheduler_lease, run_scheduled_with_lease
    await acquire_scheduler_lease(db, lease_id="job_x", owner="worker-a", ttl_seconds=60)
    calls = []
    async def job():
        calls.append("ran")
    result = await run_scheduled_with_lease(
        db, lease_id="job_x", owner="worker-b", ttl_seconds=60, label="job_x", job=job)
    assert result == {"status": "skipped", "reason": "lease_held", "owner": "worker-a"}
    assert calls == []


@pytest.mark.asyncio
async def test_run_with_lease_releases_after_job(db):
    from portal.emails import run_scheduled_with_lease
    async def job():
        pass
    await run_scheduled_with_lease(
        db, lease_id="job_x", owner="worker-a", ttl_seconds=60, label="job_x", job=job)
    doc = db.scheduler_leases._docs.get("job_x")
    assert doc is None or doc.get("owner") is None


@pytest.mark.asyncio
async def test_run_with_lease_allows_same_worker_reentry(db):
    from portal.emails import run_scheduled_with_lease
    calls = []
    async def job():
        calls.append("ran")
    await run_scheduled_with_lease(
        db, lease_id="job_x", owner="worker-a", ttl_seconds=60, label="job_x", job=job)
    await run_scheduled_with_lease(
        db, lease_id="job_x", owner="worker-a", ttl_seconds=60, label="job_x", job=job)
    assert calls == ["ran", "ran"]


@pytest.mark.asyncio
async def test_run_with_lease_releases_even_on_exception(db):
    from portal.emails import run_scheduled_with_lease
    async def job():
        raise RuntimeError("boom")
    with pytest.raises(RuntimeError, match="boom"):
        await run_scheduled_with_lease(
            db, lease_id="job_x", owner="worker-a", ttl_seconds=60, label="job_x", job=job)
    doc = db.scheduler_leases._docs.get("job_x")
    assert doc is None or doc.get("owner") is None


@pytest.mark.asyncio
async def test_run_with_lease_prevents_overlap_in_same_process(db):
    from portal.emails import run_scheduled_with_lease
    started = asyncio.Event()
    gate = asyncio.Event()
    calls = []

    async def slow_job():
        started.set()
        calls.append("start")
        await gate.wait()
        calls.append("end")

    task = asyncio.create_task(run_scheduled_with_lease(
        db, lease_id="job_x", owner="worker-a", ttl_seconds=60,
        label="job_x", job=slow_job))
    await started.wait()

    # Second call in the same process must skip while first is running,
    # even though the Mongo lease is available.
    result = await run_scheduled_with_lease(
        db, lease_id="job_x", owner="worker-a", ttl_seconds=60,
        label="job_x", job=slow_job)
    assert result == {"status": "skipped", "reason": "in_progress"}
    assert calls == ["start"]

    gate.set()
    await task
    assert calls == ["start", "end"]


@pytest.mark.asyncio
async def test_run_with_lease_reserves_label_before_waiting_for_mongo(db, monkeypatch):
    """Concurrent ticks must not both start acquisition with the same owner."""
    import portal.emails as emails

    emails._running_jobs.clear()
    entered = asyncio.Event()
    release = asyncio.Event()
    acquisitions = []

    async def delayed_acquire(*_args, **_kwargs):
        acquisitions.append("acquire")
        if len(acquisitions) == 1:
            entered.set()
            await release.wait()
        return True, "worker-a"

    monkeypatch.setattr(emails, "acquire_scheduler_lease", delayed_acquire)

    async def job():
        return "ran"

    first = asyncio.create_task(emails.run_scheduled_with_lease(
        db, lease_id="job_x", owner="worker-a", ttl_seconds=60, label="job_x", job=job))
    await entered.wait()
    try:
        second = await asyncio.wait_for(
            emails.run_scheduled_with_lease(
                db, lease_id="job_x", owner="worker-a", ttl_seconds=60,
                label="job_x", job=job,
            ),
            timeout=0.1,
        )
        assert second == {"status": "skipped", "reason": "in_progress"}
        assert acquisitions == ["acquire"]
    finally:
        release.set()
        await first


@pytest.mark.asyncio
async def test_run_with_lease_renews_while_a_long_job_is_running(db, monkeypatch):
    """A job that outlives one TTL must keep its cross-worker lease alive."""
    import portal.emails as emails

    emails._running_jobs.clear()
    acquired = []
    original_acquire = emails.acquire_scheduler_lease

    async def tracking_acquire(*args, **kwargs):
        acquired.append((args, kwargs))
        return await original_acquire(*args, **kwargs)

    monkeypatch.setattr(emails, "acquire_scheduler_lease", tracking_acquire)
    started = asyncio.Event()
    release = asyncio.Event()

    async def slow_job():
        started.set()
        await release.wait()
        return "done"

    task = asyncio.create_task(emails.run_scheduled_with_lease(
        db, lease_id="job_x", owner="worker-a", ttl_seconds=1,
        renewal_interval_seconds=0.01, label="job_x", job=slow_job))
    await started.wait()
    await asyncio.sleep(0.03)
    release.set()
    assert await task == "done"
    assert len(acquired) >= 2


def test_start_scheduler_wires_every_sweep_through_lease():
    """Every scheduled operation must cross the Mongo lease boundary."""
    source = Path("portal/emails.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    start = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "start_scheduler"
    )
    scheduled_calls = {
        "run_invoice_reminder_sweep",
        "run_renewal_invoice_sweep",
        "run_noc_probe_sweep",
        "run_domain_expiry_sweep",
        "run_ddos_detection_sweep",
        "run_traffic_sample_sweep",
        "run_monthly_report",
        "run_weekly_summary",
        "run_health_alert_sweep",
        "run_noc_probe_retention",
        "run_mongodump",
    }
    callback_nodes = {
        node.name: node
        for node in ast.walk(start)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name.endswith("_tick")
    }
    direct_calls = []
    for callback_name, callback in callback_nodes.items():
        for call in (node for node in ast.walk(callback) if isinstance(node, ast.Call)):
            if isinstance(call.func, ast.Name) and call.func.id in scheduled_calls:
                direct_calls.append((callback_name, call.func.id))
    assert direct_calls == [], f"scheduled operations bypass lease: {direct_calls}"

    leased_labels = {
        call.args[0].value
        for call in ast.walk(start)
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Name)
        and call.func.id == "_leased"
        and call.args
        and isinstance(call.args[0], ast.Constant)
    }
    assert leased_labels == {
        "invoice", "renewal", "noc", "domain", "ddos", "traffic",
        "monthly_report", "weekly_summary", "health_alert",
        "noc_retention", "monitoring", "backup",
    }

    registrations = [
        call for call in ast.walk(start)
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Attribute)
        and call.func.attr == "add_job"
    ]
    assert registrations
    for call in registrations:
        keywords = {keyword.arg: keyword.value for keyword in call.keywords}
        assert "id" in keywords
        assert isinstance(keywords.get("max_instances"), ast.Constant)
        assert keywords["max_instances"].value == 1
        assert isinstance(keywords.get("coalesce"), ast.Constant)
        assert keywords["coalesce"].value is True


def test_start_scheduler_registers_guarded_unique_jobs(monkeypatch):
    """Every APScheduler registration must have collision controls and a lease."""
    import portal.emails as emails

    class FakeScheduler:
        def __init__(self, **kwargs):
            self.jobs = []
            self.started = False

        def add_job(self, func, trigger=None, **kwargs):
            self.jobs.append((func, trigger, kwargs))

        def start(self):
            self.started = True

    fake = FakeScheduler()
    monkeypatch.setattr(emails, "_scheduler", None)
    monkeypatch.setattr(
        "apscheduler.schedulers.asyncio.AsyncIOScheduler",
        lambda **kwargs: fake,
    )

    async def initial_fake_run(*args, **kwargs):
        return {"status": "skipped", "reason": "test"}

    monkeypatch.setattr(emails, "run_scheduled_with_lease", initial_fake_run)
    result = emails.start_scheduler(object())

    assert result is fake
    assert fake.started is True
    assert len(fake.jobs) == 17
    ids = [kwargs.get("id") for _, _, kwargs in fake.jobs]
    assert all(ids)
    assert len(ids) == len(set(ids))
    assert all(kwargs.get("max_instances") == 1 for _, _, kwargs in fake.jobs)
    assert all(kwargs.get("coalesce") is True for _, _, kwargs in fake.jobs)

    # Verify every callback goes through the lease wrapper by exercising it.
    import asyncio
    lease_call_seen = []

    async def fake_run(*args, **kwargs):
        lease_call_seen.append(kwargs["label"])
        return {"status": "skipped", "reason": "test"}

    monkeypatch.setattr(
        emails, "run_scheduled_with_lease", fake_run)

    for callback, _, _ in fake.jobs:
        coro = callback()
        try:
            if asyncio.iscoroutine(coro):
                loop = asyncio.new_event_loop()
                try:
                    loop.run_until_complete(coro)
                finally:
                    loop.close()
        except TypeError:
            # wrapper returns coroutine only when invoked - some callbacks
            # may be plain callables; call() handles both shapes.
            callback()

    expected_labels = {
        "invoice", "renewal", "noc", "domain", "ddos", "traffic",
        "monthly_report", "weekly_summary", "health_alert",
        "noc_retention", "monitoring", "backup",
    }
    assert expected_labels.issubset(set(lease_call_seen)), (
        f"missing lease labels: {expected_labels - set(lease_call_seen)}")
