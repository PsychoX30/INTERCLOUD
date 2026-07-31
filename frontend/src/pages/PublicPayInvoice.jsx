import React, { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import axios from "axios";
import { Wallet, CreditCard, Copy, CheckCircle2, AlertTriangle, ShieldCheck, Loader2 } from "lucide-react";

const API = `${process.env.REACT_APP_BACKEND_URL}/api/portal`;

const money = (v) => `Rp ${Number(v || 0).toLocaleString("id-ID")}`;
const shortDate = (d) => {
  if (!d) return "-";
  try { return new Date(d).toLocaleDateString("id-ID", { day: "numeric", month: "short", year: "numeric" }); }
  catch { return d; }
};

const statusChip = {
  paid: "bg-emerald-100 text-emerald-700 border-emerald-200",
  unpaid: "bg-amber-100 text-amber-800 border-amber-200",
  overdue: "bg-red-100 text-red-700 border-red-200",
  cancelled: "bg-slate-200 text-slate-600 border-slate-300",
};

const CopyBtn = ({ value }) => {
  const [c, setC] = useState(false);
  return (
    <button
      onClick={() => { navigator.clipboard.writeText(String(value)); setC(true); setTimeout(() => setC(false), 1200); }}
      className="text-slate-400 hover:text-[#f5b120] inline-flex items-center gap-1"
    >
      <Copy className="h-3.5 w-3.5" />
      {c && <span className="text-[10px] text-emerald-600 font-bold">Disalin</span>}
    </button>
  );
};

export default function PublicPayInvoice() {
  const { token } = useParams();
  const [inv, setInv] = useState(null);
  const [err, setErr] = useState("");
  const [payBusy, setPayBusy] = useState(false);
  const [payErr, setPayErr] = useState("");
  const [payUrl, setPayUrl] = useState("");

  useEffect(() => {
    axios.get(`${API}/portal-public/pay/${token}`)
      .then((r) => { setInv(r.data); setPayUrl(r.data.payment_link || ""); })
      .catch((e) => setErr(e?.response?.status === 404
        ? "Link pembayaran tidak ditemukan atau sudah tidak berlaku."
        : (e?.response?.data?.detail || "Gagal memuat tagihan.")));
  }, [token]);

  const payDuitku = async () => {
    setPayBusy(true); setPayErr("");
    try {
      const { data } = await axios.post(`${API}/portal-public/pay/${token}/pay-online`);
      if (data.payment_url) {
        setPayUrl(data.payment_url);
        window.open(data.payment_url, "_blank", "noopener");
      } else setPayErr("Payment link tidak diterima dari gateway. Coba lagi.");
    } catch (e) {
      setPayErr(e?.response?.data?.detail || e.message);
    } finally { setPayBusy(false); }
  };

  if (err) {
    return (
      <div className="min-h-screen bg-[#0a2350] flex items-center justify-center p-6">
        <div className="bg-white rounded-3xl shadow-2xl p-10 max-w-md text-center" data-testid="public-pay-error">
          <AlertTriangle className="h-10 w-10 text-red-500 mx-auto" />
          <h1 className="mt-4 text-xl font-extrabold text-[#0a2350]">Tagihan tidak ditemukan</h1>
          <p className="mt-2 text-sm text-slate-500">{err}</p>
        </div>
      </div>
    );
  }
  if (!inv) {
    return (
      <div className="min-h-screen bg-[#0a2350] flex items-center justify-center">
        <Loader2 className="h-8 w-8 text-[#f5b120] animate-spin" data-testid="public-pay-loading" />
      </div>
    );
  }

  const canPay = inv.status === "unpaid" || inv.status === "overdue";
  const due = inv.amount_due != null ? inv.amount_due : inv.total;
  const hasCredit = (inv.credit_applied || 0) > 0;

  return (
    <div className="min-h-screen bg-slate-100" data-testid="public-pay-page">
      <div className="bg-[#0a2350] pb-24 pt-10 px-4">
        <div className="max-w-2xl mx-auto flex items-center justify-between">
          <div className="text-white">
            <div className="text-[10px] font-bold uppercase tracking-widest text-[#f5b120]">Intercloud Digital · Pembayaran Invoice</div>
            <div className="mt-1 text-2xl font-extrabold font-mono" data-testid="public-pay-number">{inv.number}</div>
            <div className="text-sm text-white/70 mt-0.5">
              {inv.client_name}{inv.client_company ? ` · ${inv.client_company}` : ""}
            </div>
          </div>
          <span className={`px-3 py-1 rounded-full border text-[11px] font-bold uppercase tracking-wide ${statusChip[inv.status] || statusChip.unpaid}`} data-testid="public-pay-status">
            {inv.status}
          </span>
        </div>
      </div>

      <div className="max-w-2xl mx-auto px-4 -mt-16 pb-16 space-y-5">
        <div className="bg-white rounded-3xl shadow-xl border border-slate-200 p-6">
          <div className="flex items-center justify-between text-sm text-slate-500 mb-4">
            <span>Jatuh tempo <b className="text-[#0a2350]">{shortDate(inv.due_date)}</b></span>
            <span className="text-xl font-extrabold text-[#0a2350]" data-testid="public-pay-total">{money(canPay ? due : inv.total)}</span>
          </div>
          <table className="w-full text-sm">
            <thead className="text-[11px] uppercase tracking-widest text-slate-500 border-b border-slate-100">
              <tr><th className="text-left py-2">Deskripsi</th><th className="text-right">Qty</th><th className="text-right">Total</th></tr>
            </thead>
            <tbody>
              {(inv.items || []).map((it, i) => (
                <tr key={i} className="border-b border-slate-100 last:border-0">
                  <td className="py-2.5">{it.description}</td>
                  <td className="text-right">{it.qty}</td>
                  <td className="text-right font-bold">{money(it.total)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="mt-3 space-y-1 text-sm text-right">
            <div className="text-slate-500">Subtotal: <span className="font-semibold text-[#0a2350]">{money(inv.subtotal)}</span></div>
            <div className="text-slate-500">PPN{inv.tax_percent != null ? ` ${inv.tax_percent}%` : ""}: <span className="font-semibold text-[#0a2350]">{money(inv.tax_amount)}</span></div>
            {hasCredit ? (
              <>
                <div className="text-slate-500">Total: <span className="font-semibold text-[#0a2350]">{money(inv.total)}</span></div>
                <div className="text-emerald-700" data-testid="public-pay-credit-row">Credit note: <span className="font-semibold">-{money(inv.credit_applied)}</span></div>
                <div className="text-lg font-extrabold text-[#0a2350]" data-testid="public-pay-amount-due">Sisa tagihan: {money(inv.status === "paid" ? 0 : due)}</div>
              </>
            ) : (
              <div className="text-lg font-extrabold text-[#0a2350]">Total: {money(inv.total)}</div>
            )}
          </div>
        </div>

        {inv.status === "paid" && (
          <div className="bg-emerald-50 border border-emerald-200 rounded-2xl px-5 py-4 text-emerald-800 text-sm flex items-center gap-2" data-testid="public-pay-paid-banner">
            <CheckCircle2 className="h-5 w-5" /> Invoice ini sudah LUNAS{inv.payment_method ? ` via ${inv.payment_method}` : ""}. Terima kasih!
          </div>
        )}

        {canPay && (
          <div className="bg-white rounded-3xl shadow-xl border border-slate-200 p-6 space-y-5">
            <div className="font-extrabold text-[#0a2350]">Pilih metode pembayaran</div>

            <div className="rounded-2xl border-2 border-[#f5b120]/60 bg-[#f5b120]/5 p-4">
              <div className="flex items-center gap-2 font-bold text-[#0a2350]"><CreditCard className="h-4 w-4" /> Bayar Online (Duitku)</div>
              <p className="text-xs text-slate-500 mt-1">VA semua bank, e-wallet, QRIS, retail - konfirmasi otomatis instan.</p>
              {payErr && <div className="mt-3 text-sm text-red-700 bg-red-50 border border-red-200 rounded-lg px-3 py-2" data-testid="public-pay-duitku-error">{payErr}</div>}
              <button
                disabled={!inv.duitku_enabled || payBusy}
                onClick={payDuitku}
                data-testid="public-pay-duitku-btn"
                className={`mt-3 inline-flex items-center gap-2 px-5 py-2.5 rounded-xl font-bold text-sm text-[#0a2350] bg-[#f5b120] hover:brightness-95 transition-all ${(!inv.duitku_enabled || payBusy) ? "opacity-50 cursor-not-allowed" : ""}`}
              >
                {payBusy ? <Loader2 className="h-4 w-4 animate-spin" /> : <ShieldCheck className="h-4 w-4" />}
                {payBusy ? "Membuat link pembayaran…" : `Bayar ${money(due)} sekarang`}
              </button>
              {payUrl && (
                <div className="mt-2 text-xs text-slate-500">
                  Popup tidak terbuka?{" "}
                  <a href={payUrl} target="_blank" rel="noopener noreferrer" className="text-[#0a2350] font-bold underline" data-testid="public-pay-duitku-link">
                    Buka halaman pembayaran →
                  </a>
                </div>
              )}
            </div>

            <div className="rounded-2xl border border-slate-200 p-4" data-testid="public-pay-bank">
              <div className="flex items-center gap-2 font-bold text-[#0a2350]"><Wallet className="h-4 w-4" /> Transfer Bank Manual</div>
              <p className="text-xs text-slate-500 mt-1">
                Transfer persis <b className="text-[#0a2350]">{money(due)}</b>{hasCredit ? " (setelah potongan credit note)" : ""} dan cantumkan nomor invoice <span className="font-mono">{inv.number}</span> di berita transfer.
              </p>
              <div className="mt-3 grid sm:grid-cols-2 gap-2">
                {(inv.bank_accounts || []).map((b, i) => (
                  <div key={i} className="rounded-xl bg-slate-50 border border-slate-200 p-3">
                    <div className="text-[10px] uppercase font-bold tracking-widest text-[#f5b120]">{b.bank}</div>
                    <div className="flex items-center gap-2 mt-1">
                      <div className="font-mono font-extrabold text-[#0a2350]">{b.number}</div>
                      <CopyBtn value={b.number} />
                    </div>
                    <div className="text-[11px] text-slate-500 mt-0.5">A/N {b.holder}</div>
                  </div>
                ))}
              </div>
              <a
                href={`https://wa.me/6287812397187?text=${encodeURIComponent(`Halo, saya sudah transfer untuk invoice ${inv.number} sebesar ${money(inv.total)}. Mohon konfirmasi.`)}`}
                target="_blank" rel="noreferrer"
                data-testid="public-pay-wa-confirm"
                className="mt-3 inline-flex items-center gap-2 px-4 py-2 rounded-xl border border-slate-300 text-xs font-bold text-[#0a2350] hover:border-[#f5b120]"
              >
                Sudah transfer? Konfirmasi via WhatsApp
              </a>
            </div>
          </div>
        )}

        <p className="text-center text-[11px] text-slate-400">
          Halaman pembayaran resmi Intercloud Digital Inovasi · support@intercloud-digital.com
        </p>
      </div>
    </div>
  );
}
