"""Contract test: rejecting an order must close its linked service.

Defect reproduced against live production before this file existed.

`PUT /admin/orders/{oid}/status` with `status="rejected"` closed the linked
invoice (paid -> refunded, else -> cancelled) but left the linked service
untouched. A rejected order therefore stranded a live service on the client's
dashboard: never provisioned, never billable, never expiring.

Found in production: service `6a8fd750…` sat `pending` for 51 days after its
order had been rejected and its invoice `INV-2026-00014` refunded. The client's
dashboard still listed it.

The fix terminates the service inside the same rejection branch. Two details
that are easy to get wrong and are pinned below:

  * the termination must NOT be nested inside the invoice branch — an order can
    carry a service without an invoice, and nesting would skip that case;
  * terminating must be idempotent — re-rejecting an already terminated service
    must not overwrite `terminated_at` or rewrite the reason.

Written with plain `asyncio.run`: the prod venv has no pytest-asyncio.
"""
import asyncio
import datetime as dt
import re

import pytest
from bson import ObjectId

from portal.routes import orders as orders_route
from portal import models as m


NOW = dt.datetime(2026, 12, 1, 12, 0, tzinfo=dt.timezone.utc)


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
    for k, v in query.items():
        val = doc.get(k)
        if isinstance(v, dict):
            if "$in" in v and val not in v["$in"]:
                return False
            if "$ne" in v and val == v["$ne"]:
                return False
        elif val != v:
            return False
    return True


class _Collection:
    def __init__(self, docs=None):
        self.docs = list(docs or [])

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
                for k, v in (update.get("$push") or {}).items():
                    d.setdefault(k, []).append(v)
                return _Result(modified=1, matched=1)
        return _Result()


class _FakeDB:
    def __init__(self, **collections):
        self.collections = collections

    def __getattr__(self, name):
        return self.collections.setdefault(name, _Collection())


@pytest.fixture
def route(monkeypatch):
    """orders route module with its DB accessor pointed at a fake."""

    def _install(db):
        async def _get_db():
            return db
        monkeypatch.setattr(orders_route, "_get_db", _get_db)
        return db

    return _install


def _world(*, order_status="active", svc_status="pending", invoice_status="paid",
           with_invoice=True, with_service=True):
    uid = ObjectId()
    oid = ObjectId()
    sid = ObjectId()
    iid = ObjectId()

    order = {"_id": oid, "user_id": uid, "status": order_status,
             "product_id": ObjectId(), "product_name": "Hosting",
             "provision_log": [], "created_at": NOW.isoformat()}
    if with_invoice:
        order["invoice_id"] = iid
    if with_service:
        order["service_id"] = sid

    svc = {"_id": sid, "user_id": uid, "name": "Hosting - Client",
           "status": svc_status, "auto_renew": True,
           "start_date": "2026-08-27", "next_renewal": "2026-09-26",
           "price_monthly": 5000.0,
           "terminated_at": "2026-01-01T00:00:00+00:00" if svc_status == "terminated" else None,
           "terminated_reason": "already done" if svc_status == "terminated" else None}

    return _FakeDB(
        users=_Collection([{"_id": uid, "email": "c@e.test"}]),
        services=_Collection([svc]),
        orders=_Collection([order]),
        invoices=_Collection([{"_id": iid, "number": "INV-T-1",
                               "status": invoice_status, "total": 5000.0}]),
    ), oid, sid


def _reject(db, oid):
    payload = m.OrderStatusUpdateIn(status="rejected")
    admin = {"id": str(ObjectId()), "email": "admin@e.test", "role": "admin"}
    return asyncio.run(
        orders_route.admin_update_order_status(str(oid), payload, admin))


# --------------------------------------------------------------- the defect

def test_reject_terminates_linked_service(route):
    """The reported defect: rejecting an order left its service alive."""
    db, oid, sid = _world()
    route(db)
    _reject(db, oid)
    svc = asyncio.run(db.services.find_one({"_id": sid}))
    assert svc["status"] == "terminated", svc["status"]


def test_reject_stops_auto_renew(route):
    """A terminated service must not keep renewing."""
    db, oid, sid = _world()
    route(db)
    _reject(db, oid)
    svc = asyncio.run(db.services.find_one({"_id": sid}))
    assert svc["auto_renew"] is False


def test_reject_records_terminated_at_and_reason(route):
    db, oid, sid = _world()
    route(db)
    _reject(db, oid)
    svc = asyncio.run(db.services.find_one({"_id": sid}))
    assert svc.get("terminated_at"), "no timestamp"
    assert svc.get("terminated_reason"), "no reason"


def test_reject_logs_service_termination(route):
    db, oid, sid = _world()
    route(db)
    _reject(db, oid)
    order = asyncio.run(db.orders.find_one({"_id": oid}))
    steps = [e.get("step") for e in (order.get("provision_log") or [])]
    assert "service_terminated_on_reject" in steps, steps


def test_invoice_still_refunded(route):
    """The pre-existing invoice behaviour must not regress."""
    db, oid, sid = _world(invoice_status="paid")
    route(db)
    _reject(db, oid)
    inv = asyncio.run(db.invoices.find_one({}))
    assert inv["status"] == "refunded"


def test_terminates_even_without_an_invoice(route):
    """An order can carry a service and no invoice; that must still be closed."""
    db, oid, sid = _world(with_invoice=False)
    route(db)
    _reject(db, oid)
    svc = asyncio.run(db.services.find_one({"_id": sid}))
    assert svc["status"] == "terminated"


# ------------------------------------------------- idempotency and boundaries

def test_rejecting_twice_does_not_rewrite_terminated_service(route):
    """The first reason must survive a second rejection."""
    db, oid, sid = _world()
    route(db)
    _reject(db, oid)
    first = asyncio.run(db.services.find_one({"_id": sid}))["terminated_at"]
    _reject(db, oid)
    second = asyncio.run(db.services.find_one({"_id": sid}))["terminated_at"]
    assert first == second, "re-rejection overwrote terminated_at"


def test_already_terminated_service_is_left_alone(route):
    db, oid, sid = _world(svc_status="terminated")
    route(db)
    _reject(db, oid)
    svc = asyncio.run(db.services.find_one({"_id": sid}))
    assert svc["terminated_reason"] == "already done", \
        "overwrote an existing termination"


def test_active_status_does_not_terminate(route):
    """Only rejection closes the service."""
    db, oid, sid = _world(svc_status="pending")
    route(db)
    payload = m.OrderStatusUpdateIn(status="provisioning")
    admin = {"id": str(ObjectId()), "email": "admin@e.test", "role": "admin"}
    asyncio.run(orders_route.admin_update_order_status(str(oid), payload, admin))
    svc = asyncio.run(db.services.find_one({"_id": sid}))
    assert svc["status"] == "pending", "non-reject status terminated the service"


def test_order_without_service_does_not_crash(route):
    db, oid, _ = _world(with_service=False)
    route(db)
    _reject(db, oid)
    order = asyncio.run(db.orders.find_one({"_id": oid}))
    assert order["status"] == "rejected"
