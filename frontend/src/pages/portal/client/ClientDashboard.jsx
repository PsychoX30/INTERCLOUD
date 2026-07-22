import React, { useEffect, useState } from "react";
import { AlertTriangle, ArrowRight, Receipt, ServerCog, LifeBuoy, ShoppingCart } from "lucide-react";
import { Link } from "react-router-dom";
import { api, money } from "../../../portal/api";
import { PageHeader, StatCard, Card, Loading, btnPrimary, btnSecondary } from "../ui";

const ClientDashboard = () => {
  const [data, setData] = useState(null);
  useEffect(() => {
    api.get("/client/dashboard").then((r) => setData(r.data));
  }, []);

  if (!data) return <Loading />;
  const s = data.stats;

  return (
    <div>
      <PageHeader
        title="Welcome back"
        subtitle="Overview of your active services, invoices, and open tickets."
      />

      {s.overdue_invoices > 0 && (
        <div
          className="mb-6 rounded-2xl bg-red-50 border border-red-200 text-red-800 p-5 flex flex-col md:flex-row md:items-center gap-4"
          data-testid="overdue-banner"
        >
          <AlertTriangle className="h-6 w-6 flex-shrink-0" />
          <div className="flex-1">
            <div className="font-extrabold">
              You have {s.overdue_invoices} overdue invoice{s.overdue_invoices > 1 ? "s" : ""} — {money(s.overdue_total)}
            </div>
            <div className="text-sm mt-1 opacity-90">
              Please settle to avoid service interruption. Bank transfer + payment gateway options are available.
            </div>
          </div>
          <Link to="/portal/client/invoices" className={btnPrimary} data-testid="overdue-view-btn">
            View Invoices <ArrowRight className="h-4 w-4" />
          </Link>
        </div>
      )}

      <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard label="Active Services" value={s.active_services} testid="stat-active-services" tone="good" />
        <StatCard label="Unpaid Invoices" value={s.unpaid_invoices} tone={s.unpaid_invoices ? "warn" : "default"} testid="stat-unpaid" />
        <StatCard label="Overdue Invoices" value={s.overdue_invoices} tone={s.overdue_invoices ? "danger" : "default"} testid="stat-overdue" />
        <StatCard label="Open Tickets" value={s.open_tickets} testid="stat-tickets" />
      </div>

      <div className="mt-6 grid md:grid-cols-2 gap-4">
        <Card className="p-6">
          <h3 className="text-lg font-extrabold">Quick actions</h3>
          <p className="text-sm text-slate-500 mt-1">Jump to the most common client tasks.</p>
          <div className="mt-5 grid grid-cols-2 gap-3">
            <Link to="/portal/client/order" className={btnPrimary}><ShoppingCart className="h-4 w-4" /> Order</Link>
            <Link to="/portal/client/invoices" className={btnSecondary}><Receipt className="h-4 w-4" /> Pay Invoice</Link>
            <Link to="/portal/client/tickets" className={btnSecondary}><LifeBuoy className="h-4 w-4" /> Open Ticket</Link>
            <Link to="/portal/client/services" className={btnSecondary}><ServerCog className="h-4 w-4" /> My Services</Link>
          </div>
        </Card>
        <Card className="p-6">
          <h3 className="text-lg font-extrabold">Need help?</h3>
          <p className="text-sm text-slate-500 mt-1">
            Our engineers are on-call 24/7 for outages, hardware issues, and configuration guidance.
          </p>
          <div className="mt-4 text-sm space-y-1.5">
            <div><span className="text-slate-500">WhatsApp:</span> <span className="font-semibold">+62 878-1239-7187</span></div>
            <div><span className="text-slate-500">Email:</span> <span className="font-semibold">support@intercloud-digital.com</span></div>
            <div><span className="text-slate-500">SLA:</span> <span className="font-semibold">99.5% uptime</span></div>
          </div>
        </Card>
      </div>
    </div>
  );
};

export default ClientDashboard;
