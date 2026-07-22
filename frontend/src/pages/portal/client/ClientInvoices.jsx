import React, { useEffect, useState } from "react";
import { api, money, shortDate, fullDateTime, docUrl } from "../../../portal/api";
import { PageHeader, Card, Loading, StatusBadge, EmptyState, btnPrimary, btnSecondary } from "../ui";
import { Receipt, Wallet, CreditCard, Copy, AlertTriangle, FileDown, Download } from "lucide-react";

const ClientInvoices = () => {
  const [rows, setRows] = useState(null);
  const [active, setActive] = useState(null);

  useEffect(() => {
    api.get("/client/invoices").then((r) => setRows(r.data));
  }, []);

  if (!rows) return <Loading />;

  return (
    <div>
      <PageHeader title="Invoices" subtitle="Download, pay, and track every invoice tied to your account." />
      {rows.length === 0 && <EmptyState title="No invoices yet" />}
      <div className="rounded-2xl bg-white border border-slate-200 overflow-x-auto">
        <table className="w-full min-w-[720px] text-sm">
          <thead className="bg-slate-50 text-[11px] font-bold uppercase tracking-widest text-slate-500">
            <tr>
              <th className="px-4 py-3 text-left">Invoice</th>
              <th className="px-4 py-3 text-left hidden sm:table-cell">Issued</th>
              <th className="px-4 py-3 text-left">Due</th>
              <th className="px-4 py-3 text-right">Total</th>
              <th className="px-4 py-3 text-left">Status</th>
              <th className="px-4 py-3 text-right">Action</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((inv) => (
              <tr key={inv.id} className="border-t border-slate-100 hover:bg-slate-50/50" data-testid={`invoice-row-${inv.number}`}>
                <td className="px-4 py-3 font-mono text-[#0a2350] font-bold">{inv.number}</td>
                <td className="px-4 py-3 hidden sm:table-cell text-slate-600">{shortDate(inv.created_at)}</td>
                <td className="px-4 py-3 text-slate-600">{shortDate(inv.due_date)}</td>
                <td className="px-4 py-3 text-right font-extrabold text-[#0a2350]">{money(inv.total)}</td>
                <td className="px-4 py-3"><StatusBadge status={inv.status} /></td>
                <td className="px-4 py-3 text-right">
                  <a href={docUrl("invoice", inv.id)} target="_blank" rel="noreferrer" className="text-slate-600 hover:text-[#f5b120] mr-3" title="Preview" data-testid={`client-inv-pdf-${inv.number}`}>
                    <FileDown className="h-4 w-4 inline" />
                  </a>
                  <a href={docUrl("invoice", inv.id, "pdf")} target="_blank" rel="noreferrer" className="text-slate-600 hover:text-[#f5b120] mr-3" title="Download PDF" data-testid={`client-inv-download-${inv.number}`}>
                    <Download className="h-4 w-4 inline" />
                  </a>
                  <button
                    onClick={() => setActive(inv)}
                    data-testid={`invoice-view-${inv.number}`}
                    className="text-xs font-bold text-[#0a2350] hover:text-[#f5b120]"
                  >
                    View →
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {active && <InvoiceDetail invoice={active} onClose={() => setActive(null)} />}
    </div>
  );
};

const CopyText = ({ v }) => {
  const [c, setC] = useState(false);
  return (
    <button
      onClick={() => { navigator.clipboard.writeText(v); setC(true); setTimeout(() => setC(false), 1200); }}
      className="text-slate-400 hover:text-[#f5b120] inline-flex items-center gap-1"
    >
      <Copy className="h-3.5 w-3.5" />
      {c && <span className="text-[10px] text-emerald-600 font-bold">Copied</span>}
    </button>
  );
};

const InvoiceDetail = ({ invoice, onClose }) => {
  const [pay, setPay] = useState(invoice.status === "paid" ? null : "bank");
  const [banks, setBanks] = useState([]);
  const [duitkuOn, setDuitkuOn] = useState(false);

  useEffect(() => {
    api.get("/client/payment-info").then((r) => { setBanks(r.data.bank_accounts || []); setDuitkuOn(!!r.data.duitku_enabled); });
  }, []);

  const isOverdue = invoice.status === "overdue";
  const canPay = invoice.status === "unpaid" || invoice.status === "overdue";

  return (
    <div className="fixed inset-0 bg-black/50 z-50 flex items-end sm:items-center justify-center p-0 sm:p-6" onClick={onClose}>
      <div onClick={(e) => e.stopPropagation()} className="w-full max-w-3xl bg-white rounded-t-3xl sm:rounded-3xl shadow-2xl overflow-hidden max-h-[92vh] flex flex-col">
        <div className="p-6 bg-[#0a2350] text-white flex items-start justify-between">
          <div>
            <div className="text-[10px] font-bold uppercase tracking-widest text-[#f5b120]">Invoice</div>
            <div className="text-xl font-extrabold font-mono">{invoice.number}</div>
            <div className="text-sm text-white/70 mt-0.5">Issued {shortDate(invoice.created_at)} · Due {shortDate(invoice.due_date)}</div>
          </div>
          <button className="text-white/70 hover:text-white text-2xl leading-none" onClick={onClose}>×</button>
        </div>

        <div className="p-6 overflow-y-auto space-y-5">
          {isOverdue && (
            <div className="rounded-xl bg-red-50 border border-red-200 text-red-800 px-4 py-3 text-sm flex items-center gap-2">
              <AlertTriangle className="h-4 w-4" /> This invoice is overdue. Please settle to avoid service interruption.
            </div>
          )}

          <Card className="p-5">
            <div className="flex items-center justify-between mb-3">
              <div className="font-extrabold text-[#0a2350]">Line items</div>
              <StatusBadge status={invoice.status} />
            </div>
            <table className="w-full min-w-[720px] text-sm">
              <thead className="text-[11px] uppercase tracking-widest text-slate-500 border-b border-slate-100">
                <tr><th className="text-left py-2">Description</th><th className="text-right">Qty</th><th className="text-right">Unit</th><th className="text-right">Total</th></tr>
              </thead>
              <tbody>
                {invoice.items.map((it, i) => (
                  <tr key={i} className="border-b border-slate-100 last:border-0">
                    <td className="py-3">{it.description}</td>
                    <td className="text-right">{it.qty}</td>
                    <td className="text-right">{money(it.unit_price)}</td>
                    <td className="text-right font-bold">{money(it.total)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="mt-3 space-y-1 text-sm text-right">
              <div className="text-slate-500">Subtotal: <span className="font-semibold text-[#0a2350]">{money(invoice.subtotal)}</span></div>
              <div className="text-slate-500">Tax: <span className="font-semibold text-[#0a2350]">{money(invoice.tax_amount)}</span></div>
              <div className="text-lg font-extrabold text-[#0a2350]">Total: {money(invoice.total)}</div>
            </div>
          </Card>

          {canPay && (
            <Card className="p-5">
              <div className="font-extrabold text-[#0a2350] mb-3">Choose payment method</div>
              <div className="grid sm:grid-cols-2 gap-3">
                <button
                  onClick={() => setPay("bank")}
                  data-testid="pay-bank"
                  className={`text-left rounded-xl border-2 p-4 transition-colors ${pay === "bank" ? "border-[#f5b120] bg-[#f5b120]/5" : "border-slate-200 hover:border-slate-300"}`}
                >
                  <div className="flex items-center gap-2"><Wallet className="h-4 w-4 text-[#0a2350]" /> <span className="font-bold text-[#0a2350]">Bank Transfer</span></div>
                  <p className="text-xs text-slate-500 mt-1">Transfer to MANDIRI or BCA. Confirm via WhatsApp after payment.</p>
                </button>
                <button
                  onClick={() => setPay("duitku")}
                  data-testid="pay-duitku"
                  className={`text-left rounded-xl border-2 p-4 transition-colors ${pay === "duitku" ? "border-[#f5b120] bg-[#f5b120]/5" : "border-slate-200 hover:border-slate-300"}`}
                >
                  <div className="flex items-center gap-2"><CreditCard className="h-4 w-4 text-[#0a2350]" /> <span className="font-bold text-[#0a2350]">Duitku Gateway</span></div>
                  <p className="text-xs text-slate-500 mt-1">VA, e-wallet, QRIS, retail outlet — instant settlement.{duitkuOn ? "" : " (Not enabled yet)"}</p>
                </button>
              </div>

              {pay === "bank" && (
                <div className="mt-4 rounded-xl bg-slate-50 border border-slate-200 p-4 space-y-3" data-testid="bank-details">
                  <div className="text-xs text-slate-500">Transfer the exact total <span className="font-bold text-[#0a2350]">{money(invoice.total)}</span> to one of the accounts below. Include the invoice number <span className="font-mono">{invoice.number}</span> in the transfer memo.</div>
                  {banks.map((b, i) => (
                    <div key={i} className="rounded-lg bg-white border border-slate-200 p-3">
                      <div className="text-xs uppercase font-bold tracking-widest text-[#f5b120]">{b.bank}</div>
                      <div className="flex items-center gap-2 mt-1">
                        <div className="text-lg font-mono font-extrabold text-[#0a2350]">{b.number}</div>
                        <CopyText v={b.number} />
                      </div>
                      <div className="text-xs text-slate-500 mt-1">A/N {b.holder}</div>
                    </div>
                  ))}
                  <a
                    href={`https://wa.me/6287812397187?text=${encodeURIComponent(`Halo, saya sudah transfer untuk invoice ${invoice.number} sebesar Rp ${invoice.total.toLocaleString('id-ID')}. Mohon konfirmasi.`)}`}
                    target="_blank" rel="noreferrer"
                    className={btnPrimary}
                    data-testid="wa-confirm-payment"
                  >
                    I've paid — confirm via WhatsApp
                  </a>
                </div>
              )}

              {pay === "duitku" && (
                <div className="mt-4 rounded-xl bg-slate-50 border border-slate-200 p-4">
                  <p className="text-sm text-slate-600">
                    You'll be redirected to Duitku's secure payment page to complete this transaction.
                  </p>
                  <button
                    disabled={!duitkuOn}
                    className={`${btnPrimary} mt-3 ${!duitkuOn ? "opacity-50 cursor-not-allowed" : ""}`}
                    data-testid="pay-duitku-cta"
                    onClick={() => alert("Duitku redirect — mocked (integration pending).")}
                  >
                    Pay with Duitku {duitkuOn ? "" : "(disabled)"}
                  </button>
                </div>
              )}
            </Card>
          )}

          {invoice.status === "paid" && (
            <div className="rounded-xl bg-emerald-50 border border-emerald-200 text-emerald-800 px-4 py-3 text-sm">
              Paid on {fullDateTime(invoice.paid_at)} via {invoice.payment_method}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default ClientInvoices;
