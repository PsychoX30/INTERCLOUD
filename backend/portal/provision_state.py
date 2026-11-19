"""Single source of truth for `config.provision_status`.

Why this module exists
----------------------
`provision_status` grew to six values written from eleven separate places
spread across `provision.py`, `orders.py` and `emails.py`. Nothing enforced
which transition was legal, so a service could be terminated at the operational
level while its provisioning state still said `pending`. Two production rows
sat in exactly that contradiction.

Scope of the guard
------------------
This module validates *shape*, not truth: it cannot know whether a VM really
exists. What it does guarantee is that the lifecycle field and the provisioning
field never claim contradictory things — a terminated service cannot keep
pretending provisioning is still outstanding.

There is deliberately no `terminated -> active` re-open transition. Bringing a
terminated service back is a new order, not a state edit.
"""
from __future__ import annotations

from typing import Optional

# canonical values
PENDING = "pending"
PROVISIONING = "provisioning"
PROVISIONED = "provisioned"
FAILED = "failed"
SUSPENDED = "suspended"
TERMINATION_PENDING = "termination_pending"
TERMINATED = "terminated"

ALL = (PENDING, PROVISIONING, PROVISIONED, FAILED,
       SUSPENDED, TERMINATION_PENDING, TERMINATED)

# Absent/None is a real state: services created before provisioning existed,
# and categories filled manually (interconnect, colocation, dedicated).
UNSET = None

# Legal transitions. A self-transition is always allowed (idempotent re-runs).
_ALLOWED: dict[Optional[str], set[Optional[str]]] = {
    UNSET:           {PENDING, PROVISIONING, PROVISIONED, FAILED, TERMINATED},
    PENDING:         {PROVISIONING, PROVISIONED, FAILED, SUSPENDED, TERMINATED},
    PROVISIONING:    {PROVISIONED, FAILED, PENDING, TERMINATED},
    PROVISIONED:     {SUSPENDED, TERMINATION_PENDING, TERMINATED, PROVISIONING},
    FAILED:          {PENDING, PROVISIONING, PROVISIONED, TERMINATED},
    SUSPENDED:       {PROVISIONED, TERMINATED},
    TERMINATION_PENDING: {TERMINATED, SUSPENDED, PROVISIONED},
    TERMINATED:      set(),   # terminal: re-opening requires a new order
}

# service.status -> provisioning states that may accompany it.
_COMPATIBLE_STATUS = {
    "pending":    {UNSET, PENDING, PROVISIONING, FAILED},
    "active":     {UNSET, PROVISIONED, FAILED, PROVISIONING, PENDING},
    "suspended":  {UNSET, PROVISIONED, SUSPENDED, PENDING, FAILED},
    "termination_pending": {UNSET, PROVISIONED, SUSPENDED, TERMINATION_PENDING, PENDING},
    "terminated": {UNSET, PROVISIONED, SUSPENDED, TERMINATED},
}


class IllegalTransition(ValueError):
    """Raised when a provisioning state change would break the lifecycle."""


def normalize(value) -> Optional[str]:
    """Coerce a stored value to a canonical state, or None when unset."""
    if value is None or value == "":
        return UNSET
    v = str(value).strip().lower()
    return v if v in ALL else None


def can_transition(current, new) -> bool:
    cur = normalize(current)
    nxt = normalize(new)
    if cur == nxt:
        return True
    return nxt in _ALLOWED.get(cur, set())


def assert_transition(current, new, *, service_name: str = "") -> str:
    """Validate and return the canonical new state. Raises IllegalTransition."""
    cur = normalize(current)
    nxt = normalize(new)
    if not can_transition(cur, nxt):
        where = f" for '{service_name}'" if service_name else ""
        raise IllegalTransition(
            f"illegal provision_status transition{where}: "
            f"{cur or '(unset)'} -> {nxt or '(unset)'}")
    return nxt


def compatible_with_service_status(provision_status, service_status) -> bool:
    """True when the provisioning field does not contradict the lifecycle field."""
    ps = normalize(provision_status)
    st = str(service_status or "").strip().lower()
    allowed = _COMPATIBLE_STATUS.get(st)
    if allowed is None:
        return True          # unknown lifecycle value: do not invent a constraint
    return ps in allowed


def is_contradiction(provision_status, service_status) -> bool:
    return not compatible_with_service_status(provision_status, service_status)


def allowed_for_service_status(service_status) -> set:
    """Provisioning states that may legally accompany a lifecycle status."""
    return set(_COMPATIBLE_STATUS.get(str(service_status or "").strip().lower(),
                                      {UNSET}))


def status_to_apply(provision_status, *, current_service_status=None) -> Optional[str]:
    """Which lifecycle status a provisioning state implies, if any.

    Used to keep the two fields in step at the moment of provisioning instead of
    letting each caller invent its own pairing.
    """
    ps = normalize(provision_status)
    if ps == PROVISIONED:
        return "active"
    if ps == SUSPENDED:
        return "suspended"
    if ps in (TERMINATED, TERMINATION_PENDING):
        return "terminated" if ps == TERMINATED else "termination_pending"
    if ps in (PENDING, PROVISIONING, FAILED):
        # Do NOT demote a live service just because a re-provision is pending.
        if str(current_service_status or "").lower() in ("active", "suspended"):
            return None
        if str(current_service_status or "").lower() == "terminated":
            # A terminated service must never be dragged back to pending.
            return "terminated"
        return "pending"
    return None


def repair_target(provision_status, service_status) -> Optional[str]:
    """Suggested provisioning state for a contradictory row, or None if fine.

    Deliberately conservative: a terminated service whose provisioning state is
    still non-final is closed out as `terminated`. Nothing is invented about
    provisioning that never happened — if the service was terminated without
    ever being provisioned, `terminated` is the honest answer for the field.
    """
    if not is_contradiction(provision_status, service_status):
        return None
    st = str(service_status or "").strip().lower()
    if st == "terminated":
        return TERMINATED
    return None


def coerce_legal(current, requested, service_status) -> Optional[str]:
    """Best legal value to store when `current -> requested` is not allowed.

    The requested value cannot stand, but silently keeping `current` is not
    always right either: requesting `pending` on a terminated row is exactly the
    bug that produced the production contradictions. So the candidate is
    required to be compatible with the lifecycle status already on disk.

    Order of preference:
      1. the value that reconciles a contradiction (repair_target)
      2. `current`, if the lifecycle field tolerates it
      3. `requested`, if the lifecycle field tolerates it
      4. the first state the lifecycle field demands (terminated -> terminated)
      5. `current`, unchanged, as the last resort
    """
    fix = repair_target(current, service_status)
    if fix is not None:
        return fix

    st = str(service_status or "").strip().lower()
    allowed = allowed_for_service_status(st)

    cur = normalize(current)
    if cur in allowed:
        return cur

    req = normalize(requested)
    if req in allowed:
        return req

    # The lifecycle status is authoritative. A terminated row ends up
    # terminated; an active row falls back to provisioned.
    preferred = {"terminated": TERMINATED,
                 "active": PROVISIONED,
                 "suspended": SUSPENDED,
                 "termination_pending": TERMINATION_PENDING,
                 "pending": PENDING}.get(st)
    if preferred in allowed:
        return preferred
    return cur
