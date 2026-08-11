import React, { useCallback, useEffect, useState } from "react";
import { Activity, Edit, Loader2, PlayCircle, Plus, RefreshCw, Trash2, X } from "lucide-react";
import { ResponsiveContainer, LineChart, Line, XAxis, YAxis, Tooltip, CartesianGrid } from "recharts";
import { useAuth } from "../../../portal/AuthContext";
import { api } from "../../../portal/api";
import { Card, EmptyState, Loading, PageHeader, StatusBadge, btnDanger, btnPrimary, btnSecondary, inputClass, labelClass } from "../ui";

const EMPTY = { name: "", target: "", enabled: true, interval_seconds: 300 };
const stamp = (value) => value ? new Date(value).toLocaleString() : "-";

const AdminMonitoring = () => {
  const { user } = useAuth() || {};
  const isAdmin = user?.role === "admin";
  const [checks, setChecks] = useState(null);
  const [selectedId, setSelectedId] = useState("");
  const [history, setHistory] = useState(null);
  const [editing, setEditing] = useState(null);
  const [busyId, setBusyId] = useState("");
  const [error, setError] = useState("");

  const loadChecks = useCallback(async () => {
    try {
      setError("");
      const response = await api.get("/admin/monitoring/checks");
      setChecks(response.data || []);
    } catch (e) {
      setError(e?.response?.data?.detail || "Failed to load monitoring checks");
      setChecks([]);
    }
  }, []);

  const loadHistory = useCallback(async (id) => {
    if (!id) return;
    try {
      setError("");
      const response = await api.get(`/admin/monitoring/checks/${id}/history`, { params: { limit: 200 } });
      setSelectedId(id);
      setHistory(response.data);
    } catch (e) {
      setError(e?.response?.data?.detail || "Failed to load monitoring history");
    }
  }, []);

  useEffect(() => { loadChecks(); }, [loadChecks]);

  const save = async (event) => {
    event.preventDefault();
    const payload = {
      name: editing.name,
      target: editing.target,
      enabled: !!editing.enabled,
      interval_seconds: Number(editing.interval_seconds),
    };
    try {
      if (editing.id) await api.put(`/admin/monitoring/checks/${editing.id}`, payload);
      else await api.post("/admin/monitoring/checks", payload);
      setEditing(null);
      await loadChecks();
    } catch (e) {
      setError(e?.response?.data?.detail || "Failed to save monitoring check");
    }
  };

  const remove = async (id) => {
    if (!window.confirm("Delete this monitoring check?")) return;
    try {
      await api.delete(`/admin/monitoring/checks/${id}`);
      if (selectedId === id) { setSelectedId(""); setHistory(null); }
      await loadChecks();
    } catch (e) {
      setError(e?.response?.data?.detail || "Failed to delete monitoring check");
    }
  };

  const run = async (id) => {
    setBusyId(id);
    try {
      setError("");
      await api.post(`/admin/monitoring/checks/${id}/run`);
      await Promise.all([loadChecks(), loadHistory(id)]);
    } catch (e) {
      setError(e?.response?.data?.detail || "Probe failed");
    } finally {
      setBusyId("");
    }
  };

  if (checks === null) return <Loading label="Loading monitoring checks…" />;

  return (
    <div data-testid="monitoring-page">
      <PageHeader
        title="Ping Monitoring"
        subtitle="Internal reachability checks. The scheduler probes enabled targets every 30 seconds when their configured interval is due."
        actions={<>
          <button className={btnSecondary} onClick={loadChecks} data-testid="monitoring-refresh"><RefreshCw className="h-4 w-4" /> Refresh</button>
          {isAdmin && <button className={btnPrimary} onClick={() => setEditing({ ...EMPTY })} data-testid="monitoring-add"><Plus className="h-4 w-4" /> Add check</button>}
        </>}
      />

      {error && <div className="mb-4 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div>}

      <Card className="overflow-hidden">
        {checks.length === 0 ? <EmptyState title="No monitoring checks" body={isAdmin ? "Add a public IP or hostname to begin polling." : "An administrator has not configured any checks."} /> : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 text-[11px] uppercase tracking-widest text-slate-500">
                <tr><th className="px-4 py-3 text-left">Name</th><th className="px-4 py-3 text-left">Target</th><th className="px-4 py-3 text-left">Interval</th><th className="px-4 py-3 text-left">Enabled</th><th className="px-4 py-3 text-right">Actions</th></tr>
              </thead>
              <tbody>
                {checks.map((check) => (
                  <tr key={check.id} className="border-t border-slate-100" data-testid={`monitoring-check-${check.id}`}>
                    <td className="px-4 py-3 font-semibold text-[#0a2350]">{check.name}</td>
                    <td className="px-4 py-3 font-mono text-xs">{check.target}</td>
                    <td className="px-4 py-3">{check.interval_seconds}s</td>
                    <td className="px-4 py-3"><StatusBadge status={check.enabled ? "enabled" : "disabled"} /></td>
                    <td className="px-4 py-3"><div className="flex justify-end gap-2">
                      <button className={btnSecondary} onClick={() => loadHistory(check.id)}><Activity className="h-4 w-4" /> History</button>
                      {isAdmin && (<>
                        <button className={btnSecondary} onClick={() => run(check.id)} disabled={busyId === check.id} data-testid={`monitoring-run-${check.id}`}>
                          {busyId === check.id ? <Loader2 className="h-4 w-4 animate-spin" /> : <PlayCircle className="h-4 w-4" />} Run
                        </button>
                        <button className={btnSecondary} onClick={() => setEditing({ ...check })}><Edit className="h-4 w-4" /></button>
                        <button className={btnDanger} onClick={() => remove(check.id)}><Trash2 className="h-4 w-4" /></button>
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
      {editing && <CheckForm value={editing} onChange={setEditing} onSubmit={save} onClose={() => setEditing(null)} />}
    </div>
  );
};

const HistoryPanel = ({ history, onClose }) => {
  const samples = [...(history.samples || [])].reverse().map((sample) => ({
    ...sample,
    label: sample.at ? new Date(sample.at).toLocaleTimeString() : "-",
  }));
  return (
    <Card className="mt-5 p-5" data-testid="monitoring-history">
      <div className="flex items-start justify-between gap-4 mb-4">
        <div><h2 className="font-extrabold text-[#0a2350]">{history.check?.name} history</h2><p className="text-xs text-slate-500">Last probe: {stamp(history.state?.last_at)} · RTT: {history.state?.last_rtt_ms ?? "-"} ms</p></div>
        <div className="flex items-center gap-2"><StatusBadge status={history.state?.status || "unknown"} /><button onClick={onClose}><X className="h-5 w-5" /></button></div>
      </div>
      {samples.length ? <div className="h-64"><ResponsiveContainer width="100%" height="100%"><LineChart data={samples}><CartesianGrid strokeDasharray="3 3" /><XAxis dataKey="label" minTickGap={24} /><YAxis unit="ms" /><Tooltip /><Line type="monotone" dataKey="rtt_ms" stroke="#0a2350" strokeWidth={2} connectNulls={false} /></LineChart></ResponsiveContainer></div> : <EmptyState title="No samples yet" body="Run the check or wait for its next scheduled interval." />}
      {(history.events || []).length > 0 && <div className="mt-5"><div className={labelClass}>Transitions</div><div className="mt-2 space-y-2">{history.events.map((event) => <div key={event.id} className="rounded-lg bg-slate-50 px-3 py-2 text-xs"><span className="font-mono text-slate-500">{stamp(event.at)}</span> · {event.from || "unknown"} → <strong>{event.to}</strong></div>)}</div></div>}
    </Card>
  );
};

const CheckForm = ({ value, onChange, onSubmit, onClose }) => {
  const set = (key, next) => onChange({ ...value, [key]: next });
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={onClose}>
      <form className="w-full max-w-lg space-y-4 rounded-2xl bg-white p-6" onClick={(e) => e.stopPropagation()} onSubmit={onSubmit} data-testid="monitoring-form">
        <h2 className="text-lg font-extrabold text-[#0a2350]">{value.id ? "Edit monitoring check" : "Add monitoring check"}</h2>
        <label className="block"><span className={labelClass}>Name</span><input required maxLength={120} className={inputClass} value={value.name} onChange={(e) => set("name", e.target.value)} /></label>
        <label className="block"><span className={labelClass}>Public IP / hostname</span><input required maxLength={253} className={inputClass} value={value.target} onChange={(e) => set("target", e.target.value)} /></label>
        <label className="block"><span className={labelClass}>Interval (30–3600 seconds)</span><input required type="number" min="30" max="3600" className={inputClass} value={value.interval_seconds} onChange={(e) => set("interval_seconds", e.target.value)} /></label>
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={!!value.enabled} onChange={(e) => set("enabled", e.target.checked)} /> Enabled</label>
        <div className="flex justify-end gap-2"><button type="button" className={btnSecondary} onClick={onClose}>Cancel</button><button type="submit" className={btnPrimary}>Save</button></div>
      </form>
    </div>
  );
};

export default AdminMonitoring;
