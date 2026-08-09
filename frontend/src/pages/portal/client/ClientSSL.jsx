import React, { useEffect, useState } from "react";
import { api } from "../../../portal/api";
import { PageHeader, Loading, EmptyState, StatusBadge, Card, btnPrimary, btnSecondary, inputClass } from "../ui";
import { ShieldCheck, CheckCircle2, XCircle, AlertTriangle, Clock } from "lucide-react";

const idr = (v) => "Rp " + Number(v || 0).toLocaleString("id-ID");

const SSLClient = () => {
  const [products, setProducts] = useState(null);
  const [source, setSource] = useState("");
  const [orders, setOrders] = useState(null);
  const [tab, setTab] = useState("catalog");
  const [selected, setSelected] = useState(null);
  const [form, setForm] = useState({ domain: "", period_months: 12, dcv_method: "dns", csr_code: "" });
  const [busy, setBusy] = useState(false);
  const [errMsg, setErrMsg] = useState("");
  const [notice, setNotice] = useState("");

  const loadCatalog = async () => {
    try {
      const { data } = await api.get("/client/ssl/products");
      setProducts(data.products || []);
      setSource(data.source || "");
    } catch { setProducts([]); }
  };

  const loadOrders = async () => {
    try {
      const { data } = await api.get("/client/ssl/orders");
      setOrders(data.orders || []);
    } catch { setOrders([]); }
  };

  useEffect(() => { loadCatalog(); loadOrders(); }, []);

  const flash = (msg) => {
    setNotice(msg);
    window.clearTimeout(flash._t);
    flash._t = window.setTimeout(() => setNotice(null), 8000);
  };

  const order = async () => {
    if (!selected || !form.domain.trim() || !form.csr_code.trim()) return;
    setBusy(true); setErrMsg("");
    try {
      const { data } = await api.post("/client/ssl/orders", {
        product_id: selected.product_id,
        period_months: form.period_months,
        domain: form.domain.trim(),
        dcv_method: form.dcv_method,
        csr_code: form.csr_code,
      });
      flash(`Order SSL ${selected.name} untuk ${form.domain} dibuat - Invoice ${data.number} (${idr(data.total)}). Selesaikan pembayaran untuk memproses.`);
      setSelected(null);
      setForm({ domain: "", period_months: 12, dcv_method: "dns", csr_code: "" });
      loadOrders();
    } catch (e) {
      setErrMsg(e?.response?.data?.detail || "Gagal membuat order SSL");
    } finally { setBusy(false); }
  };

  const validationLabel = (v) => ({ DV: "Domain Validation", OV: "Organization Validation", EV: "Extended Validation" }[v] || v);

  return (
    <div>
      <PageHeader title="SSL Certificate" subtitle="Beli dan kelola sertifikat SSL dari berbagai brand ternama." />

      {notice && (
        <div className="mb-5 rounded-2xl border border-emerald-200 bg-emerald-50 text-emerald-800 p-4 flex items-center gap-3 text-sm" data-testid="ssl-success-notice">
          <CheckCircle2 className="h-5 w-5 shrink-0" />
          <span className="font-semibold">{notice}</span>
        </div>
      )}
      {errMsg && (
        <div className="mb-5 rounded-2xl border border-red-200 bg-red-50 text-red-800 p-4 flex items-center gap-3 text-sm" data-testid="ssl-error-notice">
          <XCircle className="h-5 w-5 shrink-0" />
          <span className="font-semibold">{errMsg}</span>
        </div>
      )}

      <div className="flex gap-2 mb-5">
        <button
          className={`text-xs font-bold px-4 py-2 rounded-lg border transition-colors ${tab === "catalog" ? "bg-[#0a2350] text-white border-[#0a2350]" : "border-slate-200 text-slate-600 hover:border-slate-300"}`}
          onClick={() => setTab("catalog")}
          data-testid="ssl-tab-catalog"
        >
          <ShieldCheck className="h-3.5 w-3.5 inline mr-1" /> Katalog SSL
        </button>
        <button
          className={`text-xs font-bold px-4 py-2 rounded-lg border transition-colors ${tab === "orders" ? "bg-[#0a2350] text-white border-[#0a2350]" : "border-slate-200 text-slate-600 hover:border-slate-300"}`}
          onClick={() => setTab("orders")}
          data-testid="ssl-tab-orders"
        >
          Order Saya
        </button>
      </div>

      {tab === "catalog" && (
        <div>
          {source === "offline" && (
            <div className="mb-4 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-xs text-amber-800 flex items-center gap-2" data-testid="ssl-offline-notice">
              <AlertTriangle className="h-4 w-4 shrink-0" />
              Integrasi RNA.id belum aktif. Katalog SSL tidak tersedia.
            </div>
          )}
          {products === null && <Loading />}
          {products !== null && products.length === 0 && (
            <Card className="p-8 text-center text-sm text-slate-500" data-testid="ssl-catalog-empty">
              {source === "offline" ? "Aktifkan integrasi RNA.id untuk melihat katalog SSL." : "Belum ada produk SSL tersedia."}
            </Card>
          )}
          <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {(products || []).map((p) => (
              <Card key={p.product_id} className="p-5" data-testid={`ssl-product-${p.product_id}`}>
                <div className="flex items-start justify-between gap-2">
                  <div className="h-10 w-10 rounded-xl bg-emerald-100 flex items-center justify-center shrink-0">
                    <ShieldCheck className="h-5 w-5 text-emerald-600" strokeWidth={1.9} />
                  </div>
                  {p.is_wildcard && <span className="text-[10px] font-bold px-2 py-0.5 bg-purple-100 text-purple-700 rounded-full">Wildcard</span>}
                </div>
                <div className="mt-3 text-sm font-extrabold text-[#0a2350] leading-tight">{p.name}</div>
                <div className="mt-1 text-[11px] text-slate-500">{p.brand} &middot; {validationLabel(p.validation)}</div>
                <div className="mt-3 space-y-1">
                  {Object.entries(p.terms).sort(([a], [b]) => Number(a) - Number(b)).map(([months, price]) => (
                    <div key={months} className="flex justify-between text-xs">
                      <span className="text-slate-500">{Number(months) / 12} tahun</span>
                      <span className="font-bold text-[#0a2350]">{idr(price)}</span>
                    </div>
                  ))}
                </div>
                <button
                  className={`${btnPrimary} w-full mt-4`}
                  data-testid={`ssl-order-${p.product_id}`}
                  onClick={() => { setSelected(p); setForm({ ...form, period_months: Number(Object.keys(p.terms)[0] || 12) }); }}
                >
                  Pesan SSL
                </button>
              </Card>
            ))}
          </div>

          {/* Order dialog */}
          {selected && (
            <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40" data-testid="ssl-order-dialog">
              <Card className="w-full max-w-lg p-6 mx-4 max-h-[90vh] overflow-y-auto">
                <div className="text-base font-extrabold text-[#0a2350] mb-1">{selected.name}</div>
                <div className="text-xs text-slate-500 mb-4">{selected.brand} &middot; {validationLabel(selected.validation)}</div>

                <label className="text-xs font-bold text-slate-500 mb-1 block">Domain</label>
                <input
                  data-testid="ssl-order-domain"
                  className={`${inputClass} mb-3`}
                  placeholder="contoh.com"
                  value={form.domain}
                  onChange={(e) => setForm({ ...form, domain: e.target.value })}
                />

                <label className="text-xs font-bold text-slate-500 mb-1 block">Periode</label>
                <select
                  className={`${inputClass} mb-3`}
                  value={form.period_months}
                  onChange={(e) => setForm({ ...form, period_months: Number(e.target.value) })}
                  data-testid="ssl-order-period"
                >
                  {Object.entries(selected.terms).sort(([a], [b]) => Number(a) - Number(b)).map(([months, price]) => (
                    <option key={months} value={months}>{Number(months) / 12} tahun - {idr(price)}</option>
                  ))}
                </select>

                <label className="text-xs font-bold text-slate-500 mb-1 block">Metode Validasi</label>
                <select
                  className={`${inputClass} mb-3`}
                  value={form.dcv_method}
                  onChange={(e) => setForm({ ...form, dcv_method: e.target.value })}
                  data-testid="ssl-order-dcv"
                >
                  <option value="dns">DNS</option>
                  <option value="http">HTTP</option>
                  <option value="https">HTTPS</option>
                  <option value="email">Email</option>
                </select>

                <label className="text-xs font-bold text-slate-500 mb-1 block">CSR Code</label>
                <textarea
                  data-testid="ssl-order-csr"
                  className={`${inputClass} mb-4 font-mono text-[11px]`}
                  rows={6}
                  placeholder="-----BEGIN CERTIFICATE REQUEST-----&#10;...&#10;-----END CERTIFICATE REQUEST-----"
                  value={form.csr_code}
                  onChange={(e) => setForm({ ...form, csr_code: e.target.value })}
                />

                <div className="text-sm font-bold text-[#0a2350] mb-3">
                  Total: {idr(selected.terms[String(form.period_months)])}
                  <span className="text-[11px] text-slate-500 ml-1">(+ pajak 11%)</span>
                </div>

                <div className="flex gap-2 justify-end">
                  <button className={btnSecondary} onClick={() => setSelected(null)}>Batal</button>
                  <button
                    className={btnPrimary}
                    data-testid="ssl-order-submit"
                    disabled={!form.domain.trim() || !form.csr_code.trim() || busy}
                    onClick={order}
                  >
                    {busy ? "Memproses..." : "Buat Invoice"}
                  </button>
                </div>
              </Card>
            </div>
          )}
        </div>
      )}

      {tab === "orders" && (
        <div>
          {orders === null && <Loading />}
          {orders !== null && orders.length === 0 && (
            <Card className="p-8 text-center text-sm text-slate-500" data-testid="ssl-orders-empty">
              Belum ada order SSL. Pesan sertifikat SSL dari tab Katalog.
            </Card>
          )}
          <div className="space-y-3">
            {(orders || []).map((o) => (
              <Card key={o.id} className="p-4" data-testid={`ssl-order-${o.id}`}>
                <div className="flex items-center gap-3">
                  <div className="h-8 w-8 rounded-lg bg-emerald-100 flex items-center justify-center">
                    <ShieldCheck className="h-4 w-4 text-emerald-600" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="text-sm font-bold text-[#0a2350] truncate">{o.domain}</div>
                    <div className="text-[11px] text-slate-500">{o.product_name} &middot; {o.period_months} bulan</div>
                  </div>
                  <StatusBadge status={o.status} />
                  <div className="text-sm font-bold text-[#0a2350]">{idr(o.price)}</div>
                </div>
                {o.provision_note && (
                  <div className="mt-2 text-[11px] text-slate-500 flex items-center gap-1">
                    <Clock className="h-3 w-3" /> {o.provision_note}
                  </div>
                )}
                {o.provider_order_id && (
                  <div className="mt-1 text-[11px] text-slate-400 font-mono">Ref: {o.provider_order_id}</div>
                )}
              </Card>
            ))}
          </div>
        </div>
      )}
    </div>
  );
};

export default SSLClient;