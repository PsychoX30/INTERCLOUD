"""Contract tests for stranded-service reconciliation (2026-11-16).

Defect reproduced against live production before this file existed.

`provision.py:586` creates a service with `status = "pending"` whenever
automated provisioning did not complete:

    "status": "active" if cfg.get("provision_status") == "provisioned" else "pending"

Every category needing NOC/DC work (dedicated, colocation, interconnect,
firewall, lease) and any hosting order whose WHM server is unreachable lands
there. Nothing ever promotes it, because:

  * `run_renewal_invoice_sweep` filters `status == "active"`  -> never billed
  * `_suspend_for_invoice`      filters `status == "active"`  -> never suspended
  * no scheduler job promotes `pending` -> `active`

Production proof at the time: 3 services stuck `pending` for 38-51 days, each
backed by a PAID invoice, and zero invoices ever generated for any of them. The
client paid, received a dashboard row, and was then billed nothing forever.

Known limitation of this suite: `_FakeCursor` has no `.sort()`, so the tests
exercise the sweep's selection logic, not its ordering. The sweep does not sort,
so that is not a gap in what is being proven here.

Written with plain `asyncio.run`: the prod venv has no pytest-asyncio.
"""
import asyncio
import datetime as dt
import re

import pytest
from bson import ObjectId


NOW = dt.datetime(2026, 12, 1, 12, 0, tzinfo=dt.timezone.utc)


def _day(off: int) -> str:
    return (NOW.date() + dt.timedelta(days=off)).isoformat()


class _FakeCursor:
    def __init__(self, docs):
        self._docs = list(docs)

    def __aiter__(self):
        self._it = iter(self._docs)
        return self

    async def __anext__(self):
        try:
            return next(self._it)
        except StopIteration:
            raise StopAsyncIteration


class _Result:
    def __init__(self, modified=0, matched=0):
        self.modified_count = modified
        self.matched_count = matched
        self.inserted_id = ObjectId()


def _match(doc, query):
    """Subset of Mongo semantics: equality, $in, $ne, $gte, $lte, $regex, $or."""
    for k, v in query.items():
        if k == "$or":
            if not any(_match(doc, sub) for sub in v):
                return False
            continue
        val = doc.get(k)
        if isinstance(v, dict):
            if "$in" in v and val not in v["$in"]:
                return False
            if "$nin" in v and val in v["$nin"]:
                return False
            if "$ne" in v and val == v["$ne"]:
                return False
            if "$gte" in v:
                if val is None or val < v["$gte"]:
                    return False
            if "$lte" in v:
                if val is None or val > v["$lte"]:
                    return False
            if "$regex" in v:
                if val is None:
                    return False
                flags = re.I if "i" in str(v.get("$options", "")) else 0
                if not re.search(v["$regex"], str(val), flags):
                    return False
        elif val != v:
            return False
    return True


class _Collection:
    def __init__(self, docs=None):
        self.docs = list(docs or [])
        self.updates = []

    def find(self, query=None, *a, **kw):
        query = query or {}
        return _FakeCursor([d for d in self.docs if _match(d, query)])

    async def find_one(self, query=None, *a, **kw):
        query = query or {}
        for d in self.docs:
            if _match(d, query):
                return d
        return None

    async def insert_one(self, doc):
        doc = dict(doc)
        doc.setdefault("_id", ObjectId())
        self.docs.append(doc)
        r = _Result()
        r.inserted_id = doc["_id"]
        return r

    async def count_documents(self, query=None, *a, **kw):
        query = query or {}
        return len([d for d in self.docs if _match(d, query)])

    async def update_one(self, query, update):
        for d in self.docs:
            if _match(d, query):
                for k, v in (update.get("$set") or {}).items():
                    d[k] = v
                for k in (update.get("$unset") or {}):
                    d.pop(k, None)
                self.updates.append((query, update))
                return _Result(modified=1, matched=1)
        return _Result()

    async def update_many(self, query, update):
        n = 0
        for d in self.docs:
            if _match(d, query):
                for k, v in (update.get("$set") or {}).items():
                    d[k] = v
                for k in (update.get("$unset") or {}):
                    d.pop(k, None)
                n += 1
        return _Result(modified=n, matched=n)


class _FakeDB:
    def __init__(self, **collections):
        self.collections = collections

    def __getattr__(self, name):
        return self.collections.setdefault(name, _Collection())


@pytest.fixture
def em(monkeypatch):
    from portal import emails as _em

    async def _no_send(*a, **kw):
        return {"status": "sent"}

    monkeypatch.setattr(_em, "send_via_template", _no_send)
    return _em


def _db(*, svc_status="pending", start=None, order_status="provisioning",
        invoice_status="paid", next_renewal=None, link="service",
        price=15000.0, order_missing=False):
    """A world with exactly one service, one order and one invoice."""
    uid = ObjectId()
    sid = ObjectId()
    oid = ObjectId()
    iid = ObjectId()

    svc = {
        "_id": sid, "user_id": uid, "name": "Hosting - Client",
        "status": svc_status,
        "start_date": start if start is not None else _day(-60),
        "next_renewal": next_renewal if next_renewal is not None else _day(-40),
        "price_monthly": price, "auto_renew": True,
        "order_id": str(oid),
    }
    orders = []
    if not order_missing:
        orders.append({"_id": oid, "user_id": uid, "status": order_status,
                       "invoice_id": iid if link == "order" else ObjectId()})

    inv = {"_id": iid, "user_id": uid, "number": "INV-T-1",
           "status": invoice_status, "total": price}
    if link == "service":
        inv["service_id"] = str(sid)

    return _FakeDB(
        users=_Collection([{"_id": uid, "email": "c@e.test", "name": "C"}]),
        services=_Collection([svc]),
        orders=_Collection(orders),
        invoices=_Collection([inv]),
        notifications=_Collection(),
        audit_logs=_Collection(),
        settings=_Collection(),
    ), sid, uid


# --------------------------------------------------------------- the defect

def test_paid_started_pending_service_is_promoted(em):
    """The reported defect: paid, started, still `pending` -> must be `active`."""
    db, sid, _ = _db()
    out = asyncio.run(em.run_stranded_service_sweep(db, now=NOW))
    svc = asyncio.run(db.services.find_one({"_id": sid}))
    assert out["promoted"] == 1, out
    assert svc["status"] == "active", svc["status"]


def test_reason_recorded(em):
    db, sid, _ = _db()
    asyncio.run(em.run_stranded_service_sweep(db, now=NOW))
    svc = asyncio.run(db.services.find_one({"_id": sid}))
    assert svc["activated_reason"] == "stranded_pending_paid_reconciled"
    assert svc["activated_at"]


def test_promotion_is_idempotent(em):
    """A second sweep must promote nothing: the service no longer matches."""
    db, sid, _ = _db()
    first = asyncio.run(em.run_stranded_service_sweep(db, now=NOW))
    second = asyncio.run(em.run_stranded_service_sweep(db, now=NOW))
    assert first["promoted"] == 1
    assert second["promoted"] == 0, "re-promoted an already-active service"


def test_promoted_service_becomes_visible_to_renewal_sweep(em):
    """The whole point: after promotion the renewal query can select it."""
    db, sid, _ = _db(next_renewal=_day(-5))
    asyncio.run(em.run_stranded_service_sweep(db, now=NOW))
    n = asyncio.run(db.services.count_documents(
        {"status": "active", "auto_renew": {"$ne": False},
         "next_renewal": {"$gt": "", "$lte": _day(7)}}))
    assert n == 1, "promoted service is still invisible to the renewal sweep"


def test_stale_next_renewal_is_reseeded_and_gap_recorded(em):
    """No silent back-billing; the old date is preserved for the record."""
    db, sid, _ = _db(next_renewal=_day(-400))
    asyncio.run(em.run_stranded_service_sweep(db, now=NOW))
    svc = asyncio.run(db.services.find_one({"_id": sid}))
    assert svc["next_renewal"] == NOW.date().isoformat(), \
        "an overdue service must be billable now, not in 30 days"
    assert svc["stranded_gap_detected"] == _day(-400)


def test_future_next_renewal_is_left_alone(em):
    """A still-valid renewal date must not be rewritten."""
    future = _day(20)
    db, sid, _ = _db(next_renewal=future)
    asyncio.run(em.run_stranded_service_sweep(db, now=NOW))
    svc = asyncio.run(db.services.find_one({"_id": sid}))
    assert svc["next_renewal"] == future


def test_audit_row_written(em):
    """A flip that changes what someone is billed must be explainable."""
    db, _, _ = _db()
    asyncio.run(em.run_stranded_service_sweep(db, now=NOW))
    rows = db.audit_logs.docs
    assert len(rows) == 1, "no audit row for an automatic activation"
    assert rows[0]["action"] == "service.auto_activate"
    assert rows[0]["previous_status"] == "pending"


def test_client_notified(em):
    db, _, uid = _db()
    asyncio.run(em.run_stranded_service_sweep(db, now=NOW))
    assert db.notifications.docs, "client was never told the service is active"
    assert db.notifications.docs[0]["type"] == "service_activated"


def test_invoice_linked_via_order_id_is_accepted(em):
    """Not every invoice carries service_id; some carry the order id."""
    db, sid, _ = _db(link="order")
    out = asyncio.run(em.run_stranded_service_sweep(db, now=NOW))
    if out["promoted"] == 0:
        # The order-linked invoice must be reachable by the same lookup.
        inv = asyncio.run(db.invoices.find_one({"status": "paid"}))
        order = asyncio.run(db.orders.find_one({}))
        assert inv["_id"] == order["invoice_id"], "fixture did not link them"
    assert out["promoted"] == 1, out


# ------------------------------------------------- the guards (negative cases)

def test_unpaid_service_is_never_promoted(em):
    """Billing someone we never collected from is worse than the bug."""
    db, sid, _ = _db(invoice_status="unpaid")
    out = asyncio.run(em.run_stranded_service_sweep(db, now=NOW))
    svc = asyncio.run(db.services.find_one({"_id": sid}))
    assert svc["status"] == "pending", "unpaid service was activated"
    assert out["promoted"] == 0
    assert out["skipped"] == 1


def test_service_not_yet_started_is_skipped(em):
    db, sid, _ = _db(start=_day(10))
    out = asyncio.run(em.run_stranded_service_sweep(db, now=NOW))
    assert out["promoted"] == 0
    assert asyncio.run(db.services.find_one({"_id": sid}))["status"] == "pending"


def test_cancelled_order_is_not_resurrected(em):
    db, sid, _ = _db(order_status="cancelled")
    out = asyncio.run(em.run_stranded_service_sweep(db, now=NOW))
    assert out["promoted"] == 0, "revived a cancelled order"
    assert asyncio.run(db.services.find_one({"_id": sid}))["status"] == "pending"


def test_rejected_order_is_not_resurrected(em):
    db, sid, _ = _db(order_status="rejected")
    out = asyncio.run(em.run_stranded_service_sweep(db, now=NOW))
    assert out["promoted"] == 0


def test_already_active_service_is_untouched(em):
    """Never rewrite a service that is already correct."""
    db, sid, _ = _db(svc_status="active")
    out = asyncio.run(em.run_stranded_service_sweep(db, now=NOW))
    assert out["promoted"] == 0
    assert "activated_at" not in asyncio.run(db.services.find_one({"_id": sid}))


def test_suspended_service_is_untouched(em):
    """Suspension is a deliberate state; reconciliation must not undo it."""
    db, sid, _ = _db(svc_status="suspended")
    out = asyncio.run(em.run_stranded_service_sweep(db, now=NOW))
    assert out["promoted"] == 0


def test_missing_order_does_not_crash(em):
    """Deleted orders must not take the sweep down."""
    db, sid, _ = _db(order_missing=True)
    out = asyncio.run(em.run_stranded_service_sweep(db, now=NOW))
    assert out["errors"] == 0
    assert out["promoted"] == 1, "a paid service without an order is still owed billing"


def test_sweep_returns_expected_shape(em):
    db, _, _ = _db()
    out = asyncio.run(em.run_stranded_service_sweep(db, now=NOW))
    for k in ("date", "promoted", "skipped", "errors", "details"):
        assert k in out, f"missing key {k}"
