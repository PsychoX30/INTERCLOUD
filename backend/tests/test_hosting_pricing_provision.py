"""Offline tests for hosting tier checkout pricing, truthful provisioning
status, WHM package mapping, and gated cPanel service metadata.

Backs the three production root causes:
  #1 hosting tier price ignored -> Rp0 -> awaiting_quote
  #2 tier label used as WHM package -> _match_whm_package None -> manual
  #3 status/metadata lie: order 'active' without provisioned service

All WHM/cPanel calls are mocked. No real accounts are created/suspended.
"""
from __future__ import annotations

import os
import pytest
from unittest.mock import AsyncMock, MagicMock

os.environ.setdefault("JWT_SECRET", "test-jwt-secret-hosting-pricing")

from fastapi import HTTPException  # noqa: E402
from portal.routes import orders, provision, client  # noqa: E402


TIERS = [
    {"name": "Starter", "label": "Starter", "price": 25000, "setup_fee": 5000,
     "whm_package": "uxzjdmsf_test_ic_pkg"},
    {"name": "Starter2", "label": "Starter 2", "price": 50000,
     "whm_package": "uxzjdmsf_test_ic_pkg2"},
]


def _hosting_product():
    return {"_id": "aabbccddeeff001122334457", "name": "Shared Hosting",
            "category": "hosting", "price_monthly": 0, "setup_fee": 0,
            "provision": {"packages": TIERS, "domain_policy": "subdomain"}}


def _fake_db():
    db = MagicMock()
    _cur = MagicMock()
    _cur.to_list = AsyncMock(return_value=[])
    db.products.find = MagicMock(return_value=_cur)
    return db


# ---------------------------------------------------------------------------
# ROOT CAUSE #1 — hosting tier price flows into the cart
# ---------------------------------------------------------------------------
class TestHostingTierPricing:
    @pytest.mark.asyncio
    async def test_selected_tier_prices_base_line(self):
        db = _fake_db()
        cart = await orders._price_cart(
            db, product=_hosting_product(), config={"whm_package": "Starter"},
            selections=[], addon_ids=[], tax_percent=11.0)
        assert cart["base_line"]["monthly"] == 25000
        assert cart["base_line"]["setup"] == 5000
        assert cart["base_line"]["hosting_tier"] == "Starter"
        assert cart["base_line"]["whm_package"] == "uxzjdmsf_test_ic_pkg"
        # subtotal = 25000 + 5000 setup; tax 11%
        assert cart["subtotal"] == 30000
        assert cart["total"] == round(30000 * 1.11, 2)

    @pytest.mark.asyncio
    async def test_higher_tier_prices_more(self):
        db = _fake_db()
        cart = await orders._price_cart(
            db, product=_hosting_product(), config={"whm_package": "Starter2"},
            selections=[], addon_ids=[], tax_percent=11.0)
        assert cart["base_line"]["monthly"] == 50000
        assert cart["total"] > 0

    @pytest.mark.asyncio
    async def test_missing_tier_selection_rejected_not_quote(self):
        db = _fake_db()
        with pytest.raises(HTTPException) as ei:
            await orders._price_cart(
                db, product=_hosting_product(), config={},
                selections=[], addon_ids=[], tax_percent=11.0)
        assert ei.value.status_code == 400

    @pytest.mark.asyncio
    async def test_invalid_tier_selection_rejected(self):
        db = _fake_db()
        with pytest.raises(HTTPException) as ei:
            await orders._price_cart(
                db, product=_hosting_product(), config={"whm_package": "Nope"},
                selections=[], addon_ids=[], tax_percent=11.0)
        assert ei.value.status_code == 400

    @pytest.mark.asyncio
    async def test_vps_product_unaffected(self):
        db = _fake_db()
        vps = {"_id": "p", "name": "VPS", "category": "vps",
               "price_monthly": 100000, "setup_fee": 0}
        cart = await orders._price_cart(
            db, product=vps, config={}, selections=[], addon_ids=[], tax_percent=11.0)
        assert cart["base_line"]["monthly"] == 100000
        assert cart["base_line"]["hosting_tier"] is None

    def test_selected_hosting_tier_helper(self):
        tier = orders._selected_hosting_tier(_hosting_product(), {"whm_package": "Starter"})
        assert tier["price"] == 25000
        assert tier["whm_package"] == "uxzjdmsf_test_ic_pkg"

    def test_non_hosting_returns_none(self):
        assert orders._selected_hosting_tier(
            {"category": "vps"}, {"whm_package": "x"}) is None


# ---------------------------------------------------------------------------
# ROOT CAUSE #2 — tier.whm_package used as the WHM package (not the label)
# ---------------------------------------------------------------------------
class TestHostingPackageMapping:
    def test_resolve_uses_tier_whm_package_not_label(self):
        prod = {"name": "Shared", "provision": {"packages": TIERS}}
        cfg = {"whm_package": "Starter"}  # user selects tier NAME
        result = provision._resolve_hosting_config(prod, cfg)
        # Must resolve to the provider identifier, NOT 'Starter'
        assert result["package"] == "uxzjdmsf_test_ic_pkg"
        assert result["tier_name"] == "Starter"

    def test_resolve_second_tier(self):
        prod = {"name": "Shared", "provision": {"packages": TIERS}}
        result = provision._resolve_hosting_config(prod, {"whm_package": "Starter2"})
        assert result["package"] == "uxzjdmsf_test_ic_pkg2"

    def test_resolve_falls_back_to_config_package(self):
        prod = {"name": "Shared", "provision": {"packages": TIERS}}
        # No tier match; explicit config.package should still work
        result = provision._resolve_hosting_config(prod, {"package": "legacy_pkg"})
        assert result["package"] == "legacy_pkg"

    def test_tier_without_whm_package_yields_no_package(self):
        prod = {"name": "Shared", "provision": {"packages": [
            {"name": "Basic", "price": 10000}]}}  # no whm_package mapping
        result = provision._resolve_hosting_config(prod, {"whm_package": "Basic"})
        # No provider identifier -> None (never let WHM apply its own default label)
        assert result["package"] is None


# ---------------------------------------------------------------------------
# ROOT CAUSE #3a — order cannot be forced 'active' without a provisioned svc
# ---------------------------------------------------------------------------
class TestTruthfulOrderStatus:
    class _Payload:
        def __init__(self, status):
            self.status = status

    def _db_with(self, order, service=None):
        base_order = {
            "_id": "aabbccddeeff001122334401",
            "user_id": "aabbccddeeff001122334458",
            "user_name": "Test User",
            "user_email": "test@example.com",
            "product_id": "aabbccddeeff001122334457",
            "product_name": "Hosting",
            "notes": "",
            "config": {},
            "status": "pending",
            "assigned_admin_id": None,
            "invoice_id": None,
            "service_id": None,
            "provision_log": [],
            "created_at": "2024-01-01T00:00:00Z",
        }
        base_order.update(order)
        db = MagicMock()
        # first call returns base_order, second call (after update) returns updated order
        updated_order = dict(base_order)
        updated_order["status"] = "active"
        db.orders.find_one = AsyncMock(side_effect=[base_order, updated_order])
        db.orders.update_one = AsyncMock()
        db.services.find_one = AsyncMock(return_value=service)
        db.invoices.find_one = AsyncMock(return_value=None)
        return db

    @pytest.mark.asyncio
    async def test_cannot_activate_without_service(self, monkeypatch):
        order = {"_id": "aabbccddeeff001122334401", "service_id": None}
        db = self._db_with(order)
        monkeypatch.setattr(orders, "_get_db", AsyncMock(return_value=db))
        with pytest.raises(HTTPException) as ei:
            await orders.admin_update_order_status(
                "aabbccddeeff001122334401", self._Payload("active"), admin={"id": "a", "name": "Admin"})
        assert ei.value.status_code == 409

    @pytest.mark.asyncio
    async def test_cannot_activate_when_pending_provision(self, monkeypatch):
        order = {"_id": "aabbccddeeff001122334401", "service_id": "aabbccddeeff001122334402"}
        svc = {"_id": "aabbccddeeff001122334402", "status": "pending",
               "config": {"provision_status": "pending"}}
        db = self._db_with(order, svc)
        monkeypatch.setattr(orders, "_get_db", AsyncMock(return_value=db))
        with pytest.raises(HTTPException) as ei:
            await orders.admin_update_order_status(
                "aabbccddeeff001122334401", self._Payload("active"), admin={"id": "a", "name": "Admin"})
        assert ei.value.status_code == 409

    @pytest.mark.asyncio
    async def test_can_activate_when_provisioned(self, monkeypatch):
        svc = {"_id": "aabbccddeeff001122334402", "status": "active",
               "config": {"provision_status": "provisioned"}}
        db = self._db_with({"service_id": "aabbccddeeff001122334402"}, svc)
        monkeypatch.setattr(orders, "_get_db", AsyncMock(return_value=db))
        result = await orders.admin_update_order_status(
            "aabbccddeeff001122334401", self._Payload("active"), admin={"id": "a", "name": "Admin"})
        assert result["status"] in ("active", "pending")
        db.orders.update_one.assert_awaited()

    @pytest.mark.asyncio
    async def test_other_statuses_unaffected(self, monkeypatch):
        db = self._db_with({"service_id": None})
        monkeypatch.setattr(orders, "_get_db", AsyncMock(return_value=db))
        # 'rejected' should not be blocked by the provisioned-guard
        await orders.admin_update_order_status(
            "aabbccddeeff001122334401", self._Payload("rejected"), admin={"id": "a", "name": "Admin"})
        db.orders.update_one.assert_awaited()


# ---------------------------------------------------------------------------
# ROOT CAUSE #3b — client hosting metadata gated on provision_status
# ---------------------------------------------------------------------------
class TestClientMetadataGating:
    def _db_services(self, docs):
        db = MagicMock()
        cur = MagicMock()
        cur.sort.return_value = cur
        cur.to_list = AsyncMock(return_value=docs)
        db.services.find = MagicMock(return_value=cur)
        return db

    @pytest.mark.asyncio
    async def test_pending_service_hides_credentials(self, monkeypatch):
        svc = {"_id": "aabbccddeeff001122334402", "product_name": "Hosting", "name": "Hosting",
               "status": "pending", "category": "hosting",
               "config": {"provision_status": "pending", "username": "johndoe",
                          "domain": "johndoe.icd-cust.net", "panel_url": "https://x:2083"}}
        db = self._db_services([svc])
        monkeypatch.setattr(client, "_get_db", AsyncMock(return_value=db))
        out = await client.client_hosting_accounts(user={"id": "aabbccddeeff001122334458"})
        assert out[0]["username"] == ""
        assert out[0]["domain"] == ""
        assert out[0]["panel_url"] == ""
        assert out[0]["provision_status"] == "pending"

    @pytest.mark.asyncio
    async def test_provisioned_service_exposes_credentials(self, monkeypatch):
        svc = {"_id": "aabbccddeeff001122334402", "product_name": "Hosting", "name": "Hosting",
               "status": "active", "category": "hosting",
               "config": {"provision_status": "provisioned", "username": "johndoe",
                          "domain": "johndoe.icd-cust.net", "ip": "1.2.3.4",
                          "panel_url": "https://whm1:2083", "control_panel": "cPanel/WHM",
                          "whm_package": "uxzjdmsf_test_ic_pkg"}}
        db = self._db_services([svc])
        monkeypatch.setattr(client, "_get_db", AsyncMock(return_value=db))
        out = await client.client_hosting_accounts(user={"id": "aabbccddeeff001122334458"})
        assert out[0]["username"] == "johndoe"
        assert out[0]["domain"] == "johndoe.icd-cust.net"
        assert out[0]["ip"] == "1.2.3.4"
        assert out[0]["panel_url"] == "https://whm1:2083"
        assert out[0]["whm_package"] == "uxzjdmsf_test_ic_pkg"
