import React, { useEffect, useState } from "react";
import { api } from "../../../portal/api";
import { PageHeader, Card, Loading, EmptyState, btnSecondary } from "../ui";
import { TrendingUp, Users, ServerCog, ShieldCheck, ReceiptText, AlertTriangle, RefreshCw, Award } from "lucide-react";
import { ResponsiveContainer, LineChart, Line, XAxis, YAxis, Tooltip, CartesianGrid, BarChart, Bar } from "recharts";

const idr = (v) => "Rp " + Number(v || 0).toLocaleString("id-ID", { maximumFractionDigits: 0 });
const idrShort = (v) => {
  const n = Number(v || 0);
  if (n >= 1_000_000_000) return `Rp ${(n / 1_000_000_000).toFixed(1)} B`;
  if (n >= 1_000_000) return `Rp ${(n / 1_000_000).toFixed(1)} M`;
  if (n >= 1_000) return `Rp ${(n / 1_000).toFixed(0)} rb`;
  return `Rp ${n.toFixed(0)}`;
};

const AdminOwnerDashboard = () => {
  const [d, setD] = useState(null);
  const load = () => api.get("/admin/owner/overview").then((r) => setD(r.data));
  useEffect(() => { load(); }, []);
  if (!d) return <Loading label="Aggregating executive metrics…" />;

  return (
    <div data-testid="owner-dashboard-page">
      <PageHeader
        title="Executive Overview"
        subtitle="Read-only, fleet-wide summary — MRR, ARR, ARPU, churn, revenue trend, NOC uptime, SLA outage minutes, and top-revenue clients. Refreshes on demand."
        actions={<button className={btnSecondary} onClick={load} data-testid="owner-refresh"><RefreshCw className="h-4 w-4" /> Refresh</button>}
      />

      {/* Top KPI row: MRR / ARR / ARPU / Churn */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4">
        <BigKPI label="MRR" value={idrShort(d.mrr)} sub={`ARR ${idrShort(d.arr)}`} tone="emerald" testid="owner-mrr" Icon={TrendingUp} />
        <BigKPI label="ARPU" value={idrShort(d.arpu)} sub={`${d.clients_with_active_service} paying clients`} tone="sky" testid="owner-arpu" Icon={Users} />
        <BigKPI label="Churn (30d)" value={`${d.churn_pct_30d}%`} sub={`of ${d.active_services + 0} active services`} tone={d.churn_pct_30d > 5 ? "danger" : "warn"} testid="owner-churn" Icon={AlertTriangle} />
        <BigKPI label="Revenue MTD" value={idrShort(d.revenue_month_to_date)} sub={`${d.unpaid_invoices} unpaid · overdue ${idrShort(d.overdue_total)}`} tone="navy" testid="owner-revenue-mtd" Icon={ReceiptText} />
      </div>

      {/* NOC + Support row */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6">
        <BigKPI label="NOC Uptime (24h)" value={d.noc.uptime_24h_pct == null ? "—" : `${d.noc.uptime_24h_pct}%`}
                sub={`${d.noc.samples_24h} probes · ${d.noc.devices_down}/${d.noc.devices_total} down`}
                tone={d.noc.uptime_24h_pct == null ? "default" : d.noc.uptime_24h_pct >= 99.5 ? "emerald" : d.noc.uptime_24h_pct >= 99 ? "warn" : "danger"}
                testid="owner-uptime-24h" Icon={ShieldCheck} />
        <BigKPI label="NOC Uptime (7d)" value={d.noc.uptime_7d_pct == null ? "—" : `${d.noc.uptime_7d_pct}%`} sub="Rolling 7-day fleet avg" tone={d.noc.uptime_7d_pct == null ? "default" : d.noc.uptime_7d_pct >= 99.5 ? "emerald" : "warn"} testid="owner-uptime-7d" Icon={ShieldCheck} />
        <BigKPI label="Outage minutes (30d)" value={d.noc.outage_minutes_30d} sub="Sum of 5-min down samples" tone={d.noc.outage_minutes_30d > 60 ? "danger" : "warn"} testid="owner-outage-30d" Icon={AlertTriangle} />
        <BigKPI label="Open tickets" value={d.support.open_tickets} sub={`${d.support.critical_open} critical`} tone={d.support.critical_open > 0 ? "danger" : "default"} testid="owner-tickets" Icon={ServerCog} />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 mb-6">
        <Card className="p-5 lg:col-span-2">
          <div className="text-sm font-bold text-[#0a2350] mb-1">Revenue trend — last 12 months</div>
          <div className="text-xs text-slate-500 mb-3">Paid invoices summed by month.</div>
          <div className="h-72" style={{ minWidth: 0 }}>
            <ResponsiveContainer width="100%" height="100%" minHeight={288}>
              <LineChart data={d.revenue_trend_12m}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                <XAxis dataKey="period" tick={{ fontSize: 10, fill: "#64748b" }} />
                <YAxis tickFormatter={idrShort} tick={{ fontSize: 10, fill: "#64748b" }} width={80} />
                <Tooltip formatter={(v) => idr(v)} labelStyle={{ color: "#0a2540" }} />
                <Line type="monotone" dataKey="revenue" stroke="#0a2540" strokeWidth={2.5} dot={{ fill: "#f5b120", r: 4 }} activeDot={{ r: 6 }} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </Card>
        <Card className="p-5">
          <div className="text-sm font-bold text-[#0a2350] mb-3">Top clients by lifetime revenue</div>
          {d.top_clients.length === 0 ? (
            <EmptyState title="No paid invoices yet" />
          ) : (
            <div className="space-y-2">
              {d.top_clients.map((c, i) => (
                <div key={c.user_id} className="flex items-center gap-3 p-2 rounded-lg hover:bg-slate-50" data-testid={`owner-topclient-${i}`}>
                  <div className={`h-8 w-8 rounded-full flex items-center justify-center text-xs font-extrabold text-white ${i === 0 ? "bg-amber-500" : i === 1 ? "bg-slate-400" : i === 2 ? "bg-amber-700" : "bg-slate-300"}`}>
                    <Award className="h-4 w-4" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="text-sm font-semibold text-[#0a2350] truncate">{c.name || c.email}</div>
                    <div className="text-xs text-slate-500 truncate">{c.email}</div>
                  </div>
                  <div className="text-sm font-extrabold text-emerald-700 whitespace-nowrap">{idrShort(c.lifetime_revenue)}</div>
                </div>
              ))}
            </div>
          )}
        </Card>
      </div>

      <Card className="p-5 mb-6">
        <div className="text-sm font-bold text-[#0a2350] mb-1">Invoices generated per month</div>
        <div className="text-xs text-slate-500 mb-3">Volume of paid invoices — signals sales/renewal cadence.</div>
        <div className="h-56" style={{ minWidth: 0 }}>
          <ResponsiveContainer width="100%" height="100%" minHeight={224}>
            <BarChart data={d.revenue_trend_12m}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
              <XAxis dataKey="period" tick={{ fontSize: 10, fill: "#64748b" }} />
              <YAxis allowDecimals={false} tick={{ fontSize: 10, fill: "#64748b" }} />
              <Tooltip />
              <Bar dataKey="invoices" fill="#f5b120" radius={[6, 6, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </Card>

      <div className="text-[11px] text-slate-400 text-right" data-testid="owner-generated-at">
        Generated at {d.generated_at}
      </div>
    </div>
  );
};

const BigKPI = ({ label, value, sub, tone = "default", testid, Icon }) => {
  const toneClass = {
    default: "border-slate-200",
    navy:    "border-[#0a2540]/20 bg-[#0a2540]/[0.03]",
    emerald: "border-emerald-200 bg-emerald-50/60",
    sky:     "border-sky-200 bg-sky-50/60",
    warn:    "border-amber-200 bg-amber-50/60",
    danger:  "border-red-200 bg-red-50/60",
  }[tone];
  return (
    <div className={`rounded-2xl bg-white border p-4 ${toneClass}`} data-testid={testid}>
      <div className="flex items-center justify-between mb-1">
        <div className="text-[10px] font-bold uppercase tracking-widest text-slate-500">{label}</div>
        {Icon && <Icon className="h-4 w-4 text-slate-400" />}
      </div>
      <div className="text-2xl md:text-3xl font-extrabold text-[#0a2350]">{value}</div>
      {sub && <div className="text-[11px] text-slate-500 mt-1">{sub}</div>}
    </div>
  );
};

export default AdminOwnerDashboard;
