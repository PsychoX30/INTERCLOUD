import React, { useEffect, useState, useCallback, useMemo } from "react";
import { Link } from "react-router-dom";
import { api, shortDate, fullDateTime } from "../../../portal/api";
import { PageHeader, Card, Loading, EmptyState, StatusBadge, btnPrimary, btnSecondary, inputClass, labelClass } from "../ui";
import { Plus, Edit, Trash2, CheckCircle2, Circle, FileText, ExternalLink, Flame, MessageCircle, Phone, Mail, Upload, Download } from "lucide-react";
import { useAuth } from "../../../portal/AuthContext";
import TablePager from "./TablePager";

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
   CRM - Customers / Prospects
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
  const { user } = useAuth() || {};
  const isSales = user?.role?.toLowerCase() === "sales";
  const [rows, setRows] = useState(null);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(0);
  const [limit, setLimit] = useState(50);
  const [clients, setClients] = useState([]);
  const [q, setQ] = useState("");
  const [statusF, setStatusF] = useState("");
  const [warmOnly, setWarmOnly] = useState(false);
  const [editing, setEditing] = useState(null); // null | 'new' | obj
  const [importing, setImporting] = useState(false); // modal import xlsx
  const [exporting, setExporting] = useState(false);

  const params = useMemo(() => ({
    paginate: true,
    skip: page * limit,
    limit,
    ...(q.trim() ? { q: q.trim() } : {}),
    ...(statusF ? { status: statusF } : {}),
  }), [page, limit, q, statusF]);

  const load = useCallback(() => {
    api.get("/admin/crm", { params }).then((r) => {
      setRows(r.data?.items || []);
      setTotal(r.data?.total || 0);
    });
  }, [params]);

  useEffect(() => {
    load();
    if (isSales) {
      api.get("/admin/users").then((r) => {
        const list = Array.isArray(r.data) ? r.data : (r.data?.items || []);
        const assigned = new Set((user?.assigned_client_ids || []).map(String));
        setClients(list.filter((u) => u.role === "client" && assigned.has(String(u.id))));
      });
    }
  }, [load, isSales, user?.assigned_client_ids]);

  if (!rows) return <Loading />;

  const filtered = warmOnly ? rows.filter((r) => r.is_warm) : rows;
  const warmCount = rows.filter((r) => r.is_warm).length;
  const totalLTV = rows.reduce((s, r) => s + (Number(r.lifetime_value) || 0), 0);

  const del = async (id) => { if (window.confirm("Delete?")) { await api.delete(`/admin/crm/${id}`); load(); } };

  const exportXlsx = async () => {
    setExporting(true);
    try {
      const res = await api.get("/admin/crm/export.xlsx", { responseType: "blob" });
      const url = URL.createObjectURL(res.data);
      const a = document.createElement("a");
      a.href = url; a.download = "customer-database.xlsx"; a.click();
      URL.revokeObjectURL(url);
    } catch { alert("Gagal export XLSX."); } finally { setExporting(false); }
  };

  return (
    <div>
      <PageHeader
        title="Customer Database (CRM)"
        subtitle="Prospects, partnerships, existing & past clients - all in one directory."
        actions={
          <div className="flex gap-2 flex-wrap">
            {!isSales && (
              <button className={btnSecondary} onClick={() => setImporting(true)} data-testid="crm-import-btn">
                <Upload className="h-4 w-4" /> Import XLSX
              </button>
            )}
            <button className={btnSecondary} onClick={exportXlsx} disabled={exporting} data-testid="crm-export-btn">
              <Download className="h-4 w-4" /> {exporting ? "Menyiapkan…" : "Export XLSX"}
            </button>
            <button className={btnPrimary} onClick={() => setEditing("new")} data-testid="new-crm-btn"><Plus className="h-4 w-4" /> Add Contact</button>
          </div>
        }
      />

      {/* KPI strip */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4">
        <Card className="p-4">
          <div className="text-[11px] font-bold uppercase tracking-widest text-slate-500">Total contacts</div>
          <div className="text-2xl font-extrabold text-[#0a2350] mt-0.5" data-testid="crm-kpi-total">{total}</div>
        </Card>
        <Card className="p-4">
          <div className="text-[11px] font-bold uppercase tracking-widest text-slate-500 flex items-center gap-1"><Flame className="h-3.5 w-3.5 text-orange-500" /> Warm leads</div>
          <div className="text-2xl font-extrabold text-orange-600 mt-0.5" data-testid="crm-kpi-warm">{warmCount}</div>
          <div className="text-[10px] text-slate-400 mt-0.5">di halaman ini</div>
        </Card>
        <Card className="p-4">
          <div className="text-[11px] font-bold uppercase tracking-widest text-slate-500">Existing / active</div>
          <div className="text-2xl font-extrabold text-emerald-700 mt-0.5" data-testid="crm-kpi-existing">
            {rows.filter((r) => r.status === "existing").length}
          </div>
          <div className="text-[10px] text-slate-400 mt-0.5">di halaman ini</div>
        </Card>
        <Card className="p-4">
          <div className="text-[11px] font-bold uppercase tracking-widest text-slate-500">Lifetime value paid</div>
          <div className="text-2xl font-extrabold text-[#0a2350] mt-0.5" data-testid="crm-kpi-ltv">{idr(totalLTV)}</div>
          <div className="text-[10px] text-slate-400 mt-0.5">di halaman ini</div>
        </Card>
      </div>

      <div className="mb-3 flex gap-2 flex-wrap items-center">
        <input placeholder="Search… (server)" value={q} onChange={(e) => { setQ(e.target.value); setPage(0); }} className={`${inputClass} max-w-xs`} data-testid="crm-search" />
        <select value={statusF} onChange={(e) => { setStatusF(e.target.value); setPage(0); }} className={`${inputClass} max-w-[220px]`} data-testid="crm-status-filter">
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
                    <div className="text-xs text-slate-500">{c.company || "-"}</div>
                  </td>
                  <td className="px-4 py-3">
                    <div>{c.email || "-"}</div>
                    <div className="text-xs text-slate-500">{c.phone || "-"}</div>
                  </td>
                  <td className="px-4 py-3">{c.industry || "-"}</td>
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
                          {c.latest_order.product_name || "-"}
                        </Link>
                        <div className="text-[10px] text-slate-400">{shortDate(c.latest_order.created_at)}</div>
                      </div>
                    ) : (
                      <span className="text-slate-400 text-xs">No orders yet</span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-right">
                    <div className={`font-extrabold ${c.lifetime_value > 0 ? "text-[#0a2350]" : "text-slate-400"}`} data-testid={`crm-ltv-${c.id}`}>
                      {c.lifetime_value > 0 ? idr(c.lifetime_value) : "-"}
                    </div>
                    {c.won_orders_count > 0 && (
                      <div className="text-[10px] text-slate-500">{c.won_orders_count} active service{c.won_orders_count > 1 ? "s" : ""}</div>
                    )}
                  </td>
                  <td className="px-4 py-3"><StatusBadge status={c.status} /></td>
                  <td className="px-4 py-3 text-right whitespace-nowrap">
                    {c.phone && (
                      <a href={`https://wa.me/${String(c.phone).replace(/[^0-9]/g, "").replace(/^0/, "62")}`} target="_blank" rel="noreferrer"
                        className="text-emerald-600 hover:text-emerald-800" title="Chat WhatsApp" data-testid={`crm-wa-${c.id}`}>
                        <MessageCircle className="h-4 w-4 inline" />
                      </a>
                    )}
                    {c.phone && (
                      <a href={`tel:${c.phone}`} className="ml-3 text-sky-600 hover:text-sky-800" title="Telepon" data-testid={`crm-call-${c.id}`}>
                        <Phone className="h-4 w-4 inline" />
                      </a>
                    )}
                    {c.email && (
                      <a href={`mailto:${c.email}`} className="ml-3 text-[#0a2350] hover:text-[#f5b120]" title="Kirim email" data-testid={`crm-email-${c.id}`}>
                        <Mail className="h-4 w-4 inline" />
                      </a>
                    )}
                    <button className="ml-3 text-slate-600 hover:text-[#f5b120]" onClick={() => setEditing(c)}><Edit className="h-4 w-4 inline" /></button>
                    <button className="ml-3 text-slate-600 hover:text-red-600" onClick={() => del(c.id)}><Trash2 className="h-4 w-4 inline" /></button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {total > 0 && (
        <TablePager
          page={page}
          total={total}
          limit={limit}
          onPage={setPage}
          onLimit={(l) => { setLimit(l); setPage(0); }}
          testid="admin-crm-pager"
        />
      )}
      {editing && <CrmForm c={editing === "new" ? null : editing} clients={clients} isSales={isSales} onClose={() => setEditing(null)} onDone={() => { setEditing(null); load(); }} />}
      {importing && <CrmImportModal onClose={() => setImporting(false)} onDone={() => { setImporting(false); load(); }} />}
    </div>
  );
};

const CrmImportModal = ({ onClose, onDone }) => {
  const [file, setFile] = useState(null);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const [err, setErr] = useState("");

  const upload = async () => {
    if (!file) return;
    setBusy(true); setErr(""); setResult(null);
    try {
      const fd = new FormData();
      fd.append("file", file);
      const { data } = await api.post("/admin/crm/import", fd, { headers: { "Content-Type": "multipart/form-data" } });
      setResult(data);
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message);
    } finally { setBusy(false); }
  };

  return (
    <Modal onClose={onClose} title="Import Customer DB (.xlsx)">
      <div data-testid="crm-import-modal">
        <p className="text-xs text-slate-500 mb-3 leading-relaxed">
          Format kolom mengikuti template <b>Database Marketing</b>: <b>Nama</b>, <b>Nomor Telp</b>, <b>E-Mail</b>,
          <b> Perusahaan</b>, <b>Jabatan</b>, <b>Segmen Industri</b>, <b>Status</b> (PROSPECT / POSSIBLE PARTNERSHIP /
          EXISTING CLIENT / EX CLIENT). Kontak yang sudah ada (berdasarkan email, atau nama+telp) akan di-update, sisanya dibuat baru.
        </p>
        {err && <div className="mb-3 text-sm text-red-700 bg-red-50 border border-red-200 rounded px-3 py-2" data-testid="crm-import-error">{err}</div>}
        {result ? (
          <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-4 mb-4" data-testid="crm-import-result">
            <div className="text-sm font-bold text-emerald-700 mb-1">Import selesai</div>
            <div className="text-xs text-slate-600 space-y-0.5">
              <div>Baris diproses: <b>{result.total_rows}</b></div>
              <div>Kontak baru: <b className="text-emerald-700">{result.created}</b></div>
              <div>Di-update: <b className="text-sky-700">{result.updated}</b></div>
              <div>Dilewati (kosong): <b>{result.skipped}</b></div>
              {(result.errors || []).length > 0 && (
                <div className="text-red-600 mt-1">
                  {result.errors.length} baris error: {result.errors.slice(0, 3).map((e) => `baris ${e.row}`).join(", ")}…
                </div>
              )}
            </div>
            <div className="mt-3"><button className={btnPrimary} onClick={onDone} data-testid="crm-import-done">Tutup & muat ulang</button></div>
          </div>
        ) : (
          <>
            <input
              type="file"
              accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
              onChange={(e) => setFile(e.target.files?.[0] || null)}
              className="block w-full text-sm text-slate-600 file:mr-3 file:rounded-xl file:border-0 file:bg-[#0a2350] file:px-4 file:py-2 file:text-white file:text-sm file:font-bold hover:file:bg-[#0a2350]/90 cursor-pointer"
              data-testid="crm-import-file"
            />
            <div className="flex justify-end gap-2 mt-4">
              <button className={btnSecondary} onClick={onClose}>Batal</button>
              <button className={btnPrimary} onClick={upload} disabled={!file || busy} data-testid="crm-import-submit">
                {busy ? "Mengimpor…" : "Import"}
              </button>
            </div>
          </>
        )}
      </div>
    </Modal>
  );
};

const CrmForm = ({ c, clients, isSales, onClose, onDone }) => {
  const [f, setF] = useState({
    name: c?.name || "", email: c?.email || "", phone: c?.phone || "",
    company: c?.company || "", position: c?.position || "", industry: c?.industry || "",
    status: c?.status || "prospect", notes: c?.notes || "",
    user_id: c?.user_id || "",
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
        {isSales && !c && (
          <label className="col-span-2">
            <div className={labelClass}>Assigned client *</div>
            <select required value={f.user_id} onChange={(e) => setF({ ...f, user_id: e.target.value })} className={inputClass} data-testid="crm-client">
              <option value="">Select client…</option>
              {clients.map((u) => <option key={u.id} value={u.id}>{u.name} ({u.email || u.company || "-"})</option>)}
            </select>
          </label>
        )}
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
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(0);
  const [limit, setLimit] = useState(50);
  const [editing, setEditing] = useState(null);

  const params = useMemo(() => ({
    paginate: true,
    skip: page * limit,
    limit,
  }), [page, limit]);

  const load = useCallback(() => {
    api.get("/admin/projects", { params }).then((r) => {
      setRows(r.data?.items || []);
      setTotal(r.data?.total || 0);
    });
  }, [params]);

  useEffect(() => { load(); }, [load]);

  if (!rows) return <Loading />;
  const del = async (id) => { if (window.confirm("Delete?")) { await api.delete(`/admin/projects/${id}`); load(); } };
  return (
    <div>
      <PageHeader
        title="Project Tracker"
        subtitle="Ongoing work - implementation projects, migrations, and internal initiatives."
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
                <div className="text-xs text-slate-500 mt-0.5">Customer: {p.customer_name || "-"} · Owner: {p.owner || "-"}</div>
              </div>
              <StatusBadge status={p.status} />
            </div>
            <div className="mt-3 h-2 bg-slate-100 rounded-full overflow-hidden">
              <div className="h-full bg-gradient-to-r from-[#f5b120] to-[#0a2350]" style={{ width: `${p.progress || 0}%` }} />
            </div>
            <div className="text-[11px] text-slate-500 mt-1">{p.progress || 0}% complete · Target {shortDate(p.target_date) || "-"}</div>
            {p.description && <p className="mt-3 text-sm text-slate-600 line-clamp-2">{p.description}</p>}
            <div className="mt-4 flex justify-end gap-2">
              <button className={btnSecondary} onClick={() => setEditing(p)}>Edit</button>
              <button className="text-slate-500 hover:text-red-600 text-sm" onClick={() => del(p.id)}>Delete</button>
            </div>
          </Card>
        ))}
      </div>
      {total > 0 && (
        <TablePager
          page={page}
          total={total}
          limit={limit}
          onPage={setPage}
          onLimit={(l) => { setLimit(l); setPage(0); }}
          testid="admin-projects-pager"
        />
      )}
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
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(0);
  const [limit, setLimit] = useState(50);
  const [editing, setEditing] = useState(null);

  const params = useMemo(() => ({
    paginate: true,
    skip: page * limit,
    limit,
  }), [page, limit]);

  const load = useCallback(() => {
    api.get("/admin/content", { params }).then((r) => {
      setRows(r.data?.items || []);
      setTotal(r.data?.total || 0);
    });
  }, [params]);

  useEffect(() => { load(); }, [load]);

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
                <td className="px-4 py-3">{c.owner || "-"}</td>
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
      {total > 0 && (
        <TablePager
          page={page}
          total={total}
          limit={limit}
          onPage={setPage}
          onLimit={(l) => { setLimit(l); setPage(0); }}
          testid="admin-content-pager"
        />
      )}
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
  const { user } = useAuth() || {};
  const [rows, setRows] = useState(null);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(0);
  const [limit, setLimit] = useState(50);
  const [modal, setModal] = useState(false);
  const [doneF, setDoneF] = useState("open"); // open | done | all
  const [detail, setDetail] = useState(null); // selected follow-up for detail panel

  const params = useMemo(() => ({
    paginate: true,
    skip: page * limit,
    limit,
    ...(doneF === "all" ? {} : { done: doneF === "done" }),
  }), [page, limit, doneF]);

  const load = useCallback(() => {
    api.get("/admin/followups", { params }).then((r) => {
      setRows(r.data?.items || []);
      setTotal(r.data?.total || 0);
    });
  }, [params]);

  useEffect(() => { load(); }, [load]);

  if (!rows) return <Loading />;
  const toggle = async (r) => { await api.put(`/admin/followups/${r.id}`, { done: !r.done }); load(); };
  const del = async (id) => { if (window.confirm("Delete?")) { await api.delete(`/admin/followups/${id}`); load(); } };
  const closeDeal = async (id) => {
    try {
      const { data } = await api.post(`/admin/followups/${id}/close-deal`);
      alert("Link registrasi:\n" + data.deal_registration_link);
      load();
    } catch (e) {
      alert(e?.response?.data?.detail || "Gagal membuat link close-deal");
    }
  };

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
        subtitle="Never miss a warm lead - track outreach tasks by due date."
        actions={<button className={btnPrimary} onClick={() => setModal(true)}><Plus className="h-4 w-4" /> New Task</button>}
      />
      <div className="mb-4 flex gap-1 flex-wrap" data-testid="fu-filter-tabs">
        {[["open", "Open"], ["done", "Done"], ["all", "All"]].map(([k, l]) => (
          <button
            key={k}
            type="button"
            onClick={() => { setDoneF(k); setPage(0); }}
            className={`px-3 py-1.5 rounded-lg text-xs font-bold uppercase tracking-wider ${doneF === k ? "bg-[#0a2350] text-white" : "bg-slate-100 text-slate-500 hover:bg-slate-200"}`}
            data-testid={`fu-filter-${k}`}
          >
            {l}
          </button>
        ))}
        <span className="ml-auto self-center text-xs text-slate-400">{total} total</span>
      </div>
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
                    {r.customer_name || "-"} · {r.channel} · due {shortDate(r.due_date) || "no date"}{r.owner ? ` · ${r.owner}` : ""}
                  </div>
                  {r.role_tags && r.role_tags.length > 0 && (
                    <div className="flex gap-1 mt-1 flex-wrap" data-testid={`fu-list-tags-${r.id}`}>
                      {r.role_tags.map((tag) => (
                        <span key={tag} className="text-[10px] px-1.5 py-0.5 rounded font-bold uppercase tracking-wider bg-[#0a2350]/10 text-[#0a2350]">
                          {tag}
                        </span>
                      ))}
                    </div>
                  )}
                  {r.deal_action === "close_deal" && (
                    <div className="text-[10px] font-bold text-emerald-600 mt-0.5">CLOSE DEAL — link registrasi siap</div>
                  )}
                  {r.approvals && r.approvals.length > 0 && (
                    <div className="flex gap-1 mt-1 flex-wrap">
                      {r.approvals.map((a) => (
                        <span key={a.id} className={`text-[10px] px-1.5 py-0.5 rounded font-bold ${a.status === "accepted" ? "bg-emerald-100 text-emerald-700" : a.status === "rejected" ? "bg-red-100 text-red-700" : "bg-amber-100 text-amber-700"}`}>
                          {a.target_role}: {a.status}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
                <button onClick={() => setDetail(r)} className="text-slate-400 hover:text-[#f5b120]" title="Detail"><Edit className="h-4 w-4" /></button>
                {!r.done && !r.deal_action && (
                  <button onClick={() => closeDeal(r.id)} className="text-[10px] font-bold text-emerald-600 hover:text-emerald-800 px-2 py-1 rounded bg-emerald-50 hover:bg-emerald-100" title="Close Deal">Close Deal</button>
                )}
                <button onClick={() => del(r.id)} className="text-slate-400 hover:text-red-600"><Trash2 className="h-4 w-4" /></button>
              </div>
            ))}
          </div>
        </div>
      ))}
      {total > 0 && (
        <TablePager
          page={page}
          total={total}
          limit={limit}
          onPage={setPage}
          onLimit={(l) => { setLimit(l); setPage(0); }}
          testid="admin-followups-pager"
        />
      )}
      {modal && <FollowupForm onClose={() => setModal(false)} onDone={() => { setModal(false); load(); }} />}
      {detail && <FollowupDetail fu={detail} onClose={() => setDetail(null)} onDone={() => { setDetail(null); load(); }} currentUser={user} />}
    </div>
  );
};

const FU_ROLES = ["sales", "noc", "support", "finance", "admin"];

/* Customer picker: server-side CRM search on name / email / phone. */
const CrmCustomerPicker = ({ value, onPick }) => {
  const [q, setQ] = useState(value?.name || "");
  const [opts, setOpts] = useState([]);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!open) return;
    const term = q.trim();
    const t = setTimeout(() => {
      setBusy(true);
      api.get("/admin/crm/search", { params: { q: term, limit: 20 } })
        .then((r) => setOpts(Array.isArray(r.data) ? r.data : []))
        .catch(() => setOpts([]))
        .finally(() => setBusy(false));
    }, 250);
    return () => clearTimeout(t);
  }, [q, open]);

  return (
    <div className="relative">
      <input
        value={q}
        onChange={(e) => { setQ(e.target.value); setOpen(true); onPick(null); }}
        onFocus={() => setOpen(true)}
        className={inputClass}
        placeholder="Cari nama, email, atau nomor telp…"
        data-testid="fu-customer-search"
        autoComplete="off"
      />
      {open && (
        <div className="absolute z-20 mt-1 w-full max-h-56 overflow-y-auto rounded-xl border border-slate-200 bg-white shadow-lg" data-testid="fu-customer-options">
          {busy && <div className="px-3 py-2 text-xs text-slate-400">Mencari…</div>}
          {!busy && opts.length === 0 && <div className="px-3 py-2 text-xs text-slate-400">Tidak ada kontak cocok</div>}
          {opts.map((o) => (
            <button
              key={o.id}
              type="button"
              onClick={() => { onPick(o); setQ(o.name || o.email || ""); setOpen(false); }}
              className="w-full text-left px-3 py-2 hover:bg-slate-50 border-b border-slate-100 last:border-0"
              data-testid={`fu-customer-opt-${o.id}`}
            >
              <div className="text-sm font-semibold text-[#0a2350]">
                {o.name || "(tanpa nama)"}
                <span className={`ml-2 text-[10px] px-1.5 py-0.5 rounded font-bold ${o.status === "partnership" ? "bg-amber-100 text-amber-700" : o.status === "assigned" ? "bg-indigo-100 text-indigo-700" : "bg-slate-100 text-slate-600"}`}>
                  {o.status}
                </span>
              </div>
              <div className="text-[11px] text-slate-500">{o.email || "-"} · {o.phone || "-"} · {o.company || "-"}</div>
            </button>
          ))}
        </div>
      )}
    </div>
  );
};

const FollowupForm = ({ onClose, onDone }) => {
  const [f, setF] = useState({ customer_id: "", customer_name: "", task: "", channel: "whatsapp", due_date: "" });
  const [roleTags, setRoleTags] = useState([]);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setErr(""); setBusy(true);
    try {
      const { data } = await api.post("/admin/followups", f);
      if (roleTags.length) {
        await api.put(`/admin/followups/${data.id}`, { role_tags: roleTags });
      }
      onDone();
    } catch (e2) {
      setErr(e2?.response?.data?.detail || "Gagal menyimpan follow-up");
    } finally { setBusy(false); }
  };

  return (
    <Modal onClose={onClose} title="New follow-up">
      <form onSubmit={submit} className="grid grid-cols-2 gap-3">
        {err && <div className="col-span-2 rounded-xl bg-red-50 border border-red-200 text-red-700 text-sm px-3 py-2" data-testid="fu-error">{err}</div>}
        <label className="col-span-2"><div className={labelClass}>Task *</div><input required value={f.task} onChange={(e) => setF({ ...f, task: e.target.value })} className={inputClass} placeholder="Call, quote, follow email…" /></label>
        <div className="col-span-2">
          <div className={labelClass}>Customer (dari CRM)</div>
          <CrmCustomerPicker
            onPick={(o) => setF((p) => ({ ...p, customer_id: o?.id || "", customer_name: o?.name || "" }))}
          />
          <div className="text-[11px] text-slate-400 mt-1">
            Prospect yang dipilih akan otomatis di-assign ke Anda selama 5 hari. Possible partnership tetap shared.
          </div>
        </div>
        <label><div className={labelClass}>Channel</div><select value={f.channel} onChange={(e) => setF({ ...f, channel: e.target.value })} className={inputClass}><option>whatsapp</option><option>call</option><option>email</option><option>meeting</option></select></label>
        <label><div className={labelClass}>Due date</div><input type="date" value={f.due_date} onChange={(e) => setF({ ...f, due_date: e.target.value })} className={inputClass} required /></label>
        <div className="col-span-2">
          <div className={labelClass}>Tag role</div>
          <div className="flex gap-1.5 flex-wrap" data-testid="fu-role-tags">
            {FU_ROLES.map((role) => {
              const on = roleTags.includes(role);
              return (
                <button
                  key={role}
                  type="button"
                  onClick={() => setRoleTags((p) => on ? p.filter((x) => x !== role) : [...p, role])}
                  className={`px-2.5 py-1 rounded-lg text-[11px] font-bold uppercase tracking-wider ${on ? "bg-[#0a2350] text-white" : "bg-slate-100 text-slate-500 hover:bg-slate-200"}`}
                  data-testid={`fu-tag-${role}`}
                >
                  {role}
                </button>
              );
            })}
          </div>
        </div>
        <div className="col-span-2 flex justify-end gap-2 mt-2">
          <button type="button" className={btnSecondary} onClick={onClose}>Cancel</button>
          <button type="submit" className={btnPrimary} disabled={busy}>{busy ? "Menyimpan…" : "Save"}</button>
        </div>
      </form>
    </Modal>
  );
};

/* Task detail: per-role notes, role tags, approval requests/responses. */
const FollowupDetail = ({ fu, onClose, onDone, currentUser }) => {
  const [notes, setNotes] = useState(fu.notes || {});
  const [noteDraft, setNoteDraft] = useState("");
  const [roleTags, setRoleTags] = useState(fu.role_tags || []);
  const [approvals, setApprovals] = useState(fu.approvals || []);
  const [targetRole, setTargetRole] = useState("finance");
  const [message, setMessage] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const myRole = (currentUser?.role || "").toLowerCase();
  const canPostNote = FU_ROLES.includes(myRole);

  const saveTask = async () => {
    setErr(""); setBusy(true);
    try {
      await api.put(`/admin/followups/${fu.id}`, { role_tags: roleTags });
      onDone();
    } catch (e) {
      setErr(e?.response?.data?.detail || "Gagal menyimpan perubahan");
    } finally { setBusy(false); }
  };

  const addNote = async () => {
    const text = noteDraft.trim();
    if (!text) return;
    setErr(""); setBusy(true);
    try {
      const { data } = await api.post(`/admin/followups/${fu.id}/notes`, { text });
      setNotes(data.notes || {});
      setNoteDraft("");
    } catch (e) {
      setErr(e?.response?.data?.detail || "Gagal mengirim catatan");
    } finally { setBusy(false); }
  };

  const requestApproval = async () => {
    setErr(""); setBusy(true);
    try {
      const { data } = await api.post(`/admin/followups/${fu.id}/approval`, {
        target_role: targetRole, message,
      });
      setApprovals((p) => [...p, data]);
      setMessage("");
    } catch (e) {
      setErr(e?.response?.data?.detail || "Gagal mengirim pengajuan");
    } finally { setBusy(false); }
  };

  const respond = async (aid, response) => {
    setErr(""); setBusy(true);
    try {
      const note = window.prompt(`Catatan untuk keputusan "${response}" (opsional)`) || "";
      const { data } = await api.put(`/admin/followups/${fu.id}/approval/${aid}`, { response, note });
      setApprovals((p) => p.map((a) => (a.id === aid ? data : a)));
    } catch (e) {
      setErr(e?.response?.data?.detail || "Gagal merespon approval");
    } finally { setBusy(false); }
  };

  return (
    <Modal onClose={onClose} title={`Task: ${fu.task}`}>
      <div className="space-y-4" data-testid="fu-detail">
        {err && <div className="rounded-xl bg-red-50 border border-red-200 text-red-700 text-sm px-3 py-2">{err}</div>}
        <div className="text-xs text-slate-500">
          {fu.customer_name || "-"} · {fu.channel} · due {shortDate(fu.due_date) || "no date"} · owner {fu.owner || "-"}
        </div>

        {fu.deal_registration_link && (
          <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-3">
            <div className="text-[11px] font-bold uppercase tracking-widest text-emerald-700 mb-1">Link registrasi close-deal</div>
            <div className="text-xs break-all text-slate-700" data-testid="fu-deal-link">{fu.deal_registration_link}</div>
          </div>
        )}

        <div>
          <div className={labelClass}>Tag role</div>
          <div className="flex gap-1.5 flex-wrap">
            {FU_ROLES.map((role) => {
              const on = roleTags.includes(role);
              return (
                <button
                  key={role}
                  type="button"
                  onClick={() => setRoleTags((p) => on ? p.filter((x) => x !== role) : [...p, role])}
                  className={`px-2.5 py-1 rounded-lg text-[11px] font-bold uppercase tracking-wider ${on ? "bg-[#0a2350] text-white" : "bg-slate-100 text-slate-500 hover:bg-slate-200"}`}
                  data-testid={`fu-detail-tag-${role}`}
                >
                  {role}
                </button>
              );
            })}
          </div>
        </div>

        <div>
          <div className={labelClass}>Catatan (thread per role)</div>
          <div className="rounded-xl border border-slate-200 bg-slate-50 p-3 max-h-80 overflow-y-auto space-y-3" data-testid="fu-notes-thread">
            {FU_ROLES.map((role) => {
              const thread = notes[role] || [];
              if (!Array.isArray(thread) || thread.length === 0) return null;
              return (
                <div key={role} className="space-y-2">
                  <div className="text-[10px] font-bold uppercase tracking-widest text-[#0a2350] sticky top-0 bg-slate-50 pb-1">{role}</div>
                  {thread.map((entry, idx) => (
                    <div key={idx} className={`rounded-lg p-2 text-xs ${entry.legacy ? "bg-amber-50 border border-amber-200" : "bg-white border border-slate-200"}`} data-testid={`fu-note-entry-${role}-${idx}`}>
                      {entry.legacy && <div className="text-[10px] text-amber-700 font-bold uppercase mb-1">Legacy (format lama)</div>}
                      <div className="text-slate-700">{entry.text}</div>
                      <div className="text-[10px] text-slate-400 mt-1">
                        {entry.author || "—"} · {entry.at ? new Date(entry.at).toLocaleString("id-ID") : "—"}
                      </div>
                    </div>
                  ))}
                </div>
              );
            })}
            {FU_ROLES.every((r) => !Array.isArray(notes[r]) || notes[r].length === 0) && (
              <div className="text-xs text-slate-400 text-center py-4">Belum ada catatan.</div>
            )}
          </div>
          {canPostNote && (
            <div className="mt-2 flex gap-2">
              <input
                type="text"
                placeholder={`Tulis catatan sebagai ${myRole}…`}
                value={noteDraft}
                onChange={(e) => setNoteDraft(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); addNote(); } }}
                className={inputClass}
                disabled={busy}
                data-testid="fu-note-input"
              />
              <button
                type="button"
                onClick={addNote}
                disabled={busy || !noteDraft.trim()}
                className="px-4 py-2 rounded-xl bg-[#0a2350] text-white font-bold text-sm hover:bg-[#0a2350]/90 disabled:opacity-50"
                data-testid="fu-note-send"
              >
                Kirim
              </button>
            </div>
          )}
          {!canPostNote && (
            <div className="text-xs text-slate-400 mt-2">Anda tidak memiliki role yang dapat menambahkan catatan.</div>
          )}
        </div>

        <div>
          <div className={labelClass}>Pengajuan / approval needed</div>
          {approvals.length === 0 && <div className="text-xs text-slate-400 mb-2">Belum ada pengajuan.</div>}
          <div className="space-y-2 mb-3">
            {approvals.map((a) => (
              <div key={a.id} className="rounded-xl border border-slate-200 p-3" data-testid={`fu-approval-${a.id}`}>
                <div className="flex items-center justify-between gap-2">
                  <div className="text-xs font-bold text-[#0a2350] uppercase tracking-wider">
                    → {a.target_role}
                    <span className={`ml-2 px-1.5 py-0.5 rounded text-[10px] ${a.status === "accepted" ? "bg-emerald-100 text-emerald-700" : a.status === "rejected" ? "bg-red-100 text-red-700" : "bg-amber-100 text-amber-700"}`}>
                      {a.status}
                    </span>
                  </div>
                  {a.status === "pending" && (myRole === "admin" || myRole === a.target_role) && (
                    <div className="flex gap-1">
                      <button type="button" onClick={() => respond(a.id, "accepted")} disabled={busy}
                        className="text-[10px] font-bold px-2 py-1 rounded bg-emerald-50 text-emerald-700 hover:bg-emerald-100"
                        data-testid={`fu-approve-${a.id}`}>Accept</button>
                      <button type="button" onClick={() => respond(a.id, "rejected")} disabled={busy}
                        className="text-[10px] font-bold px-2 py-1 rounded bg-red-50 text-red-700 hover:bg-red-100"
                        data-testid={`fu-reject-${a.id}`}>Reject</button>
                    </div>
                  )}
                </div>
                {a.message && <div className="text-xs text-slate-600 mt-1">{a.message}</div>}
                <div className="text-[10px] text-slate-400 mt-1">
                  diminta oleh {a.requested_by || "-"}
                  {a.status !== "pending" && ` · ${a.status} oleh ${a.responded_by || "-"}`}
                  {a.response_note ? ` · "${a.response_note}"` : ""}
                </div>
              </div>
            ))}
          </div>
          <div className="grid grid-cols-2 gap-2">
            <select value={targetRole} onChange={(e) => setTargetRole(e.target.value)} className={inputClass} data-testid="fu-approval-role">
              {FU_ROLES.map((role) => <option key={role} value={role}>{role}</option>)}
            </select>
            <input value={message} onChange={(e) => setMessage(e.target.value)} className={inputClass}
              placeholder="Alasan pengajuan…" data-testid="fu-approval-message" />
          </div>
          <button type="button" onClick={requestApproval} disabled={busy} className={`${btnSecondary} mt-2`} data-testid="fu-approval-submit">
            Kirim pengajuan
          </button>
        </div>

        <div className="flex justify-end gap-2 pt-2 border-t border-slate-100">
          <button type="button" className={btnSecondary} onClick={onClose}>Tutup</button>
          <button type="button" className={btnPrimary} onClick={saveTask} disabled={busy} data-testid="fu-detail-save">
            {busy ? "Menyimpan…" : "Simpan"}
          </button>
        </div>
      </div>
    </Modal>
  );
};

/* =========================================================================
   Documents
   ========================================================================= */
export const AdminDocuments = () => {
  const [rows, setRows] = useState(null);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(0);
  const [limit, setLimit] = useState(50);
  const [modal, setModal] = useState(false);

  const params = useMemo(() => ({
    paginate: true,
    skip: page * limit,
    limit,
  }), [page, limit]);

  const load = useCallback(() => {
    api.get("/admin/documents", { params }).then((r) => {
      setRows(r.data?.items || []);
      setTotal(r.data?.total || 0);
    });
  }, [params]);

  useEffect(() => { load(); }, [load]);

  if (!rows) return <Loading />;
  const del = async (id) => { if (window.confirm("Delete?")) { await api.delete(`/admin/documents/${id}`); load(); } };
  const openDocument = async (path) => {
    // Only an API-relative protected-file path receives the portal Bearer
    // token. External document URLs remain ordinary browser navigation.
    if (!path.startsWith("/documents/file/")) return;
    try {
      const r = await api.get(path, { responseType: "blob" });
      const blobUrl = URL.createObjectURL(new Blob([r.data]));
      const a = document.createElement("a");
      a.href = blobUrl;
      a.target = "_blank";
      a.rel = "noreferrer";
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(blobUrl), 60000);
    } catch (e) {
      alert(e?.response?.data?.detail || "Gagal membuka dokumen");
    }
  };
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
              <div className="text-xs text-slate-500 mt-1">{d.customer_name || "-"} · {fullDateTime(d.created_at)}</div>
              {d.notes && <p className="mt-2 text-sm text-slate-600 line-clamp-2">{d.notes}</p>}
              <div className="mt-4 flex gap-2">
                {d.has_file && d.id ? (
                  <button
                    className={btnSecondary}
                    onClick={() => openDocument(`/documents/file/${d.id}`)}
                  >
                    Open
                  </button>
                ) : d.url ? (
                  <a href={d.url} target="_blank" rel="noreferrer" className={btnSecondary}>
                    Open
                  </a>
                ) : null}
                <button className="text-slate-500 hover:text-red-600 text-sm" onClick={() => del(d.id)}>Delete</button>
              </div>
            </Card>
          ))}
        </div>
      )}
      {total > 0 && (
        <TablePager
          page={page}
          total={total}
          limit={limit}
          onPage={setPage}
          onLimit={(l) => { setLimit(l); setPage(0); }}
          testid="admin-documents-pager"
        />
      )}
      {modal && <DocForm onClose={() => setModal(false)} onDone={() => { setModal(false); load(); }} />}
    </div>
  );
};

const DocForm = ({ onClose, onDone }) => {
  const [f, setF] = useState({ title: "", category: "contract", customer_name: "", url: "", notes: "" });
  const [file, setFile] = useState(null);
  const [drag, setDrag] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const fileRef = React.useRef(null);

  const pick = (fl) => {
    if (!fl) return;
    setFile(fl);
    setErr("");
    setF((p) => ({ ...p, title: p.title || fl.name.replace(/\.[^.]+$/, "") }));
  };

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true); setErr("");
    try {
      if (file) {
        const fd = new FormData();
        fd.append("file", file);
        fd.append("title", f.title);
        fd.append("category", f.category);
        fd.append("customer_name", f.customer_name);
        fd.append("notes", f.notes);
        await api.post("/admin/documents/upload", fd, { headers: { "Content-Type": "multipart/form-data" } });
      } else {
        await api.post("/admin/documents", f);
      }
      onDone();
    } catch (e2) {
      setErr(e2?.response?.data?.detail || "Gagal menyimpan dokumen");
    } finally { setBusy(false); }
  };

  return (
    <Modal onClose={onClose} title="New document">
      <form onSubmit={submit} className="grid grid-cols-2 gap-3">
        {err && <div className="col-span-2 rounded-xl bg-red-50 border border-red-200 text-red-700 text-sm px-3 py-2" data-testid="doc-error">{err}</div>}
        <div
          className={`col-span-2 rounded-2xl border-2 border-dashed p-5 text-center cursor-pointer transition-colors ${drag ? "border-[#f5b120] bg-[#f5b120]/10" : "border-slate-300 hover:border-[#f5b120]/60 bg-slate-50"}`}
          onClick={() => fileRef.current?.click()}
          onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
          onDragLeave={() => setDrag(false)}
          onDrop={(e) => { e.preventDefault(); setDrag(false); pick(e.dataTransfer.files?.[0]); }}
          data-testid="doc-dropzone"
        >
          <input
            ref={fileRef}
            type="file"
            className="hidden"
            accept=".pdf,.doc,.docx,.xls,.xlsx,.png,.jpg,.jpeg,.webp,.zip,.txt,.csv"
            onChange={(e) => pick(e.target.files?.[0])}
            data-testid="doc-file-input"
          />
          {file ? (
            <div className="text-sm font-bold text-[#0a2350]" data-testid="doc-file-selected">
              {file.name} <span className="font-normal text-slate-500">({(file.size / 1024 / 1024).toFixed(2)} MB)</span>
              <button type="button" className="ml-2 text-xs text-red-600 font-bold" onClick={(e) => { e.stopPropagation(); setFile(null); }}>hapus</button>
            </div>
          ) : (
            <div className="text-sm text-slate-500">
              <b className="text-[#0a2350]">Drag & drop file di sini</b> atau klik untuk memilih
              <div className="text-[11px] mt-1">PDF, Word, Excel, gambar, ZIP, teks · maks 15 MB</div>
            </div>
          )}
        </div>
        <label className="col-span-2"><div className={labelClass}>Title *</div><input required value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} className={inputClass} /></label>
        <label><div className={labelClass}>Category</div><select value={f.category} onChange={(e) => setF({ ...f, category: e.target.value })} className={inputClass}><option>contract</option><option>msa</option><option>proposal</option><option>diagram</option><option>invoice</option><option>legal</option><option>other</option></select></label>
        <label><div className={labelClass}>Customer</div><input value={f.customer_name} onChange={(e) => setF({ ...f, customer_name: e.target.value })} className={inputClass} /></label>
        {!file && (
          <label className="col-span-2"><div className={labelClass}>URL / link (opsional bila tanpa file)</div><input value={f.url} onChange={(e) => setF({ ...f, url: e.target.value })} className={inputClass} placeholder="Google Drive / Dropbox / GitHub link" /></label>
        )}
        <label className="col-span-2"><div className={labelClass}>Notes</div><textarea rows={3} value={f.notes} onChange={(e) => setF({ ...f, notes: e.target.value })} className={`${inputClass} h-auto py-2`} /></label>
        <div className="col-span-2 flex justify-end gap-2 mt-2">
          <button type="button" className={btnSecondary} onClick={onClose}>Cancel</button>
          <button type="submit" className={btnPrimary} disabled={busy} data-testid="doc-save">{busy ? "Uploading..." : "Save"}</button>
        </div>
      </form>
    </Modal>
  );
};
