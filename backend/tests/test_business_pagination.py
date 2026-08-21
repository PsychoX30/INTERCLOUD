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
    if key == "$and":
        return all(_match_clause(doc, k, v) for clause in cond for k, v in clause.items())
    if isinstance(cond, dict):
        if "$in" in cond:
            return doc.get(key) in cond["$in"]
        if "$lt" in cond:
            value = doc.get(key)
            return value is not None and value < cond["$lt"]
        if "$regex" in cond:
            val = str(doc.get(key) or "")
            return re.search(cond["$regex"], val, re.IGNORECASE) is not None
        if "$elemMatch" in cond:
            elem_cond = cond["$elemMatch"]
            if not isinstance(elem_cond, dict):
                return False
            arr = doc.get(key)
            if not isinstance(arr, list):
                return False
            return any(
                all(_match_clause(elem, k, v) for k, v in elem_cond.items())
                for elem in arr
            )
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

    async def insert_one(self, doc):
        doc.setdefault("_id", ObjectId())
        self.rows.append(doc)
        return type("_R", (), {"inserted_id": doc["_id"]})()

    async def update_one(self, query, update):
        query = query or {}
        for r in self.rows:
            if _matches(r, query):
                r.update((update or {}).get("$set", {}))
                return type("_R", (), {"modified_count": 1, "matched_count": 1})()
        return type("_R", (), {"modified_count": 0, "matched_count": 0})()

    async def update_many(self, query, update):
        query = query or {}
        n = 0
        for r in self.rows:
            if _matches(r, query):
                r.update((update or {}).get("$set", {}))
                n += 1
        return type("_R", (), {"modified_count": n, "matched_count": n})()

    async def delete_one(self, query):
        query = query or {}
        for i, r in enumerate(self.rows):
            if _matches(r, query):
                self.rows.pop(i)
                return type("_R", (), {"deleted_count": 1})()
        return type("_R", (), {"deleted_count": 0})()


class _Db:
    def __init__(self):
        self.crm_customers = _Collection()
        self.orders = _Collection()
        self.invoices = _Collection()
        self.projects = _Collection()
        self.content_plan = _Collection()
        self.followups = _Collection()
        self.documents = _Collection()
        self.users = _Collection()


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
async def test_crm_sales_visibility_includes_shared_pool_and_own_assignment(db):
    """Sales see shared prospects/partnerships, own assigned prospect, and assigned clients only."""
    sales_id = ObjectId()
    other_sales_id = ObjectId()
    assigned_client_id = ObjectId()
    other_client_id = ObjectId()
    db.crm_customers.rows = [
        _crm(1, status="prospect", user_id=None),
        _crm(2, status="partnership", user_id=None),
        _crm(3, status="assigned", assigned_to=sales_id, user_id=None),
        _crm(4, status="assigned", assigned_to=other_sales_id, user_id=None),
        _crm(5, status="existing", user_id=assigned_client_id),
        _crm(6, status="existing", user_id=other_client_id),
    ]
    sales = {
        "_id": sales_id,
        "role": "sales",
        "assigned_client_ids": [str(assigned_client_id)],
    }
    res = await business_routes.crm_list(staff=sales, paginate=True)
    assert res["total"] == 4
    assert {row["name"] for row in res["items"]} == {
        "Customer 1", "Customer 2", "Customer 3", "Customer 5"
    }


@pytest.mark.anyio
async def test_crm_sales_without_clients_still_sees_shared_pool_not_other_assignment(db):
    """Empty client assignment must not hide shared leads or leak another sales assignment."""
    sales_id = ObjectId()
    db.crm_customers.rows = [
        _crm(1, status="prospect"),
        _crm(2, status="partnership"),
        _crm(3, status="assigned", assigned_to=ObjectId()),
    ]
    res = await business_routes.crm_list(
        staff={"_id": sales_id, "role": "sales", "assigned_client_ids": []},
        paginate=True,
    )
    assert res["total"] == 2
    assert {row["status"] for row in res["items"]} == {"prospect", "partnership"}


@pytest.mark.anyio
async def test_crm_sales_can_create_prospect_without_user_id(db):
    """Sales must be able to create a prospect that has no linked portal user."""
    sales_id = ObjectId()
    sales = {
        "_id": sales_id,
        "role": "sales",
        "assigned_client_ids": [],
        "name": "Sales A",
    }
    res = await business_routes.crm_create(
        staff=sales,
        payload={"name": "New Lead", "email": "lead@test.id", "status": "prospect"},
    )
    assert res["name"] == "New Lead"
    assert res["status"] == "prospect"
    assert res["user_id"] is None


@pytest.mark.anyio
async def test_crm_sales_can_touch_shared_prospect(db):
    """Sales can update/delete a prospect in the shared pool."""
    sales_id = ObjectId()
    db.crm_customers.rows = [_crm(1, status="prospect")]
    sales = {"_id": sales_id, "role": "sales", "assigned_client_ids": []}
    d = await business_routes._assert_sales_can_touch_crm(
        db, sales, str(db.crm_customers.rows[0]["_id"])
    )
    assert d is not None


@pytest.mark.anyio
async def test_crm_sales_cannot_touch_other_sales_assigned_prospect(db):
    """Sales cannot edit a prospect assigned to another sales."""
    sales_id = ObjectId()
    other_sales_id = ObjectId()
    db.crm_customers.rows = [
        _crm(1, status="assigned", assigned_to=other_sales_id),
    ]
    sales = {"_id": sales_id, "role": "sales", "assigned_client_ids": []}
    with pytest.raises(Exception) as exc_info:
        await business_routes._assert_sales_can_touch_crm(
            db, sales, str(db.crm_customers.rows[0]["_id"])
        )
    assert "403" in str(exc_info.value) or "Not your" in str(exc_info.value)


@pytest.mark.anyio
async def test_crm_search_autocomplete(db, admin):
    """CRM search endpoint returns lightweight rows for autocomplete."""
    db.crm_customers.rows = [
        _crm(1, name="Budi Santoso", email="budi@test.id", phone="0811"),
        _crm(2, name="Siti Aminah", email="siti@test.id", phone="0812"),
        _crm(3, name="Budi Hartono", email="budi_h@test.id", phone="0813"),
    ]
    res = await business_routes.crm_search(staff=admin, q="budi")
    assert len(res) == 2
    assert all("budi" in r["name"].lower() or "budi" in r["email"].lower()
               for r in res)
    # Each row must have id, name, email, phone, company, status
    for r in res:
        assert all(k in r for k in
                   ("id", "name", "email", "phone", "company", "status"))


@pytest.mark.anyio
async def test_crm_export_uses_crm_scope(db):
    """CRM XLSX export must respect the shared-pool scope, not strict sales filter."""
    sales_id = ObjectId()
    db.crm_customers.rows = [
        _crm(1, status="prospect"),
        _crm(2, status="existing", user_id=ObjectId()),
    ]
    sales = {"_id": sales_id, "role": "sales", "assigned_client_ids": []}
    # Export calls find with scope filter; verify prospect is visible
    docs = await business_routes._crm_export_queryset(db, sales)
    assert len(docs) == 1
    assert docs[0]["status"] == "prospect"



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
async def test_followups_create_claims_shared_prospect(db):
    """Creating a follow-up for a shared prospect must claim it atomically."""
    sales_id = ObjectId()
    crm_id = ObjectId()
    db.crm_customers.rows = [
        _crm(1, _id=crm_id, status="prospect", user_id=None),
    ]
    db.followups.rows = []
    sales = {
        "_id": sales_id,
        "role": "sales",
        "assigned_client_ids": [],
        "name": "Sales A",
    }
    res = await business_routes.followups_create(
        staff=sales,
        payload={"customer_id": str(crm_id), "task": "Call prospect", "due_date": "2026-08-25"},
    )
    assert res["customer_id"] == str(crm_id)
    # CRM row must now be "assigned" to this sales
    crm = await db.crm_customers.find_one({"_id": crm_id})
    assert crm["status"] == "assigned"
    assert crm["assigned_to"] == sales_id
    assert crm["assigned_at"] is not None
    assert crm["assignment_expires_at"] is not None


@pytest.mark.anyio
async def test_followups_create_keeps_partnership_shared(db):
    """Possible partnership must stay shared: a follow-up never claims it."""
    sales_id = ObjectId()
    crm_id = ObjectId()
    db.crm_customers.rows = [_crm(1, _id=crm_id, status="partnership", user_id=None)]
    db.followups.rows = []
    sales = {"_id": sales_id, "role": "sales", "assigned_client_ids": [], "name": "Sales A"}
    await business_routes.followups_create(
        staff=sales,
        payload={"customer_id": str(crm_id), "task": "Explore partnership"},
    )
    crm = await db.crm_customers.find_one({"_id": crm_id})
    assert crm["status"] == "partnership"
    assert crm.get("assigned_to") is None


@pytest.mark.anyio
async def test_followups_create_second_sales_loses_claim_race(db):
    """Only one sales may win the claim; the loser must be rejected."""
    crm_id = ObjectId()
    db.crm_customers.rows = [_crm(1, _id=crm_id, status="prospect", user_id=None)]
    db.followups.rows = []
    first = {"_id": ObjectId(), "role": "sales", "assigned_client_ids": [], "name": "Sales A"}
    second = {"_id": ObjectId(), "role": "sales", "assigned_client_ids": [], "name": "Sales B"}
    await business_routes.followups_create(
        staff=first, payload={"customer_id": str(crm_id), "task": "First call"},
    )
    with pytest.raises(Exception) as exc_info:
        await business_routes.followups_create(
            staff=second, payload={"customer_id": str(crm_id), "task": "Second call"},
        )
    assert "403" in str(exc_info.value) or "sales lain" in str(exc_info.value).lower()
    crm = await db.crm_customers.find_one({"_id": crm_id})
    assert str(crm["assigned_to"]) == str(first["_id"])


@pytest.mark.anyio
async def test_followups_create_rejects_already_assigned_prospect(db):
    """Cannot create a follow-up for a prospect already assigned to another sales."""
    sales_id = ObjectId()
    crm_id = ObjectId()
    db.crm_customers.rows = [
        _crm(1, _id=crm_id, status="assigned", assigned_to=ObjectId()),
    ]
    sales = {"_id": sales_id, "role": "sales", "assigned_client_ids": [], "name": "Sales A"}
    with pytest.raises(Exception) as exc_info:
        await business_routes.followups_create(
            staff=sales,
            payload={"customer_id": str(crm_id), "task": "Call", "due_date": "2026-08-25"},
        )
    assert "403" in str(exc_info.value) or "assigned" in str(exc_info.value).lower()


@pytest.mark.anyio
async def test_followups_update_renews_assignment_expiry(db):
    """Any update to a follow-up must renew the assignment expiry."""
    sales_id = ObjectId()
    crm_id = ObjectId()
    old_expiry = "2026-08-15T00:00:00Z"
    db.crm_customers.rows = [
        _crm(1, _id=crm_id, status="assigned", assigned_to=sales_id,
             assigned_at="2026-08-10T00:00:00Z", assignment_expires_at=old_expiry),
    ]
    fu_id = ObjectId()
    db.followups.rows = [
        _followup(1, _id=fu_id, customer_id=crm_id, done=False),
    ]
    sales = {"_id": sales_id, "role": "sales", "assigned_client_ids": [], "name": "Sales A"}
    await business_routes.followups_update(
        fid=str(fu_id), payload={"task": "Updated task"}, staff=sales,
    )
    crm = await db.crm_customers.find_one({"_id": crm_id})
    assert crm["assignment_expires_at"] != old_expiry


@pytest.mark.anyio
async def test_followups_create_with_production_auth_shape(db):
    """Regression: staff with `id` (not `_id`) must claim and own a follow-up.

    Real JWT auth (auth.py:95) does `user["id"] = str(user.pop("_id"))`.
    Before the _staff_oid fix, code that used `staff.get("_id")` got None
    in production, causing "Not your follow-up" 403 after a successful save.
    """
    sales_id = ObjectId()
    crm_id = ObjectId()
    db.crm_customers.rows = [_crm(1, _id=crm_id, status="prospect", user_id=None)]
    db.followups.rows = []
    # Production auth shape: `id` string, no `_id`
    sales = {"id": str(sales_id), "role": "sales", "assigned_client_ids": [], "name": "Sales A"}
    res = await business_routes.followups_create(
        staff=sales,
        payload={"customer_id": str(crm_id), "task": "Call prospect", "due_date": "2026-08-25"},
    )
    assert res["customer_id"] == str(crm_id)
    crm = await db.crm_customers.find_one({"_id": crm_id})
    assert crm["status"] == "assigned"
    assert str(crm["assigned_to"]) == str(sales_id)


@pytest.mark.anyio
async def test_followups_update_with_production_auth_shape(db):
    """Regression: staff with `id` (not `_id`) must pass _assert_sales_can_touch_followup.

    The old code path used staff.get("_id") for visibility/ownership checks.
    In production, that returned None, so sales users got 403 "Not your
    follow-up" immediately after saving. This test proves the fix.
    """
    sales_id = ObjectId()
    crm_id = ObjectId()
    db.crm_customers.rows = [
        _crm(1, _id=crm_id, status="assigned", assigned_to=sales_id),
    ]
    fu_id = ObjectId()
    db.followups.rows = [_followup(1, _id=fu_id, customer_id=crm_id, done=False)]
    # Production auth shape: `id` string, no `_id`
    sales = {"id": str(sales_id), "role": "sales", "assigned_client_ids": [], "name": "Sales A"}
    await business_routes.followups_update(
        fid=str(fu_id), payload={"task": "Updated task"}, staff=sales,
    )
    d = await db.followups.find_one({"_id": fu_id})
    assert d["task"] == "Updated task"


@pytest.mark.anyio
async def test_followups_mark_done_releases_prospect(db):
    """Marking a follow-up as done must release the prospect back to shared pool."""
    sales_id = ObjectId()
    crm_id = ObjectId()
    db.crm_customers.rows = [
        _crm(1, _id=crm_id, status="assigned", assigned_to=sales_id),
    ]
    fu_id = ObjectId()
    db.followups.rows = [
        _followup(1, _id=fu_id, customer_id=crm_id, done=False),
    ]
    sales = {"_id": sales_id, "role": "sales", "assigned_client_ids": [], "name": "Sales A"}
    await business_routes.followups_update(
        fid=str(fu_id), payload={"done": True}, staff=sales,
    )
    crm = await db.crm_customers.find_one({"_id": crm_id})
    assert crm["status"] == "prospect"
    assert crm.get("assigned_to") is None
    assert crm.get("assigned_at") is None
    assert crm.get("assignment_expires_at") is None


@pytest.mark.anyio
async def test_followups_sales_scope_includes_followups_on_own_assigned_prospects(db):
    """Sales must see follow-ups on prospects they claimed (assigned_to=their id)."""
    sales_id = ObjectId()
    crm_id = ObjectId()
    db.crm_customers.rows = [
        _crm(1, _id=crm_id, status="assigned", assigned_to=sales_id, user_id=None),
    ]
    db.followups.rows = [
        _followup(1, customer_id=crm_id),
    ]
    sales = {
        "_id": sales_id,
        "role": "sales",
        "assigned_client_ids": [],
    }
    res = await business_routes.followups_list(staff=sales, paginate=True)
    assert res["total"] == 1


# ============================================================
# Follow-ups: notes, role tags, approvals, close-deal
# ============================================================

@pytest.mark.anyio
async def test_followup_request_approval(db, admin):
    """Sales can request an approval targeted at a role."""
    fu_id = ObjectId()
    db.crm_customers.rows = []
    db.followups.rows = [_followup(1, _id=fu_id)]
    res = await business_routes.followup_approval_request(
        fid=str(fu_id),
        payload={"target_role": "finance", "message": "Need approval for discount"},
        staff=admin,
    )
    assert res["status"] == "pending"
    assert res["target_role"] == "finance"
    assert "discount" in res["message"]
    assert res["requested_by"] is not None


@pytest.mark.anyio
async def test_followup_approval_accept(db, admin):
    """Finance can accept a pending approval."""
    fu_id = ObjectId()
    db.crm_customers.rows = []
    approval = {
        "id": ObjectId(),
        "requested_by": "Sales A",
        "requested_role": "sales",
        "target_role": "finance",
        "target_user_id": None,
        "message": "Discount 10%",
        "status": "pending",
        "responded_by": "",
        "responded_at": "",
        "response_note": "",
        "created_at": "2026-08-20T00:00:00Z",
    }
    db.followups.rows = [_followup(1, _id=fu_id, approvals=[approval])]
    res = await business_routes.followup_approval_respond(
        fid=str(fu_id), aid=str(approval["id"]), staff={"role": "finance", "name": "Finance 1"},
        payload={"response": "accepted", "note": "OK"},
    )
    assert res["status"] == "accepted"
    assert res["responded_by"] == "Finance 1"
    assert res["response_note"] == "OK"


@pytest.mark.anyio
async def test_followup_approval_reject(db, admin):
    """Finance can reject a pending approval."""
    fu_id = ObjectId()
    db.crm_customers.rows = []
    approval = {
        "id": ObjectId(),
        "requested_by": "Sales A",
        "requested_role": "sales",
        "target_role": "finance",
        "target_user_id": None,
        "message": "Extra credit",
        "status": "pending",
        "responded_by": "",
        "responded_at": "",
        "response_note": "",
        "created_at": "2026-08-20T00:00:00Z",
    }
    db.followups.rows = [_followup(1, _id=fu_id, approvals=[approval])]
    res = await business_routes.followup_approval_respond(
        fid=str(fu_id), aid=str(approval["id"]), staff={"role": "finance", "name": "Finance 1"},
        payload={"response": "rejected", "note": "Budget insufficient"},
    )
    assert res["status"] == "rejected"
    assert res["response_note"] == "Budget insufficient"


@pytest.mark.anyio
async def test_followup_approval_wrong_role_rejected(db, admin):
    """Only the target role (or admin) can respond to an approval."""
    fu_id = ObjectId()
    db.crm_customers.rows = []
    approval = {
        "id": ObjectId(),
        "requested_by": "Sales A",
        "requested_role": "sales",
        "target_role": "finance",
        "target_user_id": None,
        "message": "Discount",
        "status": "pending",
        "responded_by": "",
        "responded_at": "",
        "response_note": "",
        "created_at": "2026-08-20T00:00:00Z",
    }
    db.followups.rows = [_followup(1, _id=fu_id, approvals=[approval])]
    with pytest.raises(Exception) as exc_info:
        await business_routes.followup_approval_respond(
            fid=str(fu_id), aid=str(approval["id"]), staff={"role": "noc", "name": "NOC 1"},
            payload={"response": "accepted", "note": ""},
        )
    assert "403" in str(exc_info.value) or "not authorized" in str(exc_info.value).lower()


@pytest.mark.anyio
async def test_followup_close_deal_generates_registration_link(db, admin):
    """Close-deal must generate a signed registration token/link and mark the CRM row."""
    fu_id = ObjectId()
    crm_id = ObjectId()
    db.crm_customers.rows = [_crm(1, _id=crm_id, status="assigned", assigned_to=ObjectId())]
    db.followups.rows = [_followup(1, _id=fu_id, customer_id=crm_id)]
    res = await business_routes.followup_close_deal(fid=str(fu_id), staff=admin)
    assert res["deal_action"] == "close_deal"
    assert res["deal_registration_link"]
    assert "crm_token=" in res["deal_registration_link"]
    fu = await db.followups.find_one({"_id": fu_id})
    assert fu["deal_action"] == "close_deal"
    assert fu["deal_registration_link"]


@pytest.mark.anyio
async def test_followup_close_deal_requires_linked_customer(db, admin):
    """Close-deal without a linked CRM customer must fail loudly."""
    fu_id = ObjectId()
    db.crm_customers.rows = []
    db.followups.rows = [_followup(1, _id=fu_id, customer_id=None)]
    with pytest.raises(Exception) as exc_info:
        await business_routes.followup_close_deal(fid=str(fu_id), staff=admin)
    assert "400" in str(exc_info.value) or "customer" in str(exc_info.value).lower()


@pytest.mark.anyio
async def test_close_deal_registration_token_roundtrip(db):
    """A close-deal token must decode back to the originating CRM id."""
    crm_id = ObjectId()
    token = business_routes._make_crm_registration_token(str(crm_id))
    decoded_crm_id = business_routes._verify_crm_registration_token(token)
    assert decoded_crm_id == str(crm_id)


@pytest.mark.anyio
async def test_close_deal_registration_token_rejects_tampering(db):
    """A tampered/garbage token must not verify."""
    with pytest.raises(Exception):
        business_routes._verify_crm_registration_token("not-a-real-token")


@pytest.mark.anyio
async def test_register_with_crm_token_syncs_matching_customer(db):
    """Registering with a valid crm_token and matching email must sync the
    CRM row to 'existing' and link the new user_id, not create a duplicate."""
    crm_id = ObjectId()
    db.crm_customers.rows = [
        _crm(1, _id=crm_id, status="assigned", email="lead@test.id", name="Budi Lead"),
    ]
    token = business_routes._make_crm_registration_token(str(crm_id))
    new_user_id = ObjectId()
    await business_routes.sync_crm_after_registration(
        db, crm_token=token, new_user_id=new_user_id,
        reg_email="lead@test.id", reg_name="Budi Lead",
    )
    crm = await db.crm_customers.find_one({"_id": crm_id})
    assert crm["status"] == "existing"
    assert crm["user_id"] == new_user_id
    assert crm.get("assigned_to") is None


@pytest.mark.anyio
async def test_register_with_crm_token_mismatch_leaves_crm_untouched(db):
    """If the registered email/name differs from the CRM row, treat as a new
    customer and leave the original CRM prospect untouched (no silent merge)."""
    crm_id = ObjectId()
    db.crm_customers.rows = [
        _crm(1, _id=crm_id, status="assigned", email="lead@test.id", name="Budi Lead"),
    ]
    token = business_routes._make_crm_registration_token(str(crm_id))
    new_user_id = ObjectId()
    await business_routes.sync_crm_after_registration(
        db, crm_token=token, new_user_id=new_user_id,
        reg_email="different@test.id", reg_name="Different Person",
    )
    crm = await db.crm_customers.find_one({"_id": crm_id})
    assert crm["status"] == "assigned"
    assert crm.get("user_id") is None


@pytest.mark.anyio
async def test_public_crm_prefill_endpoint_returns_crm_data(db):
    """Public endpoint to prefill registration form from valid crm_token."""
    crm_id = ObjectId()
    db.crm_customers.rows = [
        _crm(1, _id=crm_id, status="assigned", email="lead@test.id", name="Budi Lead",
             phone="08123456789", company="PT Lead"),
    ]
    token = business_routes._make_crm_registration_token(str(crm_id))
    res = await business_routes.crm_register_prefill(staff=None, token=token)
    assert res["email"] == "lead@test.id"
    assert res["name"] == "Budi Lead"
    assert res["phone"] == "08123456789"
    assert res["company"] == "PT Lead"


@pytest.mark.anyio
async def test_public_crm_prefill_invalid_token_rejected(db):
    """Invalid/expired token must be rejected."""
    with pytest.raises(Exception) as exc_info:
        await business_routes.crm_register_prefill(staff=None, token="invalid")
    assert "400" in str(exc_info.value) or "invalid" in str(exc_info.value).lower()


@pytest.mark.anyio
async def test_expire_overdue_assignments_releases_expired_only(db):
    """The expiry job must release overdue assignments but keep fresh ones."""
    sales_id = ObjectId()
    crm_id = ObjectId()
    fresh_id = ObjectId()
    db.crm_customers.rows = [
        _crm(1, _id=crm_id, status="assigned", assigned_to=sales_id,
             assignment_expires_at="2020-01-01T00:00:00Z"),
        _crm(2, _id=fresh_id, status="assigned", assigned_to=sales_id,
             assignment_expires_at="2999-01-01T00:00:00Z"),
    ]
    await business_routes.expire_overdue_assignments(
        db, now_iso="2026-08-20T00:00:00Z",
    )
    expired = await db.crm_customers.find_one({"_id": crm_id})
    fresh = await db.crm_customers.find_one({"_id": fresh_id})
    assert expired["status"] == "prospect"
    assert expired.get("assigned_to") is None
    assert expired.get("assignment_expires_at") is None
    assert fresh["status"] == "assigned"
    assert fresh.get("assigned_to") == sales_id


@pytest.mark.anyio
async def test_expire_overdue_assignments_skips_non_assigned(db):
    """Existing clients and shared leads must not be touched by the job."""
    existing_uid = ObjectId()
    db.crm_customers.rows = [
        _crm(1, status="existing", user_id=existing_uid,
             assignment_expires_at="2020-01-01T00:00:00Z"),
        _crm(2, status="prospect", assignment_expires_at="2020-01-01T00:00:00Z"),
    ]
    await business_routes.expire_overdue_assignments(
        db, now_iso="2026-08-20T00:00:00Z",
    )
    assert db.crm_customers.rows[0]["status"] == "existing"
    assert db.crm_customers.rows[1]["status"] == "prospect"


@pytest.mark.anyio
async def test_followup_serialize_includes_approvals(db, admin):
    """Serialized follow-up must include approvals array."""
    fu_id = ObjectId()
    db.crm_customers.rows = []
    db.followups.rows = [
        _followup(1, _id=fu_id, approvals=[{"id": ObjectId(), "status": "pending", "target_role": "finance"}])
    ]
    res = await business_routes.followups_list(staff=admin)
    row = next(r for r in res if r["id"] == str(fu_id))
    assert len(row["approvals"]) == 1
    assert row["approvals"][0]["target_role"] == "finance"
    assert row["approvals"][0]["status"] == "pending"


@pytest.mark.anyio
async def test_followup_notes_append_to_own_role(db, admin):
    """Adding a note appends to the caller's own role thread."""
    fu_id = ObjectId()
    db.crm_customers.rows = []
    db.followups.rows = [_followup(1, _id=fu_id)]
    res = await business_routes.followup_notes_add(
        fid=str(fu_id),
        payload={"text": "Interested in fiber"},
        staff=admin,
    )
    assert len(res["notes"]["admin"]) == 1
    assert res["notes"]["admin"][0]["text"] == "Interested in fiber"
    assert res["notes"]["admin"][0]["author_role"] == "admin"
    assert res["notes"]["admin"][0]["legacy"] is False
    # persisted
    d = await db.followups.find_one({"_id": fu_id})
    assert d["notes"]["admin"][0]["text"] == "Interested in fiber"


@pytest.mark.anyio
async def test_followup_notes_update_endpoint_rejects_notes(db, admin):
    """The generic update endpoint must refuse notes rewrites outright."""
    fu_id = ObjectId()
    db.crm_customers.rows = []
    db.followups.rows = [_followup(1, _id=fu_id)]
    with pytest.raises(Exception) as exc_info:
        await business_routes.followups_update(
            fid=str(fu_id),
            payload={"notes": {"sales": "Interested in fiber"}},
            staff=admin,
        )
    assert "400" in str(exc_info.value)


@pytest.mark.anyio
async def test_followup_notes_thread_is_append_only_across_roles(db, admin):
    """A note posted as one role must never overwrite another role's thread.

    This is the core fix: the author role is derived from the caller, so the
    request body cannot inject content into another division's bucket, and
    existing entries are preserved (append-only).
    """
    fu_id = ObjectId()
    db.crm_customers.rows = []
    db.followups.rows = [
        _followup(1, _id=fu_id, notes={"support": "Existing support note"})
    ]
    # admin appends into admin thread; support thread is untouched, legacy preserved
    res = await business_routes.followup_notes_add(
        fid=str(fu_id),
        payload={"text": "Admin follow-up", "author_role": "support"},  # body role ignored
        staff=admin,
    )
    assert res["notes"]["admin"][0]["text"] == "Admin follow-up"
    assert res["notes"]["admin"][0]["author_role"] == "admin"
    # existing support (legacy) note still present and not overwritten
    assert len(res["notes"]["support"]) == 1
    assert res["notes"]["support"][0]["text"] == "Existing support note"
    assert res["notes"]["support"][0]["legacy"] is True


@pytest.mark.anyio
async def test_followup_role_tags_set(db, admin):
    """Follow-up must accept and persist role_tags list."""
    fu_id = ObjectId()
    db.crm_customers.rows = []
    db.followups.rows = [_followup(1, _id=fu_id)]
    await business_routes.followups_update(
        fid=str(fu_id),
        payload={"role_tags": ["sales", "support"]},
        staff=admin,
    )
    d = await db.followups.find_one({"_id": fu_id})
    assert set(d["role_tags"]) == {"sales", "support"}


@pytest.mark.anyio
async def test_followup_role_tags_invalid_value_rejected(db, admin):
    """role_tags must only accept known roles."""
    fu_id = ObjectId()
    db.crm_customers.rows = []
    db.followups.rows = [_followup(1, _id=fu_id)]
    with pytest.raises(Exception) as exc_info:
        await business_routes.followups_update(
            fid=str(fu_id),
            payload={"role_tags": ["sales", "hacker"]},
            staff=admin,
        )
    assert "400" in str(exc_info.value) or "invalid" in str(exc_info.value).lower()


@pytest.mark.anyio
async def test_followup_serialize_includes_notes_and_tags(db, admin):
    """Serialized follow-up must include a per-role note thread and role_tags list.

    Legacy plain-string notes are normalized into a one-entry thread marked
    legacy=True; the thread shape is stable across all known roles.
    """
    fu_id = ObjectId()
    db.crm_customers.rows = []
    db.followups.rows = [
        _followup(1, _id=fu_id, notes={"sales": "Hi"}, role_tags=["sales"])
    ]
    res = await business_routes.followups_list(staff=admin)
    row = next(r for r in res if r["id"] == str(fu_id))
    assert set(row["notes"].keys()) == business_routes._FOLLOWUP_ROLES
    assert len(row["notes"]["sales"]) == 1
    assert row["notes"]["sales"][0]["text"] == "Hi"
    assert row["notes"]["sales"][0]["legacy"] is True
    assert row["notes"]["support"] == []
    assert row["role_tags"] == ["sales"]


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


# ============================================================
# Follow-up structured tags and visibility
# ============================================================
@pytest.mark.anyio
async def test_followups_visibility_requires_matching_tag_or_owner(db):
    finance_id = ObjectId()
    other_finance_id = ObjectId()
    db.followups.rows = [
        _followup(1, owner_id=str(ObjectId()), tags=[]),
        _followup(2, owner_id=str(ObjectId()), tags=[
            {"scope": "role", "value": "finance", "label": "finance"},
        ]),
        _followup(3, owner_id=str(ObjectId()), tags=[
            {"scope": "user", "value": str(finance_id), "label": "Finance A"},
        ]),
        _followup(4, owner_id=str(finance_id), tags=[]),
        _followup(5, owner_id=str(ObjectId()), tags=[
            {"scope": "user", "value": str(other_finance_id), "label": "Finance B"},
        ]),
    ]
    finance = {"id": str(finance_id), "role": "finance"}
    res = await business_routes.followups_list(staff=finance)
    assert {row["task"] for row in res} == {"Follow up 2", "Follow up 3", "Follow up 4"}


@pytest.mark.anyio
async def test_followup_tag_removal_locked_until_done(db, admin):
    fu_id = ObjectId()
    original = {"scope": "role", "value": "finance", "label": "finance"}
    db.followups.rows = [_followup(1, _id=fu_id, tags=[original], role_tags=["finance"])]
    with pytest.raises(Exception) as exc_info:
        await business_routes.followups_update(
            fid=str(fu_id), payload={"tags": []}, staff=admin,
        )
    assert "400" in str(exc_info.value)

    result = await business_routes.followups_update(
        fid=str(fu_id), payload={"done": True, "tags": []}, staff=admin,
    )
    assert result["done"] is True
    assert result["tags"] == []


@pytest.mark.anyio
async def test_followups_taggable_staff_excludes_noc(db, admin):
    finance_id = ObjectId()
    db.users.rows = [
        {"_id": finance_id, "name": "Finance A", "email": "finance@example.test", "role": "finance"},
        {"_id": ObjectId(), "name": "Support A", "email": "support@example.test", "role": "support"},
        {"_id": ObjectId(), "name": "NOC legacy", "email": "noc@example.test", "role": "noc"},
    ]
    result = await business_routes.followups_taggable_staff(staff=admin)
    assert result["roles"] == ["admin", "finance", "sales", "support"]
    assert "noc" not in result["staff_by_role"]
    assert result["staff_by_role"]["finance"] == [{
        "id": str(finance_id), "name": "Finance A", "email": "finance@example.test", "role": "finance",
    }]


@pytest.mark.anyio
async def test_close_deal_link_is_absolute_and_not_double_portal(db, admin, monkeypatch):
    """The close-deal registration link must be a full absolute URL to the
    public portal register page, with exactly one /portal segment (no bare
    relative path, no doubled /portal/portal)."""
    monkeypatch.delenv("PORTAL_FRONTEND_URL", raising=False)
    fu_id = ObjectId()
    crm_id = ObjectId()
    db.crm_customers.rows = [_crm(1, _id=crm_id, status="assigned", assigned_to=ObjectId())]
    db.followups.rows = [_followup(1, _id=fu_id, customer_id=crm_id)]
    res = await business_routes.followup_close_deal(fid=str(fu_id), staff=admin)
    link = res["deal_registration_link"]
    assert link.startswith("https://"), f"link not absolute: {link}"
    assert link.count("/portal") == 1, f"portal segment count wrong: {link}"
    assert "/portal/register?crm_token=" in link, f"wrong register path: {link}"


@pytest.mark.anyio
async def test_close_deal_link_respects_env_override(db, admin, monkeypatch):
    """When PORTAL_FRONTEND_URL is set, it is used verbatim as the base."""
    monkeypatch.setenv("PORTAL_FRONTEND_URL", "https://portal.example.id")
    fu_id = ObjectId()
    crm_id = ObjectId()
    db.crm_customers.rows = [_crm(1, _id=crm_id, status="assigned", assigned_to=ObjectId())]
    db.followups.rows = [_followup(1, _id=fu_id, customer_id=crm_id)]
    res = await business_routes.followup_close_deal(fid=str(fu_id), staff=admin)
    link = res["deal_registration_link"]
    assert link.startswith("https://portal.example.id/portal/register?crm_token="), link


@pytest.mark.anyio
async def test_followups_delete_denied_for_sales(db):
    """Sales must not be able to delete follow-ups; only admin/owner/support."""
    fu_id = ObjectId()
    db.followups.rows = [_followup(1, _id=fu_id)]
    sales = {"id": str(ObjectId()), "role": "sales", "assigned_client_ids": []}
    with pytest.raises(Exception) as exc_info:
        await business_routes.followups_delete(fid=str(fu_id), staff=sales)
    assert "403" in str(exc_info.value)
    # Row still present (not deleted)
    assert await db.followups.find_one({"_id": fu_id}) is not None


@pytest.mark.anyio
async def test_followups_delete_denied_for_finance(db):
    """Finance must not be able to delete follow-ups either."""
    fu_id = ObjectId()
    db.followups.rows = [_followup(1, _id=fu_id)]
    finance = {"id": str(ObjectId()), "role": "finance"}
    with pytest.raises(Exception) as exc_info:
        await business_routes.followups_delete(fid=str(fu_id), staff=finance)
    assert "403" in str(exc_info.value)
    assert await db.followups.find_one({"_id": fu_id}) is not None


@pytest.mark.anyio
async def test_followups_delete_allowed_for_support(db):
    """Support is explicitly allowed to delete follow-ups."""
    fu_id = ObjectId()
    db.followups.rows = [_followup(1, _id=fu_id)]
    support = {"id": str(ObjectId()), "role": "support"}
    res = await business_routes.followups_delete(fid=str(fu_id), staff=support)
    assert res["deleted"] == 1
    assert await db.followups.find_one({"_id": fu_id}) is None


@pytest.mark.anyio
async def test_followups_delete_allowed_for_admin(db, admin):
    """Admin is allowed to delete follow-ups."""
    fu_id = ObjectId()
    db.followups.rows = [_followup(1, _id=fu_id)]
    res = await business_routes.followups_delete(fid=str(fu_id), staff=admin)
    assert res["deleted"] == 1
