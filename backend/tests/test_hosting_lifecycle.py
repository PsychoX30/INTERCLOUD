"""
Hosting lifecycle integration tests (R3 + R4).

Verifies WHM calls are made BEFORE DB status change and the endpoint
fails closed (no DB update) when WHM is unreachable for suspend/unsuspend.
Terminate is best-effort: remove_account failure logs a warning but
termination still succeeds.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from bson import ObjectId
from datetime import datetime, timezone

import portal.routes.lifecycle as lifecycle_mod


def _coll():
    c = MagicMock()
    c.find_one = AsyncMock()
    c.update_one = AsyncMock()
    return c


@pytest.fixture
def db():
    d = MagicMock()
    d.services = _coll()
    d.users = _coll()
    d.followups = _coll()
    return d


def _svc(**over):
    base = {
        "_id": ObjectId("66b000000000000000000001"),
        "user_id": ObjectId("66a000000000000000000001"),
        "name": "Test Hosting",
        "category": "hosting",
        "status": "active",
        "config": {
            "username": "testuser",
            "provision_status": "provisioned",
            "whm_package": "starter1",
            "domain": "example.com",
        },
    }
    base.update(over)
    return base


def _patch_db(db):
    return patch.object(lifecycle_mod, "_get_db", new=AsyncMock(return_value=db))


class TestAdminServiceSuspendHosting:
    @pytest.mark.asyncio
    async def test_suspend_calls_cpanel_then_db(self, db):
        svc = _svc()
        db.services.find_one = AsyncMock(return_value=svc)

        with _patch_db(db), \
             patch.object(lifecycle_mod, "_service_vm_power", new=AsyncMock(return_value="VM stopped")), \
             patch.object(lifecycle_mod, "sales_can_access", return_value=True), \
             patch.object(lifecycle_mod, "log_audit", new=AsyncMock()), \
             patch.object(lifecycle_mod, "_cp_settings_for_service", new=AsyncMock(return_value={"host": "whm.example.com"})), \
             patch.object(lifecycle_mod.iv2, "CpanelClient") as MockCp:

            MockCp.return_value.suspend_account = AsyncMock()
            req = MagicMock()
            staff = {"email": "admin@test.com", "roles": ["admin"]}

            result = await lifecycle_mod.admin_service_suspend(
                sid=str(svc["_id"]), payload={"reason": "Late payment"},
                request=req, staff=staff)

            MockCp.return_value.suspend_account.assert_awaited_once_with("testuser", "Late payment")
            db.services.update_one.assert_awaited()
            assert result["status"] == "suspended"

    @pytest.mark.asyncio
    async def test_suspend_fail_closed_when_whm_down(self, db):
        svc = _svc()
        db.services.find_one = AsyncMock(return_value=svc)

        with _patch_db(db), \
             patch.object(lifecycle_mod, "_service_vm_power", new=AsyncMock(return_value="VM stopped")), \
             patch.object(lifecycle_mod, "sales_can_access", return_value=True), \
             patch.object(lifecycle_mod, "log_audit", new=AsyncMock()), \
             patch.object(lifecycle_mod, "_cp_settings_for_service", new=AsyncMock(return_value={"host": "whm.example.com"})), \
             patch.object(lifecycle_mod.iv2, "CpanelClient") as MockCp:

            MockCp.return_value.suspend_account = AsyncMock(side_effect=Exception("WHM timeout"))
            req = MagicMock()
            staff = {"email": "admin@test.com", "roles": ["admin"]}

            from fastapi import HTTPException
            with pytest.raises(HTTPException) as exc:
                await lifecycle_mod.admin_service_suspend(
                    sid=str(svc["_id"]), payload={"reason": "x"},
                    request=req, staff=staff)

            assert exc.value.status_code == 502
            db.services.update_one.assert_not_awaited()


class TestAdminServiceUnsuspendHosting:
    @pytest.mark.asyncio
    async def test_unsuspend_calls_cpanel_then_db(self, db):
        svc = _svc(status="suspended")
        db.services.find_one = AsyncMock(return_value=svc)

        with _patch_db(db), \
             patch.object(lifecycle_mod, "_service_vm_power", new=AsyncMock(return_value="VM started")), \
             patch.object(lifecycle_mod, "sales_can_access", return_value=True), \
             patch.object(lifecycle_mod, "log_audit", new=AsyncMock()), \
             patch.object(lifecycle_mod, "_cp_settings_for_service", new=AsyncMock(return_value={"host": "whm.example.com"})), \
             patch.object(lifecycle_mod.iv2, "CpanelClient") as MockCp:

            MockCp.return_value.unsuspend_account = AsyncMock()
            req = MagicMock()
            staff = {"email": "admin@test.com", "roles": ["admin"]}

            result = await lifecycle_mod.admin_service_unsuspend(
                sid=str(svc["_id"]), request=req, staff=staff)

            MockCp.return_value.unsuspend_account.assert_awaited_once_with("testuser")
            db.services.update_one.assert_awaited()
            assert result["status"] == "active"

    @pytest.mark.asyncio
    async def test_unsuspend_fail_closed_when_whm_down(self, db):
        svc = _svc(status="suspended")
        db.services.find_one = AsyncMock(return_value=svc)

        with _patch_db(db), \
             patch.object(lifecycle_mod, "_service_vm_power", new=AsyncMock(return_value="VM started")), \
             patch.object(lifecycle_mod, "sales_can_access", return_value=True), \
             patch.object(lifecycle_mod, "log_audit", new=AsyncMock()), \
             patch.object(lifecycle_mod, "_cp_settings_for_service", new=AsyncMock(return_value={"host": "whm.example.com"})), \
             patch.object(lifecycle_mod.iv2, "CpanelClient") as MockCp:

            MockCp.return_value.unsuspend_account = AsyncMock(side_effect=Exception("WHM timeout"))
            req = MagicMock()
            staff = {"email": "admin@test.com", "roles": ["admin"]}

            from fastapi import HTTPException
            with pytest.raises(HTTPException) as exc:
                await lifecycle_mod.admin_service_unsuspend(
                    sid=str(svc["_id"]), request=req, staff=staff)

            assert exc.value.status_code == 502
            db.services.update_one.assert_not_awaited()


class TestAdminTerminateApproveHosting:
    @pytest.mark.asyncio
    async def test_terminate_calls_remove_account(self, db):
        svc = _svc(termination_request={"status": "pending", "reason": "done"})
        db.services.find_one = AsyncMock(return_value=svc)

        with _patch_db(db), \
             patch.object(lifecycle_mod, "_service_vm_power", new=AsyncMock(return_value="VM stopped")), \
             patch.object(lifecycle_mod, "sales_can_access", return_value=True), \
             patch.object(lifecycle_mod, "log_audit", new=AsyncMock()), \
             patch.object(lifecycle_mod, "_delete_service_vm", new=AsyncMock()), \
             patch.object(lifecycle_mod, "_cp_settings_for_service", new=AsyncMock(return_value={"host": "whm.example.com"})), \
             patch.object(lifecycle_mod.iv2, "CpanelClient") as MockCp:

            MockCp.return_value.remove_account = AsyncMock()
            req = MagicMock()
            staff = {"email": "admin@test.com", "roles": ["admin"]}

            result = await lifecycle_mod.admin_terminate_approve(
                sid=str(svc["_id"]), payload={"note": ""},
                request=req, staff=staff)

            MockCp.return_value.remove_account.assert_awaited_once_with("testuser")
            db.services.update_one.assert_awaited()
            assert result["status"] == "terminated"

    @pytest.mark.asyncio
    async def test_terminate_remove_fails_logs_warning_but_continues(self, db, caplog):
        svc = _svc(termination_request={"status": "pending", "reason": "done"})
        db.services.find_one = AsyncMock(return_value=svc)

        with _patch_db(db), \
             patch.object(lifecycle_mod, "_service_vm_power", new=AsyncMock(return_value="VM stopped")), \
             patch.object(lifecycle_mod, "sales_can_access", return_value=True), \
             patch.object(lifecycle_mod, "log_audit", new=AsyncMock()), \
             patch.object(lifecycle_mod, "_delete_service_vm", new=AsyncMock()), \
             patch.object(lifecycle_mod, "_cp_settings_for_service", new=AsyncMock(return_value={"host": "whm.example.com"})), \
             patch.object(lifecycle_mod.iv2, "CpanelClient") as MockCp:

            MockCp.return_value.remove_account = AsyncMock(side_effect=Exception("WHM error"))
            req = MagicMock()
            staff = {"email": "admin@test.com", "roles": ["admin"]}

            import logging
            with caplog.at_level(logging.WARNING, logger="portal.lifecycle"):
                result = await lifecycle_mod.admin_terminate_approve(
                    sid=str(svc["_id"]), payload={}, request=req, staff=staff)

            assert result["status"] == "terminated"
            db.services.update_one.assert_awaited()
            assert any("remove_account" in r.getMessage() for r in caplog.records)