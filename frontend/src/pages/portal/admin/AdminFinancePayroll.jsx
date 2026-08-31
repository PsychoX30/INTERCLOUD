import React, { useEffect, useState } from "react";
import { api, getToken } from "../../../portal/api";
import { Card, Loading, btnPrimary, btnSecondary, inputClass, labelClass } from "../ui";
import { Plus, Trash2, FileText, Pencil, UserCog } from "lucide-react";

const idr = (v) => "Rp " + Number(v || 0).toLocaleString("id-ID", { maximumFractionDigits: 0 });
const BASE = process.env.REACT_APP_BACKEND_URL;
const today = () => new Date().toISOString().slice(0, 10);

/* ============================================================
 * Shared toolbar: search + sort + order + pagination (10/20/50/All)
 * `filters` slot = pane-specific select elements.
 * ============================================================ */
const PagerToolbar = ({ q, onQ, sortFields, sort, onSort, order, onOrder, limit, onLimit, skip, onSkip, total, filters }) => (
  <div className="mb-3 flex flex-wrap items-center gap-2">
    <input
      value={q}
      onChange={(e) => { onQ(e.target.value); onSkip(0); }}
      placeholder="Cari…"
      className={`${inputClass} h-9 w-44`}
      data-testid="fin-payroll-search"
    />
    {filters}
    <select value={sort} onChange={(e) => { onSort(e.target.value); onSkip(0); }} className={`${inputClass} h-9 w-40`} data-testid="fin-payroll-sort">
      {sortFields.map((f) => <option key={f.value} value={f.value}>{f.label}</option>)}
    </select>
    <button type="button" onClick={() => onOrder(order === "asc" ? "desc" : "asc")} className={`${btnSecondary} h-9`} data-testid="fin-payroll-order" title="Arah urut">
      {order === "asc" ? "↑ Asc" : "↓ Desc"}
    </button>
    <select value={limit} onChange={(e) => { onLimit(Number(e.target.value)); onSkip(0); }} className={`${inputClass} h-9 w-24`} data-testid="fin-payroll-limit">
      <option value={10}>10</option>
      <option value={20}>20</option>
      <option value={50}>50</option>
      <option value={0}>All</option>
    </select>
    <span className="text-xs text-slate-500">
      <b className="text-[#0a2350]">{total}</b> entri
    </span>
    <div className="ml-auto flex items-center gap-2">
      <button type="button" className={`${btnSecondary} h-9`} disabled={skip === 0} onClick={() => onSkip(Math.max(0, skip - (limit || 10)))} data-testid="fin-payroll-prev">Prev</button>
      <span className="text-xs text-slate-500 tabular-nums">
        {limit ? `${total === 0 ? 0 : skip + 1}–${Math.min(skip + limit, total)}` : `1–${total}`}
      </span>
      <button type="button" className={`${btnSecondary} h-9`} disabled={!limit || skip + limit >= total} onClick={() => onSkip(skip + limit)} data-testid="fin-payroll-next">Next</button>
    </div>
  </div>
);

const buildQuery = (p) => {
  const params = new URLSearchParams();
  params.set("paginate", "1");
  params.set("limit", String(p.limit || 100000));
  params.set("skip", String(p.limit ? p.skip : 0));
  params.set("sort", p.sort);
  params.set("order", p.order);
  if (p.q) params.set("q", p.q);
  Object.entries(p.filters || {}).forEach(([k, v]) => { if (v) params.set(k, v); });
  return params.toString();
};

/* ============================================================
 * EmployeesPane — tab Karyawan (CRUD master data karyawan)
 * ============================================================ */
export const EmployeesPane = () => {
  const [rows, setRows] = useState(null);
  const [divisions, setDivisions] = useState([]);
  const [editing, setEditing] = useState(null); // null | {} (new) | employee
  const [err, setErr] = useState("");
  const [q, setQ] = useState("");

  const load = () => {
    api.get(`/admin/employees${q ? `?q=${encodeURIComponent(q)}` : ""}`)
      .then((r) => setRows(Array.isArray(r.data) ? r.data : (r.data.items || [])))
      .catch((e) => setErr(e?.response?.data?.detail || "Gagal memuat data karyawan."));
  };
  useEffect(() => { load(); /* eslint-disable-next-line */ }, [q]);
  useEffect(() => {
    api.get("/admin/employees/divisions").then((r) => setDivisions(r.data || [])).catch(() => setDivisions([]));
  }, []);

  const del = async (id) => {
    if (!window.confirm("Hapus karyawan ini?")) return;
    try { await api.delete(`/admin/employees/${id}`); load(); }
    catch (e) { alert(e?.response?.data?.detail || "Delete failed"); }
  };

  if (err) return <Card className="p-6 text-sm text-red-700">{err}</Card>;
  if (!rows) return <Loading />;

  return (
    <div>
      <div className="mb-3 flex justify-between items-center">
        <div className="text-sm text-slate-500">
          <b className="text-[#0a2350]">{rows.length}</b> karyawan terdaftar
        </div>
        <button onClick={() => setEditing({})} className={btnPrimary} data-testid="add-employee">
          <Plus className="h-4 w-4" /> Tambah karyawan
        </button>
      </div>

      {editing !== null && (
        <EmployeeModal
          initial={editing}
          divisions={divisions}
          onClose={() => setEditing(null)}
          onSaved={() => { setEditing(null); load(); }}
        />
      )}

      <div className="rounded-2xl bg-white border border-slate-200 overflow-x-auto">
        <table className="w-full min-w-[860px] text-sm" data-testid="employees-table">
          <thead className="bg-slate-50 text-[11px] font-bold uppercase tracking-widest text-slate-500">
            <tr>
              <th className="px-4 py-3 text-left">Nama</th>
              <th className="px-4 py-3 text-left">Divisi</th>
              <th className="px-4 py-3 text-left">Jabatan</th>
              <th className="px-4 py-3 text-left">Email</th>
              <th className="px-4 py-3 text-left">Phone</th>
              <th className="px-4 py-3 text-right">Gaji pokok</th>
              <th className="px-4 py-3 text-center">Status</th>
              <th className="px-4 py-3 text-right">Aksi</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((e) => (
              <tr key={e.id} className="border-t border-slate-100" data-testid={`employee-row-${e.id}`}>
                <td className="px-4 py-3 font-semibold text-[#0a2350]">{e.name}</td>
                <td className="px-4 py-3">{e.division || "-"}</td>
                <td className="px-4 py-3">{e.position || "-"}</td>
                <td className="px-4 py-3 text-slate-500">{e.email || "-"}</td>
                <td className="px-4 py-3 text-slate-500">{e.phone || "-"}</td>
                <td className="px-4 py-3 text-right tabular-nums">{e.base_salary ? idr(e.base_salary) : "-"}</td>
                <td className="px-4 py-3 text-center">
                  <span className={`text-[10px] font-bold uppercase px-2 py-0.5 rounded ${e.active !== false ? "bg-emerald-100 text-emerald-700" : "bg-slate-100 text-slate-500"}`}>
                    {e.active !== false ? "Aktif" : "Nonaktif"}
                  </span>
                </td>
                <td className="px-4 py-3 text-right">
                  <span className="inline-flex items-center gap-3">
                    <button onClick={() => setEditing(e)} className="text-slate-600 hover:text-[#0a2350]" title="Edit" data-testid={`employee-edit-${e.id}`}>
                      <Pencil className="h-4 w-4" />
                    </button>
                    <button onClick={() => del(e.id)} className="text-slate-600 hover:text-red-600" title="Delete" data-testid={`employee-del-${e.id}`}>
                      <Trash2 className="h-4 w-4" />
                    </button>
                  </span>
                </td>
              </tr>
            ))}
            {rows.length === 0 && <tr><td colSpan={8} className="p-8 text-center text-slate-400">Belum ada karyawan.</td></tr>}
          </tbody>
        </table>
      </div>
    </div>
  );
};

const EmployeeModal = ({ initial, divisions, onClose, onSaved }) => {
  const isNew = !initial.id;
  const [form, setForm] = useState({
    name: initial.name || "",
    division: initial.division || "",
    position: initial.position || "",
    email: initial.email || "",
    phone: initial.phone || "",
    base_salary: initial.base_salary || "",
    user_id: initial.user_id || "",
    active: initial.active !== false,
  });
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setErr(""); setBusy(true);
    const payload = { ...form, base_salary: Number(form.base_salary) || 0 };
    try {
      if (isNew) await api.post("/admin/employees", payload);
      else await api.put(`/admin/employees/${initial.id}`, payload);
      onSaved();
    } catch (e2) {
      setErr(e2?.response?.data?.detail || "Gagal menyimpan karyawan.");
    } finally { setBusy(false); }
  };

  return (
    <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4" onClick={onClose}>
      <Card className="p-5 w-full max-w-lg" onClick={(e) => e.stopPropagation()} data-testid="employee-modal">
        <div className="text-sm font-extrabold text-[#0a2350] mb-3 flex items-center gap-2">
          <UserCog className="h-4 w-4" /> {isNew ? "Tambah karyawan" : `Edit: ${initial.name}`}
        </div>
        {err && <div className="text-sm bg-red-50 border border-red-200 text-red-700 rounded px-3 py-2 mb-2">{err}</div>}
        <form onSubmit={submit} className="grid grid-cols-2 gap-3">
          <label className="col-span-2"><div className={labelClass}>Nama lengkap *</div>
            <input required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} className={inputClass} data-testid="employee-name" /></label>
          <label><div className={labelClass}>Divisi *</div>
            <input required list="employee-divisions" value={form.division} onChange={(e) => setForm({ ...form, division: e.target.value })} className={inputClass} data-testid="employee-division" />
            <datalist id="employee-divisions">{divisions.map((d) => <option key={d} value={d} />)}</datalist>
          </label>
          <label><div className={labelClass}>Jabatan *</div>
            <input required value={form.position} onChange={(e) => setForm({ ...form, position: e.target.value })} className={inputClass} data-testid="employee-position" /></label>
          <label><div className={labelClass}>Email kantor</div>
            <input type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} className={inputClass} data-testid="employee-email" /></label>
          <label><div className={labelClass}>Phone</div>
            <input value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} className={inputClass} data-testid="employee-phone" /></label>
          <label><div className={labelClass}>Gaji pokok (IDR)</div>
            <input type="number" min="0" value={form.base_salary} onChange={(e) => setForm({ ...form, base_salary: e.target.value })} className={inputClass} data-testid="employee-base-salary" /></label>
          <label><div className={labelClass}>Link user ID (opsional)</div>
            <input value={form.user_id} onChange={(e) => setForm({ ...form, user_id: e.target.value })} className={inputClass} placeholder="ObjectId user portal" data-testid="employee-user-id" /></label>
          <label className="col-span-2 flex items-center gap-2 text-sm text-slate-600">
            <input type="checkbox" checked={form.active} onChange={(e) => setForm({ ...form, active: e.target.checked })} data-testid="employee-active" />
            Aktif (tampil di dropdown transaksi baru)
          </label>
          <div className="col-span-2 flex justify-end gap-2 mt-1">
            <button type="button" onClick={onClose} className={btnSecondary}>Cancel</button>
            <button type="submit" className={btnPrimary} disabled={busy} data-testid="employee-submit">{busy ? "Menyimpan…" : "Simpan"}</button>
          </div>
        </form>
      </Card>
    </div>
  );
};

/* ============================================================
 * SalariesPane — ganti LedgerPane generik untuk tab Salaries.
 * Cascade Division → Employee + toolbar sort/filter/pagination.
 * ============================================================ */
export const SalariesPane = () => {
  const [rows, setRows] = useState([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [tick, setTick] = useState(0);
  const [err, setErr] = useState("");

  const [q, setQ] = useState("");
  const [sort, setSort] = useState("date");
  const [order, setOrder] = useState("desc");
  const [limit, setLimit] = useState(20);
  const [skip, setSkip] = useState(0);
  const [fDivision, setFDivision] = useState("");
  const [fEmployee, setFEmployee] = useState("");
  const [fPeriod, setFPeriod] = useState("");

  const [divisions, setDivisions] = useState([]);
  const [employees, setEmployees] = useState([]);

  const [adding, setAdding] = useState(false);
  const [form, setForm] = useState({ date: today(), division: "", employee_id: "", category: "", notes: "" });
  const [items, setItems] = useState([{ description: "", amount: 0 }]);
  const [formErr, setFormErr] = useState("");

  useEffect(() => {
    api.get("/admin/employees/divisions").then((r) => setDivisions(r.data || [])).catch(() => setDivisions([]));
    api.get("/admin/employees?active=true").then((r) => setEmployees(Array.isArray(r.data) ? r.data : (r.data.items || []))).catch(() => setEmployees([]));
  }, []);

  useEffect(() => {
    const t = setTimeout(() => {
      setLoading(true);
      api.get(`/admin/salaries?${buildQuery({ q, sort, order, limit, skip, filters: { division: fDivision, employee_id: fEmployee, period: fPeriod } })}`)
        .then((r) => { setRows(r.data.items || []); setTotal(r.data.total || 0); setErr(""); })
        .catch((e) => setErr(e?.response?.data?.detail || "Gagal memuat data salaries."))
        .finally(() => setLoading(false));
    }, 250);
    return () => clearTimeout(t);
  }, [q, sort, order, limit, skip, fDivision, fEmployee, fPeriod, tick]);

  const formEmployees = form.division ? employees.filter((e) => e.division === form.division) : employees;
  const pickDivision = (d) => setForm({ ...form, division: d, employee_id: "" });

  const addItem = () => setItems([...items, { description: "", amount: 0 }]);
  const rmItem = (i) => setItems(items.filter((_, idx) => idx !== i));
  const setItem = (i, key, val) => setItems(items.map((it, idx) => idx === i ? { ...it, [key]: val } : it));
  const itemsTotal = items.reduce((s, it) => s + Number(it.amount || 0), 0);

  const submit = async (e) => {
    e.preventDefault();
    setFormErr("");
    if (!form.employee_id) { setFormErr("Pilih karyawan dulu."); return; }
    if (itemsTotal === 0) { setFormErr("Total gaji tidak boleh 0."); return; }
    try {
      await api.post("/admin/salaries", { ...form, items });
      setAdding(false);
      setForm({ date: today(), division: "", employee_id: "", category: "", notes: "" });
      setItems([{ description: "", amount: 0 }]);
      setTick((t) => t + 1);
    } catch (e2) {
      setFormErr(e2?.response?.data?.detail || "Failed to save");
    }
  };

  const del = async (id) => {
    if (!window.confirm("Delete?")) return;
    try { await api.delete(`/admin/salaries/${id}`); setTick((t) => t + 1); }
    catch (e) { alert(e?.response?.data?.detail || "Delete failed"); }
  };

  return (
    <div>
      <PagerToolbar
        q={q} onQ={setQ}
        sortFields={[{ value: "date", label: "Urut: Date" }, { value: "employee", label: "Urut: Employee" }, { value: "division", label: "Urut: Division" }, { value: "amount", label: "Urut: Amount" }]}
        sort={sort} onSort={setSort} order={order} onOrder={setOrder}
        limit={limit} onLimit={setLimit} skip={skip} onSkip={setSkip} total={total}
        filters={
          <>
            <select value={fDivision} onChange={(e) => { setFDivision(e.target.value); setSkip(0); }} className={`${inputClass} h-9 w-36`} data-testid="salaries-filter-division">
              <option value="">Semua divisi</option>
              {divisions.map((d) => <option key={d} value={d}>{d}</option>)}
            </select>
            <select value={fEmployee} onChange={(e) => { setFEmployee(e.target.value); setSkip(0); }} className={`${inputClass} h-9 w-40`} data-testid="salaries-filter-employee">
              <option value="">Semua karyawan</option>
              {employees.map((e) => <option key={e.id} value={e.id}>{e.name}</option>)}
            </select>
            <input type="month" value={fPeriod} onChange={(e) => { setFPeriod(e.target.value); setSkip(0); }} className={`${inputClass} h-9 w-32`} data-testid="salaries-filter-period" />
          </>
        }
      />

      <div className="mb-3 flex justify-end">
        <button onClick={() => setAdding(!adding)} className={btnPrimary} data-testid="add-salaries"><Plus className="h-4 w-4" /> Add entry</button>
      </div>

      {adding && (
        <Card className="p-4 mb-3">
          {formErr && <div className="text-sm bg-red-50 border border-red-200 text-red-700 rounded px-3 py-2 mb-2">{formErr}</div>}
          <form onSubmit={submit} className="grid grid-cols-2 md:grid-cols-4 gap-2">
            <label><div className={labelClass}>Date</div>
              <input type="date" required value={form.date} onChange={(e) => setForm({ ...form, date: e.target.value })} className={inputClass} data-testid="salaries-date" /></label>
            <label><div className={labelClass}>Division</div>
              <select value={form.division} onChange={(e) => pickDivision(e.target.value)} className={inputClass} data-testid="salaries-division">
                <option value="">— Semua divisi —</option>
                {divisions.map((d) => <option key={d} value={d}>{d}</option>)}
              </select></label>
            <label><div className={labelClass}>Employee *</div>
              <select required value={form.employee_id} onChange={(e) => setForm({ ...form, employee_id: e.target.value })} className={inputClass} data-testid="salaries-employee">
                <option value="">{form.division ? "— Pilih karyawan —" : "Pilih divisi dulu (opsional)"}</option>
                {formEmployees.map((e) => <option key={e.id} value={e.id}>{e.name} · {e.position || "-"}</option>)}
              </select></label>
            <label><div className={labelClass}>Category</div>
              <input value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })} className={inputClass} placeholder="reguler / bonus / lembur" data-testid="salaries-category" /></label>
            <label className="md:col-span-4"><div className={labelClass}>Notes</div>
              <input value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} className={inputClass} data-testid="salaries-notes" /></label>

            <div className="col-span-full border-t border-slate-100 pt-3 mt-1">
              <div className="flex items-center justify-between mb-2">
                <div className="text-xs font-bold text-[#0a2350]">Rincian item</div>
                <button type="button" onClick={addItem} className="text-xs font-bold text-[#0a2350] hover:text-[#f5b120]" data-testid="salaries-add-item"><Plus className="h-3.5 w-3.5 inline" /> Tambah baris</button>
              </div>
              {items.map((it, i) => (
                <div key={i} className="grid grid-cols-[1fr_140px_32px] gap-2 mb-2 items-end">
                  <label><div className={labelClass}>Keterangan</div>
                    <input value={it.description} onChange={(e) => setItem(i, "description", e.target.value)} className={inputClass} placeholder="e.g. Gaji pokok / BPJS / Pajak" data-testid={`salaries-item-${i}-desc`} /></label>
                  <label><div className={labelClass}>Nominal</div>
                    <input type="number" value={it.amount} onChange={(e) => setItem(i, "amount", Number(e.target.value))} className={inputClass} data-testid={`salaries-item-${i}-amount`} /></label>
                  <button type="button" onClick={() => rmItem(i)} disabled={items.length === 1} className="h-9 w-9 inline-flex items-center justify-center rounded-lg text-slate-400 hover:text-red-600 disabled:opacity-30" title="Hapus"><Trash2 className="h-4 w-4" /></button>
                </div>
              ))}
              <div className="text-right text-sm mt-1">Total: <b className="text-[#0a2350]" data-testid="salaries-items-total">{idr(itemsTotal)}</b></div>
            </div>

            <div className="col-span-full flex justify-end gap-2 mt-2">
              <button type="button" onClick={() => setAdding(false)} className={btnSecondary}>Cancel</button>
              <button type="submit" className={btnPrimary} data-testid="salaries-submit">Save</button>
            </div>
          </form>
        </Card>
      )}

      {err && <Card className="p-4 mb-3 text-sm text-red-700">{err}</Card>}
      {loading ? <Loading /> : (
        <div className="rounded-2xl bg-white border border-slate-200 overflow-x-auto">
          <table className="w-full min-w-[860px] text-sm" data-testid="salaries-table">
            <thead className="bg-slate-50 text-[11px] font-bold uppercase tracking-widest text-slate-500">
              <tr>
                <th className="px-4 py-3 text-left">Date</th>
                <th className="px-4 py-3 text-left">Employee</th>
                <th className="px-4 py-3 text-left">Division</th>
                <th className="px-4 py-3 text-left">Position</th>
                <th className="px-4 py-3 text-left">Category</th>
                <th className="px-4 py-3 text-center">Items</th>
                <th className="px-4 py-3 text-right">Amount</th>
                <th className="px-4 py-3 text-right"></th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id} className="border-t border-slate-100">
                  <td className="px-4 py-3 text-slate-600">{r.date}</td>
                  <td className="px-4 py-3 font-semibold">{r.employee || "-"}</td>
                  <td className="px-4 py-3">{r.division || "-"}</td>
                  <td className="px-4 py-3 text-slate-500">{r.position || "-"}</td>
                  <td className="px-4 py-3">{r.category || "-"}</td>
                  <td className="px-4 py-3 text-center text-slate-500">{r.items ? r.items.length : 1}</td>
                  <td className="px-4 py-3 text-right font-bold text-red-700">{idr(r.amount)}</td>
                  <td className="px-4 py-3 text-right">
                    <span className="inline-flex items-center gap-3">
                      <a
                        href={`${BASE}/api/portal/documents/salary-slip/${r.id}?format=pdf&token=${encodeURIComponent(getToken() || "")}`}
                        className="inline-flex items-center gap-1 text-xs font-bold text-[#0a2350] hover:text-[#f5b120]"
                        title="Unduh slip gaji PDF"
                        data-testid={`salary-slip-${r.id}`}
                      >
                        <FileText className="h-4 w-4" /> Slip
                      </a>
                      <button onClick={() => del(r.id)} className="text-slate-600 hover:text-red-600" title="Delete"><Trash2 className="h-4 w-4" /></button>
                    </span>
                  </td>
                </tr>
              ))}
              {rows.length === 0 && <tr><td colSpan={8} className="p-8 text-center text-slate-400">No entries yet.</td></tr>}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
};

/* ============================================================
 * SalesFeesPane — multi-invoice items + cascade sales→customer→service
 * ============================================================ */
export const SalesFeesPane = () => {
  const [ctx, setCtx] = useState(null);
  const [ctxErr, setCtxErr] = useState("");
  const [rows, setRows] = useState([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [tick, setTick] = useState(0);

  const [q, setQ] = useState("");
  const [sort, setSort] = useState("date");
  const [order, setOrder] = useState("desc");
  const [limit, setLimit] = useState(20);
  const [skip, setSkip] = useState(0);
  const [fSales, setFSales] = useState("");
  const [fPeriod, setFPeriod] = useState("");

  const [adding, setAdding] = useState(false);
  const [err, setErr] = useState("");
  const [form, setForm] = useState({ date: today(), notes: "" });
  const [items, setItems] = useState([{ invoice_id: "", invoice_number: "", manual: false, description: "", amount: 0 }]);
  const [salesId, setSalesId] = useState("");
  const [customerId, setCustomerId] = useState("");
  const [serviceId, setServiceId] = useState("");

  useEffect(() => {
    api.get("/admin/finance/sales-context")
      .then((r) => setCtx(r.data))
      .catch((e) => setCtxErr(e?.response?.data?.detail || "Gagal memuat data sales"));
  }, []);

  useEffect(() => {
    const t = setTimeout(() => {
      setLoading(true);
      api.get(`/admin/sales-fees?${buildQuery({ q, sort, order, limit, skip, filters: { sales_person_id: fSales, period: fPeriod } })}`)
        .then((r) => { setRows(r.data.items || []); setTotal(r.data.total || 0); })
        .catch(() => setRows([]))
        .finally(() => setLoading(false));
    }, 250);
    return () => clearTimeout(t);
  }, [q, sort, order, limit, skip, fSales, fPeriod, tick]);

  const customers = (ctx && salesId && ctx.customers_by_sales[salesId]) || [];
  const services = (ctx && customerId && ctx.services_by_customer[customerId]) || [];
  const invoicesBySvc = (ctx && serviceId && ctx.invoices_by_service[serviceId]) || [];
  const invoicesByCust = (ctx && customerId && ctx.invoices_by_customer[customerId]) || [];
  const invoiceList = serviceId ? invoicesBySvc : invoicesByCust;

  const pickSales = (id) => { setSalesId(id); setCustomerId(""); setServiceId(""); };
  const pickCustomer = (id) => { setCustomerId(id); setServiceId(""); };
  const pickService = (id) => { setServiceId(id); };

  const addItem = () => setItems([...items, { invoice_id: "", invoice_number: "", manual: false, description: "", amount: 0 }]);
  const rmItem = (i) => setItems(items.filter((_, idx) => idx !== i));
  const setItem = (i, key, val) => setItems(items.map((it, idx) => idx === i ? { ...it, [key]: val } : it));
  const itemsTotal = items.reduce((s, it) => s + Number(it.amount || 0), 0);

  const submit = async (e) => {
    e.preventDefault();
    setErr("");
    if (!salesId) { setErr("Pilih sales person dulu."); return; }
    if (itemsTotal === 0) { setErr("Total fee tidak boleh 0."); return; }
    const sales = (ctx.sales_people || []).find((s) => s.id === salesId);
    const payload = {
      ...form,
      sales_person: sales ? sales.name : "",
      sales_person_id: salesId,
      items: items.map((it) => ({
        description: it.description,
        amount: Number(it.amount) || 0,
        invoice_id: it.manual ? "" : (it.invoice_id || ""),
        invoice_number: it.manual ? (it.invoice_number || "") : ((invoiceList.find((i) => i.id === it.invoice_id) || {}).number || ""),
        customer_id: customerId || "",
        service_id: serviceId || "",
      })),
    };
    try {
      await api.post("/admin/sales-fees", payload);
      setAdding(false);
      setForm({ date: today(), notes: "" });
      setItems([{ invoice_id: "", invoice_number: "", manual: false, description: "", amount: 0 }]);
      setSalesId(""); setCustomerId(""); setServiceId("");
      setTick((t) => t + 1);
    } catch (e2) {
      setErr(e2?.response?.data?.detail || "Failed to save");
    }
  };

  const del = async (id) => {
    if (!window.confirm("Delete?")) return;
    try { await api.delete(`/admin/sales-fees/${id}`); setTick((t) => t + 1); }
    catch (e) { alert(e?.response?.data?.detail || "Delete failed"); }
  };

  if (ctxErr) return <Card className="p-6 text-sm text-red-700">{ctxErr}</Card>;
  if (!ctx) return <Loading />;

  return (
    <div>
      <PagerToolbar
        q={q} onQ={setQ}
        sortFields={[{ value: "date", label: "Urut: Date" }, { value: "sales_person", label: "Urut: Sales person" }, { value: "amount", label: "Urut: Amount" }]}
        sort={sort} onSort={setSort} order={order} onOrder={setOrder}
        limit={limit} onLimit={setLimit} skip={skip} onSkip={setSkip} total={total}
        filters={
          <>
            <select value={fSales} onChange={(e) => { setFSales(e.target.value); setSkip(0); }} className={`${inputClass} h-9 w-44`} data-testid="sales-fees-filter-sales">
              <option value="">Semua sales</option>
              {(ctx.sales_people || []).map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
            </select>
            <input type="month" value={fPeriod} onChange={(e) => { setFPeriod(e.target.value); setSkip(0); }} className={`${inputClass} h-9 w-32`} data-testid="sales-fees-filter-period" />
          </>
        }
      />

      <div className="mb-3 flex justify-end">
        <button onClick={() => setAdding(!adding)} className={btnPrimary} data-testid="add-sales-fees"><Plus className="h-4 w-4" /> Add entry</button>
      </div>

      {adding && (
        <Card className="p-4 mb-3">
          {err && <div className="text-sm bg-red-50 border border-red-200 text-red-700 rounded px-3 py-2 mb-2">{err}</div>}
          <form onSubmit={submit} className="grid grid-cols-2 md:grid-cols-4 gap-2">
            <label><div className={labelClass}>Date</div>
              <input type="date" required value={form.date} onChange={(e) => setForm({ ...form, date: e.target.value })} className={inputClass} data-testid="sales-fees-date" /></label>

            <label>
              <div className={labelClass}>Sales Person</div>
              <select value={salesId} onChange={(e) => pickSales(e.target.value)} className={inputClass} data-testid="sales-fees-sales-person">
                <option value="">— Pilih sales —</option>
                {(ctx.sales_people || []).map((s) => <option key={s.id} value={s.id}>{s.name}{s.email ? ` (${s.email})` : ""}</option>)}
              </select>
            </label>

            <label>
              <div className={labelClass}>Customer</div>
              <select value={customerId} onChange={(e) => pickCustomer(e.target.value)} disabled={!salesId} className={inputClass} data-testid="sales-fees-customer">
                <option value="">{salesId ? "— Semua customer sales ini —" : "Pilih sales dulu"}</option>
                {customers.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
              </select>
            </label>

            <label>
              <div className={labelClass}>Service</div>
              <select value={serviceId} onChange={(e) => pickService(e.target.value)} disabled={!customerId} className={inputClass} data-testid="sales-fees-service">
                <option value="">{customerId ? "— Semua service —" : "Pilih customer dulu"}</option>
                {services.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
              </select>
            </label>

            <label className="md:col-span-4"><div className={labelClass}>Notes</div>
              <input value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} className={inputClass} data-testid="sales-fees-notes" /></label>

            <div className="col-span-full border-t border-slate-100 pt-3 mt-1">
              <div className="flex items-center justify-between mb-2">
                <div className="text-xs font-bold text-[#0a2350]">Rincian fee (multi-invoice)</div>
                <button type="button" onClick={addItem} className="text-xs font-bold text-[#0a2350] hover:text-[#f5b120]" data-testid="sales-fees-add-item"><Plus className="h-3.5 w-3.5 inline" /> Tambah baris</button>
              </div>
              {items.map((it, i) => (
                <div key={i} className="grid grid-cols-2 md:grid-cols-[1.2fr_1fr_1fr_120px_32px] gap-2 mb-2 items-end">
                  <label>
                    <div className={labelClass}>Invoice</div>
                    {it.manual ? (
                      <input value={it.invoice_number} onChange={(e) => setItem(i, "invoice_number", e.target.value)} className={inputClass} placeholder="Nomor invoice manual" data-testid={`sales-fees-item-${i}-invoice-manual`} />
                    ) : (
                      <select value={it.invoice_id} onChange={(e) => setItem(i, "invoice_id", e.target.value)} disabled={!customerId} className={inputClass} data-testid={`sales-fees-item-${i}-invoice`}>
                        <option value="">{customerId ? "— Pilih invoice —" : "Pilih customer dulu"}</option>
                        {invoiceList.map((inv) => <option key={inv.id} value={inv.id}>{inv.number} · {inv.status}</option>)}
                      </select>
                    )}
                  </label>
                  <label className="flex items-end gap-2 pb-2 text-xs text-slate-600">
                    <input type="checkbox" checked={it.manual} onChange={(e) => setItem(i, "manual", e.target.checked)} data-testid={`sales-fees-item-${i}-manual`} />
                    Input manual
                  </label>
                  <label><div className={labelClass}>Keterangan</div>
                    <input value={it.description} onChange={(e) => setItem(i, "description", e.target.value)} className={inputClass} placeholder="e.g. Fee closing / komisi" data-testid={`sales-fees-item-${i}-desc`} /></label>
                  <label><div className={labelClass}>Nominal</div>
                    <input type="number" value={it.amount} onChange={(e) => setItem(i, "amount", Number(e.target.value))} className={inputClass} data-testid={`sales-fees-item-${i}-amount`} /></label>
                  <button type="button" onClick={() => rmItem(i)} disabled={items.length === 1} className="h-9 w-9 inline-flex items-center justify-center rounded-lg text-slate-400 hover:text-red-600 disabled:opacity-30" title="Hapus"><Trash2 className="h-4 w-4" /></button>
                </div>
              ))}
              <div className="text-right text-sm mt-1">Total: <b className="text-[#0a2350]" data-testid="sales-fees-items-total">{idr(itemsTotal)}</b></div>
            </div>

            <div className="col-span-full flex justify-end gap-2 mt-2">
              <button type="button" onClick={() => setAdding(false)} className={btnSecondary}>Cancel</button>
              <button type="submit" className={btnPrimary} data-testid="sales-fees-submit">Save</button>
            </div>
          </form>
        </Card>
      )}

      {loading ? <Loading /> : (
        <div className="rounded-2xl bg-white border border-slate-200 overflow-x-auto">
          <table className="w-full min-w-[860px] text-sm" data-testid="sales-fees-table">
            <thead className="bg-slate-50 text-[11px] font-bold uppercase tracking-widest text-slate-500">
              <tr>
                <th className="px-4 py-3 text-left">Date</th>
                <th className="px-4 py-3 text-left">Sales person</th>
                <th className="px-4 py-3 text-left">Invoices</th>
                <th className="px-4 py-3 text-left">Period</th>
                <th className="px-4 py-3 text-center">Items</th>
                <th className="px-4 py-3 text-right">Amount</th>
                <th className="px-4 py-3 text-right"></th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => {
                const invs = (r.items || []).map((it) => it.invoice_number).filter(Boolean);
                const legacyInv = r.invoice_number && invs.length === 0 ? [r.invoice_number] : invs;
                return (
                  <tr key={r.id} className="border-t border-slate-100">
                    <td className="px-4 py-3 text-slate-600">{r.date}</td>
                    <td className="px-4 py-3 font-semibold">{r.sales_person || "-"}</td>
                    <td className="px-4 py-3 text-xs text-slate-500">{legacyInv.length ? legacyInv.join(", ") : "-"}</td>
                    <td className="px-4 py-3 text-slate-500">{r.period_yyyy_mm || "-"}</td>
                    <td className="px-4 py-3 text-center text-slate-500">{r.items ? r.items.length : 1}</td>
                    <td className="px-4 py-3 text-right font-bold text-red-700">{idr(r.amount)}</td>
                    <td className="px-4 py-3 text-right">
                      <span className="inline-flex items-center gap-3">
                        <a
                          href={`${BASE}/api/portal/documents/sales-fee-slip/${r.id}?format=pdf&token=${encodeURIComponent(getToken() || "")}`}
                          className="inline-flex items-center gap-1 text-xs font-bold text-[#0a2350] hover:text-[#f5b120]"
                          title="Unduh slip fee sales PDF"
                          data-testid={`sales-fee-slip-${r.id}`}
                        >
                          <FileText className="h-4 w-4" /> Slip
                        </a>
                        <button onClick={() => del(r.id)} className="text-slate-600 hover:text-red-600" title="Delete"><Trash2 className="h-4 w-4" /></button>
                      </span>
                    </td>
                  </tr>
                );
              })}
              {rows.length === 0 && <tr><td colSpan={7} className="p-8 text-center text-slate-400">No entries yet.</td></tr>}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
};
