import React, { useEffect, useState, useCallback, useMemo } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import {
  ShieldCheck, History, MonitorCheck, Activity, LifeBuoy,
  RefreshCw, AlertTriangle, Wifi, WifiOff, Ban, ShieldAlert,
  LayoutDashboard, TerminalSquare,
} from "lucide-react";
import { api } from "../../../portal/api";
import { PageHeader, Loading } from "../ui";
import { SamplingBadge, SamplingAlert, useSamplingHealth } from "./SamplingHealth";
import AdminOps from "./AdminOps";
import AdminNOC from "./AdminNOC";
import AdminMonitoring from "./AdminMonitoring";
import AdminDiagnostics from "./AdminDiagnostics";
import AdminSLA from "./AdminSLA";
import AdminSecurity from "./AdminSecurity";
import AdminAuditLog from "./AdminAuditLog";

// The single Operations Center.
//
// History: this console used to compose NOC / Monitoring / Security / Audit /
// SLA as tabs *while* those same pages also existed as their own sidebar
// entries — and it rendered AdminNOC as its first tab. So "Operations Center"
// and "NOC Monitor" were not two implementations of one feature, they were one
// implementation reachable two ways, with the console re-printing the NOC page
// header underneath its own. That is the duplicate-menu report.
//
// The fix is one entry point, one tab per surface, and no second header: each
// composed page takes `embedded` and drops its own <PageHeader>. The pages stay
// separate files on purpose — each owns a large, self-contained panel set, and
// duplicating them would mean two code paths per feature and two places to fix
// a bug. The legacy routes (/portal/admin/{ops,noc,monitoring,diagnostics,sla})
// redirect here with ?tab=<key> so bookmarks and backend-emitted links survive.
//
// Access is NOT widened by the merge. The route still admits any staff role
// (as /operations-center always did) and every tab keeps the exact role list
// the standalone page had. A tab the role cannot see was also a page the role
// could not open. The backend keeps its own guards regardless.
const TABS = [
  // `roles` decides for a user with no allow-list; `keys` decides for one who
  // has it. Both are needed because an explicit grant must be able to hand a
  // surface to a role that never had it, and the sidebar already treats an
  // allow-list as authoritative in both directions.
  { key: "overview",    label: "Ops Overview",    icon: LayoutDashboard, roles: ["admin", "support"], keys: ["ops", "operations_center"] },
  { key: "noc",         label: "NOC Monitor",     icon: MonitorCheck,    roles: ["admin", "support"], keys: ["noc", "operations_center"] },
  { key: "monitoring",  label: "Monitoring",      icon: Activity,        roles: ["admin", "support"], keys: ["monitoring", "operations_center"] },
  { key: "diagnostics", label: "Diagnostics",     icon: TerminalSquare,  roles: ["admin", "support"], keys: ["diagnostics", "operations_center"] },
  { key: "sla",         label: "SLA & Incidents", icon: LifeBuoy,        roles: ["admin", "support", "finance", "sales"], keys: ["sla", "operations_center"] },
  { key: "security",    label: "Security",        icon: ShieldCheck,     roles: ["admin"], keys: ["security", "operations_center"] },
  { key: "audit",       label: "Audit Log",       icon: History,         roles: ["admin"], keys: ["audit_log", "operations_center"] },
];

// Legacy route -> tab. Used both by the redirects in App.js (via ?tab=) and by
// cross-surface links that the backend still emits with old paths.
export const ROUTE_TO_TAB = {
  "/portal/admin/operations-center": "overview",
  "/portal/admin/ops": "overview",
  "/portal/admin/noc": "noc",
  "/portal/admin/monitoring": "monitoring",
  "/portal/admin/diagnostics": "diagnostics",
  "/portal/admin/sla": "sla",
  "/portal/admin/security": "security",
  "/portal/admin/audit-log": "audit",
};

const AdminNOCCenter = ({ user: userProp }) => {
  const role = userProp?.role;

  // An explicit allow-list is authoritative here too: a user granted
  // `operations_center` (or one of the former top-level keys the console
  // absorbed) sees those panels even when their role would not, and a user not
  // granted them does not see them even when their role would.
  const allow = useMemo(
    () => (Array.isArray(userProp?.menu_keys) ? userProp.menu_keys : []),
    [userProp?.menu_keys],
  );

  const readable = useMemo(() => {
    const set = new Set();
    TABS.forEach((t) => {
      if (role === "admin") set.add(t.key);
      else if (allow.length) { if (t.keys.some((k) => allow.includes(k))) set.add(t.key); }
      else if (!t.roles || t.roles.includes(role)) set.add(t.key);
    });
    return set;
  }, [role, allow]);
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();

  const visibleTabs = useMemo(() => TABS.filter((t) => readable.has(t.key)), [readable]);

  const tabFromUrl = searchParams.get("tab");
  const initialTab = useMemo(() => {
    if (tabFromUrl && visibleTabs.some((t) => t.key === tabFromUrl)) return tabFromUrl;
    return visibleTabs[0]?.key || "";
  }, [tabFromUrl, visibleTabs]);

  const [tab, setTab] = useState(initialTab);

  // Keep the active tab valid when the role gate shrinks the tab set, or when a
  // ?tab= value names a surface this role may not see (a stale bookmark, for
  // example). Resolve to the first visible tab instead of rendering nothing.
  useEffect(() => {
    if (!visibleTabs.length) return;
    if (visibleTabs.some((t) => t.key === tab)) return;

    const fallback = visibleTabs[0].key;
    setTab(fallback);
    // Keep the URL honest. A sales user who hits a bookmarked ?tab=noc must not
    // be left with a URL that claims `noc` while the SLA panel is on screen —
    // that lies to whoever copies the address, and to the next render.
    if (tabFromUrl && tabFromUrl !== fallback) {
      setSearchParams({ tab: fallback }, { replace: true });
    }
  }, [visibleTabs, tab, tabFromUrl, setSearchParams]);

  // Deep link wins when it changes (back/forward, or a link from AdminOps).
  useEffect(() => {
    if (tabFromUrl && tabFromUrl !== tab && visibleTabs.some((t) => t.key === tabFromUrl)) {
      setTab(tabFromUrl);
    }
    // `tab` is intentionally not a dependency: writing the URL on tab click must
    // not bounce back through this effect.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tabFromUrl, visibleTabs]);

  // Normalise an empty or stale ?tab= to the tab actually being rendered, so the
  // address bar always names what the user sees.
  useEffect(() => {
    if (!tab) return;
    if (tabFromUrl === tab) return;
    // An unknown/invisible tab is handled by the role gate above; only rewrite
    // when the URL is empty or names something this role cannot see.
    if (tabFromUrl && visibleTabs.some((t) => t.key === tabFromUrl)) return;
    setSearchParams({ tab }, { replace: true });
  }, [tab, tabFromUrl, visibleTabs, setSearchParams]);

  const goTab = useCallback((key) => {
    setTab(key);
    // `replace` keeps the back button meaningful: tab switching is not history.
    setSearchParams({ tab: key }, { replace: true });
  }, [setSearchParams]);

  // Links that point at an old standalone route are resolved to a tab first.
  // Anything that is genuinely a separate page (or a tab this role cannot see)
  // falls through to a normal navigation rather than silently doing nothing.
  const goLink = useCallback((link) => {
    const key = ROUTE_TO_TAB[link];
    if (key && visibleTabs.some((t) => t.key === key)) goTab(key);
    else navigate(link);
  }, [goTab, navigate, visibleTabs]);

  // The badge and the totals strip read NOC/monitoring/security surfaces. A user
  // who cannot read them must not poll them at all: every interval would 403 and
  // the empty result reads as "the collector is dead" rather than "not yours to
  // see". Skip the request instead of rendering a lie.
  const canReadNoc = readable.has("noc") || readable.has("monitoring");
  const showTotals = ["noc", "monitoring", "security"].every((k) => readable.has(k));
  const sampling = useSamplingHealth(30000, canReadNoc);

  const active = visibleTabs.find((t) => t.key === tab);

  return (
    <div data-testid="noc-center">
      <PageHeader
        title="Operations Center"
        subtitle="NOC, monitoring, diagnostics, incidents, security, and the audit trail in one console — the single entry point for every operational surface. Every number here is only as trustworthy as the flow-sampling pipeline, and that status is pinned below."
        actions={
          <div className="flex items-center gap-2 flex-wrap">
            {canReadNoc && <SamplingBadge payload={sampling.payload} testid="noc-center-sampling" />}
          </div>
        }
      />

      {canReadNoc && (
        <SamplingAlert health={sampling} context="DDoS detection, Sankey and incident triage" />
      )}

      {showTotals && <OperationsTotals sampling={sampling} onGo={goLink} />}

      {visibleTabs.length === 0 ? (
        <div className="rounded-xl border border-slate-200 bg-white p-6 text-sm text-slate-600" data-testid="noc-center-no-tabs">
          Role <b className="uppercase">{role || "unknown"}</b> has no operational surface
          assigned. Ask an administrator for access to NOC, monitoring, SLA, or security.
        </div>
      ) : (
        <>
          <div
            className="flex flex-wrap gap-1 mb-5 bg-white border border-slate-200 rounded-xl p-1 w-fit sticky top-14 z-20"
            data-testid="noc-center-tabs"
          >
            {visibleTabs.map((t) => {
              const Icon = t.icon;
              const isActive = tab === t.key;
              return (
                <button
                  key={t.key}
                  type="button"
                  onClick={() => goTab(t.key)}
                  data-testid={`noc-center-tab-${t.key}`}
                  aria-current={isActive ? "page" : undefined}
                  className={`px-3 py-1.5 rounded-lg text-xs font-semibold flex items-center gap-1.5 transition-colors ${
                    isActive ? "bg-[#0a2350] text-white" : "text-slate-600 hover:text-[#0a2350]"
                  }`}
                >
                  <Icon className="h-3.5 w-3.5" /> {t.label}
                </button>
              );
            })}
          </div>

          {/* Panels unmount when inactive: each of these polls on its own
              interval and several fetch heavy collections, so keeping all seven
              mounted would multiply background load for data nobody is looking
              at. */}
          <div data-testid={`noc-center-panel-${active?.key || ""}`}>
            {tab === "overview"    && <AdminOps embedded onNavigate={goLink} />}
            {tab === "noc"         && <AdminNOC embedded />}
            {tab === "monitoring"  && <AdminMonitoring embedded />}
            {tab === "diagnostics" && <AdminDiagnostics embedded />}
            {tab === "sla"         && <AdminSLA embedded />}
            {tab === "security"    && <AdminSecurity embedded />}
            {tab === "audit"       && <AdminAuditLog embedded />}
          </div>
        </>
      )}
    </div>
  );
};

// ---------------------------------------------------------------------------
// Cross-surface totals
// ---------------------------------------------------------------------------
// Seven surfaces used to report their own counts, so "are we under attack right
// now?" required opening three pages. This row answers that in one shot, and
// each figure jumps to the tab that owns it. A failed fetch renders "—" rather
// than 0: an unreachable API is not the same as "none".
const Metric = ({ label, value, tone = "default", Icon, testid, onGo, hint }) => {
  const toneCls = {
    default: "border-slate-200",
    good: "border-emerald-200 bg-emerald-50/60",
    warn: "border-amber-200 bg-amber-50/60",
    danger: "border-red-200 bg-red-50/60",
  }[tone];
  return (
    <button
      type="button"
      onClick={onGo}
      title={hint}
      data-testid={testid}
      className={`text-left rounded-2xl bg-white border p-4 transition-colors hover:border-[#f5b120] ${toneCls}`}
    >
      <div className="flex items-center justify-between mb-1">
        <div className="text-[10px] font-bold uppercase tracking-widest text-slate-500">{label}</div>
        {Icon && <Icon className="h-4 w-4 text-slate-400" />}
      </div>
      <div className="text-xl font-extrabold text-[#0a2350]">{value}</div>
      {hint && <div className="text-[10px] text-slate-500 mt-0.5 truncate">{hint}</div>}
    </button>
  );
};

const OperationsTotals = ({ sampling, onGo }) => {
  const [totals, setTotals] = useState(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setBusy(true);
    // Promise.allSettled, not Promise.all: one dead endpoint must not blank the
    // whole strip. Each figure is independently null-able.
    const [devices, incidents, alerts, blocks] = await Promise.allSettled([
      api.get("/admin/noc/devices"),
      api.get("/admin/noc/ddos/incidents", { params: { status: "active" } }),
      api.get("/admin/monitoring/graph-alerts", { params: { open_only: true, limit: 200 } }),
      api.get("/admin/security/blocked-ips", { params: { active_only: true } }),
    ]);
    const pick = (r) => (r.status === "fulfilled" ? r.value.data : null);
    setTotals({
      devices: pick(devices),
      incidents: pick(incidents),
      alerts: pick(alerts),
      blocks: pick(blocks),
    });
    setBusy(false);
  }, []);

  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    const t = setInterval(load, 60000);
    return () => clearInterval(t);
  }, [load]);

  if (!totals) return <div className="mb-4"><Loading label="Reading operations totals…" /></div>;

  const devList = Array.isArray(totals.devices) ? totals.devices : null;
  const downCount = devList ? devList.filter((d) => d.status === "down").length : null;
  const upCount = devList ? devList.filter((d) => d.status === "up").length : null;

  // Incidents may come back as an array or a {items|results,total} wrapper
  // depending on the route's shape; normalise both without guessing totals.
  const incRaw = totals.incidents;
  const incList = Array.isArray(incRaw)
    ? incRaw
    : Array.isArray(incRaw?.items) ? incRaw.items
    : Array.isArray(incRaw?.results) ? incRaw.results
    : null;
  const incCount = incList ? (incRaw?.total ?? incList.length) : null;

  const alertList = Array.isArray(totals.alerts) ? totals.alerts : null;
  const blockList = Array.isArray(totals.blocks) ? totals.blocks : null;

  const dash = (v) => (v == null ? "—" : v);

  return (
    <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3 mb-4" data-testid="ops-totals">
      <Metric
        label="Sampling"
        value={sampling.state === "fresh" ? "LIVE" : sampling.state.toUpperCase()}
        tone={sampling.state === "fresh" ? "good" : sampling.state === "down" ? "danger" : "warn"}
        Icon={sampling.state === "fresh" ? Wifi : WifiOff}
        testid="ops-total-sampling"
        hint={sampling.ageS != null ? `last write ${Math.round(sampling.ageS)}s ago` : "no reading yet"}
        onGo={sampling.reload}
      />
      <Metric
        label="Devices up"
        value={upCount == null ? "—" : `${upCount}/${devList.length}`}
        tone={downCount > 0 ? "warn" : "good"}
        Icon={Wifi}
        testid="ops-total-devices"
        hint={downCount == null ? "unavailable" : `${dash(downCount)} down`}
        onGo={() => onGo("/portal/admin/noc")}
      />
      <Metric
        label="DDoS incidents"
        value={dash(incCount)}
        tone={incCount > 0 ? "danger" : "good"}
        Icon={ShieldAlert}
        testid="ops-total-incidents"
        hint={incCount == null ? "unavailable" : incCount > 0 ? "active right now" : "none active"}
        onGo={() => onGo("/portal/admin/noc")}
      />
      <Metric
        label="Open alerts"
        value={alertList == null ? "—" : alertList.length}
        tone={alertList && alertList.length > 0 ? "warn" : "good"}
        Icon={AlertTriangle}
        testid="ops-total-alerts"
        hint={alertList == null ? "unavailable" : "monitoring graph alerts"}
        onGo={() => onGo("/portal/admin/monitoring")}
      />
      <Metric
        label="Blocked IPs"
        value={blockList == null ? "—" : blockList.length}
        tone={blockList && blockList.length > 0 ? "warn" : "default"}
        Icon={Ban}
        testid="ops-total-blocked"
        hint={blockList == null ? "unavailable" : "active auto-blocks"}
        onGo={() => onGo("/portal/admin/security")}
      />
      <Metric
        label="Refresh"
        value={busy ? "…" : "⟳"}
        Icon={RefreshCw}
        testid="ops-total-refresh"
        hint="re-read all four sources"
        onGo={load}
      />
    </div>
  );
};

export default AdminNOCCenter;
