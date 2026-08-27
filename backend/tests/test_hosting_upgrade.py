"""Offline contract tests for client self-service hosting package upgrades."""
from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock

import pytest

os.environ.setdefault("JWT_SECRET", "test-jwt-secret-hosting-upgrade")

from fastapi import HTTPException  # noqa: E402
from portal import integrations_v2 as iv2  # noqa: E402
from portal.routes import billing, client  # noqa: E402

USER = {"id": "aabbccddeeff001122334458", "email": "user@example.com"}
SID = "aabbccddeeff001122334455"
IID = "aabbccddeeff001122334456"

TIERS = [
    {"name": "starter", "label": "Starter", "disk_gb": 1, "bandwidth_gb": 10, "price": 25000},
    {"name": "business", "label": "Business", "disk_gb": 5, "bandwidth_gb": 50, "price": 50000},
]


def _service(*, pending=None, package="starter", username="johndoe"):
    return {"_id": SID, "user_id": USER["id"], "product_id": "aabbccddeeff001122334457",
            "category": "hosting", "status": "active", "name": "Hosting Saya",
            "product_name": "Hosting", "next_renewal": "2099-01-01", "pending_upgrade": pending,
            "config": {"username": username, "server_id": "legacy", "whm_package": package}}


def _product():
    return {"_id": "aabbccddeeff001122334457", "provision": {"packages": TIERS}}


def _db(svc=None, product=None):
    db = MagicMock()
    db.services.find_one = AsyncMock(return_value=svc)
    db.services.update_one = AsyncMock()
    db.products.find_one = AsyncMock(return_value=product)
    db.audit_log.insert_one = AsyncMock()
    return db


@pytest.mark.asyncio
async def test_options_returns_catalog_tiers_except_current(monkeypatch):
    db = _db(_service(), _product())
    monkeypatch.setattr(client, "_get_db", AsyncMock(return_value=db))

    result = await client.client_hosting_upgrade_options(SID, user=USER)

    assert result["current"]["name"] == "starter"
    assert result["tiers"] == [TIERS[1]]
    assert result["pending_upgrade"] is False


@pytest.mark.asyncio
async def test_preview_calculates_prorated_difference_and_tax(monkeypatch):
    db = _db(_service(), _product())
    monkeypatch.setattr(client, "_get_db", AsyncMock(return_value=db))
    monkeypatch.setattr(client, "_get_setting_value", AsyncMock(return_value=11.0))

    result = await client.client_hosting_upgrade_preview(SID, {"package": "business"}, user=USER)

    assert result["monthly_delta"] == 25000.0
    assert result["days_left"] == 31
    assert result["prorated_charge"] == round(25000 * 31 / 30, 2)
    assert result["tax_amount"] == round(result["prorated_charge"] * .11, 2)
    assert result["total"] == result["prorated_charge"] + result["tax_amount"]


@pytest.mark.asyncio
async def test_upgrade_creates_invoice_and_pending_flag(monkeypatch):
    db = _db(_service(), _product())
    monkeypatch.setattr(client, "_get_db", AsyncMock(return_value=db))
    monkeypatch.setattr(client, "_get_setting_value", AsyncMock(return_value=11.0))

    async def fake_insert(_db, _collection, _prefix, inv):
        return {**inv, "_id": IID, "number": "INV-001"}

    monkeypatch.setattr(client, "_insert_numbered", fake_insert)
    request = MagicMock(headers={})
    result = await client.client_hosting_upgrade_request(SID, {"package": "business"}, request, user=USER)

    assert result["invoice_id"] == IID
    assert result["amount"] > 0
    update = db.services.update_one.await_args.args[1]["$set"]["pending_upgrade"]
    assert update["type"] == "hosting_package"
    assert update["package"] == "business"
    assert update["invoice_id"] == IID


@pytest.mark.asyncio
async def test_upgrade_returns_409_when_pending(monkeypatch):
    db = _db(_service(pending={"type": "hosting_package", "invoice_id": "old"}), _product())
    monkeypatch.setattr(client, "_get_db", AsyncMock(return_value=db))
    monkeypatch.setattr(client, "_get_setting_value", AsyncMock(return_value=11.0))

    with pytest.raises(HTTPException) as exc:
        await client.client_hosting_upgrade_request(SID, {"package": "business"}, MagicMock(headers={}), user=USER)
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_invalid_package_returns_400(monkeypatch):
    db = _db(_service(), _product())
    monkeypatch.setattr(client, "_get_db", AsyncMock(return_value=db))

    with pytest.raises(HTTPException) as exc:
        await client.client_hosting_upgrade_preview(SID, {"package": "unknown"}, user=USER)
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_paid_hosting_upgrade_calls_whm_and_clears_pending(monkeypatch):
    svc = _service(pending={"type": "hosting_package", "package": "business", "invoice_id": IID})
    db = _db(svc, _product())
    monkeypatch.setattr(billing, "_cp_settings_for_service", AsyncMock(return_value={"credentials": {}, "options": {}}))
    change = AsyncMock(return_value={})
    monkeypatch.setattr(iv2.CpanelClient, "change_package", change)

    result = await billing._apply_pending_upgrade(db, {"_id": IID, "number": "INV-001", "service_id": SID,
                                                       "upgrade": {"type": "hosting_package"}})

    assert result is True
    change.assert_awaited_once_with("johndoe", "business")
    update = db.services.update_one.await_args.args[1]
    assert update["$set"]["config.whm_package"] == "business"
    assert "pending_upgrade" in update["$unset"]
