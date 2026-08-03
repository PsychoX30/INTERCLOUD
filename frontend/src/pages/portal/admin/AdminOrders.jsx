import React, { useEffect, useState } from "react";
import { api, fullDateTime, money } from "../../../portal/api";
import { PageHeader, Loading, EmptyState, StatusBadge, btnPrimary, btnSecondary, Card } from "../ui";
import { CheckCircle2, XCircle, Eye, PlayCircle } from "lucide-react";
import { Link } from "react-router-dom";

const AdminOrders = () => {
  const [rows, setRows] = useState(null);
  const [active, setActive] = useState(null);
  const [verifying, setVerifying] = useState(null);
  const [provisioning, setProvisioning] = useState(null);
  const load = () => api.get("/admin/orders").then((r) => setRows(r.data));
  useEffect(() => { load(); }, []);
  if (!rows) return <Loading />;

  const verifyPayment = async (o) => {
    if (verifying) return; // anti double-click: 1 konfirmasi = 1 provisioning
    if (!o.invoice_id) { alert("No linked invoice for this order."); return; }
    if (!window.confirm(`Confirm payment received for order "${o.product_name}"? This will auto-provision the service.`)) return;
    setVerifying(o.id);
    try {
      await api.put(`/admin/invoices/${o.invoice_id}/status`, { status: "paid", payment_method: "bank_transfer" });
      await load();
    } finally { setVerifying(null); }
  };

  const runProvision = async (o) => {
    if (provisioning) return;
    if (!window.confirm(`Jalankan auto-provision untuk order "${o.product_name}"?`)) return;
    setProvisioning(o.id);
    try {
      const { data } = await api.post(`/admin/orders/${o.id}/provision`);
      alert(data.message || "Provisioning dijalankan.");
      await load();
    } catch (e) {
      alert(e?.response?.data?.detail || "Gagal menjalankan provisioning.");
    } finally { setProvisioning(null); }
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
                <button className={btnSecondary} onClick={() => setActive(o)} data-testid={`order-detail-btn-${o.id}`}>
                  <Eye className="h-4 w-4" /> Detail
                </button>
                {(o.status === "awaiting_verification" || o.status === "pending_payment") && o.invoice_id && (
                  <button className={btnPrimary} onClick={() => verifyPayment(o)} disabled={verifying === o.id} data-testid={`verify-payment-${o.id}`}>
                    <CheckCircle2 className="h-4 w-4" /> {verifying === o.id ? "Memproses…" : "Verify Payment & Provision"}
                  </button>
                )}
                {["payment_verified", "provisioning"].includes(o.status) && o.invoice_id && (
                  <button className={btnPrimary} onClick={() => runProvision(o)} disabled={provisioning === o.id} data-testid={`run-provision-${o.id}`}>
                    <PlayCircle className="h-4 w-4" /> {provisioning === o.id ? "Menjalankan…" : "Jalankan Auto-Provision"}
                  </button>
                )}
                {o.status === "awaiting_quote" && (
                  <button className={btnSecondary} onClick={() => setStatus(o.id, "rejected")}>Reject</button>
                )}
                {!["active", "rejected"].includes(o.status) && (
                  <button className="text-red-600 hover:text-red-800 text-xs font-bold" onClick={() => setStatus(o.id, "rejected")} data-testid={`reject-order-${o.id}`}>
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
      {active && <OrderDetail order={active} onClose={() => setActive(null)} />}
    </div>
  );
};

const OrderDetail = ({ order: o, onClose }) => {
  const [notes, setNotes] = useState(o.notes || "");
  const [saving, setSaving] = useState(false);
  const saveNotes = async () => {
    setSaving(true);
    try { await api.put(`/admin/orders/${o.id}`, { notes }); o.notes = notes; } finally { setSaving(false); }
  };
  return (
  <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4" onClick={onClose}>
    <div onClick={(e) => e.stopPropagation()} className="w-full max-w-2xl bg-white rounded-3xl shadow-2xl overflow-hidden max-h-[90vh] flex flex-col" data-testid="order-detail-modal">
      <div className="p-6 bg-[#0a2350] text-white flex items-start justify-between">
        <div>
          <div className="text-[10px] font-bold uppercase tracking-widest text-[#f5b120]">Detail Pesanan</div>
          <div className="text-xl font-extrabold">{o.product_name}</div>
          <div className="text-sm text-white/70 mt-0.5">{o.user_name} · {o.user_email}</div>
        </div>
        <button className="text-white/70 hover:text-white text-2xl leading-none" onClick={onClose} data-testid="order-detail-close">×</button>
      </div>
      <div className="p-6 overflow-y-auto space-y-4">
        <div className="grid grid-cols-3 gap-3 text-center">
          <div className="rounded-xl bg-slate-50 border border-slate-200 p-3">
            <div className="text-[10px] font-bold uppercase text-slate-500">Status</div>
            <div className="mt-1"><StatusBadge status={o.status} /></div>
          </div>
          <div className="rounded-xl bg-slate-50 border border-slate-200 p-3">
            <div className="text-[10px] font-bold uppercase text-slate-500">Dibuat</div>
            <div className="mt-1 text-xs font-semibold">{fullDateTime(o.created_at)}</div>
          </div>
          <div className="rounded-xl bg-slate-50 border border-slate-200 p-3">
            <div className="text-[10px] font-bold uppercase text-slate-500">Invoice</div>
            <div className="mt-1 text-xs font-semibold">
              {o.invoice_id
                ? <Link to={`/portal/admin/invoices/${o.invoice_id}`} className="text-[#f5b120] font-bold hover:underline" data-testid="order-detail-invoice-link">Lihat invoice</Link>
                : "-"}
            </div>
          </div>
        </div>
        {o.config && Object.keys(o.config).length > 0 && (
          <div className="rounded-2xl border border-slate-200 p-4" data-testid="order-detail-config">
            <div className="text-sm font-extrabold text-[#0a2350] mb-2">Konfigurasi</div>
            <div className="divide-y divide-slate-100 text-sm">
              {Object.entries(o.config).map(([k, v]) => (
                <div key={k} className="py-1.5 flex justify-between gap-3">
                  <span className="text-xs uppercase tracking-widest text-slate-500 font-semibold">{k.replaceAll("_", " ")}</span>
                  <span className="font-mono text-xs text-[#0a2350] text-right break-all">{typeof v === "object" ? JSON.stringify(v) : String(v)}</span>
                </div>
              ))}
            </div>
          </div>
        )}
        <div className="rounded-xl bg-slate-50 border border-slate-100 p-3" data-testid="order-edit-notes">
          <div className="text-[10px] font-bold uppercase text-slate-500 mb-1">Catatan pesanan (bisa diubah)</div>
          <textarea rows={2} value={notes} onChange={(e) => setNotes(e.target.value)}
            className="w-full rounded-lg border border-slate-200 p-2 text-sm focus:outline-none focus:ring-2 focus:ring-[#f5b120]" data-testid="order-notes-input" />
          <button onClick={saveNotes} disabled={saving || notes === (o.notes || "")}
            className="mt-1 text-xs font-bold text-[#0a2350] bg-[#f5b120]/30 hover:bg-[#f5b120]/60 rounded-full px-3 py-1 disabled:opacity-40" data-testid="order-notes-save">
            {saving ? "Menyimpan..." : "Simpan catatan"}
          </button>
        </div>
        <div className="rounded-2xl border border-slate-200 p-4" data-testid="order-detail-log">
          <div className="text-sm font-extrabold text-[#0a2350] mb-2">Provision log</div>
          {(o.provision_log || []).length === 0 ? <p className="text-xs text-slate-500">Belum ada log.</p> : (
            <div className="space-y-1.5 text-xs">
              {o.provision_log.map((l, i) => (
                <div key={i} className="flex gap-2 text-slate-600">
                  <span className="text-[10px] text-slate-400 font-mono w-28 flex-shrink-0">{new Date(l.at).toLocaleString("id-ID", { hour: "2-digit", minute: "2-digit", day: "2-digit", month: "short" })}</span>
                  <span className="font-mono text-[10px] text-[#f5b120] w-36 flex-shrink-0">{l.step}</span>
                  <span>{l.message}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  </div>
  );
};

export default AdminOrders;
