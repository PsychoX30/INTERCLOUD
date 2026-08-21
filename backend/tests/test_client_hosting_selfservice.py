"""Unit tests for client-facing hosting self-service (Fase 3).

Covers:
- POST /client/services/{sid}/cpanel-sso — SSO URL, ownership, no-store, no persist
- POST /client/services/{sid}/reset-password — generated password, ownership, no persist
- GET  /client/services/{sid}/packages — list packages from service's WHM node

Security invariants tested:
- Only the service owner (user_id match) can access
- Suspended/terminated services are blocked
- Non-hosting services are rejected
- SSO URL is never persisted to DB or audit log
- Generated password is never persisted to DB or audit log
- Cache-Control: no-store on SSO response

Offline tests (unittest.mock + monkeypatch, same pattern as Fase 2).
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

import os
os.environ.setdefault("JWT_SECRET", "test-jwt-secret-client-hosting")

from fastapi import HTTPException  # noqa: E402
from portal import integrations_v2 as iv2  # noqa: E402
from portal.routes import client  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers (mirror test_whm_provisioning_contract.py patterns)
# ---------------------------------------------------------------------------
def _settings(host="https://whm1.example.com:2087", username="reseller",
             token="tok123", max_accounts=10, ssl_verify=True, name="WHM 1",
             server_id="aabbccddeeff001122334459"):
    return {
        "provider": "cpanel",
        "enabled": True,
        "name": name,
        "server_id": server_id,
        "credentials": {"host": host, "username": username,
                        "api_token": token, "password": ""},
        "options": {"max_accounts": max_accounts, "ssl_verify": ssl_verify},
    }


def _svc(uid="aabbccddeeff001122334458", sid="aabbccddeeff001122334455",
         category="hosting", username="johndoe", status="active",
         server_id="aabbccddeeff001122334459"):
    return {
        "_id": sid, "user_id": uid, "category": category,
        "status": status, "name": "Starter Hosting", "product_name": "Starter",
        "config": {"username": username, "server_id": server_id,
                   "whm_package": "uxzjdmsf_starter",
                   "control_panel": "cpanel"},
    }


def _fake_db(svc=None):
    db = MagicMock()
    db.services = MagicMock()
    db.services.find_one = AsyncMock(return_value=svc)
    db.services.update_one = AsyncMock()
    db.audit_log = MagicMock()
    db.audit_log.insert_one = AsyncMock()
    return db


USER = {"id": "aabbccddeeff001122334458", "email": "user@example.com"}
OTHER_USER = {"id": "aabbccddeeff001122334999", "email": "other@example.com"}


# ---------------------------------------------------------------------------
# Route existence & auth dependency
# ---------------------------------------------------------------------------
class TestRouteContract:
    def test_routes_exist(self):
        import inspect
        src = inspect.getsource(client)
        assert '"/client/services/{sid}/cpanel-sso"' in src
        assert '"/client/services/{sid}/reset-password"' in src
        assert '"/client/services/{sid}/packages"' in src

    def test_routes_use_get_current_user(self):
        import inspect
        for fn_name in ("client_cpanel_sso", "client_hosting_reset_password",
                        "client_hosting_packages"):
            fn = getattr(client, fn_name, None)
            assert fn is not None, f"{fn_name} not found"
            sig = inspect.signature(fn)
            deps = [str(v.default) for v in sig.parameters.values()
                    if v.default is not inspect.Parameter.empty]
            assert any("get_current_user" in d for d in deps), \
                f"{fn_name} must use get_current_user"


# ---------------------------------------------------------------------------
# SSO endpoint
# ---------------------------------------------------------------------------
class TestCpanelSso:
    @pytest.mark.asyncio
    async def test_sso_returns_url_for_owner(self, monkeypatch):
        svc = _svc()
        s = _settings()
        monkeypatch.setattr(client, "_cp_settings_for_service",
                            AsyncMock(return_value=s))
        monkeypatch.setattr(iv2.CpanelClient, "create_sso_session",
                            AsyncMock(return_value={"url": "https://cp.example.com:2083/cpanel-sso/abc"}))
        db = _fake_db(svc)
        monkeypatch.setattr(client, "_get_db", AsyncMock(return_value=db))

        req = MagicMock()
        req.headers = {}
        result = await client.client_cpanel_sso(
            "aabbccddeeff001122334455", req, user=USER)
        import json
        body = json.loads(result.body)
        assert "url" in body
        assert "https://cp.example.com" in body["url"]

    @pytest.mark.asyncio
    async def test_sso_404_for_non_owner(self, monkeypatch):
        db = _fake_db(svc=_svc())
        monkeypatch.setattr(client, "_get_db", AsyncMock(return_value=db))
        db.services.find_one = AsyncMock(return_value=None)
        req = MagicMock()
        req.headers = {}
        with pytest.raises(HTTPException) as ei:
            await client.client_cpanel_sso("aabbccddeeff001122334455", req,
                                           user=OTHER_USER)
        assert ei.value.status_code == 404

    @pytest.mark.asyncio
    async def test_sso_400_for_non_hosting(self, monkeypatch):
        svc = _svc(category="vps")
        db = _fake_db(svc=svc)
        monkeypatch.setattr(client, "_get_db", AsyncMock(return_value=db))
        req = MagicMock()
        req.headers = {}
        with pytest.raises(HTTPException) as ei:
            await client.client_cpanel_sso("aabbccddeeff001122334455", req,
                                           user=USER)
        assert ei.value.status_code == 400

    @pytest.mark.asyncio
    async def test_sso_403_for_suspended(self, monkeypatch):
        svc = _svc(status="suspended")
        db = _fake_db(svc=svc)
        monkeypatch.setattr(client, "_get_db", AsyncMock(return_value=db))
        req = MagicMock()
        req.headers = {}
        with pytest.raises(HTTPException) as ei:
            await client.client_cpanel_sso("aabbccddeeff001122334455", req,
                                           user=USER)
        assert ei.value.status_code == 403

    @pytest.mark.asyncio
    async def test_sso_403_for_terminated(self, monkeypatch):
        svc = _svc(status="terminated")
        db = _fake_db(svc=svc)
        monkeypatch.setattr(client, "_get_db", AsyncMock(return_value=db))
        req = MagicMock()
        req.headers = {}
        with pytest.raises(HTTPException) as ei:
            await client.client_cpanel_sso("aabbccddeeff001122334455", req,
                                           user=USER)
        assert ei.value.status_code == 403

    @pytest.mark.asyncio
    async def test_sso_url_not_persisted(self, monkeypatch):
        svc = _svc()
        s = _settings()
        monkeypatch.setattr(client, "_cp_settings_for_service",
                            AsyncMock(return_value=s))
        monkeypatch.setattr(iv2.CpanelClient, "create_sso_session",
                            AsyncMock(return_value={"url": "https://cp.example.com:2083/secret"}))
        db = _fake_db(svc)
        monkeypatch.setattr(client, "_get_db", AsyncMock(return_value=db))
        req = MagicMock()
        req.headers = {}
        await client.client_cpanel_sso("aabbccddeeff001122334455", req,
                                       user=USER)
        # update_one must NOT be called (no persistence of SSO URL)
        db.services.update_one.assert_not_called()
        # audit log must NOT contain the URL
        if db.audit_log.insert_one.called:
            for call in db.audit_log.insert_one.call_args_list:
                entry = call[0][0] if call[0] else call[1].get("document", {})
                assert "secret" not in str(entry), "SSO URL leaked into audit log"

    @pytest.mark.asyncio
    async def test_sso_sets_no_store_header(self, monkeypatch):
        svc = _svc()
        s = _settings()
        monkeypatch.setattr(client, "_cp_settings_for_service",
                            AsyncMock(return_value=s))
        monkeypatch.setattr(iv2.CpanelClient, "create_sso_session",
                            AsyncMock(return_value={"url": "https://cp.example.com:2083/abc"}))
        db = _fake_db(svc)
        monkeypatch.setattr(client, "_get_db", AsyncMock(return_value=db))
        req = MagicMock()
        req.headers = {}
        resp = await client.client_cpanel_sso(
            "aabbccddeeff001122334455", req, user=USER)
        # JSONResponse: verify real header is present
        assert resp.headers.get("cache-control") == "no-store"


# ---------------------------------------------------------------------------
# Reset password endpoint
# ---------------------------------------------------------------------------
class TestResetPassword:
    @pytest.mark.asyncio
    async def test_reset_generates_password_for_owner(self, monkeypatch):
        svc = _svc()
        s = _settings()
        monkeypatch.setattr(client, "_cp_settings_for_service",
                            AsyncMock(return_value=s))
        called = {}
        async def fake_passwd(self_inner, username, password):
            called["username"] = username
            called["password"] = password
            return {}
        monkeypatch.setattr(iv2.CpanelClient, "change_password", fake_passwd)
        db = _fake_db(svc)
        monkeypatch.setattr(client, "_get_db", AsyncMock(return_value=db))

        req = MagicMock()
        req.headers = {}
        result = await client.client_hosting_reset_password(
            "aabbccddeeff001122334455", {}, req, user=USER)
        assert called["username"] == "johndoe"
        assert len(called["password"]) >= 8
        assert "generated_password" in result
        assert len(result["generated_password"]) >= 8

    @pytest.mark.asyncio
    async def test_reset_404_for_non_owner(self, monkeypatch):
        db = _fake_db()
        monkeypatch.setattr(client, "_get_db", AsyncMock(return_value=db))
        db.services.find_one = AsyncMock(return_value=None)
        req = MagicMock()
        req.headers = {}
        with pytest.raises(HTTPException) as ei:
            await client.client_hosting_reset_password(
                "aabbccddeeff001122334455", {}, req, user=OTHER_USER)
        assert ei.value.status_code == 404

    @pytest.mark.asyncio
    async def test_reset_400_for_non_hosting(self, monkeypatch):
        svc = _svc(category="vps")
        db = _fake_db(svc=svc)
        monkeypatch.setattr(client, "_get_db", AsyncMock(return_value=db))
        req = MagicMock()
        req.headers = {}
        with pytest.raises(HTTPException) as ei:
            await client.client_hosting_reset_password(
                "aabbccddeeff001122334455", {}, req, user=USER)
        assert ei.value.status_code == 400

    @pytest.mark.asyncio
    async def test_reset_403_for_suspended(self, monkeypatch):
        svc = _svc(status="suspended")
        db = _fake_db(svc=svc)
        monkeypatch.setattr(client, "_get_db", AsyncMock(return_value=db))
        req = MagicMock()
        req.headers = {}
        with pytest.raises(HTTPException) as ei:
            await client.client_hosting_reset_password(
                "aabbccddeeff001122334455", {}, req, user=USER)
        assert ei.value.status_code == 403

    @pytest.mark.asyncio
    async def test_reset_password_not_persisted(self, monkeypatch):
        svc = _svc()
        s = _settings()
        monkeypatch.setattr(client, "_cp_settings_for_service",
                            AsyncMock(return_value=s))
        async def fake_passwd(self_inner, username, password):
            return {}
        monkeypatch.setattr(iv2.CpanelClient, "change_password", fake_passwd)
        db = _fake_db(svc)
        monkeypatch.setattr(client, "_get_db", AsyncMock(return_value=db))
        req = MagicMock()
        req.headers = {}
        await client.client_hosting_reset_password(
            "aabbccddeeff001122334455", {}, req, user=USER)
        # update_one must NOT store the password
        db.services.update_one.assert_not_called()
        # audit log must NOT contain password value
        if db.audit_log.insert_one.called:
            for call in db.audit_log.insert_one.call_args_list:
                entry = call[0][0] if call[0] else call[1].get("document", {})
                assert "generated_password" not in str(entry), \
                    "Password value leaked into audit log metadata"

    @pytest.mark.asyncio
    async def test_reset_403_for_terminated(self, monkeypatch):
        svc = _svc(status="terminated")
        db = _fake_db(svc=svc)
        monkeypatch.setattr(client, "_get_db", AsyncMock(return_value=db))
        req = MagicMock()
        req.headers = {}
        with pytest.raises(HTTPException) as ei:
            await client.client_hosting_reset_password(
                "aabbccddeeff001122334455", {}, req, user=USER)
        assert ei.value.status_code == 403


# ---------------------------------------------------------------------------
# Package list endpoint
# ---------------------------------------------------------------------------
class TestPackageList:
    @pytest.mark.asyncio
    async def test_packages_returned_for_owner(self, monkeypatch):
        svc = _svc()
        s = _settings()
        monkeypatch.setattr(client, "_cp_settings_for_service",
                            AsyncMock(return_value=s))
        monkeypatch.setattr(iv2.CpanelClient, "list_packages",
                            AsyncMock(return_value=["uxzjdmsf_starter", "uxzjdmsf_business"]))
        db = _fake_db(svc)
        monkeypatch.setattr(client, "_get_db", AsyncMock(return_value=db))

        result = await client.client_hosting_packages(
            "aabbccddeeff001122334455", user=USER)
        assert "packages" in result
        assert len(result["packages"]) == 2
        assert "uxzjdmsf_starter" in result["packages"]

    @pytest.mark.asyncio
    async def test_packages_404_for_non_owner(self, monkeypatch):
        db = _fake_db()
        monkeypatch.setattr(client, "_get_db", AsyncMock(return_value=db))
        db.services.find_one = AsyncMock(return_value=None)
        with pytest.raises(HTTPException) as ei:
            await client.client_hosting_packages(
                "aabbccddeeff001122334455", user=OTHER_USER)
        assert ei.value.status_code == 404

    @pytest.mark.asyncio
    async def test_packages_400_for_non_hosting(self, monkeypatch):
        svc = _svc(category="vps")
        db = _fake_db(svc=svc)
        monkeypatch.setattr(client, "_get_db", AsyncMock(return_value=db))
        with pytest.raises(HTTPException) as ei:
            await client.client_hosting_packages(
                "aabbccddeeff001122334455", user=USER)
        assert ei.value.status_code == 400

    @pytest.mark.asyncio
    async def test_packages_includes_current(self, monkeypatch):
        svc = _svc()
        s = _settings()
        monkeypatch.setattr(client, "_cp_settings_for_service",
                            AsyncMock(return_value=s))
        monkeypatch.setattr(iv2.CpanelClient, "list_packages",
                            AsyncMock(return_value=["uxzjdmsf_starter", "uxzjdmsf_business"]))
        db = _fake_db(svc)
        monkeypatch.setattr(client, "_get_db", AsyncMock(return_value=db))

        result = await client.client_hosting_packages(
            "aabbccddeeff001122334455", user=USER)
        assert result.get("current_package") == "uxzjdmsf_starter"
