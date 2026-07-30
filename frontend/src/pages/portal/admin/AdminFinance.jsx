import React, { useEffect, useState } from "react";
import { api, getToken } from "../../../portal/api";
import { PageHeader, Card, Loading, EmptyState, btnPrimary, btnSecondary, inputClass, labelClass } from "../ui";
import { Download, Plus, Trash2, Lock, TrendingUp, Wallet, HandCoins, Users, ShoppingCart, ReceiptText, Percent, Save, Loader2, Activity, FileText, Send, Mail } from "lucide-react";
import { ComposedChart, Bar, Line, XAxis, YAxis, Tooltip as ReTooltip, CartesianGrid, ResponsiveContainer, Legend } from "recharts";

const idr = (v) => "Rp " + Number(v || 0).toLocaleString("id-ID", { maximumFractionDigits: 0 });
const BASE = process.env.REACT_APP_BACKEND_URL;

const TABS = [
  { key: "summary",   label: "Summary",     icon: TrendingUp },
  { key: "cashflow",  label: "Cash-flow",   icon: Activity },
  { key: "revenue",   label: "Revenue",     icon: ReceiptText },
  { key: "expenses",  label: "Expenses",    icon: Wallet },
  { key: "kas_kecil", label: "Kas Kecil",   icon: HandCoins },
  { key: "salaries",  label: "Salaries",    icon: Users },
  { key: "sales_fees",label: "Sales Fees",  icon: ShoppingCart },
  { key: "assets",    label: "Assets",      icon: Lock },
  { key: "billing",   label: "Billing Defaults", icon: Percent },
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
      {tab === "cashflow" && <CashflowPane />}
      {tab === "revenue" && <RevenueList rows={d.revenue_rows} />}
      {tab === "expenses" && <LedgerPane rows={d.expenses_rows} onChange={load} kind="expenses" extras={["category","vendor","description"]} />}
      {tab === "kas_kecil" && <LedgerPane rows={d.kas_kecil_rows} onChange={load} kind="kas-kecil" extras={["category","vendor","notes"]} />}
      {tab === "salaries" && <LedgerPane rows={d.salaries_rows} onChange={load} kind="salaries" extras={["employee","category","notes"]} rowAction={(r) => (
        <a
          href={`${BASE}/api/portal/documents/salary-slip/${r.id}?format=pdf&token=${encodeURIComponent(getToken() || "")}`}
          className="inline-flex items-center gap-1 text-xs font-bold text-[#0a2350] hover:text-[#f5b120]"
          title="Unduh slip gaji PDF"
          data-testid={`salary-slip-${r.id}`}
        >
          <FileText className="h-4 w-4" /> Slip
        </a>
      )} />}
      {tab === "sales_fees" && <LedgerPane rows={d.sales_fees_rows} onChange={load} kind="sales-fees" extras={["sales_person","invoice_number","notes"]} rowAction={(r) => (
        <a
          href={`${BASE}/api/portal/documents/sales-fee-slip/${r.id}?format=pdf&token=${encodeURIComponent(getToken() || "")}`}
          className="inline-flex items-center gap-1 text-xs font-bold text-[#0a2350] hover:text-[#f5b120]"
          title="Unduh slip fee sales PDF"
          data-testid={`sales-fee-slip-${r.id}`}
        >
          <FileText className="h-4 w-4" /> Slip
        </a>
      )} />}
      {tab === "assets" && <AssetsList rows={d.assets_rows} />}
      {tab === "billing" && <BillingDefaultsPane />}
      {tab === "reports" && <ReportsPane dlUrl={dlUrl} />}
    </div>
  );
};

const BillingDefaultsPane = () => {
  const [form, setForm] = useState(null);
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);
  const [err, setErr] = useState("");

  useEffect(() => {
    api.get("/admin/billing/settings").then((r) => setForm(r.data)).catch((e) => setErr(e?.response?.data?.detail || e.message));
  }, []);

  const save = async () => {
    setBusy(true); setErr(""); setSaved(false);
    try {
      const { data } = await api.put("/admin/billing/settings", {
        default_tax_percent: Number(form.default_tax_percent),
        renewal_lead_days: Number(form.renewal_lead_days),
        noc_alert_recipients: form.noc_alert_recipients || [],
      });
      setForm(data); setSaved(true); setTimeout(() => setSaved(false), 2500);
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message);
    } finally { setBusy(false); }
  };

  if (!form) return <Loading />;
  const recipientsText = Array.isArray(form.noc_alert_recipients)
    ? form.noc_alert_recipients.join("\n")
    : (form.noc_alert_recipients || "");
  return (
    <Card>
      <div className="max-w-xl p-5">
        <div className="text-lg font-bold text-[#0a2350] mb-1">Billing Defaults</div>
        <p className="text-sm text-slate-500 mb-5">
          Nilai PPN di bawah hanyalah <b>saran awal</b> yang di-prefill saat membuat invoice/quotation
          baru dan invoice renewal otomatis - selalu bisa diubah manual per dokumen (termasuk 0%).
          Tidak ada perhitungan ulang otomatis setelah dokumen dibuat.
        </p>
        {err && <div className="mb-3 text-sm text-red-700 bg-red-50 border border-red-200 rounded px-3 py-2">{err}</div>}
        <div className="grid grid-cols-2 gap-4 mb-5">
          <label>
            <div className={labelClass}>Default PPN (%)</div>
            <input type="number" min="0" step="0.1" className={inputClass}
              value={form.default_tax_percent}
              onChange={(e) => setForm({ ...form, default_tax_percent: e.target.value })}
              data-testid="billing-default-tax" />
          </label>
          <label>
            <div className={labelClass}>Renewal lead days</div>
            <input type="number" min="1" step="1" className={inputClass}
              value={form.renewal_lead_days}
              onChange={(e) => setForm({ ...form, renewal_lead_days: e.target.value })}
              data-testid="billing-renewal-lead" />
            <div className="text-[11px] text-slate-400 mt-1">Invoice renewal dibuat otomatis N hari sebelum jatuh tempo layanan.</div>
          </label>
        </div>
        <label className="block mb-5">
          <div className={labelClass}>NOC alert recipients</div>
          <textarea
            rows={3}
            className={inputClass + " h-auto py-2 font-mono text-xs"}
            value={recipientsText}
            onChange={(e) => setForm({ ...form, noc_alert_recipients: e.target.value.split(/[\n,]+/).map((s) => s.trim()).filter(Boolean) })}
            placeholder={"ops@example.com\nnoc-lead@example.com"}
            data-testid="billing-noc-recipients"
          />
          <div className="text-[11px] text-slate-400 mt-1">
            Satu email per baris. Alert dikirim saat perangkat MikroTik transisi status (UP↔DOWN).
            Kosongkan untuk fallback ke semua user role=admin.
          </div>
        </label>
        <button className={btnPrimary} onClick={save} disabled={busy} data-testid="billing-save">
          {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />} Simpan
        </button>
        {saved && <span className="ml-3 text-sm font-bold text-emerald-600">Tersimpan ✓</span>}
      </div>
    </Card>
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
  <Card className="p-5" data-testid="finance-pnl">
    <div className="text-sm font-extrabold text-[#0a2350] mb-3">Laporan Laba Rugi (ringkas)</div>
    <div className="max-w-xl text-sm">
      <PnlRow label="Pendapatan (invoice paid)" value={t.revenue} strong tone="emerald" testid="pnl-revenue" />
      <div className="mt-2 mb-1 text-[10px] font-bold uppercase tracking-widest text-slate-500">Beban</div>
      <PnlRow label="Beban operasional (recurring)" value={-t.expenses_recurring} />
      <PnlRow label="Kas kecil" value={-t.kas_kecil} />
      <PnlRow label="Gaji (salaries)" value={-t.salaries} />
      <PnlRow label="Fee sales" value={-t.sales_fees} />
      <PnlRow label="Beban depresiasi aset" value={-t.depreciation_accumulated} testid="pnl-depreciation" />
      <div className="border-t border-slate-200 mt-2 pt-2">
        <PnlRow label="Total beban + depresiasi" value={-(t.expenses_all + t.depreciation_accumulated)} strong tone="red" testid="pnl-total-expenses" />
      </div>
      <div className="border-t-2 border-[#0a2350]/20 mt-2 pt-2">
        <div className="flex items-baseline justify-between">
          <span className="font-extrabold text-[#0a2350]">{t.net_profit >= 0 ? "Laba bersih" : "Rugi bersih"}</span>
          <span className={`text-2xl font-extrabold tabular-nums ${t.net_profit >= 0 ? "text-emerald-700" : "text-red-700"}`} data-testid="pnl-net">{idr(t.net_profit)}</span>
        </div>
        <p className="text-[11px] text-slate-500 mt-1">Depresiasi dicatat sebagai beban terpisah dan tidak mengurangi angka pendapatan.</p>
      </div>
    </div>
  </Card>
);

const PnlRow = ({ label, value, strong, tone, testid }) => {
  const toneCls = tone === "emerald" ? "text-emerald-700" : tone === "red" ? "text-red-700" : value < 0 ? "text-slate-700" : "text-[#0a2350]";
  return (
    <div className="flex items-baseline justify-between py-1">
      <span className={strong ? "font-bold text-[#0a2350]" : "text-slate-600"}>{label}</span>
      <span className={`tabular-nums ${strong ? "font-extrabold" : "font-semibold"} ${toneCls}`} data-testid={testid}>
        {value < 0 ? `(${idr(Math.abs(value))})` : idr(value)}
      </span>
    </div>
  );
};

const RevenueList = ({ rows }) => (
  <div className="rounded-2xl bg-white border border-slate-200 overflow-x-auto">
    <table className="w-full min-w-[720px] text-sm">
      <thead className="bg-slate-50 text-[11px] font-bold uppercase tracking-widest text-slate-500">
        <tr><th className="px-4 py-3 text-left">Paid</th><th className="px-4 py-3 text-left">Invoice #</th><th className="px-4 py-3 text-left">Customer</th><th className="px-4 py-3 text-right">Amount</th></tr>
      </thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r.id} className="border-t border-slate-100"><td className="px-4 py-3 text-slate-600">{r.paid_at}</td><td className="px-4 py-3 font-semibold">{r.number}</td><td className="px-4 py-3">{r.customer || "-"}</td><td className="px-4 py-3 text-right font-bold text-emerald-700">{idr(r.total)}</td></tr>
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
          <tr key={a.id} className="border-t border-slate-100"><td className="px-4 py-3 font-semibold text-[#0a2350]">{a.name}</td><td className="px-4 py-3">{a.category}</td><td className="px-4 py-3 text-slate-600">{a.purchase_date}</td><td className="px-4 py-3 text-right tabular-nums">{idr(a.value)}</td><td className="px-4 py-3 text-right tabular-nums text-slate-500">{idr(a.salvage_value || 0)}</td><td className="px-4 py-3 text-right tabular-nums">{a.useful_life_years || "-"}</td><td className="px-4 py-3 text-right tabular-nums text-amber-700">{idr(a.annual_depreciation || 0)}</td><td className="px-4 py-3 text-right font-bold tabular-nums">{idr(a.book_value)}</td><td className="px-4 py-3 text-right tabular-nums text-red-700">{idr(a.accumulated_depreciation)}</td></tr>
        ))}
      </tbody>
    </table>
  </div>
);

const LedgerPane = ({ rows, onChange, kind, extras, rowAction }) => {
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
                {extras.map((k) => <td key={k} className="px-4 py-3">{r[k] || "-"}</td>)}
                <td className="px-4 py-3 text-right font-bold text-red-700">{idr(r.amount)}</td>
                <td className="px-4 py-3 text-right">
                  <span className="inline-flex items-center gap-3">
                    {rowAction && rowAction(r)}
                    <button onClick={() => del(r.id, r.period_yyyy_mm)} className="text-slate-600 hover:text-red-600" title="Delete"><Trash2 className="h-4 w-4" /></button>
                  </span>
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

const fmtJt = (v) => {
  const a = Math.abs(v);
  if (a >= 1e9) return `${(v / 1e9).toFixed(1)}M`;
  if (a >= 1e6) return `${(v / 1e6).toFixed(1)}jt`;
  if (a >= 1e3) return `${(v / 1e3).toFixed(0)}rb`;
  return `${v}`;
};

const CashflowPane = () => {
  const [f, setF] = useState(null);
  const [err, setErr] = useState("");
  useEffect(() => {
    api.get("/admin/finance/cashflow-forecast")
      .then((r) => setF(r.data))
      .catch((e) => setErr(e?.response?.data?.detail || "Gagal memuat proyeksi"));
  }, []);
  if (err) return <Card className="p-6 text-sm text-red-700">{err}</Card>;
  if (!f) return <Loading />;
  const buckets = [
    { key: "d30", label: "30 hari" },
    { key: "d60", label: "60 hari" },
    { key: "d90", label: "90 hari" },
  ];
  const chart = f.weekly.map((w) => ({ ...w, label: w.week_start.slice(5) }));
  const dl = (fmt) => `${BASE}/api/portal/admin/finance/cashflow-forecast/export?format=${fmt}&token=${encodeURIComponent(getToken() || "")}`;
  return (
    <div data-testid="cashflow-pane">
      <div className="flex justify-end gap-2 mb-4">
        <a href={dl("pdf")} className={btnSecondary} data-testid="cashflow-export-pdf">
          <Download className="h-4 w-4" /> PDF
        </a>
        <a href={dl("xlsx")} className={btnSecondary} data-testid="cashflow-export-xlsx">
          <Download className="h-4 w-4" /> Excel
        </a>
      </div>
      <div className="grid sm:grid-cols-3 gap-4 mb-5">
        {buckets.map((b) => {
          const v = f.buckets[b.key];
          return (
            <Card key={b.key} className="p-5" data-testid={`cashflow-bucket-${b.key}`}>
              <div className="text-[11px] font-bold uppercase tracking-widest text-slate-500">Proyeksi {b.label}</div>
              <div className={`mt-1 text-2xl font-extrabold ${v.net >= 0 ? "text-emerald-600" : "text-red-600"}`}>
                {v.net >= 0 ? "+" : ""}{idr(v.net)}
              </div>
              <div className="mt-2 text-xs text-slate-500 space-y-0.5">
                <div className="flex justify-between"><span>Perkiraan masuk</span><b className="text-emerald-700">{idr(v.inflow)}</b></div>
                <div className="flex justify-between"><span>Perkiraan keluar</span><b className="text-red-700">{idr(v.outflow)}</b></div>
              </div>
            </Card>
          );
        })}
      </div>
      <Card className="p-5" data-testid="cashflow-chart-card">
        <div className="flex items-center justify-between flex-wrap gap-2 mb-3">
          <div>
            <div className="text-sm font-extrabold text-[#0a2350]">Proyeksi arus kas mingguan (90 hari ke depan)</div>
            <div className="text-[11px] text-slate-500">
              Masuk: invoice unpaid/overdue ({f.sources.unpaid_invoices}) + perpanjangan layanan ({f.sources.upcoming_renewals}) ·
              Keluar: run-rate beban {idr(f.monthly_expense_run_rate)}/bulan (rata-rata 3 bulan terakhir)
            </div>
          </div>
          <div className="text-[11px] text-slate-400">per {f.as_of}</div>
        </div>
        <div style={{ height: 330 }}>
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart data={chart} margin={{ top: 6, right: 12, bottom: 0, left: 6 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
              <XAxis dataKey="label" tick={{ fontSize: 11 }} />
              <YAxis tickFormatter={fmtJt} tick={{ fontSize: 11 }} width={54} />
              <ReTooltip formatter={(v, name) => [idr(v), name]} labelFormatter={(l) => `Minggu ${l}`} />
              <Legend wrapperStyle={{ fontSize: 12 }} />
              <Bar dataKey="inflow" name="Masuk" fill="#10b981" radius={[4, 4, 0, 0]} />
              <Bar dataKey="outflow" name="Keluar" fill="#ef4444" radius={[4, 4, 0, 0]} />
              <Line type="monotone" dataKey="cumulative" name="Kumulatif (net)" stroke="#0a2350" strokeWidth={2.5} dot={false} />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      </Card>
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
      <MonthlyArchivePane />
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

const MonthlyArchivePane = () => {
  const [rows, setRows] = useState(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null);
  const load = () => api.get("/admin/reports/monthly").then((r) => setRows(r.data)).catch(() => setRows([]));
  useEffect(() => { load(); }, []);

  const generate = async () => {
    setBusy(true); setMsg(null);
    try {
      const { data } = await api.post("/admin/reports/monthly/send", {});
      setMsg({ ok: true, text: `Laporan ${data.month} dibuat & dikirim ke ${data.to_email} (${data.delivery?.status}).` });
      load();
    } catch (e) {
      setMsg({ ok: false, text: e?.response?.data?.detail || "Gagal membuat laporan" });
    } finally { setBusy(false); }
  };

  const pdfUrl = (month) => `${BASE}/api/portal/admin/reports/monthly/${month}/pdf?token=${encodeURIComponent(getToken() || "")}`;
  const xlsxUrl = (month) => `${BASE}/api/portal/admin/reports/monthly/${month}/xlsx?token=${encodeURIComponent(getToken() || "")}`;

  return (
    <Card className="p-5" data-testid="monthly-archive-pane">
      <div className="flex items-center justify-between mb-1">
        <div className="font-bold text-[#0a2350]">Arsip Laporan Bulanan (tagihan + trafik)</div>
        <button onClick={generate} disabled={busy} className={btnSecondary} data-testid="monthly-archive-generate">
          {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Mail className="h-4 w-4" />}
          {busy ? "Memproses…" : "Generate & kirim bulan lalu"}
        </button>
      </div>
      <p className="text-xs text-slate-500 mb-3">Dikirim otomatis ke email support setiap tanggal 1 pukul 06:30 WIB dan diarsipkan di sini sebagai PDF.</p>
      {msg && (
        <div className={`mb-3 text-xs rounded-lg px-2.5 py-1.5 border ${msg.ok ? "bg-emerald-50 border-emerald-200 text-emerald-800" : "bg-red-50 border-red-200 text-red-700"}`} data-testid="monthly-archive-msg">
          {msg.text}
        </div>
      )}
      {rows === null ? <Loading /> : rows.length === 0 ? (
        <p className="text-sm text-slate-500">Belum ada arsip. Klik "Generate &amp; kirim bulan lalu" untuk membuat laporan pertama.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[720px] text-sm" data-testid="monthly-archive-table">
            <thead className="bg-slate-50 text-[11px] font-bold uppercase tracking-widest text-slate-500">
              <tr>
                <th className="px-4 py-3 text-left">Periode</th>
                <th className="px-4 py-3 text-right">Invoice terbit</th>
                <th className="px-4 py-3 text-right">Dibayar</th>
                <th className="px-4 py-3 text-right">Trafik (GB in/out)</th>
                <th className="px-4 py-3 text-left">Dikirim ke</th>
                <th className="px-4 py-3 text-left">Status</th>
                <th className="px-4 py-3 text-right">PDF</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id} className="border-t border-slate-100" data-testid={`monthly-archive-row-${r.month}`}>
                  <td className="px-4 py-3 font-bold text-[#0a2350]">{r.month}</td>
                  <td className="px-4 py-3 text-right tabular-nums">{r.summary?.invoices_issued ?? 0} · {idr(r.summary?.invoices_issued_total)}</td>
                  <td className="px-4 py-3 text-right tabular-nums text-emerald-700">{r.summary?.invoices_paid ?? 0} · {idr(r.summary?.invoices_paid_total)}</td>
                  <td className="px-4 py-3 text-right tabular-nums">{r.summary?.traffic_in_gb ?? 0} / {r.summary?.traffic_out_gb ?? 0}</td>
                  <td className="px-4 py-3 text-xs text-slate-500">{r.to_email}</td>
                  <td className="px-4 py-3">
                    <span className={`text-[10px] font-bold uppercase px-2 py-0.5 rounded ${r.delivery_status === "sent" ? "bg-emerald-100 text-emerald-700" : "bg-amber-100 text-amber-700"}`}>
                      {r.delivery_status || "-"}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-right">
                    <a href={pdfUrl(r.month)} className="inline-flex items-center gap-1 text-[#0a2350] hover:text-[#f5b120] font-bold text-xs" data-testid={`monthly-archive-pdf-${r.month}`}>
                      <Download className="h-3.5 w-3.5" /> PDF
                    </a>
                    <a href={xlsxUrl(r.month)} className="inline-flex items-center gap-1 text-emerald-700 hover:text-emerald-500 font-bold text-xs ml-3" data-testid={`monthly-archive-xlsx-${r.month}`}>
                      <FileText className="h-3.5 w-3.5" /> Excel
                    </a>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
};

export default AdminFinance;
