"""Test untuk perbaikan bug kritis 2026-11-12.

Ditulis dengan `asyncio.run` langsung, bukan `@pytest.mark.asyncio`: venv prod
tidak punya pytest-asyncio (12 test di test_scheduler_lease.py gagal karena itu,
sudah begitu sebelum perubahan ini).
"""
import asyncio
import datetime as dt

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


class _Collection:
    """Subset of the motor Collection API that the sweeps actually use."""

    def __init__(self, docs=None):
        self.docs = list(docs or [])
        self.updates = []

    def _match(self, doc, query):
        for k, v in query.items():
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
            elif val != v:
                return False
        return True

    def find(self, query=None, *a, **kw):
        query = query or {}
        return _FakeCursor([d for d in self.docs if self._match(d, query)])

    async def find_one(self, query=None, *a, **kw):
        query = query or {}
        for d in self.docs:
            if self._match(d, query):
                return d
        return None

    async def insert_one(self, doc):
        self.docs.append(dict(doc))
        return _Result()

    async def update_one(self, query, update):
        for d in self.docs:
            if self._match(d, query):
                for k, v in (update.get("$set") or {}).items():
                    d[k] = v
                for k, v in (update.get("$push") or {}).items():
                    d.setdefault(k, []).append(v)
                self.updates.append((query, update))
                return _Result(modified=1, matched=1)
        return _Result()

    async def update_many(self, query, update):
        n = 0
        for d in self.docs:
            if self._match(d, query):
                for k, v in (update.get("$set") or {}).items():
                    d[k] = v
                n += 1
        return _Result(modified=n, matched=n)


class _FakeDB:
    def __init__(self, **collections):
        self.collections = collections

    def __getattr__(self, name):
        return self.collections.setdefault(name, _Collection())


@pytest.fixture
def sweep_env(monkeypatch):
    """emails module with email delivery stubbed out."""
    from portal import emails as em

    async def _no_send(*a, **kw):
        return {"status": "sent"}

    async def _no_token(*a, **kw):
        return "tok"

    monkeypatch.setattr(em, "send_via_template", _no_send)
    monkeypatch.setattr(em, "ensure_pay_token", _no_token)
    return em


# --------------------------------------------------------------------------- #
# Bug #1 / #4 - suspension must catch up, must respect manual guard
# --------------------------------------------------------------------------- #
def test_suspension_fires_when_tick_was_missed(sweep_env):
    """D+20 (the D+8 tick was missed) must still suspend."""
    em = sweep_env
    uid = ObjectId()
    db = _FakeDB(
        users=_Collection([{"_id": uid, "email": "u@e.test", "name": "U"}]),
        services=_Collection([{"_id": ObjectId(), "user_id": uid, "status": "active",
                               "name": "VPS-1"}]),
        invoices=_Collection([{"_id": ObjectId(), "number": "INV-1", "user_id": uid,
                               "status": "overdue", "due_date": _day(-20)}]),
        email_logs=_Collection(),
        notifications=_Collection(),
        audit_logs=_Collection(),
    )
    out = asyncio.run(em.run_invoice_reminder_sweep(db, now=NOW))
    assert out["services_suspended"] == 1
    assert db.services.docs[0]["status"] == "suspended"
    assert db.notifications.docs, "client must get a suspension notification"
    assert db.audit_logs.docs, "suspension must leave an audit trail"


def test_suspension_is_idempotent(sweep_env):
    """A second sweep must not double-notify or re-suspend."""
    em = sweep_env
    uid = ObjectId()
    db = _FakeDB(
        users=_Collection([{"_id": uid, "email": "u@e.test", "name": "U"}]),
        services=_Collection([{"_id": ObjectId(), "user_id": uid, "status": "active",
                               "name": "VPS-1"}]),
        invoices=_Collection([{"_id": ObjectId(), "number": "INV-1", "user_id": uid,
                               "status": "overdue", "due_date": _day(-20)}]),
        email_logs=_Collection(), notifications=_Collection(), audit_logs=_Collection(),
    )
    asyncio.run(em.run_invoice_reminder_sweep(db, now=NOW))
    n_first = len(db.notifications.docs)
    asyncio.run(em.run_invoice_reminder_sweep(db, now=NOW))
    assert len(db.notifications.docs) == n_first
    assert db.services.docs[0]["status"] == "suspended"


def test_suspension_respects_manual_override(sweep_env):
    em = sweep_env
    uid = ObjectId()
    db = _FakeDB(
        users=_Collection([{"_id": uid, "email": "u@e.test", "name": "U"}]),
        services=_Collection([{"_id": ObjectId(), "user_id": uid, "status": "active",
                               "name": "VPS-1", "suspended_manual": True}]),
        invoices=_Collection([{"_id": ObjectId(), "number": "INV-1", "user_id": uid,
                               "status": "overdue", "due_date": _day(-20)}]),
        email_logs=_Collection(), notifications=_Collection(), audit_logs=_Collection(),
    )
    asyncio.run(em.run_invoice_reminder_sweep(db, now=NOW))
    assert db.services.docs[0]["status"] == "active"


def test_reminders_still_fire_on_exact_day_only(sweep_env):
    """D+3 must NOT suspend, and must not spam every day."""
    em = sweep_env
    uid = ObjectId()
    db = _FakeDB(
        users=_Collection([{"_id": uid, "email": "u@e.test", "name": "U"}]),
        services=_Collection([{"_id": ObjectId(), "user_id": uid, "status": "active",
                               "name": "VPS-1"}]),
        invoices=_Collection([{"_id": ObjectId(), "number": "INV-1", "user_id": uid,
                               "status": "overdue", "due_date": _day(-3)}]),
        email_logs=_Collection(), notifications=_Collection(), audit_logs=_Collection(),
    )
    out = asyncio.run(em.run_invoice_reminder_sweep(db, now=NOW))
    assert out["services_suspended"] == 0
    assert db.services.docs[0]["status"] == "active"
    assert out["fired"]["invoice_overdue_d3"] == 1


# --------------------------------------------------------------------------- #
# Bug #3 - pending_payment orders expire after 14 days, new orders only
# --------------------------------------------------------------------------- #
def test_order_expiry_cancels_and_cancels_unpaid_invoice(sweep_env):
    em = sweep_env
    uid, iid = ObjectId(), ObjectId()
    db = _FakeDB(
        users=_Collection([{"_id": uid, "email": "o@e.test", "name": "O"}]),
        orders=_Collection([{
            "_id": ObjectId(), "user_id": uid, "product_name": "VPS",
            "status": "pending_payment", "invoice_id": iid,
            "expires_at": (NOW - dt.timedelta(days=1)).isoformat(),
        }]),
        invoices=_Collection([{"_id": iid, "status": "unpaid", "user_id": uid}]),
        notifications=_Collection(),
    )
    out = asyncio.run(em.run_order_expiry_sweep(db, now=NOW))
    assert out["cancelled"] == 1
    assert out["invoices_cancelled"] == 1
    assert db.orders.docs[0]["status"] == "cancelled"
    assert db.invoices.docs[0]["status"] == "cancelled"


def test_order_expiry_skips_legacy_orders_without_expires_at(sweep_env):
    """"Khusus order baru": orders predating the field must never be cancelled."""
    em = sweep_env
    uid = ObjectId()
    db = _FakeDB(
        users=_Collection([{"_id": uid, "email": "o@e.test", "name": "O"}]),
        orders=_Collection([{"_id": ObjectId(), "user_id": uid, "status": "pending_payment",
                             "created_at": (NOW - dt.timedelta(days=90)).isoformat()}]),
        notifications=_Collection(),
    )
    out = asyncio.run(em.run_order_expiry_sweep(db, now=NOW))
    assert out["cancelled"] == 0
    assert db.orders.docs[0]["status"] == "pending_payment"


def test_order_expiry_never_cancels_paid_invoice(sweep_env):
    em = sweep_env
    uid, iid = ObjectId(), ObjectId()
    db = _FakeDB(
        users=_Collection([{"_id": uid, "email": "o@e.test", "name": "O"}]),
        orders=_Collection([{"_id": ObjectId(), "user_id": uid, "status": "pending_payment",
                             "invoice_id": iid,
                             "expires_at": (NOW - dt.timedelta(days=2)).isoformat()}]),
        invoices=_Collection([{"_id": iid, "status": "paid", "user_id": uid}]),
        notifications=_Collection(),
    )
    asyncio.run(em.run_order_expiry_sweep(db, now=NOW))
    assert db.invoices.docs[0]["status"] == "paid"


def test_order_expiry_leaves_unexpired_orders_alone(sweep_env):
    em = sweep_env
    uid = ObjectId()
    db = _FakeDB(
        users=_Collection([{"_id": uid, "email": "o@e.test", "name": "O"}]),
        orders=_Collection([{"_id": ObjectId(), "user_id": uid, "status": "pending_payment",
                             "expires_at": (NOW + dt.timedelta(days=5)).isoformat()}]),
        notifications=_Collection(),
    )
    out = asyncio.run(em.run_order_expiry_sweep(db, now=NOW))
    assert out["cancelled"] == 0
