import fs from "fs";
import path from "path";

// The admin sidebar grew past a screenful: 9 groups / ~40 links rendered flat,
// so reaching "Credit Notes" meant scrolling past every group on desktop, and
// on mobile that scroll happened inside an overlay that also had to be closed.
// Groups now fold. These guards pin the behaviour that makes folding usable:
// a real toggle per group, an accessible expanded state, auto-reveal of the
// group owning the current route, and persistence so the choice survives nav.
//
// Note: this file now has BOTH a behavior companion test that clicks a real DOM
// (PortalLayout.nav-collapse.behavior.test.jsx, jsdom + RTL) AND these
// source-level guards. The guards pin the wiring; the behavior test proves the
// click path end-to-end. The behavior test is the authoritative gate.
describe("PortalLayout admin nav folding (source guards)", () => {
  const source = fs.readFileSync(path.join(__dirname, "PortalLayout.jsx"), "utf8");

  const navRender = source.slice(
    source.indexOf('<nav className="flex-1 overflow-y-auto'),
    source.indexOf("<div className=\"px-3 py-3 border-t"),
  );

  it("renders each admin group as a toggle button, not a static label", () => {
    expect(navRender).toContain("onClick={() => toggleGroup(grp.label)}");
    expect(navRender).toContain("data-testid={`nav-group-toggle-");
    // The old static header div must be gone.
    expect(navRender).not.toMatch(/text-white\/40 font-bold mb-1\.5/);
  });

  it("hides group items while folded and shows them when unfolded", () => {
    expect(navRender).toContain("const isCollapsed = isGroupCollapsed(grp.label);");
    expect(navRender).toMatch(/\{!isCollapsed && \(/);
    expect(navRender).toContain("grp.items.map((it) => (");
  });

  // The reported problem was total sidebar length, so groups must NOT all start
  // open — folding is the default. Without this, first load still shows the
  // ~40-link scroll the user complained about.
  it("folds groups by default, not only after a click", () => {
    const defaultBlock = source.slice(
      source.indexOf("const isGroupCollapsed = useCallback"),
      source.indexOf("const groupSlug ="),
    );
    expect(defaultBlock).toContain("collapsedGroups[label] ?? !activeGroupLabels.includes(label)");
  });

  // A group must never render an untoggleable header, and its panel id must be
  // derived from the same slug for both aria-controls and the element id.
  it("derives a stable slug shared by toggle testid, aria-controls and panel id", () => {
    expect(source).toContain('const groupSlug = (label) => label.toLowerCase().replace(/[^a-z0-9]+/g, "-");');
    expect(navRender).toContain("data-testid={`nav-group-toggle-${groupSlug(grp.label)}`}");
    expect(navRender).toContain("aria-controls={`nav-group-${groupSlug(grp.label)}`}");
    expect(navRender).toContain('id={`nav-group-${groupSlug(grp.label)}`}');
  });

  it("exposes the folded state to assistive tech", () => {
    expect(navRender).toContain("aria-expanded={!isCollapsed}");
    expect(navRender).toContain("aria-controls={`nav-group-");
  });

  it("shows a chevron that reflects the folded state", () => {
    expect(navRender).toContain("<ChevronRight");
    expect(navRender).toContain("<ChevronDown");
  });

  it("keeps role and menu_keys filtering authoritative", () => {
    const filterBlock = source.slice(
      source.indexOf("const visibleAdminGroups = useMemo"),
      source.indexOf("const activeGroupLabels = useMemo"),
    );
    expect(filterBlock).toContain("grp.items.filter");
    expect(filterBlock).toContain("it.roles.includes(user?.role)");
    expect(filterBlock).toContain("user.menu_keys.includes(it.key)");
    // A group with nothing visible for this user must not render a header.
    expect(filterBlock).toContain(".filter((grp) => grp.items.length > 0)");
  });

  it("auto-reveals the group that owns the current route", () => {
    const activeBlock = source.slice(
      source.indexOf("const activeGroupLabels = useMemo"),
      source.indexOf("const toggleGroup = useCallback"),
    );
    expect(activeBlock).toContain("location.pathname");
    expect(activeBlock).toContain("path.startsWith(`${it.to}/`)");
    // Direct URL entry must not strand the user in a folded group. The effect
    // now expands only when the active group *identity* changes; same-group nav
    // keeps the user's deliberate folded state.
    expect(activeBlock).toContain("lastExpandedRef.current === label");
    expect(activeBlock).toContain('setCollapsedGroups((prev) => (prev[label] ? { ...prev, [label]: false } : prev))');
  });

  it("persists folded groups across navigation and reload", () => {
    expect(source).toContain('const STORAGE_KEY_ADMIN_NAV_COLLAPSED = "ic_admin_nav_collapsed_groups";');
    expect(source).toContain("window.localStorage.getItem(STORAGE_KEY_ADMIN_NAV_COLLAPSED)");
    expect(source).toContain("JSON.stringify(collapsedGroups)");
    // Malformed storage must not break the sidebar.
    expect(source).toMatch(/catch \{\s*\/\/ ignore malformed localStorage/);
  });

  it("toggles a single group without disturbing the others", () => {
    const toggleBlock = source.slice(
      source.indexOf("const toggleGroup = useCallback"),
      source.indexOf("const returnToAdmin = () =>"),
    );
    // F1: the inverted value must be the EFFECTIVE collapsed state (what the UI
    // renders), not the raw stored value — otherwise the first click on a
    // default-folded group is a no-op.
    expect(toggleBlock).toContain("const current = prev[label] ?? !activeGroupLabels.includes(label);");
    expect(toggleBlock).toContain("return { ...prev, [label]: !current };");
  });

  it("leaves the client sidebar unfaceted", () => {
    // Clients have 12 short links; folding there would be noise.
    expect(navRender).toContain('CLIENT_NAV.map((it) => <NavItem');
  });
});
