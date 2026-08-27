"""Offline tests: seamless WHM package auto-create during provisioning.

Scenarios (all offline, MagicMock DB + AsyncMock/fake CpanelClient):
- _pick_cp_server(allow_auto_create=True): server without package is eligible.
- _pick_cp_server default: package-less server NOT eligible (legacy contract).
- _auto_provision: missing package auto-created (addpkg) then account created
  with the freshly resolved (reseller-prefixed) package name.
- addpkg failure -> NO createacct with unresolved package (falls back to manual).
- create_package: idempotent when package already exists.
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

import os
os.environ.setdefault("JWT_SECRET", "test-jwt-secret-whm")

from portal import integrations_v2 as iv2  # noqa: E402
from portal.routes import provision  # noqa: E402


def _settings(host="https://whm1.example.com:2087", username="reseller",
             token="tok123", max_accounts=10, ssl_verify=True, name="WHM 1",
             server_id="srv1"):
    return {
        "provider": "cpanel",
        "enabled": True,
        "name": name,
        "server_id": server_id,
        "credentials": {"host": host, "username": username,
                        "api_token": token, "password": ""},
        "options": {"max_accounts": max_accounts, "ssl_verify": ssl_verify},
    }


def _fake_db():
    db = MagicMock()
    db.orders.update_one = AsyncMock()
    db.services.insert_one = AsyncMock(return_value=MagicMock(inserted_id="svc1"))
    db.orders.find_one = AsyncMock(return_value=None)
    db.users.find_one = AsyncMock(return_value={"_id": "u1", "name": "John",
                                                "email": "john@example.com"})
    db.integration_settings.find_one = AsyncMock(return_value=None)
    # DCIM prefixes cursor (manual-path IP allocation fallback)
    _pfx_cursor = MagicMock()
    _pfx_cursor.to_list = AsyncMock(return_value=[])
    db.dcim_prefixes.find = MagicMock(return_value=_pfx_cursor)
    return db


# ---------------------------------------------------------------------------
# _pick_cp_server eligibility
# ---------------------------------------------------------------------------
class TestPickCpServerAutoCreate:
    @pytest.mark.asyncio
    async def test_server_without_package_eligible_when_allowed(self, monkeypatch):
        s1 = _settings(name="A", server_id="a")
        caps = {"a": {"ok": True, "accounts": 0, "loadavg": {"five": 1.0},
                      "packages": ["uxzjdmsf_business"]}}

        async def _fake_capacity(self):
            return caps["a"]

        monkeypatch.setattr(iv2.CpanelClient, "capacity", _fake_capacity)
        monkeypatch.setattr(provision, "_cp_servers", AsyncMock(return_value=[s1]))
        best, report = await provision._pick_cp_server(
            _fake_db(), package_name="starter", allow_auto_create=True)
        assert best is not None
        assert report[0]["has_package"] is False
        assert report[0]["can_create_pkg"] is True

    @pytest.mark.asyncio
    async def test_server_without_package_not_eligible_by_default(self, monkeypatch):
        s1 = _settings(name="A", server_id="a")
        caps = {"a": {"ok": True, "accounts": 0, "loadavg": {"five": 1.0},
                      "packages": ["uxzjdmsf_business"]}}

        async def _fake_capacity(self):
            return caps["a"]

        monkeypatch.setattr(iv2.CpanelClient, "capacity", _fake_capacity)
        monkeypatch.setattr(provision, "_cp_servers", AsyncMock(return_value=[s1]))
        best, report = await provision._pick_cp_server(
            _fake_db(), package_name="starter")
        assert best is None
        assert report[0]["can_create_pkg"] is False

    @pytest.mark.asyncio
    async def test_server_with_package_preferred_over_auto_create(self, monkeypatch):
        """2 servers: A has the package, B doesn't. A must win even if B has more slots."""
        sA = _settings(name="A", server_id="a", max_accounts=5)
        sB = _settings(name="B", server_id="b", max_accounts=100)
        caps = {
            "A": {"ok": True, "accounts": 0, "loadavg": {"five": 1.0},
                  "packages": ["uxzjdmsf_starter"]},
            "B": {"ok": True, "accounts": 0, "loadavg": {"five": 0.1},
                  "packages": []},
        }

        # patch per-instance using server settings name
        async def capacity_by_name(self):
            return caps[self._name]
        monkeypatch.setattr(iv2.CpanelClient, "capacity", capacity_by_name)
        # attach identity helpers
        orig_init = iv2.CpanelClient.__init__

        def _init(self, settings):
            orig_init(self, settings)
            self._name = settings.get("name")
        monkeypatch.setattr(iv2.CpanelClient, "__init__", _init)
        monkeypatch.setattr(provision, "_cp_servers", AsyncMock(return_value=[sA, sB]))
        best, report = await provision._pick_cp_server(
            _fake_db(), package_name="starter", allow_auto_create=True)
        assert best is not None
        assert best["name"] == "A"
        assert report[0]["has_package"] is True
        assert report[1]["has_package"] is False


# ---------------------------------------------------------------------------
# create_package idempotency (client-level)
# ---------------------------------------------------------------------------
class TestCreatePackageClient:
    def _client(self):
        return iv2.CpanelClient(_settings())

    @pytest.mark.asyncio
    async def test_success_response(self, monkeypatch):
        cp = self._client()
        async def fake_call(fn, params):
            return {"result": [{"status": 1, "statusmsg": "Created"}]}
        monkeypatch.setattr(cp, "_call", fake_call)
        out = await cp.create_package("starter", quota_mb=512, bwlimit_mb=2048)
        assert out["status"] == 1

    @pytest.mark.asyncio
    async def test_already_exists_is_success(self, monkeypatch):
        cp = self._client()
        async def fake_call(fn, params):
            return {"result": [{"status": 0,
                                "statusmsg": "(XID abc) The package \"res_starter\" already exists."}]}
        monkeypatch.setattr(cp, "_call", fake_call)
        out = await cp.create_package("starter")
        assert out["status"] == 1
        assert "already exists" in out["statusmsg"]

    @pytest.mark.asyncio
    async def test_failure_raises(self, monkeypatch):
        cp = self._client()
        async def fake_call(fn, params):
            return {"result": [{"status": 0, "statusmsg": "quota exceeded"}]}
        monkeypatch.setattr(cp, "_call", fake_call)
        with pytest.raises(RuntimeError, match="quota exceeded"):
            await cp.create_package("starter")


# ---------------------------------------------------------------------------
# _auto_provision seamless path: auto-create then createacct
# ---------------------------------------------------------------------------
class TestAutoProvisionAutoCreate:
    def _setup_common(self, monkeypatch, prod_tiers, report_rows, pick_settings,
                      create_package_result="ok", create_account_result="ok"):
        prod = {"_id": "prod1", "name": "Hosting", "category": "hosting",
                "provision": {"package": "starter", "packages": prod_tiers}}
        order = {"_id": "ord1", "user_id": "u1", "user_name": "John",
                 "user_email": "john@example.com", "product_id": "prod1",
                 "config": {"whm_package": "starter"}, "selections": [], "addon_ids": []}

        async def fake_pick(db, package_name="", allow_auto_create=False):
            return pick_settings, report_rows
        monkeypatch.setattr(provision, "_pick_cp_server", fake_pick)
        monkeypatch.setattr(provision, "_generate_unique_whm_username",
                            AsyncMock(return_value="johndoe"))
        monkeypatch.setattr(provision, "_resolve_hosting_domain",
                            lambda hc, cfg, username, server_settings: "johndoe.icd.net")

        # real _resolve_hosting_config on the product, so tier spec is exercised
        created_pkgs = []
        created_accts = []

        async def fake_create_package(self, name, quota_mb=256, bwlimit_mb=1024,
                                      **kwargs):
            if create_package_result == "ok":
                created_pkgs.append({"name": name, "quota_mb": quota_mb,
                                     "bwlimit_mb": bwlimit_mb})
                return {"status": 1}
            raise RuntimeError(create_package_result)

        async def fake_list_packages(self):
            # after creation, reseller-prefixed package is visible
            return ["uxzjdmsf_starter"]

        async def fake_create_account(self, domain, username, password,
                                      package=None, contact_email=""):
            if create_account_result == "ok":
                created_accts.append({"domain": domain, "username": username,
                                      "package": package})
                return {"ip": "1.2.3.4"}
            raise RuntimeError(create_account_result)

        monkeypatch.setattr(iv2.CpanelClient, "create_package", fake_create_package)
        monkeypatch.setattr(iv2.CpanelClient, "list_packages", fake_list_packages)
        monkeypatch.setattr(iv2.CpanelClient, "create_account", fake_create_account)
        monkeypatch.setattr(provision, "_notify_admin_manual_provision", AsyncMock())

        db = _fake_db()
        db.products.find_one = AsyncMock(return_value=prod)
        db.orders.find_one = AsyncMock(return_value=order)
        monkeypatch.setattr(provision, "_get_db", AsyncMock(return_value=db))
        return db, order, created_pkgs, created_accts

    @pytest.mark.asyncio
    async def test_auto_creates_package_then_account(self, monkeypatch):
        tiers = [{"name": "starter", "disk_gb": 1, "bandwidth_gb": 2, "price": 5000}]
        report = [{"server": "WHM 1", "server_id": "srv1", "resolved_package": None,
                   "can_create_pkg": True, "has_package": False}]
        s = _settings(name="WHM 1", server_id="srv1")
        db, order, created_pkgs, created_accts = self._setup_common(
            monkeypatch, tiers, report, s)

        await provision._auto_provision(db, order)

        assert created_pkgs and created_pkgs[0]["name"] == "starter"
        assert created_pkgs[0]["quota_mb"] == 1024   # 1 GB * 1024
        assert created_pkgs[0]["bwlimit_mb"] == 2048  # 2 GB * 1024
        assert created_accts, "account must be created after package auto-create"
        assert created_accts[0]["package"] == "uxzjdmsf_starter"

    @pytest.mark.asyncio
    async def test_addpkg_failure_falls_back_no_createacct(self, monkeypatch):
        tiers = [{"name": "starter", "disk_gb": 1, "bandwidth_gb": 2, "price": 5000}]
        report = [{"server": "WHM 1", "server_id": "srv1", "resolved_package": None,
                   "can_create_pkg": True, "has_package": False}]
        s = _settings(name="WHM 1", server_id="srv1")
        db, order, created_pkgs, created_accts = self._setup_common(
            monkeypatch, tiers, report, s, create_package_result="quota exceeded")

        await provision._auto_provision(db, order)

        assert not created_pkgs
        assert not created_accts, "createacct MUST NOT run with unresolved package"

    @pytest.mark.asyncio
    async def test_no_autocreate_when_package_resolved(self, monkeypatch):
        tiers = [{"name": "starter", "whm_package": "uxzjdmsf_starter",
                  "disk_gb": 1, "bandwidth_gb": 2, "price": 5000}]
        report = [{"server": "WHM 1", "server_id": "srv1",
                   "resolved_package": "uxzjdmsf_starter",
                   "can_create_pkg": False, "has_package": True}]
        s = _settings(name="WHM 1", server_id="srv1")
        db, order, created_pkgs, created_accts = self._setup_common(
            monkeypatch, tiers, report, s)

        await provision._auto_provision(db, order)

        assert not created_pkgs, "package already resolved -> no addpkg"
        assert created_accts and created_accts[0]["package"] == "uxzjdmsf_starter"
