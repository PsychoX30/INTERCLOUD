import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, shortDate, fullDateTime } from "../../../portal/api";
import { PageHeader, Card, Loading, EmptyState, StatusBadge, btnPrimary, btnSecondary, inputClass, labelClass } from "../ui";
import { Plus, Edit, Trash2, CheckCircle2, Circle, FileText, ExternalLink, Flame } from "lucide-react";

/* ============ Small generic modal ============ */
const Modal = ({ children, onClose, title }) => (
  <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4" onClick={onClose}>
    <div onClick={(e) => e.stopPropagation()} className="w-full max-w-lg bg-white rounded-3xl p-6 max-h-[92vh] overflow-y-auto">
      <h3 className="text-xl font-extrabold text-[#0a2350] mb-4">{title}</h3>
      {children}
    </div>
  </div>
);

/* =========================================================================
   CRM — Customers / Prospects
   ========================================================================= */
const idr = (v) => "Rp" + Number(v || 0).toLocaleString("en-US", { minimumFractionDigits: 0, maximumFractionDigits: 0 });

const ORDER_STATUS_TONE = {
  pending: "bg-slate-100 text-slate-700",
  pending_payment: "bg-amber-100 text-amber-800",
  awaiting_verification: "bg-amber-100 text-amber-800",
  awaiting_quote: "bg-sky-100 text-sky-800",
  payment_verified: "bg-indigo-100 text-indigo-800",
  assigned: "bg-indigo-100 text-indigo-800",
  provisioning: "bg-indigo-100 text-indigo-800",
  active: "bg-emerald-100 text-emerald-800",
  rejected: "bg-rose-100 text-rose-800",
  cancelled: "bg-slate-100 text-slate-500 line-through",
};
const OrderStatusChip = ({ status }) => (
  <span className={`inline-block px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider ${ORDER_STATUS_TONE[status] || "bg-slate-100 text-slate-600"}`}>
    {(status || "").replace(/_/g, " ")}
  </span>
);

const STATUSES = [
  ["prospect", "Prospect"],
  ["partnership", "Possible Partnership"],
  ["existing", "Existing Client"],
  ["ex_client", "Ex-Client"],
];
export const AdminCRM = () => {
  const [rows, setRows] = useState(null);
  const [q, setQ] = useState("");
  const [statusF, setStatusF] = useState("");
  const [warmOnly, setWarmOnly] = useState(false);
  const [editing, setEditing] = useState(null); // null | 'new' | obj
  const load = () => api.get("/admin/crm").then((r) => setRows(r.data));
  useEffect(() => { load(); }, []);
  if (!rows) return <Loading />;

  const filtered = rows.filter((r) =>
    (!statusF || r.status === statusF) &&
    (!warmOnly || r.is_warm) &&
    (!q || `${r.name} ${r.email} ${r.company} ${r.industry}`.toLowerCase().includes(q.toLowerCase()))
  );
  const warmCount = rows.filter((r) => r.is_warm).length;
  const totalLTV = rows.reduce((s, r) => s + (Number(r.lifetime_value) || 0), 0);

  const del = async (id) => { if (window.confirm("Delete?")) { await api.delete(`/admin/crm/${id}`); load(); } };

  return (
    <div>
      <PageHeader
        title="Customer Database (CRM)"
        subtitle="Prospects, partnerships, existing & past clients — all in one directory."
        actions={<button className={btnPrimary} onClick={() => setEditing("new")} data-testid="new-crm-btn"><Plus className="h-4 w-4" /> Add Contact</button>}
      />

      {/* KPI strip */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4">
        <Card className="p-4">
          <div className="text-[11px] font-bold uppercase tracking-widest text-slate-500">Total contacts</div>
          <div className="text-2xl font-extrabold text-[#0a2350] mt-0.5" data-testid="crm-kpi-total">{rows.length}</div>
        </Card>
        <Card className="p-4">
          <div className="text-[11px] font-bold uppercase tracking-widest text-slate-500 flex items-center gap-1"><Flame className="h-3.5 w-3.5 text-orange-500" /> Warm leads</div>
          <div className="text-2xl font-extrabold text-orange-600 mt-0.5" data-testid="crm-kpi-warm">{warmCount}</div>
        </Card>
        <Card className="p-4">
          <div className="text-[11px] font-bold uppercase tracking-widest text-slate-500">Existing / active</div>
          <div className="text-2xl font-extrabold text-emerald-700 mt-0.5" data-testid="crm-kpi-existing">
            {rows.filter((r) => r.status === "existing").length}
          </div>
        </Card>
        <Card className="p-4">
          <div className="text-[11px] font-bold uppercase tracking-widest text-slate-500">Lifetime value paid</div>
          <div className="text-2xl font-extrabold text-[#0a2350] mt-0.5" data-testid="crm-kpi-ltv">{idr(totalLTV)}</div>
        </Card>
      </div>

      <div className="mb-3 flex gap-2 flex-wrap items-center">
        <input placeholder="Search…" value={q} onChange={(e) => setQ(e.target.value)} className={`${inputClass} max-w-xs`} data-testid="crm-search" />
        <select value={statusF} onChange={(e) => setStatusF(e.target.value)} className={`${inputClass} max-w-[220px]`}>
          <option value="">All statuses</option>
          {STATUSES.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
        </select>
        <label className="inline-flex items-center gap-2 text-sm text-slate-600 cursor-pointer select-none" data-testid="crm-warm-toggle">
          <input type="checkbox" checked={warmOnly} onChange={(e) => setWarmOnly(e.target.checked)} />
          <Flame className="h-4 w-4 text-orange-500" />
          Warm leads only ({warmCount})
        </label>
      </div>
      {filtered.length === 0 && <EmptyState title="No contacts" />}
      {filtered.length > 0 && (
        <div className="rounded-2xl bg-white border border-slate-200 overflow-x-auto">
          <table className="w-full min-w-[720px] text-sm">
            <thead className="bg-slate-50 text-[11px] font-bold uppercase tracking-widest text-slate-500">
              <tr>
                <th className="px-4 py-3 text-left">Name / Company</th>
                <th className="px-4 py-3 text-left">Email · Phone</th>
                <th className="px-4 py-3 text-left">Industry</th>
                <th className="px-4 py-3 text-left">Latest order</th>
                <th className="px-4 py-3 text-right">Lifetime value</th>
                <th className="px-4 py-3 text-left">Status</th>
                <th className="px-4 py-3 text-right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((c) => (
                <tr key={c.id} className={`border-t border-slate-100 ${c.is_warm ? "bg-orange-50/40" : ""}`} data-testid={`crm-${c.id}`}>
                  <td className="px-4 py-3">
                    <div className="font-semibold text-[#0a2350] flex items-center gap-2">
                      {c.name}
                      {c.is_warm && (
                        <span
                          title={`${c.in_progress_count} order(s) in progress`}
                          className="inline-flex items-center gap-1 text-[10px] font-bold uppercase tracking-wider bg-orange-100 text-orange-700 px-1.5 py-0.5 rounded"
                          data-testid={`crm-warm-badge-${c.id}`}
                        >
                          <Flame className="h-3 w-3" /> Warm
                        </span>
                      )}
                      {c.user_id && !c.is_warm && (
                        <span
                          title={`Linked to portal user • source: ${c.source || "manual"}`}
                          className="inline-flex items-center gap-1 text-[10px] font-bold uppercase tracking-wider bg-emerald-100 text-emerald-700 px-1.5 py-0.5 rounded"
                          data-testid={`crm-portal-badge-${c.id}`}
                        >
                          Portal user
                        </span>
                      )}
                    </div>
                    <div className="text-xs text-slate-500">{c.company || "—"}</div>
                  </td>
                  <td className="px-4 py-3">
                    <div>{c.email || "—"}</div>
                    <div className="text-xs text-slate-500">{c.phone || "—"}</div>
                  </td>
                  <td className="px-4 py-3">{c.industry || "—"}</td>
                  <td className="px-4 py-3" data-testid={`crm-latest-order-${c.id}`}>
                    {c.latest_order ? (
                      <div className="flex flex-col gap-0.5">
                        <div className="flex items-center gap-2">
                          <OrderStatusChip status={c.latest_order.status} />
                          {c.in_progress_count > 0 && (
                            <span className="text-[10px] font-bold text-orange-600">
                              +{c.in_progress_count} in progress
                            </span>
                          )}
                        </div>
                        <Link
                          to="/portal/admin/orders"
                          className="text-xs text-slate-600 hover:text-[#f5b120] truncate max-w-[220px] inline-block"
                          title={c.latest_order.product_name}
                        >
                          {c.latest_order.product_name || "—"}
                        </Link>
                        <div className="text-[10px] text-slate-400">{shortDate(c.latest_order.created_at)}</div>
                      </div>
                    ) : (
                      <span className="text-slate-400 text-xs">No orders yet</span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-right">
                    <div className={`font-extrabold ${c.lifetime_value > 0 ? "text-[#0a2350]" : "text-slate-400"}`} data-testid={`crm-ltv-${c.id}`}>
                      {c.lifetime_value > 0 ? idr(c.lifetime_value) : "—"}
                    </div>
                    {c.won_orders_count > 0 && (
                      <div className="text-[10px] text-slate-500">{c.won_orders_count} active service{c.won_orders_count > 1 ? "s" : ""}</div>
                    )}
                  </td>
                  <td className="px-4 py-3"><StatusBadge status={c.status} /></td>
                  <td className="px-4 py-3 text-right">
                    <button className="text-slate-600 hover:text-[#f5b120]" onClick={() => setEditing(c)}><Edit className="h-4 w-4 inline" /></button>
                    <button className="ml-3 text-slate-600 hover:text-red-600" onClick={() => del(c.id)}><Trash2 className="h-4 w-4 inline" /></button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {editing && <CrmForm c={editing === "new" ? null : editing} onClose={() => setEditing(null)} onDone={() => { setEditing(null); load(); }} />}
    </div>
  );
};

const CrmForm = ({ c, onClose, onDone }) => {
  const [f, setF] = useState({
    name: c?.name || "", email: c?.email || "", phone: c?.phone || "",
    company: c?.company || "", position: c?.position || "", industry: c?.industry || "",
    status: c?.status || "prospect", notes: c?.notes || "",
  });
  const submit = async (e) => {
    e.preventDefault();
    if (c) await api.put(`/admin/crm/${c.id}`, f);
    else await api.post("/admin/crm", f);
    onDone();
  };
  return (
    <Modal onClose={onClose} title={c ? "Edit contact" : "New contact"}>
      <form onSubmit={submit} className="grid grid-cols-2 gap-3" data-testid="crm-form">
        <label className="col-span-2"><div className={labelClass}>Full name *</div><input required value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} className={inputClass} data-testid="crm-name" /></label>
        <label><div className={labelClass}>Email</div><input type="email" value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} className={inputClass} /></label>
        <label><div className={labelClass}>Phone</div><input value={f.phone} onChange={(e) => setF({ ...f, phone: e.target.value })} className={inputClass} /></label>
        <label><div className={labelClass}>Company</div><input value={f.company} onChange={(e) => setF({ ...f, company: e.target.value })} className={inputClass} /></label>
        <label><div className={labelClass}>Position</div><input value={f.position} onChange={(e) => setF({ ...f, position: e.target.value })} className={inputClass} /></label>
        <label><div className={labelClass}>Industry</div><input value={f.industry} onChange={(e) => setF({ ...f, industry: e.target.value })} className={inputClass} placeholder="Fintech, ISP, Retail…" /></label>
        <label><div className={labelClass}>Status</div><select value={f.status} onChange={(e) => setF({ ...f, status: e.target.value })} className={inputClass}>{STATUSES.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select></label>
        <label className="col-span-2"><div className={labelClass}>Notes</div><textarea rows={3} value={f.notes} onChange={(e) => setF({ ...f, notes: e.target.value })} className={`${inputClass} h-auto py-2`} /></label>
        <div className="col-span-2 flex justify-end gap-2 mt-2">
          <button type="button" className={btnSecondary} onClick={onClose}>Cancel</button>
          <button type="submit" className={btnPrimary} data-testid="crm-submit">Save</button>
        </div>
      </form>
    </Modal>
  );
};

/* =========================================================================
   Projects
   ========================================================================= */
const PROJ_STATUS = [["planning", "Planning"], ["in_progress", "In Progress"], ["on_hold", "On Hold"], ["done", "Done"], ["cancelled", "Cancelled"]];
const PROJ_PRIO = [["low", "Low"], ["medium", "Medium"], ["high", "High"], ["critical", "Critical"]];
export const AdminProjects = () => {
  const [rows, setRows] = useState(null);
  const [editing, setEditing] = useState(null);
  const load = () => api.get("/admin/projects").then((r) => setRows(r.data));
  useEffect(() => { load(); }, []);
  if (!rows) return <Loading />;
  const del = async (id) => { if (window.confirm("Delete?")) { await api.delete(`/admin/projects/${id}`); load(); } };
  return (
    <div>
      <PageHeader
        title="Project Tracker"
        subtitle="Ongoing work — implementation projects, migrations, and internal initiatives."
        actions={<button className={btnPrimary} onClick={() => setEditing("new")} data-testid="new-proj-btn"><Plus className="h-4 w-4" /> New Project</button>}
      />
      {rows.length === 0 && <EmptyState title="No projects" />}
      <div className="grid md:grid-cols-2 gap-4">
        {rows.map((p) => (
          <Card key={p.id} className="p-5" data-testid={`proj-${p.id}`}>
            <div className="flex items-start justify-between">
              <div>
                <div className="text-[10px] font-bold uppercase tracking-widest text-[#f5b120]">{p.priority}</div>
                <div className="text-lg font-extrabold text-[#0a2350] leading-tight">{p.name}</div>
                <div className="text-xs text-slate-500 mt-0.5">Customer: {p.customer_name || "—"} · Owner: {p.owner || "—"}</div>
              </div>
              <StatusBadge status={p.status} />
            </div>
            <div className="mt-3 h-2 bg-slate-100 rounded-full overflow-hidden">
              <div className="h-full bg-gradient-to-r from-[#f5b120] to-[#0a2350]" style={{ width: `${p.progress || 0}%` }} />
            </div>
            <div className="text-[11px] text-slate-500 mt-1">{p.progress || 0}% complete · Target {shortDate(p.target_date) || "—"}</div>
            {p.description && <p className="mt-3 text-sm text-slate-600 line-clamp-2">{p.description}</p>}
            <div className="mt-4 flex justify-end gap-2">
              <button className={btnSecondary} onClick={() => setEditing(p)}>Edit</button>
              <button className="text-slate-500 hover:text-red-600 text-sm" onClick={() => del(p.id)}>Delete</button>
            </div>
          </Card>
        ))}
      </div>
      {editing && <ProjForm p={editing === "new" ? null : editing} onClose={() => setEditing(null)} onDone={() => { setEditing(null); load(); }} />}
    </div>
  );
};

const ProjForm = ({ p, onClose, onDone }) => {
  const [f, setF] = useState({
    name: p?.name || "", customer_name: p?.customer_name || "", owner: p?.owner || "",
    status: p?.status || "planning", priority: p?.priority || "medium",
    progress: p?.progress || 0, start_date: p?.start_date || "", target_date: p?.target_date || "",
    description: p?.description || "",
  });
  const submit = async (e) => {
    e.preventDefault();
    const payload = { ...f, progress: Number(f.progress) };
    if (p) await api.put(`/admin/projects/${p.id}`, payload);
    else await api.post("/admin/projects", payload);
    onDone();
  };
  return (
    <Modal onClose={onClose} title={p ? "Edit project" : "New project"}>
      <form onSubmit={submit} className="grid grid-cols-2 gap-3">
        <label className="col-span-2"><div className={labelClass}>Project name *</div><input required value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} className={inputClass} /></label>
        <label><div className={labelClass}>Customer</div><input value={f.customer_name} onChange={(e) => setF({ ...f, customer_name: e.target.value })} className={inputClass} /></label>
        <label><div className={labelClass}>Owner</div><input value={f.owner} onChange={(e) => setF({ ...f, owner: e.target.value })} className={inputClass} /></label>
        <label><div className={labelClass}>Status</div><select value={f.status} onChange={(e) => setF({ ...f, status: e.target.value })} className={inputClass}>{PROJ_STATUS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select></label>
        <label><div className={labelClass}>Priority</div><select value={f.priority} onChange={(e) => setF({ ...f, priority: e.target.value })} className={inputClass}>{PROJ_PRIO.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select></label>
        <label><div className={labelClass}>Start</div><input type="date" value={f.start_date} onChange={(e) => setF({ ...f, start_date: e.target.value })} className={inputClass} /></label>
        <label><div className={labelClass}>Target</div><input type="date" value={f.target_date} onChange={(e) => setF({ ...f, target_date: e.target.value })} className={inputClass} /></label>
        <label className="col-span-2"><div className={labelClass}>Progress ({f.progress}%)</div><input type="range" min="0" max="100" value={f.progress} onChange={(e) => setF({ ...f, progress: e.target.value })} className="w-full" /></label>
        <label className="col-span-2"><div className={labelClass}>Description</div><textarea rows={3} value={f.description} onChange={(e) => setF({ ...f, description: e.target.value })} className={`${inputClass} h-auto py-2`} /></label>
        <div className="col-span-2 flex justify-end gap-2 mt-2">
          <button type="button" className={btnSecondary} onClick={onClose}>Cancel</button>
          <button type="submit" className={btnPrimary}>Save</button>
        </div>
      </form>
    </Modal>
  );
};

/* =========================================================================
   Content Planner
   ========================================================================= */
const CHANNELS = ["blog", "instagram", "linkedin", "email_campaign", "youtube", "tiktok"];
const CONTENT_STATUS = [["idea", "Idea"], ["draft", "Draft"], ["scheduled", "Scheduled"], ["published", "Published"]];
export const AdminContent = () => {
  const [rows, setRows] = useState(null);
  const [editing, setEditing] = useState(null);
  const load = () => api.get("/admin/content").then((r) => setRows(r.data));
  useEffect(() => { load(); }, []);
  if (!rows) return <Loading />;
  const del = async (id) => { if (window.confirm("Delete?")) { await api.delete(`/admin/content/${id}`); load(); } };
  return (
    <div>
      <PageHeader
        title="Content Planner"
        subtitle="Blog posts, social content, and campaign schedule."
        actions={<button className={btnPrimary} onClick={() => setEditing("new")}><Plus className="h-4 w-4" /> New Content</button>}
      />
      {rows.length === 0 && <EmptyState title="Nothing planned yet" />}
      <div className="rounded-2xl bg-white border border-slate-200 overflow-x-auto">
        <table className="w-full min-w-[720px] text-sm">
          <thead className="bg-slate-50 text-[11px] font-bold uppercase tracking-widest text-slate-500">
            <tr>
              <th className="px-4 py-3 text-left">Title</th>
              <th className="px-4 py-3 text-left">Channel</th>
              <th className="px-4 py-3 text-left">Type</th>
              <th className="px-4 py-3 text-left">Owner</th>
              <th className="px-4 py-3 text-left">Publish</th>
              <th className="px-4 py-3 text-left">Status</th>
              <th className="px-4 py-3 text-right"></th>
            </tr>
          </thead>
          <tbody>
            {rows.map((c) => (
              <tr key={c.id} className="border-t border-slate-100">
                <td className="px-4 py-3">
                  <div className="font-semibold text-[#0a2350]">{c.title}</div>
                  {c.hook && <div className="text-xs text-slate-500 line-clamp-1">{c.hook}</div>}
                </td>
                <td className="px-4 py-3 uppercase text-xs font-bold text-[#f5b120]">{c.channel}</td>
                <td className="px-4 py-3 text-xs">{c.type}</td>
                <td className="px-4 py-3">{c.owner || "—"}</td>
                <td className="px-4 py-3 text-slate-500">{shortDate(c.publish_date)}</td>
                <td className="px-4 py-3"><StatusBadge status={c.status} /></td>
                <td className="px-4 py-3 text-right">
                  {c.url && <a href={c.url} target="_blank" rel="noreferrer" className="text-slate-500 hover:text-[#f5b120]"><ExternalLink className="h-4 w-4 inline" /></a>}
                  <button className="ml-3 text-slate-600 hover:text-[#f5b120]" onClick={() => setEditing(c)}><Edit className="h-4 w-4 inline" /></button>
                  <button className="ml-3 text-slate-600 hover:text-red-600" onClick={() => del(c.id)}><Trash2 className="h-4 w-4 inline" /></button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {editing && <ContentForm c={editing === "new" ? null : editing} onClose={() => setEditing(null)} onDone={() => { setEditing(null); load(); }} />}
    </div>
  );
};

const ContentForm = ({ c, onClose, onDone }) => {
  const [f, setF] = useState({
    title: c?.title || "", channel: c?.channel || "blog", type: c?.type || "post",
    status: c?.status || "idea", owner: c?.owner || "",
    publish_date: c?.publish_date || "", hook: c?.hook || "", url: c?.url || "",
  });
  const submit = async (e) => {
    e.preventDefault();
    if (c) await api.put(`/admin/content/${c.id}`, f);
    else await api.post("/admin/content", f);
    onDone();
  };
  return (
    <Modal onClose={onClose} title={c ? "Edit content" : "New content"}>
      <form onSubmit={submit} className="grid grid-cols-2 gap-3">
        <label className="col-span-2"><div className={labelClass}>Title *</div><input required value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} className={inputClass} /></label>
        <label><div className={labelClass}>Channel</div><select value={f.channel} onChange={(e) => setF({ ...f, channel: e.target.value })} className={inputClass}>{CHANNELS.map((c) => <option key={c} value={c}>{c}</option>)}</select></label>
        <label><div className={labelClass}>Type</div><input value={f.type} onChange={(e) => setF({ ...f, type: e.target.value })} className={inputClass} placeholder="post / reel / carousel" /></label>
        <label><div className={labelClass}>Owner</div><input value={f.owner} onChange={(e) => setF({ ...f, owner: e.target.value })} className={inputClass} /></label>
        <label><div className={labelClass}>Publish date</div><input type="date" value={f.publish_date} onChange={(e) => setF({ ...f, publish_date: e.target.value })} className={inputClass} /></label>
        <label><div className={labelClass}>Status</div><select value={f.status} onChange={(e) => setF({ ...f, status: e.target.value })} className={inputClass}>{CONTENT_STATUS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select></label>
        <label><div className={labelClass}>URL</div><input value={f.url} onChange={(e) => setF({ ...f, url: e.target.value })} className={inputClass} placeholder="https://…" /></label>
        <label className="col-span-2"><div className={labelClass}>Hook / caption</div><textarea rows={3} value={f.hook} onChange={(e) => setF({ ...f, hook: e.target.value })} className={`${inputClass} h-auto py-2`} /></label>
        <div className="col-span-2 flex justify-end gap-2 mt-2">
          <button type="button" className={btnSecondary} onClick={onClose}>Cancel</button>
          <button type="submit" className={btnPrimary}>Save</button>
        </div>
      </form>
    </Modal>
  );
};

/* =========================================================================
   Follow-up Checklist
   ========================================================================= */
export const AdminFollowups = () => {
  const [rows, setRows] = useState(null);
  const [modal, setModal] = useState(false);
  const load = () => api.get("/admin/followups").then((r) => setRows(r.data));
  useEffect(() => { load(); }, []);
  if (!rows) return <Loading />;
  const toggle = async (r) => { await api.put(`/admin/followups/${r.id}`, { done: !r.done }); load(); };
  const del = async (id) => { if (window.confirm("Delete?")) { await api.delete(`/admin/followups/${id}`); load(); } };

  const grouped = { overdue: [], today: [], upcoming: [], done: [] };
  const todayStr = new Date().toISOString().slice(0, 10);
  rows.forEach((r) => {
    if (r.done) grouped.done.push(r);
    else if (r.due_date && r.due_date < todayStr) grouped.overdue.push(r);
    else if (r.due_date === todayStr) grouped.today.push(r);
    else grouped.upcoming.push(r);
  });

  return (
    <div>
      <PageHeader
        title="Follow-up Checklist"
        subtitle="Never miss a warm lead — track outreach tasks by due date."
        actions={<button className={btnPrimary} onClick={() => setModal(true)}><Plus className="h-4 w-4" /> New Task</button>}
      />
      {rows.length === 0 && <EmptyState title="No follow-ups scheduled" />}
      {["overdue", "today", "upcoming", "done"].map((k) => grouped[k].length > 0 && (
        <div key={k} className="mb-6">
          <div className={`text-[11px] font-bold uppercase tracking-widest mb-2 ${k === "overdue" ? "text-red-600" : k === "today" ? "text-[#f5b120]" : "text-slate-500"}`}>
            {k} ({grouped[k].length})
          </div>
          <div className="space-y-2">
            {grouped[k].map((r) => (
              <div key={r.id} className={`rounded-xl border p-4 flex items-center gap-3 ${r.done ? "bg-slate-50 border-slate-200 opacity-70" : "bg-white border-slate-200"}`}>
                <button onClick={() => toggle(r)} className={r.done ? "text-emerald-500" : "text-slate-300 hover:text-[#f5b120]"} data-testid={`fu-toggle-${r.id}`}>
                  {r.done ? <CheckCircle2 className="h-5 w-5" /> : <Circle className="h-5 w-5" />}
                </button>
                <div className="flex-1 min-w-0">
                  <div className={`font-semibold text-[#0a2350] ${r.done ? "line-through" : ""}`}>{r.task}</div>
                  <div className="text-xs text-slate-500">
                    {r.customer_name || "—"} · {r.channel} · due {shortDate(r.due_date) || "no date"} · {r.owner}
                  </div>
                </div>
                <button onClick={() => del(r.id)} className="text-slate-400 hover:text-red-600"><Trash2 className="h-4 w-4" /></button>
              </div>
            ))}
          </div>
        </div>
      ))}
      {modal && <FollowupForm onClose={() => setModal(false)} onDone={() => { setModal(false); load(); }} />}
    </div>
  );
};

const FollowupForm = ({ onClose, onDone }) => {
  const [f, setF] = useState({ customer_name: "", task: "", channel: "whatsapp", due_date: "", owner: "" });
  const submit = async (e) => { e.preventDefault(); await api.post("/admin/followups", f); onDone(); };
  return (
    <Modal onClose={onClose} title="New follow-up">
      <form onSubmit={submit} className="grid grid-cols-2 gap-3">
        <label className="col-span-2"><div className={labelClass}>Task *</div><input required value={f.task} onChange={(e) => setF({ ...f, task: e.target.value })} className={inputClass} placeholder="Call, quote, follow email…" /></label>
        <label><div className={labelClass}>Customer</div><input value={f.customer_name} onChange={(e) => setF({ ...f, customer_name: e.target.value })} className={inputClass} /></label>
        <label><div className={labelClass}>Channel</div><select value={f.channel} onChange={(e) => setF({ ...f, channel: e.target.value })} className={inputClass}><option>whatsapp</option><option>call</option><option>email</option><option>meeting</option></select></label>
        <label><div className={labelClass}>Due date</div><input type="date" value={f.due_date} onChange={(e) => setF({ ...f, due_date: e.target.value })} className={inputClass} required /></label>
        <label><div className={labelClass}>Owner</div><input value={f.owner} onChange={(e) => setF({ ...f, owner: e.target.value })} className={inputClass} /></label>
        <div className="col-span-2 flex justify-end gap-2 mt-2">
          <button type="button" className={btnSecondary} onClick={onClose}>Cancel</button>
          <button type="submit" className={btnPrimary}>Save</button>
        </div>
      </form>
    </Modal>
  );
};

/* =========================================================================
   Documents
   ========================================================================= */
export const AdminDocuments = () => {
  const [rows, setRows] = useState(null);
  const [modal, setModal] = useState(false);
  const load = () => api.get("/admin/documents").then((r) => setRows(r.data));
  useEffect(() => { load(); }, []);
  if (!rows) return <Loading />;
  const del = async (id) => { if (window.confirm("Delete?")) { await api.delete(`/admin/documents/${id}`); load(); } };
  return (
    <div>
      <PageHeader
        title="Documents"
        subtitle="Contracts, MSAs, network diagrams, and other business documents."
        actions={<button className={btnPrimary} onClick={() => setModal(true)}><Plus className="h-4 w-4" /> New Document</button>}
      />
      {rows.length === 0 && <EmptyState title="No documents yet" body="Track your contracts, MSAs, and diagrams here." />}
      {rows.length > 0 && (
        <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {rows.map((d) => (
            <Card key={d.id} className="p-5">
              <div className="flex items-start justify-between">
                <div className="h-10 w-10 rounded-lg bg-[#0a2350] flex items-center justify-center"><FileText className="h-5 w-5 text-[#f5b120]" /></div>
                <div className="text-[10px] font-bold uppercase tracking-widest text-[#f5b120]">{d.category}</div>
              </div>
              <div className="mt-4 text-base font-extrabold text-[#0a2350] leading-tight">{d.title}</div>
              <div className="text-xs text-slate-500 mt-1">{d.customer_name || "—"} · {fullDateTime(d.created_at)}</div>
              {d.notes && <p className="mt-2 text-sm text-slate-600 line-clamp-2">{d.notes}</p>}
              <div className="mt-4 flex gap-2">
                {d.url && <a href={d.url} target="_blank" rel="noreferrer" className={btnSecondary}>Open</a>}
                <button className="text-slate-500 hover:text-red-600 text-sm" onClick={() => del(d.id)}>Delete</button>
              </div>
            </Card>
          ))}
        </div>
      )}
      {modal && <DocForm onClose={() => setModal(false)} onDone={() => { setModal(false); load(); }} />}
    </div>
  );
};

const DocForm = ({ onClose, onDone }) => {
  const [f, setF] = useState({ title: "", category: "contract", customer_name: "", url: "", notes: "" });
  const submit = async (e) => { e.preventDefault(); await api.post("/admin/documents", f); onDone(); };
  return (
    <Modal onClose={onClose} title="New document">
      <form onSubmit={submit} className="grid grid-cols-2 gap-3">
        <label className="col-span-2"><div className={labelClass}>Title *</div><input required value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} className={inputClass} /></label>
        <label><div className={labelClass}>Category</div><select value={f.category} onChange={(e) => setF({ ...f, category: e.target.value })} className={inputClass}><option>contract</option><option>msa</option><option>proposal</option><option>diagram</option><option>invoice</option><option>legal</option><option>other</option></select></label>
        <label><div className={labelClass}>Customer</div><input value={f.customer_name} onChange={(e) => setF({ ...f, customer_name: e.target.value })} className={inputClass} /></label>
        <label className="col-span-2"><div className={labelClass}>URL / link</div><input value={f.url} onChange={(e) => setF({ ...f, url: e.target.value })} className={inputClass} placeholder="Google Drive / Dropbox / GitHub link" /></label>
        <label className="col-span-2"><div className={labelClass}>Notes</div><textarea rows={3} value={f.notes} onChange={(e) => setF({ ...f, notes: e.target.value })} className={`${inputClass} h-auto py-2`} /></label>
        <div className="col-span-2 flex justify-end gap-2 mt-2">
          <button type="button" className={btnSecondary} onClick={onClose}>Cancel</button>
          <button type="submit" className={btnPrimary}>Save</button>
        </div>
      </form>
    </Modal>
  );
};
