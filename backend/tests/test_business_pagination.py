"""Regression tests for Business endpoints: pagination, filter, sort.

Endpoints covered:
- GET /admin/crm
- GET /admin/projects
- GET /admin/content
- GET /admin/followups
- GET /admin/documents

Each endpoint must support:
- skip / limit pagination with total count (paginate=true) via shared
  _pagination_params / _pagination_response helpers
- server-side filtering (status for projects, q search for crm/documents)
- backward-compatible bare-array return when paginate=false (default)
- unchanged _sales_scope_filter / _sales_followup_filter scoping behavior
- unchanged CRM enrichment (latest_order, active_orders_count, etc.)
"""
from __future__ import annotations

import re
from unittest.mock import AsyncMock

import pytest
from bson import ObjectId

from portal.routes import business as business_routes


def _match_clause(doc: dict, key: str, cond) -> bool:
    if key == "$or":
        return any(all(_match_clause(doc, k, v) for k, v in clause.items()) for clause in cond)
    if isinstance(cond, dict):
        if "$in" in cond:
            return doc.get(key) in cond["$in"]
        if "$regex" in cond:
            val = str(doc.get(key) or "")
            return re.search(cond["$regex"], val, re.IGNORECASE) is not None
        return doc.get(key) == cond
    if cond is None and key == "_id":
        return False  # sales-with-no-assignment sentinel: matches nothing
    return doc.get(key) == cond


def _matches(doc: dict, query: dict) -> bool:
    if not query:
        return True
    return all(_match_clause(doc, k, v) for k, v in query.items())


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
    def __init__(self, rows=None):
        self.rows = rows or []

    def find(self, query=None, projection=None):
        query = query or {}
        return _Cursor([r for r in self.rows if _matches(r, query)])

    async def count_documents(self, query=None):
        query = query or {}
        return len([r for r in self.rows if _matches(r, query)])

    async def find_one(self, query=None):
        query = query or {}
        for r in self.rows:
            if _matches(r, query):
                return r
        return None


class _Db:
    def __init__(self):
        self.crm_customers = _Collection()
        self.orders = _Collection()
        self.invoices = _Collection()
        self.projects = _Collection()
        self.content_plan = _Collection()
        self.followups = _Collection()
        self.documents = _Collection()


@pytest.fixture
def db(monkeypatch):
    value = _Db()
    monkeypatch.setattr(business_routes, "_get_db", AsyncMock(return_value=value))
    return value


@pytest.fixture
def admin():
    return {"role": "admin", "email": "admin@example.test"}


def _crm(i: int, **overrides):
    base = {
        "_id": ObjectId(),
        "name": f"Customer {i}",
        "email": f"customer{i}@test.id",
        "phone": "",
        "company": f"PT Contoh {i}",
        "position": "",
        "industry": "",
        "status": "prospect",
        "notes": "",
        "user_id": None,
        "source": "",
        "created_at": f"2026-08-14T{10 + i:02d}:00:00Z",
        "updated_at": f"2026-08-14T{10 + i:02d}:00:00Z",
    }
    base.update(overrides)
    return base


def _project(i: int, **overrides):
    base = {
        "_id": ObjectId(),
        "name": f"Project {i}",
        "customer_id": None,
        "customer_name": "",
        "owner": "",
        "status": "planning",
        "priority": "medium",
        "progress": 0,
        "start_date": "",
        "target_date": "",
        "description": "",
        "tasks": [],
        "created_at": f"2026-08-14T{10 + i:02d}:00:00Z",
        "updated_at": f"2026-08-14T{10 + i:02d}:00:00Z",
    }
    base.update(overrides)
    return base


def _content(i: int, **overrides):
    base = {
        "_id": ObjectId(),
        "title": f"Post {i}",
        "channel": "blog",
        "type": "post",
        "status": "idea",
        "owner": "",
        "publish_date": f"2026-08-{10 + i:02d}",
        "hook": "",
        "url": "",
        "created_at": f"2026-08-14T{10 + i:02d}:00:00Z",
    }
    base.update(overrides)
    return base


def _followup(i: int, **overrides):
    base = {
        "_id": ObjectId(),
        "customer_id": None,
        "customer_name": f"Customer {i}",
        "task": f"Follow up {i}",
        "channel": "whatsapp",
        "due_date": f"2026-08-{10 + i:02d}",
        "done": False,
        "owner": "",
        "created_at": f"2026-08-14T{10 + i:02d}:00:00Z",
    }
    base.update(overrides)
    return base


def _document(i: int, **overrides):
    base = {
        "_id": ObjectId(),
        "title": f"Document {i}",
        "category": "contract",
        "customer_name": f"Customer {i}",
        "url": "",
        "notes": "",
        "filename": "",
        "size_bytes": 0,
        "created_at": f"2026-08-14T{10 + i:02d}:00:00Z",
    }
    base.update(overrides)
    return base


# ============================================================
# /admin/crm
# ============================================================
@pytest.mark.anyio
async def test_crm_pagination_paginated(db, admin):
    db.crm_customers.rows = [_crm(i) for i in range(25)]

    res = await business_routes.crm_list(staff=admin, skip=0, limit=10, paginate=True)
    assert res["total"] == 25
    assert res["limit"] == 10
    assert res["skip"] == 0
    assert len(res["items"]) == 10
    assert res["items"][0]["updated_at"] > res["items"][-1]["updated_at"]

    res2 = await business_routes.crm_list(staff=admin, skip=10, limit=10, paginate=True)
    assert res2["total"] == 25
    assert res2["skip"] == 10
    assert len(res2["items"]) == 10
    assert res2["items"][0]["id"] != res["items"][0]["id"]


@pytest.mark.anyio
async def test_crm_backward_compat_array(db, admin):
    db.crm_customers.rows = [_crm(i) for i in range(3)]
    res = await business_routes.crm_list(staff=admin)
    assert isinstance(res, list)
    assert len(res) == 3


@pytest.mark.anyio
async def test_crm_search_q(db, admin):
    db.crm_customers.rows = [
        _crm(1, name="Budi Santoso"),
        _crm(2, name="Siti Aminah"),
    ]
    res = await business_routes.crm_list(staff=admin, q="budi")
    assert len(res) == 1
    assert res[0]["name"] == "Budi Santoso"


@pytest.mark.anyio
async def test_crm_filter_status(db, admin):
    """CRM status filter must narrow server-side (paginated total reflects it)."""
    db.crm_customers.rows = [
        _crm(1, status="lead"),
        _crm(2, status="customer"),
        _crm(3, status="lead"),
    ]
    res = await business_routes.crm_list(staff=admin, status="lead")
    assert len(res) == 2
    assert all(r["status"] == "lead" for r in res)

    res_p = await business_routes.crm_list(staff=admin, status="customer", paginate=True)
    assert res_p["total"] == 1
    assert res_p["items"][0]["status"] == "customer"


@pytest.mark.anyio
async def test_crm_filter_status_all_noop(db, admin):
    """status='all' (or empty) must not filter anything."""
    db.crm_customers.rows = [_crm(1, status="lead"), _crm(2, status="customer")]
    res = await business_routes.crm_list(staff=admin, status="all")
    assert len(res) == 2


@pytest.mark.anyio
async def test_crm_sales_scope_preserved_with_pagination(db):
    """Sales must only see their assigned clients, even when paginating."""
    assigned_uid = ObjectId()
    other_uid = ObjectId()
    db.crm_customers.rows = [
        _crm(1, user_id=assigned_uid),
        _crm(2, user_id=other_uid),
    ]
    sales = {"role": "sales", "assigned_client_ids": [str(assigned_uid)]}
    res = await business_routes.crm_list(staff=sales, paginate=True)
    assert res["total"] == 1
    assert res["items"][0]["user_id"] == str(assigned_uid)


@pytest.mark.anyio
async def test_crm_enrichment_preserved_with_pagination(db, admin):
    """CRM enrichment (latest_order, lifetime_value, etc.) must survive pagination."""
    uid = ObjectId()
    db.crm_customers.rows = [_crm(1, user_id=uid)]
    db.orders.rows = [{
        "_id": ObjectId(), "user_id": uid, "status": "active",
        "created_at": "2026-08-14T10:00:00Z", "product_name": "VPS",
        "invoice_id": None,
    }]
    db.invoices.rows = [{"_id": ObjectId(), "user_id": uid, "total": 500000, "status": "paid"}]
    res = await business_routes.crm_list(staff=admin, paginate=True)
    row = res["items"][0]
    assert row["latest_order"]["product_name"] == "VPS"
    assert row["won_orders_count"] == 1
    assert row["lifetime_value"] == 500000


# ============================================================
# /admin/projects
# ============================================================
@pytest.mark.anyio
async def test_projects_pagination_paginated(db, admin):
    db.projects.rows = [_project(i) for i in range(25)]
    res = await business_routes.projects_list(staff=admin, skip=0, limit=10, paginate=True)
    assert res["total"] == 25
    assert len(res["items"]) == 10

    res2 = await business_routes.projects_list(staff=admin, skip=10, limit=10, paginate=True)
    assert res2["skip"] == 10
    assert len(res2["items"]) == 10


@pytest.mark.anyio
async def test_projects_backward_compat_array(db, admin):
    db.projects.rows = [_project(i) for i in range(3)]
    res = await business_routes.projects_list(staff=admin)
    assert isinstance(res, list)
    assert len(res) == 3


@pytest.mark.anyio
async def test_projects_filter_status(db, admin):
    db.projects.rows = [
        _project(1, status="planning"),
        _project(2, status="done"),
    ]
    res = await business_routes.projects_list(staff=admin, status="done")
    assert len(res) == 1
    assert res[0]["status"] == "done"


# ============================================================
# /admin/content
# ============================================================
@pytest.mark.anyio
async def test_content_pagination_paginated(db, admin):
    db.content_plan.rows = [_content(i) for i in range(25)]
    res = await business_routes.content_list(staff=admin, skip=0, limit=10, paginate=True)
    assert res["total"] == 25
    assert len(res["items"]) == 10


@pytest.mark.anyio
async def test_content_backward_compat_array(db, admin):
    db.content_plan.rows = [_content(i) for i in range(3)]
    res = await business_routes.content_list(staff=admin)
    assert isinstance(res, list)
    assert len(res) == 3


# ============================================================
# /admin/followups
# ============================================================
@pytest.mark.anyio
async def test_followups_pagination_paginated(db, admin):
    db.followups.rows = [_followup(i) for i in range(25)]
    res = await business_routes.followups_list(staff=admin, skip=0, limit=10, paginate=True)
    assert res["total"] == 25
    assert len(res["items"]) == 10


@pytest.mark.anyio
async def test_followups_backward_compat_array(db, admin):
    db.followups.rows = [_followup(i) for i in range(3)]
    res = await business_routes.followups_list(staff=admin)
    assert isinstance(res, list)
    assert len(res) == 3


@pytest.mark.anyio
async def test_followups_filter_done(db, admin):
    """Follow-up done filter must narrow rows and paginated total server-side."""
    db.followups.rows = [
        _followup(1, done=False),
        _followup(2, done=True),
        _followup(3, done=False),
    ]
    open_res = await business_routes.followups_list(staff=admin, done=False, paginate=True)
    assert open_res["total"] == 2
    assert all(not row["done"] for row in open_res["items"])

    done_res = await business_routes.followups_list(staff=admin, done=True)
    assert len(done_res) == 1
    assert done_res[0]["done"] is True


@pytest.mark.anyio
async def test_followups_sales_scope_empty_short_circuits_with_pagination(db):
    """Sales with zero visible CRM rows must still short-circuit to an empty
    result, even when paginate=true (preserves _sales_followup_filter None
    short-circuit behavior)."""
    db.followups.rows = [_followup(1)]
    sales = {"role": "sales", "assigned_client_ids": []}
    res = await business_routes.followups_list(staff=sales, paginate=True)
    assert res == []


# ============================================================
# /admin/documents
# ============================================================
@pytest.mark.anyio
async def test_documents_pagination_paginated(db, admin):
    db.documents.rows = [_document(i) for i in range(25)]
    res = await business_routes.docs_list(staff=admin, skip=0, limit=10, paginate=True)
    assert res["total"] == 25
    assert len(res["items"]) == 10


@pytest.mark.anyio
async def test_documents_backward_compat_array(db, admin):
    db.documents.rows = [_document(i) for i in range(3)]
    res = await business_routes.docs_list(staff=admin)
    assert isinstance(res, list)
    assert len(res) == 3


@pytest.mark.anyio
async def test_documents_search_q(db, admin):
    db.documents.rows = [
        _document(1, title="Kontrak Sewa Server"),
        _document(2, title="Invoice Reguler"),
    ]
    res = await business_routes.docs_list(staff=admin, q="kontrak")
    assert len(res) == 1
    assert "Kontrak" in res[0]["title"]
