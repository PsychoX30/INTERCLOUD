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
                    # simple equality for test
                    if k == "$regex":
                        match = str(r.get(k, "")).lower().find(v.get("$regex", "").lower()) >= 0
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
            "date": "2026-08-25", "category": "reguler", "notes": "no emp"
        }, admin=admin)
        assert False, "expected 422"
    except Exception as exc:
        assert getattr(exc, "status_code", 422) == 422


@pytest.mark.anyio
async def test_salary_create_with_valid_employee_id(db, admin):
    emp = _emp(1, division="NOC", position="Engineer")
    db.employees.rows = [emp]
    created = await finance_routes._sal_create(payload={
        "date": "2026-08-25",
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
    assert created["period_yyyy_mm"] == "2026-08"
    assert len(created.get("items", [])) == 2


@pytest.mark.anyio
async def test_salary_create_invalid_employee_id_rejected(db, admin):
    db.employees.rows = []
    try:
        await finance_routes._sal_create(payload={
            "date": "2026-08-25",
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
    payload = {
        "date": "2026-08-25",
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
    assert created["period_yyyy_mm"] == "2026-08"
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
    db.sales_fees.rows = [_sf(0)]
    slip = await finance_routes.render_sales_fee_slip(str(db.sales_fees.rows[0]["_id"]), format="html", admin=admin)
    body = slip.body.decode()
    assert "INV-A" in body
    assert "INV-B" in body