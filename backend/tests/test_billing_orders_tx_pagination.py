"""Regression coverage for true server-side admin-list pagination.

The paginated path must apply Mongo cursor ``skip`` and ``limit`` before
serialization, and count using the exact scoped/filter query. Legacy arrays and
page-based envelopes remain available for existing consumers.
"""
from __future__ import annotations

from unittest.mock import AsyncMock

from bson import ObjectId
import pytest

from portal.routes import billing as billing_routes
from portal.routes import orders as orders_routes
from portal.routes import transactions as tx_routes


class _Cursor:
    def __init__(self, rows):
        self.rows = list(rows)
        self.skip_value = 0
        self.limit_value = None

    def sort(self, key, direction=-1):
        self.rows.sort(key=lambda row: row.get(key, ""), reverse=direction == -1)
        return self

    def skip(self, value):
        self.skip_value = value
        return self

    def limit(self, value):
        self.limit_value = value
        return self

    def _sliced(self):
        end = None if self.limit_value is None else self.skip_value + self.limit_value
        return self.rows[self.skip_value:end]

    async def to_list(self, _limit):
        return self._sliced()

    def __aiter__(self):
        self._iterator = iter(self._sliced())
        return self

    async def __anext__(self):
        try:
            return next(self._iterator)
        except StopIteration:
            raise StopAsyncIteration


class _Collection:
    def __init__(self, rows=()):
        self.rows = list(rows)
        self.last_cursor = None
        self.last_count_query = None

    def find(self, query, *_args, **_kwargs):
        self.last_cursor = _Cursor(self._filtered(query))
        return self.last_cursor

    async def count_documents(self, query):
        self.last_count_query = query
        return len(self._filtered(query))

    async def find_one(self, query, *_args, **_kwargs):
        matches = self._filtered(query)
        return matches[0] if matches else None

    async def update_one(self, *_args, **_kwargs):
        return None

    async def update_many(self, *_args, **_kwargs):
        return None

    def _filtered(self, query):
        if not query:
            return list(self.rows)
        result = []
        for row in self.rows:
            matched = True
            for key, value in query.items():
                if key == "$or":
                    matched = any(
                        str(row.get(field, "")).lower().find(condition["$regex"].lower()) >= 0
                        for clause in value
                        for field, condition in clause.items()
                        if "$regex" in condition
                    )
                elif isinstance(value, dict) and "$in" in value:
                    matched = row.get(key) in value["$in"]
                elif isinstance(value, dict) and ("$gte" in value or "$lte" in value):
                    matched = (("$gte" not in value or row.get(key, "") >= value["$gte"])
                               and ("$lte" not in value or row.get(key, "") <= value["$lte"]))
                else:
                    matched = row.get(key) == value
                if not matched:
                    break
            if matched:
                result.append(row)
        return result


class _Db:
    def __init__(self):
        self.invoices = _Collection()
        self.quotations = _Collection()
        self.orders = _Collection()
        self.transactions = _Collection()
        self.users = _Collection()
        self.credit_notes = _Collection()


@pytest.fixture
def db(monkeypatch):
    value = _Db()
    for module in (billing_routes, orders_routes, tx_routes):
        monkeypatch.setattr(module, "_get_db", AsyncMock(return_value=value))
    return value


@pytest.fixture
def staff():
    return {"role": "admin", "email": "admin@example.test"}


def _invoice(i, **overrides):
    user_id = ObjectId()
    row = {"_id": ObjectId(), "user_id": user_id, "number": f"INV-{i:03d}", "total": i * 100,
           "status": "paid" if i % 2 else "unpaid", "due_date": f"2026-09-{i:02d}",
           "created_at": f"2026-08-{i:02d}T00:00:00Z", "items": []}
    row.update(overrides)
    return row


def _quotation(i, **overrides):
    user_id = ObjectId()
    row = {"_id": ObjectId(), "user_id": user_id, "number": f"QTN-{i:03d}", "total": i * 100,
           "status": "draft", "created_at": f"2026-08-{i:02d}T00:00:00Z", "items": []}
    row.update(overrides)
    return row


def _order(i, **overrides):
    row = {"_id": ObjectId(), "user_id": ObjectId(), "product_id": ObjectId(), "product_name": f"Plan {i}",
           "status": "pending", "created_at": f"2026-08-{i:02d}T00:00:00Z", "cart_snapshot": {"total": i * 100}}
    row.update(overrides)
    return row


def _transaction(i, **overrides):
    row = {"_id": ObjectId(), "user_id": ObjectId(), "invoice_id": ObjectId(), "amount": i * 100,
           "method": "bank" if i % 2 else "card", "status": "paid", "created_at": f"2026-08-{i:02d}T00:00:00Z"}
    row.update(overrides)
    return row


@pytest.mark.anyio
async def test_invoices_paginate_uses_cursor_and_count(db, staff):
    db.invoices.rows = [_invoice(i) for i in range(1, 11)]
    result = await billing_routes.admin_list_invoices(staff, skip=3, limit=2, sort="total", order="asc", paginate=True)
    assert result["total"] == 10
    assert [item["total"] for item in result["items"]] == [400, 500]
    assert db.invoices.last_cursor.skip_value == 3
    assert db.invoices.last_cursor.limit_value == 2
    assert db.invoices.last_count_query == {}


@pytest.mark.anyio
async def test_quotations_paginate_and_legacy_page_response(db, staff):
    db.quotations.rows = [_quotation(i) for i in range(1, 6)]
    paginated = await billing_routes.admin_list_quotations(staff, skip=1, limit=2, sort="number", order="asc", paginate=True)
    assert paginated["total"] == 5
    assert [item["number"] for item in paginated["items"]] == ["QTN-002", "QTN-003"]
    assert db.quotations.last_cursor.skip_value == 1
    assert db.quotations.last_cursor.limit_value == 2
    legacy = await billing_routes.admin_list_quotations(staff, page=2, limit=2)
    assert legacy["page"] == 2
    assert len(legacy["items"]) == 2


@pytest.mark.anyio
async def test_orders_paginate_sort_and_legacy_array(db, staff):
    db.orders.rows = [_order(1, total=300), _order(2, total=100), _order(3, total=200)]
    result = await orders_routes.admin_list_orders(staff, limit=2, sort="total", order="asc", paginate=True)
    assert result["total"] == 3
    assert [item["id"] for item in result["items"]] == [str(db.orders.rows[1]["_id"]), str(db.orders.rows[2]["_id"])]
    assert db.orders.last_cursor.limit_value == 2
    legacy = await orders_routes.admin_list_orders(staff)
    assert isinstance(legacy, list)
    assert len(legacy) == 3


@pytest.mark.anyio
async def test_transactions_paginate_filters_cursor_and_legacy_page(db, staff):
    db.transactions.rows = [_transaction(i, status="paid" if i < 5 else "pending") for i in range(1, 7)]
    result = await tx_routes.list_transactions(staff, status="paid", skip=1, limit=2, sort="amount", order="asc", paginate=True)
    assert result["total"] == 4
    assert [item["amount"] for item in result["items"]] == [200.0, 300.0]
    assert db.transactions.last_cursor.skip_value == 1
    assert db.transactions.last_cursor.limit_value == 2
    assert db.transactions.last_count_query == {"status": "paid"}
    legacy = await tx_routes.list_transactions(staff, status="paid", page=2, limit=2)
    assert isinstance(legacy, list)
    assert len(legacy) == 2
