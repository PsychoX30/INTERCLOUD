import React, { useEffect, useState, useCallback, useMemo } from "react";
import { Link } from "react-router-dom";
import {
  ShieldCheck, History, MonitorCheck, Activity, LifeBuoy,
  RefreshCw, AlertTriangle, Wifi, WifiOff, Ban, ShieldAlert,
} from "lucide-react";
import { api } from "../../../portal/api";
import { PageHeader, Card, Loading } from "../ui";
import { SamplingBadge, SamplingAlert, useSamplingHealth } from "./SamplingHealth";
import AdminNOC from "./AdminNOC";
import AdminSecurity from "./AdminSecurity";
import AdminAuditLog from "./AdminAuditLog";
import AdminSLA from "./AdminSLA";
import AdminMonitoring from "./AdminMonitoring";

// All-in-one operations console.
//
// The five surfaces below stayed separate routes because each owns a large,
// self-contained panel set; duplicating them would mean two code paths per
// feature and two places to fix a bug. Instead this page composes the existing
// pages as tabs, and adds the one thing that was missing when they were
// scattered: a single header strip that answers "is the data behind all of
// this even alive right now?".
const TABS = [
  { key: "noc",        label: "NOC Monitor",  icon: MonitorCheck, roles: ["admin", "support"] },
  { key: "monitoring", label: "Monitoring",   icon: Activity,     roles: ["admin", "support"] },
  { key: "security",   label: "Security",     icon: ShieldCheck,  roles: ["admin"] },
  { key: "audit",      label: "Audit Log",    icon: History,      roles: ["admin"] },
  { key: "sla",        label: "SLA & Incidents", icon: LifeBuoy,  roles: ["admin", "support", "finance", "sales"] },
];

const AdminNOCCenter = ({ user: userProp }) => {
  const role = userProp?.role;
  const visibleTabs = useMemo(
    () => TABS.filter((t) => !t.roles || !role || t.roles.includes(role)),
    [role],
  );
  const [tab, setTab] = useState(visibleTabs[0]?.key || "noc");

  // Keep the active tab valid when the role gate shrinks the tab set.
  useEffect(() => {
    if (!visibleTabs.some((t) => t.key === tab)) setTab(visibleTabs[0]?.key || "noc");
  }, [visibleTabs, tab]);

  const sampling = useSamplingHealth(30000);

  return (
    <div data-testid="noc-center">
      <PageHeader
        title="Operations Center"
        subtitle="NOC, monitoring, security, audit trail, and incidents in one console. Every number on this page is only as trustworthy as the flow-sampling pipeline — that status is pinned below."
        actions={
          <div className="flex items-center gap-2 flex-wrap">
            <SamplingBadge payload={sampling.payload} testid="noc-center-sampling" />
          </div>
        }
      />

      <SamplingAlert health={sampling} context="DDoS detection, Sankey and incident triage" />

      <OperationsTotals sampling={sampling} />

      <div
        className="flex flex-wrap gap-1 mb-5 bg-white border border-slate-200 rounded-xl p-1 w-fit sticky top-14 z-20"
        data-testid="noc-center-tabs"
      >
        {visibleTabs.map((t) => {
          const Icon = t.icon;
          const active = tab === t.key;
          return (
            <button
              key={t.key}
              type="button"
              onClick={() => setTab(t.key)}
              data-testid={`noc-center-tab-${t.key}`}
              aria-current={active ? "page" : undefined}
              className={`px-3 py-1.5 rounded-lg text-xs font-semibold flex items-center gap-1.5 transition-colors ${
                active ? "bg-[#0a2350] text-white" : "text-slate-600 hover:text-[#0a2350]"
              }`}
            >
              <Icon className="h-3.5 w-3.5" /> {t.label}
            </button>
          );
        })}
      </div>

      {/* Panels unmount when inactive: each of these polls on its own interval
          and several fetch heavy collections, so keeping all five mounted would
          multiply background load by five for data nobody is looking at. */}
      <div data-testid={`noc-center-panel-${tab}`}>
        {tab === "noc"        && <AdminNOC />}
        {tab === "monitoring" && <AdminMonitoring />}
        {tab === "security"   && <AdminSecurity />}
        {tab === "audit"      && <AdminAuditLog />}
        {tab === "sla"        && <AdminSLA />}
      </div>
    </div>
  );
};

// ---------------------------------------------------------------------------
// Cross-surface totals
// ---------------------------------------------------------------------------
// Five separate pages each reported their own counts, so "are we under attack
// right now?" required opening three of them. This row answers that in one
// shot, and each figure links to the surface that owns it. A failed fetch
// renders "—" rather than 0: an unreachable API is not the same as "none".
const Metric = ({ label, value, tone = "default", Icon, testid, to, onGo, hint }) => {
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

const OperationsTotals = ({ sampling }) => {
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
      />
      <Metric
        label="DDoS incidents"
        value={dash(incCount)}
        tone={incCount > 0 ? "danger" : "good"}
        Icon={ShieldAlert}
        testid="ops-total-incidents"
        hint={incCount == null ? "unavailable" : incCount > 0 ? "active right now" : "none active"}
      />
      <Metric
        label="Open alerts"
        value={alertList == null ? "—" : alertList.length}
        tone={alertList && alertList.length > 0 ? "warn" : "good"}
        Icon={AlertTriangle}
        testid="ops-total-alerts"
        hint={alertList == null ? "unavailable" : "monitoring graph alerts"}
      />
      <Metric
        label="Blocked IPs"
        value={blockList == null ? "—" : blockList.length}
        tone={blockList && blockList.length > 0 ? "warn" : "default"}
        Icon={Ban}
        testid="ops-total-blocked"
        hint={blockList == null ? "unavailable" : "active auto-blocks"}
      />
      <Metric
        label="Refresh"
        value={busy ? "…" : "⟳"}
        Icon={RefreshCw}
        testid="ops-total-refresh"
        hint="re-read all five sources"
        onGo={load}
      />
    </div>
  );
};

export default AdminNOCCenter;
