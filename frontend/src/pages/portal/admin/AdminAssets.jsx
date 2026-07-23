import React, { useEffect, useMemo, useState } from "react";
import { api, money, shortDate } from "../../../portal/api";
import { PageHeader, StatCard, btnPrimary, btnSecondary, inputClass, labelClass } from "../ui";
import { Plus, Trash2, Edit, Calculator, X } from "lucide-react";
import { DataTable } from "../../../components/ui/data-table";

const CATEGORIES = ["server", "switch", "router", "firewall", "storage", "ups", "aircon", "monitor", "cable", "other"];

const AdminAssets = () => {
  const [rows, setRows] = useState(null);
  const [editing, setEditing] = useState(null);
  const [scheduleFor, setScheduleFor] = useState(null);
  const load = () => api.get("/admin/assets").then((r) => setRows(r.data));
  useEffect(() => { load(); }, []);

  const del = async (id) => { if (window.confirm("Delete?")) { await api.delete(`/admin/assets/${id}`); load(); } };
  const showSchedule = async (id) => {
    const { data } = await api.get(`/admin/assets/${id}`);
    setScheduleFor(data);
  };

  const list = rows || [];
  const totalValue = list.reduce((a, b) => a + (b.value || 0), 0);
  const totalBook = list.reduce((a, b) => a + (b.book_value || 0), 0);
  const totalDep = list.reduce((a, b) => a + (b.accumulated_depreciation || 0), 0);

  const columns = [
    { key: "name", label: "Asset", sortable: true,
      render: (_v, a) => (
        <>
          <div className="font-semibold text-[#0a2350]">{a.name}</div>
          <div className="text-xs text-slate-500">{a.vendor || "—"} · {a.location || "—"}</div>
        </>
      ) },
    { key: "serial_number", label: "Serial", sortable: true, mono: true,
      render: (v) => <span className="font-mono text-xs">{v || "—"}</span> },
    { key: "category", label: "Category", sortable: true,
      render: (v) => <span className="uppercase text-xs font-bold text-[#f5b120]">{v}</span> },
    { key: "purchase_date", label: "Purchased", sortable: true,
      render: (v) => <span className="text-xs text-slate-500">{shortDate(v) || "—"}</span> },
    { key: "value", label: "Cost", sortable: true, align: "right",
      render: (v) => <span className="font-semibold">{money(v)}</span> },
    { key: "salvage_value", label: "Salvage", sortable: true, align: "right",
      render: (v) => <span className="text-xs text-slate-500">{money(v || 0)}</span> },
    { key: "useful_life_years", label: "Life", sortable: true, align: "right",
      render: (v) => <span className="text-xs">{v ? `${v} yr` : "—"}</span> },
    { key: "annual_depreciation", label: "Annual Dep.", sortable: true, align: "right",
      render: (v) => <span className="text-amber-700">{money(v || 0)}</span> },
    { key: "book_value", label: "Book Value", sortable: true, align: "right",
      render: (_v, a) => (
        <>
          <div className="font-extrabold text-[#0a2350] tabular-nums">{money(a.book_value)}</div>
          <div className="text-[10px] text-red-500 tabular-nums">-{money(a.accumulated_depreciation)}</div>
        </>
      ) },
    { key: "_actions", label: "", sortable: false, align: "right",
      render: (_v, a) => (
        <span onClick={(e) => e.stopPropagation()} className="whitespace-nowrap">
          <button title="Depreciation schedule" className="text-slate-600 hover:text-[#0a2350]" onClick={() => showSchedule(a.id)} data-testid={`asset-schedule-${a.id}`}><Calculator className="h-4 w-4 inline" /></button>
          <button className="ml-2 text-slate-600 hover:text-[#f5b120]" onClick={() => setEditing(a)}><Edit className="h-4 w-4 inline" /></button>
          <button className="ml-2 text-slate-600 hover:text-red-600" onClick={() => del(a.id)}><Trash2 className="h-4 w-4 inline" /></button>
        </span>
      ) },
  ];

  return (
    <div>
      <PageHeader
        title="Assets"
        subtitle="Straight-line depreciation (metode garis lurus): (Harga Perolehan − Nilai Sisa) ÷ Umur Ekonomis."
        actions={<button className={btnPrimary} onClick={() => setEditing("new")} data-testid="new-asset-btn"><Plus className="h-4 w-4" /> Add Asset</button>}
      />
      <div className="grid sm:grid-cols-4 gap-4 mb-6">
        <StatCard label="Asset Count" value={list.length} testid="asset-count" />
        <StatCard label="Total Cost (Harga Perolehan)" value={money(totalValue)} tone="good" testid="asset-total" />
        <StatCard label="Net Book Value (Nilai Buku)" value={money(totalBook)} tone="good" testid="asset-net" />
        <StatCard label="Accumulated Depreciation" value={money(totalDep)} tone="warn" testid="asset-dep" />
      </div>

      <DataTable
        rows={list}
        loading={rows === null}
        columns={columns}
        searchKeys={["name", "serial_number", "category", "vendor", "location"]}
        rowKey={(a) => a.id}
        empty={{ title: "No assets yet", hint: "Track your appliances, servers, and DC equipment with straight-line depreciation." }}
        testid="admin-assets-table"
      />

      {editing && <AssetForm a={editing === "new" ? null : editing} onClose={() => setEditing(null)} onDone={() => { setEditing(null); load(); }} />}
      {scheduleFor && <ScheduleModal asset={scheduleFor} onClose={() => setScheduleFor(null)} />}
    </div>
  );
};

const AssetForm = ({ a, onClose, onDone }) => {
  const [f, setF] = useState({
    name: a?.name || "",
    category: a?.category || "server",
    serial_number: a?.serial_number || "",
    location: a?.location || "",
    vendor: a?.vendor || "",
    value: a?.value ?? 0,
    salvage_value: a?.salvage_value ?? 0,
    useful_life_years: a?.useful_life_years || 5,
    purchase_date: a?.purchase_date || new Date().toISOString().slice(0, 10),
    notes: a?.notes || "",
  });

  const preview = useMemo(() => {
    const cost = Number(f.value || 0);
    const salvage = Number(f.salvage_value || 0);
    const life = Number(f.useful_life_years || 0);
    if (life <= 0) return null;
    const base = Math.max(cost - salvage, 0);
    const annual = base / life;
    return { annual, monthly: annual / 12, base };
  }, [f.value, f.salvage_value, f.useful_life_years]);

  const submit = async (e) => {
    e.preventDefault();
    const payload = {
      ...f,
      value: Number(f.value),
      salvage_value: Number(f.salvage_value),
      useful_life_years: Number(f.useful_life_years),
    };
    if (a) await api.put(`/admin/assets/${a.id}`, payload);
    else await api.post("/admin/assets", payload);
    onDone();
  };

  return (
    <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4" onClick={onClose}>
      <form onSubmit={submit} onClick={(e) => e.stopPropagation()} className="w-full max-w-2xl bg-white rounded-3xl p-6 max-h-[92vh] overflow-y-auto" data-testid="asset-form">
        <div className="flex items-start justify-between">
          <div>
            <h3 className="text-xl font-extrabold text-[#0a2350]">{a ? "Edit asset" : "New asset"}</h3>
            <p className="mt-0.5 text-xs text-slate-500">Straight-line: <span className="font-mono">(Harga Perolehan − Nilai Sisa) ÷ Umur Ekonomis</span></p>
          </div>
          <button type="button" onClick={onClose} className="text-slate-400 hover:text-slate-700"><X className="h-5 w-5" /></button>
        </div>

        <div className="mt-4 grid grid-cols-2 gap-3">
          <label className="col-span-2"><div className={labelClass}>Name *</div><input required value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} className={inputClass} placeholder="Dell PowerEdge R650" data-testid="asset-name" /></label>
          <label><div className={labelClass}>Category</div><select value={f.category} onChange={(e) => setF({ ...f, category: e.target.value })} className={inputClass}>{CATEGORIES.map((c) => <option key={c}>{c}</option>)}</select></label>
          <label><div className={labelClass}>Vendor</div><input value={f.vendor} onChange={(e) => setF({ ...f, vendor: e.target.value })} className={inputClass} /></label>
          <label className="col-span-2"><div className={labelClass}>Serial number</div><input value={f.serial_number} onChange={(e) => setF({ ...f, serial_number: e.target.value })} className={`${inputClass} font-mono`} data-testid="asset-serial" /></label>
          <label><div className={labelClass}>Location</div><input value={f.location} onChange={(e) => setF({ ...f, location: e.target.value })} className={inputClass} placeholder="Cyber 1 · Metta Rack B12" /></label>
          <label><div className={labelClass}>Acquisition date (Tgl Perolehan) *</div><input required type="date" value={f.purchase_date} onChange={(e) => setF({ ...f, purchase_date: e.target.value })} className={inputClass} data-testid="asset-purchase-date" /></label>
          <label><div className={labelClass}>Acquisition Cost / Harga Perolehan (IDR) *</div><input required type="number" min="0" step="0.01" value={f.value} onChange={(e) => setF({ ...f, value: e.target.value })} className={`${inputClass} text-right tabular-nums`} data-testid="asset-value" /></label>
          <label><div className={labelClass}>Salvage / Nilai Sisa (IDR)</div><input type="number" min="0" step="0.01" value={f.salvage_value} onChange={(e) => setF({ ...f, salvage_value: e.target.value })} className={`${inputClass} text-right tabular-nums`} data-testid="asset-salvage" /></label>
          <label className="col-span-2"><div className={labelClass}>Useful Life / Umur Ekonomis (tahun) *</div><input required type="number" min="1" max="100" value={f.useful_life_years} onChange={(e) => setF({ ...f, useful_life_years: e.target.value })} className={`${inputClass} text-right tabular-nums`} data-testid="asset-life-years" /></label>
          <label className="col-span-2"><div className={labelClass}>Notes</div><textarea rows={2} value={f.notes} onChange={(e) => setF({ ...f, notes: e.target.value })} className={`${inputClass} h-auto py-2`} /></label>
        </div>

        {/* Live preview */}
        <div className="mt-4 rounded-2xl border border-dashed border-slate-300 bg-slate-50 p-4" data-testid="asset-preview">
          <div className="text-[10px] font-bold uppercase tracking-widest text-slate-500 flex items-center gap-2">
            <Calculator className="h-3 w-3" /> Preview — Straight-Line
          </div>
          {preview ? (
            <div className="mt-2 grid grid-cols-1 sm:grid-cols-3 gap-4">
              <div>
                <div className="text-xs text-slate-500">Depreciable Base</div>
                <div className="text-lg font-extrabold text-[#0a2350] tabular-nums">{money(preview.base)}</div>
              </div>
              <div>
                <div className="text-xs text-slate-500">Annual / per Tahun</div>
                <div className="text-lg font-extrabold text-[#0a2350] tabular-nums" data-testid="preview-annual">{money(preview.annual)}</div>
              </div>
              <div>
                <div className="text-xs text-slate-500">Monthly / per Bulan</div>
                <div className="text-lg font-extrabold text-[#0a2350] tabular-nums" data-testid="preview-monthly">{money(preview.monthly)}</div>
              </div>
            </div>
          ) : (
            <div className="mt-2 text-sm text-slate-500">Fill in acquisition cost and useful life to see the preview.</div>
          )}
        </div>

        <div className="mt-5 flex justify-end gap-2">
          <button type="button" className={btnSecondary} onClick={onClose}>Cancel</button>
          <button type="submit" className={btnPrimary} data-testid="asset-submit">Save</button>
        </div>
      </form>
    </div>
  );
};

const ScheduleModal = ({ asset, onClose }) => {
  return (
    <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4" onClick={onClose}>
      <div onClick={(e) => e.stopPropagation()} className="w-full max-w-2xl bg-white rounded-3xl p-6 max-h-[92vh] overflow-y-auto" data-testid="asset-schedule-modal">
        <div className="flex items-start justify-between">
          <div>
            <h3 className="text-xl font-extrabold text-[#0a2350]">{asset.name}</h3>
            <div className="text-xs text-slate-500">Depreciation schedule (Straight-Line) · {asset.useful_life_years} year(s)</div>
          </div>
          <button type="button" onClick={onClose} className="text-slate-400 hover:text-slate-700"><X className="h-5 w-5" /></button>
        </div>

        <div className="mt-4 grid grid-cols-2 sm:grid-cols-4 gap-3 text-sm">
          <div><div className="text-[10px] font-bold uppercase tracking-widest text-slate-500">Cost</div><div className="font-bold tabular-nums">{money(asset.value)}</div></div>
          <div><div className="text-[10px] font-bold uppercase tracking-widest text-slate-500">Salvage</div><div className="font-bold tabular-nums">{money(asset.salvage_value)}</div></div>
          <div><div className="text-[10px] font-bold uppercase tracking-widest text-slate-500">Annual</div><div className="font-bold tabular-nums text-amber-700">{money(asset.annual_depreciation)}</div></div>
          <div><div className="text-[10px] font-bold uppercase tracking-widest text-slate-500">Book Value</div><div className="font-bold tabular-nums text-emerald-700">{money(asset.book_value)}</div></div>
        </div>

        <div className="mt-4 overflow-x-auto rounded-2xl border border-slate-200">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-[11px] font-bold uppercase tracking-widest text-slate-500">
              <tr>
                <th className="px-4 py-3 text-left">Period</th>
                <th className="px-4 py-3 text-left">Year</th>
                <th className="px-4 py-3 text-right">Depreciation</th>
                <th className="px-4 py-3 text-right">Accumulated</th>
                <th className="px-4 py-3 text-right">Book Value</th>
              </tr>
            </thead>
            <tbody>
              {(asset.schedule || []).map((r) => (
                <tr key={r.period} className="border-t border-slate-100">
                  <td className="px-4 py-3 tabular-nums">{r.period} / {asset.useful_life_years}</td>
                  <td className="px-4 py-3 tabular-nums">{r.year}</td>
                  <td className="px-4 py-3 text-right tabular-nums">{money(r.depreciation)}</td>
                  <td className="px-4 py-3 text-right tabular-nums text-amber-700">{money(r.accumulated_depreciation)}</td>
                  <td className="px-4 py-3 text-right tabular-nums text-emerald-700">{money(r.book_value)}</td>
                </tr>
              ))}
              {(!asset.schedule || asset.schedule.length === 0) && (
                <tr><td colSpan={5} className="px-4 py-10 text-center text-slate-400">No schedule (missing life or acquisition date).</td></tr>
              )}
            </tbody>
          </table>
        </div>

        <div className="mt-4 flex justify-end">
          <button type="button" className={btnPrimary} onClick={onClose}>Close</button>
        </div>
      </div>
    </div>
  );
};

export default AdminAssets;
