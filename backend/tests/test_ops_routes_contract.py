"""Static contract for the unified Ops overview.

AST-based (read-only, no app import) like the monitoring auth contract:

* the route is read-only for admin+support and mutates nothing,
* the read-model contains no database writes,
* the frontend page is lazy-routed with a matching role guard and a nav entry.
"""
import ast
from pathlib import Path

ROOT = Path("/home/support/INTERCLOUD")
OPS_MODEL = (ROOT / "backend/portal/ops.py").read_text()
OPS_ROUTE = (ROOT / "backend/portal/routes/ops.py").read_text()
ROUTES_INIT = (ROOT / "backend/portal/routes/__init__.py").read_text()
APP = (ROOT / "frontend/src/App.js").read_text()
LAYOUT = (ROOT / "frontend/src/pages/portal/PortalLayout.jsx").read_text()
PAGE = (ROOT / "frontend/src/pages/portal/admin/AdminOps.jsx").read_text()


def _calls(source: str) -> set:
    """All function/method names invoked anywhere in the source."""
    names = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call):
            fn = node.func
            if isinstance(fn, ast.Name):
                names.add(fn.id)
            elif isinstance(fn, ast.Attribute):
                names.add(fn.attr)
    return names


def test_ops_read_model_never_writes():
    calls = _calls(OPS_MODEL)
    for forbidden in ("insert_one", "insert_many", "update_one", "update_many",
                      "delete_one", "delete_many", "replace_one",
                      "find_one_and_update", "find_one_and_replace",
                      "bulk_write", "aggregate", "drop"):
        assert forbidden not in calls, f"read-model must not call {forbidden}()"


def test_ops_route_is_read_only_with_role_guard():
    assert 'ops_overview(staff=Depends(require_roles("admin", "support")))' in OPS_ROUTE
    assert "build_ops_overview" in OPS_ROUTE
    # The route must not widen beyond one GET.
    assert "@router.get" in OPS_ROUTE
    for method in ("@router.post", "@router.put", "@router.patch", "@router.delete"):
        assert method not in OPS_ROUTE


def test_ops_router_is_mounted():
    assert "network_map, ops)" in ROUTES_INIT
    assert "router.include_router(ops.router)" in ROUTES_INIT


def test_ops_page_is_lazy_routed_and_role_guarded():
    assert 'const AdminOps' in APP
    assert 'import("./pages/portal/admin/AdminOps")' in APP
    assert (
        '<Route path="ops" element={<RequireAuth role={["admin", "support"]}>'
        "<AdminOps /></RequireAuth>} />"
    ) in APP


def test_ops_nav_entry_is_staff_only():
    nav_line = next(line for line in LAYOUT.splitlines() if 'key: "ops"' in line)
    assert 'roles: ["admin", "support"]' in nav_line
    assert 'to: "/portal/admin/ops"' in nav_line
    assert 'testid: "nav-ops"' in nav_line


def test_ops_page_uses_the_overview_endpoint_and_renders_unknowns():
    assert 'api.get("/admin/ops/overview")' in PAGE
    # Unknown counters must render as a distinct glyph, never as 0.
    assert '"—"' in PAGE
    # A failed aggregate must be shown, not swallowed.
    assert "ops-error" in PAGE
