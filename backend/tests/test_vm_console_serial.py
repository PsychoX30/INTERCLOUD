"""Tests for VM serial console support (Proxmox termproxy).

Root cause covered: all VMs provisioned by this portal use vga=serial0 +
serial0=socket (headless). Requesting a VNC ticket for such a VM opens a
graphical console that does not exist, so keystrokes never reach the getty on
ttyS0 -- Backspace shows up as a literal ^H and keypad Enter does nothing.

These tests pin the fix:
  * has_serial_console() detects headless VMs from the Proxmox config
  * console_type=auto resolves to serial for headless VMs, vnc otherwise
  * an explicit console_type is always honoured
  * an invalid console_type is rejected
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import portal.integrations_v2 as iv2


# ---------------------------------------------------------------- has_serial_console

@pytest.mark.asyncio
async def test_has_serial_console_true_for_vga_serial0():
    """Our provisioning template sets vga=serial0 -> headless."""
    px = iv2.ProxmoxClient({"host": "https://px.local", "token": "t"})
    px.vm_config = AsyncMock(return_value={"vga": "serial0", "serial0": "socket"})
    assert await px.has_serial_console("node1", 111) is True


@pytest.mark.asyncio
async def test_has_serial_console_true_for_serial_dev_without_vga():
    """serial0 present and no vga key at all -> still headless."""
    px = iv2.ProxmoxClient({"host": "https://px.local", "token": "t"})
    px.vm_config = AsyncMock(return_value={"serial0": "socket", "cores": 2})
    assert await px.has_serial_console("node1", 111) is True


@pytest.mark.asyncio
async def test_has_serial_console_false_for_graphical_vm():
    """A VM with a real framebuffer must keep using VNC."""
    px = iv2.ProxmoxClient({"host": "https://px.local", "token": "t"})
    px.vm_config = AsyncMock(return_value={"vga": "std", "cores": 2})
    assert await px.has_serial_console("node1", 111) is False


@pytest.mark.asyncio
async def test_has_serial_console_false_when_config_unreadable():
    """Fail safe: if the config call blows up, do not force serial."""
    px = iv2.ProxmoxClient({"host": "https://px.local", "token": "t"})
    px.vm_config = AsyncMock(side_effect=RuntimeError("boom"))
    assert await px.has_serial_console("node1", 111) is False


# ---------------------------------------------------------------- serial_ticket

@pytest.mark.asyncio
async def test_serial_ticket_uses_termproxy_console_serial():
    """Serial consoles come from termproxy, never from vncproxy."""
    px = iv2.ProxmoxClient({"host": "https://px.local", "token": "t"})
    px._post = AsyncMock(return_value={"ticket": "TICKET", "port": "5900", "cert": "CERT", "user": "root@pam!IDI"})

    out = await px.serial_ticket("node1", 111)

    px._post.assert_awaited_once()
    path, params = px._post.await_args.args
    assert path == "/nodes/node1/qemu/111/termproxy"
    assert params == {"serial": "serial0"}
    assert out == {"ticket": "TICKET", "port": "5900", "cert": "CERT", "user": "root@pam!IDI"}


@pytest.mark.asyncio
async def test_serial_ticket_includes_user_for_handshake():
    """pve-xtermjs termproxy WS requires a '<user>:<ticket>\\n' handshake before
    the serial stream emits anything. The relay needs the PVE user name;
    without it the WS connects but delivers 0 bytes (lap-2 bug, proven live).
    """
    px = iv2.ProxmoxClient({"host": "https://px.local", "token": "t"})
    px._post = AsyncMock(return_value={"ticket": "T", "port": "5901", "user": "root@pam!IDI"})

    out = await px.serial_ticket("node1", 114)

    assert out.get("user") == "root@pam!IDI"


@pytest.mark.asyncio
async def test_serial_ticket_payload_matches_pve_schema():
    """Proxmox qemu termproxy schema has NO 'console' property (PVE::API2::Qemu
    registers only node, vmid, serial) — 'console' triggers HTTP 400
    'property is not defined in schema'. Proven live against Proxmox 8.x:
    console=serial -> 400, empty -> 200 (display), serial=serial0 -> 200 (serial)."""
    px = iv2.ProxmoxClient({"host": "https://px.local", "token": "t"})
    px._post = AsyncMock(return_value={"ticket": "T", "port": "5901"})

    await px.serial_ticket("node1", 111)

    _, params = px._post.await_args.args
    assert "console" not in params
    assert params["serial"] == "serial0"


# ---------------------------------------------------------------- endpoint routing

def _svc():
    return {
        "_id": "SID",
        "user_id": "UID",
        "category": "vps",
        "status": "active",
        "config": {"node": "node1", "vmid": 111},
    }


def _db_for(svc):
    db = MagicMock()
    db.services.find_one = AsyncMock(return_value=svc)
    db.services.update_one = AsyncMock(return_value=None)
    return db


@pytest.mark.asyncio
async def test_auto_resolves_to_serial_for_headless_vm():
    from portal.routes import client as client_mod

    px = MagicMock()
    px.has_serial_console = AsyncMock(return_value=True)
    px.serial_ticket = AsyncMock(return_value={"ticket": "T", "port": "5900"})
    px.vnc_ticket = AsyncMock(return_value={"ticket": "NO", "port": "0"})

    with patch.object(client_mod, "_get_db", AsyncMock(return_value=_db_for(_svc()))), \
         patch.object(client_mod, "_proxmox_settings_for_service", AsyncMock(return_value={"host": "h"})), \
         patch.object(client_mod, "_oid", lambda x: x), \
         patch.object(client_mod, "ObjectId", lambda x: x), \
         patch.object(client_mod.iv2, "ProxmoxClient", return_value=px):
        out = await client_mod.client_vm_console_info("SID", console_type="auto", user={"id": "UID", "email": "e@x"})

    assert out["console_type"] == "serial"
    px.serial_ticket.assert_awaited_once()
    px.vnc_ticket.assert_not_awaited()


@pytest.mark.asyncio
async def test_auto_resolves_to_vnc_for_graphical_vm():
    from portal.routes import client as client_mod

    px = MagicMock()
    px.has_serial_console = AsyncMock(return_value=False)
    px.serial_ticket = AsyncMock(return_value={"ticket": "NO", "port": "0"})
    px.vnc_ticket = AsyncMock(return_value={"ticket": "T", "port": "5900"})

    with patch.object(client_mod, "_get_db", AsyncMock(return_value=_db_for(_svc()))), \
         patch.object(client_mod, "_proxmox_settings_for_service", AsyncMock(return_value={"host": "h"})), \
         patch.object(client_mod, "_oid", lambda x: x), \
         patch.object(client_mod, "ObjectId", lambda x: x), \
         patch.object(client_mod.iv2, "ProxmoxClient", return_value=px):
        out = await client_mod.client_vm_console_info("SID", console_type="auto", user={"id": "UID", "email": "e@x"})

    assert out["console_type"] == "vnc"
    px.vnc_ticket.assert_awaited_once()
    px.serial_ticket.assert_not_awaited()


@pytest.mark.asyncio
async def test_explicit_serial_skips_detection():
    """An operator forcing serial must not depend on config detection."""
    from portal.routes import client as client_mod

    px = MagicMock()
    px.has_serial_console = AsyncMock(return_value=False)  # would say vnc
    px.serial_ticket = AsyncMock(return_value={"ticket": "T", "port": "5900"})
    px.vnc_ticket = AsyncMock(return_value={"ticket": "NO", "port": "0"})

    with patch.object(client_mod, "_get_db", AsyncMock(return_value=_db_for(_svc()))), \
         patch.object(client_mod, "_proxmox_settings_for_service", AsyncMock(return_value={"host": "h"})), \
         patch.object(client_mod, "_oid", lambda x: x), \
         patch.object(client_mod, "ObjectId", lambda x: x), \
         patch.object(client_mod.iv2, "ProxmoxClient", return_value=px):
        out = await client_mod.client_vm_console_info("SID", console_type="serial", user={"id": "UID", "email": "e@x"})

    assert out["console_type"] == "serial"
    px.has_serial_console.assert_not_awaited()
    px.serial_ticket.assert_awaited_once()


@pytest.mark.asyncio
async def test_console_info_exposes_pve_user_only_for_serial():
    """The WS relay needs the PVE user name for the termproxy handshake, but
    only in serial mode; VNC mode must not leak it."""
    from portal.routes import client as client_mod

    px = MagicMock()
    px.has_serial_console = AsyncMock(return_value=True)
    px.serial_ticket = AsyncMock(return_value={"ticket": "T", "port": "5901", "user": "root@pam!IDI"})
    px.vnc_ticket = AsyncMock(return_value={"ticket": "V", "port": "5900", "user": "root@pam!IDI"})

    with patch.object(client_mod, "_get_db", AsyncMock(return_value=_db_for(_svc()))), \
         patch.object(client_mod, "_proxmox_settings_for_service", AsyncMock(return_value={"host": "h"})), \
         patch.object(client_mod, "_oid", lambda x: x), \
         patch.object(client_mod, "ObjectId", lambda x: x), \
         patch.object(client_mod.iv2, "ProxmoxClient", return_value=px):
        serial_out = await client_mod.client_vm_console_info("SID", console_type="serial", user={"id": "UID", "email": "e@x"})
        vnc_out = await client_mod.client_vm_console_info("SID", console_type="vnc", user={"id": "UID", "email": "e@x"})

    assert serial_out["pve_user"] == "root@pam!IDI"
    assert vnc_out["pve_user"] is None


@pytest.mark.asyncio
async def test_invalid_console_type_rejected():
    from fastapi import HTTPException
    from portal.routes import client as client_mod

    with patch.object(client_mod, "_get_db", AsyncMock(return_value=_db_for(_svc()))), \
         patch.object(client_mod, "_proxmox_settings_for_service", AsyncMock(return_value={"host": "h"})), \
         patch.object(client_mod, "_oid", lambda x: x), \
         patch.object(client_mod, "ObjectId", lambda x: x):
        with pytest.raises(HTTPException) as ei:
            await client_mod.client_vm_console_info("SID", console_type="telnet", user={"id": "UID", "email": "e@x"})

    assert ei.value.status_code == 400
