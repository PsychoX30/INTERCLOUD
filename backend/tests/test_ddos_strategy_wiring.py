"""Test that the detection sweep wires select_mitigation_strategy correctly.

When action="alert_bgp_blackhole", the sweep should:
  - Set mitigation_type="bgp_rtbh" if strategy says bgp_rtbh
    (but NOT execute any router BGP write — only record intent).
  - Set mitigation_type="local_blackhole" and actually blackhole /32
    if strategy says local_blackhole.
  - Set mitigation_type="none" if strategy says alert.

When action="alert" → mitigation_type="none" always.
When action="alert_blackhole" → mitigation_type="local_blackhole" always (legacy).
"""
from __future__ import annotations

import asyncio
import sys
from unittest.mock import MagicMock

import pytest


# Reuse the FakeDB / helpers from the detection test module
sys.path.insert(0, "/home/support/INTERCLOUD/backend/tests")
from test_ddos_detection import (  # noqa: E402
    FakeDB, _rule, _device, _flow, _patch_torch_flows,
)


@pytest.fixture
def db():
    d = FakeDB()
    d.ddos_threshold_rules._docs = []
    d.mikrotik_devices._docs = []
    d.ddos_incidents._docs = []
    d.ddos_samples._docs = []
    d.blackhole_log._docs = []
    d.bgp_blackhole_configs = FakeDB().integration_settings
    return d


@pytest.fixture(autouse=True)
def patch_mikrotik(monkeypatch):
    from portal import integrations_v2 as iv2

    class FakeClient:
        def __init__(self, device=None, *a, **kw):
            self.device = device

        def torch(self, interface="ether1", duration="2s", **kw):
            return {"ok": True, "rows": getattr(self, "_flows", [])}

        def list_interfaces(self):
            return [{"name": "ether1", "running": "true", "disabled": "false"}]

        def blackhole_add(self, prefix, *, comment=""):
            return {"ok": True, "prefix": prefix}

        def blackhole_find_by_prefix(self, prefix):
            return {"id": "route-001", "prefix": prefix}

        def blackhole_remove(self, route_id):
            return {"ok": True, "id": route_id}

    monkeypatch.setattr(iv2, "MikrotikClient", FakeClient)
    from portal import emails as _em
    monkeypatch.setattr(_em, "iv2", iv2)
    async def _gs(*a, **kw):
        return None
    monkeypatch.setattr(iv2, "get_settings", _gs)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

# 1. action=alert → mitigation_type=none, no blackhole
async def test_alert_action_sets_mitigation_none(db, monkeypatch):
    db.ddos_threshold_rules._docs = [_rule(action="alert")]
    db.mikrotik_devices._docs = [_device()]
    flows = [_flow("8.8.8.8", "157.20.32.50", pps=80_000)]
    _patch_torch_flows(monkeypatch, flows)

    from portal.emails import run_ddos_detection_sweep
    await run_ddos_detection_sweep(db)

    inc = db.ddos_incidents._docs[0]
    assert inc["mitigation_type"] == "none"
    assert inc.get("blackholed_prefix") is None
    assert inc["status"] == "active"


# 2. action=alert_blackhole (legacy) → always local_blackhole
async def test_legacy_alert_blackhole_sets_local(db, monkeypatch):
    db.ddos_threshold_rules._docs = [_rule(action="alert_blackhole")]
    db.mikrotik_devices._docs = [_device()]
    flows = [_flow("8.8.8.8", "157.20.32.50", pps=80_000)]
    _patch_torch_flows(monkeypatch, flows)

    from portal.emails import run_ddos_detection_sweep
    await run_ddos_detection_sweep(db)

    inc = db.ddos_incidents._docs[0]
    assert inc["mitigation_type"] == "local_blackhole"
    assert inc["status"] == "mitigated"
    assert inc["blackholed_prefix"] == "157.20.32.50/32"


# 3. action=alert_bgp_blackhole + high severity volumetric + no upstream
#    → strategy=local_blackhole → actually blackhole locally
async def test_bgp_action_no_upstream_falls_back_to_local(db, monkeypatch):
    db.ddos_threshold_rules._docs = [_rule(action="alert_bgp_blackhole")]
    db.mikrotik_devices._docs = [_device()]
    # UDP flood to port 53 → DNS Amplification (volumetric) → high severity
    flows = [_flow("8.8.8.8", "157.20.32.50", proto="udp", dp="53", pps=200_000)]
    _patch_torch_flows(monkeypatch, flows)

    from portal.emails import run_ddos_detection_sweep
    await run_ddos_detection_sweep(db)

    inc = db.ddos_incidents._docs[0]
    assert inc["mitigation_type"] == "local_blackhole"
    assert inc["status"] == "mitigated"


# 4. action=alert_bgp_blackhole + high severity volumetric + upstream available
#    → strategy=bgp_rtbh → record intent, do NOT execute BGP, no local blackhole
async def test_bgp_action_with_upstream_records_intent(db, monkeypatch):
    db.ddos_threshold_rules._docs = [_rule(action="alert_bgp_blackhole")]
    db.mikrotik_devices._docs = [_device()]
    flows = [_flow("8.8.8.8", "157.20.32.50", proto="udp", dp="53", pps=200_000)]
    _patch_torch_flows(monkeypatch, flows)

    # Patch BGP config lookup to return an enabled upstream config
    db.bgp_blackhole_configs._docs = [{
        "_id": "bgp_blackhole_config",
        "enabled": True,
        "bgp_community": "65000:666",
        "upstream_name": "upstream-1",
        "scope_prefixes": ["157.20.32.0/24"],
    }]

    from portal.emails import run_ddos_detection_sweep
    await run_ddos_detection_sweep(db)

    inc = db.ddos_incidents._docs[0]
    assert inc["mitigation_type"] == "bgp_rtbh"
    assert inc["status"] == "active"  # not mitigated — BGP not executed
    assert inc.get("blackholed_prefix") is None  # no local blackhole applied
