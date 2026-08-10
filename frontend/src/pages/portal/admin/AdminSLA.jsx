import React, { useEffect, useState } from "react";
import { useAuth } from "../../../portal/AuthContext";
import { api, money, shortDate } from "../../../portal/api";
import { PageHeader, StatusBadge } from "../ui";
import { DataTable } from "../../../components/ui/data-table";

const AdminSLA = () => {
  const { user: me } = useAuth();
  const canWrite = ["admin", "support"].includes(me?.role);
  const canConfigure = me?.role === "admin";

  const [incidents, setIncidents] = useState(null);
  const [config, setConfig] = useState(null);
  const [filters, setFilters] = useState({ status: "", severity: "", start: "", end: "", page: 1 });
  const [total, setTotal] = useState(0);
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [showConfigModal, setShowConfigModal] = useState(false);
  const [form, setForm] = useState({
    title: "",
    description: "",
    severity: "medium",
    started_at: new Date().toISOString().slice(0, 16),
    ended_at: "",
    affected_customers: [],
    root_cause: "",
    notes: "",
  });
  const [configForm, setConfigForm] = useState({
    sla_target_uptime_percent: 99.5,
    sla_excluded_maintenance_windows: [],
    auto_create_sla_incidents: false,
  });

  const load = async () => {
    const params = { ...filters };
    if (params.start) params.start = params.start + "T00:00:00";
    if (params.end) params.end = params.end + "T23:59:59";
    try {
      const r1 = await api.get("/admin/sla/incidents", { params });
      setIncidents(r1.data.results);
      setTotal(r1.data.total);
      if (canConfigure) {
        const r2 = await api.get("/admin/sla/config");
        setConfig(r2.data);
        setConfigForm(r2.data);
      }
    } catch (e) {
      console.error(e);
    }
  };

  useEffect(() => { load(); }, [filters.status, filters.severity, filters.start, filters.end, filters.page]);

  const handleCreate = async (e) => {
    e.preventDefault();
    try {
      await api.post("/admin/sla/incidents", {
        title: form.title,
        description: form.description,
        severity: form.severity,
        started_at: form.started_at + ":00Z",
        ended_at: form.ended_at ? form.ended_at + ":00Z" : null,
        affected_customers: form.affected_customers,
        root_cause: form.root_cause,
        notes: form.notes,
      });
      setShowCreateModal(false);
      setForm({ title: "", description: "", severity: "medium", started_at: new Date().toISOString().slice(0, 16), ended_at: "", affected_customers: [], root_cause: "", notes: "" });
      load();
    } catch (e) {
      alert(e.response?.data?.detail || "Create failed");
    }
  };

  const handleConfigSave = async (e) => {
    e.preventDefault();
    try {
      await api.put("/admin/sla/config", {
        sla_target_uptime_percent: configForm.sla_target_uptime_percent,
        sla_excluded_maintenance_windows: configForm.sla_excluded_maintenance_windows,
        auto_create_sla_incidents: configForm.auto_create_sla_incidents,
      });
      setShowConfigModal(false);
      load();
    } catch (e) {
      alert(e.response?.data?.detail || "Config save failed");
    }
  };

  const exportPDF = async () => {
    if (!filters.start || !filters.end) {
      alert("Please select start and end date");
      return;
    }
    try {
      const response = await api.get("/admin/sla/report/pdf", { params: { start: filters.start, end: filters.end }, responseType: "blob" });
      const blobUrl = URL.createObjectURL(response.data);
      const link = document.createElement("a");
      link.href = blobUrl;
      link.download = `SLA_Report_${filters.start}_${filters.end}.pdf`;
      link.click();
      URL.revokeObjectURL(blobUrl);
    } catch (e) {
      alert(e.response?.data?.detail || "PDF export failed");
    }
  };

  const columns = [
    { key: "id", label: "ID", sortable: false, mono: true, render: (v) => <span className="font-mono text-slate-400 text-xs">{v ? String(v).slice(-8) : "-"}</span> },
    { key: "started_at", label: "Started", sortable: true, render: (v) => <span className="text-slate-600">{shortDate(v)}</span> },
    { key: "ended_at", label: "Ended", sortable: true, render: (v) => <span className="text-slate-600">{v ? shortDate(v) : "-"}</span> },
    { key: "title", label: "Title", sortable: true, render: (v) => <span className="font-semibold text-[#0a2350]">{v}</span> },
    { key: "severity", label: "Severity", sortable: true, render: (v) => <StatusBadge status={v} /> },
    { key: "status", label: "Status", sortable: true, render: (v) => <StatusBadge status={v} /> },
  ];

  return (
    <div>
      <PageHeader
        title="SLA Incidents"
        subtitle="Internal incident tracking and uptime reporting."
        actions={
          <div className="flex items-center gap-2">
            <button onClick={exportPDF} className="px-3 py-1.5 text-sm font-semibold bg-[#0a2350] text-white rounded-lg hover:bg-[#0a2350]/90" data-testid="sla-export-pdf">Export PDF</button>
            {canConfigure && (
              <button onClick={() => setShowConfigModal(true)} className="px-3 py-1.5 text-sm font-semibold bg-slate-100 text-slate-700 rounded-lg hover:bg-slate-200" data-testid="sla-config-btn">Config</button>
            )}
            {canWrite && (
              <button onClick={() => setShowCreateModal(true)} className="px-3 py-1.5 text-sm font-semibold bg-[#f5b120] text-[#0a2350] rounded-lg hover:bg-[#f5b120]/90" data-testid="sla-create-btn">New Incident</button>
            )}
          </div>
        }
      />
      <div className="flex flex-wrap gap-4 mb-4 p-4 bg-[#f8fafc] rounded-lg border border-slate-200">
        <select value={filters.status} onChange={(e) => setFilters({ ...filters, status: e.target.value, page: 1 })} className="border border-slate-200 rounded-lg px-3 py-2 text-sm">
          <option value="">All Status</option>
          <option value="open">Open</option>
          <option value="resolved">Resolved</option>
          <option value="postmortem">Postmortem</option>
        </select>
        <select value={filters.severity} onChange={(e) => setFilters({ ...filters, severity: e.target.value, page: 1 })} className="border border-slate-200 rounded-lg px-3 py-2 text-sm">
          <option value="">All Severity</option>
          <option value="critical">Critical</option>
          <option value="high">High</option>
          <option value="medium">Medium</option>
          <option value="low">Low</option>
        </select>
        <input type="date" value={filters.start} onChange={(e) => setFilters({ ...filters, start: e.target.value, page: 1 })} className="border border-slate-200 rounded-lg px-3 py-2 text-sm" placeholder="Start Date" />
        <input type="date" value={filters.end} onChange={(e) => setFilters({ ...filters, end: e.target.value, page: 1 })} className="border border-slate-200 rounded-lg px-3 py-2 text-sm" placeholder="End Date" />
      </div>
      <DataTable
        rows={incidents || []}
        loading={incidents === null}
        columns={columns}
        searchKeys={["title", "description", "severity", "status"]}
        rowKey={(r) => r.id}
        pagination={{ page: filters.page, total, limit: 50, onChange: (p) => setFilters({ ...filters, page: p }) }}
        empty={{ title: "No incidents", hint: "Create your first SLA incident or wait for NOC auto-creation." }}
        testid="admin-sla-table"
      />
      {showCreateModal && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50" onClick={() => setShowCreateModal(false)}>
          <div className="bg-white rounded-xl p-6 w-full max-w-2xl max-h-[90vh] overflow-auto" onClick={(e) => e.stopPropagation()}>
            <h3 className="text-lg font-bold mb-4">New SLA Incident</h3>
            <form onSubmit={handleCreate}>
              <div className="space-y-4">
                <label className="block"><div className="text-xs font-semibold text-slate-500 mb-1">Title *</div><input required value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} className="w-full border border-slate-200 rounded-lg px-3 py-2" placeholder="e.g. Core router outage" /></label>
                <label className="block"><div className="text-xs font-semibold text-slate-500 mb-1">Description</div><textarea value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} className="w-full border border-slate-200 rounded-lg px-3 py-2" rows={3} /></label>
                <label className="block"><div className="text-xs font-semibold text-slate-500 mb-1">Severity *</div><select value={form.severity} onChange={(e) => setForm({ ...form, severity: e.target.value })} className="w-full border border-slate-200 rounded-lg px-3 py-2"><option value="critical">Critical</option><option value="high">High</option><option value="medium">Medium</option><option value="low">Low</option></select></label>
                <label className="block"><div className="text-xs font-semibold text-slate-500 mb-1">Started At *</div><input type="datetime-local" required value={form.started_at} onChange={(e) => setForm({ ...form, started_at: e.target.value })} className="w-full border border-slate-200 rounded-lg px-3 py-2" /></label>
                <label className="block"><div className="text-xs font-semibold text-slate-500 mb-1">Ended At</div><input type="datetime-local" value={form.ended_at} onChange={(e) => setForm({ ...form, ended_at: e.target.value })} className="w-full border border-slate-200 rounded-lg px-3 py-2" /></label>
                <label className="block"><div className="text-xs font-semibold text-slate-500 mb-1">Root Cause</div><textarea value={form.root_cause} onChange={(e) => setForm({ ...form, root_cause: e.target.value })} className="w-full border border-slate-200 rounded-lg px-3 py-2" rows={2} /></label>
                <label className="block"><div className="text-xs font-semibold text-slate-500 mb-1">Notes</div><textarea value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} className="w-full border border-slate-200 rounded-lg px-3 py-2" rows={2} /></label>
              </div>
              <div className="flex justify-end gap-2 mt-6">
                <button type="button" onClick={() => setShowCreateModal(false)} className="px-4 py-2 text-sm font-semibold bg-slate-100 text-slate-700 rounded-lg hover:bg-slate-200">Cancel</button>
                <button type="submit" className="px-4 py-2 text-sm font-semibold bg-[#f5b120] text-[#0a2350] rounded-lg hover:bg-[#f5b120]/90">Create</button>
              </div>
            </form>
          </div>
        </div>
      )}
      {showConfigModal && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50" onClick={() => setShowConfigModal(false)}>
          <div className="bg-white rounded-xl p-6 w-full max-w-lg max-h-[90vh] overflow-auto" onClick={(e) => e.stopPropagation()}>
            <h3 className="text-lg font-bold mb-4">SLA Configuration</h3>
            <form onSubmit={handleConfigSave}>
              <div className="space-y-4">
                <label className="block"><div className="text-xs font-semibold text-slate-500 mb-1">Target Uptime % *</div><input type="number" step="0.01" min="0" max="100" required value={configForm.sla_target_uptime_percent} onChange={(e) => setConfigForm({ ...configForm, sla_target_uptime_percent: parseFloat(e.target.value) })} className="w-full border border-slate-200 rounded-lg px-3 py-2" /></label>
                <label className="block"><div className="text-xs font-semibold text-slate-500 mb-1">Auto-create from NOC</div><label className="flex items-center gap-2"><input type="checkbox" checked={configForm.auto_create_sla_incidents} onChange={(e) => setConfigForm({ ...configForm, auto_create_sla_incidents: e.target.checked })} className="w-4 h-4" /> Create SLA incident when device goes down</label></label>
                <label className="block"><div className="text-xs font-semibold text-slate-500 mb-1">Excluded Maintenance Windows</div><div className="text-xs text-slate-400 mb-1">One per line (e.g. \"Mon 02:00-04:00\")</div><textarea value={configForm.sla_excluded_maintenance_windows.join("\n")} onChange={(e) => setConfigForm({ ...configForm, sla_excluded_maintenance_windows: e.target.value.split("\n").map((s) => s.trim()).filter(Boolean) })} className="w-full border border-slate-200 rounded-lg px-3 py-2" rows={4} /></label>
              </div>
              <div className="flex justify-end gap-2 mt-6">
                <button type="button" onClick={() => setShowConfigModal(false)} className="px-4 py-2 text-sm font-semibold bg-slate-100 text-slate-700 rounded-lg hover:bg-slate-200">Cancel</button>
                <button type="submit" className="px-4 py-2 text-sm font-semibold bg-[#0a2350] text-white rounded-lg hover:bg-[#0a2350]/90">Save</button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
};

export default AdminSLA;