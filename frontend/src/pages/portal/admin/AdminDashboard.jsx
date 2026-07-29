import React, { useEffect, useState } from "react";
import { api, money } from "../../../portal/api";
import { PageHeader, Card, Loading, StatCard, StatusBadge } from "../ui";
import { Users, Package, ShoppingCart, Receipt, LifeBuoy, TrendingUp, Bell, CheckCircle2 } from "lucide-react";
import { Link } from "react-router-dom";

const AdminDashboard = () => {
  const [d, setD] = useState(null);
  useEffect(() => {
    const load = () => api.get("/admin/dashboard").then((r) => setD(r.data)).catch(() => {});
    load();
    const t = setInterval(load, 60000);
    return () => clearInterval(t);
  }, []);
  if (!d) return <Loading />;
  const s = d.stats;
  const showFinance = s.revenue_month !== undefined;
  return (
    <div>
      <PageHeader title="Dashboard" subtitle="Ringkasan status bisnis real-time dalam satu layar." />
      <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard label="Total Clients" value={s.total_clients} testid="stat-clients" />
        <StatCard label="Active Services" value={s.active_services} tone="good" testid="stat-services" />
        <StatCard label="Pending Orders" value={s.pending_orders ?? 0} tone={s.pending_orders ? "warn" : "default"} testid="stat-orders" />
        <StatCard label="Open Tickets" value={s.open_tickets} testid="stat-tickets" />
        {showFinance && (<>
          <StatCard label="Revenue (Month)" value={money(s.revenue_month)} tone="good" testid="stat-rev-month" />
          <StatCard label="Revenue (Total)" value={money(s.revenue_total)} testid="stat-rev-total" />
          <StatCard label="Unpaid Invoices" value={s.unpaid_invoices} tone={s.unpaid_invoices ? "warn" : "default"} testid="stat-unpaid" />
          <StatCard label="Overdue Total" value={money(s.overdue_total)} hint={`${s.overdue_invoices || 0} invoice(s)`} tone={s.overdue_total ? "danger" : "default"} testid="stat-overdue" />
        </>)}
      </div>
      <div className="mt-6 grid md:grid-cols-2 gap-4">
        <NotificationCenter alerts={d.alerts || []} />
        <QuickLinks />
      </div>
      <div className="mt-4 grid md:grid-cols-2 gap-4">
        <RecentInvoices rows={d.recent_invoices || []} show={showFinance} />
        <Health items={d.health || []} />
      </div>
    </div>
  );
};

const NotificationCenter = ({ alerts }) => (
  <Card className="p-6 min-w-0" data-testid="notification-center">
    <h3 className="text-lg font-extrabold flex items-center gap-2">
      <Bell className="h-5 w-5 text-[#f5b120]" /> Pusat Notifikasi
      {alerts.length > 0 && (
        <span className="ml-auto text-xs font-bold rounded-full bg-red-100 text-red-700 px-2.5 py-0.5" data-testid="alert-count">{alerts.length}</span>
      )}
    </h3>
    {alerts.length === 0 ? (
      <div className="mt-4 flex items-center gap-2 text-sm text-slate-600" data-testid="alerts-empty">
        <CheckCircle2 className="h-4 w-4 text-emerald-500" /> Tidak ada peringatan. Semua berjalan normal.
      </div>
    ) : (
      <ul className="mt-4 space-y-2">
        {alerts.map((a, i) => (
          <li key={i}>
            <Link to={a.link} className="flex items-start gap-2.5 rounded-xl border border-red-100 bg-red-50/60 hover:border-red-300 px-3 py-2.5 transition-colors" data-testid={`alert-item-${i}`}>
              <span className="mt-1.5 h-2 w-2 rounded-full bg-red-500 shrink-0" />
              <span className="min-w-0 flex-1">
                <span className="block text-sm font-bold text-[#0a2350] truncate">{a.title}</span>
                <span className="block text-xs text-slate-600 truncate">{a.detail}</span>
              </span>
            </Link>
          </li>
        ))}
      </ul>
    )}
  </Card>
);

const QuickLinks = () => (
  <Card className="p-6 min-w-0">
    <h3 className="text-lg font-extrabold">Aksi Cepat</h3>
    <div className="mt-4 grid grid-cols-2 gap-3 text-sm">
      <QL to="/portal/admin/invoices" icon={Receipt} label="Buat Tagihan" testid="ql-invoices" />
      <QL to="/portal/admin/tickets" icon={LifeBuoy} label="Buka Tiket" testid="ql-tickets" />
      <QL to="/portal/admin/noc" icon={TrendingUp} label="Cek NOC" testid="ql-noc" />
      <QL to="/portal/admin/orders" icon={ShoppingCart} label="Orders" testid="ql-orders" />
      <QL to="/portal/admin/users" icon={Users} label="Manage Users" testid="ql-users" />
      <QL to="/portal/admin/products" icon={Package} label="Products" testid="ql-products" />
    </div>
  </Card>
);

const QL = ({ to, icon: Icon, label, testid }) => (
  <Link to={to} data-testid={testid} className="flex items-center gap-2 rounded-xl border border-slate-200 hover:border-[#f5b120] px-3 py-2.5 transition-colors">
    <Icon className="h-4 w-4 text-[#f5b120]" /> <span className="font-semibold text-[#0a2350]">{label}</span>
  </Link>
);

const RecentInvoices = ({ rows, show }) => (
  <Card className="p-6" data-testid="recent-invoices">
    <h3 className="text-lg font-extrabold">Tagihan Terbaru</h3>
    {!show ? (
      <p className="mt-4 text-sm text-slate-600">Data tagihan tidak tersedia untuk role Anda.</p>
    ) : rows.length === 0 ? (
      <p className="mt-4 text-sm text-slate-600" data-testid="recent-invoices-empty">Belum ada tagihan.</p>
    ) : (
      <ul className="mt-3 divide-y divide-slate-100">
        {rows.map((r) => (
          <li key={r.id} className="py-2.5 flex items-center gap-3 text-sm" data-testid={`recent-invoice-${r.number}`}>
            <Link to="/portal/admin/invoices" className="font-bold text-[#0a2350] hover:text-[#f5b120] transition-colors shrink-0">{r.number}</Link>
            <span className="text-slate-600 truncate">{r.user_name}</span>
            <span className="ml-auto font-semibold text-[#0a2350] shrink-0">{money(r.total)}</span>
            <StatusBadge status={r.status} />
          </li>
        ))}
      </ul>
    )}
  </Card>
);

const dotClass = { ok: "bg-emerald-500", warn: "bg-amber-500", off: "bg-slate-300" };

const Health = ({ items }) => (
  <Card className="p-6 min-w-0" data-testid="system-health">
    <h3 className="text-lg font-extrabold">System Health</h3>
    <ul className="mt-3 space-y-2 text-sm">
      {items.map((h, i) => (
        <li key={i} className="flex items-center gap-2 text-slate-600" data-testid={`health-${i}`}>
          <span className={`h-2 w-2 rounded-full ${dotClass[h.status] || "bg-slate-300"}`} />
          <span className="font-semibold text-[#0a2350]">{h.name}</span>
          <span className="ml-auto text-xs">{h.detail}</span>
        </li>
      ))}
    </ul>
    <p className="mt-3 text-[11px] text-slate-500">Kelola layanan eksternal di <Link to="/portal/admin/integrations" className="text-[#f5b120] font-bold">Integrations</Link>.</p>
  </Card>
);

export default AdminDashboard;

