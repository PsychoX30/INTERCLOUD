"""Unit regressions for paginated billing list endpoints."""
from __future__ import annotations

from unittest.mock import AsyncMock

from bson import ObjectId
import pytest

from portal.routes import billing as billing_routes


class _Cursor:
    def __init__(self, rows):
        self.rows = list(rows)
        self._skip = 0
        self._limit = None

    def sort(self, key, direction=-1):
        self.rows.sort(key=lambda row: row.get(key, ""), reverse=direction == -1)
        return self

    def skip(self, value):
        self._skip = value
        return self

    def limit(self, value):
        self._limit = value
        return self

    async def to_list(self, _limit):
        end = None if self._limit is None else self._skip + self._limit
        return self.rows[self._skip:end]


class _Collection:
    def __init__(self, rows=()):
        self.rows = list(rows)
        self.queries = []

    def find(self, query):
        self.queries.append(query)
        return _Cursor(self._filtered(query))

    async def count_documents(self, query):
        self.queries.append(query)
        return len(self._filtered(query))

    def _filtered(self, query):
        def matches(row):
            for key, value in query.items():
                if isinstance(value, dict) and "$in" in value:
                    if row.get(key) not in value["$in"]:
                        return False
                elif row.get(key) != value:
                    return False
            return True

        return [row for row in self.rows if matches(row)]


class _Db:
    def __init__(self):
        self.invoices = _Collection()
        self.quotations = _Collection()


@pytest.fixture
def db(monkeypatch):
    value = _Db()
    monkeypatch.setattr(billing_routes, "_get_db", AsyncMock(return_value=value))
    monkeypatch.setattr(billing_routes, "_mark_overdue", AsyncMock())
    monkeypatch.setattr(billing_routes, "_deny_creative", lambda _staff: None)

    async def serialize_invoice(_db, document):
        return {"id": str(document["_id"]), **document}

    async def serialize_quotation(_db, document):
        return {"id": str(document["_id"]), **document}

    monkeypatch.setattr(billing_routes, "_serialize_invoice", serialize_invoice)
    monkeypatch.setattr(billing_routes, "_serialize_quotation", serialize_quotation)
    return value


@pytest.fixture
def admin():
    return {"role": "admin", "email": "admin@example.test"}


def _invoice(index, *, user_id=None, **overrides):
    document = {
        "_id": ObjectId(),
        "number": f"INV-{index:03d}",
        "user_id": user_id or ObjectId(),
        "status": "unpaid",
        "total": index * 100,
        "due_date": f"2026-09-{index:02d}",
        "created_at": f"2026-08-{index:02d}T00:00:00Z",
    }
    document.update(overrides)
    return document


def _quotation(index, *, user_id=None, **overrides):
    document = {
        "_id": ObjectId(),
        "number": f"QTN-{index:03d}",
        "user_id": user_id or ObjectId(),
        "status": "draft",
        "total": index * 100,
        "valid_until": f"2026-09-{index:02d}",
        "created_at": f"2026-08-{index:02d}T00:00:00Z",
    }
    document.update(overrides)
    return document


@pytest.mark.anyio
async def test_invoices_paginate_returns_scoped_sorted_slice(db, admin):
    db.invoices.rows = [_invoice(index) for index in range(1, 6)]

    result = await billing_routes.admin_list_invoices(
        staff=admin, paginate=True, skip=1, limit=2, sort="number", order="asc"
    )

    assert result["total"] == 5
    assert result["skip"] == 1
    assert result["limit"] == 2
    assert [item["number"] for item in result["items"]] == ["INV-002", "INV-003"]


@pytest.mark.anyio
async def test_invoices_legacy_request_returns_bare_array(db, admin):
    db.invoices.rows = [_invoice(index) for index in range(1, 4)]

    result = await billing_routes.admin_list_invoices(staff=admin, skip=1, limit=1)

    assert isinstance(result, list)
    assert len(result) == 3


@pytest.mark.anyio
async def test_quotations_paginate_preserves_sales_scope(db):
    assigned_client = ObjectId()
    db.quotations.rows = [
        _quotation(1, user_id=assigned_client),
        _quotation(2, user_id=ObjectId()),
        _quotation(3, user_id=assigned_client),
    ]
    sales = {"role": "sales", "assigned_client_ids": [str(assigned_client)]}

    result = await billing_routes.admin_list_quotations(
        staff=sales, paginate=True, limit=1, sort="number", order="asc"
    )

    assert result["total"] == 2
    assert result["limit"] == 1
    assert [item["number"] for item in result["items"]] == ["QTN-001"]
    assert db.quotations.queries[0] == {"user_id": {"$in": [assigned_client]}}


@pytest.mark.anyio
async def test_quotations_legacy_request_returns_bare_array(db, admin):
    db.quotations.rows = [_quotation(index) for index in range(1, 4)]

    result = await billing_routes.admin_list_quotations(staff=admin, skip=1, limit=1)

    assert isinstance(result, list)
    assert len(result) == 3
