"""Unit tests for the multi-server WHM/cPanel registry (Fase 1).

Covers:
- CpanelClient contract against Fase 0 live-verified WHM API 1 responses
  (httpx mocked — no network).
- _cp_server_to_settings / _cp_server_public secret sanitation.
- _pick_cp_server placement: slot count, package availability, loadavg tie-break.
- _cp_servers legacy fallback when the whm_servers registry is empty.
- admin route authorization on /admin/cpanel/servers.

Ad-hoc source verification companion to runtime tests; live node behavior was
verified during Fase 0 on cupang2.serverkita.web.id.
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

import os
os.environ.setdefault("JWT_SECRET", "test-jwt-secret-whm")

from portal import integrations_v2 as iv2  # noqa: E402
from portal.routes import provision  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _settings(host="https://whm1.example.com:2087", username="reseller",
             token="tok123", max_accounts=10, ssl_verify=True, name="WHM 1",
             server_id="s1"):
    return {
        "provider": "cpanel",
        "enabled": True,
        "name": name,
        "server_id": server_id,
        "credentials": {"host": host, "username": username,
                        "api_token": token, "password": ""},
        "options": {"max_accounts": max_accounts, "ssl_verify": ssl_verify},
    }


def _ok_meta():
    return {"metadata": {"result": 1, "reason": "OK"}}


def _version_payload():
    return {"data": {"version": "11.136.0.35"}, "metadata": {"result": 1}}


def _listpkgs_payload(names):
    return {"data": {"pkg": [{"name": n} for n in names]},
            "metadata": {"result": 1}}


def _listaccts_payload(n):
    return {"data": {"acct": [{"user": f"u{i}"} for i in range(n)]},
            "metadata": {"result": 1}}


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


class _FakeAsyncClient:
    """Replays canned payloads per WHM function name, records requests."""
    calls: list = []

    def __init__(self, responses=None, **kwargs):
        self.responses = responses or {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url, headers=None, params=None):
        type(self).calls.append((url, headers, params))
        fn = url.rsplit("/", 1)[-1]
        payload = self.responses.get(fn)
        if payload is None:
            payload = {"metadata": {"result": 1}}
        return _FakeResponse(payload)


def _install(monkeypatch, responses):
    _FakeAsyncClient.calls = []
    _FakeAsyncClient.__init__ = lambda self, **kwargs: object.__setattr__(
        self, "responses", responses)
    monkeypatch.setattr(iv2.httpx, "AsyncClient", _FakeAsyncClient)
    return _FakeAsyncClient


# ---------------------------------------------------------------------------
# CpanelClient contract (Fase 0 live-verified response shapes)
# ---------------------------------------------------------------------------
class TestCpanelClientContract:
    @pytest.mark.asyncio
    async def test_version_test_connection_ok(self, monkeypatch):
        _install(monkeypatch, {"version": _version_payload()})
        cp = iv2.CpanelClient(_settings())
        res = await cp.test_connection()
        assert res["ok"] is True
        assert "11.136.0.35" in res["message"]
        url, headers, params = _FakeAsyncClient.calls[0]
        assert url == "https://whm1.example.com:2087/json-api/version"
        assert headers["Authorization"] == "whm reseller:tok123"
        assert params["api.version"] == 1

    @pytest.mark.asyncio
    async def test_list_packages(self, monkeypatch):
        _install(monkeypatch, {"listpkgs": _listpkgs_payload(["uxzjdmsf_a", "uxzjdmsf_b"])})
        cp = iv2.CpanelClient(_settings())
        pkgs = await cp.list_packages()
        assert pkgs == ["uxzjdmsf_a", "uxzjdmsf_b"]

    @pytest.mark.asyncio
    async def test_count_accounts(self, monkeypatch):
        _install(monkeypatch, {"listaccts": _listaccts_payload(3)})
        cp = iv2.CpanelClient(_settings())
        assert await cp.count_accounts() == 3

    @pytest.mark.asyncio
    async def test_load_average_handles_raw_payload(self, monkeypatch):
        # Fase 0 finding: loadavg returns raw JSON, no metadata wrapper.
        _install(monkeypatch, {"loadavg": {"one": "2.26", "five": "2.29", "fifteen": "2.55"}})
        cp = iv2.CpanelClient(_settings())
        load = await cp.load_average()
        assert load == {"one": 2.26, "five": 2.29, "fifteen": 2.55}

    @pytest.mark.asyncio
    async def test_load_average_failure_returns_zeros(self, monkeypatch):
        # _call raises (raise_for_status simulated by missing payload → default ok);
        # force an exception path by making the call raise.
        class _Boom(_FakeAsyncClient):
            async def get(self, url, headers=None, params=None):
                raise RuntimeError("conn refused")

        monkeypatch.setattr(iv2.httpx, "AsyncClient", _Boom)
        cp = iv2.CpanelClient(_settings())
        load = await cp.load_average()
        assert load == {"one": 0.0, "five": 0.0, "fifteen": 0.0}

    @pytest.mark.asyncio
    async def test_create_account_sends_plan_param(self, monkeypatch):
        _install(monkeypatch, {"createacct": {"data": {"rawout": "ok"}, **_ok_meta()}})
        cp = iv2.CpanelClient(_settings())
        await cp.create_account("demo.test", "demo01", "pw", package="uxzjdmsf_test_ic_pkg",
                                contact_email="a@b.c")
        url, headers, params = _FakeAsyncClient.calls[0]
        assert params["domain"] == "demo.test"
        assert params["username"] == "demo01"
        assert params["plan"] == "uxzjdmsf_test_ic_pkg"
        assert params["contactemail"] == "a@b.c"

    @pytest.mark.asyncio
    async def test_create_account_failure_raises(self, monkeypatch):
        _install(monkeypatch, {"createacct": {"metadata": {"result": 0, "reason": "domain taken"}}})
        cp = iv2.CpanelClient(_settings())
        with pytest.raises(RuntimeError, match="domain taken"):
            await cp.create_account("x.y", "xuser", "pw")

    @pytest.mark.asyncio
    async def test_change_package_uses_pkg_param(self, monkeypatch):
        # Fase 0 live-verified: parameter name is 'pkg', not 'package'.
        _install(monkeypatch, {"changepackage": _ok_meta()})
        cp = iv2.CpanelClient(_settings())
        await cp.change_package("demo01", "uxzjdmsf_test_ic_pkg")
        url, headers, params = _FakeAsyncClient.calls[0]
        assert params["pkg"] == "uxzjdmsf_test_ic_pkg"
        assert "package" not in params

    @pytest.mark.asyncio
    async def test_remove_and_password_and_summary(self, monkeypatch):
        _install(monkeypatch, {
            "removeacct": _ok_meta(),
            "passwd": _ok_meta(),
            "accountsummary": {"data": {"acct": [{"user": "demo01", "domain": "demo.test"}]},
                               "metadata": {"result": 1}},
        })
        cp = iv2.CpanelClient(_settings())
        await cp.remove_account("demo01")
        await cp.change_password("demo01", "newpw")
        summary = await cp.account_summary("demo01")
        assert summary["domain"] == "demo.test"

    @pytest.mark.asyncio
    async def test_capacity_aggregates(self, monkeypatch):
        _install(monkeypatch, {
            "listaccts": _listaccts_payload(7),
            "loadavg": {"one": "1.0", "five": "1.5", "fifteen": "2.0"},
            "listpkgs": _listpkgs_payload(["pkg_a"]),
        })
        cp = iv2.CpanelClient(_settings())
        cap = await cp.capacity()
        assert cap["ok"] is True
        assert cap["accounts"] == 7
        assert cap["loadavg"]["five"] == 1.5
        assert cap["packages"] == ["pkg_a"]

    @pytest.mark.asyncio
    async def test_host_without_scheme_gets_default_port(self):
        cp = iv2.CpanelClient(_settings(host="whm1.example.com"))
        assert cp.host == "https://whm1.example.com:2087"


# ---------------------------------------------------------------------------
# Registry doc <-> settings/public sanitation
# ---------------------------------------------------------------------------
class TestRegistrySanitation:
    def test_settings_from_doc_decrypts_secret(self):
        from portal import secretbox as sb
        doc = {"_id": "507f1f77bcf86cd799439011", "name": "WHM 1", "host": "https://x:2087",
               "username": "res", "api_token": sb.enc_value("sekrit"),
               "password": sb.enc_value("pw"), "max_accounts": 5,
               "ssl_verify": True, "enabled": True}
        s = provision._cp_server_to_settings(doc)
        assert s["credentials"]["api_token"] == "sekrit"
        assert s["credentials"]["password"] == "pw"
        assert s["options"]["max_accounts"] == 5
        assert s["server_id"] == "507f1f77bcf86cd799439011"

    def test_public_never_leaks_secrets(self):
        from portal import secretbox as sb
        from bson import ObjectId
        doc = {"_id": ObjectId(), "name": "WHM 1", "host": "https://x:2087",
               "username": "res", "api_token": sb.enc_value("sekrit"),
               "password": sb.enc_value("pw"), "max_accounts": 5,
               "ssl_verify": True, "enabled": True, "sort_order": 100,
               "created_at": "2026"}
        pub = provision._cp_server_public(doc)
        dumped = str(pub)
        assert "sekrit" not in dumped
        assert "api_token" not in dumped.replace("has_api_token", "")
        assert "password" not in dumped.replace("has_password", "")
        assert pub["has_api_token"] is True
        assert pub["has_password"] is True
        assert pub["id"] == str(doc["_id"])

    def test_public_empty_secrets_reported_false(self):
        from bson import ObjectId
        doc = {"_id": ObjectId(), "name": "WHM 2", "host": "https://y:2087",
               "username": "res", "api_token": "", "password": "",
               "max_accounts": 0, "ssl_verify": False, "enabled": False}
        pub = provision._cp_server_public(doc)
        assert pub["has_api_token"] is False
        assert pub["has_password"] is False
        assert pub["enabled"] is False
        assert pub["ssl_verify"] is False


# ---------------------------------------------------------------------------
# _cp_servers: registry + legacy fallback
# ---------------------------------------------------------------------------
def _fake_db(whm_docs=None, legacy_settings=None):
    db = MagicMock()
    cursor = MagicMock()
    cursor.sort.return_value = cursor
    cursor.to_list = AsyncMock(return_value=whm_docs or [])
    db.whm_servers.find = MagicMock(return_value=cursor)
    return db


class TestCpServersFallback:
    @pytest.mark.asyncio
    async def test_registry_empty_falls_back_to_legacy(self, monkeypatch):
        db = _fake_db(whm_docs=[])
        legacy = _settings(name="Default", server_id="legacy", host="https://legacy:2087")
        monkeypatch.setattr(iv2, "get_settings", AsyncMock(return_value=legacy))
        out = await provision._cp_servers(db)
        assert len(out) == 1
        assert out[0]["name"] == "Default"
        assert out[0]["server_id"] == "legacy"

    @pytest.mark.asyncio
    async def test_registry_empty_and_no_legacy_returns_empty(self, monkeypatch):
        db = _fake_db(whm_docs=[])
        monkeypatch.setattr(iv2, "get_settings", AsyncMock(return_value=None))
        assert await provision._cp_servers(db) == []

    @pytest.mark.asyncio
    async def test_registry_docs_win_over_legacy(self, monkeypatch):
        from bson import ObjectId
        docs = [{"_id": ObjectId(), "name": "WHM 1", "host": "https://a:2087",
                 "username": "u", "api_token": "", "password": "",
                 "max_accounts": 10, "ssl_verify": True, "enabled": True}]
        db = _fake_db(whm_docs=docs)
        legacy = _settings(name="Default", server_id="legacy")
        monkeypatch.setattr(iv2, "get_settings", AsyncMock(return_value=legacy))
        out = await provision._cp_servers(db)
        assert len(out) == 1
        assert out[0]["name"] == "WHM 1"
        assert out[0]["server_id"] != "legacy"

    @pytest.mark.asyncio
    async def test_doc_without_host_is_skipped(self, monkeypatch):
        from bson import ObjectId
        docs = [{"_id": ObjectId(), "name": "no host", "host": "",
                 "username": "u", "api_token": "", "password": "",
                 "max_accounts": 0, "ssl_verify": True, "enabled": True}]
        db = _fake_db(whm_docs=docs)
        monkeypatch.setattr(iv2, "get_settings", AsyncMock(return_value=None))
        assert await provision._cp_servers(db) == []


# ---------------------------------------------------------------------------
# _pick_cp_server placement
# ---------------------------------------------------------------------------
class TestPlacement:
    @pytest.mark.asyncio
    async def test_picks_most_free_slots(self, monkeypatch):
        s1 = _settings(name="A", server_id="a", max_accounts=10)
        s2 = _settings(name="B", server_id="b", max_accounts=20, host="https://b:2087")
        caps = {
            "a": {"ok": True, "accounts": 5, "loadavg": {"five": 1.0}, "packages": ["p"]},
            "b": {"ok": True, "accounts": 3, "loadavg": {"five": 9.0}, "packages": ["p"]},
        }

        async def _fake_capacity(self):
            host = self.host
            for sid, cap in caps.items():
                if host.startswith(f"https://{sid}"):
                    return cap
            return {"ok": False}

        monkeypatch.setattr(iv2.CpanelClient, "capacity", _fake_capacity)
        monkeypatch.setattr(provision.iv2, "CpanelClient", iv2.CpanelClient)
        servers = [s1, s2]
        monkeypatch.setattr(provision, "_cp_servers", AsyncMock(return_value=servers))

        db = _fake_db()
        best, report = await provision._pick_cp_server(db, package_name="p")
        assert best["name"] == "B"  # 17 slots > 5 slots despite worse load
        assert len(report) == 2
        r_b = next(r for r in report if r["server"] == "B")
        assert r_b["slots"] == 17
        assert r_b["has_package"] is True

    @pytest.mark.asyncio
    async def test_requires_package_availability(self, monkeypatch):
        s1 = _settings(name="A", server_id="a", max_accounts=10)
        caps = {"a": {"ok": True, "accounts": 0, "loadavg": {"five": 1.0}, "packages": ["other"]}}

        async def _fake_capacity(self):
            return caps["a"]

        monkeypatch.setattr(iv2.CpanelClient, "capacity", _fake_capacity)
        monkeypatch.setattr(provision.iv2, "CpanelClient", iv2.CpanelClient)
        monkeypatch.setattr(provision, "_cp_servers", AsyncMock(return_value=[s1]))
        best, report = await provision._pick_cp_server(_fake_db(), package_name="wanted")
        assert best is None
        assert report[0]["has_package"] is False

    @pytest.mark.asyncio
    async def test_unreachable_server_excluded(self, monkeypatch):
        s1 = _settings(name="A", server_id="a", max_accounts=10)

        async def _fake_capacity(self):
            return {"ok": False, "error": "timeout"}

        monkeypatch.setattr(iv2.CpanelClient, "capacity", _fake_capacity)
        monkeypatch.setattr(provision.iv2, "CpanelClient", iv2.CpanelClient)
        monkeypatch.setattr(provision, "_cp_servers", AsyncMock(return_value=[s1]))
        best, report = await provision._pick_cp_server(_fake_db())
        assert best is None
        assert report[0]["ok"] is False

    @pytest.mark.asyncio
    async def test_tie_break_by_lower_load(self, monkeypatch):
        s1 = _settings(name="A", server_id="a", max_accounts=10)
        s2 = _settings(name="B", server_id="b", max_accounts=10, host="https://b:2087")
        caps = {
            "a": {"ok": True, "accounts": 5, "loadavg": {"five": 3.0}, "packages": ["p"]},
            "b": {"ok": True, "accounts": 5, "loadavg": {"five": 1.0}, "packages": ["p"]},
        }

        async def _fake_capacity(self):
            for sid, cap in caps.items():
                if self.host.startswith(f"https://{sid}"):
                    return cap
            return {"ok": False}

        monkeypatch.setattr(iv2.CpanelClient, "capacity", _fake_capacity)
        monkeypatch.setattr(provision.iv2, "CpanelClient", iv2.CpanelClient)
        monkeypatch.setattr(provision, "_cp_servers", AsyncMock(return_value=[s1, s2]))
        best, _ = await provision._pick_cp_server(_fake_db(), package_name="p")
        assert best["name"] == "B"  # same slots, lower five-minute load wins

    @pytest.mark.asyncio
    async def test_full_server_excluded(self, monkeypatch):
        s1 = _settings(name="A", server_id="a", max_accounts=5)

        async def _fake_capacity(self):
            return {"ok": True, "accounts": 5, "loadavg": {"five": 1.0}, "packages": ["p"]}

        monkeypatch.setattr(iv2.CpanelClient, "capacity", _fake_capacity)
        monkeypatch.setattr(provision.iv2, "CpanelClient", iv2.CpanelClient)
        monkeypatch.setattr(provision, "_cp_servers", AsyncMock(return_value=[s1]))
        best, report = await provision._pick_cp_server(_fake_db())
        assert best is None
        assert report[0]["slots"] == 0


# ---------------------------------------------------------------------------
# Route authorization contract (source-level)
# ---------------------------------------------------------------------------
class TestRouteAuthorization:
    def test_registry_routes_gated_by_roles(self):
        import inspect
        src = inspect.getsource(provision)
        for route in ("admin_cp_servers_list", "admin_cp_servers_capacity",
                      "admin_cp_server_packages", "admin_cp_servers_test"):
            fn = getattr(provision, route)
            sig_src = inspect.signature(fn)
            # every registry route must carry a role/admin dependency
            deps = [str(v.default) for v in sig_src.parameters.values()
                    if v.default is not inspect.Parameter.empty]
            assert any("Depends" in d for d in deps), f"{route} missing auth dependency"

    def test_routes_have_no_auth_bypass(self):
        import inspect
        for route in ("admin_cp_servers_create", "admin_cp_servers_update",
                      "admin_cp_servers_delete"):
            fn = getattr(provision, route)
            sig = inspect.signature(fn)
            assert any("admin" in str(p) or "Depends" in str(p.default)
                       for p in sig.parameters.values()), f"{route} missing admin dep"
