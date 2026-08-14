"""Tests for SNMP graph collectors: _clean_visible_roles, poll_snmp, probe_graph.

Uses fake DB and monkeypatched run_ping/poll_snmp to avoid real network calls.
"""
from unittest.mock import AsyncMock

import pytest
from bson import ObjectId

from portal import monitoring_graphs as mg


# ---------------------------------------------------------------------------
# _clean_visible_roles
# ---------------------------------------------------------------------------
def test_visible_roles_none_defaults():
    assert mg._clean_visible_roles(None) == ["admin", "support"]


def test_visible_roles_empty_list_defaults():
    assert mg._clean_visible_roles([]) == ["admin", "support"]


def test_visible_roles_single_role():
    assert mg._clean_visible_roles("sales") == ["sales"]


def test_visible_roles_comma_string():
    assert mg._clean_visible_roles("admin, sales, finance") == ["admin", "sales", "finance"]


def test_visible_roles_list():
    assert mg._clean_visible_roles(["admin", "support"]) == ["admin", "support"]


def test_visible_roles_filters_invalid():
    assert mg._clean_visible_roles(["admin", "hacker", "support"]) == ["admin", "support"]


def test_visible_roles_all_invalid_defaults():
    assert mg._clean_visible_roles(["hacker", "root"]) == ["admin", "support"]


def test_valid_visible_roles_contains_expected():
    assert {"admin", "support", "owner", "sales", "finance", "creative", "ticket_only"} <= mg.VALID_VISIBLE_ROLES


def test_system_sensor_oids_are_hr_mib_compatible():
    """Discovery must use OIDs exposed by MikroTik, not Linux UCD-SNMP only OIDs."""
    assert mg._SYSTEM_SENSORS["cpu_load"]["oid"] == "1.3.6.1.2.1.25.3.3.1.2"
    assert mg._SYSTEM_SENSORS["system_uptime"]["oid"] == "1.3.6.1.2.1.1.3.0"
    # Memory is no longer a static OID: it's discovered dynamically from
    # hrStorageType so the RAM row index isn't hardcoded to 65536.
    assert "memory_used" not in mg._SYSTEM_SENSORS
    assert "memory_total" not in mg._SYSTEM_SENSORS


def test_is_hr_storage_ram_matches_numeric_and_symbolic():
    assert mg._is_hr_storage_ram("1.3.6.1.2.1.25.2.1.2")
    assert mg._is_hr_storage_ram('"1.3.6.1.2.1.25.2.1.2"')
    assert mg._is_hr_storage_ram("hrStorageRam")
    assert not mg._is_hr_storage_ram("1.3.6.1.2.1.25.2.1.4")


def test_storage_index_from_oid():
    assert mg._storage_index_from_oid("1.3.6.1.2.1.25.2.3.1.2.65536") == "65536"
    assert mg._storage_index_from_oid("1.3.6.1.2.1.25.2.3.1.2.1") == "1"


# ---------------------------------------------------------------------------
# _clean helpers
# ---------------------------------------------------------------------------
def test_clean_graph_name_rejects_empty():
    with pytest.raises(ValueError):
        mg._clean_graph_name("")


def test_clean_graph_name_trims():
    assert mg._clean_graph_name("  Router  ") == "Router"


def test_clean_graph_interval_bounds():
    assert mg._clean_graph_interval(20) == 20
    assert mg._clean_graph_interval(30) == 30
    assert mg._clean_graph_interval(3600) == 3600
    with pytest.raises(ValueError):
        mg._clean_graph_interval(19)
    with pytest.raises(ValueError):
        mg._clean_graph_interval(3601)


def test_clean_oid_rejects_empty():
    with pytest.raises(ValueError):
        mg._clean_oid("")


def test_clean_community_default_public():
    assert mg._clean_community(None) == "public"


# ---------------------------------------------------------------------------
# poll_snmp
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_poll_snmp_missing_binary(monkeypatch):
    async def _fake_exec(*_a, **_kw):
        raise FileNotFoundError()
    monkeypatch.setattr(mg.asyncio, "create_subprocess_exec", _fake_exec)
    out = await mg.poll_snmp("8.8.8.8", "1.3.6.1", "public")
    assert out["error"] == "snmpget not installed"
    assert out["value"] is None


@pytest.mark.anyio
async def test_poll_snmp_parses_numeric_value(monkeypatch):
    class _Proc:
        returncode = 0
        async def communicate(self):
            return b"1.3.6.1.2.1.1.3.0 = Timeticks: (12345) 0:02:03.45", b""
    async def _fake_exec(*_a, **_kw):
        return _Proc()
    monkeypatch.setattr(mg.asyncio, "create_subprocess_exec", _fake_exec)
    out = await mg.poll_snmp("8.8.8.8", "1.3.6.1", "public")
    assert out["error"] is None
    assert out["value"] is not None


@pytest.mark.anyio
async def test_poll_snmp_nonzero_returncode(monkeypatch):
    class _Proc:
        returncode = 1
        async def communicate(self):
            return b"", b"No Such Object"
    async def _fake_exec(*_a, **_kw):
        return _Proc()
    monkeypatch.setattr(mg.asyncio, "create_subprocess_exec", _fake_exec)
    out = await mg.poll_snmp("8.8.8.8", "1.3.6.1", "public")
    assert out["error"] == "No Such Object"
    assert out["value"] is None


# ---------------------------------------------------------------------------
# discover_snmp_sensors memory row discovery
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_discover_snmp_sensors_finds_memory_by_hr_storage_type(monkeypatch):
    """RAM index is not always 65536; discover it from hrStorageType."""

    async def fake_walk(target, base_oid, *args, **kwargs):
        if base_oid == mg._IF_NAME_OID:
            return {}  # no interfaces in this focused test
        if base_oid == mg._HR_STORAGE_TYPE_OID:
            return {
                f"{mg._HR_STORAGE_TYPE_OID}.1": "hrStorageRam",
                f"{mg._HR_STORAGE_TYPE_OID}.2": "hrStorageVirtualMemory",
            }
        if base_oid == mg._HR_STORAGE_USED_OID:
            return {f"{mg._HR_STORAGE_USED_OID}.1": "1234"}
        if base_oid == mg._HR_STORAGE_SIZE_OID:
            return {f"{mg._HR_STORAGE_SIZE_OID}.1": "4096"}
        if base_oid == "1.3.6.1.2.1.1.3.0":
            return {"1.3.6.1.2.1.1.3.0": "(123456) 1:23:45.67"}
        return {}

    monkeypatch.setattr(mg, "_walk_oid", fake_walk)
    out = await mg.discover_snmp_sensors("8.8.8.8")
    assert out["ok"] is True
    memory_sensors = [s for s in out["sensors"] if s["kind"] == "snmp_memory"]
    assert len(memory_sensors) == 2
    labels = {s["label"] for s in memory_sensors}
    assert labels == {"Memory Used", "Memory Total"}
    used_sensor = next(s for s in memory_sensors if s["label"] == "Memory Used")
    assert used_sensor["oid"] == "1.3.6.1.2.1.25.2.3.1.6.1"
    assert used_sensor["value"] == "1234"


@pytest.mark.anyio
async def test_discover_snmp_sensors_numeric_hr_storage_type(monkeypatch):
    """Some agents return the numeric OID for hrStorageRam instead of name."""

    async def fake_walk(target, base_oid, *args, **kwargs):
        if "if" in base_oid:
            # crude but enough to avoid interface discovery
            return {}
        if base_oid == mg._HR_STORAGE_TYPE_OID:
            return {f"{mg._HR_STORAGE_TYPE_OID}.65536": mg._HR_STORAGE_RAM_TYPE}
        if base_oid == mg._HR_STORAGE_USED_OID:
            return {f"{mg._HR_STORAGE_USED_OID}.65536": "500"}
        if base_oid == mg._HR_STORAGE_SIZE_OID:
            return {f"{mg._HR_STORAGE_SIZE_OID}.65536": "1000"}
        return {}

    monkeypatch.setattr(mg, "_walk_oid", fake_walk)
    out = await mg.discover_snmp_sensors("8.8.8.8")
    assert out["ok"] is True
    used_sensor = next(
        (s for s in out["sensors"] if s["label"] == "Memory Used"), None
    )
    assert used_sensor is not None
    assert used_sensor["oid"] == "1.3.6.1.2.1.25.2.3.1.6.65536"


# ---------------------------------------------------------------------------
# probe_graph (SNMP path)
# ---------------------------------------------------------------------------
class _Samples:
    def __init__(self):
        self.inserted = []
    async def insert_one(self, doc):
        self.inserted.append(doc)


class _Db:
    def __init__(self):
        self.monitoring_graph_samples_raw = _Samples()


@pytest.mark.anyio
async def test_probe_graph_snmp_stores_sample(monkeypatch):
    db = _Db()
    graph = {
        "_id": ObjectId(), "type": "snmp_traffic", "target": "8.8.8.8",
        "snmp_oid": "1.3.6.1", "snmp_community": "public", "snmp_port": 161,
        "snmp_version": "2c",
    }
    monkeypatch.setattr(mg, "poll_snmp", AsyncMock(return_value={"value": 42.5, "raw": "x", "error": None}))
    out = await mg.probe_graph(db, graph=graph, owner="host:1")
    assert out["probed"] is True
    assert out["value"] == 42.5
    assert len(db.monitoring_graph_samples_raw.inserted) == 1
    sample = db.monitoring_graph_samples_raw.inserted[0]
    assert sample["graph_id"] == str(graph["_id"])
    assert sample["value"] == 42.5


@pytest.mark.anyio
async def test_probe_graph_snmp_error_skips(monkeypatch):
    db = _Db()
    graph = {
        "_id": ObjectId(), "type": "snmp_traffic", "target": "8.8.8.8",
        "snmp_oid": "1.3.6.1", "snmp_community": "public", "snmp_port": 161,
        "snmp_version": "2c",
    }
    monkeypatch.setattr(mg, "poll_snmp", AsyncMock(return_value={"value": None, "raw": "", "error": "timeout"}))
    out = await mg.probe_graph(db, graph=graph, owner="host:1")
    assert out["skipped"] is True
    assert out["error"] == "timeout"
    assert db.monitoring_graph_samples_raw.inserted == []


@pytest.mark.anyio
async def test_probe_graph_ping_path(monkeypatch):
    db = _Db()
    graph = {
        "_id": ObjectId(), "type": "ping", "target": "8.8.8.8",
    }
    async def fake_ping(_target, count=None, timeout=None):
        return {"summary": {"avg_ms": 12.3}}
    monkeypatch.setattr(mg, "resolve_ip", lambda h: h)
    monkeypatch.setattr(mg, "validate_target", lambda h: h)
    monkeypatch.setattr("portal.diagnostics.run_ping", fake_ping)
    out = await mg.probe_graph(db, graph=graph, owner="host:1")
    assert out["probed"] is True
    assert out["value"] == 12.3
    assert len(db.monitoring_graph_samples_raw.inserted) == 1
    assert db.monitoring_graph_samples_raw.inserted[0]["value"] == 12.3


# ---------------------------------------------------------------------------
# serialize_graph
# ---------------------------------------------------------------------------
def test_serialize_graph_includes_visible_roles():
    doc = {"_id": ObjectId(), "name": "G", "target": "8.8.8.8",
           "visible_roles": ["admin", "sales"]}
    out = mg.serialize_graph(doc)
    assert out["visible_roles"] == ["admin", "sales"]


def test_serialize_graph_defaults_visible_roles():
    doc = {"_id": ObjectId(), "name": "G", "target": "8.8.8.8"}
    out = mg.serialize_graph(doc)
    assert out["visible_roles"] == ["admin", "support"]


def test_serialize_graph_does_not_leak_auth_keys():
    doc = {"_id": ObjectId(), "name": "G", "target": "8.8.8.8",
           "snmp_auth_key": "secret", "snmp_priv_key": "secret2"}
    out = mg.serialize_graph(doc)
    assert "snmp_auth_key" not in out
    assert "snmp_priv_key" not in out
