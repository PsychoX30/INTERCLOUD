import React, { useEffect, useState } from "react";
import { useAuth } from "../../../portal/AuthContext";
import { api, shortDate } from "../../../portal/api";
import { PageHeader, StatusBadge } from "../ui";
import { DataTable } from "../../../components/ui/data-table";
import { Pencil, Check, Trash2, Plus } from "lucide-react";

// `embedded` is set when this page is composed as a tab inside Operations
// Center. The console owns the title; the header actions (Export PDF, Config,
// New Incident) stay because they are the actual controls.
//
// INCIDENT LIFECYCLE (2026-11-21)
// Previously this page could only CREATE an incident: the backend already had
// PUT/DELETE, but no UI reached them, so an incident could never be progressed,
// corrected, or closed. Statuses could never move past "open" and a typo in the
// start time was permanent. The table now carries per-row actions:
//   Edit          - every field including status, start/end, maintenance window
//   Mark resolved - one click: status=resolved, ended_at=now if still empty
//   Delete        - admin only (backend enforces the same rule)
// "maintenance" is a first-class status so planned work is not counted as
// unplanned downtime in the SLA report.

const STATUSES = [
  { value: "open", label: "Open" },
  { value: "maintenance", label: "Maintenance" },
  { value: "resolved", label: "Resolved" },
  { value: "postmortem", label: "Postmortem" },
];

const SEVERITIES = [
  { value: "critical", label: "Critical" },
  { value: "high", label: "High" },
  { value: "medium", label: "Medium" },
  { value: "low", label: "Low" },
];

const toLocalInput = (v) => {
  // Stored values are UTC ISO strings ("2026-11-21T03:00:00Z").
  // datetime-local inputs want "YYYY-MM-DDTHH:mm" in the browser's own zone.
  if (!v) return "";
  const d = new Date(v);
  if (Number.isNaN(d.getTime())) return "";
  const pad = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
};

const toUtc = (v) => {
  if (!v) return null;
  // A datetime-local value has no zone. Treat it as local and convert to UTC.
  const d = new Date(v);
  if (Number.isNaN(d.getTime())) return null;
  return d.toISOString();
};

const blankForm = () => ({
  title: "",
  description: "",
  severity: "medium",
  status: "open",
  started_at: toLocalInput(new Date().toISOString()),
  ended_at: "",
  maintenance_start: "",
  maintenance_end: "",
  affected_customers: [],
  root_cause: "",
  notes: "",
});

const AdminSLA = ({ embedded = false } = {}) => {
  const { user: me } = useAuth();
  const canWrite = ["admin", "support"].includes(me?.role);
  const canConfigure = me?.role === "admin";
  const canDelete = me?.role === "admin";

  const [incidents, setIncidents] = useState(null);
  const [config, setConfig] = useState(null);
  const [filters, setFilters] = useState({ status: "", severity: "", start: "", end: "", page: 1 });
  const [total, setTotal] = useState(0);
  const [showForm, setShowForm] = useState(false);
  const [editingId, setEditingId] = useState(null);
  const [showConfigModal, setShowConfigModal] = useState(false);
  const [busy, setBusy] = useState(false);
  const [form, setForm] = useState(blankForm());
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
      setIncidents([]);
    }
  };

  useEffect(() => {
    load();
  }, [filters.status, filters.severity, filters.start, filters.end, filters.page]);

  const openCreate = () => {
    setEditingId(null);
    setForm(blankForm());
    setShowForm(true);
  };

  const openEdit = (row) => {
    setEditingId(row.id);
    setForm({
      title: row.title || "",
      description: row.description || "",
      severity: row.severity || "medium",
      status: row.status || "open",
      started_at: toLocalInput(row.started_at),
      ended_at: toLocalInput(row.ended_at),
      maintenance_start: toLocalInput(row.maintenance_start),
      maintenance_end: toLocalInput(row.maintenance_end),
      affected_customers: row.affected_customers || [],
      root_cause: row.root_cause || "",
      notes: row.notes || "",
    });
    setShowForm(true);
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (busy) return;
    setBusy(true);
    const payload = {
      title: form.title,
      description: form.description,
      severity: form.severity,
      status: form.status,
      started_at: toUtc(form.started_at),
      ended_at: toUtc(form.ended_at),
      maintenance_start: toUtc(form.maintenance_start),
      maintenance_end: toUtc(form.maintenance_end),
      affected_customers: form.affected_customers,
      root_cause: form.root_cause,
      notes: form.notes,
    };
    try {
      if (editingId) {
        await api.put(`/admin/sla/incidents/${editingId}`, payload);
      } else {
        await api.post("/admin/sla/incidents", payload);
      }
      setShowForm(false);
      setEditingId(null);
      setForm(blankForm());
      load();
    } catch (err) {
      alert(err.response?.data?.detail || "Save failed");
    } finally {
      setBusy(false);
    }
  };

  const markResolved = async (row) => {
    if (!window.confirm(`Mark "${row.title}" as resolved?`)) return;
    try {
      const patch = { status: "resolved" };
      if (!row.ended_at) patch.ended_at = new Date().toISOString();
      await api.put(`/admin/sla/incidents/${row.id}`, patch);
      load();
    } catch (err) {
      alert(err.response?.data?.detail || "Update failed");
    }
  };

  const removeIncident = async (row) => {
    if (!window.confirm(`Delete incident "${row.title}"? This cannot be undone.`)) return;
    try {
      await api.delete(`/admin/sla/incidents/${row.id}`);
      load();
    } catch (err) {
      alert(err.response?.data?.detail || "Delete failed");
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
    } catch (err) {
      alert(err.response?.data?.detail || "Config save failed");
    }
  };

  const exportPDF = async () => {
    if (!filters.start || !filters.end) {
      alert("Please select start and end date");
      return;
    }
    try {
      const response = await api.get("/admin/sla/report/pdf", {
        params: { start: filters.start, end: filters.end },
        responseType: "blob",
      });
      const blobUrl = URL.createObjectURL(response.data);
      const link = document.createElement("a");
      link.href = blobUrl;
      link.download = `SLA_Report_${filters.start}_${filters.end}.pdf`;
      link.click();
      URL.revokeObjectURL(blobUrl);
    } catch (err) {
      alert(err.response?.data?.detail || "PDF export failed");
    }
  };

  const columns = [
    {
      key: "id", label: "ID", sortable: false, mono: true,
      render: (v) => <span className="font-mono text-slate-400 text-xs">{v ? String(v).slice(-8) : "-"}</span>,
    },
    { key: "started_at", label: "Started", sortable: true, render: (v) => <span className="text-slate-600">{shortDate(v)}</span> },
    { key: "ended_at", label: "Ended", sortable: true, render: (v) => <span className="text-slate-600">{v ? shortDate(v) : "-"}</span> },
    { key: "title", label: "Title", sortable: true, render: (v) => <span className="font-semibold text-[#0a2350]">{v}</span> },
    { key: "severity", label: "Severity", sortable: true, render: (v) => <StatusBadge status={v} /> },
    { key: "status", label: "Status", sortable: true, render: (v) => <StatusBadge status={v} /> },
    {
      key: "_actions", label: "", sortable: false,
      render: (_v, row) => (
        <div className="flex items-center justify-end gap-1">
          {canWrite && (
            <>
              <button
                onClick={(e) => { e.stopPropagation(); openEdit(row); }}
                title="Edit incident"
                data-testid={`sla-edit-${row.id}`}
                className="p-1.5 rounded-lg text-slate-500 hover:bg-slate-100 hover:text-[#0a2350]"
              >
                <Pencil className="h-3.5 w-3.5" />
              </button>
              {row.status !== "resolved" && (
                <button
                  onClick={(e) => { e.stopPropagation(); markResolved(row); }}
                  title="Mark as resolved"
                  data-testid={`sla-resolve-${row.id}`}
                  className="p-1.5 rounded-lg text-emerald-600 hover:bg-emerald-50"
                >
                  <Check className="h-3.5 w-3.5" />
                </button>
              )}
            </>
          )}
          {canDelete && (
            <button
              onClick={(e) => { e.stopPropagation(); removeIncident(row); }}
              title="Delete incident"
              data-testid={`sla-delete-${row.id}`}
              className="p-1.5 rounded-lg text-red-500 hover:bg-red-50"
            >
              <Trash2 className="h-3.5 w-3.5" />
            </button>
          )}
        </div>
      ),
    },
  ];

  const headerActions = (
    <div className="flex items-center gap-2">
      <button onClick={exportPDF} className="px-3 py-1.5 text-sm font-semibold bg-[#0a2350] text-white rounded-lg hover:bg-[#0a2350]/90" data-testid="sla-export-pdf">Export PDF</button>
      {canConfigure && (
        <button onClick={() => setShowConfigModal(true)} className="px-3 py-1.5 text-sm font-semibold bg-slate-100 text-slate-700 rounded-lg hover:bg-slate-200" data-testid="sla-config-btn">Config</button>
      )}
      {canWrite && (
        <button onClick={openCreate} className="px-3 py-1.5 text-sm font-semibold bg-[#f5b120] text-[#0a2350] rounded-lg hover:bg-[#f5b120]/90 inline-flex items-center gap-1.5" data-testid="sla-create-btn">
          <Plus className="h-3.5 w-3.5" /> New Incident
        </button>
      )}
    </div>
  );

  const field = "w-full border border-slate-200 rounded-lg px-3 py-2 text-sm";
  const label = "block text-xs font-semibold text-slate-500 mb-1";

  return (
    <div data-testid="sla-page">
      {embedded ? (
        <div className="flex items-center justify-end mb-3">{headerActions}</div>
      ) : (
        <PageHeader title="SLA Incidents" subtitle="Internal incident tracking and uptime reporting." actions={headerActions} />
      )}

      <div className="flex flex-wrap gap-4 mb-4 p-4 bg-[#f8fafc] rounded-lg border border-slate-200">
        <select value={filters.status} onChange={(e) => setFilters({ ...filters, status: e.target.value, page: 1 })} className="border border-slate-200 rounded-lg px-3 py-2 text-sm" data-testid="sla-filter-status">
          <option value="">All Status</option>
          {STATUSES.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
        </select>
        <select value={filters.severity} onChange={(e) => setFilters({ ...filters, severity: e.target.value, page: 1 })} className="border border-slate-200 rounded-lg px-3 py-2 text-sm">
          <option value="">All Severity</option>
          {SEVERITIES.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
        </select>
        <input type="date" value={filters.start} onChange={(e) => setFilters({ ...filters, start: e.target.value, page: 1 })} className="border border-slate-200 rounded-lg px-3 py-2 text-sm" />
        <input type="date" value={filters.end} onChange={(e) => setFilters({ ...filters, end: e.target.value, page: 1 })} className="border border-slate-200 rounded-lg px-3 py-2 text-sm" />
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

      {showForm && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50" onClick={() => setShowForm(false)}>
          <div className="bg-white rounded-xl p-6 w-full max-w-2xl max-h-[90vh] overflow-auto" onClick={(e) => e.stopPropagation()}>
            <h3 className="text-lg font-bold mb-4">{editingId ? "Edit SLA Incident" : "New SLA Incident"}</h3>
            <form onSubmit={handleSubmit}>
              <div className="space-y-4">
                <label className="block"><div className={label}>Title *</div>
                  <input required value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} className={field} placeholder="e.g. Core router outage" data-testid="sla-form-title" /></label>
                <label className="block"><div className={label}>Description</div>
                  <textarea value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} className={field} rows={3} /></label>
                <div className="grid grid-cols-2 gap-4">
                  <label className="block"><div className={label}>Severity *</div>
                    <select value={form.severity} onChange={(e) => setForm({ ...form, severity: e.target.value })} className={field} data-testid="sla-form-severity">
                      {SEVERITIES.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
                    </select></label>
                  <label className="block"><div className={label}>Status *</div>
                    <select value={form.status} onChange={(e) => setForm({ ...form, status: e.target.value })} className={field} data-testid="sla-form-status">
                      {STATUSES.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
                    </select></label>
                </div>
                <div className="grid grid-cols-2 gap-4">
                  <label className="block"><div className={label}>Started At *</div>
                    <input type="datetime-local" required value={form.started_at} onChange={(e) => setForm({ ...form, started_at: e.target.value })} className={field} data-testid="sla-form-started" /></label>
                  <label className="block"><div className={label}>Ended At</div>
                    <input type="datetime-local" value={form.ended_at} onChange={(e) => setForm({ ...form, ended_at: e.target.value })} className={field} data-testid="sla-form-ended" /></label>
                </div>

                <div className="p-3 bg-slate-50 border border-slate-200 rounded-lg">
                  <div className="text-xs font-bold text-slate-600 uppercase tracking-wide mb-2">Planned Maintenance Window</div>
                  <div className="text-xs text-slate-400 mb-2">Isi bila status = Maintenance. Rentang ini tidak dihitung sebagai downtime tak terencana di laporan SLA.</div>
                  <div className="grid grid-cols-2 gap-4">
                    <label className="block"><div className={label}>Maintenance Start</div>
                      <input type="datetime-local" value={form.maintenance_start} onChange={(e) => setForm({ ...form, maintenance_start: e.target.value })} className={field} data-testid="sla-form-maint-start" /></label>
                    <label className="block"><div className={label}>Maintenance End</div>
                      <input type="datetime-local" value={form.maintenance_end} onChange={(e) => setForm({ ...form, maintenance_end: e.target.value })} className={field} data-testid="sla-form-maint-end" /></label>
                  </div>
                </div>

                <label className="block"><div className={label}>Root Cause</div>
                  <textarea value={form.root_cause} onChange={(e) => setForm({ ...form, root_cause: e.target.value })} className={field} rows={2} /></label>
                <label className="block"><div className={label}>Notes</div>
                  <textarea value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} className={field} rows={2} /></label>
              </div>
              <div className="flex justify-end gap-2 mt-6">
                <button type="button" onClick={() => setShowForm(false)} className="px-4 py-2 text-sm font-semibold bg-slate-100 text-slate-700 rounded-lg hover:bg-slate-200">Cancel</button>
                <button type="submit" disabled={busy} className="px-4 py-2 text-sm font-semibold bg-[#f5b120] text-[#0a2350] rounded-lg hover:bg-[#f5b120]/90 disabled:opacity-60" data-testid="sla-form-submit">
                  {busy ? "Saving..." : editingId ? "Save Changes" : "Create"}
                </button>
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
                <label className="block"><div className={label}>Target Uptime % *</div>
                  <input type="number" step="0.01" min="0" max="100" required value={configForm.sla_target_uptime_percent} onChange={(e) => setConfigForm({ ...configForm, sla_target_uptime_percent: parseFloat(e.target.value) })} className={field} /></label>
                <label className="block"><div className={label}>Auto-create from NOC</div>
                  <label className="flex items-center gap-2 text-sm">
                    <input type="checkbox" checked={configForm.auto_create_sla_incidents} onChange={(e) => setConfigForm({ ...configForm, auto_create_sla_incidents: e.target.checked })} className="w-4 h-4" />
                    Create SLA incident when device goes down
                  </label></label>
                <label className="block"><div className={label}>Excluded Maintenance Windows</div>
                  <div className="text-xs text-slate-400 mb-1">One per line (e.g. "Mon 02:00-04:00")</div>
                  <textarea value={configForm.sla_excluded_maintenance_windows.join("\n")} onChange={(e) => setConfigForm({ ...configForm, sla_excluded_maintenance_windows: e.target.value.split("\n").map((s) => s.trim()).filter(Boolean) })} className={field} rows={4} /></label>
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
