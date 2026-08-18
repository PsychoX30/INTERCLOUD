"""Regression tests for catalog /admin/products endpoint: pagination, filter, sort.

Covers:
- GET /admin/products via admin_list_products
- skip / limit pagination with total count (paginate=true)
- server-side search by name/description (q)
- server-side sort (asc / desc) on allowlisted fields
- backward-compatible bare array return when paginate is falsy (default)
"""
from __future__ import annotations
from unittest.mock import AsyncMock
from bson import ObjectId
import pytest

from portal.routes import catalog as catalog_routes


class _Cursor:
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


class _Collection:
    def __init__(self, rows):
        self.rows = rows

    def find(self, query):
        return _Cursor(self._filtered(query))

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
                    match = any(
                        r.get(field, "").lower().find(condition["$regex"].lower()) >= 0
                        for clause in v
                        for field, condition in clause.items()
                        if isinstance(condition, dict) and "$regex" in condition
                    )
                elif isinstance(v, dict) and "$regex" in v:
                    match = r.get(k, "").lower().find(v["$regex"].lower()) >= 0
                else:
                    match = r.get(k) == v
                if not match:
                    break
            if match:
                out.append(r)
        return out


class _Db:
    def __init__(self):
        self.products = _Collection([])
        self.categories = _Collection([])


@pytest.fixture
def db(monkeypatch):
    value = _Db()
    monkeypatch.setattr(catalog_routes, "_get_db", AsyncMock(return_value=value))
    return value


@pytest.fixture
def admin():
    return {"role": "admin", "email": "admin@example.test"}


def _product(i: int, **overrides) -> dict:
    base = {
        "_id": ObjectId(),
        "name": f"Product {i}",
        "category": "cloud" if i % 2 == 0 else "vps",
        "description": f"Description for product {i}",
        "price_monthly": 100 * i,
        "setup_fee": 0,
        "billing_cycle": "monthly",
        "features": [],
        "is_active": True,
        "is_addon": False,
        "sort_order": i,
        "created_at": f"2026-08-14T{10 + i:02d}:00:00Z",
    }
    base.update(overrides)
    return base


# ============================================================
# Pagination
# ============================================================
@pytest.mark.anyio
async def test_products_paginated_basic(db, admin):
    """paginate=true returns {items, total, limit, skip}."""
    db.products.rows = [_product(i) for i in range(25)]

    res = await catalog_routes.admin_list_products(
        admin=admin, limit=10, skip=0, paginate=True
    )
    assert res["total"] == 25
    assert res["limit"] == 10
    assert res["skip"] == 0
    assert len(res["items"]) == 10
    # default sort is created_at desc -> newest first
    assert res["items"][0]["created_at"] > res["items"][-1]["created_at"]


@pytest.mark.anyio
async def test_products_paginated_second_page(db, admin):
    """Second page of pagination returns a different slice and same total."""
    db.products.rows = [_product(i) for i in range(25)]

    res = await catalog_routes.admin_list_products(
        admin=admin, limit=10, skip=0, paginate=True
    )
    res2 = await catalog_routes.admin_list_products(
        admin=admin, limit=10, skip=10, paginate=True
    )
    assert res2["total"] == 25
    assert res2["skip"] == 10
    assert len(res2["items"]) == 10
    assert res2["items"][0]["id"] != res["items"][0]["id"]


@pytest.mark.anyio
async def test_products_default_limit_50(db, admin):
    """Default limit is 50, not the shared helper's 25."""
    db.products.rows = [_product(i) for i in range(60)]

    res = await catalog_routes.admin_list_products(admin=admin, paginate=True)
    assert res["limit"] == 50
    assert len(res["items"]) == 50
    assert res["total"] == 60


# ============================================================
# Backward compatibility
# ============================================================
@pytest.mark.anyio
async def test_products_backward_compat_array(db, admin):
    """Default (paginate falsy) returns a bare array, not an object."""
    db.products.rows = [_product(i) for i in range(3)]
    res = await catalog_routes.admin_list_products(admin=admin)
    assert isinstance(res, list)
    assert len(res) == 3


@pytest.mark.anyio
async def test_products_no_paginate_param_array(db, admin):
    """Omitting paginate entirely returns a bare array."""
    db.products.rows = [_product(i) for i in range(5)]
    res = await catalog_routes.admin_list_products(admin=admin)
    assert isinstance(res, list)
    assert len(res) == 5


# ============================================================
# Search (q)
# ============================================================
@pytest.mark.anyio
async def test_products_search_by_name(db, admin):
    """q filters by name (case-insensitive)."""
    db.products.rows = [
        _product(1, name="VPS Starter"),
        _product(2, name="Cloud Enterprise"),
    ]
    res = await catalog_routes.admin_list_products(admin=admin, q="vps")
    assert len(res) == 1
    assert "VPS" in res[0]["name"]


@pytest.mark.anyio
async def test_products_search_by_description(db, admin):
    """q filters by description (case-insensitive)."""
    db.products.rows = [
        _product(1, description="High performance server"),
        _product(2, description="Budget storage box"),
    ]
    res = await catalog_routes.admin_list_products(admin=admin, q="storage")
    assert len(res) == 1
    assert "storage" in res[0]["description"].lower()


@pytest.mark.anyio
async def test_products_search_paginated_total(db, admin):
    """q interacts correctly with paginate: total reflects filtered count."""
    db.products.rows = [
        _product(i, name=f"VPS Plan {i}") for i in range(15)
    ] + [_product(i + 100, name=f"Cloud Plan {i}") for i in range(10)]

    res = await catalog_routes.admin_list_products(
        admin=admin, q="vps", paginate=True, limit=5
    )
    assert res["total"] == 15
    assert len(res["items"]) == 5


# ============================================================
# Sort allowlist
# ============================================================
@pytest.mark.anyio
async def test_products_sort_by_name_asc(db, admin):
    """sort=name&order=asc returns products alphabetically by name."""
    db.products.rows = [
        _product(1, name="Gamma"),
        _product(2, name="Alpha"),
        _product(3, name="Beta"),
    ]
    res = await catalog_routes.admin_list_products(
        admin=admin, sort="name", order="asc"
    )
    names = [r["name"] for r in res]
    assert names == ["Alpha", "Beta", "Gamma"]


@pytest.mark.anyio
async def test_products_sort_by_name_desc(db, admin):
    """sort=name&order=desc returns products reverse-alphabetically."""
    db.products.rows = [
        _product(1, name="Alpha"),
        _product(2, name="Gamma"),
        _product(3, name="Beta"),
    ]
    res = await catalog_routes.admin_list_products(
        admin=admin, sort="name", order="desc"
    )
    names = [r["name"] for r in res]
    assert names == ["Gamma", "Beta", "Alpha"]


@pytest.mark.anyio
async def test_products_sort_by_price_asc(db, admin):
    """sort=price_monthly&order=asc returns cheapest first."""
    db.products.rows = [
        _product(1, price_monthly=300),
        _product(2, price_monthly=100),
        _product(3, price_monthly=200),
    ]
    res = await catalog_routes.admin_list_products(
        admin=admin, sort="price_monthly", order="asc"
    )
    prices = [r["price_monthly"] for r in res]
    assert prices == [100, 200, 300]


@pytest.mark.anyio
async def test_products_sort_by_category(db, admin):
    """sort=category&order=asc groups products by category."""
    db.products.rows = [
        _product(1, category="vps"),
        _product(2, category="cloud"),
        _product(3, category="zcategory"),
    ]
    res = await catalog_routes.admin_list_products(
        admin=admin, sort="category", order="asc"
    )
    cats = [r["category"] for r in res]
    assert cats == ["cloud", "vps", "zcategory"]


@pytest.mark.anyio
async def test_products_sort_by_sort_order(db, admin):
    """sort=sort_order&order=asc returns by manual sort order ascending."""
    db.products.rows = [
        _product(1, sort_order=50),
        _product(2, sort_order=10),
        _product(3, sort_order=30),
    ]
    res = await catalog_routes.admin_list_products(
        admin=admin, sort="sort_order", order="asc"
    )
    orders = [r["sort_order"] for r in res]
    assert orders == [10, 30, 50]


@pytest.mark.anyio
async def test_products_sort_invalid_falls_back_to_created_at(db, admin):
    """sort with a non-allowlisted field falls back to created_at."""
    db.products.rows = [
        _product(1, created_at="2026-08-14T12:00:00Z"),
        _product(2, created_at="2026-08-14T10:00:00Z"),
        _product(3, created_at="2026-08-14T11:00:00Z"),
    ]
    res = await catalog_routes.admin_list_products(
        admin=admin, sort="invalid_field", order="asc"
    )
    # created_at asc -> oldest first
    times = [r["created_at"] for r in res]
    assert times == [
        "2026-08-14T10:00:00Z",
        "2026-08-14T11:00:00Z",
        "2026-08-14T12:00:00Z",
    ]


# ============================================================
# is_addon filter (server-side, used by AdminProducts tabs)
# ============================================================
@pytest.mark.anyio
async def test_products_filter_addons_only(db, admin):
    """is_addon=true returns only add-on products with matching total."""
    db.products.rows = [_product(1, is_addon=True), _product(2), _product(3, is_addon=True), _product(4)]

    res = await catalog_routes.admin_list_products(
        admin=admin, is_addon=True, paginate=True
    )
    assert res["total"] == 2
    assert all(p["is_addon"] for p in res["items"])


@pytest.mark.anyio
async def test_products_filter_base_only(db, admin):
    """is_addon=false returns only base plans."""
    db.products.rows = [_product(1, is_addon=True), _product(2), _product(3, is_addon=True), _product(4)]

    res = await catalog_routes.admin_list_products(
        admin=admin, is_addon=False, paginate=True
    )
    assert res["total"] == 2
    assert all(not p["is_addon"] for p in res["items"])


@pytest.mark.anyio
async def test_products_filter_addon_legacy_bare_array(db, admin):
    """Legacy path (no paginate) also honors is_addon filter."""
    db.products.rows = [_product(1, is_addon=True), _product(2), _product(3)]

    res = await catalog_routes.admin_list_products(admin=admin, is_addon=True)
    assert isinstance(res, list)
    assert len(res) == 1
    assert res[0]["is_addon"] is True


# ============================================================
# is_addon filter (drives the frontend all/base/addons tabs)
# ============================================================
@pytest.mark.anyio
async def test_products_filter_is_addon_true(db, admin):
    """is_addon=True returns only add-on products."""
    db.products.rows = [
        _product(1, is_addon=False),
        _product(2, is_addon=True),
        _product(3, is_addon=True),
    ]
    res = await catalog_routes.admin_list_products(
        admin=admin, paginate=True, is_addon=True
    )
    assert res["total"] == 2
    assert all(r["is_addon"] is True for r in res["items"])


@pytest.mark.anyio
async def test_products_filter_is_addon_false(db, admin):
    """is_addon=False returns only base plans."""
    db.products.rows = [
        _product(1, is_addon=False),
        _product(2, is_addon=True),
        _product(3, is_addon=False),
    ]
    res = await catalog_routes.admin_list_products(
        admin=admin, paginate=True, is_addon=False
    )
    assert res["total"] == 2
    assert all(r["is_addon"] is False for r in res["items"])


@pytest.mark.anyio
async def test_products_is_addon_omitted_returns_both(db, admin):
    """Omitting is_addon must not filter anything (tab 'all')."""
    db.products.rows = [
        _product(1, is_addon=False),
        _product(2, is_addon=True),
    ]
    res = await catalog_routes.admin_list_products(admin=admin, paginate=True)
    assert res["total"] == 2


# ============================================================
# Legacy full response (no paginate) ignores skip/limit
# ============================================================
@pytest.mark.anyio
async def test_products_legacy_returns_full_array(db, admin):
    """Legacy (no paginate) returns the entire set regardless of skip/limit."""
    db.products.rows = [_product(i) for i in range(5)]
    res = await catalog_routes.admin_list_products(
        admin=admin, skip=2, limit=1
    )
    assert isinstance(res, list)
    assert len(res) == 5
