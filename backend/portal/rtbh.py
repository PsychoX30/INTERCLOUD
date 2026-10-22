"""BGP RTBH (Remote Triggered Black Hole) execution — destination-based only.

Why this module exists
----------------------
``ddos_guard.select_mitigation_strategy()`` could return ``"bgp_rtbh"`` but no
code path ever executed it: the sweep only handled ``local_blackhole``.  The
incident was then written with ``mitigation_type="bgp_rtbh"`` while nothing was
announced upstream, so operators believed traffic was being dropped at the
provider edge when in reality the circuit kept saturating.  That is a silent
failure of the worst kind, so RTBH now has a real executor.

Why OUTBOUND is refused (important)
-----------------------------------
An earlier revision of this module claimed that announcing an internal
*attacker* as a /32 would stop its outbound attack.  That claim is wrong and
was removed:

* Forwarding selects a route by **destination**.  A packet from an internal
  host attacking the internet has ``dst`` = the external victim, so neither a
  ``dst-address=<attacker>/32 blackhole=yes`` route nor an upstream
  announcement of the attacker prefix ever matches it.  The attack continues
  at full rate.
* The side effect is worse than nothing: the attacker's /32 becomes a blackhole
  for traffic **destined to** that host, so the customer disappears from
  monitoring and remote access while still attacking.
* Dropping traffic by *source* requires Source RTBH, i.e. destination-based
  RTBH combined with **uRPF at the provider edge** (RFC 5635 section 4).  That
  is a capability of the upstream, not something we can trigger from here, and
  RFC 5635 requires a *separate* community plus NO_EXPORT for it.  None of that
  is modeled or verified in this codebase, so ``plan_rtbh()`` refuses
  ``direction="outbound"`` with an explicit reason instead of pretending.

So this module implements destination RTBH only: the target is an internal
*victim* we are willing to sacrifice to protect the rest of the network.  That
is reachable through an explicit rule action, never implicitly.

Safety model
------------
1. Whitelist is enforced here *again* (defence in depth) even though the sweep
   also checks it.  A future refactor must not be able to bypass the shared
   gateway protection.
2. ``plan_rtbh()`` is pure: no router, no DB.  It can be unit tested and it can
   refuse before any device is touched.
3. Execution is split into two independently reported steps:
   - local blackhole route  — always attempted, reduces router CPU;
   - upstream announcement  — the actual RTBH part, via a routing filter rule
     that stamps the BGP community so the upstream drops the prefix.
   A failure in step 2 never hides step 1, and the result carries a per-step
   status so the incident record cannot claim more than what happened.  When
   step 2 fails, step 1 is **rolled back** so no unrecoverable local blackhole
   is left behind.
4. Every step returns the exact RouterOS command that was issued.  That string
   is persisted to ``blackhole_log`` so an operator can audit and reproduce.
"""
from __future__ import annotations

import ipaddress
from dataclasses import dataclass, field
from typing import Optional

# Community used by most upstreams for destination RTBH.  A configured value
# always wins; this is only the fallback that makes ``plan_rtbh`` usable in
# tests.  This is NOT valid for source RTBH (RFC 5635 requires a separate one).
DEFAULT_RTBH_COMMUNITY = "65535:666"

# Prefix length we are willing to announce.  A /32 (or /128) is the only sane
# RTBH target: anything wider can blackhole a customer block.
RTBH_PREFIXLEN_V4 = 32
RTBH_PREFIXLEN_V6 = 128

# Markers so a route/filter created by us can be found again even if the
# database record is lost.  Never match on these alone for removal — always
# require the portal-generated id as well.
ROUTE_COMMENT_PREFIX = "portal-rtbh"
FILTER_COMMENT_PREFIX = "portal-rtbh-filter"

# Directions this module is allowed to act on.
SUPPORTED_DIRECTIONS = ("inbound",)


@dataclass
class RTBHPlan:
    """A fully validated, ready-to-execute RTBH action."""

    target: str                  # host IP (no mask)
    prefix: str                  # strict CIDR, /32 or /128
    direction: str               # inbound | outbound
    community: str               # e.g. "65535:666"
    upstream_name: str           # operator label, for audit only
    token: str                   # short id embedded in route/filter comments
    allowed: bool
    reason: str = ""
    scope_prefixes: list[str] = field(default_factory=list)

    @property
    def route_comment(self) -> str:
        return f"{ROUTE_COMMENT_PREFIX} {self.token} {self.direction}"

    @property
    def filter_comment(self) -> str:
        return f"{FILTER_COMMENT_PREFIX} {self.token}"


@dataclass
class RTBHResult:
    """Outcome of an RTBH execution attempt, per step.

    ``ok`` is True only when *both* the local route and the upstream
    announcement succeeded.  ``local_ok`` / ``announce_ok`` let callers record
    partial mitigation honestly instead of collapsing everything into one
    boolean.
    """

    ok: bool = False
    local_ok: bool = False
    announce_ok: bool = False
    rolled_back: bool = False
    prefix: str = ""
    community: str = ""
    route_id: Optional[str] = None
    filter_id: Optional[str] = None
    commands: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    dry_run: bool = False

    def as_dict(self) -> dict:
        return {
            "ok": self.ok,
            "local_ok": self.local_ok,
            "announce_ok": self.announce_ok,
            "rolled_back": self.rolled_back,
            "prefix": self.prefix,
            "community": self.community,
            "route_id": self.route_id,
            "filter_id": self.filter_id,
            "commands": self.commands,
            "errors": self.errors,
            "dry_run": self.dry_run,
        }


def _validate_community(community: str) -> bool:
    """``AS:VALUE`` with both parts in 0..65535 (RFC 1997 well-known form)."""
    try:
        left, right = str(community).split(":", 1)
        return 0 <= int(left) <= 65535 and 0 <= int(right) <= 65535
    except (ValueError, AttributeError):
        return False


def _within_scope(ip: str, scope_prefixes: list[str]) -> bool:
    """True when *ip* belongs to one of the protected scopes.

    Empty scope means "unknown target" and must not be acted on automatically.
    """
    if not scope_prefixes:
        return False
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    for raw in scope_prefixes:
        try:
            if addr in ipaddress.ip_network(raw, strict=False):
                return True
        except ValueError:
            continue
    return False


def plan_rtbh(
    *,
    target: str,
    direction: str,
    community: str,
    upstream_name: str,
    scope_prefixes: Optional[list[str]] = None,
    whitelist: Optional[list[str]] = None,
    token: str = "",
) -> RTBHPlan:
    """Build and validate an RTBH plan.  Pure: never touches a device.

    Refusal reasons are explicit so they can be surfaced to the operator and
    written to the audit log instead of being swallowed.
    """
    scope = list(scope_prefixes or [])
    target = (target or "").strip()

    def deny(reason: str) -> RTBHPlan:
        return RTBHPlan(target=target, prefix="", direction=direction,
                        community=community, upstream_name=upstream_name,
                        token=token, allowed=False, reason=reason,
                        scope_prefixes=scope)

    if direction not in SUPPORTED_DIRECTIONS:
        # Outbound is not "RTBH with a different target", it is a different
        # mechanism (source filtering at the provider edge, RFC 5635 section 4).
        # Refusing loudly is the only honest answer while that capability is
        # neither modeled nor verified.
        return deny(
            f"RTBH direction {direction!r} is not supported: blocking an internal "
            f"attacker requires provider-side uRPF/S-RTBH, not a destination "
            f"blackhole announcement")

    try:
        addr = ipaddress.ip_address(target.split("/")[0])
    except ValueError:
        return deny(f"Target is not a valid IP address: {target!r}")

    # Refuse to announce anything wider than a single host.
    prefixlen = RTBH_PREFIXLEN_V6 if addr.version == 6 else RTBH_PREFIXLEN_V4
    prefix = f"{addr}/{prefixlen}"

    if not _validate_community(community):
        return deny(f"Invalid BGP community (expected AS:VALUE): {community!r}")

    if not (upstream_name or "").strip():
        return deny("No upstream name configured for RTBH")

    if not _within_scope(str(addr), scope):
        return deny(f"Target {addr} is outside the protected scope {scope}")

    # Defence in depth: the shared/NAT gateway must never be announced.
    from .ddos_guard import is_protected
    if is_protected(prefix, whitelist):
        return deny(f"Target {prefix} is whitelisted (infrastructure protection)")

    # Outbound mitigation must not blackhole our own transit address.
    return RTBHPlan(target=str(addr), prefix=prefix, direction=direction,
                    community=community, upstream_name=upstream_name,
                    token=token, allowed=True, reason="ok", scope_prefixes=scope)


def _ros7_announce_rule(plan: RTBHPlan) -> str:
    """RouterOS 7 routing filter rule body.

    Matches the exact blackhole prefix and stamps the RTBH community on the
    outbound advertisement.  ``accept`` is intentional: the prefix must be
    advertised, not filtered out.

    The writable property is ``bgp-communities`` (RFC 1997).  There is no
    ``bgp-out-community`` property in RouterOS — the only ``bgp-out-*``
    property is ``bgp-out-med``.  The previous value made every announcement
    fail on the device.
    """
    return (f'if (dst=={plan.prefix} && protocol static) '
            f'{{ append bgp-communities {plan.community}; accept }}')


def _ros6_announce_rule(plan: RTBHPlan) -> str:
    """RouterOS 6 routing filter.

    RouterOS 6 has no ``rule=`` script parameter (that is v7 only) and no
    ``dst-address`` matcher; it uses discrete properties.  Kept for the audit
    string only — the executor sends these as real parameters.
    """
    return (f'prefix={plan.prefix} prefix-length={plan.prefix.split("/")[-1]} '
            f'protocol=static action=accept '
            f'set-bgp-communities={plan.community}')


def build_commands(plan: RTBHPlan, *, ros_major: int | None = None) -> list[str]:
    """Return the RouterOS commands for *plan*, for dry-run and for audit.

    The command list must match what ``apply_rtbh`` really does, otherwise the
    ``blackhole_log`` audit trail would describe a different action than the one
    performed — exactly the kind of drift that made the original bug invisible.

    ``ros_major=None`` (unknown version) emits the v7 filter command as an
    explicit guess for display; ``apply_rtbh`` itself refuses when unknown.
    """
    if not plan.allowed:
        return []
    route_cmd = (f'/ip/route/add dst-address={plan.prefix} blackhole=yes '
                 f'distance=1 comment="{plan.route_comment}"')
    if ros_major is None or ros_major >= 7:
        filter_cmd = (f'/routing/filter/rule/add chain=rtbh-out '
                      f'rule="{_ros7_announce_rule(plan)}" '
                      f'comment="{plan.filter_comment}"')
    else:
        filter_cmd = (f'/routing/filter/add chain=rtbh-out '
                      f'{_ros6_announce_rule(plan)} '
                      f'comment="{plan.filter_comment}"')
    return [route_cmd, filter_cmd]


def apply_rtbh(client, plan: RTBHPlan, *, dry_run: bool = True,
               ros_major: int | None = None) -> RTBHResult:
    """Execute *plan* on *client* (a ``MikrotikClient``).

    Steps are independent so partial mitigation is reported truthfully:

    1. local blackhole route — drops the traffic at this router immediately;
    2. routing filter rule  — stamps the community so the upstream drops it.

    ``dry_run=True`` (default) only builds commands.  Callers must opt in
    explicitly before anything is changed on a production router.
    """
    result = RTBHResult(prefix=plan.prefix, community=plan.community,
                        dry_run=dry_run)

    if not plan.allowed:
        result.errors.append(plan.reason or "plan not allowed")
        return result

    result.commands = build_commands(plan, ros_major=ros_major)

    if dry_run:
        # Nothing is executed; ok stays False because nothing was mitigated.
        result.errors.append("dry_run: commands built but not executed")
        return result

    # A wrong major version yields commands the router rejects, so refuse to
    # act when it cannot be determined — never guess.
    if ros_major is None:
        ros_major = getattr(client, "_ros_major", None)
        if ros_major is None and hasattr(client, "_ros_major_required"):
            ros_major = client._ros_major_required()
    if ros_major not in (6, 7):
        result.errors.append("RouterOS major version unknown; refusing to act")
        return result

    # --- step 1: local blackhole route -----------------------------------
    try:
        bh = client.blackhole_add(plan.prefix, comment=plan.route_comment)
        if bh.get("ok"):
            route = client.blackhole_find_by_prefix(plan.prefix)
            route_id = (route or {}).get("id")
            if route_id:
                result.local_ok = True
                result.route_id = route_id
            else:
                # A route we cannot identify cannot be withdrawn later. Treat it
                # as a failure so nothing claims mitigation we cannot undo.
                result.errors.append(
                    "local blackhole added but no route id could be read back; "
                    "refusing to proceed")
        else:
            result.errors.append(f"local blackhole failed: {bh.get('error')}")
    except Exception as exc:  # never let a device error escape the sweep
        result.errors.append(f"local blackhole raised: {type(exc).__name__}: {exc}")

    if not result.local_ok:
        return result

    # --- step 2: upstream announcement -----------------------------------
    try:
        add = client.rtbh_announce(
            plan.prefix, plan.community, plan.filter_comment,
            upstream_name=plan.upstream_name, ros_major=ros_major)
        if add.get("ok"):
            result.announce_ok = True
            result.filter_id = add.get("id")
        else:
            result.errors.append(f"announce failed: {add.get('error')}")
            # Keep a filter id the device did create, so recovery can remove it.
            result.filter_id = add.get("id")
    except Exception as exc:
        result.errors.append(f"announce raised: {type(exc).__name__}: {exc}")

    # --- rollback: never leave an unannounced local blackhole behind ------
    # Without an upstream announcement the route only blackholes inbound
    # traffic to the victim, which is pure collateral damage: the attack is not
    # mitigated and the customer disappears. Remove it.
    if not result.announce_ok:
        try:
            res = client.blackhole_remove(result.route_id)
            if res.get("ok"):
                result.rolled_back = True
                result.local_ok = False
                result.route_id = None
                result.errors.append("local blackhole rolled back (announce failed)")
            else:
                result.errors.append(
                    f"ROLLBACK FAILED, local blackhole may persist: {res.get('error')}")
        except Exception as exc:
            result.errors.append(
                f"ROLLBACK RAISED, local blackhole may persist: {type(exc).__name__}: {exc}")

    result.ok = result.local_ok and result.announce_ok
    return result


def withdraw_rtbh(client, *, prefix: str, route_id: Optional[str] = None,
                  filter_id: Optional[str] = None) -> RTBHResult:
    """Remove the announcement first, then the route.

    Order matters: withdrawing the community before removing the route avoids a
    window where the prefix is still advertised with the blackhole community
    but no longer intended.
    """
    result = RTBHResult(prefix=prefix)
    if filter_id:
        try:
            res = client.rtbh_withdraw(filter_id)
            if res.get("ok"):
                result.announce_ok = True
            else:
                result.errors.append(f"filter remove failed: {res.get('error')}")
        except Exception as exc:
            result.errors.append(f"filter remove raised: {type(exc).__name__}: {exc}")
    else:
        # Nothing to withdraw upstream; treat as done so recovery can proceed.
        result.announce_ok = True

    if route_id:
        try:
            res = client.blackhole_remove(route_id)
            if res.get("ok"):
                result.local_ok = True
            else:
                result.errors.append(f"route remove failed: {res.get('error')}")
        except Exception as exc:
            result.errors.append(f"route remove raised: {type(exc).__name__}: {exc}")
    else:
        result.errors.append("no route_id recorded; route left in place")

    result.ok = result.local_ok and result.announce_ok
    return result
