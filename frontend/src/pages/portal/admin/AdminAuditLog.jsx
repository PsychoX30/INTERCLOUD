import React, { useEffect, useState, useCallback } from "react";
import { api } from "../../../portal/api";
import { PageHeader, Card, Loading, EmptyState, btnSecondary, inputClass, labelClass } from "../ui";
import { RefreshCw, Filter, Search, ShieldAlert, ShieldCheck, Info, ChevronLeft, ChevronRight, Eye } from "lucide-react";

const SEVERITY_STYLES = {
  info:     { bg: "bg-slate-100 text-slate-700 border-slate-300",   Icon: Info },
  warning:  { bg: "bg-amber-100 text-amber-800 border-amber-300",   Icon: ShieldAlert },
  critical: { bg: "bg-red-100 text-red-700 border-red-300",         Icon: ShieldAlert },
};
const CATEGORY_TONES = {
  security:     "bg-red-50 text-red-700 border-red-200",
  billing:      "bg-emerald-50 text-emerald-700 border-emerald-200",
  integrations: "bg-indigo-50 text-indigo-700 border-indigo-200",
  users:        "bg-sky-50 text-sky-700 border-sky-200",
  system:       "bg-slate-100 text-slate-700 border-slate-300",
  noc:          "bg-purple-50 text-purple-700 border-purple-200",
};

const PAGE_SIZE = 25;

const AdminAuditLog = () => {
  const [rows, setRows] = useState([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [facets, setFacets] = useState({ categories: [], actions: [], severities: [] });
  const [page, setPage] = useState(0);
  const [filters, setFilters] = useState({
    q: "", category: "", action: "", severity: "", date_from: "", date_to: "",
  });
  const [detail, setDetail] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    const params = new URLSearchParams();
    params.set("limit", PAGE_SIZE);
    params.set("skip", page * PAGE_SIZE);
    for (const [k, v] of Object.entries(filters)) {
      if (v) params.set(k, v);
    }
    try {
      const r = await api.get(`/admin/audit-logs?${params.toString()}`);
      setRows(r.data.items || []);
      setTotal(r.data.total || 0);
    } finally { setLoading(false); }
  }, [page, filters]);

  useEffect(() => {
    api.get("/admin/audit-logs/facets").then((r) => setFacets(r.data)).catch(() => {});
  }, []);
  useEffect(() => { load(); }, [load]);

  const set = (k, v) => { setFilters((f) => ({ ...f, [k]: v })); setPage(0); };
  const clearAll = () => { setFilters({ q: "", category: "", action: "", severity: "", date_from: "", date_to: "" }); setPage(0); };

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  return (
    <div data-testid="audit-log-page">
      <PageHeader
        title="Audit Log"
        subtitle="Every sensitive administrative action (role changes, integrations, billing settings, factory reset, credit notes, backup restore, NOC alerts) is recorded here with actor, timestamp, IP, and a before/after snapshot."
        actions={
          <button className={btnSecondary} onClick={load} data-testid="audit-refresh">
            <RefreshCw className="h-4 w-4" /> Refresh
          </button>
        }
      />

      {/* Filters */}
      <Card className="p-4 mb-4">
        <div className="flex items-center gap-2 mb-3">
          <Filter className="h-4 w-4 text-slate-500" />
          <div className="text-sm font-semibold text-slate-700">Filters</div>
          <button onClick={clearAll} className="ml-auto text-xs text-slate-500 hover:text-[#0a2350] underline" data-testid="audit-clear-filters">Clear all</button>
        </div>
        <div className="grid grid-cols-2 md:grid-cols-6 gap-2">
          <div className="col-span-2 md:col-span-2">
            <label className={labelClass}>Search</label>
            <div className="relative">
              <Search className="h-4 w-4 absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-400" />
              <input value={filters.q} onChange={(e) => set("q", e.target.value)}
                     placeholder="Actor email, action, target"
                     className={inputClass + " pl-8"} data-testid="audit-search" />
            </div>
          </div>
          <div>
            <label className={labelClass}>Category</label>
            <select value={filters.category} onChange={(e) => set("category", e.target.value)} className={inputClass} data-testid="audit-category">
              <option value="">All</option>
              {(facets.categories || []).map((c) => <option key={c} value={c}>{c}</option>)}
            </select>
          </div>
          <div>
            <label className={labelClass}>Action</label>
            <select value={filters.action} onChange={(e) => set("action", e.target.value)} className={inputClass} data-testid="audit-action">
              <option value="">All</option>
              {(facets.actions || []).map((c) => <option key={c} value={c}>{c}</option>)}
            </select>
          </div>
          <div>
            <label className={labelClass}>Severity</label>
            <select value={filters.severity} onChange={(e) => set("severity", e.target.value)} className={inputClass} data-testid="audit-severity">
              <option value="">All</option>
              {(facets.severities || []).map((c) => <option key={c} value={c}>{c}</option>)}
            </select>
          </div>
          <div>
            <label className={labelClass}>From</label>
            <input type="date" value={filters.date_from} onChange={(e) => set("date_from", e.target.value)} className={inputClass} data-testid="audit-date-from" />
          </div>
          <div>
            <label className={labelClass}>To</label>
            <input type="date" value={filters.date_to} onChange={(e) => set("date_to", e.target.value)} className={inputClass} data-testid="audit-date-to" />
          </div>
        </div>
      </Card>

      <Card className="overflow-hidden">
        {loading ? <Loading /> : rows.length === 0 ? (
          <EmptyState title="No audit entries" body="Perform a sensitive action (edit billing settings, apply a credit note, change a user role) and it will appear here." />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm" data-testid="audit-table">
              <thead className="bg-slate-50 text-[11px] uppercase tracking-widest text-slate-500">
                <tr>
                  <th className="text-left px-4 py-3">When</th>
                  <th className="text-left px-4 py-3">Actor</th>
                  <th className="text-left px-4 py-3">Action</th>
                  <th className="text-left px-4 py-3">Target</th>
                  <th className="text-left px-4 py-3">Severity</th>
                  <th className="text-left px-4 py-3">IP</th>
                  <th className="text-right px-4 py-3"></th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => {
                  const sev = SEVERITY_STYLES[r.severity] || SEVERITY_STYLES.info;
                  const SevIcon = sev.Icon;
                  return (
                    <tr key={r.id} className="border-t border-slate-100 hover:bg-slate-50/60" data-testid={`audit-row-${r.id}`}>
                      <td className="px-4 py-3 whitespace-nowrap text-slate-700">
                        <div className="font-medium">{(r.created_at || "").slice(0, 10)}</div>
                        <div className="text-xs text-slate-500">{(r.created_at || "").slice(11, 19)} UTC</div>
                      </td>
                      <td className="px-4 py-3">
                        <div className="font-semibold text-[#0a2350]">{r.actor_email}</div>
                        <div className="text-xs text-slate-500">{r.actor_role}</div>
                      </td>
                      <td className="px-4 py-3">
                        <div className="font-mono text-xs text-slate-800">{r.action}</div>
                        <span className={`inline-block mt-1 px-2 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-widest border ${CATEGORY_TONES[r.category] || "bg-slate-100 text-slate-700 border-slate-300"}`}>{r.category}</span>
                      </td>
                      <td className="px-4 py-3 max-w-[240px] truncate" title={r.target_label}>{r.target_label || "—"}</td>
                      <td className="px-4 py-3">
                        <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full border text-[11px] font-bold uppercase ${sev.bg}`}>
                          <SevIcon className="h-3 w-3" /> {r.severity}
                        </span>
                      </td>
                      <td className="px-4 py-3 font-mono text-xs text-slate-600">{r.ip || "—"}</td>
                      <td className="px-4 py-3 text-right">
                        <button onClick={() => setDetail(r)} className="text-slate-500 hover:text-[#0a2350]" data-testid={`audit-view-${r.id}`}>
                          <Eye className="h-4 w-4" />
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
        {/* Pagination */}
        <div className="flex items-center justify-between px-4 py-3 border-t border-slate-100 text-xs text-slate-600">
          <div data-testid="audit-total">Showing {rows.length ? page * PAGE_SIZE + 1 : 0}–{page * PAGE_SIZE + rows.length} of {total}</div>
          <div className="flex items-center gap-2">
            <button disabled={page === 0} onClick={() => setPage((p) => Math.max(0, p - 1))} className={`p-1.5 rounded hover:bg-slate-100 ${page === 0 && "opacity-30 cursor-not-allowed"}`} data-testid="audit-prev"><ChevronLeft className="h-4 w-4" /></button>
            <span>Page {page + 1} / {totalPages}</span>
            <button disabled={page + 1 >= totalPages} onClick={() => setPage((p) => p + 1)} className={`p-1.5 rounded hover:bg-slate-100 ${page + 1 >= totalPages && "opacity-30 cursor-not-allowed"}`} data-testid="audit-next"><ChevronRight className="h-4 w-4" /></button>
          </div>
        </div>
      </Card>

      {detail && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={() => setDetail(null)} data-testid="audit-detail-modal">
          <div className="bg-white rounded-2xl max-w-2xl w-full max-h-[85vh] overflow-y-auto shadow-2xl" onClick={(e) => e.stopPropagation()}>
            <div className="p-5 border-b border-slate-200 flex items-start justify-between">
              <div>
                <div className="text-xs uppercase tracking-widest text-slate-500">Audit entry</div>
                <div className="text-lg font-extrabold text-[#0a2350]">{detail.action}</div>
                <div className="text-xs text-slate-500 mt-1">{detail.created_at}</div>
              </div>
              <button onClick={() => setDetail(null)} className="text-slate-400 hover:text-slate-700 text-xl" data-testid="audit-detail-close">×</button>
            </div>
            <div className="p-5 space-y-3 text-sm">
              <div className="grid grid-cols-2 gap-3">
                <Field label="Actor" value={`${detail.actor_email} (${detail.actor_role})`} />
                <Field label="Target" value={detail.target_label || "—"} />
                <Field label="IP" value={detail.ip || "—"} mono />
                <Field label="Severity" value={detail.severity} />
              </div>
              {detail.user_agent && <Field label="User Agent" value={detail.user_agent} mono />}
              {detail.before && (
                <div>
                  <div className={labelClass + " mb-1"}>Before</div>
                  <pre className="bg-slate-50 border border-slate-200 rounded-lg p-3 text-xs overflow-x-auto">{JSON.stringify(detail.before, null, 2)}</pre>
                </div>
              )}
              {detail.after && (
                <div>
                  <div className={labelClass + " mb-1"}>After</div>
                  <pre className="bg-slate-50 border border-slate-200 rounded-lg p-3 text-xs overflow-x-auto">{JSON.stringify(detail.after, null, 2)}</pre>
                </div>
              )}
              {detail.metadata && Object.keys(detail.metadata).length > 0 && (
                <div>
                  <div className={labelClass + " mb-1"}>Metadata</div>
                  <pre className="bg-slate-50 border border-slate-200 rounded-lg p-3 text-xs overflow-x-auto">{JSON.stringify(detail.metadata, null, 2)}</pre>
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

const Field = ({ label, value, mono }) => (
  <div>
    <div className={labelClass}>{label}</div>
    <div className={`text-sm ${mono ? "font-mono" : ""} text-slate-800`}>{value}</div>
  </div>
);

export default AdminAuditLog;
