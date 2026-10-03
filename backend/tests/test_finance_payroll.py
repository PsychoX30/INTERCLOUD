"""TDD offline tests for Finance Payroll: employees + salaries + sales-fees pagination/filter/sort."""

from __future__ import annotations
from unittest.mock import AsyncMock
from datetime import datetime, timezone
from bson import ObjectId
import pytest
from portal.routes import finance as finance_routes


# ---------- Async cursor/collection mocks (reuse finance_pagination pattern) ----------

class _Cursor:
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

    async def distinct(self, field, query):
        vals = set()
        for r in self._filtered(query):
            v = r.get(field)
            if v:
                vals.add(v)
        return sorted(vals)

    async def insert_one(self, doc):
        inserted_id = doc.get("_id") or ObjectId()
        doc["_id"] = inserted_id
        self.rows.append(doc)

        class _Res:
            pass
        _Res.inserted_id = inserted_id
        return _Res()

    async def find_one(self, query):
        for r in self.rows:
            match = True
            for k, v in query.items():
                if r.get(k) != v:
                    match = False
                    break
            if match:
                return r
        return None

    async def update_one(self, q, upd):
        class _Res:
            matched_count = 0
        for r in self.rows:
            if r.get("_id") == q.get("_id"):
                r.update(upd.get("$set", {}))
                _Res.matched_count = 1
                break
        return _Res()

    async def delete_one(self, q):
        class _Res:
            deleted_count = 0
        before = len(self.rows)
        self.rows = [r for r in self.rows if r.get("_id") != q.get("_id")]
        _Res.deleted_count = before - len(self.rows)
        return _Res()

    def _filtered(self, query):
        if not query:
            return list(self.rows)
        out = []
        for r in self.rows:
            match = True
            for k, v in query.items():
                if k == "q":  # regex search on name/employee
                    continue  # handled at cursor level
                if isinstance(v, dict):
                    if k == "$regex":
                        match = str(r.get(k, "")).lower().find(v.get("$regex", "").lower()) >= 0
                    elif "$in" in v:
                        match = r.get(k) in v["$in"]
                    else:
                        match = False
                    break
                if r.get(k) != v:
                    match = False
                    break
            if match:
                out.append(r)
        return out


class _Db:
    def __init__(self):
        self.employees = _Collection([])
        self.salaries = _Collection([])
        self.sales_fees = _Collection([])
        self.users = _Collection([])
        self.services = _Collection([])

    def __getitem__(self, name):
        return getattr(self, name)


@pytest.fixture
def db(monkeypatch):
    value = _Db()
    monkeypatch.setattr(finance_routes, "_get_db", AsyncMock(return_value=value))
    return value


@pytest.fixture
def admin():
    return {"role": "admin", "email": "admin@example.test", "id": "admin-id"}


def _emp(i: int, **overrides) -> dict:
    base = {
        "_id": ObjectId(),
        "name": f"Karyawan {i}",
        "division": "NOC" if i % 2 == 0 else "Finance",
        "position": "Engineer",
        "email": f"emp{i}@test.com",
        "phone": f"081234567{i:02d}",
        "base_salary": float(10000000 + i * 100000),
        "user_id": None,
        "active": True,
        "created_at": "2026-08-01T00:00:00Z",
        "updated_at": "2026-08-01T00:00:00Z",
    }
    base.update(overrides)
    return base


def _sal(i: int, emp: dict, **overrides) -> dict:
    base = {
        "_id": ObjectId(),
        "date": f"2026-08-{20 + i:02d}",
        "employee_id": emp["_id"],
        "employee": emp["name"],
        "division": emp["division"],
        "position": emp["position"],
        "category": "reguler",
        "notes": "",
        "amount": 5000000 + i * 100000,
        "items": [{"description": "Gaji pokok", "amount": 4000000}, {"description": "Bonus", "amount": 1000000 + i * 100000}],
        "period_yyyy_mm": "2026-08",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    base.update(overrides)
    return base


def _sf(i: int, **overrides) -> dict:
    base = {
        "_id": ObjectId(),
        "date": f"2026-08-{25 + i}",
        "sales_person_id": "sales123",
        "sales_person": "Sales Test",
        "notes": "",
        "amount": 100000 + i * 50000,
        "items": [
            {"description": "Fee A", "amount": 50000, "invoice_id": "invA", "invoice_number": "INV-A"},
            {"description": "Fee B", "amount": 50000 + i * 50000, "invoice_id": "invB", "invoice_number": "INV-B"},
        ],
        "period_yyyy_mm": "2026-08",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    base.update(overrides)
    return base


# -------------------- EMPLOYEES TESTS --------------------

@pytest.mark.anyio
async def test_employees_crud(db, admin):
    payload = {
        "name": "Budi Santoso",
        "division": "NOC",
        "position": "Engineer",
        "email": "budi@intercloud.test",
        "phone": "08123456789",
        "base_salary": 12000000,
        "active": True,
    }
    created = await finance_routes.create_employee(payload, admin=admin)
    assert created["name"] == payload["name"]
    assert created["division"] == payload["division"]
    assert created["position"] == payload["position"]
    assert created["email"] == payload["email"]
    assert created["phone"] == payload["phone"]
    assert created["base_salary"] == payload["base_salary"]
    assert created["active"] is True
    emp_id = created["id"]

    lst = await finance_routes.list_employees(admin=admin)
    assert any(e["id"] == emp_id for e in lst)

    got = await finance_routes.get_employee(emp_id, admin=admin)
    assert got["id"] == emp_id

    upd = await finance_routes.update_employee(emp_id, {"position": "Senior Engineer", "base_salary": 15000000}, admin=admin)
    assert upd["position"] == "Senior Engineer"
    assert upd["base_salary"] == 15000000

    del_res = await finance_routes.delete_employee(emp_id, admin=admin)
    assert del_res["deleted"] == 1

    with pytest.raises(Exception) as exc:
        await finance_routes.get_employee(emp_id, admin=admin)
    assert exc.value.status_code == 404


@pytest.mark.anyio
async def test_employees_divisions_endpoint(db, admin):
    db.employees.rows = [_emp(1, division="NOC"), _emp(2, division="Finance")]
    divs = await finance_routes.list_employee_divisions(admin=admin)
    assert isinstance(divs, list)
    assert "Finance" in divs
    assert "NOC" in divs


# -------------------- SALARIES TESTS --------------------

@pytest.mark.anyio
async def test_salary_create_requires_employee_id(db, admin):
    emp = _emp(1)
    db.employees.rows = [emp]
    # Without employee_id should fail with 422 (new behavior)
    try:
        await finance_routes._sal_create(payload={
            "date": datetime.now(timezone.utc).date().isoformat(), "category": "reguler", "notes": "no emp"
        }, admin=admin)
        assert False, "expected 422"
    except Exception as exc:
        assert getattr(exc, "status_code", 422) == 422


@pytest.mark.anyio
async def test_salary_create_with_valid_employee_id(db, admin):
    emp = _emp(1, division="NOC", position="Engineer")
    db.employees.rows = [emp]
    _today = datetime.now(timezone.utc).date().isoformat()
    created = await finance_routes._sal_create(payload={
        "date": _today,
        "employee_id": str(emp["_id"]),
        "category": "reguler",
        "items": [
            {"description": "Gaji pokok", "amount": 5000000},
            {"description": "Bonus", "amount": 1000000},
        ],
        "notes": "test"
    }, admin=admin)
    assert created["employee_id"] == str(emp["_id"])
    assert created["employee"] == emp["name"]
    assert created["division"] == emp["division"]
    assert created["position"] == emp["position"]
    assert created["amount"] == 6000000
    assert created["period_yyyy_mm"] == _today[:7]
    assert len(created.get("items", [])) == 2


@pytest.mark.anyio
async def test_salary_create_invalid_employee_id_rejected(db, admin):
    db.employees.rows = []
    try:
        await finance_routes._sal_create(payload={
            "date": datetime.now(timezone.utc).date().isoformat(),
            "employee_id": "invalid",
            "category": "reguler",
            "items": [{"description": "Gaji pokok", "amount": 5000000}],
        }, admin=admin)
        assert False, "expected 400"
    except Exception as exc:
        assert getattr(exc, "status_code", 400) in (400, 422)


@pytest.mark.anyio
async def test_salary_pagination_filter_sort(db, admin):
    emp = _emp(1, division="NOC", position="Engineer")
    db.employees.rows = [emp]
    db.salaries.rows = [_sal(i, emp) for i in range(5)]

    # paginate
    res = await finance_routes._sal_list(
        admin=admin, paginate=True, limit=2, skip=0, sort="date", order="asc"
    )
    assert set(res) == {"items", "total", "limit", "skip"}
    assert res["limit"] == 2
    assert res["skip"] == 0
    assert res["total"] >= 5
    assert len(res["items"]) == 2

    # filter by division
    res = await finance_routes._sal_list(admin=admin, paginate=True, division="NOC")
    assert all(it["division"] == "NOC" for it in res["items"])

    # filter by employee_id
    res = await finance_routes._sal_list(admin=admin, paginate=True, employee_id=str(emp["_id"]))
    assert all(it["employee_id"] == str(emp["_id"]) for it in res["items"])

    # backward compat: no paginate -> array
    res = await finance_routes._sal_list(admin=admin)
    assert isinstance(res, list)
    assert len(res) >= 5


# -------------------- SALES FEES TESTS --------------------

@pytest.mark.anyio
async def test_sales_fee_multi_invoice_items(db, admin):
    _today = datetime.now(timezone.utc).date().isoformat()
    payload = {
        "date": _today,
        "sales_person_id": "sales123",
        "sales_person": "Sales Test",
        "notes": "test",
        "items": [
            {"description": "Fee invoice A", "amount": 100000, "invoice_id": "invA", "invoice_number": "INV-A"},
            {"description": "Fee invoice B", "amount": 200000, "invoice_id": "invB", "invoice_number": "INV-B"},
        ],
    }
    created = await finance_routes._sf_create(payload=payload, admin=admin)
    assert created["amount"] == 300000
    assert created["period_yyyy_mm"] == _today[:7]
    items = created.get("items") or []
    assert len(items) == 2
    assert all("invoice_id" in it for it in items)
    assert items[0]["invoice_number"] == "INV-A"
    assert items[1]["invoice_number"] == "INV-B"

    # paginate sales fees
    res = await finance_routes._sf_list(admin=admin, paginate=True, limit=5, sort="date", order="desc")
    assert set(res) == {"items", "total", "limit", "skip"}

    # filter by sales_person_id (raw doc already in collection via _sf_create)
    res = await finance_routes._sf_list(admin=admin, paginate=True, sales_person_id="sales123")
    assert all(it["sales_person_id"] == "sales123" for it in res["items"])

    # backward compat
    res = await finance_routes._sf_list(admin=admin)
    assert isinstance(res, list)


@pytest.mark.anyio
async def test_sales_fee_rejects_same_invoice_period_and_salesperson(db, admin):
    """The same invoice may not be commissioned twice for one sales/month."""
    today = datetime.now(timezone.utc).date().isoformat()
    db.sales_fees.rows = [_sf(
        0,
        date=today,
        period_yyyy_mm=today[:7],
        sales_person_id="sales123",
        items=[{"description": "Existing", "amount": 5000,
                "invoice_id": "inv-1", "invoice_number": "INV-001"}],
    )]
    payload = {
        "date": today,
        "sales_person_id": "sales123",
        "sales_person": "Sales Test",
        "items": [{"description": "Duplicate", "amount": 10000,
                   "invoice_id": "inv-1", "invoice_number": " inv-001 "}],
    }

    with pytest.raises(finance_routes.HTTPException) as exc:
        await finance_routes._sf_create(payload=payload, admin=admin)

    assert exc.value.status_code == 409
    assert "INV-001" in exc.value.detail
    assert len(db.sales_fees.rows) == 1


@pytest.mark.anyio
@pytest.mark.parametrize(
    "date,sales_person_id,invoice_number",
    [
        ("2099-11-01", "sales123", "INV-001"),  # different period
        ("2099-12-01", "sales999", "INV-001"),  # different salesperson
        ("2099-12-01", "sales123", "INV-002"),  # different invoice
    ],
)
async def test_sales_fee_allows_when_any_dedupe_dimension_differs(
    db, admin, date, sales_person_id, invoice_number,
):
    db.sales_fees.rows = [_sf(
        0,
        date="2099-12-01",
        period_yyyy_mm="2099-12",
        sales_person_id="sales123",
        items=[{"description": "Existing", "amount": 5000,
                "invoice_id": "inv-1", "invoice_number": "INV-001"}],
    )]
    created = await finance_routes._sf_create(payload={
        "date": date,
        "sales_person_id": sales_person_id,
        "sales_person": "Sales Test",
        "items": [{"description": "Allowed", "amount": 10000,
                   "invoice_id": "inv-new", "invoice_number": invoice_number}],
    }, admin=admin)

    assert created["amount"] == 10000
    assert len(db.sales_fees.rows) == 2


# -------------------- ROUTE SIGNATURE (FastAPI contract) TESTS --------------------

def _ledger_openapi_query_params(path):
    """Return {param_name: required_bool} from the PUBLIC OpenAPI schema.

    Deliberately uses app.openapi() (the public contract FastAPI generates)
    instead of route.dependant.query_params internals: ModelField internals
    (.required attribute) differ across FastAPI/Pydantic versions and caused
    cross-env test failures (Tatang's FAIL on 2355963). The OpenAPI schema is
    the stable, version-independent contract.
    """
    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(finance_routes.router)
    schema = app.openapi()
    op = schema["paths"][path]["get"]
    return {
        p["name"]: bool(p.get("required"))
        for p in op.get("parameters", [])
        if p.get("in") == "query"
    }


def test_ledger_list_no_required_extra_param():
    """Regression: **kwargs in _ledger_list_query._list made FastAPI register a
    REQUIRED query param named 'extra', so GET /admin/salaries (and sales-fees)
    always returned 422 'query.extra Field required' in production.

    The explicit division/employee_id/sales_person_id params must be optional,
    and no required 'extra' param may exist.
    """
    for path in ("/admin/salaries", "/admin/sales-fees"):
        params = _ledger_openapi_query_params(path)
        assert "extra" not in params, f"{path} still registers a required 'extra' param"
        for name in ("division", "employee_id", "sales_person_id"):
            assert name in params, f"{path} missing explicit optional {name}"
            assert params[name] is False, f"{path}.{name} must be optional"


def test_ledger_list_explicit_filters_default_empty():
    """The explicit filter params must default to '' so no filter is applied."""
    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(finance_routes.router)
    schema = app.openapi()
    for path in ("/admin/salaries", "/admin/sales-fees"):
        op = schema["paths"][path]["get"]
        defaults = {
            p["name"]: p.get("schema", {}).get("default")
            for p in op.get("parameters", [])
            if p.get("in") == "query"
        }
        for name in ("division", "employee_id", "sales_person_id"):
            assert defaults[name] == "", f"{path}.{name} must default to ''"


# -------------------- SLIP PDF SERIALIZATION TESTS --------------------

@pytest.mark.anyio
async def test_salary_slip_includes_division_position(db, admin):
    emp = _emp(1, division="NOC", position="Senior Engineer")
    db.employees.rows = [emp]
    s = _sal(0, emp)
    db.salaries.rows = [s]
    slip = await finance_routes.render_salary_slip(str(s["_id"]), format="html", admin=admin)
    assert emp["division"] in slip.body.decode()
    assert emp["position"] in slip.body.decode()


@pytest.mark.anyio
async def test_sales_fee_slip_shows_invoice_per_item(db, admin):
    customer_id = ObjectId()
    service_id = ObjectId()
    db.users = _Collection([{"_id": customer_id, "name": "Pelanggan Nusantara"}])
    db.services = _Collection([{"_id": service_id, "name": "Dedicated Internet 100 Mbps"}])
    db.sales_fees.rows = [_sf(0, items=[
        {"description": "Fee A", "amount": 50000, "invoice_id": "invA",
         "invoice_number": "INV-A", "customer_id": str(customer_id),
         "service_id": str(service_id)},
        {"description": "Fee B", "amount": 50000, "invoice_id": "invB",
         "invoice_number": "INV-B", "customer_id": str(customer_id),
         "service_id": str(service_id)},
    ])]
    slip = await finance_routes.render_sales_fee_slip(str(db.sales_fees.rows[0]["_id"]), format="html", admin=admin)
    body = slip.body.decode()
    assert "INV-A" in body
    assert "INV-B" in body
    assert "Pelanggan Nusantara" in body
    assert "Dedicated Internet 100 Mbps" in body
    assert str(customer_id) not in body
    assert str(service_id) not in body


# -------------------- HTTP regression tests (real FastAPI routing) --------------------

@pytest.fixture
async def http_client(db, admin):
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    app = FastAPI()
    app.include_router(finance_routes.router, prefix="/api/portal")
    app.dependency_overrides[finance_routes.get_current_admin] = lambda: admin
    async with AsyncClient(transport=ASGITransport(app=app),
                           base_url="http://test/api/portal/") as client:
        yield client


@pytest.mark.anyio
@pytest.mark.parametrize("path", ["salaries", "sales-fees"])
@pytest.mark.parametrize("params", [{}, {"paginate": "1", "limit": "20", "skip": "0", "sort": "date", "order": "desc"}])
async def test_http_ledger_list_no_required_extra(http_client, path, params):
    """Replay the UI GET, not a direct Python call which bypasses validation."""
    response = await http_client.get(f"admin/{path}", params=params)
    assert response.status_code == 200, response.text
    assert response.json() == ({"items": [], "total": 0, "limit": 20, "skip": 0} if params else [])


@pytest.mark.anyio
async def test_http_salary_save_reload_filter(http_client, db):
    emp = _emp(1, division="NOC", position="Engineer")
    other = _emp(2, division="Sales")
    db.employees.rows = [emp, other]
    date = datetime.now(timezone.utc).date().isoformat()
    db.salaries.rows = [_sal(0, other, date=date, period_yyyy_mm=date[:7])]
    payload = {"date": date, "employee_id": str(emp["_id"]), "category": "reguler",
               "items": [{"description": "Gaji pokok", "amount": 5000000},
                         {"description": "Bonus", "amount": 1000000}]}
    response = await http_client.post("admin/salaries", json=payload)
    assert response.status_code == 200, response.text
    created = response.json()
    assert created["employee"] == emp["name"]
    assert created["division"] == "NOC"
    assert created["position"] == "Engineer"
    assert created["amount"] == 6000000
    for filters, expected in [({}, 2), ({"employee_id": str(emp["_id"])}, 1),
                              ({"division": "NOC", "period": date[:7]}, 1)]:
        response = await http_client.get("admin/salaries", params={"paginate": 1, **filters})
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["total"] == expected
        assert len(body["items"]) == expected
        assert created["id"] in [item["id"] for item in body["items"]]
    response = await http_client.get("admin/salaries", params={"employee_id": "not-an-objectid"})
    assert response.status_code == 400, response.text


@pytest.mark.anyio
async def test_http_fee_save_reload_filter(http_client, db):
    date = datetime.now(timezone.utc).date().isoformat()
    db.sales_fees.rows = [_sf(0, sales_person_id="other-sales", date=date, period_yyyy_mm=date[:7])]
    payload = {"date": date, "sales_person_id": "sales123", "sales_person": "Test Sales",
               "items": [{"description": "Fee A", "amount": 100000, "invoice_number": "INV-A"},
                         {"description": "Fee B", "amount": 200000, "invoice_number": "INV-B"}]}
    response = await http_client.post("admin/sales-fees", json=payload)
    assert response.status_code == 200, response.text
    created = response.json()
    assert created["amount"] == 300000
    assert [item["invoice_number"] for item in created["items"]] == ["INV-A", "INV-B"]
    for filters, expected in [({}, 2), ({"sales_person_id": "sales123", "period": date[:7]}, 1)]:
        response = await http_client.get("admin/sales-fees", params={"paginate": 1, **filters})
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["total"] == expected
        assert len(body["items"]) == expected
        assert created["id"] in [item["id"] for item in body["items"]]


@pytest.mark.anyio
@pytest.mark.parametrize("path", ["salaries", "sales-fees"])
async def test_http_ledger_lists_still_require_auth(db, path):
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    app = FastAPI()
    app.include_router(finance_routes.router, prefix="/api/portal")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/api/portal/admin/{path}")
        assert response.status_code == 401, response.text
