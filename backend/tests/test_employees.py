"""TDD tests for Employees master data endpoints (offline mock)."""

from __future__ import annotations
from unittest.mock import AsyncMock
from bson import ObjectId
import pytest
from portal.routes import finance as finance_routes


class _EmpCursor:
    """Async cursor mock supporting sort, skip, limit, to_list, async iteration."""

    def __init__(self, rows):
        self.rows = list(rows)
        self._skip = 0
        self._limit = None

    def sort(self, key, direction=1):
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


class _EmpCollection:
    def __init__(self, rows):
        self.rows = rows

    def find(self, query):
        return _EmpCursor(self._filtered(query))

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
                if isinstance(v, dict):
                    # only simple equality for test
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
        self.employees = _EmpCollection([])


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


# -------------------- TESTS --------------------

@pytest.mark.anyio
async def test_employee_crud(db, admin):
    # CREATE via handler
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

    # READ list (default active=True)
    lst = await finance_routes.list_employees(admin=admin)
    assert any(e["id"] == emp_id for e in lst)

    # READ single
    got = await finance_routes.get_employee(emp_id, admin=admin)
    assert got["id"] == emp_id

    # UPDATE
    upd = await finance_routes.update_employee(emp_id, {"position": "Senior Engineer", "base_salary": 15000000}, admin=admin)
    assert upd["position"] == "Senior Engineer"
    assert upd["base_salary"] == 15000000

    # DELETE
    del_res = await finance_routes.delete_employee(emp_id, admin=admin)
    assert del_res["deleted"] == 1

    # Verify gone
    with pytest.raises(Exception) as exc:
        await finance_routes.get_employee(emp_id, admin=admin)
    assert exc.value.status_code == 404


@pytest.mark.anyio
async def test_employees_divisions_endpoint(db, admin):
    # seed two employees with different divisions
    db.employees.rows = [_emp(1, division="NOC"), _emp(2, division="Finance")]
    divs = await finance_routes.list_employee_divisions(admin=admin)
    assert isinstance(divs, list)
    assert "Finance" in divs
    assert "NOC" in divs