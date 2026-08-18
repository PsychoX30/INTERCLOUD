"""Focused tests for transactions pagination migration to true server-side."""

from __future__ import annotations
from unittest.mock import AsyncMock
from bson import ObjectId
import pytest
from portal.routes import transactions as tx_routes


class _TxCursor:
    """Async cursor mock supporting sort, skip, limit, to_list, and async iteration."""
    def __init__(self, rows):
        self.rows = list(rows)
        self._skip = 0
        self._limit = None

    def sort(self, key, direction=-1):
        reverse = direction == -1
        self.rows = sorted(self.rows, key=lambda r: r.get(key, ""), reverse=reverse)
        return self

    def skip(self, n):
        self._skip = n
        return self

    def limit(self, n):
        self._limit = n
        return self

    def _sliced(self):
        start = self._skip or 0
        end = start + (self._limit if self._limit is not None else len(self.rows))
        return self.rows[start:end]

    async def to_list(self, _limit):
        return self._sliced()

    def __aiter__(self):
        self._iter = iter(self._sliced())
        return self

    async def __anext__(self):
        try:
            return next(self._iter)
        except StopIteration:
            raise StopAsyncIteration


class _TxCollection:
    def __init__(self, rows):
        self.rows = rows

    def find(self, query):
        return _TxCursor(self._filtered(query))

    async def count_documents(self, query):
        return len(self._filtered(query))

    def _filtered(self, query):
        if not query:
            return list(self.rows)
        out = []
        for r in self.rows:
            match = True
            for k, v in query.items():
                if k == "$or":
                    # Simplified regex match for test
                    match = any(
                        any(
                            str(r.get(field, "")).lower().find(condition.get("$regex", "").lower()) >= 0
                            for field, condition in clause.items()
                            if isinstance(condition, dict) and "$regex" in condition
                        )
                        for clause in v
                    )
                elif isinstance(v, dict) and "$regex" in v:
                    match = str(r.get(k, "")).lower().find(v["$regex"].lower()) >= 0
                elif isinstance(v, dict) and ("$gte" in v or "$lte" in v):
                    rv = str(r.get(k, ""))
                    if "$gte" in v and not (rv >= v["$gte"]):
                        match = False
                    if "$lte" in v and not (rv <= v["$lte"]):
                        match = False
                elif isinstance(v, dict):
                    # Simple MongoDB operator support for tests ($gte/$lte/$gt/$lt/$in)
                    row_val = r.get(k)
                    if "$gte" in v:
                        match = row_val is not None and row_val >= v["$gte"]
                        if "$lte" in v:
                            match = match and row_val <= v["$lte"]
                        elif "$gt" in v:
                            match = match and row_val > v["$gt"]
                        elif "$lt" in v:
                            match = match and row_val < v["$lt"]
                    elif "$lte" in v:
                        match = row_val is not None and row_val <= v["$lte"]
                        if "$gt" in v:
                            match = match and row_val > v["$gt"]
                        elif "$lt" in v:
                            match = match and row_val < v["$lt"]
                    elif "$gt" in v:
                        match = row_val is not None and row_val > v["$gt"]
                        if "$lt" in v:
                            match = match and row_val < v["$lt"]
                    elif "$lt" in v:
                        match = row_val is not None and row_val < v["$lt"]
                    elif "$in" in v:
                        match = row_val in v["$in"]
                    else:
                        match = row_val == v
                else:
                    match = r.get(k) == v
                if not match:
                    break
            if match:
                out.append(r)
        return out


class _Db:
    def __init__(self):
        self.transactions = _TxCollection([])


@pytest.fixture
def db(monkeypatch):
    value = _Db()
    monkeypatch.setattr(tx_routes, "_get_db", AsyncMock(return_value=value))
    return value


@pytest.fixture
def staff():
    return {"role": "admin", "email": "admin@example.test"}


def _tx(i: int, **overrides):
    base = {
        "_id": ObjectId(),
        "invoice_id": ObjectId(),
        "invoice_number": f"INV-{i:06d}",
        "user_id": ObjectId(),
        "user_name": f"user{i}",
        "customer_name": f"Customer {i}",
        "amount": float(i * 1000),
        "method": "bank_transfer" if i % 2 == 0 else "credit_card",
        "status": "paid" if i % 3 == 0 else "pending",
        "paid_at": f"2026-08-14T{10+i:02d}:00:00Z",
        "verified_at": f"2026-08-14T{10+i:02d}:00:00Z" if i % 4 == 0 else None,
        "verified_by": str(ObjectId()) if i % 4 == 0 else None,
        "invoice_date": f"2026-08-01",
        "due_date": f"2026-08-30",
        "reference": f"REF-{i}",
        "notes": f"Note {i}",
        "source": "auto",
        "created_at": f"2026-08-14T{10+i:02d}:00:00Z",
        "updated_at": f"2026-08-14T{10+i:02d}:00:00Z",
    }
    base.update(overrides)
    return base


# ============================================================
# /admin/transactions
# ============================================================

@pytest.mark.anyio
async def test_transactions_pagination_paginated(db, staff):
    """Transactions: paginate=true returns {items, total, limit, skip}."""
    # Seed more than a page to force pagination
    db.transactions.rows = [_tx(i) for i in range(80)]

    # Page 1: limit 25, skip 0
    res = await tx_routes.list_transactions(
        staff, page=1, limit=25, paginate=True
    )
    assert res["total"] == 80
    assert res["limit"] == 25
    assert res["skip"] == 0
    assert len(res["items"]) == 25
    # newest first (created_at desc)
    assert res["items"][0]["created_at"] > res["items"][-1]["created_at"]

    # Page 2: limit 25, skip 25
    res2 = await tx_routes.list_transactions(
        staff, page=2, limit=25, paginate=True
    )
    assert res2["total"] == 80
    assert res2["skip"] == 25
    assert len(res2["items"]) == 25
    # Ensure different items
    assert res2["items"][0]["id"] != res["items"][0]["id"]


@pytest.mark.anyio
async def test_transactions_backward_compat_array(db, staff):
    """Transactions: default (paginate=false) returns array, not object."""
    db.transactions.rows = [_tx(i) for i in range(3)]
    res = await tx_routes.list_transactions(staff)
    assert isinstance(res, list)
    assert len(res) == 3


@pytest.mark.anyio
async def test_transactions_filters_preserved(db, staff):
    """Transactions: filters work with pagination."""
    db.transactions.rows = [
        _tx(1, status="paid", method="bank_transfer", customer_name="Alice"),
        _tx(2, status="pending", method="credit_card", customer_name="Bob"),
        _tx(3, status="paid", method="bank_transfer", customer_name="Charlie"),
    ]

    # Filter by status
    res = await tx_routes.list_transactions(
        staff, status="paid", paginate=True
    )
    assert res["total"] == 2
    assert len(res["items"]) == 2
    assert all(t["status"] == "paid" for t in res["items"])

    # Filter by method
    res = await tx_routes.list_transactions(
        staff, method="credit_card", paginate=True
    )
    assert res["total"] == 1
    assert len(res["items"]) == 1
    assert res["items"][0]["method"] == "credit_card"

    # Filter by search (customer_name)
    res = await tx_routes.list_transactions(
        staff, search="Bob", paginate=True
    )
    assert res["total"] == 1
    assert len(res["items"]) == 1
    assert res["items"][0]["customer_name"] == "Bob"

    # Date range filter. _tx(i) sets created_at at hour 10+i, so rows here are at
    # 11:00, 12:00 and 13:00. Boundaries are kept off the exact row timestamps because
    # fixtures use the "Z" suffix while the route emits "+00:00" -- lexicographic
    # comparison is only reliable away from the boundary.
    res = await tx_routes.list_transactions(
        staff, start="2026-08-14T10:00:00Z", end="2026-08-14T23:00:00Z", paginate=True
    )
    assert res["total"] == 3

    # Narrower window excludes the 13:00 row.
    res = await tx_routes.list_transactions(
        staff, start="2026-08-14T10:00:00Z", end="2026-08-14T12:30:00Z", paginate=True
    )
    assert res["total"] == 2


@pytest.mark.anyio
async def test_transactions_paginate_param_respected(db, staff):
    """Transactions: paginate parameter controls response shape."""
    db.transactions.rows = [_tx(i) for i in range(5)]

    # paginate=False (default) -> array
    res = await tx_routes.list_transactions(staff, page=1, limit=2)
    assert isinstance(res, list)
    assert len(res) == 2  # limit respected even in legacy mode

    # paginate=True -> object
    res = await tx_routes.list_transactions(
        staff, page=1, limit=2, paginate=True
    )
    assert isinstance(res, dict)
    assert res["total"] == 5
    assert res["limit"] == 2
    assert res["skip"] == 0
    assert len(res["items"]) == 2