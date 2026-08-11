"""Regression tests for sales-scoped CRM mutations."""
from unittest.mock import AsyncMock

import pytest
from bson import ObjectId
from fastapi import HTTPException

import portal.routes.business as business


@pytest.fixture
def mock_db(monkeypatch):
    db = AsyncMock()
    result = AsyncMock()
    result.inserted_id = ObjectId()
    db.crm_customers.insert_one.return_value = result
    db.users.find_one.return_value = {"_id": ObjectId(), "role": "client"}

    async def get_db():
        return db

    monkeypatch.setattr(business, "_get_db", get_db)
    return db


@pytest.mark.anyio
async def test_sales_create_requires_linked_client_id(mock_db):
    staff = {"role": "sales", "assigned_client_ids": []}

    with pytest.raises(HTTPException) as exc:
        await business.crm_create({"name": "Prospect"}, staff=staff)

    assert exc.value.status_code == 403
    mock_db.crm_customers.insert_one.assert_not_awaited()


@pytest.mark.anyio
async def test_sales_create_accepts_only_assigned_client(mock_db):
    assigned = ObjectId()
    staff = {"role": "sales", "assigned_client_ids": [str(assigned)]}

    result = await business.crm_create(
        {"name": "Assigned Client", "user_id": str(assigned)}, staff=staff
    )

    inserted = mock_db.crm_customers.insert_one.await_args.args[0]
    assert inserted["user_id"] == assigned
    assert result["user_id"] == str(assigned)


@pytest.mark.anyio
async def test_sales_create_rejects_unassigned_client(mock_db):
    staff = {"role": "sales", "assigned_client_ids": [str(ObjectId())]}

    with pytest.raises(HTTPException) as exc:
        await business.crm_create(
            {"name": "Other Client", "user_id": str(ObjectId())}, staff=staff
        )

    assert exc.value.status_code == 403
    mock_db.crm_customers.insert_one.assert_not_awaited()


@pytest.mark.anyio
async def test_sales_create_rejects_assigned_id_when_user_is_not_a_client(mock_db):
    assigned = ObjectId()
    # The production lookup includes {role: "client"}; a support record must
    # therefore be invisible to that query.
    mock_db.users.find_one.return_value = None

    with pytest.raises(HTTPException) as exc:
        await business.crm_create(
            {"name": "Wrong Role", "user_id": str(assigned)},
            staff={"role": "sales", "assigned_client_ids": [str(assigned)]},
        )

    assert exc.value.status_code == 403
    mock_db.crm_customers.insert_one.assert_not_awaited()


@pytest.mark.anyio
async def test_sales_create_rejects_missing_assigned_client(mock_db):
    assigned = ObjectId()
    mock_db.users.find_one.return_value = None

    with pytest.raises(HTTPException) as exc:
        await business.crm_create(
            {"name": "Missing Client", "user_id": str(assigned)},
            staff={"role": "sales", "assigned_client_ids": [str(assigned)]},
        )

    assert exc.value.status_code == 403
    mock_db.crm_customers.insert_one.assert_not_awaited()


@pytest.mark.anyio
async def test_non_sales_create_may_remain_unlinked(mock_db):
    result = await business.crm_create(
        {"name": "Unlinked Prospect"}, staff={"role": "admin"}
    )

    inserted = mock_db.crm_customers.insert_one.await_args.args[0]
    assert "user_id" not in inserted
    assert result["user_id"] is None


@pytest.mark.anyio
async def test_creative_cannot_create_crm(mock_db):
    with pytest.raises(HTTPException) as exc:
        await business.crm_create({"name": "Blocked"}, staff={"role": "creative"})

    assert exc.value.status_code == 403
    mock_db.crm_customers.insert_one.assert_not_awaited()


@pytest.mark.anyio
async def test_creative_cannot_touch_existing_crm(mock_db):
    with pytest.raises(HTTPException) as exc:
        await business._assert_sales_can_touch_crm(
            mock_db, {"role": "creative"}, str(ObjectId())
        )

    assert exc.value.status_code == 403
    mock_db.crm_customers.find_one.assert_not_awaited()


@pytest.mark.anyio
async def test_sales_cannot_bulk_import_unscoped_crm(mock_db):
    upload = AsyncMock()
    upload.filename = "contacts.xlsx"
    staff = {"role": "sales", "assigned_client_ids": [str(ObjectId())]}

    with pytest.raises(HTTPException) as exc:
        await business.crm_import_xlsx(file=upload, staff=staff)

    assert exc.value.status_code == 403
    upload.read.assert_not_awaited()
