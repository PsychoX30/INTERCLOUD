import React, { useEffect, useState, useCallback } from "react";
import { api, getToken } from "../../../portal/api";
import { PageHeader, Card, Loading, EmptyState, btnPrimary, btnSecondary, btnDanger, inputClass, labelClass } from "../ui";
import { Plus, ReceiptText, Loader2, CheckCircle2, XCircle, FileText, Download, Search, RefreshCw } from "lucide-react";

const idr = (v) => "Rp " + Number(v || 0).toLocaleString("id-ID", { maximumFractionDigits: 0 });
const BASE = process.env.REACT_APP_BACKEND_URL;

const STATUS_CHIPS = {
  draft:     "bg-slate-200 text-slate-700 border-slate-300",
  applied:   "bg-emerald-100 text-emerald-700 border-emerald-300",
  cancelled: "bg-red-100 text-red-700 border-red-300",
};

const AdminCreditNotes = () => {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [invoices, setInvoices] = useState([]);
  const [showCreate, setShowCreate] = useState(false);
  const [q, setQ] = useState("");
  const [statusFilter, setStatusFilter] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = statusFilter ? `?status=${statusFilter}` : "";
      const [r, i] = await Promise.all([
        api.get(`/admin/credit-notes${params}`),
        api.get("/admin/invoices"),
      ]);
      setRows(r.data || []);
      setInvoices(i.data || []);
    } finally { setLoading(false); }
  }, [statusFilter]);

  useEffect(() => { load(); }, [load]);

  const apply = async (id) => {
    if (!window.confirm("Apply this credit note? If the credit meets or exceeds the invoice total, the invoice will be marked paid and any suspended services will be reactivated.")) return;
    await api.post(`/admin/credit-notes/${id}/apply`);
    await load();
  };
  const cancel = async (id) => {
    if (!window.confirm("Cancel this credit note? This cannot be undone.")) return;
    await api.post(`/admin/credit-notes/${id}/cancel`);
    await load();
  };

  const filtered = rows.filter((r) => {
    if (!q) return true;
    const needle = q.toLowerCase();
    return (r.number || "").toLowerCase().includes(needle)
        || (r.invoice_number || "").toLowerCase().includes(needle)
        || (r.user_email || "").toLowerCase().includes(needle)
        || (r.reason || "").toLowerCase().includes(needle);
  });

  const pdfUrl = (id) => `${BASE}/api/portal/documents/credit-note/${id}?format=pdf&token=${encodeURIComponent(getToken() || "")}`;

  return (
    <div data-testid="credit-notes-page">
      <PageHeader
        title="Credit Notes"
        subtitle="Refunds and adjustments applied against unpaid invoices. When applied credits meet or exceed an invoice's total, the invoice is auto-marked paid and suspended services reactivate — same behavior as a payment webhook."
        actions={
          <div className="flex items-center gap-2">
            <button className={btnSecondary} onClick={load} data-testid="cn-refresh"><RefreshCw className="h-4 w-4" /> Refresh</button>
            <button className={btnPrimary} onClick={() => setShowCreate(true)} data-testid="cn-new"><Plus className="h-4 w-4" /> New credit note</button>
          </div>
        }
      />

      <Card className="p-4 mb-4">
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          <div>
            <label className={labelClass}>Search</label>
            <div className="relative">
              <Search className="h-4 w-4 absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-400" />
              <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="CN number, invoice, email, reason" className={inputClass + " pl-8"} data-testid="cn-search" />
            </div>
          </div>
          <div>
            <label className={labelClass}>Status</label>
            <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)} className={inputClass} data-testid="cn-status-filter">
              <option value="">All</option>
              <option value="draft">Draft</option>
              <option value="applied">Applied</option>
              <option value="cancelled">Cancelled</option>
            </select>
          </div>
        </div>
      </Card>

      <Card className="overflow-hidden">
        {loading ? <Loading /> : filtered.length === 0 ? (
          <EmptyState title="No credit notes yet"
                      body="Issue a credit note against any invoice to record a refund or adjustment. It will show up here and, if applied, will reduce the invoice's outstanding amount." />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm" data-testid="cn-table">
              <thead className="bg-slate-50 text-[11px] uppercase tracking-widest text-slate-500">
                <tr>
                  <th className="text-left px-4 py-3">Number</th>
                  <th className="text-left px-4 py-3">Client</th>
                  <th className="text-left px-4 py-3">Invoice</th>
                  <th className="text-right px-4 py-3">Amount</th>
                  <th className="text-left px-4 py-3">Reason</th>
                  <th className="text-left px-4 py-3">Status</th>
                  <th className="text-left px-4 py-3">Created</th>
                  <th className="text-right px-4 py-3">Actions</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((r) => (
                  <tr key={r.id} className="border-t border-slate-100 hover:bg-slate-50/60" data-testid={`cn-row-${r.id}`}>
                    <td className="px-4 py-3 font-mono text-sm font-semibold text-[#0a2350]">{r.number}</td>
                    <td className="px-4 py-3">
                      <div className="font-semibold text-[#0a2350]">{r.user_name}</div>
                      <div className="text-xs text-slate-500">{r.user_email}</div>
                    </td>
                    <td className="px-4 py-3 font-mono text-xs">{r.invoice_number || "—"}</td>
                    <td className="px-4 py-3 text-right font-bold">{idr(r.amount)}</td>
                    <td className="px-4 py-3 max-w-[240px] truncate" title={r.reason}>{r.reason}</td>
                    <td className="px-4 py-3">
                      <span className={`inline-block px-2 py-0.5 rounded-full border text-[10px] font-bold uppercase tracking-widest ${STATUS_CHIPS[r.status] || STATUS_CHIPS.draft}`}>{r.status}</span>
                    </td>
                    <td className="px-4 py-3 text-xs text-slate-500 whitespace-nowrap">{(r.created_at || "").slice(0, 10)}</td>
                    <td className="px-4 py-3 text-right whitespace-nowrap">
                      <div className="flex items-center justify-end gap-1">
                        <a href={pdfUrl(r.id)} target="_blank" rel="noreferrer" className="p-1.5 rounded hover:bg-slate-100 text-slate-600" title="Download PDF" data-testid={`cn-pdf-${r.id}`}>
                          <Download className="h-4 w-4" />
                        </a>
                        {r.status === "draft" && (
                          <>
                            <button onClick={() => apply(r.id)} className="px-2 py-1 rounded bg-emerald-600 hover:bg-emerald-700 text-white text-xs font-semibold" data-testid={`cn-apply-${r.id}`}>
                              Apply
                            </button>
                            <button onClick={() => cancel(r.id)} className="px-2 py-1 rounded bg-red-600 hover:bg-red-700 text-white text-xs font-semibold" data-testid={`cn-cancel-${r.id}`}>
                              Cancel
                            </button>
                          </>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {showCreate && (
        <CreateModal
          invoices={invoices}
          onClose={() => setShowCreate(false)}
          onSaved={() => { setShowCreate(false); load(); }}
        />
      )}
    </div>
  );
};

const CreateModal = ({ invoices, onClose, onSaved }) => {
  const [invoiceId, setInvoiceId] = useState("");
  const [amount, setAmount] = useState("");
  const [reason, setReason] = useState("");
  const [notes, setNotes] = useState("");
  const [autoApply, setAutoApply] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const selectedInv = invoices.find((i) => i.id === invoiceId);
  // Show only invoices that still have a balance (unpaid/overdue)
  const eligible = invoices.filter((i) => ["unpaid", "overdue"].includes((i.status || "").toLowerCase()));

  const submit = async () => {
    setError("");
    if (!invoiceId || !amount || !reason.trim()) {
      setError("Invoice, amount, and reason are all required.");
      return;
    }
    setSaving(true);
    try {
      await api.post("/admin/credit-notes", {
        invoice_id: invoiceId,
        amount: Number(amount),
        reason: reason.trim(),
        notes,
        auto_apply: autoApply,
      });
      onSaved();
    } catch (e) {
      setError(e.response?.data?.detail || "Failed to save credit note");
    } finally { setSaving(false); }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={onClose} data-testid="cn-create-modal">
      <div className="bg-white rounded-2xl max-w-lg w-full max-h-[90vh] overflow-y-auto shadow-2xl" onClick={(e) => e.stopPropagation()}>
        <div className="p-5 border-b border-slate-200 flex items-start justify-between">
          <div>
            <div className="text-xs uppercase tracking-widest text-slate-500">New credit note</div>
            <div className="text-lg font-extrabold text-[#0a2350]">Issue refund / adjustment</div>
          </div>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-700 text-xl" data-testid="cn-modal-close">×</button>
        </div>
        <div className="p-5 space-y-3 text-sm">
          <div>
            <label className={labelClass}>Invoice (unpaid or overdue)*</label>
            <select value={invoiceId} onChange={(e) => setInvoiceId(e.target.value)} className={inputClass} data-testid="cn-modal-invoice">
              <option value="">— Select invoice —</option>
              {eligible.map((i) => {
                const label = `${i.number} · ${i.user_email} · ${idr(i.total)} · ${i.status}`;
                return <option key={i.id} value={i.id}>{label}</option>;
              })}
            </select>
            {eligible.length === 0 && (
              <div className="text-xs text-amber-700 mt-1">No unpaid/overdue invoices available.</div>
            )}
          </div>
          {selectedInv && (
            <div className="bg-slate-50 border border-slate-200 rounded-lg p-3 text-xs text-slate-600">
              <div>Invoice total: <b>{idr(selectedInv.total)}</b></div>
              <div>Status: <b>{selectedInv.status}</b></div>
            </div>
          )}
          <div>
            <label className={labelClass}>Amount (IDR)*</label>
            <input type="number" min="0" value={amount} onChange={(e) => setAmount(e.target.value)}
                   placeholder="0" className={inputClass} data-testid="cn-modal-amount" />
          </div>
          <div>
            <label className={labelClass}>Reason*</label>
            <input value={reason} onChange={(e) => setReason(e.target.value)}
                   placeholder="e.g. Refund for SLA breach, promo adjustment" className={inputClass} data-testid="cn-modal-reason" />
          </div>
          <div>
            <label className={labelClass}>Notes</label>
            <textarea value={notes} onChange={(e) => setNotes(e.target.value)} rows={3}
                      placeholder="Internal notes (visible on the PDF)" className={inputClass + " h-auto py-2"} data-testid="cn-modal-notes" />
          </div>
          <label className="flex items-center gap-2 text-sm cursor-pointer" data-testid="cn-modal-autoapply-label">
            <input type="checkbox" checked={autoApply} onChange={(e) => setAutoApply(e.target.checked)} data-testid="cn-modal-autoapply" />
            Apply immediately (deducts from invoice outstanding; may auto-settle it if credit ≥ total)
          </label>
          {error && <div className="text-sm text-red-700 bg-red-50 border border-red-200 p-2 rounded">{error}</div>}
        </div>
        <div className="p-5 border-t border-slate-200 flex justify-end gap-2">
          <button onClick={onClose} className={btnSecondary} data-testid="cn-modal-cancel">Cancel</button>
          <button onClick={submit} disabled={saving} className={btnPrimary} data-testid="cn-modal-save">
            {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <ReceiptText className="h-4 w-4" />}
            {saving ? "Saving…" : "Create credit note"}
          </button>
        </div>
      </div>
    </div>
  );
};

export default AdminCreditNotes;
