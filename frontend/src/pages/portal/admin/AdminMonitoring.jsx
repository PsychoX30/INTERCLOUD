import React, { useCallback, useEffect, useState } from "react";
import { Activity, Edit, Loader2, Map, Network, PlayCircle, Plus, RefreshCw, Trash2, X, BarChart3, Download, Eye, EyeOff } from "lucide-react";
import { ResponsiveContainer, LineChart, Line, XAxis, YAxis, Tooltip, CartesianGrid } from "recharts";
import { useAuth } from "../../../portal/AuthContext";
import { api } from "../../../portal/api";
import { Card, EmptyState, Loading, PageHeader, StatusBadge, btnDanger, btnPrimary, btnSecondary, inputClass, labelClass } from "../ui";

const stamp = (value) => value ? new Date(value).toLocaleString() : "-";
const PING_EMPTY = { name: "", target: "", enabled: true, interval_seconds: 300 };
const GRAPH_EMPTY = { name: "", target: "", type: "snmp_traffic", snmp_oid: "", snmp_community: "public", snmp_port: 161, interval_seconds: 300, enabled: true, client_id: "", unit: "", display_name: "", visible_roles: ["admin", "support"] };

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
        <TabBtn active={tab === "map"} onClick={() => setTab("map")} icon={Map} testid="tab-map">Network Map</TabBtn>
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
    try { setError(""); await api.post(`/admin/monitoring/checks/${id}/run`); await Promise.all([loadChecks(), loadHistory(id)]); }
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
  const samples = [...(history.samples || [])].reverse().map(s => ({ ...s, label: s.at ? new Date(s.at).toLocaleTimeString() : "-" }));
  return (
    <Card className="mt-5 p-5" data-testid="monitoring-history">
      <div className="flex items-start justify-between gap-4 mb-4">
        <div><h2 className="font-extrabold text-[#0a2350]">{history.check?.name} history</h2><p className="text-xs text-slate-500">Last probe: {stamp(history.state?.last_at)} · RTT: {history.state?.last_rtt_ms ?? "-"} ms</p></div>
        <div className="flex items-center gap-2"><StatusBadge status={history.state?.status || "unknown"} /><button onClick={onClose}><X className="h-5 w-5" /></button></div>
      </div>
      {samples.length ? <div className="h-64"><ResponsiveContainer width="100%" height="100%"><LineChart data={samples}><CartesianGrid strokeDasharray="3 3" /><XAxis dataKey="label" minTickGap={24} /><YAxis unit="ms" /><Tooltip /><Line type="monotone" dataKey="rtt_ms" stroke="#0a2350" strokeWidth={2} connectNulls={false} /></LineChart></ResponsiveContainer></div> : <EmptyState title="No samples yet" body="Run the check or wait for its next scheduled interval." />}
      {(history.events || []).length > 0 && <div className="mt-5"><div className={labelClass}>Transitions</div><div className="mt-2 space-y-2">{history.events.map(ev => <div key={ev.id} className="rounded-lg bg-slate-50 px-3 py-2 text-xs"><span className="font-mono text-slate-500">{stamp(ev.at)}</span> · {ev.from || "unknown"} → <strong>{ev.to}</strong></div>)}</div></div>}
    </Card>
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
        <label className="block"><span className={labelClass}>Interval (30–3600s)</span><input required type="number" min="30" max="3600" className={inputClass} value={value.interval_seconds} onChange={e => set("interval_seconds", e.target.value)} /></label>
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
  { value: "snmp_traffic", label: "SNMP Traffic" },
  { value: "snmp_uptime", label: "SNMP Uptime" },
  { value: "snmp_cpu", label: "SNMP CPU" },
  { value: "ping", label: "Ping RTT" },
];

const GraphsTab = ({ isAdmin }) => {
  const [graphs, setGraphs] = useState(null);
  const [selectedId, setSelectedId] = useState("");
  const [graphData, setGraphData] = useState(null);
  const [editing, setEditing] = useState(null);
  const [busyId, setBusyId] = useState("");
  const [error, setError] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");

  const loadGraphs = useCallback(async () => {
    try { setError(""); const r = await api.get("/admin/monitoring/graphs"); setGraphs(r.data || []); }
    catch (e) { setError(e?.response?.data?.detail || "Failed to load graphs"); setGraphs([]); }
  }, []);

  useEffect(() => { loadGraphs(); }, [loadGraphs]);

  const loadData = useCallback(async (id) => {
    if (!id) return;
    const f = from || new Date(Date.now() - 24 * 3600 * 1000).toISOString();
    const t = to || new Date().toISOString();
    try {
      setError("");
      const r = await api.get(`/admin/monitoring/graphs/${id}/data`, { params: { from: f, to: t, resolution: "auto" } });
      setSelectedId(id);
      setGraphData(r.data);
    } catch (e) { setError(e?.response?.data?.detail || "Failed to load graph data"); }
  }, [from, to]);

  const save = async (e) => {
    e.preventDefault();
    const payload = { ...editing };
    delete payload.id;
    try {
      if (editing.id) await api.put(`/admin/monitoring/graphs/${editing.id}`, payload);
      else await api.post("/admin/monitoring/graphs", payload);
      setEditing(null); await loadGraphs();
    } catch (e) { setError(e?.response?.data?.detail || "Failed to save"); }
  };

  const remove = async (id) => {
    if (!window.confirm("Delete this graph?")) return;
    try { await api.delete(`/admin/monitoring/graphs/${id}`); if (selectedId === id) { setSelectedId(""); setGraphData(null); } await loadGraphs(); }
    catch (e) { setError(e?.response?.data?.detail || "Failed to delete"); }
  };

  const run = async (id) => {
    setBusyId(id);
    try { setError(""); await api.post(`/admin/monitoring/graphs/${id}/run`); await loadGraphs(); }
    catch (e) { setError(e?.response?.data?.detail || "Probe failed"); }
    finally { setBusyId(""); }
  };

  const exportGraph = async (id, fmt) => {
    const f = from || new Date(Date.now() - 7 * 86400 * 1000).toISOString();
    const t = to || new Date().toISOString();
    try {
      const r = await api.get(`/admin/monitoring/graphs/${id}/export`, { params: { from: f, to: t, fmt }, responseType: "blob" });
      const url = window.URL.createObjectURL(new Blob([r.data]));
      const a = document.createElement("a"); a.href = url;
      a.download = `graph-${id}.${fmt}`; a.click(); window.URL.revokeObjectURL(url);
    } catch (e) { setError(e?.response?.data?.detail || "Export failed"); }
  };

  if (graphs === null) return <Loading label="Loading graphs…" />;

  return (
    <div>
      <div className="flex items-center gap-2 mb-4">
        <button className={btnSecondary} onClick={loadGraphs}><RefreshCw className="h-4 w-4" /> Refresh</button>
        {isAdmin && <button className={btnPrimary} onClick={() => setEditing({ ...GRAPH_EMPTY })}><Plus className="h-4 w-4" /> Add graph</button>}
      </div>
      {error && <div className="mb-4 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div>}

      <Card className="overflow-hidden mb-5">
        {graphs.length === 0 ? <EmptyState title="No graphs" body={isAdmin ? "Add an SNMP or ping graph to begin collecting data." : "An admin has not configured any graphs."} /> : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 text-[11px] uppercase tracking-widest text-slate-500">
                <tr><th className="px-4 py-3 text-left">Name</th><th className="px-4 py-3 text-left">Target</th><th className="px-4 py-3 text-left">Type</th><th className="px-4 py-3 text-left">Interval</th><th className="px-4 py-3 text-left">Client</th><th className="px-4 py-3 text-left">Visible to</th><th className="px-4 py-3 text-right">Actions</th></tr>
              </thead>
              <tbody>
                {graphs.map(g => (
                  <tr key={g.id} className="border-t border-slate-100">
                    <td className="px-4 py-3 font-semibold text-[#0a2350]">{g.display_name || g.name}</td>
                    <td className="px-4 py-3 font-mono text-xs">{g.target}</td>
                    <td className="px-4 py-3"><StatusBadge status={g.type} /></td>
                    <td className="px-4 py-3">{g.interval_seconds}s</td>
                    <td className="px-4 py-3">{g.client_id ? <span className="text-green-700">assigned</span> : <span className="text-slate-400">internal</span>}</td>
                    <td className="px-4 py-3 text-xs text-slate-500">{(g.visible_roles || []).join(", ")}</td>
                    <td className="px-4 py-3"><div className="flex justify-end gap-2">
                      <button className={btnSecondary} onClick={() => loadData(g.id)}><BarChart3 className="h-4 w-4" /> View</button>
                      {isAdmin && (<>
                        <button className={btnSecondary} onClick={() => run(g.id)} disabled={busyId === g.id}>{busyId === g.id ? <Loader2 className="h-4 w-4 animate-spin" /> : <PlayCircle className="h-4 w-4" />} Probe</button>
                        <button className={btnSecondary} onClick={() => exportGraph(g.id, "xlsx")}><Download className="h-4 w-4" /> XLSX</button>
                        <button className={btnSecondary} onClick={() => exportGraph(g.id, "pdf")}><Download className="h-4 w-4" /> PDF</button>
                        <button className={btnSecondary} onClick={() => setEditing({ ...g })}><Edit className="h-4 w-4" /></button>
                        <button className={btnDanger} onClick={() => remove(g.id)}><Trash2 className="h-4 w-4" /></button>
                      </>)}
                    </div></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {graphData && <GraphDataPanel graphData={graphData} onClose={() => { setGraphData(null); setSelectedId(""); }} />}
      {editing && <GraphForm value={editing} onChange={setEditing} onSubmit={save} onClose={() => setEditing(null)} />}
    </div>
  );
};

const GraphDataPanel = ({ graphData, onClose }) => {
  const samples = (graphData.data || []).map(s => ({ ...s, label: s.at ? new Date(s.at).toLocaleTimeString() : "-" }));
  return (
    <Card className="p-5 mt-5" data-testid="monitoring-graph-data">
      <div className="flex items-start justify-between gap-4 mb-4">
        <div><h2 className="font-extrabold text-[#0a2350]">Graph {graphData.graph_id}</h2><p className="text-xs text-slate-500">Resolution: {graphData.resolution} · Points: {samples.length}</p></div>
        <button onClick={onClose}><X className="h-5 w-5" /></button>
      </div>
      {samples.length ? <div className="h-64"><ResponsiveContainer width="100%" height="100%"><LineChart data={samples}><CartesianGrid strokeDasharray="3 3" /><XAxis dataKey="label" minTickGap={24} /><YAxis /><Tooltip /><Line type="monotone" dataKey="value" stroke="#0a2350" strokeWidth={2} /></LineChart></ResponsiveContainer></div> : <EmptyState title="No data" body="No samples in range." />}
    </Card>
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

const GraphForm = ({ value, onChange, onSubmit, onClose }) => {
  const set = (k, v) => onChange({ ...value, [k]: v });
  const toggleRole = (role) => {
    const current = Array.isArray(value.visible_roles) ? value.visible_roles : [];
    const next = current.includes(role) ? current.filter(r => r !== role) : [...current, role];
    set("visible_roles", next.length ? next : ["admin", "support"]);
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
          <label className="block"><span className={labelClass}>SNMP OID</span><input required maxLength={256} className={inputClass} value={value.snmp_oid} onChange={e => set("snmp_oid", e.target.value)} /></label>
          <label className="block"><span className={labelClass}>SNMP Version</span>
            <select className={inputClass} value={value.snmp_version || "2c"} onChange={e => set("snmp_version", e.target.value)}>
              <option value="2c">v2c</option>
              <option value="3">v3</option>
            </select>
          </label>
          <label className="block"><span className={labelClass}>Community (v2c)</span><input className={inputClass} value={value.snmp_community} onChange={e => set("snmp_community", e.target.value)} /></label>
          <label className="block"><span className={labelClass}>SNMP Port</span><input type="number" className={inputClass} value={value.snmp_port} onChange={e => set("snmp_port", e.target.value)} /></label>
        </>}
        <label className="block"><span className={labelClass}>Interval (30–3600s)</span><input required type="number" min="30" max="3600" className={inputClass} value={value.interval_seconds} onChange={e => set("interval_seconds", e.target.value)} /></label>
        <label className="block"><span className={labelClass}>Unit</span><input className={inputClass} value={value.unit} onChange={e => set("unit", e.target.value)} /></label>
        <label className="block"><span className={labelClass}>Client ID (optional)</span><input className={inputClass} value={value.client_id} onChange={e => set("client_id", e.target.value)} placeholder="MongoDB ObjectId" /></label>
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
// Network Map Tab
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
            <div className="relative bg-slate-50 rounded-xl border border-slate-200 overflow-hidden" style={{ minHeight: "400px", width: "100%" }}>
              <svg viewBox="0 0 800 500" className="w-full h-full" style={{ minHeight: "400px" }}>
                {/* Links */}
                {links.map(l => {
                  const src = nodes.find(n => n.id === l.source_id);
                  const tgt = nodes.find(n => n.id === l.target_id);
                  if (!src || !tgt) return null;
                  return (
                    <line key={l.id} x1={src.x} y1={src.y} x2={tgt.x} y2={tgt.y}
                      stroke={l.color || "#64748b"} strokeWidth={l.width || 1}
                      strokeDasharray={l.label ? "none" : "4,2"} />
                  );
                })}
                {/* Nodes */}
                {nodes.map(n => (
                  <g key={n.id} transform={`translate(${n.x},${n.y})`}>
                    <circle r="24" fill="#0a2350" stroke="#f5b120" strokeWidth="2" />
                    <text textAnchor="middle" dy="-30" fontSize="10" fill="#0a2350" fontWeight="bold">{n.label}</text>
                    <text textAnchor="middle" dy="5" fontSize="16">{nodeIcon(n.type)}</text>
                  </g>
                ))}
              </svg>
            </div>
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
            {links.length === 0 ? <EmptyState title="No links" body="Connect nodes by adding links." /> : (
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
            <label className="block"><span className={labelClass}>X</span><input type="number" className={inputClass} value={editingNode.x} onChange={e => setEditingNode({ ...editingNode, x: Number(e.target.value) })} /></label>
            <label className="block"><span className={labelClass}>Y</span><input type="number" className={inputClass} value={editingNode.y} onChange={e => setEditingNode({ ...editingNode, y: Number(e.target.value) })} /></label>
            <label className="block"><span className={labelClass}>Graph ID (optional)</span><input className={inputClass} value={editingNode.graph_id} onChange={e => setEditingNode({ ...editingNode, graph_id: e.target.value })} /></label>
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