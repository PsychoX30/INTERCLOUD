"""Static contract for the consolidated Operations Center.

This replaces the older per-page contracts (``test_ops_routes_contract.py`` and
``test_monitoring_frontend_contract.py``), which pinned the *standalone* route and
sidebar entry for Ops Overview and Monitoring. Those assertions were correct while
each surface had its own menu — and they are exactly what made the duplicate menu
possible, because they required a second way in for a page the Operations Center
already rendered as a tab.

The contract now is:

* there is ONE sidebar entry point (``operations_center``) and the surfaces that
  were folded into it have no sibling nav entry,
* the legacy routes still resolve, as redirects into the matching console tab,
  so bookmarks and backend-emitted links do not 404,
* the console route admits staff and every tab keeps the exact role list its
  standalone page had — merging menus must not widen access,
* the composed pages accept ``embedded`` and drop their own ``<PageHeader>``,
  which is the actual cause of "Operations Center and NOC Monitor look identical",
* the ops read-model stays read-only and its attention links point at console
  tabs the caller's role can open,
* every menu the sidebar can render is also present in the access catalog, and
  the catalog's ``default_roles`` agrees with the nav role gate. A menu the nav
  renders but the catalog omits cannot be granted *at all*, because the access
  modal builds its checkboxes from the catalog — there is no key to tick.

AST/string level only: no app import, no network, no DB.
"""
import ast
import re
from pathlib import Path

ROOT = Path("/home/support/INTERCLOUD")

APP = (ROOT / "frontend/src/App.js").read_text()
LAYOUT = (ROOT / "frontend/src/pages/portal/PortalLayout.jsx").read_text()
CENTER = (ROOT / "frontend/src/pages/portal/admin/AdminNOCCenter.jsx").read_text()

ADMIN_DIR = ROOT / "frontend/src/pages/portal/admin"
OPS_MODEL = (ROOT / "backend/portal/ops.py").read_text()
OPS_ROUTE = (ROOT / "backend/portal/routes/ops.py").read_text()
ROUTES_INIT = (ROOT / "backend/portal/routes/__init__.py").read_text()
USERS = (ROOT / "backend/portal/routes/users.py").read_text()

CONSOLE_PATH = "/portal/admin/operations-center"

# Surfaces folded into the console, with the role list each tab must keep.
MERGED_TABS = {
    "overview": ('"admin", "support"', "/portal/admin/ops"),
    "noc": ('"admin", "support"', "/portal/admin/noc"),
    "monitoring": ('"admin", "support"', "/portal/admin/monitoring"),
    "diagnostics": ('"admin", "support"', "/portal/admin/diagnostics"),
    "sla": ('"admin", "support", "finance", "sales"', "/portal/admin/sla"),
    "security": ('"admin"', "/portal/admin/security"),
    "audit": ('"admin"', "/portal/admin/audit-log"),
}


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


# ---------------------------------------------------------------------------
# Ops read-model / route (unchanged guarantees)
# ---------------------------------------------------------------------------
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
    assert "ops" in ROUTES_INIT.split("from . import (")[1].split(")")[0]
    assert "router.include_router(ops.router)" in ROUTES_INIT


# ---------------------------------------------------------------------------
# The console is the only entry point
# ---------------------------------------------------------------------------
def test_console_is_lazy_routed_for_staff():
    assert 'const AdminNOCCenter' in APP
    assert 'import("./pages/portal/admin/AdminNOCCenter")' in APP
    assert '<Route path="operations-center" element={<AdminNOCCenterRoute />} />' in APP
    # The route level admits staff; each tab carries its own narrower gate.
    assert 'const STAFF_ROLES = ["admin", "support", "finance", "sales", "ticket_only", "creative"];' in APP
    assert "<RequireAuth role={STAFF_ROLES}>" in APP


def test_folded_pages_are_no_longer_imported_by_the_router():
    """A second import in App.js is how the standalone routes stayed alive."""
    for page in ("AdminNOC", "AdminOps", "AdminMonitoring",
                 "AdminDiagnostics", "AdminSLA", "AdminSecurity", "AdminAuditLog"):
        assert f'import("./pages/portal/admin/{page}")' not in APP, (
            f"{page} must be composed by AdminNOCCenter, not routed directly"
        )


def test_legacy_routes_redirect_into_the_matching_tab():
    for tab, (_, legacy) in MERGED_TABS.items():
        # `ops` is the console's own default tab, so its redirect names it too.
        expected = (
            f'<Route path="ops" element={{<Navigate to="{CONSOLE_PATH}?tab=overview" replace />}} />'
            if tab == "overview"
            else None
        )
        if expected:
            assert expected in APP, f"missing redirect for {legacy}"
            continue
        seg = legacy.rsplit("/", 1)[-1]
        redirect = f'<Route path="{seg}" element={{<Navigate to="{CONSOLE_PATH}?tab={tab}" replace />}} />'
        assert redirect in APP, f"missing redirect {redirect}"


def test_sidebar_has_exactly_one_operations_entry():
    for dead in ('testid: "nav-noc"', 'testid: "nav-ops"', 'testid: "nav-monitoring"',
                 'testid: "nav-sla"', 'testid: "nav-diagnostics"',
                 'testid: "nav-security"', 'testid: "nav-audit-log"'):
        assert dead not in LAYOUT, f"{dead} must not survive the merge"
    nav_line = next(line for line in LAYOUT.splitlines()
                    if 'testid: "nav-operations-center"' in line)
    assert f'to: "{CONSOLE_PATH}"' in nav_line
    assert 'roles: ["admin", "support", "finance", "sales"]' in nav_line


def test_sidebar_still_renders_operations_center_for_a_tab_only_allow_list():
    """A user whose menu_keys still name an old key must keep seeing the console."""
    assert "aliasKeys" in LAYOUT
    assert "it.aliasKeys.some((k) => user.menu_keys.includes(k))" in LAYOUT
    nav_line = next(line for line in LAYOUT.splitlines()
                    if 'testid: "nav-operations-center"' in line)
    for old_key in ("ops", "noc", "monitoring", "diagnostics", "sla", "security", "audit_log"):
        assert f'"{old_key}"' in nav_line, f"alias key {old_key} missing from the nav entry"


# ---------------------------------------------------------------------------
# Tabs keep the roles their standalone pages had
# ---------------------------------------------------------------------------
def test_every_merged_tab_keeps_its_original_role_gate():
    for tab, (roles, _legacy) in MERGED_TABS.items():
        line = next(
            (ln for ln in CENTER.splitlines() if f'key: "{tab}"' in ln),
            None,
        )
        assert line, f"tab {tab} missing from AdminNOCCenter TABS"
        assert f"roles: [{roles}]" in line, (
            f"tab {tab} must keep roles: [{roles}] — merging menus must not widen access"
        )


def test_console_hides_tabs_the_role_cannot_open_and_never_renders_an_empty_panel():
    assert "visibleTabs = useMemo(" in CENTER
    assert "t.roles.includes(role)" in CENTER
    # An unknown ?tab= value or a shrunken role gate must resolve to a visible tab.
    assert "if (visibleTabs.some((t) => t.key === tab)) return;" in CENTER
    assert "const fallback = visibleTabs[0].key;" in CENTER
    # A role with no surface at all gets an explanation, not a blank page.
    assert "noc-center-no-tabs" in CENTER


def test_console_tab_state_lives_in_the_url():
    """Without ?tab= in the URL, the legacy redirects and deep links are inert."""
    assert "useSearchParams" in CENTER
    assert 'searchParams.get("tab")' in CENTER
    assert "setSearchParams({ tab: key }, { replace: true })" in CENTER
    # Tab switching must not stack history entries.
    assert "{ replace: true }" in CENTER


def test_url_never_names_a_tab_the_role_cannot_see():
    """A sales user who opens a bookmarked ?tab=noc gets the SLA panel. If the
    URL kept saying `noc`, the address bar would contradict the screen and the
    next render would read a value the role cannot open."""
    # The role gate must rewrite the URL when it falls back...
    assert "setSearchParams({ tab: fallback }, { replace: true })" in CENTER
    # ...and the normaliser must not fight a tab the role *can* see.
    assert "visibleTabs.some((t) => t.key === tabFromUrl)" in CENTER
    # An empty tab set must not crash the fallback path.
    assert "if (!visibleTabs.length) return;" in CENTER


# ---------------------------------------------------------------------------
# The duplicate-heading bug must stay fixed
# ---------------------------------------------------------------------------
def test_composed_pages_accept_embedded_and_suppress_their_own_header():
    for page, testid in (
        ("AdminNOC.jsx", "noc-page"),
        ("AdminMonitoring.jsx", "monitoring-page"),
        ("AdminDiagnostics.jsx", "diagnostics-page"),
        ("AdminSLA.jsx", "sla-page"),
        ("AdminOps.jsx", "ops-page"),
        ("AdminSecurity.jsx", "security-page"),
        ("AdminAuditLog.jsx", "audit-log-page"),
    ):
        src = (ADMIN_DIR / page).read_text()
        assert "embedded" in src, f"{page} must accept an `embedded` prop"
        assert f'data-testid="{testid}"' in src, f"{page} lost its root testid"
    # The console must actually pass it, or the header comes back.
    for composed in ("<AdminOps embedded", "<AdminNOC embedded", "<AdminMonitoring embedded",
                     "<AdminDiagnostics embedded", "<AdminSLA embedded",
                     "<AdminSecurity embedded", "<AdminAuditLog embedded"):
        assert composed in CENTER, f"console must render {composed}"


def test_console_does_not_duplicate_a_child_pages_heading():
    """Operations Center prints one <h1>. The tab panels must print none."""
    # Count real JSX usages, not mentions in prose comments.
    code_lines = [
        ln for ln in CENTER.splitlines()
        if not ln.lstrip().startswith("//")
    ]
    jsx_headers = [ln for ln in code_lines if "<PageHeader" in ln and "import" not in ln]
    assert len(jsx_headers) == 1, f"expected exactly one <PageHeader>, found {len(jsx_headers)}"
    assert 'title="Operations Center"' in CENTER


def test_console_tabs_are_unmounted_when_inactive():
    """Seven polling panels mounted at once would multiply background load."""
    assert "tab === \"noc\"         && <AdminNOC embedded />" in CENTER
    assert "tab === \"sla\"         && <AdminSLA embedded />" in CENTER


# ---------------------------------------------------------------------------
# Attention links must land on a tab the caller can open
# ---------------------------------------------------------------------------
def test_ops_attention_links_point_at_console_tabs():
    assert "_ops_tab_link" in OPS_MODEL
    assert 'return f"/portal/admin/operations-center?tab={tab}"' in OPS_MODEL
    # Unknown paths are passed through untouched rather than mangled.
    assert "if not tab:\n        return link" in OPS_MODEL


def test_ops_attention_links_respect_the_callers_role():
    """A finance/sales operator can read SLA but must not be sent to a NOC tab."""
    assert '"sla": ("admin", "support", "finance", "sales"),' in OPS_MODEL
    assert 'return "/portal/admin/operations-center"' in OPS_MODEL
    assert "role=staff.get(\"role\") or \"admin\"" in OPS_ROUTE


def test_ops_attention_rows_are_clickable_inside_the_console():
    page = (ADMIN_DIR / "AdminOps.jsx").read_text()
    assert "onNavigate" in page
    assert "onNavigate(item.link)" in page
    assert "<AdminOps embedded onNavigate={goLink} />" in CENTER


# ---------------------------------------------------------------------------
# The composed pages keep the guarantees their own contracts pinned
# ---------------------------------------------------------------------------
def test_monitoring_tab_keeps_role_aware_check_crud():
    """Carried over from test_monitoring_frontend_contract.py — folding the page
    into a tab must not drop its role gate or its persisted-check endpoints."""
    source = (ADMIN_DIR / "AdminMonitoring.jsx").read_text()

    assert "useAuth" in source
    assert 'const isAdmin = user?.role === "admin"' in source
    assert 'api.get("/admin/monitoring/checks")' in source
    assert 'api.post("/admin/monitoring/checks"' in source
    assert 'api.put(`/admin/monitoring/checks/${editing.id}`' in source
    assert 'api.delete(`/admin/monitoring/checks/${id}`)' in source
    assert 'api.post(`/admin/monitoring/checks/${id}/run`)' in source
    assert 'api.get(`/admin/monitoring/checks/${id}/history`' in source
    assert "{isAdmin && (" in source


def test_monitoring_tab_does_not_accept_an_arbitrary_manual_probe_target():
    source = (ADMIN_DIR / "AdminMonitoring.jsx").read_text()
    assert "/run`, { target:" not in source
    assert 'api.post(`/admin/monitoring/checks/${id}/run`)' in source


def test_ops_tab_uses_the_overview_endpoint_and_renders_unknowns():
    """Carried over from test_ops_routes_contract.py."""
    page = (ADMIN_DIR / "AdminOps.jsx").read_text()
    assert 'api.get("/admin/ops/overview")' in page
    # Unknown counters must render as a distinct glyph, never as 0.
    assert '"—"' in page
    # A failed aggregate must be shown, not swallowed.
    assert "ops-error" in page


def _menu_catalog_entries() -> list:
    """Parse ADMIN_MENU_CATALOG (the assignment *and* the += that merges the
    Operations Center tab keys) straight out of the module source.

    Text slicing is what broke the first version of this test: the catalog is
    built by two statements, so a slice at the first ``]`` sees only half of it.
    """
    entries: list = []
    for node in ast.parse(USERS).body:
        if isinstance(node, ast.Assign) and any(
            getattr(t, "id", None) == "ADMIN_MENU_CATALOG" for t in node.targets
        ):
            entries.extend(ast.literal_eval(node.value))
        elif isinstance(node, ast.AugAssign) and getattr(node.target, "id", None) == "ADMIN_MENU_CATALOG":
            entries.extend(ast.literal_eval(node.value))
    return entries


def test_menu_catalog_offers_a_single_operations_entry():
    """Exactly one *menu* entry for the console. The former top-level keys stay
    in the catalog only so an existing allow-list still resolves, and they must
    not be offered as menus."""
    entries = _menu_catalog_entries()
    assert entries, "could not parse ADMIN_MENU_CATALOG"

    menus = [e for e in entries if e.get("kind") != "tab"]
    tabs = [e for e in entries if e.get("kind") == "tab"]

    assert any(e["key"] == "operations_center" for e in menus)
    menu_keys = {e["key"] for e in menus}
    tab_keys = {e["key"] for e in tabs}

    for folded in ("diagnostics", "noc", "monitoring", "ops", "sla", "security", "audit_log"):
        assert folded not in menu_keys, (
            f"catalog must not offer a second menu entry for {folded}"
        )
        assert folded in tab_keys, (
            f"catalog must keep {folded} so existing allow-lists still resolve"
        )


def test_tab_entries_are_hidden_from_the_access_modal():
    """A tab key rendered as a checkbox would let an admin toggle a menu that no
    longer exists. Both the `kind` marker and the reserved group are required —
    the modal filters on either."""
    tabs = [e for e in _menu_catalog_entries() if e.get("kind") == "tab"]
    assert len(tabs) == 7, f"expected 7 tab keys, got {len(tabs)}"
    for entry in tabs:
        assert entry.get("kind") == "tab"
        assert entry.get("group", "").startswith("_"), (
            f"tab key {entry['key']} must sit in a reserved group, got {entry.get('group')!r}"
        )


def test_every_menu_entry_is_still_a_real_menu():
    """Guard against the reverse mistake: nothing else in the catalog may hide
    itself from the access modal."""
    for entry in _menu_catalog_entries():
        if entry.get("kind") == "tab":
            continue
        assert not entry.get("group", "").startswith("_"), (
            f"menu {entry['key']} uses a reserved group prefix and would vanish "
            f"from the access modal"
        )
        assert entry.get("kind") in (None, "menu"), (
            f"menu {entry['key']} carries an unexpected kind {entry.get('kind')!r}"
        )


def test_access_modal_does_not_render_tab_keys_as_checkboxes():
    """The backend hides them; the modal must also skip them client-side, or an
    admin sees a checkbox for a menu that no longer exists."""
    modal = (ADMIN_DIR / "AdminUsers.jsx").read_text()
    assert 'm.kind === "tab"' in modal
    assert '(m.group || "").startsWith("_")' in modal


# ---------------------------------------------------------------------------
# Sidebar / access-catalog parity
#
# The access modal builds its checkboxes FROM the catalog. So a menu the sidebar
# can render but the catalog omits has no key to tick — the admin literally
# cannot grant it, and `menu_keys` (an allow-list) then hides it forever for any
# user who is customised at all. Five menus were in that state: cve_tracker,
# domains, jitsi, ssl, virtualization.
# ---------------------------------------------------------------------------
_NAV_ENTRY_RE = re.compile(
    r'\{\s*key:\s*"(?P<key>[^"]+)",\s*to:\s*"(?P<to>[^"]+)",\s*'
    r'label:\s*"(?P<label>[^"]+)"[^\n]*?roles:\s*\[(?P<roles>[^\]]*)\]'
)


def _nav_entries() -> dict:
    """key -> {to, label, roles} for every admin sidebar item."""
    entries = {}
    for m in _NAV_ENTRY_RE.finditer(LAYOUT):
        roles = [r.strip().strip('"') for r in m.group("roles").split(",") if r.strip()]
        entries[m.group("key")] = {
            "to": m.group("to"),
            "label": m.group("label"),
            "roles": roles,
        }
    return entries


def test_sidebar_parse_is_not_silently_empty():
    """Guards the parser itself: a refactor of PortalLayout must not turn the
    parity checks below into a vacuous pass."""
    nav = _nav_entries()
    assert len(nav) > 30, f"parsed only {len(nav)} sidebar entries — parser drifted"
    assert "operations_center" in nav


def test_every_sidebar_menu_is_grantable_from_the_access_catalog():
    """A nav item with no catalog entry can never be granted to anyone."""
    catalog_keys = {e["key"] for e in _menu_catalog_entries() if e.get("kind") != "tab"}
    orphans = sorted(set(_nav_entries()) - catalog_keys)
    assert not orphans, (
        "sidebar menus missing from ADMIN_MENU_CATALOG (cannot be granted, and "
        f"`menu_keys` will hide them for every customised user): {orphans}"
    )


def test_catalog_default_roles_agree_with_the_sidebar_gate():
    """`default_roles` is what the modal pre-ticks and what the backend falls back
    to. If it names a role the sidebar does not render the item for, the catalog
    promises access that does not exist; if it omits one, the item silently
    disappears for that role once a user is customised."""
    catalog = {e["key"]: e for e in _menu_catalog_entries() if e.get("kind") != "tab"}
    nav = _nav_entries()
    mismatches = []
    for key, entry in catalog.items():
        if key not in nav:
            continue
        promised = set(entry.get("default_roles") or [])
        rendered = set(nav[key]["roles"])
        if promised != rendered:
            mismatches.append(
                f"{key}: catalog-only={sorted(promised - rendered)} "
                f"nav-only={sorted(rendered - promised)}"
            )
    assert not mismatches, "catalog/nav role drift:\n  " + "\n  ".join(mismatches)


def test_catalog_has_no_key_that_resolves_to_nothing():
    """The reverse direction: a grantable key with no nav entry and no console tab
    is a checkbox that does nothing."""
    nav = _nav_entries()
    dangling = sorted(
        e["key"] for e in _menu_catalog_entries()
        if e.get("kind") != "tab" and e["key"] not in nav
    )
    assert not dangling, f"catalog menus with no sidebar entry: {dangling}"
