"""Audit trail untuk PUT /admin/invoices/{iid}/status.

Route ini menandai invoice lunas, memicu provisioning server, dan menerapkan
upgrade resource - semuanya memindahkan uang. Sebelum perbaikan, route ini
menulis NOL baris `audit_logs`: tidak ada bukti siapa yang mengubah status.

Test ditulis dengan `asyncio.run` langsung (venv prod tidak punya
pytest-asyncio), mengikuti pola test_critical_billing_fixes.py.

Regression guard: pada kode tanpa audit, `db.audit_logs.docs` kosong dan
`metadata["from"]` tidak pernah ada -> kedua assert gagal.
"""
import asyncio
import datetime as dt

import pytest
from bson import ObjectId


NOW = dt.datetime(2026, 12, 1, 12, 0, tzinfo=dt.timezone.utc).isoformat()


class _Result:
    def __init__(self, modified=0, matched=0):
        self.modified_count = modified
        self.matched_count = matched


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


def _match(doc, query):
    for k, v in query.items():
        val = doc.get(k)
        if isinstance(v, dict):
            if "$ne" in v and val == v["$ne"]:
                return False
            if "$in" in v and val not in v["$in"]:
                return False
            if "$nin" in v and val in v["$nin"]:
                return False
            if "$gte" in v:
                if val is None or val < v["$gte"]:
                    return False
        elif val != v:
            return False
    return True


class _Collection:
    """Subset of motor's Collection API used by this route."""

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

    async def find_one_and_update(self, query, update, *a, **kw):
        for d in self.docs:
            if _match(d, query):
                before = dict(d)
                for k, v in (update.get("$set") or {}).items():
                    d[k] = v
                return before
        return None

    async def update_one(self, query, update, *a, **kw):
        for d in self.docs:
            if _match(d, query):
                for k, v in (update.get("$set") or {}).items():
                    d[k] = v
                return _Result(modified=1, matched=1)
        return _Result()

    async def insert_one(self, doc):
        self.docs.append(dict(doc))
        return _Result()


class _FakeDB:
    def __init__(self, **collections):
        self.collections = collections

    def __getattr__(self, name):
        return self.collections.setdefault(name, _Collection())


class _Req:
    """Minimal Starlette Request stand-in for _extract_request()."""

    class _Client:
        host = "10.9.9.9"

    client = _Client()
    headers = {"user-agent": "pytest-audit/1.0"}


@pytest.fixture
def route_env(monkeypatch):
    """Patch billing module: fake DB + all side-effect helpers."""
    from portal.routes import billing as b

    db = _FakeDB(
        users=_Collection([{"_id": ObjectId(), "email": "cli@e.test", "name": "Client"}]),
        invoices=_Collection(),
        transactions=_Collection(),
        audit_logs=_Collection(),
    )

    calls = {"provision": 0, "upgrade": 0, "ledger": 0}

    async def _get_db():
        return db

    async def _noop_provision(d, inv):
        calls["provision"] += 1

    async def _noop_upgrade(d, inv):
        calls["upgrade"] += 1
        return True

    async def _noop_log_tx(d, **kw):
        calls["ledger"] += 1

    async def _serialize(d, doc):
        return {"id": str(doc["_id"]), "status": doc.get("status")}

    monkeypatch.setattr(b, "_get_db", _get_db)
    monkeypatch.setattr(b, "_provision_order_from_invoice", _noop_provision)
    monkeypatch.setattr(b, "_apply_pending_upgrade", _noop_upgrade)
    monkeypatch.setattr(b, "_log_transaction", _noop_log_tx)
    monkeypatch.setattr(b, "_serialize_invoice", _serialize)

    for name in ("_auto_register_domain", "_apply_domain_renewal",
                 "_apply_domain_transfer", "_provision_ssl_order"):
        async def _noop(d, inv, _n=name):
            return None
        monkeypatch.setattr(b, name, _noop)

    return b, db, calls


def _invoice(status="unpaid", **extra):
    doc = {
        "_id": ObjectId(), "number": "INV-2026-00999",
        "user_id": ObjectId(), "status": status, "total": 250000,
        "order_id": ObjectId(), "payment_method": None,
    }
    doc.update(extra)
    return doc


def _payload(status, method=None):
    from portal.models import InvoiceStatusIn
    return InvoiceStatusIn(status=status, payment_method=method)


# --------------------------------------------------------------------------- #
# The audit row must exist, and must say what changed
# --------------------------------------------------------------------------- #
def test_status_update_writes_audit_row(route_env):
    b, db, _ = route_env
    inv = _invoice("unpaid")
    db.invoices.docs.append(inv)

    asyncio.run(b.admin_update_invoice_status(
        str(inv["_id"]), _payload("paid", "bank_transfer"), _Req(), admin={"id": str(ObjectId()),
                                                                          "email": "adm@e.test",
                                                                          "role": "admin"}))

    assert db.audit_logs.docs, "marking an invoice paid must leave an audit row"
    row = db.audit_logs.docs[0]
    assert row["action"] == "invoice.status_update"
    assert row["category"] == "billing"
    assert row["target_type"] == "invoice"
    assert row["target_id"] == str(inv["_id"])
    assert row["target_label"] == "INV-2026-00999"
    assert row["actor_email"] == "adm@e.test"
    assert row["severity"] == "warning", "money recognised -> warning"
    assert row["metadata"]["from"] == "unpaid"
    assert row["metadata"]["to"] == "paid"
    assert row["metadata"]["just_paid"] is True
    assert row["metadata"]["total"] == 250000.0


def test_audit_records_request_origin(route_env):
    b, db, _ = route_env
    inv = _invoice("unpaid")
    db.invoices.docs.append(inv)

    asyncio.run(b.admin_update_invoice_status(
        str(inv["_id"]), _payload("paid"), _Req(),
        admin={"id": str(ObjectId()), "email": "adm@e.test", "role": "admin"}))

    row = db.audit_logs.docs[0]
    assert row["ip"] == "10.9.9.9"
    assert row["user_agent"] == "pytest-audit/1.0"


def test_non_paid_transition_is_info_not_warning(route_env):
    b, db, _ = route_env
    inv = _invoice("unpaid")
    db.invoices.docs.append(inv)

    asyncio.run(b.admin_update_invoice_status(
        str(inv["_id"]), _payload("cancelled"), _Req(),
        admin={"id": str(ObjectId()), "email": "adm@e.test", "role": "admin"}))

    row = db.audit_logs.docs[0]
    assert row["severity"] == "info", "no funds recognised -> info"
    assert row["metadata"]["from"] == "unpaid"
    assert row["metadata"]["to"] == "cancelled"
    assert row["metadata"]["just_paid"] is False


def test_repeat_paid_is_logged_without_double_provisioning(route_env):
    """Klik ganda: audit tetap tercatat, tapi uang/upgrade tidak diproses 2x."""
    b, db, calls = route_env
    inv = _invoice("paid", paid_at=NOW)
    db.invoices.docs.append(inv)
    admin = {"id": str(ObjectId()), "email": "adm@e.test", "role": "admin"}

    asyncio.run(b.admin_update_invoice_status(str(inv["_id"]), _payload("paid"), _Req(), admin=admin))

    row = db.audit_logs.docs[0]
    assert row["metadata"]["just_paid"] is False, "already paid -> not a new payment"
    assert row["metadata"]["from"] == "paid"
    assert calls["ledger"] == 0, "ledger must not double-count"
    assert calls["upgrade"] == 0
    assert len(db.audit_logs.docs) == 1, "but the attempt is still on record"


def test_missing_invoice_raises_404_and_writes_no_audit(route_env):
    from fastapi import HTTPException
    b, db, _ = route_env
    admin = {"id": str(ObjectId()), "email": "adm@e.test", "role": "admin"}

    with pytest.raises(HTTPException) as ei:
        asyncio.run(b.admin_update_invoice_status(
            str(ObjectId()), _payload("paid"), _Req(), admin=admin))
    assert ei.value.status_code == 404
    assert not db.audit_logs.docs
