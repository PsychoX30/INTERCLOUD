"""Finance multi-item sales fees / salaries + cascade context tests.

OFFLINE unit tests: call the real handlers directly with a mocked DB
(pola test_hosting_* / test_whm_*). No live server, no credentials, no DB writes.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from bson import ObjectId

import portal.routes.finance as finance_mod


def _coll():
    c = MagicMock()
    c.find_one = AsyncMock()
    c.insert_one = AsyncMock()
    c.delete_one = AsyncMock()
    c.update_one = AsyncMock()
    c.find = MagicMock()
    return c


def _insert_id(doc, _id=None):
    """Simulate insert_one by injecting _id into the doc."""
    doc["_id"] = _id or ObjectId()
    r = MagicMock()
    r.inserted_id = doc["_id"]
    return r


@pytest.fixture
def db():
    d = MagicMock()
    d.sales_fees = _coll()
    d.salaries = _coll()
    d.users = _coll()
    d.services = _coll()
    d.invoices = _coll()
    # handlers access collections via db[collection]; route __getitem__ to attrs
    d.__getitem__.side_effect = lambda k: getattr(d, k)
    return d


def _patch_db(db):
    return patch.object(finance_mod, "_get_db", new=AsyncMock(return_value=db))


STAFF = {"email": "admin@test.com", "roles": ["admin"]}


# ---------- factory create with items ----------

class TestLedgerCreateWithItems:
    @pytest.mark.asyncio
    async def test_sales_fee_amount_computed_from_items(self, db):
        db.sales_fees.insert_one = AsyncMock(side_effect=lambda doc: _insert_id(doc))
        with _patch_db(db):
            handler = finance_mod._sf_create
            out = await handler(payload={
                "date": "2099-12-01",  # far future → never month-locked
                "notes": "pytest",
                "sales_person": "S",
                "invoice_number": "INV-M",
                "items": [
                    {"description": "A", "amount": 50000},
                    {"description": "B", "amount": 30000},
                ],
            }, admin=STAFF)
            assert out["amount"] == 80000
            assert out["items"] == [{"description": "A", "amount": 50000.0},
                                    {"description": "B", "amount": 30000.0}]

    @pytest.mark.asyncio
    async def test_salary_amount_computed_with_negative_component(self, db):
        db.salaries.insert_one = AsyncMock(side_effect=lambda doc: _insert_id(doc))
        with _patch_db(db):
            out = await finance_mod._sal_create(payload={
                "date": "2099-12-01",
                "employee": "E", "category": "C",
                "items": [
                    {"description": "Gaji pokok", "amount": 5000000},
                    {"description": "Tunjangan", "amount": 500000},
                    {"description": "Potongan BPJS", "amount": -150000},
                ],
            }, admin=STAFF)
            assert out["amount"] == 5350000
            assert len(out["items"]) == 3

    @pytest.mark.asyncio
    async def test_legacy_single_amount_still_works(self, db):
        db.sales_fees.insert_one = AsyncMock(side_effect=lambda doc: _insert_id(doc))
        with _patch_db(db):
            out = await finance_mod._sf_create(payload={
                "date": "2099-12-01", "amount": 25000,
                "sales_person": "S", "invoice_number": "INV-L",
            }, admin=STAFF)
            assert out["amount"] == 25000
            assert "items" not in out  # serializer omits empty items


# ---------- _ledger_items normalization ----------

class TestLedgerItemsHelper:
    def test_normalizes_and_filters_junk(self):
        items = finance_mod._ledger_items({"items": [
            {"description": "  Gaji pokok  ", "amount": 100},
            {"description": "", "amount": 0},            # dropped
            {"description": "Tax", "amount": "5"},       # coerced
            "not-a-dict",                                 # dropped
        ]})
        assert items == [
            {"description": "Gaji pokok", "amount": 100.0},
            {"description": "Tax", "amount": 5.0},
        ]

    def test_absent_or_non_list_returns_empty(self):
        assert finance_mod._ledger_items({}) == []
        assert finance_mod._ledger_items({"items": "x"}) == []


# ---------- sales context cascade ----------

def _list_cursor(docs):
    cur = MagicMock()
    cur.to_list = AsyncMock(return_value=docs)
    return cur


class TestSalesContext:
    @pytest.mark.asyncio
    async def test_cascade_shape_and_linkage(self, db):
        sales_id = ObjectId("66b100000000000000000001")
        cust_id = ObjectId("66b200000000000000000002")
        order_id = ObjectId("66b300000000000000000003")
        svc_id = ObjectId("66b400000000000000000004")
        inv_id = ObjectId("66b500000000000000000005")

        sales_doc = {"_id": sales_id, "name": "Sales A", "email": "s@x.com",
                     "role": "sales", "assigned_client_ids": [cust_id]}
        cust_doc = {"_id": cust_id, "name": "Cust One", "email": "c@x.com"}
        svc_doc = {"_id": svc_id, "user_id": cust_id, "name": "VPS-01",
                   "category": "vps", "order_id": order_id}
        inv_doc = {"_id": inv_id, "user_id": cust_id, "number": "INV-1",
                   "status": "paid", "order_id": order_id}

        db.users.find = MagicMock(side_effect=lambda q: _list_cursor(
            [sales_doc] if q.get("role") == "sales" else [cust_doc]))
        db.services.find = MagicMock(return_value=_list_cursor([svc_doc]))
        db.invoices.find = MagicMock(return_value=_list_cursor([inv_doc]))

        with _patch_db(db):
            out = await finance_mod.sales_context(admin=STAFF)
            assert out["sales_people"] == [
                {"id": str(sales_id), "name": "Sales A", "email": "s@x.com"}]
            assert out["customers_by_sales"][str(sales_id)] == [
                {"id": str(cust_id), "name": "Cust One", "email": "c@x.com"}]
            assert out["services_by_customer"][str(cust_id)] == [
                {"id": str(svc_id), "name": "VPS-01", "category": "vps"}]
            # invoice reachable via both customer and service(order_id)
            assert out["invoices_by_customer"][str(cust_id)][0]["number"] == "INV-1"
            assert out["invoices_by_service"][str(svc_id)][0]["number"] == "INV-1"

    @pytest.mark.asyncio
    async def test_empty_when_no_sales(self, db):
        db.users.find = MagicMock(return_value=_list_cursor([]))
        db.services.find = MagicMock(return_value=_list_cursor([]))
        db.invoices.find = MagicMock(return_value=_list_cursor([]))
        with _patch_db(db):
            out = await finance_mod.sales_context(admin=STAFF)
            assert out["sales_people"] == []
            assert out["customers_by_sales"] == {}


# ---------- PDF slip breakdown ----------

class TestSlipBreakdown:
    @pytest.mark.asyncio
    async def test_salary_slip_renders_breakdown(self, db):
        sid = ObjectId("66b600000000000000000006")
        db.salaries.find_one = AsyncMock(return_value={
            "_id": sid, "date": "2099-12-01", "amount": 5000000,
            "employee": "Emp", "category": "Eng", "period_yyyy_mm": "2099-12",
            "items": [
                {"description": "Gaji pokok", "amount": 4000000},
                {"description": "Bonus", "amount": 1000000},
            ],
        })
        with _patch_db(db):
            out = await finance_mod.render_salary_slip(sid=str(sid), format="html", admin=STAFF)
            html = out.body.decode()
            assert "Gaji pokok" in html
            assert "Bonus" in html
            assert "Rp 5.000.000" in html
            assert "Rincian Komponen" in html

    @pytest.mark.asyncio
    async def test_salary_slip_legacy_no_breakdown(self, db):
        sid = ObjectId("66b700000000000000000007")
        db.salaries.find_one = AsyncMock(return_value={
            "_id": sid, "date": "2099-12-01", "amount": 25000,
            "employee": "Emp", "category": "Eng", "period_yyyy_mm": "2099-12",
        })
        with _patch_db(db):
            out = await finance_mod.render_salary_slip(sid=str(sid), format="html", admin=STAFF)
            html = out.body.decode()
            assert "Rincian Komponen" not in html
            assert "Rp 25.000" in html

    @pytest.mark.asyncio
    async def test_sales_fee_slip_renders_breakdown(self, db):
        sid = ObjectId("66b800000000000000000008")
        db.sales_fees.find_one = AsyncMock(return_value={
            "_id": sid, "date": "2099-12-01", "amount": 100000,
            "sales_person": "SP", "invoice_number": "INV-X",
            "period_yyyy_mm": "2099-12",
            "items": [{"description": "Line A", "amount": 100000}],
        })
        with _patch_db(db):
            out = await finance_mod.render_sales_fee_slip(sid=str(sid), format="html", admin=STAFF)
            html = out.body.decode()
            assert "Line A" in html
            assert "Rp 100.000" in html
            assert "Rincian Fee" in html
