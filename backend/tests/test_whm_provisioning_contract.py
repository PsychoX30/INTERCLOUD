"""Unit tests for WHM/cPanel hosting provisioning contract (Fase 2).

Covers:
- _match_whm_package: fuzzy matching against reseller-prefixed WHM packages.
- _resolve_hosting_config: product provisioning_config extraction.
- _generate_whm_username: collision-safe username generation.
- _resolve_hosting_domain: domain policy resolution.
- _pick_cp_server: package availability with fuzzy matching.
- _auto_provision hosting branch: uses resolved package/domain/username.
- Hosting lifecycle routes: suspend, unsuspend, terminate, password, package.

Offline tests (unittest.mock + _FakeAsyncClient pattern from Fase 1).
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

import os
os.environ.setdefault("JWT_SECRET", "test-jwt-secret-whm")

from fastapi import HTTPException  # noqa: E402
from portal import integrations_v2 as iv2  # noqa: E402
from portal.routes import provision  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
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


def _fake_db(services=None, products=None, orders=None):
    db = MagicMock()
    # services
    svc_cursor = MagicMock()
    svc_cursor.sort.return_value = svc_cursor
    svc_cursor.to_list = AsyncMock(return_value=services or [])
    db.services.find = MagicMock(return_value=svc_cursor)
    db.services.find_one = AsyncMock(return_value=services[0] if services else None)
    db.services.update_one = AsyncMock()
    db.services.insert_one = AsyncMock(return_value=MagicMock(inserted_id="aabbccddeeff001122334460"))
    db.users = MagicMock()
    db.users.find_one = AsyncMock(return_value={"_id": "aabbccddeeff001122334458", "name": "User"})
    _prod_cursor = MagicMock()
    _prod_cursor.to_list = AsyncMock(return_value=[])
    db.products.find = MagicMock(return_value=_prod_cursor)
    db.products.find_one = AsyncMock(return_value=products[0] if products else None)
    # orders
    db.orders.find_one = AsyncMock(return_value=orders[0] if orders else None)
    db.orders.update_one = AsyncMock()
    return db


# ---------------------------------------------------------------------------
# _match_whm_package: fuzzy matching against reseller-prefixed names
# ---------------------------------------------------------------------------
class TestMatchWhmPackage:
    """WHM reseller packages are prefixed, e.g. 'uxzjdmsf_starter'.
    The portal product may say 'starter' or 'uxzjdmsf_starter'."""

    def test_exact_match(self):
        pkgs = ["uxzjdmsf_starter", "uxzjdmsf_business"]
        assert provision._match_whm_package("uxzjdmsf_starter", pkgs) == "uxzjdmsf_starter"

    def test_suffix_match_finds_prefixed(self):
        pkgs = ["uxzjdmsf_starter", "uxzjdmsf_business"]
        assert provision._match_whm_package("starter", pkgs) == "uxzjdmsf_starter"

    def test_case_insensitive_suffix(self):
        pkgs = ["uxzjdmsf_Starter", "uxzjdmsf_business"]
        assert provision._match_whm_package("starter", pkgs) == "uxzjdmsf_Starter"

    def test_multiple_matches_returns_none(self):
        # ambiguous: two packages both end with "_starter"
        pkgs = ["uxzjdmsf_starter", "reseller2_starter"]
        assert provision._match_whm_package("starter", pkgs) is None

    def test_no_match_returns_none(self):
        pkgs = ["uxzjdmsf_business"]
        assert provision._match_whm_package("enterprise", pkgs) is None

    def test_empty_input_returns_none(self):
        assert provision._match_whm_package("", ["pkg_a"]) is None
        assert provision._match_whm_package(None, ["pkg_a"]) is None

    def test_empty_package_list_returns_none(self):
        assert provision._match_whm_package("starter", []) is None

    def test_partial_middle_match_not_accepted(self):
        # "start" should NOT match "uxzjdmsf_starter" (not a suffix boundary)
        pkgs = ["uxzjdmsf_starter"]
        assert provision._match_whm_package("start", pkgs) is None


# ---------------------------------------------------------------------------
# _resolve_hosting_config: product provisioning_config extraction
# ---------------------------------------------------------------------------
class TestResolveHostingConfig:
    """Product.provision may carry hosting-specific settings."""

    def test_extracts_package_from_provision(self):
        prod = {"name": "Starter", "provision": {"package": "starter"}}
        result = provision._resolve_hosting_config(prod, {})
        assert result["package"] == "starter"

    def test_extracts_domain_policy(self):
        prod = {"name": "Starter", "provision": {
            "package": "starter",
            "domain_policy": "customer_domain",
        }}
        result = provision._resolve_hosting_config(prod, {})
        assert result["domain_policy"] == "customer_domain"

    def test_extracts_nameservers(self):
        prod = {"name": "Starter", "provision": {
            "package": "starter",
            "nameservers": ["ns1.example.com", "ns2.example.com"],
        }}
        result = provision._resolve_hosting_config(prod, {})
        assert result["nameservers"] == ["ns1.example.com", "ns2.example.com"]

    def test_extracts_set_registrar_ns(self):
        prod = {"name": "Starter", "provision": {
            "package": "starter",
            "set_registrar_ns": True,
        }}
        result = provision._resolve_hosting_config(prod, {})
        assert result["set_registrar_ns"] is True

    def test_defaults_when_provision_empty(self):
        prod = {"name": "Starter"}
        result = provision._resolve_hosting_config(prod, {})
        assert result["package"] is None
        assert result["domain_policy"] == "subdomain"  # default
        assert result["nameservers"] == []
        assert result["set_registrar_ns"] is False

    def test_merges_order_config_overrides(self):
        prod = {"name": "Starter", "provision": {"package": "starter"}}
        order_cfg = {"domain": "customer.com", "package": "business"}
        result = provision._resolve_hosting_config(prod, order_cfg)
        assert result["package"] == "business"  # order config wins
        assert result["domain"] == "customer.com"

    def test_no_provision_key_uses_defaults(self):
        prod = {"name": "Starter", "provision": {"cores": 2}}  # VPS-style provision
        result = provision._resolve_hosting_config(prod, {})
        assert result["package"] is None


# ---------------------------------------------------------------------------
# _generate_whm_username: collision-safe generation
# ---------------------------------------------------------------------------
class TestGenerateWhmUsername:
    def test_base_from_email(self):
        assert provision._generate_whm_username("john.doe@example.com") == "johndoe"

    def test_max_8_chars(self):
        assert len(provision._generate_whm_username("verylongname@example.com")) <= 8

    def test_strips_non_alphanumeric(self):
        assert provision._generate_whm_username("j-d+t@example.com") == "jdt"

    def test_lowercase(self):
        assert provision._generate_whm_username("John.DOE@example.com") == "johndoe"

    def test_numeric_prefix_gets_u(self):
        assert provision._generate_whm_username("123abc@example.com") == "u123abc"

    def test_empty_email_fallback(self):
        assert provision._generate_whm_username("") == "icduser"

    def test_all_non_alphanumeric_fallback(self):
        assert provision._generate_whm_username("---@example.com") == "icduser"

    @pytest.mark.asyncio
    async def test_collision_suffix_increment(self, monkeypatch):
        # First attempt fails, second succeeds
        attempts = []
        async def fake_verify(self, username):
            attempts.append(username)
            return {"available": username != "johndoe", "reason": "taken" if username == "johndoe" else ""}
        monkeypatch.setattr(iv2.CpanelClient, "verify_username", fake_verify)
        cp = iv2.CpanelClient(_settings())
        result = await provision._generate_unique_whm_username(cp, "john.doe@example.com")
        assert result == "johndoe1"
        assert attempts == ["johndoe", "johndoe1"]

    @pytest.mark.asyncio
    async def test_collision_multiple_increments(self, monkeypatch):
        taken = {"johndoe", "johndoe1", "johndoe2"}
        async def fake_verify(self, username):
            return {"available": username not in taken, "reason": "taken"}
        monkeypatch.setattr(iv2.CpanelClient, "verify_username", fake_verify)
        cp = iv2.CpanelClient(_settings())
        result = await provision._generate_unique_whm_username(cp, "john.doe@example.com")
        assert result == "johndoe3"

    @pytest.mark.asyncio
    async def test_collision_max_retries_raises(self, monkeypatch):
        async def fake_verify(self, username):
            return {"available": False, "reason": "taken"}
        monkeypatch.setattr(iv2.CpanelClient, "verify_username", fake_verify)
        cp = iv2.CpanelClient(_settings())
        with pytest.raises(RuntimeError, match="username.*taken"):
            await provision._generate_unique_whm_username(cp, "john.doe@example.com", max_tries=3)

    @pytest.mark.asyncio
    async def test_available_on_first_try(self, monkeypatch):
        async def fake_verify(self, username):
            return {"available": True, "reason": ""}
        monkeypatch.setattr(iv2.CpanelClient, "verify_username", fake_verify)
        cp = iv2.CpanelClient(_settings())
        result = await provision._generate_unique_whm_username(cp, "john.doe@example.com")
        assert result == "johndoe"


# ---------------------------------------------------------------------------
# _resolve_hosting_domain: domain policy resolution
# ---------------------------------------------------------------------------
class TestResolveHostingDomain:
    def test_customer_domain_from_order_config(self):
        result = provision._resolve_hosting_domain(
            {"domain_policy": "customer_domain"}, {"domain": "mysite.com"},
            username="johndoe", server_settings={})
        assert result == "mysite.com"

    def test_customer_domain_missing_raises(self):
        with pytest.raises(ValueError, match="domain.*required"):
            provision._resolve_hosting_domain(
                {"domain_policy": "customer_domain"}, {},
                username="johndoe", server_settings={})

    def test_subdomain_uses_username_and_suffix(self):
        result = provision._resolve_hosting_domain(
            {"domain_policy": "subdomain", "subdomain_suffix": "icd-cust.net"}, {},
            username="johndoe", server_settings={})
        assert result == "johndoe.icd-cust.net"

    def test_subdomain_default_suffix(self):
        result = provision._resolve_hosting_domain(
            {"domain_policy": "subdomain"}, {},
            username="johndoe", server_settings={})
        assert result == "johndoe.icd-cust.net"

    def test_subdomain_suffix_from_server_settings(self):
        srv = {"options": {"subdomain_suffix": "serverkita.web.id"}}
        result = provision._resolve_hosting_domain(
            {"domain_policy": "subdomain"}, {},
            username="johndoe", server_settings=srv)
        assert result == "johndoe.serverkita.web.id"

    def test_domain_sanitized(self):
        result = provision._resolve_hosting_domain(
            {"domain_policy": "customer_domain"}, {"domain": "MySite.COM"},
            username="johndoe", server_settings={})
        assert result == "mysite.com"


# ---------------------------------------------------------------------------
# _pick_cp_server with fuzzy package matching
# ---------------------------------------------------------------------------
class TestPickCpServerFuzzyPackage:
    @pytest.mark.asyncio
    async def test_fuzzy_match_finds_prefixed_package(self, monkeypatch):
        s1 = _settings(name="A", server_id="a", max_accounts=10)
        caps = {"a": {"ok": True, "accounts": 0, "loadavg": {"five": 1.0},
                       "packages": ["uxzjdmsf_starter", "uxzjdmsf_business"]}}

        async def _fake_capacity(self):
            return caps["a"]

        monkeypatch.setattr(iv2.CpanelClient, "capacity", _fake_capacity)
        monkeypatch.setattr(provision.iv2, "CpanelClient", iv2.CpanelClient)
        monkeypatch.setattr(provision, "_cp_servers", AsyncMock(return_value=[s1]))
        best, report = await provision._pick_cp_server(_fake_db(), package_name="starter")
        assert best is not None
        assert best["name"] == "A"
        assert report[0]["has_package"] is True
        assert report[0]["resolved_package"] == "uxzjdmsf_starter"

    @pytest.mark.asyncio
    async def test_no_match_reports_unresolved(self, monkeypatch):
        s1 = _settings(name="A", server_id="a", max_accounts=10)
        caps = {"a": {"ok": True, "accounts": 0, "loadavg": {"five": 1.0},
                       "packages": ["uxzjdmsf_business"]}}

        async def _fake_capacity(self):
            return caps["a"]

        monkeypatch.setattr(iv2.CpanelClient, "capacity", _fake_capacity)
        monkeypatch.setattr(provision.iv2, "CpanelClient", iv2.CpanelClient)
        monkeypatch.setattr(provision, "_cp_servers", AsyncMock(return_value=[s1]))
        best, report = await provision._pick_cp_server(_fake_db(), package_name="enterprise")
        assert best is None
        assert report[0]["has_package"] is False
        assert report[0]["resolved_package"] is None

    @pytest.mark.asyncio
    async def test_ambiguous_match_excluded(self, monkeypatch):
        s1 = _settings(name="A", server_id="a", max_accounts=10)
        caps = {"a": {"ok": True, "accounts": 0, "loadavg": {"five": 1.0},
                       "packages": ["uxzjdmsf_starter", "other_starter"]}}

        async def _fake_capacity(self):
            return caps["a"]

        monkeypatch.setattr(iv2.CpanelClient, "capacity", _fake_capacity)
        monkeypatch.setattr(provision.iv2, "CpanelClient", iv2.CpanelClient)
        monkeypatch.setattr(provision, "_cp_servers", AsyncMock(return_value=[s1]))
        best, report = await provision._pick_cp_server(_fake_db(), package_name="starter")
        assert best is None  # ambiguous, not safe to pick
        assert report[0]["has_package"] is False
        assert report[0]["resolved_package"] is None

    @pytest.mark.asyncio
    async def test_exact_match_wins_over_suffix(self, monkeypatch):
        s1 = _settings(name="A", server_id="a", max_accounts=10)
        caps = {"a": {"ok": True, "accounts": 0, "loadavg": {"five": 1.0},
                       "packages": ["starter", "uxzjdmsf_starter"]}}

        async def _fake_capacity(self):
            return caps["a"]

        monkeypatch.setattr(iv2.CpanelClient, "capacity", _fake_capacity)
        monkeypatch.setattr(provision.iv2, "CpanelClient", iv2.CpanelClient)
        monkeypatch.setattr(provision, "_cp_servers", AsyncMock(return_value=[s1]))
        best, report = await provision._pick_cp_server(_fake_db(), package_name="starter")
        assert best is not None
        assert report[0]["resolved_package"] == "starter"  # exact wins


# ---------------------------------------------------------------------------
# _auto_provision hosting branch uses resolved config
# ---------------------------------------------------------------------------
class TestAutoProvisionHosting:
    @pytest.mark.asyncio
    async def test_uses_resolved_package_name(self, monkeypatch):
        """_auto_provision should use _match_whm_package result, not raw product name."""
        prod = {"_id": "aabbccddeeff001122334457", "name": "Starter Hosting", "category": "hosting",
                "provision": {"package": "starter"}}
        order = {"_id": "aabbccddeeff001122334456", "user_id": "aabbccddeeff001122334458", "user_name": "John",
                 "user_email": "john@example.com", "product_id": "aabbccddeeff001122334457",
                 "config": {}, "selections": [], "addon_ids": []}
        s = _settings(name="WHM 1", server_id="aabbccddeeff001122334459")

        async def fake_pick(db, package_name=""):
            return s, [{"resolved_package": "uxzjdmsf_starter"}]

        monkeypatch.setattr(provision, "_pick_cp_server", fake_pick)
        monkeypatch.setattr(provision, "_generate_unique_whm_username",
                            AsyncMock(return_value="johndoe"))
        monkeypatch.setattr(provision, "_resolve_hosting_domain",
                            lambda hc, cfg, username, server_settings: "johndoe.icd-cust.net")
        monkeypatch.setattr(provision, "_resolve_hosting_config",
                            lambda prod, cfg: {"package": "starter", "domain_policy": "subdomain",
                                               "nameservers": [], "set_registrar_ns": False})

        created = {}
        async def fake_create(self, domain, username, password, package=None, contact_email=""):
            created.update({"domain": domain, "username": username, "package": package})
            return {}
        monkeypatch.setattr(iv2.CpanelClient, "create_account", fake_create)
        monkeypatch.setattr(provision, "_notify_admin_manual_provision", AsyncMock())

        db = _fake_db(products=[prod], orders=[order])
        monkeypatch.setattr(provision, "_get_db", AsyncMock(return_value=db))
        # Mock the DB calls inside _auto_provision
        db.products.find_one = AsyncMock(return_value=prod)
        db.orders.update_one = AsyncMock()
        db.services.insert_one = AsyncMock(return_value=MagicMock(inserted_id="aabbccddeeff001122334455"))
        db.orders.find_one = AsyncMock(return_value=order)

        await provision._auto_provision(db, order)
        assert created["package"] == "uxzjdmsf_starter"  # resolved, not raw "starter"

    @pytest.mark.asyncio
    async def test_stores_server_id_and_package_in_config(self, monkeypatch):
        prod = {"_id": "aabbccddeeff001122334457", "name": "Starter Hosting", "category": "hosting",
                "provision": {"package": "starter"}}
        order = {"_id": "aabbccddeeff001122334456", "user_id": "aabbccddeeff001122334458", "user_name": "John",
                 "user_email": "john@example.com", "product_id": "aabbccddeeff001122334457",
                 "config": {}, "selections": [], "addon_ids": []}
        s = _settings(name="WHM 1", server_id="aabbccddeeff001122334459")

        async def fake_pick(db, package_name=""):
            return s, [{"resolved_package": "uxzjdmsf_starter"}]

        monkeypatch.setattr(provision, "_pick_cp_server", fake_pick)
        monkeypatch.setattr(provision, "_generate_unique_whm_username",
                            AsyncMock(return_value="johndoe"))
        monkeypatch.setattr(provision, "_resolve_hosting_domain",
                            lambda hc, cfg, username, server_settings: "johndoe.icd-cust.net")
        monkeypatch.setattr(provision, "_resolve_hosting_config",
                            lambda prod, cfg: {"package": "starter", "domain_policy": "subdomain",
                                               "nameservers": [], "set_registrar_ns": False})

        async def fake_create(self, domain, username, password, package=None, contact_email=""):
            return {}
        monkeypatch.setattr(iv2.CpanelClient, "create_account", fake_create)
        monkeypatch.setattr(provision, "_notify_admin_manual_provision", AsyncMock())

        db = _fake_db(products=[prod], orders=[order])
        monkeypatch.setattr(provision, "_get_db", AsyncMock(return_value=db))
        db.products.find_one = AsyncMock(return_value=prod)
        db.orders.update_one = AsyncMock()
        db.services.insert_one = AsyncMock(return_value=MagicMock(inserted_id="aabbccddeeff001122334455"))
        db.orders.find_one = AsyncMock(return_value=order)

        await provision._auto_provision(db, order)
        # Check what was passed to services.insert_one
        call_args = db.services.insert_one.call_args[0][0]
        cfg = call_args["config"]
        assert cfg["server_id"] == "aabbccddeeff001122334459"
        assert cfg["whm_package"] == "uxzjdmsf_starter"
        assert cfg["username"] == "johndoe"
        assert cfg["domain"] == "johndoe.icd-cust.net"
        assert cfg["provision_status"] == "provisioned"


# ---------------------------------------------------------------------------
# Hosting lifecycle routes (source-level contract)
# ---------------------------------------------------------------------------
class TestHostingLifecycleRoutes:
    """Verify lifecycle routes exist and have correct auth dependencies."""

    def test_suspend_route_exists(self):
        import inspect
        src = inspect.getsource(provision)
        assert '"/admin/hosting/{sid}/suspend"' in src
        assert '"/admin/hosting/{sid}/unsuspend"' in src
        assert '"/admin/hosting/{sid}/terminate"' in src
        assert '"/admin/hosting/{sid}/password"' in src
        assert '"/admin/hosting/{sid}/package"' in src

    def test_lifecycle_routes_gated_by_roles(self):
        import inspect
        for route in ("admin_hosting_suspend", "admin_hosting_unsuspend",
                      "admin_hosting_terminate", "admin_hosting_password",
                      "admin_hosting_package"):
            fn = getattr(provision, route)
            sig = inspect.signature(fn)
            deps = [str(v.default) for v in sig.parameters.values()
                    if v.default is not inspect.Parameter.empty]
            assert any("Depends" in d for d in deps), f"{route} missing auth dependency"

    def test_lifecycle_uses_service_affinity(self):
        """Lifecycle routes must resolve WHM settings via the affinity helper,
        which in turn calls _cp_settings_for_service."""
        import inspect
        helper_src = inspect.getsource(provision._hosting_service_for_lifecycle)
        assert "_cp_settings_for_service" in helper_src
        for route in ("admin_hosting_suspend", "admin_hosting_unsuspend",
                      "admin_hosting_terminate"):
            src = inspect.getsource(getattr(provision, route))
            assert "_hosting_service_for_lifecycle" in src, f"{route} missing affinity helper"


# ---------------------------------------------------------------------------
# Lifecycle route behavior (mocked DB + client)
# ---------------------------------------------------------------------------
class TestLifecycleBehavior:
    @pytest.mark.asyncio
    async def test_suspend_calls_whm_with_reason(self, monkeypatch):
        svc = {"_id": "aabbccddeeff001122334455", "user_id": "aabbccddeeff001122334458", "category": "hosting",
               "config": {"username": "johndoe", "server_id": "aabbccddeeff001122334459"}}
        s = _settings(name="WHM 1", server_id="aabbccddeeff001122334459")

        monkeypatch.setattr(provision, "_cp_settings_for_service", AsyncMock(return_value=s))
        called = {}
        async def fake_suspend(self, username, reason=""):
            called.update({"username": username, "reason": reason})
            return {}
        monkeypatch.setattr(iv2.CpanelClient, "suspend_account", fake_suspend)

        db = _fake_db(services=[svc])
        monkeypatch.setattr(provision, "_get_db", AsyncMock(return_value=db))
        db.services.find_one = AsyncMock(return_value=svc)
        db.services.update_one = AsyncMock()

        payload = {"reason": "overdue payment"}
        await provision.admin_hosting_suspend("aabbccddeeff001122334455", payload, admin={"name": "Admin"})
        assert called["username"] == "johndoe"
        assert called["reason"] == "overdue payment"

    @pytest.mark.asyncio
    async def test_suspend_marks_service_suspended(self, monkeypatch):
        svc = {"_id": "aabbccddeeff001122334455", "user_id": "aabbccddeeff001122334458", "category": "hosting",
               "config": {"username": "johndoe", "server_id": "aabbccddeeff001122334459"}}
        s = _settings(name="WHM 1", server_id="aabbccddeeff001122334459")
        monkeypatch.setattr(provision, "_cp_settings_for_service", AsyncMock(return_value=s))
        async def fake_suspend(self, username, reason=""):
            return {}
        monkeypatch.setattr(iv2.CpanelClient, "suspend_account", fake_suspend)

        db = _fake_db(services=[svc])
        monkeypatch.setattr(provision, "_get_db", AsyncMock(return_value=db))
        db.services.find_one = AsyncMock(return_value=svc)
        db.services.update_one = AsyncMock()

        await provision.admin_hosting_suspend("aabbccddeeff001122334455", {"reason": "test"}, admin={"name": "Admin"})
        # Verify service was marked suspended
        call_args = db.services.update_one.call_args
        assert "$set" in call_args[0][1]
        assert call_args[0][1]["$set"]["status"] == "suspended"

    @pytest.mark.asyncio
    async def test_terminate_calls_removeacct(self, monkeypatch):
        svc = {"_id": "aabbccddeeff001122334455", "user_id": "aabbccddeeff001122334458", "category": "hosting",
               "config": {"username": "johndoe", "server_id": "aabbccddeeff001122334459"}}
        s = _settings(name="WHM 1", server_id="aabbccddeeff001122334459")
        monkeypatch.setattr(provision, "_cp_settings_for_service", AsyncMock(return_value=s))
        called = {}
        async def fake_remove(self, username):
            called["username"] = username
            return {}
        monkeypatch.setattr(iv2.CpanelClient, "remove_account", fake_remove)

        db = _fake_db(services=[svc])
        monkeypatch.setattr(provision, "_get_db", AsyncMock(return_value=db))
        db.services.find_one = AsyncMock(return_value=svc)
        db.services.update_one = AsyncMock()

        await provision.admin_hosting_terminate("aabbccddeeff001122334455", {"confirm": True}, admin={"name": "Admin"})
        assert called["username"] == "johndoe"

    @pytest.mark.asyncio
    async def test_terminate_requires_confirm(self, monkeypatch):
        svc = {"_id": "aabbccddeeff001122334455", "user_id": "aabbccddeeff001122334458", "category": "hosting",
               "config": {"username": "johndoe", "server_id": "aabbccddeeff001122334459"}}
        db = _fake_db(services=[svc])
        monkeypatch.setattr(provision, "_get_db", AsyncMock(return_value=db))
        db.services.find_one = AsyncMock(return_value=svc)
        with pytest.raises(HTTPException) as ei:
            await provision.admin_hosting_terminate("aabbccddeeff001122334455", {"confirm": False}, admin={"name": "Admin"})
        assert ei.value.status_code == 400

    @pytest.mark.asyncio
    async def test_password_change_calls_whm(self, monkeypatch):
        svc = {"_id": "aabbccddeeff001122334455", "user_id": "aabbccddeeff001122334458", "category": "hosting",
               "config": {"username": "johndoe", "server_id": "aabbccddeeff001122334459"}}
        s = _settings(name="WHM 1", server_id="aabbccddeeff001122334459")
        monkeypatch.setattr(provision, "_cp_settings_for_service", AsyncMock(return_value=s))
        called = {}
        async def fake_passwd(self, username, password):
            called.update({"username": username, "password": password})
            return {}
        monkeypatch.setattr(iv2.CpanelClient, "change_password", fake_passwd)

        db = _fake_db(services=[svc])
        monkeypatch.setattr(provision, "_get_db", AsyncMock(return_value=db))
        db.services.find_one = AsyncMock(return_value=svc)
        db.services.update_one = AsyncMock()

        await provision.admin_hosting_password("aabbccddeeff001122334455", {"new_password": "newpass123"}, admin={"name": "Admin"})
        assert called["username"] == "johndoe"
        assert called["password"] == "newpass123"

    @pytest.mark.asyncio
    async def test_package_change_calls_whm(self, monkeypatch):
        svc = {"_id": "aabbccddeeff001122334455", "user_id": "aabbccddeeff001122334458", "category": "hosting",
               "config": {"username": "johndoe", "server_id": "aabbccddeeff001122334459", "whm_package": "uxzjdmsf_starter"}}
        s = _settings(name="WHM 1", server_id="aabbccddeeff001122334459")
        monkeypatch.setattr(provision, "_cp_settings_for_service", AsyncMock(return_value=s))
        called = {}
        async def fake_pkg(self, username, package):
            called.update({"username": username, "package": package})
            return {}
        monkeypatch.setattr(iv2.CpanelClient, "change_package", fake_pkg)
        monkeypatch.setattr(iv2.CpanelClient, "list_packages", AsyncMock(return_value=["uxzjdmsf_starter", "uxzjdmsf_business"]))

        db = _fake_db(services=[svc])
        monkeypatch.setattr(provision, "_get_db", AsyncMock(return_value=db))
        db.services.find_one = AsyncMock(return_value=svc)
        db.services.update_one = AsyncMock()

        await provision.admin_hosting_package("aabbccddeeff001122334455", {"package": "uxzjdmsf_business"}, admin={"name": "Admin"})
        assert called["username"] == "johndoe"
        assert called["package"] == "uxzjdmsf_business"

    @pytest.mark.asyncio
    async def test_lifecycle_returns_404_for_missing_service(self, monkeypatch):
        db = _fake_db(services=[])
        monkeypatch.setattr(provision, "_get_db", AsyncMock(return_value=db))
        db.services.find_one = AsyncMock(return_value=None)
        with pytest.raises(HTTPException) as ei:
            await provision.admin_hosting_suspend("nonexistent", {"reason": "x"}, admin={"name": "Admin"})
        assert ei.value.status_code == 404

    @pytest.mark.asyncio
    async def test_lifecycle_returns_400_for_non_hosting(self, monkeypatch):
        svc = {"_id": "aabbccddeeff001122334455", "user_id": "aabbccddeeff001122334458", "category": "vps",
               "config": {"username": "johndoe", "server_id": "aabbccddeeff001122334459"}}
        db = _fake_db(services=[svc])
        monkeypatch.setattr(provision, "_get_db", AsyncMock(return_value=db))
        db.services.find_one = AsyncMock(return_value=svc)
        with pytest.raises(HTTPException) as ei:
            await provision.admin_hosting_suspend("aabbccddeeff001122334455", {"reason": "x"}, admin={"name": "Admin"})
        assert ei.value.status_code == 400

    @pytest.mark.asyncio
    async def test_lifecycle_returns_400_when_no_username(self, monkeypatch):
        svc = {"_id": "aabbccddeeff001122334455", "user_id": "aabbccddeeff001122334458", "category": "hosting",
               "config": {"server_id": "aabbccddeeff001122334459"}}  # no username
        db = _fake_db(services=[svc])
        monkeypatch.setattr(provision, "_get_db", AsyncMock(return_value=db))
        db.services.find_one = AsyncMock(return_value=svc)
        with pytest.raises(HTTPException) as ei:
            await provision.admin_hosting_suspend("aabbccddeeff001122334455", {"reason": "x"}, admin={"name": "Admin"})
        assert ei.value.status_code == 400
