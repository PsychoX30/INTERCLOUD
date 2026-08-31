"""Finance v2 offline unit tests.

Covers:
- petty cash / salaries / sales-fees CRUD
- month-lock rejection
- sales-context cascade shape
- detailed report shape
- monthly/annual xlsx headers/type
- reports list shape + annual locked flag

Uses handler functions directly with a mocked DB, no HTTP/credentials/network.
"""
from datetime import date, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from bson import ObjectId

import portal.routes.finance as finance_mod


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _async_cursor(docs):
    """Return a mock async cursor supporting .sort(...).to_list(...)"""
    cursor = MagicMock()
    cursor.sort = MagicMock(return_value=cursor)
    cursor.to_list = AsyncMock(return_value=docs)
    return cursor


def _db():
    d = MagicMock()
    # collections accessed via db[collection]
    for coll in ("kas_kecil", "salaries", "sales_fees", "users", "services",
                 "invoices", "assets", "expenses", "reports", "cashflow",
                 "credit_notes", "ledger", "finalized_reports", "settings"):
        setattr(d, coll, MagicMock())
    d.__getitem__.side_effect = lambda k: getattr(d, k)
    return d


def _patch_db(db):
    return patch.object(finance_mod, "_get_db", new=AsyncMock(return_value=db))


def _admin():
    return {"email": "admin@test.com", "roles": ["admin"]}


def _patch_require_roles():
    # make Depends(require_roles(...)) resolve to our admin dict
    return patch.object(finance_mod, "require_roles", return_value=lambda *a, **k: _admin())


# ---------------------------------------------------------------------------
# Month-lock logic (pure unit)
# ---------------------------------------------------------------------------

class TestMonthLock:
    def test_future_month_is_not_locked(self):
        future = (date.today().replace(day=1) + timedelta(days=60)).isoformat()[:7]
        assert finance_mod._month_locked(future) is False

    def test_current_month_is_not_locked(self):
        cur = date.today().isoformat()[:7]
        assert finance_mod._month_locked(cur) is False

    def test_prior_month_same_year_is_locked(self):
        prior = (date.today().replace(day=1) - timedelta(days=15)).isoformat()[:7]
        assert finance_mod._month_locked(prior) is True

    def test_prior_year_month_locked_outside_jan5_window(self):
        y = date.today().year - 1
        assert finance_mod._month_locked(f"{y}-02") is True

    def test_garbage_period_is_not_locked(self):
        # unparseable period never locks (fail-open for mutability check)
        assert finance_mod._month_locked("not-a-period") is False


# ---------------------------------------------------------------------------
# CRUD helpers
# ---------------------------------------------------------------------------

class TestLedgerCrud:
    @pytest.mark.asyncio
    async def test_kas_kecil_create_and_delete(self):
        oid = ObjectId()
        db = _db()
        db.kas_kecil.insert_one = AsyncMock(return_value=MagicMock(inserted_id=oid))
        db.kas_kecil.find_one = AsyncMock(return_value={"_id": oid, "date": "2026-08-01", "period_yyyy_mm": "2026-08"})
        db.kas_kecil.delete_one = AsyncMock(return_value=MagicMock(deleted_count=1))
        with _patch_db(db), _patch_require_roles():
            created = await finance_mod._kk_create(payload={
                "date": "2026-08-01", "amount": 1000, "category": "office", "vendor": "kopi", "notes": "q"
            }, admin=_admin())
            assert created["amount"] == 1000
            assert created["category"] == "office"
            deleted = await finance_mod._kk_delete(item_id=str(oid), admin=_admin())
            assert deleted["deleted"] == 1

    @pytest.mark.asyncio
    async def test_salaries_create_and_delete(self):
        oid = ObjectId()
        db = _db()
        db.salaries.insert_one = AsyncMock(return_value=MagicMock(inserted_id=oid))
        db.salaries.find_one = AsyncMock(return_value={"_id": oid, "date": "2026-08-01", "period_yyyy_mm": "2026-08"})
        db.salaries.delete_one = AsyncMock(return_value=MagicMock(deleted_count=1))
        with _patch_db(db), _patch_require_roles():
            created = await finance_mod._sal_create(payload={
                "date": "2026-08-01", "amount": 5000, "employee": "Budi", "category": "NOC", "notes": ""
            }, admin=_admin())
            assert created["employee"] == "Budi"
            assert created["amount"] == 5000
            deleted = await finance_mod._sal_delete(item_id=str(oid), admin=_admin())
            assert deleted["deleted"] == 1

    @pytest.mark.asyncio
    async def test_sales_fees_create_and_delete(self):
        oid = ObjectId()
        db = _db()
        db.sales_fees.insert_one = AsyncMock(return_value=MagicMock(inserted_id=oid))
        db.sales_fees.find_one = AsyncMock(return_value={"_id": oid, "date": "2026-08-01", "period_yyyy_mm": "2026-08"})
        db.sales_fees.delete_one = AsyncMock(return_value=MagicMock(deleted_count=1))
        with _patch_db(db), _patch_require_roles():
            created = await finance_mod._sf_create(payload={
                "date": "2026-08-01", "amount": 2000, "sales_person": "S", "invoice_number": "INV-1", "notes": ""
            }, admin=_admin())
            assert created["sales_person"] == "S"
            assert created["amount"] == 2000
            deleted = await finance_mod._sf_delete(item_id=str(oid), admin=_admin())
            assert deleted["deleted"] == 1

    @pytest.mark.asyncio
    async def test_prior_month_insert_is_rejected(self):
        prior = (date.today().replace(day=1) - timedelta(days=45)).isoformat()
        db = _db()
        with _patch_db(db), _patch_require_roles():
            with pytest.raises(Exception) as exc:
                await finance_mod._kk_create(payload={
                    "date": prior, "amount": 100, "notes": "blocked"
                }, admin=_admin())
            assert "403" in str(exc.value) or getattr(exc.value, "status_code", None) == 403

    @pytest.mark.asyncio
    async def test_delete_missing_returns_404(self):
        db = _db()
        db.kas_kecil.find_one = AsyncMock(return_value=None)
        with _patch_db(db), _patch_require_roles():
            with pytest.raises(Exception) as exc:
                await finance_mod._kk_delete(item_id=str(ObjectId()), admin=_admin())
            assert "404" in str(exc.value) or getattr(exc.value, "status_code", None) == 404


# ---------------------------------------------------------------------------
# Sales-context cascade shape
# ---------------------------------------------------------------------------

class TestSalesContext:
    @pytest.mark.asyncio
    async def test_cascade_shape_and_linkage(self):
        db = _db()
        # empty results
        db.users.find = MagicMock(return_value=_async_cursor([]))
        db.services.find = MagicMock(return_value=_async_cursor([]))
        db.invoices.find = MagicMock(return_value=_async_cursor([]))
        with _patch_db(db), _patch_require_roles():
            out = await finance_mod.sales_context(admin=_admin())
            assert "sales_people" in out
            assert "customers_by_sales" in out
            assert "services_by_customer" in out
            assert "invoices_by_service" in out
            assert "invoices_by_customer" in out
            assert out["sales_people"] == []

    @pytest.mark.asyncio
    async def test_empty_when_no_sales(self):
        db = _db()
        db.users.find = MagicMock(return_value=_async_cursor([]))
        with _patch_db(db), _patch_require_roles():
            out = await finance_mod.sales_context(admin=_admin())
            assert out["sales_people"] == []
            assert out["customers_by_sales"] == {}


# ---------------------------------------------------------------------------
# Detailed report shape
# ---------------------------------------------------------------------------

class TestDetailedReport:
    @pytest.mark.asyncio
    async def test_detailed_endpoint_shape(self):
        db = _db()
        db.invoices.find = MagicMock(return_value=_async_cursor([]))
        db.expenses.find = MagicMock(return_value=_async_cursor([]))
        db.kas_kecil.find = MagicMock(return_value=_async_cursor([]))
        db.salaries.find = MagicMock(return_value=_async_cursor([]))
        db.sales_fees.find = MagicMock(return_value=_async_cursor([]))
        db.assets.find = MagicMock(return_value=_async_cursor([]))
        db.settings.find_one = AsyncMock(return_value={})
        with _patch_db(db), _patch_require_roles():
            out = await finance_mod.finance_detailed(admin=_admin())
            for k in ("revenue_rows", "expenses_rows", "kas_kecil_rows", "salaries_rows",
                      "sales_fees_rows", "assets_rows", "totals"):
                assert k in out
            for k in ("revenue", "expenses_recurring", "kas_kecil", "salaries",
                      "sales_fees", "expenses_all", "depreciation_accumulated", "net_profit"):
                assert k in out["totals"]


# ---------------------------------------------------------------------------
# Reports / xlsx headers (offline via handler + mocked xlsx bytes)
# ---------------------------------------------------------------------------

class TestReports:
    @pytest.mark.asyncio
    async def test_monthly_xlsx_is_zip_pk(self):
        db = _db()
        db.finalized_reports.update_one = AsyncMock(return_value=MagicMock())
        empty_period = {
            "revenue": [], "expenses": [], "kk": [], "sal": [], "sf": [], "assets": []
        }
        with _patch_db(db), _patch_require_roles(), \
             patch.object(finance_mod, "_gather_period_data", new=AsyncMock(return_value=empty_period)), \
             patch.object(finance_mod, "_write_xlsx", return_value=b"PK\x03\x04fake"):
            resp = await finance_mod.finance_monthly_xlsx(period="2026-08", admin=_admin())
            assert resp.status_code == 200
            assert resp.headers["content-type"].startswith(
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
            body = b"".join([chunk async for chunk in resp.body_iterator])
            assert body[:2] == b"PK"
            cd = resp.headers.get("content-disposition", "")
            assert "Intercloud_Finance_2026-08.xlsx" in cd

    @pytest.mark.asyncio
    async def test_annual_xlsx_is_zip_pk(self):
        db = _db()
        db.finalized_reports.update_one = AsyncMock(return_value=MagicMock())
        empty_period = {
            "revenue": [], "expenses": [], "kk": [], "sal": [], "sf": [], "assets": []
        }
        with _patch_db(db), _patch_require_roles(), \
             patch.object(finance_mod, "_gather_period_data", new=AsyncMock(return_value=empty_period)), \
             patch.object(finance_mod, "_write_xlsx", return_value=b"PK\x03\x04fake"):
            resp = await finance_mod.finance_annual_xlsx(year=2026, admin=_admin())
            assert resp.status_code == 200
            assert resp.headers["content-type"].startswith(
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
            body = b"".join([chunk async for chunk in resp.body_iterator])
            assert body[:2] == b"PK"

    @pytest.mark.asyncio
    async def test_reports_list_shape_and_locked_annual(self):
        db = _db()
        db.finalized_reports.find = MagicMock(return_value=_async_cursor([
            {"_id": ObjectId(), "period": "2026-08", "kind": "monthly", "locked": False},
            {"_id": ObjectId(), "period": "2026", "kind": "annual", "locked": True},
        ]))
        with _patch_db(db), _patch_require_roles():
            rows = await finance_mod.finance_finalized_reports(admin=_admin())
            kinds = {r["kind"] for r in rows}
            assert "monthly" in kinds
            assert "annual" in kinds
            for r in rows:
                if r["kind"] == "annual":
                    assert r["locked"] is True