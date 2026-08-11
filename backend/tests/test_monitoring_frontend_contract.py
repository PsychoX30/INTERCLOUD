"""Static contract for the internal monitoring operator UI."""
from pathlib import Path

ROOT = Path("/home/support/INTERCLOUD")
APP = ROOT / "frontend/src/App.js"
LAYOUT = ROOT / "frontend/src/pages/portal/PortalLayout.jsx"
PAGE = ROOT / "frontend/src/pages/portal/admin/AdminMonitoring.jsx"


def test_monitoring_page_is_lazy_routed_and_staff_nav_is_narrow():
    app = APP.read_text()
    layout = LAYOUT.read_text()

    assert 'const AdminMonitoring' in app
    assert 'import("./pages/portal/admin/AdminMonitoring")' in app
    assert (
        '<Route path="monitoring" element={<RequireAuth role={["admin", "support"]}>'
        '<AdminMonitoring /></RequireAuth>} />'
    ) in app
    nav_line = next(line for line in layout.splitlines() if 'key: "monitoring"' in line)
    assert 'roles: ["admin", "support"]' in nav_line
    assert 'to: "/portal/admin/monitoring"' in nav_line


def test_monitoring_page_uses_authenticated_role_and_persisted_check_endpoints():
    source = PAGE.read_text()

    assert 'useAuth' in source
    assert 'const isAdmin = user?.role === "admin"' in source
    assert 'api.get("/admin/monitoring/checks")' in source
    assert 'api.post("/admin/monitoring/checks"' in source
    assert 'api.put(`/admin/monitoring/checks/${editing.id}`' in source
    assert 'api.delete(`/admin/monitoring/checks/${id}`)' in source
    assert 'api.post(`/admin/monitoring/checks/${id}/run`)' in source
    assert 'api.get(`/admin/monitoring/checks/${id}/history`' in source
    assert '{isAdmin && (' in source


def test_monitoring_page_does_not_accept_an_arbitrary_manual_probe_target():
    source = PAGE.read_text()

    assert '/run`, { target:' not in source
    assert 'api.post(`/admin/monitoring/checks/${id}/run`)' in source
