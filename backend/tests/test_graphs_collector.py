"""Tests for SNMP graph collectors: _clean_visible_roles, poll_snmp, probe_graph.

Uses fake DB and monkeypatched run_ping/poll_snmp to avoid real network calls.
"""
from datetime import datetime, timedelta, timezone
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
    assert mg._is_hr_storage_ram(".1.3.6.1.2.1.25.2.1.2")
    assert mg._is_hr_storage_ram('"1.3.6.1.2.1.25.2.1.2"')
    assert mg._is_hr_storage_ram("hrStorageRam")
    assert not mg._is_hr_storage_ram("1.3.6.1.2.1.25.2.1.4")


def test_parse_walk_line_strips_leading_dot():
    """snmpwalk -On prints a leading dot; normalize to canonical OID."""
    oid, value = mg._parse_walk_line(
        ".1.3.6.1.2.1.25.2.3.1.2.65536 = OID: iso.3.6.1.2.1.25.2.1.2"
    )
    assert oid == "1.3.6.1.2.1.25.2.3.1.2.65536"
    assert value == "iso.3.6.1.2.1.25.2.1.2"


def test_parse_walk_line_keeps_plain_numeric():
    oid, value = mg._parse_walk_line(
        ".1.3.6.1.2.1.25.2.3.1.6.65536 = Gauge32: 1234"
    )
    assert oid == "1.3.6.1.2.1.25.2.3.1.6.65536"
    assert value == "1234"


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


def test_clean_community_rejects_flag_injection():
    with pytest.raises(ValueError):
        mg._clean_community("-M/tmp")
    with pytest.raises(ValueError):
        mg._clean_community("-cpublic")


def test_clean_oid_valid():
    assert mg._clean_oid("1.3.6.1.2.1.1") == "1.3.6.1.2.1.1"
    assert mg._clean_oid("0") == "0"
    assert mg._clean_oid("0.0") == "0.0"
    assert mg._clean_oid("1.0.0.1") == "1.0.0.1"


def test_clean_oid_rejects_invalid():
    with pytest.raises(ValueError):
        mg._clean_oid("")
    with pytest.raises(ValueError):
        mg._clean_oid("1..2")          # empty component
    with pytest.raises(ValueError):
        mg._clean_oid("01.2")          # leading zero
    with pytest.raises(ValueError):
        mg._clean_oid(".1.2")          # leading dot
    with pytest.raises(ValueError):
        mg._clean_oid("1.2.")          # trailing dot
    with pytest.raises(ValueError):
        mg._clean_oid("1.2a")          # non-digit
    with pytest.raises(ValueError):
        mg._clean_oid("-1.3.6")        # flag injection
    with pytest.raises(ValueError):
        mg._clean_oid("-")             # just dash


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


@pytest.mark.anyio
async def test_poll_snmp_no_such_object_on_stdout_is_stale_error(monkeypatch):
    """net-snmp exits 0 and prints the diagnostic to STDOUT for a missing OID.

    Regression guard: the real shape must surface as ``error`` (and be
    recognised as a stale-OID error) so probe_graph's auto-heal path fires.
    Previously the text landed in ``value`` and the healer was dead code.
    """
    class _Proc:
        returncode = 0
        async def communicate(self):
            return (b"1.3.6.1.2.1.31.1.1.1.6.9999 = No Such Object available "
                    b"on this agent at that OID"), b""
    async def _fake_exec(*_a, **_kw):
        return _Proc()
    monkeypatch.setattr(mg.asyncio, "create_subprocess_exec", _fake_exec)
    out = await mg.poll_snmp("8.8.8.8", "1.3.6.1.2.1.31.1.1.1.6.9999", "public")
    assert out["value"] is None
    assert out["error"] is not None
    assert mg._is_stale_oid_error(out["error"])


@pytest.mark.anyio
async def test_poll_snmp_no_such_instance_on_stdout_is_stale_error(monkeypatch):
    """Same for the 'No Such Instance' wording net-snmp emits for bad indices."""
    class _Proc:
        returncode = 0
        async def communicate(self):
            return b"1.3.6.1.2.1.31.1.1.1.6.9999 = No Such Instance currently exists at this OID", b""
    async def _fake_exec(*_a, **_kw):
        return _Proc()
    monkeypatch.setattr(mg.asyncio, "create_subprocess_exec", _fake_exec)
    out = await mg.poll_snmp("8.8.8.8", "1.3.6.1.2.1.31.1.1.1.6.9999", "public")
    assert out["value"] is None
    assert mg._is_stale_oid_error(out["error"])


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
        if base_oid == mg._HR_STORAGE_ALLOCATION_UNITS_OID:
            return {f"{mg._HR_STORAGE_ALLOCATION_UNITS_OID}.1": "1024"}
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
    assert used_sensor.get("hr_storage_allocation_units") == "1024"


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


class _Graphs:
    """Minimal stand-in for the monitoring_graphs collection."""
    def __init__(self):
        self.updates = []
    async def update_one(self, flt, update):
        self.updates.append((flt, update))


class _Db:
    def __init__(self):
        self.monitoring_graph_samples_raw = _Samples()
        self.monitoring_graphs = _Graphs()


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


def test_serialize_graph_exposes_poll_status():
    """A graph that stopped sampling must be distinguishable from an idle one."""
    doc = {"_id": ObjectId(), "name": "G", "target": "8.8.8.8",
           "last_poll_state": "error", "last_poll_error": "No Such Object"}
    out = mg.serialize_graph(doc)
    assert out["last_poll_state"] == "error"
    assert out["last_poll_error"] == "No Such Object"


def test_serialize_graph_poll_status_defaults_empty():
    doc = {"_id": ObjectId(), "name": "G", "target": "8.8.8.8"}
    out = mg.serialize_graph(doc)
    assert out["last_poll_state"] == ""
    assert out["last_poll_error"] == ""


# ---------------------------------------------------------------------------
# _record_graph_status
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_probe_graph_records_ok_status(monkeypatch):
    db = _Db()
    graph = {
        "_id": ObjectId(), "type": "snmp_traffic", "target": "8.8.8.8",
        "snmp_oid": "1.3.6.1", "snmp_community": "public", "snmp_port": 161,
        "snmp_version": "2c",
    }
    monkeypatch.setattr(mg, "poll_snmp", AsyncMock(
        return_value={"value": 42.5, "raw": "x", "error": None}))
    await mg.probe_graph(db, graph=graph, owner="host:1")
    assert len(db.monitoring_graphs.updates) == 1
    _flt, update = db.monitoring_graphs.updates[0]
    assert update["$set"]["last_poll_state"] == "ok"
    assert update["$set"]["last_poll_at"] is not None


@pytest.mark.anyio
async def test_probe_graph_records_error_status(monkeypatch):
    """The stale-OID failure mode that silently killed 4 production graphs."""
    db = _Db()
    graph = {
        "_id": ObjectId(), "type": "snmp_traffic", "target": "8.8.8.8",
        "snmp_oid": "1.3.6.1", "snmp_community": "public", "snmp_port": 161,
        "snmp_version": "2c",
    }
    monkeypatch.setattr(mg, "poll_snmp", AsyncMock(
        return_value={"value": None, "raw": "",
                      "error": "No Such Object available on this agent at this OID"}))
    out = await mg.probe_graph(db, graph=graph, owner="host:1")
    assert out["skipped"] is True
    _flt, update = db.monitoring_graphs.updates[0]
    assert update["$set"]["last_poll_state"] == "error"
    assert "No Such Object" in update["$set"]["last_poll_error"]


@pytest.mark.anyio
async def test_record_graph_status_never_raises():
    """Status bookkeeping is advisory: a DB hiccup must not break collection."""
    class _Boom:
        async def update_one(self, *_a, **_kw):
            raise RuntimeError("mongo down")
    db = _Db()
    db.monitoring_graphs = _Boom()
    await mg._record_graph_status(db, graph={"_id": ObjectId()}, state="ok")


def test_sweep_concurrency_is_bounded():
    """Sweep must poll concurrently but stay bounded to avoid SNMP floods."""
    assert 1 < mg._SWEEP_CONCURRENCY <= 32


# ---------------------------------------------------------------------------
# run_graph_sweep concurrency
# ---------------------------------------------------------------------------
class _SweepCursor:
    def __init__(self, docs):
        self._docs = docs
    async def to_list(self, _limit):
        return list(self._docs)


class _SweepGraphsCol:
    def __init__(self, docs):
        self._docs = docs
    def find(self, *_a, **_kw):
        return _SweepCursor(self._docs)
    async def update_one(self, *_a, **_kw):
        return None


class _SweepSamplesCol:
    def __init__(self):
        self.inserted = []
    async def insert_one(self, doc):
        self.inserted.append(doc)
    async def find_one(self, *_a, **_kw):
        return None  # nothing sampled yet -> everything is due


class _SweepDb:
    def __init__(self, docs):
        self.monitoring_graphs = _SweepGraphsCol(docs)
        self.monitoring_graph_samples_raw = _SweepSamplesCol()
        self.scheduler_leases = _LeaseCol()


class _LeaseCol:
    """Lease collection that always grants the lease (single-process test)."""
    def __init__(self):
        self.docs = {}
    async def find_one(self, *_a, **_kw):
        return None
    async def insert_one(self, doc):
        self.docs[doc.get("lease_id")] = doc
    async def delete_one(self, flt, *_a, **_kw):
        self.docs.pop(flt.get("lease_id"), None)
        return type("R", (), {"deleted_count": 1})()
    async def update_one(self, *_a, **_kw):
        return None
    async def find_one_and_update(self, query, update, *_a, **_kw):
        """Grant the lease unconditionally (single-process test)."""
        doc = dict(update["$set"])
        doc["_id"] = query.get("_id")
        doc["owner"] = update["$set"]["owner"]
        self.docs[doc["_id"]] = doc
        return doc


@pytest.mark.anyio
async def test_run_graph_sweep_probes_all_due_graphs(monkeypatch):
    """All due graphs are polled in one sweep (previously serial + half-rate)."""
    docs = [
        {"_id": ObjectId(), "type": "snmp_traffic", "target": "8.8.8.8",
         "snmp_oid": f"1.3.6.1.2.1.31.1.1.1.6.{i}", "snmp_community": "public",
         "snmp_port": 161, "snmp_version": "2c", "enabled": True,
         "interval_seconds": 20}
        for i in range(6)
    ]
    db = _SweepDb(docs)
    seen = []

    async def fake_poll_snmp(target, oid, *a, **kw):
        seen.append(oid)
        return {"value": 1000.0, "raw": "x", "error": None}

    monkeypatch.setattr(mg, "poll_snmp", fake_poll_snmp)
    monkeypatch.setattr(mg, "_load_last_counter", AsyncMock(return_value=None))
    summary = await mg.run_graph_sweep(db, owner="host:1")
    assert summary["checked"] == 6
    assert len(seen) == 6
    assert summary["errors"] == 0


@pytest.mark.anyio
async def test_run_graph_sweep_polls_concurrently(monkeypatch):
    """Proof of concurrency: overlapping polls means the sweep fits its tick.

    A serial sweep of N graphs took longer than the 20s tick, so every second
    tick was skipped and the effective cadence halved.
    """
    docs = [
        {"_id": ObjectId(), "type": "snmp_traffic", "target": "8.8.8.8",
         "snmp_oid": f"1.3.6.1.2.1.31.1.1.1.6.{i}", "snmp_community": "public",
         "snmp_port": 161, "snmp_version": "2c", "enabled": True,
         "interval_seconds": 20}
        for i in range(6)
    ]
    db = _SweepDb(docs)
    in_flight = 0
    max_in_flight = 0

    async def fake_poll_snmp(target, oid, *a, **kw):
        nonlocal in_flight, max_in_flight
        in_flight += 1
        max_in_flight = max(max_in_flight, in_flight)
        await asyncio.sleep(0.01)  # yield so siblings can overlap
        in_flight -= 1
        return {"value": 1000.0, "raw": "x", "error": None}

    monkeypatch.setattr(mg, "poll_snmp", fake_poll_snmp)
    monkeypatch.setattr(mg, "_load_last_counter", AsyncMock(return_value=None))
    await mg.run_graph_sweep(db, owner="host:1")
    assert max_in_flight > 1, "sweep is still serial"


# ---------------------------------------------------------------------------
# run_graph_sweep due-check tolerance
# ---------------------------------------------------------------------------
class _LastAtSamplesCol:
    """Reports a fixed 'last sample' time so we can probe the due-check."""

    def __init__(self, last_at):
        self.last_at = last_at
        self.inserted = []

    async def find_one(self, *_a, **_kw):
        if self.last_at is None:
            return None
        return {"graph_id": "x", "at": self.last_at, "value": 1.0}

    async def insert_one(self, doc):
        self.inserted.append(doc)


class _LastAtDb:
    def __init__(self, docs, last_at):
        self.monitoring_graphs = _SweepGraphsCol(docs)
        self.monitoring_graph_samples_raw = _LastAtSamplesCol(last_at)
        self.scheduler_leases = _LeaseCol()


@pytest.mark.anyio
async def test_sweep_polls_graph_whose_interval_just_elapsed(monkeypatch):
    """A graph 0.09s short of its interval must still be polled.

    Real-world bug: the sweep polls at :00.09 and ticks again at :20.006. The
    strict `last_at + interval > now` test saw a 0.09s shortfall, skipped the
    graph, and the graph was sampled every 40s instead of every 20s.
    """
    now = datetime.now(timezone.utc)
    docs = [{
        "_id": ObjectId(), "type": "snmp_traffic_in", "target": "8.8.8.8",
        "snmp_oid": "1.3.6.1.2.1.31.1.1.1.6.1", "snmp_community": "public",
        "snmp_port": 161, "snmp_version": "2c", "enabled": True,
        "interval_seconds": 20,
    }]
    # Sampled 19.91s ago — 0.09s short of the 20s interval.
    db = _LastAtDb(docs, now - timedelta(seconds=19.91))
    seen = []

    async def fake_poll_snmp(target, oid, *a, **kw):
        seen.append(oid)
        return {"value": 1000.0, "raw": "x", "error": None}

    monkeypatch.setattr(mg, "poll_snmp", fake_poll_snmp)
    monkeypatch.setattr(mg, "_load_last_counter", AsyncMock(return_value=None))
    summary = await mg.run_graph_sweep(db, owner="host:1", now=now)

    assert summary["skipped_not_due"] == 0
    assert len(seen) == 1


@pytest.mark.anyio
async def test_sweep_still_skips_graph_polled_moments_ago(monkeypatch):
    """The tolerance must not turn the sweep into a tight re-poll loop."""
    now = datetime.now(timezone.utc)
    docs = [{
        "_id": ObjectId(), "type": "snmp_traffic_in", "target": "8.8.8.8",
        "snmp_oid": "1.3.6.1.2.1.31.1.1.1.6.1", "snmp_community": "public",
        "snmp_port": 161, "snmp_version": "2c", "enabled": True,
        "interval_seconds": 20,
    }]
    db = _LastAtDb(docs, now - timedelta(seconds=5))
    seen = []

    async def fake_poll_snmp(target, oid, *a, **kw):
        seen.append(oid)
        return {"value": 1000.0, "raw": "x", "error": None}

    monkeypatch.setattr(mg, "poll_snmp", fake_poll_snmp)
    monkeypatch.setattr(mg, "_load_last_counter", AsyncMock(return_value=None))
    summary = await mg.run_graph_sweep(db, owner="host:1", now=now)

    assert summary["skipped_not_due"] == 1
    assert seen == []


def test_due_tolerance_is_small():
    """Tolerance absorbs jitter, not a whole extra poll cycle."""
    assert 0 < mg._DUE_TOLERANCE_SECONDS < mg._MIN_INTERVAL / 2


# ---------------------------------------------------------------------------
# Stale-OID auto-heal (the production failure: ifIndex renumbering)
# ---------------------------------------------------------------------------
def test_is_stale_oid_error_matches_net_snmp_wording():
    assert mg._is_stale_oid_error(
        "No Such Object available on this agent at this OID")
    assert mg._is_stale_oid_error("Timeout: No Such Instance currently exists")
    assert not mg._is_stale_oid_error("Timeout: No Response from 8.8.8.8")


def test_graph_interface_name_prefers_stored_field():
    assert mg._graph_interface_name({"interface_name": '"sfp-sfpplus1"'}) == "sfp-sfpplus1"


def test_graph_interface_name_falls_back_to_title():
    """Legacy graphs predate the stored field; their title carries the name."""
    g = {"name": '"VLAN 108 - RIVAN" (""'}
    assert mg._graph_interface_name(g) == "VLAN 108 - RIVAN"


@pytest.mark.anyio
async def test_heal_stale_oid_remaps_by_interface_name(monkeypatch):
    """Regression: ifIndex 7 -> 42 must be recovered automatically."""
    db = _Db()
    graph = {
        "_id": ObjectId(), "type": "snmp_traffic_in", "target": "157.20.32.253",
        "snmp_oid": "1.3.6.1.2.1.31.1.1.1.6.7",
        "snmp_community": "INTERCLOUD", "interface_name": "sfp-sfpplus1",
    }
    mg._last_remap_attempt.clear()

    async def fake_discover(target, community="public", **kw):
        return {"ok": True, "target": target, "error": None, "sensors": [
            {"category": "interface", "direction": "in",
             "interface_name": '"sfp-sfpplus1"', "interface_index": "42",
             "oid": "1.3.6.1.2.1.31.1.1.1.6.42"},
            {"category": "interface", "direction": "out",
             "interface_name": '"sfp-sfpplus1"', "interface_index": "42",
             "oid": "1.3.6.1.2.1.31.1.1.1.10.42"},
        ]}

    monkeypatch.setattr(mg, "discover_snmp_sensors", fake_discover)
    new_oid = await mg.heal_stale_oid(db, graph=graph)
    assert new_oid == "1.3.6.1.2.1.31.1.1.1.6.42"
    _flt, update = db.monitoring_graphs.updates[0]
    assert update["$set"]["snmp_oid"] == "1.3.6.1.2.1.31.1.1.1.6.42"
    assert update["$set"]["interface_index"] == "42"


@pytest.mark.anyio
async def test_heal_stale_oid_respects_direction(monkeypatch):
    """An IN graph must not be healed onto the OUT counter OID."""
    db = _Db()
    graph = {
        "_id": ObjectId(), "type": "snmp_traffic_in", "target": "10.0.0.1",
        "snmp_oid": "1.3.6.1.2.1.31.1.1.1.6.7", "interface_name": "eth1",
    }
    mg._last_remap_attempt.clear()

    async def fake_discover(target, community="public", **kw):
        return {"ok": True, "sensors": [
            {"category": "interface", "direction": "out",
             "interface_name": '"eth1"', "interface_index": "9",
             "oid": "1.3.6.1.2.1.31.1.1.1.10.9"},
        ]}

    monkeypatch.setattr(mg, "discover_snmp_sensors", fake_discover)
    assert await mg.heal_stale_oid(db, graph=graph) is None
    assert db.monitoring_graphs.updates == []


@pytest.mark.anyio
async def test_heal_stale_oid_ignores_non_counter_graphs(monkeypatch):
    """Ping/CPU graphs have no ifIndex to drift, so healing must not run."""
    db = _Db()
    graph = {"_id": ObjectId(), "type": "snmp_cpu", "target": "10.0.0.1",
             "snmp_oid": "1.3.6.1.2.1.25.3.3.1.2"}
    called = []

    async def fake_discover(*a, **kw):
        called.append(1)
        return {"ok": True, "sensors": []}

    monkeypatch.setattr(mg, "discover_snmp_sensors", fake_discover)
    assert await mg.heal_stale_oid(db, graph=graph) is None
    assert called == []


@pytest.mark.anyio
async def test_heal_stale_oid_throttles_per_target(monkeypatch):
    """A flapping device must not trigger an snmpwalk storm every sweep."""
    db = _Db()
    graph = {"_id": ObjectId(), "type": "snmp_traffic_in", "target": "10.0.0.9",
             "snmp_oid": "1.3.6.1.2.1.31.1.1.1.6.7", "interface_name": "eth1"}
    mg._last_remap_attempt.clear()
    calls = []

    async def fake_discover(*a, **kw):
        calls.append(1)
        return {"ok": True, "sensors": []}

    monkeypatch.setattr(mg, "discover_snmp_sensors", fake_discover)
    await mg.heal_stale_oid(db, graph=graph)
    await mg.heal_stale_oid(db, graph=graph)
    assert len(calls) == 1, "second attempt inside cooldown must be skipped"


@pytest.mark.anyio
async def test_probe_graph_heals_then_retries(monkeypatch):
    """End-to-end: stale OID -> heal -> successful sample in one poll."""
    db = _Db()
    graph = {
        "_id": ObjectId(), "type": "snmp_traffic_in", "target": "157.20.32.253",
        "snmp_oid": "1.3.6.1.2.1.31.1.1.1.6.7", "snmp_community": "INTERCLOUD",
        "snmp_port": 161, "snmp_version": "2c",
        "interface_name": "sfp-sfpplus1", "interval_seconds": 20,
    }
    mg._last_remap_attempt.clear()
    seen_oids = []

    async def fake_poll_snmp(target, oid, *a, **kw):
        seen_oids.append(oid)
        if oid.endswith(".7"):
            return {"value": None, "raw": "",
                    "error": "No Such Object available on this agent at this OID"}
        return {"value": 123456.0, "raw": "x", "error": None}

    async def fake_discover(*a, **kw):
        return {"ok": True, "sensors": [
            {"category": "interface", "direction": "in",
             "interface_name": '"sfp-sfpplus1"', "interface_index": "42",
             "oid": "1.3.6.1.2.1.31.1.1.1.6.42"},
        ]}

    monkeypatch.setattr(mg, "poll_snmp", fake_poll_snmp)
    monkeypatch.setattr(mg, "discover_snmp_sensors", fake_discover)
    monkeypatch.setattr(mg, "_load_last_counter", AsyncMock(
        return_value=({"raw_counter": 100000.0, "at": None})))

    out = await mg.probe_graph(db, graph=graph, owner="host:1")
    assert seen_oids == ["1.3.6.1.2.1.31.1.1.1.6.7", "1.3.6.1.2.1.31.1.1.1.6.42"]
    assert out.get("probed") is True
    assert graph["snmp_oid"] == "1.3.6.1.2.1.31.1.1.1.6.42"


@pytest.mark.anyio
async def test_probe_graph_still_errors_when_heal_finds_nothing(monkeypatch):
    """If the interface is gone entirely, report the error instead of looping."""
    db = _Db()
    graph = {
        "_id": ObjectId(), "type": "snmp_traffic_in", "target": "157.20.32.253",
        "snmp_oid": "1.3.6.1.2.1.31.1.1.1.6.7", "snmp_community": "INTERCLOUD",
        "snmp_port": 161, "snmp_version": "2c", "interface_name": "ghost0",
    }
    mg._last_remap_attempt.clear()

    async def fake_poll_snmp(*a, **kw):
        return {"value": None, "raw": "",
                "error": "No Such Object available on this agent at this OID"}

    async def fake_discover(*a, **kw):
        return {"ok": True, "sensors": []}

    monkeypatch.setattr(mg, "poll_snmp", fake_poll_snmp)
    monkeypatch.setattr(mg, "discover_snmp_sensors", fake_discover)
    out = await mg.probe_graph(db, graph=graph, owner="host:1")
    assert out["skipped"] is True
    _flt, update = db.monitoring_graphs.updates[0]
    assert update["$set"]["last_poll_state"] == "error"
