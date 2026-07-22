import React, { useEffect, useState } from "react";
import { api, fullDateTime } from "../../../portal/api";
import { PageHeader, Loading, EmptyState, StatusBadge, btnPrimary, btnSecondary, Card } from "../ui";
import { CheckCircle2, XCircle, Zap } from "lucide-react";

const AdminOrders = () => {
  const [rows, setRows] = useState(null);
  const load = () => api.get("/admin/orders").then((r) => setRows(r.data));
  useEffect(() => { load(); }, []);
  if (!rows) return <Loading />;

  const verifyPayment = async (o) => {
    if (!o.invoice_id) { alert("No linked invoice for this order."); return; }
    if (!window.confirm(`Confirm payment received for order "${o.product_name}"? This will auto-provision the service.`)) return;
    await api.put(`/admin/invoices/${o.invoice_id}/status`, { status: "paid", payment_method: "bank_transfer" });
    load();
  };

  const setStatus = async (id, status) => {
    await api.put(`/admin/orders/${id}/status`, { status });
    load();
  };

  return (
    <div>
      <PageHeader
        title="Orders"
        subtitle="Client orders flow: pending payment → awaiting verification → payment verified → auto provision → active. Confirming the linked invoice as paid triggers auto-provisioning."
      />
      {rows.length === 0 && <EmptyState title="No orders yet" />}
      <div className="grid gap-3">
        {rows.map((o) => (
          <Card key={o.id} className="p-4" data-testid={`admin-order-${o.id}`}>
            <div className="flex flex-col md:flex-row md:items-center gap-4">
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 flex-wrap">
                  <StatusBadge status={o.status} />
                  <span className="text-xs text-slate-500">{fullDateTime(o.created_at)}</span>
                  {o.invoice_id && <span className="text-[10px] uppercase tracking-widest font-bold text-[#f5b120]">has invoice</span>}
                  {o.service_id && <span className="text-[10px] uppercase tracking-widest font-bold text-emerald-600">service delivered</span>}
                </div>
                <div className="mt-1 text-base font-extrabold text-[#0a2350]">{o.product_name}</div>
                <div className="text-xs text-slate-500">{o.user_name} · {o.user_email}</div>
                {o.notes && <div className="mt-1 text-sm text-slate-600">Notes: {o.notes}</div>}
              </div>
              <div className="flex items-center gap-2 flex-wrap">
                {(o.status === "awaiting_verification" || o.status === "pending_payment") && o.invoice_id && (
                  <button className={btnPrimary} onClick={() => verifyPayment(o)} data-testid={`verify-payment-${o.id}`}>
                    <CheckCircle2 className="h-4 w-4" /> Verify Payment & Provision
                  </button>
                )}
                {o.status === "awaiting_quote" && (
                  <button className={btnSecondary} onClick={() => setStatus(o.id, "rejected")}>Reject</button>
                )}
                {!["active", "rejected"].includes(o.status) && (
                  <button className="text-red-600 hover:text-red-800 text-xs font-bold" onClick={() => setStatus(o.id, "rejected")}>
                    <XCircle className="h-3.5 w-3.5 inline" /> Reject
                  </button>
                )}
              </div>
            </div>
            {o.provision_log && o.provision_log.length > 0 && (
              <details className="mt-3">
                <summary className="text-xs font-bold text-slate-500 cursor-pointer">Provision log ({o.provision_log.length})</summary>
                <div className="mt-2 space-y-1 text-xs">
                  {o.provision_log.map((l, i) => (
                    <div key={i} className="flex gap-2 text-slate-600">
                      <span className="text-[10px] text-slate-400 font-mono w-32 flex-shrink-0">{new Date(l.at).toLocaleString("id-ID", { hour: "2-digit", minute: "2-digit", day: "2-digit", month: "short" })}</span>
                      <span className="font-mono text-[10px] text-[#f5b120] w-40 flex-shrink-0">{l.step}</span>
                      <span>{l.message}</span>
                    </div>
                  ))}
                </div>
              </details>
            )}
          </Card>
        ))}
      </div>
    </div>
  );
};

export default AdminOrders;
