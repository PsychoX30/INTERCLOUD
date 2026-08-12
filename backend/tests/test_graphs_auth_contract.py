"""Auth contract tests for graph endpoints.

AST-based: verify that mutating endpoints use get_current_admin,
while read endpoints use require_roles("admin", "support").
"""
import ast
from pathlib import Path

GRAPHS_FILE = Path("/home/support/INTERCLOUD/backend/portal/routes/graphs.py")
ADMIN = "get_current_admin"
REQUIRE_ROLES = "require_roles"


def _load_functions():
    tree = ast.parse(GRAPHS_FILE.read_text())
    function_types = (ast.FunctionDef, ast.AsyncFunctionDef)
    return {node.name: node for node in tree.body if isinstance(node, function_types)}


def _defaults(func):
    """Yield all default values, skipping None (from Optional params)."""
    for d in func.args.defaults:
        if d is not None:
            yield d


def _extract_depends_calls(defaults):
    """Extract Depends(...) calls from default values."""
    for d in defaults:
        if (isinstance(d, ast.Call)
                and isinstance(d.func, ast.Name)
                and d.func.id == "Depends"
                and d.args):
            yield d.args[0]  # The first arg inside Depends(...)


def _has_admin_default(defaults):
    """Check if any default contains get_current_admin."""
    return any(ADMIN in ast.unparse(d) for d in defaults)


def _has_require_roles(defaults, roles):
    """Check if any default is Depends(require_roles(...roles))."""
    for dep in _extract_depends_calls(defaults):
        if (isinstance(dep, ast.Call)
                and isinstance(dep.func, ast.Name)
                and dep.func.id == REQUIRE_ROLES):
            role_args = [arg.value for arg in dep.args if isinstance(arg, ast.Constant)]
            if role_args == roles:
                return True
    return False


# --- Mutation endpoints must use get_current_admin ---
def test_create_route_requires_admin():
    fns = _load_functions()
    defaults = list(_defaults(fns["create_graph"]))
    assert _has_admin_default(defaults), "create_graph must use get_current_admin"


def test_update_route_requires_admin():
    fns = _load_functions()
    defaults = list(_defaults(fns["update_graph"]))
    assert _has_admin_default(defaults), "update_graph must use get_current_admin"


def test_delete_route_requires_admin():
    fns = _load_functions()
    defaults = list(_defaults(fns["delete_graph"]))
    assert _has_admin_default(defaults), "delete_graph must use get_current_admin"


def test_run_manual_requires_admin():
    fns = _load_functions()
    defaults = list(_defaults(fns["run_graph_manual"]))
    assert _has_admin_default(defaults), "run_graph_manual must use get_current_admin"


def test_sweep_and_downsample_require_admin():
    fns = _load_functions()
    for name in ("trigger_graph_sweep", "trigger_downsample"):
        defaults = list(_defaults(fns[name]))
        assert _has_admin_default(defaults), f"{name} must use get_current_admin"


# --- Read endpoints must use require_roles("admin", "support") ---
def test_list_graphs_requires_admin_or_support():
    fns = _load_functions()
    defaults = list(_defaults(fns["list_graphs"]))
    assert _has_require_roles(defaults, ["admin", "support"]), \
        "list_graphs must require admin+support"


def test_graph_data_requires_admin_or_support():
    fns = _load_functions()
    defaults = list(_defaults(fns["graph_data"]))
    assert _has_require_roles(defaults, ["admin", "support"]), \
        "graph_data must require admin+support"


def test_export_requires_admin_or_support():
    fns = _load_functions()
    defaults = list(_defaults(fns["export_graph"]))
    assert _has_require_roles(defaults, ["admin", "support"]), \
        "export_graph must require admin+support"


def test_discover_sensors_requires_admin():
    fns = _load_functions()
    defaults = list(_defaults(fns["discover_sensors"]))
    assert _has_admin_default(defaults), "discover_sensors must use get_current_admin"


# --- Client endpoints must use get_current_user ---
def test_client_endpoints_use_get_current_user():
    fns = _load_functions()
    for name in ("client_list_graphs", "client_graph_data"):
        defaults = list(_defaults(fns[name]))
        rendered = [ast.unparse(d) for d in defaults]
        assert any("get_current_user" in d for d in rendered), \
            f"{name} must use get_current_user"
