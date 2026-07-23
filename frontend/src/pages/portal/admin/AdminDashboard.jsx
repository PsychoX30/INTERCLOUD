import React, { useEffect, useState } from "react";
import { api, money } from "../../../portal/api";
import { PageHeader, Card, Loading, StatCard } from "../ui";
import { Users, Package, ShoppingCart, Receipt, Wallet, LifeBuoy, TrendingUp, AlertTriangle } from "lucide-react";
import { Link } from "react-router-dom";

const AdminDashboard = () => {
  const [d, setD] = useState(null);
  useEffect(() => { api.get("/admin/dashboard").then((r) => setD(r.data)); }, []);
  if (!d) return <Loading />;
  const s = d.stats;
  return (
    <div>
      <PageHeader title="Admin Dashboard" subtitle="Real-time snapshot of the business." />
      <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard label="Total Clients" value={s.total_clients} testid="stat-clients" />
        <StatCard label="Active Services" value={s.active_services} tone="good" testid="stat-services" />
        <StatCard label="Pending Orders" value={s.pending_orders} tone={s.pending_orders ? "warn" : "default"} testid="stat-orders" />
        <StatCard label="Open Tickets" value={s.open_tickets} testid="stat-tickets" />
        <StatCard label="Revenue (Month)" value={money(s.revenue_month)} tone="good" testid="stat-rev-month" />
        <StatCard label="Revenue (Total)" value={money(s.revenue_total)} testid="stat-rev-total" />
        <StatCard label="Unpaid Invoices" value={s.unpaid_invoices} tone={s.unpaid_invoices ? "warn" : "default"} testid="stat-unpaid" />
        <StatCard label="Overdue Total" value={money(s.overdue_total)} hint={`${s.overdue_invoices || 0} invoice(s)`} tone={s.overdue_total ? "danger" : "default"} testid="stat-overdue" />
      </div>
      <div className="mt-6 grid md:grid-cols-2 gap-4">
        <QuickLinks />
        <Health />
      </div>
    </div>
  );
};

const QuickLinks = () => (
  <Card className="p-6">
    <h3 className="text-lg font-extrabold">Quick actions</h3>
    <div className="mt-4 grid grid-cols-2 gap-3 text-sm">
      <QL to="/portal/admin/users" icon={Users} label="Manage Users" />
      <QL to="/portal/admin/products" icon={Package} label="Products" />
      <QL to="/portal/admin/orders" icon={ShoppingCart} label="Orders" />
      <QL to="/portal/admin/invoices" icon={Receipt} label="Invoices" />
      <QL to="/portal/admin/tickets" icon={LifeBuoy} label="Tickets" />
      <QL to="/portal/admin/finance" icon={TrendingUp} label="Finance" />
    </div>
  </Card>
);

const QL = ({ to, icon: Icon, label }) => (
  <Link to={to} className="flex items-center gap-2 rounded-xl border border-slate-200 hover:border-[#f5b120] px-3 py-2.5 transition-colors">
    <Icon className="h-4 w-4 text-[#f5b120]" /> <span className="font-semibold text-[#0a2350]">{label}</span>
  </Link>
);

const Health = () => (
  <Card className="p-6">
    <h3 className="text-lg font-extrabold">System health</h3>
    <ul className="mt-3 space-y-2 text-sm">
      {[
        ["API Backend", "green", "Online"],
        ["MongoDB", "green", "Connected"],
        ["cPanel Integration", "gray", "Not configured"],
        ["Proxmox Integration", "gray", "Not configured"],
        ["MikroTik Ops", "gray", "Not configured"],
        ["Payment Gateways", "gray", "Not configured"],
        ["SMTP", "gray", "Not configured"],
      ].map(([name, tone, status]) => (
        <li key={name} className="flex items-center gap-2 text-slate-600">
          <span className={`h-2 w-2 rounded-full ${tone === "green" ? "bg-emerald-500" : "bg-slate-300"}`} />
          <span className="font-semibold text-[#0a2350]">{name}</span>
          <span className="ml-auto text-xs">{status}</span>
        </li>
      ))}
    </ul>
    <p className="mt-3 text-[11px] text-slate-500">Configure external services under <Link to="/portal/admin/integrations" className="text-[#f5b120] font-bold">Integrations</Link>.</p>
  </Card>
);

export default AdminDashboard;
