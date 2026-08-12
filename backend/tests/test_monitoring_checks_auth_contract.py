"""Read-only AST/inspect check: the monitoring check registry only exposes
mutating endpoints to admins, while listing is open to admin/support.

Avoids importing the FastAPI route so we don't pull the heavy deps chain."""
import ast
from pathlib import Path

ROUTES_FILE = Path("/home/support/INTERCLOUD/backend/portal/routes/monitoring.py")
ADMIN = "get_current_admin"


def _load_functions():
    tree = ast.parse(ROUTES_FILE.read_text())
    function_types = (ast.FunctionDef, ast.AsyncFunctionDef)
    return {node.name: node for node in tree.body if isinstance(node, function_types)}


def _defaults(_name, func):
    yield from func.args.defaults


def test_create_route_requires_admin():
    fns = _load_functions()
    create = fns["monitoring_check_create"]
    defaults = list(_defaults("monitoring_check_create", create))
    matches = [ast.unparse(d) for d in defaults]
    assert any(ADMIN in d for d in matches), f"create defaults: {matches}"


def test_update_and_delete_require_admin():
    fns = _load_functions()
    for name in ("monitoring_check_update", "monitoring_check_delete", "monitoring_check_run"):
        defaults = list(_defaults(name, fns[name]))
        rendered = [ast.unparse(d) for d in defaults]
        assert any(ADMIN in d for d in rendered), f"{name} defaults: {rendered}"


def test_list_allows_admin_and_support():
    fns = _load_functions()
    for name in ("monitoring_checks_list", "monitoring_check_history"):
        defaults = list(_defaults(name, fns[name]))
        dependencies = [
            default.args[0]
            for default in defaults
            if isinstance(default, ast.Call)
            and isinstance(default.func, ast.Name)
            and default.func.id == "Depends"
            and default.args
        ]
        role_calls = [
            dep for dep in dependencies
            if isinstance(dep, ast.Call)
            and isinstance(dep.func, ast.Name)
            and dep.func.id == "require_roles"
        ]
        assert any(
            [arg.value for arg in call.args if isinstance(arg, ast.Constant)] == ["admin", "support"]
            for call in role_calls
        ), f"{name} must allow exactly admin/support"


def test_monitoring_route_module_registered():
    routes_init = Path("/home/support/INTERCLOUD/backend/portal/routes/__init__.py").read_text()
    tree = ast.parse(routes_init)
    included = [
        ast.unparse(node.value.args[0])
        for node in tree.body
        if isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Attribute)
        and node.value.func.attr == "include_router"
        and node.value.args
    ]
    assert "monitoring.router" in included


def test_monitoring_indexes_match_registry_and_probe_queries():
    server_source = Path("/home/support/INTERCLOUD/backend/server.py").read_text()
    required = {
        # Registry listing is globally ordered by created_at, while the sweep
        # filters enabled checks; both access paths require their own index.
        'await db.monitoring_checks.create_index([("created_at", 1)])',
        'await db.monitoring_checks.create_index([("enabled", 1), ("created_at", 1)])',
        'await db.monitoring_probes.create_index([("check_id", 1), ("at", -1)])',
        'await db.monitoring_check_state.create_index("check_id", unique=True)',
        'await db.monitoring_events.create_index([("check_id", 1), ("at", -1)])',
    }
    assert all(index in server_source for index in required)
    assert "db.monitoring_probes.create_index" in server_source
    # The monitoring_* indexes should not use TTL, but the graph sample
    # collections (monitoring_graph_samples_*) legitimately use TTL.
    # Assert only that monitoring_checks*/probes/events/state do not use TTL.
    monitoring_lines = [line for line in server_source.splitlines() if "monitoring_" in line]
    graph_sample_lines = [line for line in monitoring_lines if "monitoring_graph_samples" in line]
    non_graph_lines = [line for line in monitoring_lines if "monitoring_graph_samples" not in line]
    assert "expireAfterSeconds" not in "\n".join(non_graph_lines), "Non-graph monitoring indexes must not use TTL"
