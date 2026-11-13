"""Outbound enforcement: turn a detector verdict into a verified router block.

Design rules this module enforces, in order of importance
--------------------------------------------------------
1. **Never claim a block that was not verified.**  ``apply_block`` re-reads the
   address-list entry from the router that was supposed to write it.  A failed
   connection, a timeout or a rejected command returns ``ok=False`` — it is
   never reported as success, because the operator's next action (notifying the
   customer) depends on that boolean being true.

2. **The router drops the block by itself.**  Every entry is written with a
   ``timeout``, so a portal crash cannot leave a paying customer disconnected
   forever.  The portal removes the entry early on a manual lift; if the portal
   is gone, RouterOS still releases it.

3. **One login per enforcement cycle.**  ``MikrotikClient.session()`` keeps a
   single API connection open for the whole add-verify sequence.  The previous
   per-call connect/close pattern opened three sessions for one block, which is
   how the router hit ``too many concurrent logins (6)``.

4. **Role-based device selection, never "whatever device is first".**  The old
   fallback (``next(iter(devices), None)``) could execute a block on an
   unrelated router.  Devices now declare ``collection_role`` and ``sites``;
   the enforcer is chosen by longest-prefix coverage of the target IP, then by
   priority, then by host for determinism.

5. **Only /32 and /128.**  An address-list entry for a wider prefix would block
   a whole customer block because one host inside it misbehaved.
"""
from __future__ import annotations

import ipaddress
import logging
from dataclasses import dataclass
from typing import Optional

log = logging.getLogger("portal.outbound_guard")

# Single source-list name for every automated block.  One list means one
# firewall rule, and one rule means the forward path stays fast.
SRCBLOCK_LIST = "portal-srcblock"
# The rule that consumes it.  Matched by these three properties so an operator
# who edits the comment does not break detection of an existing rule.
RULE_CHAIN = "forward"
RULE_COMMENT = "portal-outbound-srcblock"

ENFORCER_ROLES = ("enforcer", "both")


@dataclass
class EnforcerChoice:
    """One candidate device plus the reason it was chosen."""

    device: dict
    matched_prefix: Optional[str]
    specificity: int          # prefix length of the matched block, 0 if none
    reason: str
    scoped: bool = False      # matched via an explicit site assignment


def _prefix_len(text: str) -> int:
    try:
        return ipaddress.ip_network(str(text), strict=False).prefixlen
    except ValueError:
        return -1


def device_sites(device: dict) -> list[str]:
    """Sites a device serves, tolerant of the legacy single ``site`` string."""
    sites = device.get("sites")
    if isinstance(sites, list):
        cleaned = [str(s).strip() for s in sites if str(s or "").strip()]
        if cleaned:
            return cleaned
    legacy = str(device.get("site") or "").strip()
    return [legacy] if legacy else []


def coverage_prefixes(device: dict, prefixes: list[dict]) -> list[str]:
    """Prefixes this device is responsible for, derived from DCIM.

    A device with no sites configured covers everything: that is the border
    router case, and treating "unset" as "nothing" would silently disable
    enforcement on a fresh deployment.
    """
    sites = device_sites(device)
    if not sites:
        return [str(p.get("prefix") or "") for p in prefixes if p.get("prefix")]
    wanted = {s.lower() for s in sites}
    return [str(p.get("prefix")) for p in prefixes
            if p.get("prefix") and str(p.get("site") or "").strip().lower() in wanted]


def resolve_enforcers(target_ip: str, devices: list[dict],
                      prefixes: list[dict]) -> list[EnforcerChoice]:
    """Order the devices that may enforce a block for ``target_ip``.

    Ordering is deterministic and explainable:
      1. device actually covers the IP (longest matching prefix wins)
      2. higher ``priority`` wins a tie
      3. host name as the final tie-break so two equal devices never swap
         between sweeps (which would produce duplicate rules)

    Devices that do not cover the IP are still returned, after the covering
    ones: a border router with no site assignment is a valid fallback and the
    caller decides whether to try it.
    """
    try:
        address = ipaddress.ip_address(str(target_ip).split("/")[0])
    except ValueError:
        return []

    covering: list[EnforcerChoice] = []
    fallback: list[EnforcerChoice] = []
    for device in devices:
        if not device:
            continue
        role = str(device.get("collection_role") or "none").lower()
        if role not in ENFORCER_ROLES:
            continue
        if device.get("block_enabled") is False:
            continue
        nets = coverage_prefixes(device, prefixes)
        scoped = bool(device_sites(device))
        best = None
        best_len = -1
        for raw in nets:
            try:
                net = ipaddress.ip_network(raw, strict=False)
            except ValueError:
                continue
            if net.version != address.version or address not in net:
                continue
            if net.prefixlen > best_len:
                best, best_len = raw, net.prefixlen
        if best is not None:
            covering.append(EnforcerChoice(
                device=device, matched_prefix=best, specificity=best_len,
                scoped=scoped,
                reason=f"covers {target_ip} via {best}"))
        elif not nets:
            fallback.append(EnforcerChoice(
                device=device, matched_prefix=None, specificity=0,
                reason="no site restriction — whole-network fallback"))
        else:
            fallback.append(EnforcerChoice(
                device=device, matched_prefix=None, specificity=0,
                reason="does not cover this IP (kept as last resort)"))

    def _sort(choice: EnforcerChoice):
        # A device with explicit site coverage always outranks a catch-all that
        # happens to cover the same block. Without this, the border router (no
        # sites = covers everything) ties with the local distribution router at
        # /24 and wins on hostname order — the block lands on the far side of
        # the network and the customer's uplink keeps flooding.
        return (not choice.scoped,
                -choice.specificity,
                -int(choice.device.get("priority") or 0),
                str(choice.device.get("host") or ""),
                str(choice.device.get("name") or ""))

    covering.sort(key=_sort)
    fallback.sort(key=_sort)
    return covering + fallback


def validate_target(target_ip: str) -> tuple[Optional[str], Optional[str]]:
    """Return ``(normalised, error)``.

    Only single hosts are acceptable: an automated rule must never widen to a
    prefix, because that disconnects an entire customer block.
    """
    try:
        address = ipaddress.ip_address(str(target_ip).split("/")[0])
    except ValueError:
        return None, f"not an IP address: {target_ip!r}"
    if "/" in str(target_ip):
        try:
            net = ipaddress.ip_network(str(target_ip), strict=False)
        except ValueError:
            return None, f"unparsable network: {target_ip!r}"
        if net.num_addresses != 1:
            return None, "refusing to block a prefix automatically; /32 and /128 only"
    return str(address), None


# ---------------------------------------------------------------------------
# Router operations
# ---------------------------------------------------------------------------
def _is_drop_rule(row: dict) -> bool:
    return (str(row.get("chain") or "") == RULE_CHAIN
            and str(row.get("src-address-list") or "") == SRCBLOCK_LIST
            and str(row.get("action") or "") == "drop")


def _forward_position(rows: list[dict], rule_id: str) -> int:
    """Index of ``rule_id`` among ``forward`` rules only, ``-1`` when absent.

    Position is counted inside the chain, not inside the whole filter table: an
    ``input`` rule above it is irrelevant to forwarded traffic.
    """
    position = -1
    for row in rows:
        if str(row.get("chain") or "") != RULE_CHAIN:
            continue
        position += 1
        if str(row.get(".id") or "") == rule_id:
            return position
    return -1


def _move_before(api, rule_id: str, anchor_id: str) -> bool:
    """Move ``rule_id`` above ``anchor_id``.  Best effort, never raises."""
    try:
        tuple(api.path("ip", "firewall", "filter")(
            "move", **{".id": rule_id, "destination": anchor_id}))
        return True
    except Exception as e:  # noqa: BLE001
        log.warning("[outbound] move %s before %s failed: %s", rule_id, anchor_id, e)
        return False


def ensure_drop_rule(api) -> dict:
    """Make sure exactly one ``forward`` drop rule consumes SRCBLOCK_LIST.

    Idempotent: an existing rule is reused, never duplicated.

    The rule has to be the *first* rule of the ``forward`` chain.  A drop that
    sits after ``accept established,related`` or after a fasttrack rule never
    sees the packets it is meant to drop, so the block would be reported as
    applied while the customer's flood keeps leaving the network.  This router
    currently has an empty forward chain, but the same code runs on every
    device added later, so the position is enforced and then verified:

    * new rule -> added with ``place-before`` the current first forward rule,
    * existing rule that drifted down -> moved back up,
    * still not first -> ``ok=False`` (a rule that cannot fire is not a block).
    """
    rows = list(api.path("ip", "firewall", "filter"))
    existing = next((r for r in rows if _is_drop_rule(r)), None)
    created = False
    moved = False

    if existing is None:
        anchor = next((r for r in rows
                       if str(r.get("chain") or "") == RULE_CHAIN), None)
        params = {
            "chain": RULE_CHAIN,
            "src-address-list": SRCBLOCK_LIST,
            "action": "drop",
            "comment": RULE_COMMENT,
        }
        if anchor and anchor.get(".id"):
            params["place-before"] = anchor[".id"]
        api.path("ip", "firewall", "filter").add(**params)
        created = True
        rows = list(api.path("ip", "firewall", "filter"))
        existing = next((r for r in rows if _is_drop_rule(r)), None)
        if existing is None:
            return {"ok": False,
                    "error": "drop rule was added but is not visible in /ip/firewall/filter"}

    rule_id = str(existing.get(".id") or "")
    position = _forward_position(rows, rule_id)
    if position > 0:
        anchor = next((r for r in rows
                       if str(r.get("chain") or "") == RULE_CHAIN
                       and str(r.get(".id") or "") != rule_id), None)
        if anchor is not None:
            moved = _move_before(api, rule_id, str(anchor.get(".id")))
            rows = list(api.path("ip", "firewall", "filter"))
            position = _forward_position(rows, rule_id)

    if position != 0:
        return {"ok": False, "id": rule_id, "created": created, "moved": moved,
                "position": position,
                "error": "drop rule is not the first forward-chain rule; an "
                         "earlier accept/fasttrack would shadow it"}
    return {"ok": True, "created": created, "moved": moved, "id": rule_id,
            "position": 0}


def list_blocks(api) -> list[dict]:
    rows = list(api.path("ip", "firewall", "address-list"))
    return [r for r in rows if str(r.get("list") or "") == SRCBLOCK_LIST]


def apply_block(client, target_ip: str, *, hours: float, incident_id: str) -> dict:
    """Write, then verify, a source block.  Returns ``{ok, ...}``.

    ``hours`` may be ``-1`` for "permanent until lifted manually"; that is
    written without a ``timeout`` property, which RouterOS interprets as
    permanent.  Every other value gets a timeout so the router self-heals.
    """
    normalised, error = validate_target(target_ip)
    if error:
        return {"ok": False, "error": error, "target": target_ip}
    if hours is not None and float(hours) < 0:
        timeout = None
    else:
        timeout = f"{max(1, int(round(float(hours or 0.5) * 60)))}m"

    comment = f"portal:auto:{incident_id}"[:120]
    try:
        with client.session() as api:
            rule = ensure_drop_rule(api)
            if not rule.get("ok"):
                return {"ok": False, "error": rule.get("error") or "drop rule missing",
                        "target": normalised, "verified": False}

            existing = [b for b in list_blocks(api)
                        if str(b.get("address") or "") == normalised]
            if existing:
                # librouteros 4 takes ids positionally: ``remove(**{".id": x})``
                # raises TypeError and the old block would survive every
                # re-block attempt.
                api.path("ip", "firewall", "address-list").remove(
                    existing[0][".id"])

            params = {"list": SRCBLOCK_LIST, "address": normalised, "comment": comment}
            if timeout is not None:
                params["timeout"] = timeout
            api.path("ip", "firewall", "address-list").add(**params)

            verified = [b for b in list_blocks(api)
                        if str(b.get("address") or "") == normalised]
            if not verified:
                return {"ok": False, "target": normalised, "verified": False,
                        "error": "entry written but not present on re-read"}
            entry = verified[0]
            return {
                "ok": True, "target": normalised, "verified": True,
                "entry_id": entry.get(".id"),
                "timeout": entry.get("timeout") or "",
                "rule_id": rule.get("id"),
                "rule_created": bool(rule.get("created")),
                "rule_position": rule.get("position"),
                "comment": comment,
            }
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "target": normalised, "verified": False,
                "error": f"{type(e).__name__}: {e}"}


def remove_block(client, target_ip: str) -> dict:
    """Remove every entry for ``target_ip`` and verify the removal."""
    normalised, error = validate_target(target_ip)
    if error:
        return {"ok": False, "error": error}
    try:
        with client.session() as api:
            entries = [b for b in list_blocks(api)
                       if str(b.get("address") or "") == normalised]
            for entry in entries:
                api.path("ip", "firewall", "address-list").remove(entry[".id"])
            left = [b for b in list_blocks(api)
                    if str(b.get("address") or "") == normalised]
            return {"ok": not left, "removed": len(entries) - len(left),
                    "remaining": len(left), "target": normalised}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "target": normalised,
                "error": f"{type(e).__name__}: {e}"}


def enforce_target(target_ip: str, devices: list[dict], prefixes: list[dict],
                   *, hours: float, incident_id: str,
                   make_client) -> dict:
    """Try each resolved enforcer until one block is verified.

    ``make_client`` is injected so this function stays testable without a
    router and without importing ``integrations_v2``.

    A device that fails is recorded and the next one is tried; the caller gets
    the full attempt log so a blocked customer can always be traced to the
    router that is actually holding the block.
    """
    choices = resolve_enforcers(target_ip, devices, prefixes)
    if not choices:
        return {"ok": False, "target": target_ip,
                "error": "no device is configured as an enforcer",
                "attempts": []}
    attempts = []
    for choice in choices:
        device = choice.device
        name = device.get("name") or device.get("host") or "unnamed"
        try:
            client = make_client(device)
            result = apply_block(client, target_ip, hours=hours,
                                 incident_id=incident_id)
        except Exception as e:  # noqa: BLE001
            result = {"ok": False, "error": f"{type(e).__name__}: {e}"}
        attempts.append({
            "device": name,
            "device_id": str(device.get("_id") or ""),
            "host": device.get("host") or "",
            "matched_prefix": choice.matched_prefix,
            "reason": choice.reason,
            "ok": bool(result.get("ok")),
            "verified": bool(result.get("verified")),
            "error": result.get("error") or "",
            "timeout": result.get("timeout") or "",
        })
        if result.get("ok"):
            return {"ok": True, "target": result.get("target", target_ip),
                    "device": name, "device_id": str(device.get("_id") or ""),
                    "matched_prefix": choice.matched_prefix,
                    "timeout": result.get("timeout") or "",
                    "attempts": attempts}
        log.warning("[outbound] block failed on %s: %s", name, result.get("error"))
    return {"ok": False, "target": target_ip,
            "error": "every candidate device refused or failed",
            "attempts": attempts}
