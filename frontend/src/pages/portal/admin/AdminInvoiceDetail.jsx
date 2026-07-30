import React, { useEffect, useState } from "react";
import { useParams, Link, useNavigate } from "react-router-dom";
import { api, money, shortDate, docUrl } from "../../../portal/api";
import { StatusBadge, btnPrimary, btnSecondary } from "../ui";
import { ArrowLeft, FileDown, Download, CheckCircle2, Trash2, ReceiptText, Copy, Send } from "lucide-react";
import { toast } from "sonner";

const CreditDeduction = ({ inv, credits, onChanged }) => {
  const applied = credits.filter((c) => c.status === "applied").reduce((a, b) => a + b.amount, 0);
  const remaining = Math.max(0, inv.total - applied);
  if (!credits.length) return null;

  const apply = async (cn) => {
    if (!window.confirm(`Terapkan ${cn.number} (${money(cn.amount)}) untuk memotong invoice ini?`)) return;
    try {
      await api.post(`/admin/credit-notes/${cn.id}/apply`);
      toast.success(`${cn.number} diterapkan`);
      onChanged();
    } catch (e) { toast.error(e?.response?.data?.detail || "Gagal menerapkan credit note"); }
  };

  return (
    <div className="border-t border-slate-100 px-4 py-4" data-testid="invoice-credit-deduction">
      <div className="text-xs uppercase tracking-wide text-slate-400 font-bold mb-2">Potongan credit note</div>
      <div className="space-y-2">
        {credits.map((cn) => (
          <div key={cn.id} className="flex items-center justify-between gap-3 text-sm" data-testid={`invoice-cn-${cn.number}`}>
            <div className="min-w-0">
              <span className="font-mono font-bold text-[#0a2350]">{cn.number}</span>
              <span className="ml-2 text-slate-500 text-xs">{cn.reason}</span>
            </div>
            <div className="flex items-center gap-3 whitespace-nowrap">
              <span className="font-semibold text-[#0a2350]">-{money(cn.amount)}</span>
              {cn.status === "applied" && <span className="text-[10px] font-bold uppercase text-emerald-700 bg-emerald-50 border border-emerald-200 rounded-full px-2 py-0.5">applied</span>}
              {cn.status === "cancelled" && <span className="text-[10px] font-bold uppercase text-slate-500 bg-slate-100 rounded-full px-2 py-0.5">cancelled</span>}
              {cn.status === "draft" && (inv.status === "unpaid" || inv.status === "overdue") && (
                <button onClick={() => apply(cn)} className="text-[11px] font-bold text-white bg-emerald-600 hover:bg-emerald-700 rounded-full px-2.5 py-1" data-testid={`invoice-cn-apply-${cn.number}`}>
                  Terapkan
                </button>
              )}
              {cn.status === "draft" && !(inv.status === "unpaid" || inv.status === "overdue") && (
                <span className="text-[10px] font-bold uppercase text-amber-700 bg-amber-50 border border-amber-200 rounded-full px-2 py-0.5">draft</span>
              )}
            </div>
          </div>
        ))}
      </div>
      {applied > 0 && (
        <div className="mt-3 pt-3 border-t border-dashed border-slate-200 text-right text-sm space-y-1">
          <div className="text-slate-500">Kredit diterapkan: <span className="font-semibold text-emerald-700">-{money(applied)}</span></div>
          <div className="font-extrabold text-[#0a2350]" data-testid="invoice-remaining-balance">Sisa tagihan: {money(inv.status === "paid" ? 0 : remaining)}</div>
        </div>
      )}
    </div>
  );
};

export default function AdminInvoiceDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [inv, setInv] = useState(null);
  const [credits, setCredits] = useState([]);
  const [sending, setSending] = useState(false);
  const [err, setErr] = useState("");

  const sendToClient = async () => {
    setSending(true);
    try {
      const r = await api.post(`/admin/invoices/${id}/send`);
      if (r.data.email_sent) toast.success(`Invoice terkirim via email ke ${r.data.email}`);
      else toast.warning("Email gagal terkirim (cek konfigurasi SMTP)");
      if (r.data.wa_link) window.open(r.data.wa_link, "_blank");
    } catch (e) { toast.error(e?.response?.data?.detail || "Gagal mengirim invoice"); }
    finally { setSending(false); }
  };

  const load = () => {
    api.get(`/admin/invoices/${id}`)
      .then((r) => setInv(r.data))
      .catch((e) => setErr(e?.response?.data?.detail || "Invoice tidak ditemukan"));
    api.get(`/admin/credit-notes`, { params: { invoice_id: id } })
      .then((r) => setCredits(r.data)).catch(() => {});
  };
  useEffect(() => { load(); }, [id]); // eslint-disable-line react-hooks/exhaustive-deps

  const markPaid = async () => {
    await api.put(`/admin/invoices/${id}/status`, { status: "paid", payment_method: "bank_transfer" });
    toast.success("Invoice ditandai lunas"); load();
  };
  const cancel = async () => {
    if (!window.confirm("Batalkan invoice ini?")) return;
    await api.put(`/admin/invoices/${id}/status`, { status: "cancelled" });
    toast.success("Invoice dibatalkan"); load();
  };
  const copyLink = () => {
    navigator.clipboard.writeText(window.location.href);
    toast.success("Tautan invoice disalin");
  };

  if (err) {
    return (
      <div className="text-center py-20" data-testid="invoice-detail-error">
        <p className="text-lg font-bold text-[#0a2350]">{err}</p>
        <button className={`${btnSecondary} mt-4`} onClick={() => navigate("/portal/admin/invoices")}>
          <ArrowLeft className="h-4 w-4" /> Kembali ke daftar invoice
        </button>
      </div>
    );
  }
  if (!inv) return <div className="py-20 text-center text-slate-400" data-testid="invoice-detail-loading">Memuat invoice...</div>;

  const open = inv.status === "unpaid" || inv.status === "overdue";

  return (
    <div data-testid="invoice-detail-page">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <Link to="/portal/admin/invoices" className="inline-flex items-center gap-1 text-sm text-slate-500 hover:text-[#0a2350]" data-testid="invoice-detail-back">
            <ArrowLeft className="h-4 w-4" /> Invoices
          </Link>
          <div className="mt-1 flex items-center gap-3">
            <h1 className="text-2xl sm:text-3xl font-extrabold text-[#0a2350] font-mono" data-testid="invoice-detail-number">{inv.number}</h1>
            <StatusBadge status={inv.status} />
          </div>
          <p className="text-sm text-slate-500 mt-1">Diterbitkan {shortDate(inv.created_at)} · Jatuh tempo {shortDate(inv.due_date)}</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button className={btnSecondary} onClick={copyLink} data-testid="invoice-detail-copy-link"><Copy className="h-4 w-4" /> Salin tautan</button>
          <a href={docUrl("invoice", inv.id)} target="_blank" rel="noreferrer" className={btnSecondary} data-testid="invoice-detail-preview"><FileDown className="h-4 w-4" /> Preview</a>
          <a href={docUrl("invoice", inv.id, "pdf")} target="_blank" rel="noreferrer" className={btnSecondary} data-testid="invoice-detail-pdf"><Download className="h-4 w-4" /> PDF</a>
          {open && <button className={btnPrimary} onClick={markPaid} data-testid="invoice-detail-mark-paid"><CheckCircle2 className="h-4 w-4" /> Tandai Lunas</button>}
        </div>
      </div>

      <div className="mt-6 grid grid-cols-1 lg:grid-cols-3 gap-4">
        <div className="lg:col-span-2 bg-white rounded-2xl border border-slate-100 shadow-sm overflow-hidden">
          <table className="w-full text-sm" data-testid="invoice-detail-items">
            <thead>
              <tr className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
                <th className="px-4 py-3">Deskripsi</th>
                <th className="px-4 py-3 text-right">Qty</th>
                <th className="px-4 py-3 text-right">Harga satuan</th>
                <th className="px-4 py-3 text-right">Total</th>
              </tr>
            </thead>
            <tbody>
              {inv.items.map((it, i) => (
                <tr key={i} className="border-t border-slate-100">
                  <td className="px-4 py-3 font-medium text-[#0a2350]">{it.description}</td>
                  <td className="px-4 py-3 text-right text-slate-600">{it.qty}</td>
                  <td className="px-4 py-3 text-right text-slate-600">{money(it.unit_price)}</td>
                  <td className="px-4 py-3 text-right font-semibold text-[#0a2350]">{money(it.total)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="border-t border-slate-100 px-4 py-4 text-right space-y-1 text-sm">
            <div className="text-slate-500">Subtotal: <span className="font-semibold text-[#0a2350]">{money(inv.subtotal)}</span></div>
            <div className="text-slate-500">Pajak{inv.tax_percent != null ? ` (${inv.tax_percent}%)` : ""}: <span className="font-semibold text-[#0a2350]">{money(inv.tax_amount)}</span></div>
            <div className="text-xl font-extrabold text-[#0a2350]" data-testid="invoice-detail-total">Total: {money(inv.total)}</div>
          </div>
          <CreditDeduction inv={inv} credits={credits} onChanged={load} />
          <div className="mt-3 flex justify-end gap-2">
            <a href={docUrl("invoice", inv.id)} target="_blank" rel="noreferrer" className={btnSecondary}><FileDown className="h-4 w-4" /> Lihat invoice</a>
            <button className={btnPrimary} onClick={sendToClient} disabled={sending} data-testid="invoice-detail-send">
              <Send className="h-4 w-4" /> {sending ? "Mengirim..." : "Kirim ke Klien"}
            </button>
          </div>
        </div>

        <div className="space-y-4">
          <div className="bg-white rounded-2xl border border-slate-100 shadow-sm p-5" data-testid="invoice-detail-client">
            <div className="text-xs uppercase tracking-wide text-slate-400 font-bold">Klien</div>
            <div className="mt-2 font-bold text-[#0a2350]">{inv.user_name}</div>
            <div className="text-sm text-slate-500">{inv.user_email}</div>
            <Link to={`/portal/admin/users?focus=${inv.user_id}`} className="mt-2 inline-block text-xs font-bold text-[#f5b120] hover:underline">Lihat profil klien</Link>
          </div>

          <div className="bg-white rounded-2xl border border-slate-100 shadow-sm p-5 text-sm space-y-2" data-testid="invoice-detail-payment">
            <div className="text-xs uppercase tracking-wide text-slate-400 font-bold">Pembayaran</div>
            <div className="flex justify-between"><span className="text-slate-500">Metode</span><span className="font-semibold text-[#0a2350]">{inv.payment_method || "-"}</span></div>
            <div className="flex justify-between"><span className="text-slate-500">Dibayar pada</span><span className="font-semibold text-[#0a2350]">{inv.paid_at ? shortDate(inv.paid_at) : "-"}</span></div>
            {inv.payment_ref && <div className="flex justify-between"><span className="text-slate-500">Ref</span><span className="font-mono text-xs text-[#0a2350]">{inv.payment_ref}</span></div>}
            {inv.source_quotation_number && (
              <div className="flex justify-between">
                <span className="text-slate-500">Dari quotation</span>
                <Link to="/portal/admin/quotations" className="font-mono text-xs font-bold text-[#f5b120] hover:underline" data-testid="invoice-detail-source-qtn">{inv.source_quotation_number}</Link>
              </div>
            )}
            {inv.notes && <div className="pt-2 border-t border-slate-100 text-slate-500 text-xs">{inv.notes}</div>}
          </div>

          {open && (
            <div className="bg-white rounded-2xl border border-slate-100 shadow-sm p-5 space-y-2">
              <div className="text-xs uppercase tracking-wide text-slate-400 font-bold">Aksi lain</div>
              <Link to={`/portal/admin/credit-notes?invoice=${inv.id}`} className="flex items-center gap-2 text-sm text-indigo-600 hover:text-indigo-800 font-semibold" data-testid="invoice-detail-credit-note">
                <ReceiptText className="h-4 w-4" /> Terbitkan credit note / refund
              </Link>
              <button onClick={cancel} className="flex items-center gap-2 text-sm text-red-600 hover:text-red-800 font-semibold" data-testid="invoice-detail-cancel">
                <Trash2 className="h-4 w-4" /> Batalkan invoice
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
