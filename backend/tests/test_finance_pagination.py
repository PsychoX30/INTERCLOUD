"""Focused tests for finance pagination migration to true server-side."""

from __future__ import annotations
from unittest.mock import AsyncMock
from bson import ObjectId
import pytest
from portal.routes import finance as finance_routes


class _AssetsCursor:
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


class _AssetsCollection:
    def __init__(self, rows):
        self.rows = rows

    def find(self, query):
        return _AssetsCursor(self._filtered(query))

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
                else:
                    match = r.get(k) == v
                if not match:
                    break
            if match:
                out.append(r)
        return out


class _CreditNotesCursor:
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


class _CreditNotesCollection:
    def __init__(self, rows):
        self.rows = rows

    def find(self, query):
        return _CreditNotesCursor(self._filtered(query))

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
                else:
                    match = r.get(k) == v
                if not match:
                    break
            if match:
                out.append(r)
        return out


class _Db:
    def __init__(self):
        self.assets = _AssetsCollection([])
        self.credit_notes = _CreditNotesCollection([])
        self.users = _CreditNotesCollection([])  # reuse for user lookups
        self.invoices = _CreditNotesCollection([])  # reuse for invoice lookups


@pytest.fixture
def db(monkeypatch):
    value = _Db()
    monkeypatch.setattr(finance_routes, "_get_db", AsyncMock(return_value=value))
    return value


@pytest.fixture
def admin():
    return {"role": "admin", "email": "admin@example.test", "id": "admin-id"}


def _asset(i: int, **overrides) -> dict:
    base = {
        "_id": ObjectId(),
        "name": f"Asset {i}",
        "category": "server" if i % 2 == 0 else "network",
        "serial_number": f"SN{i:04d}",
        "location": f"Datacenter {i}",
        "vendor": f"Vendor {i}",
        "value": float(1000 * i),
        "salvage_value": float(100 * i),
        "useful_life_years": 5,
        "depreciation_percent": 20.0,
        "useful_life_months": 60,
        "purchase_date": f"2026-01-{i+1:02d}",
        "status": "active" if i % 3 != 0 else "disposed",
        "disposed_at": f"2026-12-{i+1:02d}" if i % 3 == 0 else "",
        "notes": f"Notes for asset {i}",
        "created_at": f"2026-08-14T{10 + i:02d}:00:00Z",
    }
    base.update(overrides)
    return base


def _credit_note(i: int, **overrides) -> dict:
    base = {
        "_id": ObjectId(),
        "number": f"CN-{i:06d}",
        "invoice_id": ObjectId(),
        "invoice_number": f"INV-{i:06d}",
        "user_id": ObjectId(),
        "user_name": f"User {i}",
        "user_email": f"user{i}@example.com",
        "amount": float(1000 * i),
        "reason": f"Reason {i}",
        "notes": f"Notes {i}",
        "status": "draft" if i % 3 == 0 else "applied" if i % 3 == 1 else "cancelled",
        "applied_at": f"2026-08-14T{10 + i:02d}:00:00Z" if i % 3 == 1 else None,
        "applied_by": str(ObjectId()) if i % 3 == 1 else None,
        "created_at": f"2026-08-14T{10 + i:02d}:00:00Z",
    }
    base.update(overrides)
    return base


def _user(i: int, **overrides) -> dict:
    base = {
        "_id": ObjectId(),
        "email": f"user{i}@example.com",
        "name": f"User {i}",
        "role": "client",
        "company": f"Company {i}",
        "created_at": f"2026-01-01T00:00:00Z",
    }
    base.update(overrides)
    return base


def _invoice(i: int, **overrides) -> dict:
    base = {
        "_id": ObjectId(),
        "number": f"INV-{i:06d}",
        "user_id": ObjectId(),
        "customer_name": f"Customer {i}",
        "total": float(5000 * i),
        "status": "paid" if i % 2 == 0 else "unpaid",
        "created_at": f"2026-08-14T{10 + i:02d}:00:00Z",
        "paid_at": f"2026-08-14T{10 + i:02d}:00:00Z" if i % 2 == 0 else None,
        "due_date": f"2026-09-14T{10 + i:02d}:00:00Z",
    }
    base.update(overrides)
    return base


# ============================================================
# ASSETS PAGINATION
# ============================================================
@pytest.mark.anyio
async def test_assets_paginated_basic(db, admin):
    """paginate=true returns {items, total, limit, skip}."""
    db.assets.rows = [_asset(i) for i in range(25)]

    res = await finance_routes.assets_list(
        admin=admin, limit=10, skip=0, paginate=True
    )
    assert res["total"] == 25
    assert res["limit"] == 10
    assert res["skip"] == 0
    assert len(res["items"]) == 10
    # default sort is created_at desc -> newest first
    assert res["items"][0]["created_at"] > res["items"][-1]["created_at"]


@pytest.mark.anyio
async def test_assets_paginated_second_page(db, admin):
    """Second page of pagination returns a different slice and same total."""
    db.assets.rows = [_asset(i) for i in range(25)]

    res = await finance_routes.assets_list(
        admin=admin, limit=10, skip=0, paginate=True
    )
    res2 = await finance_routes.assets_list(
        admin=admin, limit=10, skip=10, paginate=True
    )
    assert res2["total"] == 25
    assert res2["skip"] == 10
    assert len(res2["items"]) == 10
    assert res2["items"][0]["id"] != res["items"][0]["id"]


@pytest.mark.anyio
async def test_assets_default_limit_50(db, admin):
    """Default limit is 50, not the shared helper's 25."""
    db.assets.rows = [_asset(i) for i in range(60)]

    res = await finance_routes.assets_list(admin=admin, paginate=True)
    assert res["limit"] == 50
    assert len(res["items"]) == 50
    assert res["total"] == 60


# ============================================================
# Backward compatibility
# ============================================================
@pytest.mark.anyio
async def test_assets_backward_compat_array(db, admin):
    """Default (paginate falsy) returns a bare array, not an object."""
    db.assets.rows = [_asset(i) for i in range(3)]
    res = await finance_routes.assets_list(admin=admin)
    assert isinstance(res, list)
    assert len(res) == 3


@pytest.mark.anyio
async def test_assets_no_paginate_param_array(db, admin):
    """Omitting paginate entirely returns a bare array."""
    db.assets.rows = [_asset(i) for i in range(5)]
    res = await finance_routes.assets_list(admin=admin)
    assert isinstance(res, list)
    assert len(res) == 5


# ============================================================
# Search (q) - assets filter by name/serial_number/location/vendor/notes
# ============================================================
@pytest.mark.anyio
async def test_assets_search_by_name(db, admin):
    """q filters by name (case-insensitive)."""
    db.assets.rows = [
        _asset(1, name="VPS Server"),
        _asset(2, name="Cloud Switch"),
    ]
    res = await finance_routes.assets_list(admin=admin, q="vps")
    assert len(res) == 1
    assert "VPS" in res[0]["name"]


@pytest.mark.anyio
async def test_assets_search_by_serial_number(db, admin):
    """q filters by serial_number (case-insensitive)."""
    db.assets.rows = [
        _asset(1, serial_number="SN0001"),
        _asset(2, serial_number="SN0002"),
    ]
    res = await finance_routes.assets_list(admin=admin, q="sn0001")
    assert len(res) == 1
    assert "SN0001" == res[0]["serial_number"]


@pytest.mark.anyio
async def test_assets_search_paginated_total(db, admin):
    """q interacts correctly with paginate: total reflects filtered count."""
    db.assets.rows = [
        _asset(i, name=f"VPS Plan {i}") for i in range(15)
    ] + [_asset(i + 100, name=f"Cloud Plan {i}") for i in range(10)]

    res = await finance_routes.assets_list(
        admin=admin, q="vps", paginate=True, limit=5
    )
    assert res["total"] == 15
    assert len(res["items"]) == 5


# ============================================================
# Sort allowlist for assets
# ============================================================
@pytest.mark.anyio
async def test_assets_sort_by_name_asc(db, admin):
    """sort=name&order=asc returns assets alphabetically by name."""
    db.assets.rows = [
        _asset(1, name="Gamma"),
        _asset(2, name="Alpha"),
        _asset(3, name="Beta"),
    ]
    res = await finance_routes.assets_list(
        admin=admin, sort="name", order="asc"
    )
    names = [r["name"] for r in res]
    assert names == ["Alpha", "Beta", "Gamma"]


@pytest.mark.anyio
async def test_assets_sort_by_value_desc(db, admin):
    """sort=value&order=desc returns highest value first."""
    db.assets.rows = [
        _asset(1, value=100),
        _asset(2, value=300),
        _asset(3, value=200),
    ]
    res = await finance_routes.assets_list(
        admin=admin, sort="value", order="desc"
    )
    values = [r["value"] for r in res]
    assert values == [300.0, 200.0, 100.0]


# ============================================================
# Legacy full response (no paginate) ignores skip/limit
# ============================================================
@pytest.mark.anyio
async def test_assets_legacy_returns_full_array(db, admin):
    """Legacy (no paginate) returns the entire set regardless of skip/limit."""
    db.assets.rows = [_asset(i) for i in range(5)]
    res = await finance_routes.assets_list(
        admin=admin, skip=2, limit=1
    )
    assert isinstance(res, list)
    assert len(res) == 5


# ============================================================
# CREDIT NOTES PAGINATION
# ============================================================
@pytest.mark.anyio
async def test_credit_notes_paginated_basic(db, admin):
    """paginate=true returns {items, total, limit, skip} with invoice/user enrichment."""
    # Setup related data
    db.users.rows = [_user(i) for i in range(25)]
    db.invoices.rows = [_invoice(i) for i in range(25)]
    db.credit_notes.rows = [_credit_note(i) for i in range(25)]

    res = await finance_routes.credit_notes_list(
        admin=admin, limit=10, skip=0, paginate=True
    )
    assert res["total"] == 25
    assert res["limit"] == 10
    assert res["skip"] == 0
    assert len(res["items"]) == 10
    # default sort is created_at desc -> newest first
    assert res["items"][0]["created_at"] > res["items"][-1]["created_at"]
    # Verify enrichment exists
    assert "user_name" in res["items"][0]
    assert "invoice_number" in res["items"][0]


@pytest.mark.anyio
async def test_credit_notes_paginated_second_page(db, admin):
    """Second page of pagination returns a different slice and same total."""
    db.users.rows = [_user(i) for i in range(25)]
    db.invoices.rows = [_invoice(i) for i in range(25)]
    db.credit_notes.rows = [_credit_note(i) for i in range(25)]

    res = await finance_routes.credit_notes_list(
        admin=admin, limit=10, skip=0, paginate=True
    )
    res2 = await finance_routes.credit_notes_list(
        admin=admin, limit=10, skip=10, paginate=True
    )
    assert res2["total"] == 25
    assert res2["skip"] == 10
    assert len(res2["items"]) == 10
    assert res2["items"][0]["id"] != res["items"][0]["id"]


@pytest.mark.anyio
async def test_credit_notes_default_limit_50(db, admin):
    """Default limit is 50, not the shared helper's 25."""
    db.users.rows = [_user(i) for i in range(60)]
    db.invoices.rows = [_invoice(i) for i in range(60)]
    db.credit_notes.rows = [_credit_note(i) for i in range(60)]

    res = await finance_routes.credit_notes_list(admin=admin, paginate=True)
    assert res["limit"] == 50
    assert len(res["items"]) == 50
    assert res["total"] == 60


# ============================================================
# Backward compatibility
# ============================================================
@pytest.mark.anyio
async def test_credit_notes_backward_compat_array(db, admin):
    """Default (paginate falsy) returns a bare array, not an object."""
    db.users.rows = [_user(i) for i in range(3)]
    db.invoices.rows = [_invoice(i) for i in range(3)]
    db.credit_notes.rows = [_credit_note(i) for i in range(3)]
    res = await finance_routes.credit_notes_list(admin=admin)
    assert isinstance(res, list)
    assert len(res) == 3


@pytest.mark.anyio
async def test_credit_notes_no_paginate_param_array(db, admin):
    """Omitting paginate entirely returns a bare array."""
    db.users.rows = [_user(i) for i in range(5)]
    db.invoices.rows = [_invoice(i) for i in range(5)]
    db.credit_notes.rows = [_credit_note(i) for i in range(5)]
    res = await finance_routes.credit_notes_list(admin=admin)
    assert isinstance(res, list)
    assert len(res) == 5


# ============================================================
# Filters (invoice_id, user_id, status) preserved with pagination
# ============================================================
@pytest.mark.anyio
async def test_credit_notes_filter_by_invoice_id(db, admin):
    """Filter by invoice_id works with pagination."""
    inv_id = ObjectId()
    db.users.rows = [_user(0)]
    db.invoices.rows = [_invoice(0, _id=inv_id)]
    db.credit_notes.rows = [
        _credit_note(0, invoice_id=inv_id, status="draft"),
        _credit_note(1, invoice_id=ObjectId(), status="applied"),  # different invoice
    ]

    res = await finance_routes.credit_notes_list(
        admin=admin, invoice_id=str(inv_id), paginate=True
    )
    assert res["total"] == 1
    assert len(res["items"]) == 1
    assert res["items"][0]["invoice_id"] == str(inv_id)
    assert res["items"][0]["status"] == "draft"


@pytest.mark.anyio
async def test_credit_notes_filter_by_user_id(db, admin):
    """Filter by user_id works with pagination."""
    user_id = ObjectId()
    db.users.rows = [_user(0, _id=user_id)]
    db.invoices.rows = [_invoice(0)]
    db.credit_notes.rows = [
        _credit_note(0, user_id=user_id, status="draft"),
        _credit_note(1, user_id=ObjectId(), status="applied"),  # different user
    ]

    res = await finance_routes.credit_notes_list(
        admin=admin, user_id=str(user_id), paginate=True
    )
    assert res["total"] == 1
    assert len(res["items"]) == 1
    assert res["items"][0]["user_id"] == str(user_id)
    assert res["items"][0]["status"] == "draft"


@pytest.mark.anyio
async def test_credit_notes_filter_by_status(db, admin):
    """Filter by status works with pagination."""
    db.users.rows = [_user(0), _user(1)]
    db.invoices.rows = [_invoice(0), _invoice(1)]
    db.credit_notes.rows = [
        _credit_note(0, status="draft"),
        _credit_note(1, status="applied"),
        _credit_note(2, status="cancelled"),
        _credit_note(3, status="draft"),
    ]

    res = await finance_routes.credit_notes_list(
        admin=admin, status="draft", paginate=True
    )
    assert res["total"] == 2
    assert len(res["items"]) == 2
    assert all(item["status"] == "draft" for item in res["items"])


# ============================================================
# Sort allowlist for credit notes
# ============================================================
@pytest.mark.anyio
async def test_credit_notes_sort_by_number_asc(db, admin):
    """sort=number&order=asc returns credit notes numerically by number."""
    db.users.rows = [_user(0), _user(1), _user(2)]
    db.invoices.rows = [_invoice(0), _invoice(1), _invoice(2)]
    db.credit_notes.rows = [
        _credit_note(0, number="CN-000100"),
        _credit_note(1, number="CN-000050"),
        _credit_note(2, number="CN-000200"),
    ]
    res = await finance_routes.credit_notes_list(
        admin=admin, sort="number", order="asc"
    )
    numbers = [r["number"] for r in res]
    assert numbers == ["CN-000050", "CN-000100", "CN-000200"]


@pytest.mark.anyio
async def test_credit_notes_sort_by_amount_desc(db, admin):
    """sort=amount&order=desc returns highest amount first."""
    db.users.rows = [_user(0), _user(1), _user(2)]
    db.invoices.rows = [_invoice(0), _invoice(1), _invoice(2)]
    db.credit_notes.rows = [
        _credit_note(0, amount=100),
        _credit_note(1, amount=300),
        _credit_note(2, amount=200),
    ]
    res = await finance_routes.credit_notes_list(
        admin=admin, sort="amount", order="desc"
    )
    amounts = [r["amount"] for r in res]
    assert amounts == [300.0, 200.0, 100.0]


# ============================================================
# Legacy full response (no paginate) ignores skip/limit for credit notes
# ============================================================
@pytest.mark.anyio
async def test_credit_notes_legacy_returns_full_array(db, admin):
    """Legacy (no paginate) returns the entire set regardless of skip/limit."""
    db.users.rows = [_user(i) for i in range(3)]
    db.invoices.rows = [_invoice(i) for i in range(3)]
    db.credit_notes.rows = [_credit_note(i) for i in range(3)]
    res = await finance_routes.credit_notes_list(
        admin=admin, skip=1, limit=1
    )
    assert isinstance(res, list)
    assert len(res) == 3