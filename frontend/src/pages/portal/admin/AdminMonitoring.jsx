import React, { useCallback, useEffect, useMemo, useState } from "react";
import { Activity, Edit, Loader2, Map as MapIcon, Network, PlayCircle, Plus, RefreshCw, Trash2, X, BarChart3, Download, Search, ChevronDown, ChevronRight, Copy, Check, ChevronUp } from "lucide-react";
import { ResponsiveContainer, LineChart, Line, XAxis, YAxis, Tooltip, CartesianGrid } from "recharts";
import { ReactFlow, Background, Controls, MiniMap, useNodesState, useEdgesState, Handle, Position, MarkerType } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { useAuth } from "../../../portal/AuthContext";
import { api } from "../../../portal/api";
import { Card, EmptyState, Loading, PageHeader, StatusBadge, btnDanger, btnPrimary, btnSecondary, inputClass, labelClass } from "../ui";

const stamp = (value) => value ? new Date(value).toLocaleString() : "-";
const PING_EMPTY = { name: "", target: "", enabled: true, interval_seconds: 300 };
const GRAPH_EMPTY = {
  name: "",
  target: "",
  type: "snmp_traffic_pair",
  snmp_oid_in: "",
  snmp_oid_out: "",
  snmp_community: "public",
  snmp_port: 161,
  snmp_version: "2c",
  interval_seconds: 60,
  enabled: true,
  client_id: "",
  unit: "",
  display_name: "",
  visible_roles: ["admin", "support"],
};

const isTrafficType = (t) => t === "snmp_traffic_in" || t === "snmp_traffic_out" || t === "snmp_traffic_pair";

// ── Adaptive unit formatters ───────────────────────────────────
// Auto-scale bps → kbps → Mbps → Gbps → Tbps (1000-based prefix)
const fmtBps = (v) => {
  if (v == null || isNaN(v)) return "-";
  const units = ["bps", "kbps", "Mbps", "Gbps", "Tbps"];
  const sign = v < 0 ? "-" : "";
  let abs = Math.abs(v);
  let i = 0;
  while (abs >= 1000 && i < units.length - 1) { abs /= 1000; i++; }
  return `${sign}${abs.toFixed(i > 0 ? 2 : 0)} ${units[i]}`;
};

// Generic value formatter for non-traffic metrics (CPU %, memory, ms, etc.)
const fmtValue = (v, unit) => {
  if (v == null || isNaN(v)) return "-";
  const u = (unit || "").toLowerCase();
  if (u === "bps") return fmtBps(v);
  if (u === "%") return `${Number(v).toFixed(1)}%`;
  if (u === "ms") return `${Number(v).toFixed(2)} ms`;
  if (u === "kb" || u === "mb" || u === "gb") return `${Number(v).toFixed(2)} ${u.toUpperCase()}`;
  if (u === "bytes") return fmtBps(v);  // bytes per second equivalent
  return `${Number(v).toFixed(2)} ${unit || ""}`.trim();
};

// Pick the right formatter based on graph type/unit
const valueFormatter = (graph) => {
  if (!graph) return fmtValue;
  if (isTrafficType(graph.type)) return fmtBps;
  return (v) => fmtValue(v, graph.unit);
};

// ── Tab button ──────────────────────────────────────────────────
const TabBtn = ({ active, onClick, icon: Icon, children, testid }) => (
  <button
    onClick={onClick}
    data-testid={testid}
    className={`px-4 h-11 -mb-px border-b-2 text-sm font-bold inline-flex items-center gap-2 whitespace-nowrap transition-colors ${
      active ? "border-[#f5b120] text-[#0a2350]" : "border-transparent text-slate-500 hover:text-[#0a2350]"
    }`}
  >
    <Icon className="h-4 w-4" /> {children}
  </button>
);



const CopyId = ({ id }) => {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try { await navigator.clipboard.writeText(id); setCopied(true); setTimeout(() => setCopied(false), 1500); }
    catch (_) { /* clipboard unavailable */ }
  };
  return <button type="button" onClick={copy} className="inline-flex items-center gap-1 text-[11px] font-mono text-slate-400 hover:text-[#0a2350]" data-testid="graph-id-copy" title="Copy graph ID">id: {id} {copied ? <Check className="h-3 w-3 text-green-600" /> : <Copy className="h-3 w-3" />}</button>;
};

const trafficBaseName = (g) => (g.display_name || g.name || "").replace(/\s*(in|out)\s*$/i, "").trim().toLowerCase();

// Recharts Y-axis tick formatter: compact form without unit suffix repetition.
const yTickFormatter = (unit) => (v) => {
  if (v == null || Number.isNaN(v)) return "";
  const u = (unit || "").toLowerCase();
  if (u === "bps") return fmtBps(v);
  if (u === "%") return `${Math.round(Number(v))}%`;
  if (u === "ms") return `${Math.round(Number(v))}`;
  return Number(v).toFixed(0);
};

// Recharts Tooltip formatter: [formattedValue, seriesLabel]
const tooltipFormatter = (unit) => (value) => [fmtValue(value, unit), ""];

// Compute aggregate stats from a merged IN/OUT traffic series.
// Returns peak and average rates in bps; volume (bytes) is omitted because
// summing bps values without per-sample Δt is meaningless.
const trafficStats = (merged) => {
  const nums = (arr) => arr.filter(v => v != null && !Number.isNaN(v)).map(Number);
  const inVals = nums(merged.map(d => d.in));
  const outVals = nums(merged.map(d => d.out));
  const avg = (arr) => (arr.length ? arr.reduce((a, b) => a + b, 0) / arr.length : null);
  const max = (arr) => (arr.length ? Math.max(...arr) : null);
  return {
    maxIn: max(inVals),
    maxOut: max(outVals),
    avgIn: avg(inVals),
    avgOut: avg(outVals),
  };
};

const StatCard = ({ label, value, color }) => (
  <div className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-center">
    <div className={`text-sm font-bold ${color || "text-[#0a2350]"}`}>{value}</div>
    <div className="text-[10px] uppercase tracking-wider text-slate-500">{label}</div>
  </div>
);

const formatGraphTick = (timestamp, spanMs) => {
  if (!timestamp) return "";
  const d = new Date(timestamp);
  if (spanMs <= 2 * 86400000) return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  if (spanMs <= 14 * 86400000) return d.toLocaleDateString([], { day: "2-digit", month: "short" });
  if (spanMs <= 180 * 86400000) return d.toLocaleDateString([], { day: "2-digit", month: "short" });
  return d.toLocaleDateString([], { month: "short", year: "numeric" });
};

const graphSpanMs = (data) => {
  const points = (data || []).map(s => new Date(s.at).getTime()).filter(Number.isFinite);
  return points.length > 1 ? Math.max(...points) - Math.min(...points) : 0;
};

const chartTickFormatter = (spanMs) => (value) => formatGraphTick(value, spanMs);

// ── Main wrapper ─────────────────────────────────────────────────
const AdminMonitoring = () => {
  const { user } = useAuth() || {};
  const isAdmin = user?.role === "admin";
  const [tab, setTab] = useState("ping");

  return (
    <div data-testid="monitoring-page">
      <PageHeader
        title="Monitoring"
        subtitle="Unified monitoring: ping checks, SNMP/MRTG graphs, and network map."
      />
      <div className="flex items-center gap-2 mb-4 border-b border-slate-200 overflow-x-auto">
        <TabBtn active={tab === "ping"} onClick={() => setTab("ping")} icon={Activity} testid="tab-ping">Ping Checks</TabBtn>
        <TabBtn active={tab === "graphs"} onClick={() => setTab("graphs")} icon={BarChart3} testid="tab-graphs">SNMP Graphs</TabBtn>
        <TabBtn active={tab === "map"} onClick={() => setTab("map")} icon={MapIcon} testid="tab-map">Network Map</TabBtn>
      </div>
      {tab === "ping" && <PingTab isAdmin={isAdmin} />}
      {tab === "graphs" && <GraphsTab isAdmin={isAdmin} />}
      {tab === "map" && <NetworkMapTab isAdmin={isAdmin} />}
    </div>
  );
};

// ═════════════════════════════════════════════════════════════════
// Ping Check Tab
// ═════════════════════════════════════════════════════════════════
const PingTab = ({ isAdmin }) => {
  const [checks, setChecks] = useState(null);
  const [selectedId, setSelectedId] = useState("");
  const [history, setHistory] = useState(null);
  const [editing, setEditing] = useState(null);
  const [busyId, setBusyId] = useState("");
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");

  const loadChecks = useCallback(async () => {
    try { setError(""); const r = await api.get("/admin/monitoring/checks"); setChecks(r.data || []); }
    catch (e) { setError(e?.response?.data?.detail || "Failed to load"); setChecks([]); }
  }, []);

  const loadHistory = useCallback(async (id) => {
    if (!id) return;
    try { setError(""); const r = await api.get(`/admin/monitoring/checks/${id}/history`, { params: { limit: 200 } }); setSelectedId(id); setHistory(r.data); }
    catch (e) { setError(e?.response?.data?.detail || "Failed to load history"); }
  }, []);

  useEffect(() => { loadChecks(); }, [loadChecks]);

  const save = async (e) => {
    e.preventDefault();
    const payload = { name: editing.name, target: editing.target, enabled: !!editing.enabled, interval_seconds: Number(editing.interval_seconds) };
    try {
      if (editing.id) await api.put(`/admin/monitoring/checks/${editing.id}`, payload);
      else await api.post("/admin/monitoring/checks", payload);
      setEditing(null); await loadChecks();
    } catch (e) { setError(e?.response?.data?.detail || "Failed to save"); }
  };

  const remove = async (id) => {
    if (!window.confirm("Delete this check?")) return;
    try { await api.delete(`/admin/monitoring/checks/${id}`); if (selectedId === id) { setSelectedId(""); setHistory(null); } await loadChecks(); }
    catch (e) { setError(e?.response?.data?.detail || "Failed to delete"); }
  };

  const run = async (id) => {
    setBusyId(id);
    try {
      setError(""); setInfo("");
      const r = await api.post(`/admin/monitoring/checks/${id}/run`);
      // Backend returns { skipped: true, owner: "..." } if the scheduled sweep
      // already holds the per-check lease; that is not a probe failure.
      if (r.data && r.data.skipped) {
        setInfo("Probe skipped — the scheduled sweep already holds the lease for this check. Try again in a moment.");
      } else {
        setInfo("Probe completed — history refreshed below.");
      }
      await Promise.all([loadChecks(), loadHistory(id)]);
    }
    catch (e) { setError(e?.response?.data?.detail || "Probe failed"); }
    finally { setBusyId(""); }
  };

  if (checks === null) return <Loading label="Loading checks…" />;

  return (
    <div>
      <div className="flex items-center gap-2 mb-4">
        <button className={btnSecondary} onClick={loadChecks} data-testid="monitoring-refresh"><RefreshCw className="h-4 w-4" /> Refresh</button>
        {isAdmin && <button className={btnPrimary} onClick={() => setEditing({ ...PING_EMPTY })} data-testid="monitoring-add"><Plus className="h-4 w-4" /> Add check</button>}
      </div>
      {error && <div className="mb-4 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div>}
      {info && <div className="mb-4 rounded-xl border border-blue-200 bg-blue-50 px-4 py-3 text-sm text-blue-700">{info}</div>}
      <Card className="overflow-hidden">
        {checks.length === 0 ? <EmptyState title="No checks" body={isAdmin ? "Add a public IP or hostname to begin polling." : "An admin has not configured any checks."} /> : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 text-[11px] uppercase tracking-widest text-slate-500">
                <tr><th className="px-4 py-3 text-left">Name</th><th className="px-4 py-3 text-left">Target</th><th className="px-4 py-3 text-left">Interval</th><th className="px-4 py-3 text-left">Enabled</th><th className="px-4 py-3 text-right">Actions</th></tr>
              </thead>
              <tbody>
                {checks.map(c => (
                  <tr key={c.id} className="border-t border-slate-100" data-testid={`monitoring-check-${c.id}`}>
                    <td className="px-4 py-3 font-semibold text-[#0a2350]">{c.name}</td>
                    <td className="px-4 py-3 font-mono text-xs">{c.target}</td>
                    <td className="px-4 py-3">{c.interval_seconds}s</td>
                    <td className="px-4 py-3"><StatusBadge status={c.enabled ? "enabled" : "disabled"} /></td>
                    <td className="px-4 py-3"><div className="flex justify-end gap-2">
                      <button className={btnSecondary} onClick={() => loadHistory(c.id)}><Activity className="h-4 w-4" /> History</button>
                      {isAdmin && (<>
                        <button className={btnSecondary} onClick={() => run(c.id)} disabled={busyId === c.id}><PlayCircle className="h-4 w-4" /> Run</button>
                        <button className={btnSecondary} onClick={() => setEditing({ ...c })}><Edit className="h-4 w-4" /></button>
                        <button className={btnDanger} onClick={() => remove(c.id)}><Trash2 className="h-4 w-4" /></button>
                      </>)}
                    </div></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
      {history && <HistoryPanel history={history} onClose={() => { setHistory(null); setSelectedId(""); }} />}
      {editing && <PingForm value={editing} onChange={setEditing} onSubmit={save} onClose={() => setEditing(null)} />}
    </div>
  );
};

const HistoryPanel = ({ history, onClose }) => {
  const [expanded, setExpanded] = useState(true);
  const samples = [...(history.samples || [])].reverse().map(s => ({ ...s, label: s.at ? new Date(s.at).toLocaleTimeString() : "-" }));

  // Latency + loss summary over the returned window (nulls excluded).
  const pingStats = useMemo(() => {
    const rtts = samples.map(s => s.rtt_ms).filter(v => v != null && !Number.isNaN(v)).map(Number);
    const losses = samples.map(s => s.loss).filter(v => v != null && !Number.isNaN(v)).map(Number);
    const maxes = samples.map(s => s.rtt_max_ms).filter(v => v != null && !Number.isNaN(v)).map(Number);
    const avg = (arr) => (arr.length ? arr.reduce((a, b) => a + b, 0) / arr.length : null);
    return {
      avgRtt: avg(rtts),
      maxRtt: maxes.length ? Math.max(...maxes) : (rtts.length ? Math.max(...rtts) : null),
      avgLoss: avg(losses),
      up: samples.length ? samples.filter(s => s.up).length : 0,
      total: samples.length,
    };
  }, [samples]);

  return (
    <Foldable
      title={`${history.check?.name || "Check"} history`}
      subtitle={`Last probe: ${stamp(history.state?.last_at)} · RTT: ${history.state?.last_rtt_ms ?? "-"} ms`}
      expanded={expanded}
      onToggle={setExpanded}
      badge={<StatusBadge status={history.state?.status || "unknown"} />}
    >
      <div className="flex justify-end mb-2">
        <button onClick={onClose} aria-label="Close"><X className="h-5 w-5" /></button>
      </div>
      {samples.length ? <div className="h-64"><ResponsiveContainer width="100%" height="100%"><LineChart data={samples}><CartesianGrid strokeDasharray="3 3" /><XAxis dataKey="label" minTickGap={24} /><YAxis tickFormatter={yTickFormatter("ms")} /><Tooltip formatter={tooltipFormatter("ms")} /><Line type="monotone" dataKey="rtt_max_ms" name="Max" stroke="#f5b120" strokeWidth={1} dot={false} connectNulls={false} /><Line type="monotone" dataKey="rtt_ms" name="Avg" stroke="#0a2350" strokeWidth={2} connectNulls={false} /></LineChart></ResponsiveContainer></div> : <EmptyState title="No samples yet" body="Run the check or wait for its next scheduled interval." />}
      {samples.length > 0 && (
        <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-4">
          <StatCard label="Avg RTT" value={fmtValue(pingStats.avgRtt, "ms")} />
          <StatCard label="Max RTT" value={fmtValue(pingStats.maxRtt, "ms")} color="text-amber-500" />
          <StatCard label="Avg Loss" value={pingStats.avgLoss == null ? "-" : `${pingStats.avgLoss.toFixed(1)}%`} color={pingStats.avgLoss > 0 ? "text-red-600" : "text-green-600"} />
          <StatCard label="Up / Total" value={`${pingStats.up} / ${pingStats.total}`} color={pingStats.up === pingStats.total ? "text-green-600" : "text-red-600"} />
        </div>
      )}
      {(history.events || []).length > 0 && <div className="mt-5"><div className={labelClass}>Transitions</div><div className="mt-2 space-y-2">{history.events.map(ev => <div key={ev.id} className="rounded-lg bg-slate-50 px-3 py-2 text-xs"><span className="font-mono text-slate-500">{stamp(ev.at)}</span> · {ev.from || "unknown"} → <strong>{ev.to}</strong></div>)}</div></div>}
    </Foldable>
  );
};

const PingForm = ({ value, onChange, onSubmit, onClose }) => {
  const set = (k, v) => onChange({ ...value, [k]: v });
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={onClose}>
      <form className="w-full max-w-lg space-y-4 rounded-2xl bg-white p-6" onClick={e => e.stopPropagation()} onSubmit={onSubmit} data-testid="monitoring-form">
        <h2 className="text-lg font-extrabold text-[#0a2350]">{value.id ? "Edit check" : "Add check"}</h2>
        <label className="block"><span className={labelClass}>Name</span><input required maxLength={120} className={inputClass} value={value.name} onChange={e => set("name", e.target.value)} /></label>
        <label className="block"><span className={labelClass}>Public IP / hostname</span><input required maxLength={253} className={inputClass} value={value.target} onChange={e => set("target", e.target.value)} /></label>
        <label className="block"><span className={labelClass}>Interval (10–3600s)</span><input required type="number" min="10" max="3600" className={inputClass} value={value.interval_seconds} onChange={e => set("interval_seconds", e.target.value)} /></label>
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={!!value.enabled} onChange={e => set("enabled", e.target.checked)} /> Enabled</label>
        <div className="flex justify-end gap-2"><button type="button" className={btnSecondary} onClick={onClose}>Cancel</button><button type="submit" className={btnPrimary}>Save</button></div>
      </form>
    </div>
  );
};

// ═════════════════════════════════════════════════════════════════
// SNMP Graphs Tab
// ═════════════════════════════════════════════════════════════════
const GRAPH_TYPES = [
  { value: "snmp_traffic_pair", label: "SNMP Traffic (IN+OUT)" },
  { value: "snmp_cpu", label: "SNMP CPU" },
  { value: "snmp_memory", label: "SNMP Memory" },
  { value: "snmp_uptime", label: "SNMP Uptime" },
  { value: "ping", label: "Ping RTT" },
];

// Legacy single-direction types used by old docs and discovery; kept in the
// set so existing graphs validate on the backend but not exposed in the form.
const TRAFFIC_PAIR_TYPES = new Set(["snmp_traffic_in", "snmp_traffic_out"]);

const GraphsTab = ({ isAdmin }) => {
  const [graphs, setGraphs] = useState(null);
  const [expandedId, setExpandedId] = useState(null);
  const [graphData, setGraphData] = useState(null);
  const [pairData, setPairData] = useState(null);
  const [editing, setEditing] = useState(null);
  const [busyId, setBusyId] = useState("");
  const [error, setError] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [autoRefresh, setAutoRefresh] = useState(true);

  // Range presets: set from/to for quick time range selection.
  // Also immediately reload the open graph so the chart reflects the new range
  // (previously the preset only set state; the chart never re-queried).
  const setRange = (hours) => {
    const t = new Date();
    const f = new Date(t.getTime() - hours * 3600 * 1000).toISOString();
    const toIso = t.toISOString();
    setFrom(f);
    setTo(toIso);
    if (expandedId) {
      loadData(expandedId, { from: f, to: toIso });
      const g = (graphs || []).find(x => x.id === expandedId);
      const pair = g ? findTrafficPair(graphs || [], g) : null;
      if (pair) loadPairData(pair.id, { from: f, to: toIso });
    }
  };
  const RANGES = [
    { label: "1H", hours: 1 },
    { label: "1D", hours: 24 },
    { label: "1W", hours: 24 * 7 },
    { label: "1M", hours: 24 * 30 },
    { label: "1Y", hours: 24 * 365 },
  ];

  const loadGraphs = useCallback(async () => {
    try { setError(""); const r = await api.get("/admin/monitoring/graphs"); setGraphs(r.data || []); }
    catch (e) { setError(e?.response?.data?.detail || "Failed to load graphs"); setGraphs([]); }
  }, []);

  useEffect(() => { loadGraphs(); }, [loadGraphs]);

  // Legacy IN/OUT documents are one logical traffic graph in the operator UI.
  const graphRows = useMemo(() => groupGraphRows(graphs || []), [graphs]);

  const loadData = useCallback(async (id, opts = {}) => {
    if (!id) return;
    const f = opts.from || from || new Date(Date.now() - 24 * 3600 * 1000).toISOString();
    const t = opts.to || to || new Date().toISOString();
    try {
      setError("");
      const r = await api.get(`/admin/monitoring/graphs/${id}/data`, { params: { from: f, to: t, resolution: "auto" } });
      setExpandedId(id);
      setGraphData(r.data);
      return r.data;
    } catch (e) { setError(e?.response?.data?.detail || "Failed to load graph data"); return null; }
  }, [from, to]);

  const loadPairData = useCallback(async (pairId, opts = {}) => {
    if (!pairId) return;
    const f = opts.from || from || new Date(Date.now() - 24 * 3600 * 1000).toISOString();
    const t = opts.to || to || new Date().toISOString();
    try {
      const pr = await api.get(`/admin/monitoring/graphs/${pairId}/data`, { params: { from: f, to: t, resolution: "auto" } });
      setPairData(pr.data);
    } catch (e) { setPairData(null); }
  }, [from, to]);

  const refreshData = useCallback(async () => {
    if (!expandedId) return;
    const data = await loadData(expandedId);
    if (data && graphs) {
      const g = graphs.find(x => x.id === expandedId);
      const pair = g ? findTrafficPair(graphs, g) : null;
      if (pair) await loadPairData(pair.id);
      else setPairData(null);
    }
  }, [expandedId, graphs, loadData, loadPairData]);

  // Load sibling pair data whenever a graph is selected for viewing.
  useEffect(() => {
    if (!expandedId || !graphs) { setPairData(null); return; }
    const g = graphs.find(x => x.id === expandedId);
    const pair = g ? findTrafficPair(graphs, g) : null;
    if (!pair) { setPairData(null); return; }
    loadPairData(pair.id);
  }, [expandedId, graphs, loadPairData]);

  // Auto-refresh the open graph panel periodically so traffic feels realtime.
  useEffect(() => {
    if (!autoRefresh || !expandedId) return undefined;
    const timer = setInterval(() => { refreshData(); }, 30000);
    return () => clearInterval(timer);
  }, [autoRefresh, expandedId, refreshData]);

  const save = async (e) => {
    e.preventDefault();
    const payload = { ...editing };
    const pairMemberIds = payload.__pairMemberIds; // {in, out} when editing an existing pair
    delete payload.id;
    delete payload.__pairMemberIds;
    try {
      if (payload.type === "snmp_traffic_pair") {
        // Creating (or re-saving) a traffic pair: two legacy documents share
        // the same target/SNMP config but each carries its own OID.
        const common = {
          target: payload.target,
          snmp_community: payload.snmp_community || "public",
          snmp_port: Number(payload.snmp_port) || 161,
          snmp_version: payload.snmp_version || "2c",
          snmp_user: payload.snmp_user || "",
          snmp_auth_protocol: payload.snmp_auth_protocol || "",
          snmp_auth_key: payload.snmp_auth_key || "",
          snmp_priv_protocol: payload.snmp_priv_protocol || "",
          snmp_priv_key: payload.snmp_priv_key || "",
          interval_seconds: Number(payload.interval_seconds) || 60,
          enabled: payload.enabled !== false,
          client_id: payload.client_id || "",
          visible_roles: payload.visible_roles || ["admin", "support"],
        };
        const baseName = payload.name || payload.target;
        const baseDisplay = payload.display_name || baseName;
        if (pairMemberIds?.in && pairMemberIds?.out) {
          // Editing an existing pair: update both documents individually.
          await Promise.all([
            api.put(`/admin/monitoring/graphs/${pairMemberIds.in}`, {
              ...common, name: `${baseName} In`, display_name: `${baseDisplay} In`,
              snmp_oid: payload.snmp_oid_in, unit: payload.unit || "",
            }),
            api.put(`/admin/monitoring/graphs/${pairMemberIds.out}`, {
              ...common, name: `${baseName} Out`, display_name: `${baseDisplay} Out`,
              snmp_oid: payload.snmp_oid_out, unit: payload.unit || "",
            }),
          ]);
        } else {
          await api.post("/admin/monitoring/graphs/bulk", {
            ...common,
            sensors: [
              { oid: payload.snmp_oid_in, name: `${baseName} In`, display_name: `${baseDisplay} In`, type: "snmp_traffic_in", unit: payload.unit || "" },
              { oid: payload.snmp_oid_out, name: `${baseName} Out`, display_name: `${baseDisplay} Out`, type: "snmp_traffic_out", unit: payload.unit || "" },
            ],
          });
        }
      } else if (editing.id) {
        await api.put(`/admin/monitoring/graphs/${editing.id}`, payload);
      } else {
        await api.post("/admin/monitoring/graphs", payload);
      }
      setEditing(null); await loadGraphs();
    } catch (e) { setError(e?.response?.data?.detail || "Failed to save"); }
  };

  const remove = async (ids) => {
    const idList = Array.isArray(ids) ? ids : [ids];
    if (!window.confirm(idList.length > 1 ? "Delete this traffic graph (IN+OUT)?" : "Delete this graph?")) return;
    try {
      await Promise.all(idList.map(id => api.delete(`/admin/monitoring/graphs/${id}`)));
      if (idList.includes(expandedId)) { setExpandedId(null); setGraphData(null); setPairData(null); }
      await loadGraphs();
    } catch (e) { setError(e?.response?.data?.detail || "Failed to delete"); }
  };

  const run = async (ids) => {
    const idList = Array.isArray(ids) ? ids : [ids];
    const busyKey = idList[0];
    setBusyId(busyKey);
    try {
      setError("");
      const results = await Promise.all(idList.map(id => api.post(`/admin/monitoring/graphs/${id}/run`)));
      await loadGraphs();
      if (idList.includes(expandedId)) await refreshData();
      if (results.some(r => r.data && r.data.baseline)) setError("Probe OK — baseline counter captured. Next poll will show the rate.");
    } catch (e) { setError("Probe failed"); }
    finally { setBusyId(""); }
  };

  // Convert a grouped pair row back into the GraphForm's pair-editing shape.
  const pairToFormValue = (row) => ({
    ...GRAPH_EMPTY,
    id: row.id,
    name: row.name,
    display_name: row.name,
    target: row.target,
    type: "snmp_traffic_pair",
    snmp_oid_in: row.inGraph?.snmp_oid || "",
    snmp_oid_out: row.outGraph?.snmp_oid || "",
    snmp_community: row.inGraph?.snmp_community || row.outGraph?.snmp_community || "public",
    snmp_port: row.inGraph?.snmp_port || row.outGraph?.snmp_port || 161,
    snmp_version: row.inGraph?.snmp_version || row.outGraph?.snmp_version || "2c",
    interval_seconds: row.interval_seconds,
    enabled: row.inGraph?.enabled !== false,
    client_id: row.client_id || "",
    unit: row.inGraph?.unit || row.outGraph?.unit || "",
    visible_roles: row.visible_roles || ["admin", "support"],
    __pairMemberIds: { in: row.inGraph?.id, out: row.outGraph?.id },
  });

  const exportGraph = async (id, fmt) => {
    const f = from || new Date(Date.now() - 7 * 86400 * 1000).toISOString();
    const t = to || new Date().toISOString();
    try {
      const r = await api.get(`/admin/monitoring/graphs/${id}/export`, { params: { from: f, to: t, fmt }, responseType: "blob" });
      const url = window.URL.createObjectURL(new Blob([r.data]));
      const a = document.createElement("a"); a.href = url;
      a.download = `graph-${id}.${fmt}`; a.click(); window.URL.revokeObjectURL(url);
    } catch (e) {
      let detail = "";
      const data = e?.response?.data;
      if (data && typeof data.text === "function") {
        try { detail = (JSON.parse(await data.text()) || {}).detail || ""; }
        catch (_) { /* not a JSON error body */ }
      } else if (data?.detail) {
        detail = data.detail;
      }
      setError(detail || "Export failed");
    }
  };

  if (graphs === null) return <Loading label="Loading graphs…" />;

  return (
    <div>
      <div className="flex items-center gap-2 mb-4 flex-wrap">
        <button className={btnSecondary} onClick={loadGraphs}><RefreshCw className="h-4 w-4" /> Refresh</button>
        {isAdmin && <button className={btnPrimary} onClick={() => setEditing({ ...GRAPH_EMPTY })}><Plus className="h-4 w-4" /> Add graph</button>}
        <div className="flex items-center gap-1 ml-2 rounded-full bg-slate-100 p-1 text-xs" data-testid="range-selector">
          {RANGES.map(r => (
            <button key={r.label} type="button"
              className="px-2.5 h-7 rounded-full font-semibold text-slate-600 hover:bg-white hover:text-[#0a2350]"
              onClick={() => setRange(r.hours)}
              data-testid={`range-${r.label}`}
            >{r.label}</button>
          ))}
        </div>
        <label className="inline-flex items-center gap-2 text-sm text-slate-600 ml-auto">
          <input type="checkbox" checked={autoRefresh} onChange={e => setAutoRefresh(e.target.checked)} /> Auto-refresh (30s)
        </label>
      </div>
      {error && <div className="mb-4 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div>}

      <Card className="overflow-hidden mb-5">
        {graphs.length === 0 ? <EmptyState title="No graphs" body={isAdmin ? "Add an SNMP or ping graph to begin collecting data." : "An admin has not configured any graphs."} /> : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 text-[11px] uppercase tracking-widest text-slate-500">
                <tr><th className="px-4 py-3 text-left">Name</th><th className="px-4 py-3 text-left">Graph ID</th><th className="px-4 py-3 text-left">Target</th><th className="px-4 py-3 text-left">Type</th><th className="px-4 py-3 text-left">Interval</th><th className="px-4 py-3 text-left">Client</th><th className="px-4 py-3 text-left">Visible to</th><th className="px-4 py-3 text-right">Actions</th></tr>
              </thead>
              <tbody>
                {graphRows.map(row => {
                  const isPair = row.kind === "pair";
                  const g = isPair ? (row.inGraph || row.outGraph) : row.graph;
                  const rowName = isPair ? row.name : (g.display_name || g.name);
                  const rowType = isPair ? "snmp_traffic" : g.type;
                  const memberIds = isPair
                    ? [row.inGraph?.id, row.outGraph?.id].filter(Boolean)
                    : [g.id];
                  const busy = memberIds.some(id => busyId === id);
                  return (
                    <React.Fragment key={row.id}>
                      <tr className="border-t border-slate-100">
                        <td className="px-4 py-3 font-semibold text-[#0a2350]">
                          {rowName}
                          {isPair && <span className="ml-2 rounded bg-slate-100 px-1.5 py-0.5 text-[10px] font-bold text-slate-500">IN+OUT</span>}
                        </td>
                        <td className="px-4 py-3 font-mono text-xs text-slate-500"><CopyButton text={row.id} label="copy" /> <span className="ml-1">{row.id.slice(0, 10)}…</span></td>
                        <td className="px-4 py-3 font-mono text-xs">{isPair ? row.target : g.target}</td>
                        <td className="px-4 py-3"><StatusBadge status={rowType} /></td>
                        <td className="px-4 py-3">{(isPair ? row.interval_seconds : g.interval_seconds)}s</td>
                        <td className="px-4 py-3">{(isPair ? row.client_id : g.client_id) ? <span className="text-green-700">assigned</span> : <span className="text-slate-400">internal</span>}</td>
                        <td className="px-4 py-3 text-xs text-slate-500">{((isPair ? row.visible_roles : g.visible_roles) || []).join(", ")}</td>
                        <td className="px-4 py-3"><div className="flex justify-end gap-2">
                          <button className={btnSecondary} onClick={() => {
                            if (expandedId === row.id) { setExpandedId(null); setGraphData(null); setPairData(null); }
                            else { setExpandedId(row.id); loadData(row.id); }
                          }}>
                            {expandedId === row.id ? <ChevronUp className="h-4 w-4" /> : <BarChart3 className="h-4 w-4" />} View
                          </button>
                          {isAdmin && (<>
                            <button className={btnSecondary} onClick={() => run(memberIds)} disabled={busy}>{busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <PlayCircle className="h-4 w-4" />} Probe</button>
                            <button className={btnSecondary} onClick={() => exportGraph(row.id, "pdf")}><Download className="h-4 w-4" /> PDF</button>
                            <button className={btnSecondary} onClick={() => setEditing(isPair ? pairToFormValue(row) : { ...g })}><Edit className="h-4 w-4" /></button>
                            <button className={btnDanger} onClick={() => remove(memberIds)}><Trash2 className="h-4 w-4" /></button>
                          </>)}
                        </div></td>
                      </tr>
                      {expandedId === row.id && (
                        <tr className="bg-slate-50">
                          <td colSpan={8} className="p-0">
                            <div className="p-4 border-t border-slate-200">
                              {graphData ? <GraphDataPanel
                                graphData={graphData}
                                pairData={pairData}
                                graphs={graphs || []}
                                from={from}
                                to={to}
                                onClose={() => { setExpandedId(null); setGraphData(null); setPairData(null); }}
                              /> : <Loading label="Loading graph data…" />}
                            </div>
                          </td>
                        </tr>
                      )}
                    </React.Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>
      {editing && (
        <GraphForm
          value={editing}
          onChange={setEditing}
          onSubmit={save}
          onClose={() => setEditing(null)}
          onAfterSave={loadGraphs}
        />
      )}
    </div>
  );
};

const GraphDataPanel = ({ graphData, pairData, graphs, from, to, onClose }) => {
  const [expanded, setExpanded] = useState(true);
  const [trafficView, setTrafficView] = useState("both");
  const graph = (graphs || []).find(g => g.id === graphData.graph_id);
  const isTraffic = graph && (graph.type === "snmp_traffic_in" || graph.type === "snmp_traffic_out");
  const pair = isTraffic ? findTrafficPair(graphs || [], graph) : null;

  const samples = (graphData.data || []).map(s => ({ ...s, at: s.at, ts: s.at ? new Date(s.at).getTime() : null }));
  const pairSamples = (pairData?.data || []).map(s => ({ ...s, at: s.at, ts: s.at ? new Date(s.at).getTime() : null }));
  const title = graph?.display_name || graph?.name || `Graph ${graphData.graph_id}`;

  // The X-axis spans the full user-selected range (from/to), not just the
  // points present, so a 1W view with only 3 days of data still shows the
  // whole week with empty buckets rendered as gaps.  The span of that range
  // drives the tick formatter: short ranges show time-of-day, longer ranges
  // roll up to day/month/year to match Cacti/MRTG behaviour.
  const fromMs = from ? new Date(from).getTime() : null;
  const toMs = to ? new Date(to).getTime() : null;
  const rangeSpan = fromMs && toMs && toMs > fromMs ? toMs - fromMs : Math.max(graphSpanMs(samples), graphSpanMs(pairSamples));
  const xTickFormatter = useMemo(() => chartTickFormatter(rangeSpan), [rangeSpan]);
  const xDataKey = "ts";
  const xDomain = (fromMs && toMs && toMs > fromMs) ? [fromMs, toMs] : undefined;

  // Merge timelines for a single chart with IN and OUT series.
  // `graphData` is whichever direction the user opened; `pairData` is its sibling.
  const primaryIsIn = graph?.type === "snmp_traffic_in";
  const merged = useMemo(() => {
    if (!pairSamples.length) return samples;
    const byLabel = new Map();
    samples.forEach(s => byLabel.set(s.ts, { ts: s.ts, in: primaryIsIn ? s.value : undefined, out: primaryIsIn ? undefined : s.value }));
    pairSamples.forEach(s => {
      if (byLabel.has(s.ts)) { if (primaryIsIn) byLabel.get(s.ts).out = s.value; else byLabel.get(s.ts).in = s.value; }
      else byLabel.set(s.ts, { ts: s.ts, in: primaryIsIn ? undefined : s.value, out: primaryIsIn ? s.value : undefined });
    });
    return Array.from(byLabel.values());
  }, [samples, pairSamples, primaryIsIn]);

  const unit = graph?.unit || (isTraffic ? "bps" : "");
  const stats = useMemo(() => isTraffic && pair ? trafficStats(merged) : null, [isTraffic, pair, merged]);

  // Y-axis auto-scales to the peak value within the selected range (0 → peak),
  // matching Cacti/LibreNMS/PRTG behaviour. A little headroom keeps the peak
  // line off the top edge.
  const yDomainForValues = (vals) => {
    const nums = vals.filter(v => v != null && Number.isFinite(Number(v))).map(Number);
    if (!nums.length) return [0, "auto"];
    const peak = Math.max(...nums);
    if (peak <= 0) return [0, "auto"];
    return [0, Math.ceil(peak * 1.1)];
  };

  const renderChart = () => {
    if (isTraffic && pair) {
      // Toggle IN / OUT / BOTH by hiding series; Y-axis scales to whatever is shown.
      const showIn = trafficView !== "out";
      const showOut = trafficView !== "in";
      const visibleVals = merged.flatMap(row => [
        showIn ? row.in : null,
        showOut ? row.out : null,
      ]);
      const yDomain = yDomainForValues(visibleVals);
      return merged.length ? (
        <div className="h-64">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={merged}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey={xDataKey} type="number" scale="time" domain={xDomain} tickFormatter={xTickFormatter} minTickGap={24} interval="preserveStartEnd" tickCount={8} tick={{ fontSize: 10 }} />
              <YAxis domain={yDomain} allowDataOverflow tickFormatter={yTickFormatter("bps")} width={70} tick={{ fontSize: 10 }} />
              <Tooltip formatter={tooltipFormatter("bps")} labelFormatter={xTickFormatter} />
              <Line hide={!showIn} type="monotone" dataKey="in" name="IN" stroke="#16a34a" strokeWidth={2} connectNulls={false} />
              <Line hide={!showOut} type="monotone" dataKey="out" name="OUT" stroke="#f5b120" strokeWidth={2} connectNulls={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      ) : <EmptyState title="No data" body="No samples in range." />;
    }
    const yDomain = yDomainForValues(samples.map(s => s.value));
    return samples.length ? (
      <div className="h-64">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={samples}>
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis dataKey={xDataKey} type="number" scale="time" domain={xDomain} tickFormatter={xTickFormatter} minTickGap={24} interval="preserveStartEnd" tickCount={8} tick={{ fontSize: 10 }} />
          <YAxis domain={yDomain} allowDataOverflow tickFormatter={yTickFormatter(unit)} width={70} tick={{ fontSize: 10 }} />
          <Tooltip formatter={tooltipFormatter(unit)} labelFormatter={xTickFormatter} />
            <Line type="monotone" dataKey="value" name={unit ? unit.toUpperCase() : undefined} stroke="#0a2350" strokeWidth={2} />
          </LineChart>
        </ResponsiveContainer>
      </div>
    ) : <EmptyState title="No data" body="No samples in range." />;
  };

  const badge = (
    <span className="inline-flex items-center gap-1 rounded-md bg-slate-200 px-2 py-0.5 text-[11px] font-mono text-slate-600">
      id: {graphData.graph_id}
      <CopyButton text={graphData.graph_id} label="" />
    </span>
  );

  return (
    <Foldable
      title={isTraffic && pair ? `${title} — IN / OUT` : title}
      subtitle={`Resolution: ${graphData.resolution} · Points: ${samples.length}${pair ? ` + ${pairSamples.length}` : ""}`}
      expanded={expanded}
      onToggle={setExpanded}
      badge={badge}
    >
      <div className="flex items-start justify-between gap-4 mb-4">
        <div className="flex items-center gap-2">
          <span className="text-xs text-slate-500">Graph ID:</span>
          <span className="font-mono text-xs text-slate-600">{graphData.graph_id}</span>
          <CopyButton text={graphData.graph_id} label="copy id" />
        </div>
        <button onClick={onClose} aria-label="Close"><X className="h-5 w-5" /></button>
      </div>
      {isTraffic && pair && (
        <div className="mb-3 flex items-center gap-1 rounded-lg bg-slate-100 p-1 text-xs w-fit" data-testid="traffic-view-toggle">
          {["in", "out", "both"].map(view => (
            <button key={view} type="button" onClick={() => setTrafficView(view)} className={`rounded-md px-3 py-1.5 font-semibold ${trafficView === view ? "bg-white text-[#0a2350] shadow-sm" : "text-slate-500 hover:text-[#0a2350]"}`} data-testid={`traffic-view-${view}`}>
              {view.toUpperCase()}
            </button>
          ))}
        </div>
      )}
      {renderChart()}
      {isTraffic && pair && stats && (
        <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-4">
          <StatCard label="Max IN" value={fmtValue(stats.maxIn, "bps")} color="text-green-600" />
          <StatCard label="Max OUT" value={fmtValue(stats.maxOut, "bps")} color="text-amber-500" />
          <StatCard label="Avg IN" value={fmtValue(stats.avgIn, "bps")} color="text-green-600" />
          <StatCard label="Avg OUT" value={fmtValue(stats.avgOut, "bps")} color="text-amber-500" />
        </div>
      )}
      {isTraffic && pair && (
        <div className="mt-3 flex items-center gap-4 text-xs text-slate-500">
          <span className="inline-flex items-center gap-1"><span className="h-2 w-2 rounded-full bg-green-600" /> IN</span>
          <span className="inline-flex items-center gap-1"><span className="h-2 w-2 rounded-full bg-[#f5b120]" /> OUT</span>
          <span className="ml-auto">Combined from {graphData.graph_id} & {pair.id}</span>
        </div>
      )}
    </Foldable>
  );
};

// Collapse IN/OUT traffic graphs into one logical "pair" row so the operator
// sees a single "SNMP Traffic" entry instead of two rows. Non-traffic and
// unpaired traffic graphs stay as single rows.
//   pair  -> { kind:"pair", id, inGraph, outGraph, name, target, ... }
//   single-> { kind:"single", id, graph, ... }
const groupGraphRows = (graphs) => {
  const rows = [];
  const consumed = new Set();
  (graphs || []).forEach(g => {
    if (consumed.has(g.id)) return;
    if (TRAFFIC_PAIR_TYPES.has(g.type)) {
      const sibling = findTrafficPair(graphs, g);
      const inGraph = g.type === "snmp_traffic_in" ? g : sibling;
      const outGraph = g.type === "snmp_traffic_out" ? g : sibling;
      if (sibling) {
        consumed.add(g.id);
        consumed.add(sibling.id);
        // Use the IN graph as the primary handle for View/expand.
        const primary = inGraph || g;
        rows.push({
          kind: "pair",
          id: primary.id,
          inGraph: inGraph || null,
          outGraph: outGraph || null,
          name: (primary.display_name || primary.name || "").replace(/\s*(In|Out|IN|OUT)\b/i, "").trim() || primary.name,
          target: primary.target,
          interval_seconds: primary.interval_seconds,
          client_id: primary.client_id,
          visible_roles: primary.visible_roles,
        });
        return;
      }
    }
    consumed.add(g.id);
    rows.push({ kind: "single", id: g.id, graph: g });
  });
  return rows;
};

// Helper: find the sibling IN/OUT traffic graph for the same target/interface.
const findTrafficPair = (graphs, graph) => {
  if (!graph || !graphs) return null;
  const siblingType = graph.type === "snmp_traffic_in" ? "snmp_traffic_out" : "snmp_traffic_in";
  // Prefer matching display_name / name as interface identifier.
  const graphIf = (graph.display_name || graph.name || "").replace(/\s*(In|Out|IN|OUT)\b/i, "").trim().toLowerCase();
  const graphTarget = (graph.target || "").trim().toLowerCase();
  return graphs.find(g =>
    g.id !== graph.id &&
    g.type === siblingType &&
    (g.target || "").trim().toLowerCase() === graphTarget &&
    (g.display_name || g.name || "").replace(/\s*(In|Out|IN|OUT)\b/i, "").trim().toLowerCase() === graphIf
  ) || null;
};

// Simple foldable panel wrapper.
const Foldable = ({ title, subtitle, children, expanded: controlledExpanded, onToggle, badge }) => {
  const [internal, setInternal] = useState(true);
  const expanded = controlledExpanded !== undefined ? controlledExpanded : internal;
  const setExpanded = onToggle || setInternal;
  return (
    <Card className="mt-5 overflow-hidden" data-testid="foldable-panel">
      <button type="button" onClick={() => setExpanded(!expanded)} className="w-full px-5 py-4 flex items-center justify-between bg-slate-50 hover:bg-slate-100 transition-colors">
        <div className="text-left">
          <h2 className="font-extrabold text-[#0a2350]">{title}</h2>
          {subtitle && <p className="text-xs text-slate-500">{subtitle}</p>}
        </div>
        <div className="flex items-center gap-2">
          {badge}
          {expanded ? <ChevronDown className="h-5 w-5 text-slate-500" /> : <ChevronRight className="h-5 w-5 text-slate-500" />}
        </div>
      </button>
      {expanded && <div className="p-5">{children}</div>}
    </Card>
  );
};

const CopyButton = ({ text, label = "Copy" }) => {
  const [copied, setCopied] = useState(false);
  const handle = () => {
    if (!text) return;
    navigator.clipboard.writeText(text).then(() => { setCopied(true); setTimeout(() => setCopied(false), 1500); });
  };
  return (
    <button type="button" onClick={handle} className="inline-flex items-center gap-1 text-xs text-slate-500 hover:text-[#0a2350]" title={label}>
      {copied ? <Check className="h-3 w-3" /> : <Copy className="h-3 w-3" />} {copied ? "Copied" : label}
    </button>
  );
};

const GRAPH_ROLES = [
  { value: "admin", label: "Admin" },
  { value: "support", label: "Support" },
  { value: "owner", label: "Owner" },
  { value: "sales", label: "Sales" },
  { value: "finance", label: "Finance" },
  { value: "creative", label: "Creative" },
  { value: "ticket_only", label: "Ticket Only" },
];

// Map every discovery kind to a persisted graph type; never coerce memory to traffic.
const kindToType = (kind) => {
  const supported = new Set(["snmp_traffic_in", "snmp_traffic_out", "snmp_cpu", "snmp_memory", "snmp_uptime", "ping"]);
  return supported.has(kind) ? kind : "snmp_traffic_in";
};

// Helper: map a pair type to the two legacy types it creates.
const pairToLegacyTypes = (pairType) => {
  if (pairType === "snmp_traffic_pair") return ["snmp_traffic_in", "snmp_traffic_out"];
  return [pairType];
};

const ClientPicker = ({ value, onChange }) => {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState([]);
  const [searching, setSearching] = useState(false);
  const [selected, setSelected] = useState(null);
  const [err, setErr] = useState("");

  useEffect(() => {
    if (!value) { setSelected(null); return undefined; }
    let cancelled = false;
    api.get("/admin/monitoring/clients", { params: { client_id: value } })
      .then(r => { if (!cancelled) setSelected((r.data || [])[0] || null); })
      .catch(() => { if (!cancelled) setSelected(null); });
    return () => { cancelled = true; };
  }, [value]);

  useEffect(() => {
    if (!query.trim()) { setResults([]); return undefined; }
    let cancelled = false;
    const timer = setTimeout(async () => {
      try {
        setSearching(true); setErr("");
        const r = await api.get("/admin/monitoring/clients", { params: { q: query.trim() } });
        if (!cancelled) setResults(r.data || []);
      } catch (e) {
        if (!cancelled) { setResults([]); setErr(e?.response?.data?.detail || "Search failed"); }
      } finally { if (!cancelled) setSearching(false); }
    }, 250);
    return () => { cancelled = true; clearTimeout(timer); };
  }, [query]);

  return (
    <div className="space-y-2" data-testid="client-picker">
      <span className={labelClass}>Client (optional)</span>
      {selected ? (
        <div className="flex items-center justify-between rounded-lg border border-green-200 bg-green-50 px-3 py-2 text-sm">
          <span><strong>{selected.name || selected.email}</strong>{selected.company ? ` · ${selected.company}` : ""}</span>
          <button type="button" className="text-xs text-red-600" onClick={() => { onChange(""); setSelected(null); setQuery(""); setResults([]); }}>Clear</button>
        </div>
      ) : (
        <>
          <input className={inputClass} placeholder="Search name, email, or company" value={query} onChange={e => setQuery(e.target.value)} data-testid="client-search" />
          {searching && <div className="text-xs text-slate-500">Searching...</div>}
          {err && <div className="text-xs text-red-600">{err}</div>}
          {results.length > 0 && (
            <div className="max-h-40 overflow-y-auto rounded-lg border border-slate-200 bg-white" data-testid="client-results">
              {results.map(client => (
                <button key={client.id} type="button" className="w-full border-b border-slate-100 px-3 py-2 text-left text-sm hover:bg-slate-50 last:border-b-0"
                  onClick={() => { onChange(client.id); setSelected(client); setQuery(""); setResults([]); }}>
                  <div className="font-semibold">{client.name || client.email}</div>
                  <div className="text-xs text-slate-500">{client.email}{client.company ? ` · ${client.company}` : ""}</div>
                </button>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
};

const DiscoveryResults = ({ sensors, onBulkCreate, busy, target, common }) => {
  const [selected, setSelected] = useState(new Set());

  // Reset selection whenever a new discovery scan replaces the sensor list.
  // `selected` stores indices into `sensors`; keeping them across a rescan
  // would submit the wrong sensors.
  useEffect(() => { setSelected(new Set()); }, [sensors]);

  const interfacePairs = useMemo(() => {
    const byIndex = new Map();
    sensors.filter(s => s.category === "interface").forEach(sensor => {
      if (!byIndex.has(sensor.interface_index)) byIndex.set(sensor.interface_index, { name: sensor.interface_name || sensor.interface_descr || `if${sensor.interface_index}`, sensors: [] });
      byIndex.get(sensor.interface_index).sensors.push(sensor);
    });
    return Array.from(byIndex.entries()).map(([index, info]) => ({ index, ...info }));
  }, [sensors]);

  const systemSensors = useMemo(() => sensors.filter(s => s.category !== "interface"), [sensors]);
  const toggle = (idx) => setSelected(current => { const next = new Set(current); if (next.has(idx)) next.delete(idx); else next.add(idx); return next; });

  const generate = () => {
    const picks = Array.from(selected).map(index => sensors[index]).filter(Boolean);
    if (!picks.length) return;
    onBulkCreate(picks);
  };

  if (!sensors.length) return <div className="p-2 text-xs text-slate-500">No sensors discovered.</div>;

  return (
    <div className="space-y-3" data-testid="discovery-results">
      {interfacePairs.length > 0 && (
        <div>
          <div className="mb-1 text-xs font-bold text-slate-700">Interfaces ({interfacePairs.length})</div>
          <div className="space-y-1">{interfacePairs.map(pair => {
            const inbound = pair.sensors.find(s => s.direction === "in");
            const outbound = pair.sensors.find(s => s.direction === "out");
            const inIndex = inbound ? sensors.indexOf(inbound) : -1;
            const outIndex = outbound ? sensors.indexOf(outbound) : -1;
            // One checkbox per interface; selecting it turns on both IN and OUT
            // so a traffic graph is always created as a matched pair.
            const both = inIndex >= 0 && outIndex >= 0;
            const bothSelected = both && selected.has(inIndex) && selected.has(outIndex);
            const togglePair = () => {
              const next = new Set(selected);
              if (bothSelected) { next.delete(inIndex); next.delete(outIndex); }
              else { if (inIndex >= 0) next.add(inIndex); if (outIndex >= 0) next.add(outIndex); }
              setSelected(next);
            };
            return <div key={pair.index} className="flex items-center gap-3 rounded-md border border-slate-200 bg-white px-3 py-2 text-xs">
              <label className="flex items-center gap-2 cursor-pointer flex-1">
                <input type="checkbox" disabled={!inbound && !outbound} checked={bothSelected} onChange={togglePair} data-testid={`discovery-check-${pair.index}-pair`} />
                <strong className="text-[#0a2350]">{pair.name}</strong><span className="ml-2 text-slate-500">ifIndex {pair.index}</span>
              </label>
              <span className="text-slate-400">{both ? "In + Out" : (inbound ? "In" : "Out")}</span>
            </div>;
          })}</div>
        </div>
      )}
      {systemSensors.length > 0 && (
        <div>
          <div className="mb-1 text-xs font-bold text-slate-700">System sensors ({systemSensors.length})</div>
          <div className="space-y-1">{systemSensors.map(sensor => {
            const index = sensors.indexOf(sensor);
            return <label key={`${sensor.oid}-${index}`} className="flex cursor-pointer items-center gap-2 rounded-md border border-slate-200 bg-white px-3 py-2 text-xs">
              <input type="checkbox" checked={selected.has(index)} onChange={() => toggle(index)} data-testid={`discovery-check-system-${index}`} />
              <strong className="text-[#0a2350]">{sensor.label}</strong><span className="text-slate-500">{sensor.unit}</span>
            </label>;
          })}</div>
        </div>
      )}
      <div className="flex items-center justify-between rounded-md bg-slate-100 px-3 py-2 text-xs">
        <span>{selected.size} sensor(s) selected</span>
        <button type="button" className={btnPrimary} disabled={busy || !selected.size} onClick={generate} data-testid="discovery-generate">
          {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />} Generate graphs
        </button>
      </div>
    </div>
  );
};

const GraphForm = ({ value, onChange, onSubmit, onClose, onAfterSave }) => {
  const set = (k, v) => onChange({ ...value, [k]: v });
  const [scanning, setScanning] = useState(false);
  const [sensors, setSensors] = useState(null);
  const [scanError, setScanError] = useState("");
  const [bulkBusy, setBulkBusy] = useState(false);
  const [showManualOid, setShowManualOid] = useState(false);
  const toggleRole = (role) => {
    const current = Array.isArray(value.visible_roles) ? value.visible_roles : [];
    const next = current.includes(role) ? current.filter(r => r !== role) : [...current, role];
    set("visible_roles", next.length ? next : ["admin", "support"]);
  };

  const scan = async () => {
    if (!value.target) { setScanError("Set the target IP/hostname first."); return; }
    setScanning(true); setScanError(""); setSensors(null);
    const payload = {
      target: value.target,
      snmp_community: value.snmp_community || "public",
      snmp_port: Number(value.snmp_port) || 161,
      snmp_version: value.snmp_version || "2c",
      snmp_user: value.snmp_user || "",
      snmp_auth_protocol: value.snmp_auth_protocol || "",
      snmp_auth_key: value.snmp_auth_key || "",
      snmp_priv_protocol: value.snmp_priv_protocol || "",
      snmp_priv_key: value.snmp_priv_key || "",
    };
    try {
      const r = await api.post("/admin/monitoring/discover", payload);
      const res = r.data || {};
      if (res.ok) setSensors(res.sensors || []);
      else { setSensors([]); setScanError(res.error || "Discovery failed"); }
    } catch (e) {
      setSensors([]); setScanError(e?.response?.data?.detail || "Discovery request failed");
    } finally { setScanning(false); }
  };

  const createBulk = async (pickedSensors) => {
    const sensorsPayload = pickedSensors.map(sensor => ({
      oid: sensor.oid,
      name: sensor.label || sensor.oid,
      display_name: sensor.label || sensor.oid,
      type: kindToType(sensor.kind),
      unit: sensor.unit || "",
    }));
    setBulkBusy(true); setScanError("");
    try {
      await api.post("/admin/monitoring/graphs/bulk", {
        target: value.target,
        snmp_community: value.snmp_community || "public",
        snmp_port: Number(value.snmp_port) || 161,
        snmp_version: value.snmp_version || "2c",
        snmp_user: value.snmp_user || "",
        snmp_auth_protocol: value.snmp_auth_protocol || "",
        snmp_auth_key: value.snmp_auth_key || "",
        snmp_priv_protocol: value.snmp_priv_protocol || "",
        snmp_priv_key: value.snmp_priv_key || "",
        interval_seconds: Number(value.interval_seconds) || 300,
        enabled: value.enabled !== false,
        client_id: value.client_id || "",
        visible_roles: value.visible_roles || ["admin", "support"],
        sensors: sensorsPayload,
      });
      await onAfterSave?.();
      onClose();
    } catch (e) {
      setScanError(e?.response?.data?.detail || "Bulk graph creation failed");
    } finally { setBulkBusy(false); }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={onClose}>
      <form className="w-full max-w-lg space-y-4 rounded-2xl bg-white p-6 max-h-[90vh] overflow-y-auto" onClick={e => e.stopPropagation()} onSubmit={onSubmit}>
        <h2 className="text-lg font-extrabold text-[#0a2350]">{value.id ? "Edit graph" : "Add graph"}</h2>
        <label className="block"><span className={labelClass}>Name</span><input required maxLength={120} className={inputClass} value={value.name} onChange={e => set("name", e.target.value)} /></label>
        <label className="block"><span className={labelClass}>Display Name</span><input maxLength={120} className={inputClass} value={value.display_name} onChange={e => set("display_name", e.target.value)} /></label>
        <label className="block"><span className={labelClass}>Target (IP/hostname)</span><input required maxLength={253} className={inputClass} value={value.target} onChange={e => set("target", e.target.value)} /></label>
        <label className="block"><span className={labelClass}>Type</span>
          <select className={inputClass} value={value.type} onChange={e => set("type", e.target.value)}>
            {GRAPH_TYPES.map(t => <option key={t.value} value={t.value}>{t.label}</option>)}
          </select>
        </label>
        {value.type !== "ping" && <>
          <div className="rounded-xl border border-slate-200 p-3 space-y-3">
            <div className="flex items-center justify-between">
              <span className={labelClass}>SNMP Sensor Discovery</span>
              <button type="button" className={btnSecondary} onClick={scan} disabled={scanning} data-testid="discovery-scan">
                {scanning ? <Loader2 className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />} Scan sensors
              </button>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <label className="block"><span className={labelClass}>Version</span>
                <select className={inputClass} value={value.snmp_version || "2c"} onChange={e => set("snmp_version", e.target.value)}>
                  <option value="2c">v2c</option>
                  <option value="3">v3</option>
                </select>
              </label>
              <label className="block"><span className={labelClass}>Port</span><input type="number" className={inputClass} value={value.snmp_port} onChange={e => set("snmp_port", e.target.value)} /></label>
            </div>
            {value.snmp_version === "3" ? (
              <div className="space-y-2">
                <label className="block"><span className={labelClass}>User</span><input className={inputClass} value={value.snmp_user || ""} onChange={e => set("snmp_user", e.target.value)} /></label>
                <div className="grid grid-cols-2 gap-3">
                  <label className="block"><span className={labelClass}>Auth protocol</span>
                    <select className={inputClass} value={value.snmp_auth_protocol || ""} onChange={e => set("snmp_auth_protocol", e.target.value)}>
                      <option value="">—</option><option value="MD5">MD5</option><option value="SHA">SHA</option>
                    </select>
                  </label>
                  <label className="block"><span className={labelClass}>Auth key</span><input className={inputClass} value={value.snmp_auth_key || ""} onChange={e => set("snmp_auth_key", e.target.value)} /></label>
                  <label className="block"><span className={labelClass}>Priv protocol</span>
                    <select className={inputClass} value={value.snmp_priv_protocol || ""} onChange={e => set("snmp_priv_protocol", e.target.value)}>
                      <option value="">—</option><option value="DES">DES</option><option value="AES">AES</option>
                    </select>
                  </label>
                  <label className="block"><span className={labelClass}>Priv key</span><input className={inputClass} value={value.snmp_priv_key || ""} onChange={e => set("snmp_priv_key", e.target.value)} /></label>
                </div>
              </div>
            ) : (
              <label className="block"><span className={labelClass}>Community (v2c)</span><input className={inputClass} value={value.snmp_community} onChange={e => set("snmp_community", e.target.value)} /></label>
            )}

            {scanError && <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700" data-testid="discovery-error">{scanError}</div>}
            {sensors && <DiscoveryResults sensors={sensors} onBulkCreate={createBulk} busy={bulkBusy} />}
            <button type="button" className="text-xs text-slate-500 hover:text-[#0a2350] underline" onClick={() => setShowManualOid(v => !v)}>
              {showManualOid ? "Hide manual OIDs" : "Enter OIDs manually"}
           </button>
            {showManualOid && value.type === "snmp_traffic_pair" && (
              <div className="space-y-2 rounded-lg border border-slate-200 bg-slate-50 p-3">
                <p className="text-xs text-slate-500">SNMP Traffic needs two OIDs (one for IN, one for OUT)</p>
                <label className="block"><span className={labelClass}>SNMP OID In (manual)</span><input maxLength={256} className={inputClass} value={value.snmp_oid_in} onChange={e => set("snmp_oid_in", e.target.value)} /></label>
                <label className="block"><span className={labelClass}>SNMP OID Out (manual)</span><input maxLength={256} className={inputClass} value={value.snmp_oid_out} onChange={e => set("snmp_oid_out", e.target.value)} /></label>
              </div>
            )}
            {showManualOid && value.type !== "snmp_traffic_pair" && value.type !== "ping" && (
              <label className="block"><span className={labelClass}>SNMP OID (manual)</span><input maxLength={256} className={inputClass} value={value.snmp_oid} onChange={e => set("snmp_oid", e.target.value)} /></label>
            )}
          </div>
        </>}
        <label className="block"><span className={labelClass}>Interval (20–3600s)</span><input required type="number" min="20" max="3600" className={inputClass} value={value.interval_seconds} onChange={e => set("interval_seconds", e.target.value)} /></label>
        <label className="block"><span className={labelClass}>Unit</span>
          <select className={inputClass} value={value.unit || ""} onChange={e => set("unit", e.target.value)}>
            <option value="">Auto / none</option>
            <option value="bps">bps</option>
            <option value="%">%</option>
            <option value="KB">KB</option>
            <option value="bytes">bytes</option>
            <option value="ms">ms</option>
            <option value="seconds">seconds</option>
          </select>
        </label>
        <ClientPicker value={value.client_id} onChange={clientId => set("client_id", clientId)} />
        <fieldset className="rounded-xl border border-slate-200 p-3">
          <legend className={labelClass}>Visible to roles</legend>
          <div className="grid grid-cols-2 gap-2 mt-2">
            {GRAPH_ROLES.map(role => <label key={role.value} className="flex items-center gap-2 text-sm"><input type="checkbox" checked={(value.visible_roles || ["admin", "support"]).includes(role.value)} onChange={() => toggleRole(role.value)} /> {role.label}</label>)}
          </div>
          <p className="mt-2 text-xs text-slate-500">Admin selalu dapat melihat semua graph.</p>
        </fieldset>
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={!!value.enabled} onChange={e => set("enabled", e.target.checked)} /> Enabled</label>
        <div className="flex justify-end gap-2"><button type="button" className={btnSecondary} onClick={onClose}>Cancel</button><button type="submit" className={btnPrimary}>Save</button></div>
      </form>
    </div>
  );
};

// ═════════════════════════════════════════════════════════════════
// Network Map Tab (React Flow)
// ═════════════════════════════════════════════════════════════════
const NODE_EMPTY = { label: "", type: "custom", x: 100, y: 100, device_id: "", graph_id: "" };
const LINK_EMPTY = { source_id: "", target_id: "", label: "", color: "#64748b", width: 1 };

const NODE_TYPES = [
  { value: "router", label: "Router" },
  { value: "switch", label: "Switch" },
  { value: "server", label: "Server" },
  { value: "cloud", label: "Cloud" },
  { value: "custom", label: "Custom" },
];

const nodeIcon = (type) => {
  switch (type) {
    case "router": return "📡";
    case "switch": return "🔀";
    case "server": return "🖥️";
    case "cloud": return "☁️";
    default: return "🔘";
  }
};

// Custom React Flow node with connection handles
const NOCNode = ({ data }) => (
  <div className="relative flex flex-col items-center">
    <Handle type="target" position={Position.Top} className="!w-2 !h-2" />
    <div className="flex flex-col items-center rounded-xl border-2 border-[#f5b120] bg-[#0a2350] px-3 py-2 shadow-md min-w-[90px]">
      <span className="text-2xl leading-none">{nodeIcon(data.type)}</span>
      <span className="mt-1 text-center text-xs font-bold text-white leading-tight">{data.label}</span>
    </div>
    <Handle type="source" position={Position.Bottom} className="!w-2 !h-2" />
  </div>
);

const nodeTypes = { noc: NOCNode };

const NetworkMapTab = ({ isAdmin }) => {
  const [nodes, setNodes] = useState(null);
  const [links, setLinks] = useState(null);
  const [error, setError] = useState("");
  const [editingNode, setEditingNode] = useState(null);
  const [editingLink, setEditingLink] = useState(null);

  const load = useCallback(async () => {
    try {
      setError("");
      const [nr, lr] = await Promise.all([
        api.get("/admin/monitoring/map/nodes"),
        api.get("/admin/monitoring/map/links"),
      ]);
      setNodes(nr.data || []);
      setLinks(lr.data || []);
    } catch (e) { setError(e?.response?.data?.detail || "Failed to load map"); }
  }, []);

  useEffect(() => { load(); }, [load]);

  // Build React Flow nodes/edges from backend data
  const rfNodes = useMemo(() => (nodes || []).map(n => ({
    id: n.id,
    position: { x: Number(n.x) || 100, y: Number(n.y) || 100 },
    data: { label: n.label, type: n.type || "custom" },
    type: "noc",
  })), [nodes]);

  const rfEdges = useMemo(() => (links || []).map(l => ({
    id: l.id,
    source: l.source_id,
    target: l.target_id,
    label: l.label || "",
    style: { stroke: l.color || "#64748b", strokeWidth: Number(l.width) || 1 },
    markerEnd: { type: MarkerType.ArrowClosed },
  })), [links]);

  const [flowNodes, setFlowNodes, onNodesChange] = useNodesState(rfNodes);
  const [flowEdges, setFlowEdges, onEdgesChange] = useEdgesState(rfEdges);

  // Keep React Flow state in sync when backend data reloads
  useEffect(() => { setFlowNodes(rfNodes); }, [rfNodes, setFlowNodes]);
  useEffect(() => { setFlowEdges(rfEdges); }, [rfEdges, setFlowEdges]);

  const onConnect = useCallback(async (conn) => {
    if (!conn.source || !conn.target) return;
    try {
      setError("");
      await api.post("/admin/monitoring/map/links", { source_id: conn.source, target_id: conn.target });
      await load();
    } catch (e) { setError(e?.response?.data?.detail || "Failed to create link"); }
  }, [load]);

  const onNodeDragStop = useCallback(async (_e, node) => {
    try {
      setError("");
      await api.put(`/admin/monitoring/map/nodes/${node.id}`, { x: Math.round(node.position.x), y: Math.round(node.position.y) });
    } catch (e) { setError(e?.response?.data?.detail || "Failed to save node position"); }
  }, []);

  const saveNode = async (e) => {
    e.preventDefault();
    try {
      if (editingNode.id) await api.put(`/admin/monitoring/map/nodes/${editingNode.id}`, editingNode);
      else await api.post("/admin/monitoring/map/nodes", editingNode);
      setEditingNode(null); await load();
    } catch (e) { setError(e?.response?.data?.detail || "Failed to save node"); }
  };

  const deleteNode = async (id) => {
    if (!window.confirm("Delete this node? All connected links will also be removed.")) return;
    try { await api.delete(`/admin/monitoring/map/nodes/${id}`); await load(); }
    catch (e) { setError(e?.response?.data?.detail || "Failed to delete"); }
  };

  const saveLink = async (e) => {
    e.preventDefault();
    try {
      if (editingLink.id) await api.put(`/admin/monitoring/map/links/${editingLink.id}`, editingLink);
      else await api.post("/admin/monitoring/map/links", editingLink);
      setEditingLink(null); await load();
    } catch (e) { setError(e?.response?.data?.detail || "Failed to save link"); }
  };

  const deleteLink = async (id) => {
    if (!window.confirm("Delete this link?")) return;
    try { await api.delete(`/admin/monitoring/map/links/${id}`); await load(); }
    catch (e) { setError(e?.response?.data?.detail || "Failed to delete"); }
  };

  if (nodes === null || links === null) return <Loading label="Loading map…" />;

  return (
    <div>
      <div className="flex items-center gap-2 mb-4">
        <button className={btnSecondary} onClick={load}><RefreshCw className="h-4 w-4" /> Refresh</button>
        {isAdmin && <button className={btnPrimary} onClick={() => setEditingNode({ ...NODE_EMPTY })}><Plus className="h-4 w-4" /> Add node</button>}
        {isAdmin && (nodes.length > 1) && <button className={btnSecondary} onClick={() => setEditingLink({ ...LINK_EMPTY })}><Network className="h-4 w-4" /> Add link</button>}
      </div>
      {error && <div className="mb-4 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div>}

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">
        <div className="lg:col-span-2">
          <Card className="p-5">
            <h3 className="font-extrabold text-[#0a2350] mb-3">Map</h3>
            <div className="rounded-xl border border-slate-200 overflow-hidden" data-testid="map-canvas" style={{ height: 480 }}>
              <ReactFlow
                nodes={flowNodes}
                edges={flowEdges}
                onNodesChange={onNodesChange}
                onEdgesChange={onEdgesChange}
                onConnect={onConnect}
                onNodeDragStop={onNodeDragStop}
                nodeTypes={nodeTypes}
                fitView
                proOptions={{ hideAttribution: true }}
              >
                <Background gap={20} size={1} />
                <Controls />
                <MiniMap nodeColor={(n) => n.data?.type === "router" ? "#f5b120" : "#0a2350"} />
              </ReactFlow>
            </div>
            <p className="mt-2 text-xs text-slate-500">Drag nodes to reposition. Drag from the bottom handle of one node to the top handle of another to draw a link.</p>
          </Card>
        </div>

        <div className="space-y-5">
          <Card className="p-5">
            <h3 className="font-extrabold text-[#0a2350] mb-3">Nodes ({nodes.length})</h3>
            {nodes.length === 0 ? <EmptyState title="No nodes" body="Add a node to begin." /> : (
              <div className="space-y-2">
                {nodes.map(n => (
                  <div key={n.id} className="flex items-center gap-2 text-sm border-b border-slate-100 pb-2">
                    <span className="text-lg">{nodeIcon(n.type)}</span>
                    <span className="flex-1 font-semibold">{n.label}</span>
                    {isAdmin && (<>
                      <button className="text-xs text-slate-500 hover:text-[#0a2350]" onClick={() => setEditingNode({ ...n })}><Edit className="h-3 w-3" /></button>
                      <button className="text-xs text-red-500 hover:text-red-700" onClick={() => deleteNode(n.id)}><Trash2 className="h-3 w-3" /></button>
                    </>)}
                  </div>
                ))}
              </div>
            )}
          </Card>

          <Card className="p-5">
            <h3 className="font-extrabold text-[#0a2350] mb-3">Links ({links.length})</h3>
            {links.length === 0 ? <EmptyState title="No links" body="Connect nodes by drawing between handles or adding links." /> : (
              <div className="space-y-2">
                {links.map(l => {
                  const src = nodes.find(n => n.id === l.source_id);
                  const tgt = nodes.find(n => n.id === l.target_id);
                  return (
                    <div key={l.id} className="flex items-center gap-2 text-sm border-b border-slate-100 pb-2">
                      <span className="text-xs">{src?.label || "?"} → {tgt?.label || "?"}</span>
                      {l.label && <span className="text-xs text-slate-500">({l.label})</span>}
                      {isAdmin && (<>
                        <button className="text-xs text-slate-500 hover:text-[#0a2350]" onClick={() => setEditingLink({ ...l })}><Edit className="h-3 w-3" /></button>
                        <button className="text-xs text-red-500 hover:text-red-700" onClick={() => deleteLink(l.id)}><Trash2 className="h-3 w-3" /></button>
                      </>)}
                    </div>
                  );
                })}
              </div>
            )}
          </Card>
        </div>
      </div>

      {editingNode && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={() => setEditingNode(null)}>
          <form className="w-full max-w-md space-y-4 rounded-2xl bg-white p-6" onClick={e => e.stopPropagation()} onSubmit={saveNode}>
            <h2 className="text-lg font-extrabold text-[#0a2350]">{editingNode.id ? "Edit node" : "Add node"}</h2>
            <label className="block"><span className={labelClass}>Label</span><input required maxLength={120} className={inputClass} value={editingNode.label} onChange={e => setEditingNode({ ...editingNode, label: e.target.value })} /></label>
            <label className="block"><span className={labelClass}>Type</span>
              <select className={inputClass} value={editingNode.type} onChange={e => setEditingNode({ ...editingNode, type: e.target.value })}>
                {NODE_TYPES.map(t => <option key={t.value} value={t.value}>{t.label}</option>)}
              </select>
            </label>
            <label className="block"><span className={labelClass}>Graph ID (optional)</span><input className={inputClass} value={editingNode.graph_id} onChange={e => setEditingNode({ ...editingNode, graph_id: e.target.value })} /></label>
            <p className="text-xs text-slate-500">Position is set by dragging on the map after saving.</p>
            <div className="flex justify-end gap-2"><button type="button" className={btnSecondary} onClick={() => setEditingNode(null)}>Cancel</button><button type="submit" className={btnPrimary}>Save</button></div>
          </form>
        </div>
      )}

      {editingLink && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={() => setEditingLink(null)}>
          <form className="w-full max-w-md space-y-4 rounded-2xl bg-white p-6" onClick={e => e.stopPropagation()} onSubmit={saveLink}>
            <h2 className="text-lg font-extrabold text-[#0a2350]">{editingLink.id ? "Edit link" : "Add link"}</h2>
            <label className="block"><span className={labelClass}>Source node</span>
              <select required className={inputClass} value={editingLink.source_id} onChange={e => setEditingLink({ ...editingLink, source_id: e.target.value })}>
                <option value="">— Select —</option>
                {nodes.map(n => <option key={n.id} value={n.id}>{n.label}</option>)}
              </select>
            </label>
            <label className="block"><span className={labelClass}>Target node</span>
              <select required className={inputClass} value={editingLink.target_id} onChange={e => setEditingLink({ ...editingLink, target_id: e.target.value })}>
                <option value="">— Select —</option>
                {nodes.map(n => <option key={n.id} value={n.id}>{n.label}</option>)}
              </select>
            </label>
            <label className="block"><span className={labelClass}>Label</span><input className={inputClass} value={editingLink.label} onChange={e => setEditingLink({ ...editingLink, label: e.target.value })} /></label>
            <label className="block"><span className={labelClass}>Color</span><input type="color" className="h-10 w-full rounded-lg border border-slate-300" value={editingLink.color} onChange={e => setEditingLink({ ...editingLink, color: e.target.value })} /></label>
            <div className="flex justify-end gap-2"><button type="button" className={btnSecondary} onClick={() => setEditingLink(null)}>Cancel</button><button type="submit" className={btnPrimary}>Save</button></div>
          </form>
        </div>
      )}
    </div>
  );
};

export default AdminMonitoring;