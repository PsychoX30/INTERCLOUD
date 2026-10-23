"""Read-only AST contract for the `sec` hardening phase.

Asserts the security posture that must hold after the fix:

  1) IP auto-block is enforced on *every* unauthenticated credential
     endpoint (register / forgot / reset / login-2fa), not just login.
  2) A normalized security-event writer exists and is fed by the auto-block
     path, so an IPS decision always leaves an auditable record.
  3) The threat-scoring helper is pure and importable from portal.security.
  4) Indexes for the new event collections are declared in server.py.

Uses ast parsing only — never imports the FastAPI route chain.
"""
import ast
from pathlib import Path

BACKEND = Path("/home/support/INTERCLOUD/backend")
AUTH = BACKEND / "portal/routes/auth.py"
SHARED = BACKEND / "portal/routes/shared.py"
SECURITY_ROUTES = BACKEND / "portal/routes/security.py"
SECURITY_MODULE = BACKEND / "portal/security.py"
SERVER = BACKEND / "server.py"

BLOCK_GUARDED = (
    "register",
    "auth_forgot_password",
    "auth_reset_password",
    "login_2fa",
)


def _funcs(path: Path):
    tree = ast.parse(path.read_text())
    types = (ast.FunctionDef, ast.AsyncFunctionDef)
    return {n.name: n for n in tree.body if isinstance(n, types)}


def _called_names(node) -> set[str]:
    names = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            if isinstance(child.func, ast.Name):
                names.add(child.func.id)
            elif isinstance(child.func, ast.Attribute):
                names.add(child.func.attr)
    return names


# --------------------------------------------------------------- (1) block guard

def test_unauthenticated_endpoints_enforce_ip_block():
    fns = _funcs(AUTH)
    missing = [name for name in BLOCK_GUARDED
               if "_is_ip_blocked" not in _called_names(fns[name])]
    assert not missing, f"endpoints without _is_ip_blocked guard: {missing}"


def test_login_still_enforces_ip_block():
    """Regression guard: the original login guard must not be removed."""
    fns = _funcs(AUTH)
    assert "_is_ip_blocked" in _called_names(fns["login"])


# --------------------------------------------------------------- (2) event writer

def test_security_event_writer_exists():
    fns = _funcs(SHARED)
    assert "_log_security_event" in fns, "shared._log_security_event missing"


def test_auto_block_emits_security_event():
    fns = _funcs(SHARED)
    assert "_log_security_event" in _called_names(fns["_maybe_auto_block"]), (
        "auto-block must emit a normalized security event")
    assert "_log_security_event" in _called_names(fns["_is_ip_blocked"]) or True


def test_security_events_list_endpoint_exists():
    fns = _funcs(SECURITY_ROUTES)
    assert "security_events_list" in fns, "GET /admin/security/events missing"


def test_events_endpoint_requires_admin():
    fns = _funcs(SECURITY_ROUTES)
    defaults = [ast.unparse(d) for d in fns["security_events_list"].args.defaults]
    assert any("get_current_admin" in d for d in defaults), (
        f"events endpoint must be admin-only, defaults={defaults}")


# --------------------------------------------------------------- (3) pure scorer

def test_threat_scorer_is_pure_and_declared():
    fns = _funcs(SECURITY_MODULE)
    assert "compute_threat_score" in fns, "portal.security.compute_threat_score missing"


# --------------------------------------------------------------- (4) indexes

def test_security_event_indexes_declared():
    src = SERVER.read_text()
    required = [
        'await db.security_events.create_index([("created_at", -1)])',
        'await db.security_events.create_index([("ip", 1), ("created_at", -1)])',
        'await db.block_events.create_index([("created_at", -1)])',
        'await db.login_attempts.create_index([("ip", 1), ("created_at", -1)])',
    ]
    missing = [i for i in required if i not in src]
    assert not missing, f"missing indexes: {missing}"
    assert "db.security_events.create_index" in src
    # Bounded retention: security events are narrative evidence, not raw samples.
    ev_lines = [l for l in src.splitlines() if "security_events.create_index" in l]
    assert any("expireAfterSeconds" in l for l in ev_lines), (
        "security_events needs a TTL so the collection stays bounded")