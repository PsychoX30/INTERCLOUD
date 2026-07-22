import React, { useEffect, useState } from "react";
import { api, getToken } from "../../../portal/api";
import { PageHeader, Card, Loading, EmptyState, btnPrimary, btnSecondary, inputClass, labelClass } from "../ui";
import { Download, Plus, Trash2, Lock, TrendingUp, Wallet, HandCoins, Users, ShoppingCart, ReceiptText } from "lucide-react";

const idr = (v) => "Rp " + Number(v || 0).toLocaleString("id-ID", { maximumFractionDigits: 0 });
const BASE = process.env.REACT_APP_BACKEND_URL;

const TABS = [
  { key: "summary",   label: "Summary",     icon: TrendingUp },
  { key: "revenue",   label: "Revenue",     icon: ReceiptText },
  { key: "expenses",  label: "Expenses",    icon: Wallet },
  { key: "kas_kecil", label: "Kas Kecil",   icon: HandCoins },
  { key: "salaries",  label: "Salaries",    icon: Users },
  { key: "sales_fees",label: "Sales Fees",  icon: ShoppingCart },
  { key: "assets",    label: "Assets",      icon: Lock },
  { key: "reports",   label: "Reports",     icon: Download },
];

const AdminFinance = () => {
  const [d, setD] = useState(null);
  const [tab, setTab] = useState("summary");
  const load = () => api.get("/admin/finance/detailed").then((r) => setD(r.data));
  useEffect(() => { load(); }, []);
  if (!d) return <Loading />;

  const t = d.totals;
  const currentMonth = new Date().toISOString().slice(0, 7);
  const currentYear = new Date().getFullYear();
  const dlUrl = (kind, period) => `${BASE}/api/portal/admin/finance/report/${kind}/${period}?token=${encodeURIComponent(getToken() || "")}`;

  return (
    <div>
      <PageHeader
        title="Finance"
        subtitle="Revenue, all four expense ledgers, asset depreciation and downloadable monthly & annual Excel reports."
        actions={
          <div className="flex gap-2">
            <a href={dlUrl("monthly", currentMonth)} className={btnSecondary} data-testid="dl-monthly"><Download className="h-4 w-4" /> This month</a>
            <a href={dlUrl("annual", currentYear)} className={btnPrimary} data-testid="dl-annual"><Download className="h-4 w-4" /> {currentYear} annual</a>
          </div>
        }
      />

      {/* KPI cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4">
        <KPI label="Total revenue" value={idr(t.revenue)} tone="emerald" testid="kpi-revenue" />
        <KPI label="All expenses" value={idr(t.expenses_all)} tone="red" testid="kpi-expenses" />
        <KPI label="Accum. depreciation" value={idr(t.depreciation_accumulated)} tone="slate" testid="kpi-depreciation" />
        <KPI label={t.net_profit >= 0 ? "Net profit" : "Net loss"} value={idr(t.net_profit)} tone={t.net_profit >= 0 ? "navy" : "red"} testid="kpi-net" />
      </div>

      {/* Tabs */}
      <div className="flex gap-2 mb-4 overflow-x-auto pb-1">
        {TABS.map((x) => {
          const Ico = x.icon;
          return (
            <button key={x.key} onClick={() => setTab(x.key)} data-testid={`fin-tab-${x.key}`}
              className={`h-9 px-4 rounded-full text-xs font-bold uppercase tracking-widest inline-flex items-center gap-1.5 whitespace-nowrap ${
                tab === x.key ? "bg-[#0a2350] text-white" : "bg-white text-slate-500 border border-slate-200 hover:border-[#0a2350]"
              }`}>
              <Ico className="h-3.5 w-3.5" /> {x.label}
            </button>
          );
        })}
      </div>

      {tab === "summary" && <SummaryPane t={t} d={d} />}
      {tab === "revenue" && <RevenueList rows={d.revenue_rows} />}
      {tab === "expenses" && <LedgerPane rows={d.expenses_rows} onChange={load} kind="expenses" extras={["category","vendor","description"]} />}
      {tab === "kas_kecil" && <LedgerPane rows={d.kas_kecil_rows} onChange={load} kind="kas-kecil" extras={["category","vendor","notes"]} />}
      {tab === "salaries" && <LedgerPane rows={d.salaries_rows} onChange={load} kind="salaries" extras={["employee","category","notes"]} />}
      {tab === "sales_fees" && <LedgerPane rows={d.sales_fees_rows} onChange={load} kind="sales-fees" extras={["sales_person","invoice_number","notes"]} />}
      {tab === "assets" && <AssetsList rows={d.assets_rows} />}
      {tab === "reports" && <ReportsPane dlUrl={dlUrl} />}
    </div>
  );
};

const KPI = ({ label, value, tone = "navy", testid }) => {
  const toneCls = { emerald: "text-emerald-700", red: "text-red-700", slate: "text-slate-700", navy: "text-[#0a2350]" }[tone];
  return (
    <Card className="p-4">
      <div className="text-[10px] font-bold uppercase tracking-widest text-slate-500">{label}</div>
      <div className={`text-lg md:text-2xl font-extrabold mt-1 ${toneCls}`} data-testid={testid}>{value}</div>
    </Card>
  );
};

const SummaryPane = ({ t, d }) => (
  <Card className="p-5">
    <div className="grid grid-cols-2 md:grid-cols-3 gap-4 text-sm">
      <div><div className="text-slate-500 text-xs">Revenue</div><div className="font-extrabold text-emerald-700">{idr(t.revenue)}</div></div>
      <div><div className="text-slate-500 text-xs">Recurring expenses</div><div className="font-extrabold">{idr(t.expenses_recurring)}</div></div>
      <div><div className="text-slate-500 text-xs">Kas Kecil</div><div className="font-extrabold">{idr(t.kas_kecil)}</div></div>
      <div><div className="text-slate-500 text-xs">Salaries</div><div className="font-extrabold">{idr(t.salaries)}</div></div>
      <div><div className="text-slate-500 text-xs">Sales fees</div><div className="font-extrabold">{idr(t.sales_fees)}</div></div>
      <div><div className="text-slate-500 text-xs">Total expenses</div><div className="font-extrabold text-red-700">{idr(t.expenses_all)}</div></div>
      <div><div className="text-slate-500 text-xs">Accumulated depreciation</div><div className="font-extrabold">{idr(t.depreciation_accumulated)}</div></div>
      <div className="col-span-2"><div className="text-slate-500 text-xs">Net profit (rev − exp − depreciation)</div><div className={`text-2xl font-extrabold ${t.net_profit >= 0 ? "text-emerald-700" : "text-red-700"}`}>{idr(t.net_profit)}</div></div>
    </div>
  </Card>
);

const RevenueList = ({ rows }) => (
  <div className="rounded-2xl bg-white border border-slate-200 overflow-x-auto">
    <table className="w-full min-w-[720px] text-sm">
      <thead className="bg-slate-50 text-[11px] font-bold uppercase tracking-widest text-slate-500">
        <tr><th className="px-4 py-3 text-left">Paid</th><th className="px-4 py-3 text-left">Invoice #</th><th className="px-4 py-3 text-left">Customer</th><th className="px-4 py-3 text-right">Amount</th></tr>
      </thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r.id} className="border-t border-slate-100"><td className="px-4 py-3 text-slate-600">{r.paid_at}</td><td className="px-4 py-3 font-semibold">{r.number}</td><td className="px-4 py-3">{r.customer || "—"}</td><td className="px-4 py-3 text-right font-bold text-emerald-700">{idr(r.total)}</td></tr>
        ))}
        {rows.length === 0 && <tr><td colSpan="4" className="p-8 text-center text-slate-400">No paid invoices in the period.</td></tr>}
      </tbody>
    </table>
  </div>
);

const AssetsList = ({ rows }) => (
  <div className="rounded-2xl bg-white border border-slate-200 overflow-x-auto">
    <table className="w-full min-w-[860px] text-sm">
      <thead className="bg-slate-50 text-[11px] font-bold uppercase tracking-widest text-slate-500">
        <tr><th className="px-4 py-3 text-left">Asset</th><th className="px-4 py-3 text-left">Category</th><th className="px-4 py-3 text-left">Purchased</th><th className="px-4 py-3 text-right">Cost</th><th className="px-4 py-3 text-right">Salvage</th><th className="px-4 py-3 text-right">Life (yr)</th><th className="px-4 py-3 text-right">Annual dep.</th><th className="px-4 py-3 text-right">Book value</th><th className="px-4 py-3 text-right">Accum. dep.</th></tr>
      </thead>
      <tbody>
        {rows.map((a) => (
          <tr key={a.id} className="border-t border-slate-100"><td className="px-4 py-3 font-semibold text-[#0a2350]">{a.name}</td><td className="px-4 py-3">{a.category}</td><td className="px-4 py-3 text-slate-600">{a.purchase_date}</td><td className="px-4 py-3 text-right tabular-nums">{idr(a.value)}</td><td className="px-4 py-3 text-right tabular-nums text-slate-500">{idr(a.salvage_value || 0)}</td><td className="px-4 py-3 text-right tabular-nums">{a.useful_life_years || "—"}</td><td className="px-4 py-3 text-right tabular-nums text-amber-700">{idr(a.annual_depreciation || 0)}</td><td className="px-4 py-3 text-right font-bold tabular-nums">{idr(a.book_value)}</td><td className="px-4 py-3 text-right tabular-nums text-red-700">{idr(a.accumulated_depreciation)}</td></tr>
        ))}
      </tbody>
    </table>
  </div>
);

const LedgerPane = ({ rows, onChange, kind, extras }) => {
  const [adding, setAdding] = useState(false);
  const [form, setForm] = useState({ date: new Date().toISOString().slice(0, 10), amount: 0 });
  const [err, setErr] = useState("");

  const submit = async (e) => {
    e.preventDefault();
    setErr("");
    try {
      await api.post(`/admin/${kind}`, form);
      setAdding(false);
      setForm({ date: new Date().toISOString().slice(0, 10), amount: 0 });
      onChange();
    } catch (e2) {
      setErr(e2?.response?.data?.detail || "Failed to save");
    }
  };
  const del = async (id, period) => {
    if (!window.confirm("Delete?")) return;
    try { await api.delete(`/admin/${kind}/${id}`); onChange(); }
    catch (e) { alert(e?.response?.data?.detail || "Delete failed"); }
  };
  const total = rows.reduce((s, r) => s + Number(r.amount || 0), 0);

  return (
    <div>
      <div className="mb-3 flex justify-between items-center">
        <div className="text-sm text-slate-500">
          <b className="text-[#0a2350]">{rows.length}</b> entries · Total <b className="text-red-700">{idr(total)}</b>
        </div>
        <button onClick={() => setAdding(!adding)} className={btnPrimary} data-testid={`add-${kind}`}><Plus className="h-4 w-4" /> Add entry</button>
      </div>

      {adding && (
        <Card className="p-4 mb-3">
          {err && <div className="text-sm bg-red-50 border border-red-200 text-red-700 rounded px-3 py-2 mb-2">{err}</div>}
          <form onSubmit={submit} className="grid grid-cols-2 md:grid-cols-4 gap-2">
            <label><div className={labelClass}>Date</div><input type="date" required value={form.date} onChange={(e) => setForm({ ...form, date: e.target.value })} className={inputClass} data-testid={`${kind}-date`} /></label>
            <label><div className={labelClass}>Amount (IDR)</div><input type="number" required value={form.amount} onChange={(e) => setForm({ ...form, amount: Number(e.target.value) })} className={inputClass} data-testid={`${kind}-amount`} /></label>
            {extras.map((k) => (
              <label key={k}><div className={labelClass}>{k.replace(/_/g, " ")}</div><input value={form[k] || ""} onChange={(e) => setForm({ ...form, [k]: e.target.value })} className={inputClass} data-testid={`${kind}-${k}`} /></label>
            ))}
            <div className="col-span-full flex justify-end gap-2 mt-2">
              <button type="button" onClick={() => setAdding(false)} className={btnSecondary}>Cancel</button>
              <button type="submit" className={btnPrimary} data-testid={`${kind}-submit`}>Save</button>
            </div>
          </form>
        </Card>
      )}

      <div className="rounded-2xl bg-white border border-slate-200 overflow-x-auto">
        <table className="w-full min-w-[720px] text-sm">
          <thead className="bg-slate-50 text-[11px] font-bold uppercase tracking-widest text-slate-500">
            <tr>
              <th className="px-4 py-3 text-left">Date</th>
              {extras.map((k) => <th key={k} className="px-4 py-3 text-left">{k.replace(/_/g, " ")}</th>)}
              <th className="px-4 py-3 text-right">Amount</th><th className="px-4 py-3"></th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id} className="border-t border-slate-100">
                <td className="px-4 py-3 text-slate-600">{r.date}</td>
                {extras.map((k) => <td key={k} className="px-4 py-3">{r[k] || "—"}</td>)}
                <td className="px-4 py-3 text-right font-bold text-red-700">{idr(r.amount)}</td>
                <td className="px-4 py-3 text-right">
                  <button onClick={() => del(r.id, r.period_yyyy_mm)} className="text-slate-600 hover:text-red-600" title="Delete"><Trash2 className="h-4 w-4" /></button>
                </td>
              </tr>
            ))}
            {rows.length === 0 && <tr><td colSpan={extras.length + 3} className="p-8 text-center text-slate-400">No entries yet.</td></tr>}
          </tbody>
        </table>
      </div>
    </div>
  );
};

const ReportsPane = ({ dlUrl }) => {
  const [rows, setRows] = useState(null);
  useEffect(() => { api.get("/admin/finance/reports").then((r) => setRows(r.data)); }, []);
  if (!rows) return <Loading />;

  const now = new Date();
  const months = [];
  for (let i = 0; i < 12; i++) {
    const d = new Date(now.getFullYear(), now.getMonth() - i, 1);
    months.push(d.toISOString().slice(0, 7));
  }

  return (
    <div className="space-y-4">
      <Card className="p-5">
        <div className="font-bold text-[#0a2350] mb-3">Download by month (last 12 months)</div>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
          {months.map((m) => (
            <a key={m} href={dlUrl("monthly", m)} className="p-3 rounded-xl border border-slate-200 bg-white hover:bg-slate-50 flex justify-between items-center" data-testid={`dl-month-${m}`}>
              <span className="text-sm font-bold text-[#0a2350]">{m}</span>
              <Download className="h-4 w-4 text-[#f5b120]" />
            </a>
          ))}
        </div>
      </Card>

      <Card className="p-5">
        <div className="font-bold text-[#0a2350] mb-3">Annual report</div>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
          {[0, 1, 2].map((offset) => {
            const y = now.getFullYear() - offset;
            return (
              <a key={y} href={dlUrl("annual", y)} className="p-4 rounded-xl border-2 border-[#0a2350]/20 bg-slate-50 hover:bg-[#0a2350] hover:text-white text-[#0a2350] transition-colors" data-testid={`dl-year-${y}`}>
                <div className="text-2xl font-extrabold">{y}</div>
                <div className="text-xs opacity-70 mt-1"><Download className="h-3 w-3 inline" /> Full year P&amp;L + Assets</div>
              </a>
            );
          })}
        </div>
      </Card>

      {rows.length > 0 && (
        <Card className="p-5">
          <div className="font-bold text-[#0a2350] mb-3">Previously generated reports</div>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[720px] text-sm">
              <thead className="bg-slate-50 text-[11px] font-bold uppercase tracking-widest text-slate-500">
                <tr><th className="px-4 py-3 text-left">Period</th><th className="px-4 py-3 text-left">Kind</th><th className="px-4 py-3 text-right">Revenue</th><th className="px-4 py-3 text-right">Expenses</th><th className="px-4 py-3 text-right">Net</th><th className="px-4 py-3 text-left">Generated</th><th className="px-4 py-3 text-left">Status</th></tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.id} className="border-t border-slate-100">
                    <td className="px-4 py-3 font-bold text-[#0a2350]">{r.period}</td>
                    <td className="px-4 py-3 uppercase text-xs">{r.kind}</td>
                    <td className="px-4 py-3 text-right text-emerald-700">{idr(r.totals?.revenue)}</td>
                    <td className="px-4 py-3 text-right text-red-700">{idr(r.totals?.expenses_all)}</td>
                    <td className="px-4 py-3 text-right font-bold">{idr(r.totals?.net_profit)}</td>
                    <td className="px-4 py-3 text-slate-500 text-xs">{r.generated_at?.slice(0, 10)}</td>
                    <td className="px-4 py-3">
                      {r.locked ? <span className="text-[10px] font-bold uppercase text-red-700 bg-red-100 px-2 py-0.5 rounded"><Lock className="h-3 w-3 inline mr-0.5" /> Locked</span> : <span className="text-[10px] font-bold uppercase text-emerald-700 bg-emerald-100 px-2 py-0.5 rounded">Editable</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}
    </div>
  );
};

export default AdminFinance;
