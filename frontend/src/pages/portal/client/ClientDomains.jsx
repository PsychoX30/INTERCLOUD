import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../../portal/api";
import { PageHeader, Card, StatusBadge, Loading, btnPrimary, inputClass } from "../ui";
import { Globe, Search, RefreshCw, CheckCircle2, XCircle, FileSearch, Lightbulb, AlertTriangle } from "lucide-react";

const idr = (v) => "Rp " + Number(v || 0).toLocaleString("id-ID");

const WhoisCard = () => {
  const [q, setQ] = useState("");
  const [data, setData] = useState(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  const lookup = async () => {
    if (!q.trim() || !q.includes(".")) return;
    setBusy(true); setErr(""); setData(null);
    try {
      const { data: w } = await api.get("/client/domains/whois", { params: { domain: q.trim().toLowerCase() } });
      setData(w);
    } catch (e) {
      setErr(e?.response?.data?.detail || "Lookup gagal");
    } finally { setBusy(false); }
  };

  return (
    <Card className="p-6 mt-6" data-testid="whois-card">
      <div className="text-sm font-extrabold text-[#0a2350] mb-1">WHOIS Lookup</div>
      <p className="text-[11px] text-slate-500 mb-3">Lihat informasi registrasi domain yang sudah terdaftar (data live).</p>
      <div className="flex gap-2">
        <input
          data-testid="whois-input"
          className={`${inputClass} flex-1`}
          placeholder="contoh: intercloud-digital.com"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && lookup()}
        />
        <button data-testid="whois-btn" className={btnPrimary} onClick={lookup} disabled={busy || !q.includes(".")}>
          <FileSearch className="h-4 w-4" /> {busy ? "Mencari..." : "Lookup"}
        </button>
      </div>
      {err && <div className="mt-3 text-sm text-red-700 bg-red-50 border border-red-200 rounded-xl px-3 py-2" data-testid="whois-error">{err}</div>}
      {data && (
        <div className="mt-4 rounded-xl bg-slate-50 border border-slate-200 p-4" data-testid="whois-result">
          <div className="text-sm font-extrabold text-[#0a2350] mb-2">{data.domain}</div>
          {data.registered === false ? (
            <div className="text-sm text-emerald-700 font-semibold" data-testid="whois-unregistered">
              Domain ini belum terdaftar - tersedia untuk registrasi.
            </div>
          ) : (
            <>
              <div className="grid sm:grid-cols-2 gap-x-6 gap-y-1.5 text-sm">
                {[["Registrar", data.registrar || "-"],
                  ["Registrant", data.registrant || "-"],
                  ["Dibuat", data.created || "-"],
                  ["Diperbarui", data.updated || "-"],
                  ["Kadaluarsa", data.expiry || "-"],
                  ["DNSSEC", data.dnssec || "-"]].map(([l, v]) => (
                  <div key={l} className="flex justify-between gap-3">
                    <span className="text-xs uppercase tracking-widest text-slate-500 font-semibold shrink-0">{l}</span>
                    <span className="font-semibold text-[#0a2350] text-right truncate">{v}</span>
                  </div>
                ))}
              </div>
              <div className="mt-3 pt-3 border-t border-slate-200">
                <div className="text-xs uppercase tracking-widest text-slate-500 font-semibold mb-1">Nameservers</div>
                <div className="flex flex-wrap gap-1.5">
                  {(data.nameservers || []).map((ns) => (
                    <span key={ns} className="font-mono text-xs bg-white border border-slate-200 rounded-lg px-2 py-1">{ns}</span>
                  ))}
                  {(data.nameservers || []).length === 0 && <span className="text-xs text-slate-400">-</span>}
                </div>
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {(data.status || []).map((st) => (
                    <span key={st} className="text-[10px] font-bold uppercase bg-[#0a2350] text-white rounded-full px-2 py-0.5">{st}</span>
                  ))}
                </div>
              </div>
            </>
          )}
          <p className="mt-3 text-[11px] text-slate-500">Sumber: {data.source === "rna" ? "RNA.id (RDASH)" : "RDAP publik"} - data live.</p>
        </div>
      )}
    </Card>
  );
};

const domainPrice = (domain, fallback, prices) => {
  const tld = "." + String(domain || "").split(".").slice(1).join(".");
  const p = prices?.[tld];
  return p?.register ?? fallback;
};

const SuggestionList = ({ items, onRegister, busyDomain, prices }) => {
  if (!items || items.length === 0) return null;
  return (
    <div className="mt-4 rounded-xl border border-dashed border-[#f5b120]/60 bg-[#f5b120]/5 p-4" data-testid="domain-suggestions">
      <div className="flex items-center gap-2 mb-2">
        <Lightbulb className="h-4 w-4 text-[#f5b120]" />
        <span className="text-sm font-extrabold text-[#0a2350]">Saran nama alternatif</span>
      </div>
      <div className="grid sm:grid-cols-2 gap-x-6 divide-y sm:divide-y-0 divide-slate-100">
        {items.map((r) => (
          <div key={r.domain} className="py-2 flex items-center gap-2.5 text-sm min-w-0" data-testid={`suggestion-${r.domain}`}>
            {r.available
              ? <CheckCircle2 className="h-3.5 w-3.5 text-emerald-500 shrink-0" />
              : <XCircle className="h-3.5 w-3.5 text-red-400 shrink-0" />}
            <span className={`font-semibold truncate ${r.available ? "text-[#0a2350]" : "text-slate-400 line-through"}`}>{r.domain}</span>
            <span className="ml-auto text-xs font-bold text-[#0a2350] shrink-0">{idr(domainPrice(r.domain, r.price, prices))}</span>
            <button
              className={`text-[10px] font-bold px-2 py-1 rounded-md border shrink-0 ${r.available ? "border-[#f5b120] text-[#0a2350] hover:bg-[#f5b120]/10" : "border-slate-200 text-slate-300 cursor-not-allowed"}`}
              disabled={!r.available || busyDomain === r.domain}
              onClick={() => onRegister(r.domain)}
              data-testid={`suggestion-register-${r.domain}`}
            >
              {busyDomain === r.domain ? "..." : "Daftarkan"}
            </button>
          </div>
        ))}
      </div>
    </div>
  );
};

const daysUntil = (dateStr) => Math.ceil((new Date(dateStr) - new Date()) / 86400000);

const ExpiryReminder = ({ domains }) => {
  const expiring = (domains || [])
    .filter((d) => d.expires_at && d.status !== "pending")
    .map((d) => ({ ...d, days: daysUntil(d.expires_at) }))
    .filter((d) => d.days <= 30);
  if (expiring.length === 0) return null;
  return (
    <div className="mb-5 space-y-2" data-testid="expiry-reminders">
      {expiring.map((d) => (
        <div
          key={d.id}
          className={`rounded-2xl border p-4 flex items-center gap-3 text-sm ${
            d.days < 0 ? "bg-red-50 border-red-200 text-red-800" : "bg-amber-50 border-amber-200 text-amber-800"
          }`}
          data-testid={`expiry-reminder-${d.domain}`}
        >
          <AlertTriangle className="h-5 w-5 shrink-0" />
          <div className="min-w-0 flex-1">
            <span className="font-extrabold">{d.domain}</span>{" "}
            {d.days < 0
              ? <>sudah kadaluarsa sejak <b>{d.expires_at}</b>. Perpanjang sekarang sebelum masuk masa redemption.</>
              : <>akan kadaluarsa dalam <b>{d.days} hari</b> ({d.expires_at}). Perpanjang untuk menghindari downtime.</>}
          </div>
        </div>
      ))}
    </div>
  );
};

const ClientDomains = () => {
  const [q, setQ] = useState("");
  const [results, setResults] = useState(null);
  const [suggestions, setSuggestions] = useState(null);
  const [checking, setChecking] = useState(false);
  const [domains, setDomains] = useState(null);
  const [notice, setNotice] = useState(null);
  const [errMsg, setErrMsg] = useState("");
  const [busyDomain, setBusyDomain] = useState("");
  const [prices, setPrices] = useState(null);

  const load = () => api.get("/client/domains").then((r) => setDomains(r.data)).catch(() => setDomains([]));
  const loadPrices = () => api.get("/client/domains/pricing").then((r) => setPrices(r.data.prices || {})).catch(() => setPrices({}));
  useEffect(() => { load(); loadPrices(); }, []);

  const flash = (msg) => {
    setNotice(msg);
    window.clearTimeout(flash._t);
    flash._t = window.setTimeout(() => setNotice(null), 8000);
  };

  const check = async () => {
    if (!q.trim()) return;
    setChecking(true); setErrMsg(""); setResults(null); setSuggestions(null);
    try {
      const [chk, sug] = await Promise.all([
        api.get("/client/domains/check", { params: { domain: q.trim() } }),
        api.get("/client/domains/suggest", { params: { q: q.trim() } }).catch(() => ({ data: { suggestions: [] } })),
      ]);
      setResults(chk.data.results);
      setSuggestions(sug.data.suggestions);
    } catch (e) {
      setErrMsg(e?.response?.data?.detail || "Pengecekan gagal, coba lagi.");
    } finally { setChecking(false); }
  };

  const register = async (domain) => {
    setBusyDomain(domain); setErrMsg("");
    try {
      const { data } = await api.post("/client/domains/order", { domain, years: 1 });
      flash(`Order registrasi ${domain} dibuat - Invoice ${data.number} (${idr(data.total)}). Selesaikan pembayaran untuk memproses.`);
      load();
    } catch (e) {
      setErrMsg(e?.response?.data?.detail || "Gagal membuat order domain");
    } finally { setBusyDomain(""); }
  };

  const renew = async (d) => {
    setBusyDomain(d.domain); setErrMsg("");
    try {
      const { data } = await api.post(`/client/domains/${d.id}/renew`, { years: 1 });
      flash(`Order perpanjangan ${d.domain} dibuat - Invoice ${data.number} (${idr(data.total)}). Selesaikan pembayaran untuk memproses.`);
      load();
    } catch (e) {
      setErrMsg(e?.response?.data?.detail || "Gagal membuat order perpanjangan");
    } finally { setBusyDomain(""); }
  };

  return (
    <div>
      <PageHeader
        title="Domain"
        subtitle="Cek ketersediaan, daftarkan domain baru, dan kelola perpanjangan domain Anda."
      />

      <ExpiryReminder domains={domains} />

      {notice && (
        <div className="mb-5 rounded-2xl border border-emerald-200 bg-emerald-50 text-emerald-800 p-4 flex items-center gap-3 text-sm" data-testid="domain-success-notice">
          <CheckCircle2 className="h-5 w-5 shrink-0" />
          <span className="font-semibold">{notice}</span>
          <Link to="/portal/client/invoices" className="ml-auto shrink-0 text-xs font-bold underline hover:text-emerald-950" data-testid="domain-notice-invoice-link">Lihat invoice →</Link>
        </div>
      )}
      {errMsg && (
        <div className="mb-5 rounded-2xl border border-red-200 bg-red-50 text-red-800 p-4 flex items-center gap-3 text-sm" data-testid="domain-error-notice">
          <XCircle className="h-5 w-5 shrink-0" />
          <span className="font-semibold">{errMsg}</span>
        </div>
      )}

      <Card className="p-6" data-testid="domain-search-card">
        <div className="text-sm font-extrabold text-[#0a2350] mb-3">Cari domain baru</div>
        <div className="flex gap-2">
          <input
            data-testid="domain-search-input"
            className={`${inputClass} flex-1`}
            placeholder="namadomainanda"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && check()}
          />
          <button data-testid="domain-search-btn" className={btnPrimary} onClick={check} disabled={checking || !q.trim()}>
            <Search className="h-4 w-4" /> {checking ? "Mengecek..." : "Cek Ketersediaan"}
          </button>
        </div>
        {results && (
          <div className="mt-4 divide-y divide-slate-100" data-testid="domain-results">
            {results.map((r) => (
              <div key={r.domain} className="py-2.5 flex items-center gap-3 text-sm" data-testid={`domain-result-${r.domain}`}>
                {r.available
                  ? <CheckCircle2 className="h-4 w-4 text-emerald-500 shrink-0" />
                  : <XCircle className="h-4 w-4 text-red-400 shrink-0" />}
                <span className="font-semibold text-[#0a2350]">{r.domain}</span>
                <span className={`text-xs font-bold ${r.available ? "text-emerald-600" : "text-red-500"}`}>
                  {r.available === null ? "Tidak diketahui" : r.available ? "Tersedia" : "Tidak tersedia"}
                </span>
                <span className="ml-auto font-extrabold text-[#0a2350]">{idr(domainPrice(r.domain, r.price, prices))}<span className="text-[10px] font-semibold text-slate-500">/thn</span></span>
                <button
                  className={`text-xs font-bold px-3 py-1.5 rounded-lg border transition-colors ${r.available ? "border-[#f5b120] text-[#0a2350] hover:bg-[#f5b120]/10" : "border-slate-200 text-slate-400 cursor-not-allowed"}`}
                  disabled={!r.available || busyDomain === r.domain}
                  onClick={() => register(r.domain)}
                  data-testid={`domain-register-${r.domain}`}
                >
                  {busyDomain === r.domain ? "Memproses..." : "Daftarkan"}
                </button>
              </div>
            ))}
            <p className="pt-3 text-[11px] text-slate-500">Pengecekan live (RNA.id bila aktif, fallback DNS). Registrasi diproses otomatis setelah invoice lunas.</p>
          </div>
        )}
        {results && <SuggestionList items={suggestions} onRegister={register} busyDomain={busyDomain} prices={prices} />}
      </Card>

      <WhoisCard />

      <DomainOrders domains={domains} />

      <div className="mt-6">
        <div className="text-sm font-extrabold text-[#0a2350] mb-3">Domain Saya</div>
        {domains === null && <Loading />}
        {domains !== null && domains.length === 0 && (
          <Card className="p-8 text-center text-sm text-slate-500" data-testid="my-domains-empty">
            Belum ada domain. Cari dan daftarkan domain pertama Anda di atas.
          </Card>
        )}
        <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4" data-testid="my-domains">
          {(domains || []).map((d) => (
            <Card key={d.id} className="p-5 min-w-0" data-testid={`domain-card-${d.domain}`}>
              <div className="flex items-start justify-between gap-2">
                <div className="h-10 w-10 rounded-xl bg-[#0a2350] flex items-center justify-center shrink-0">
                  <Globe className="h-5 w-5 text-[#f5b120]" strokeWidth={1.9} />
                </div>
                <StatusBadge status={d.status} />
              </div>
              <div className="mt-3 text-base font-extrabold text-[#0a2350] truncate">{d.domain}</div>
              <div className="mt-3 space-y-1 text-sm">
                <div className="flex justify-between"><span className="text-slate-500">Terdaftar</span><span className="font-semibold">{d.registered_at || "-"}</span></div>
                <div className="flex justify-between"><span className="text-slate-500">Kadaluarsa</span><span className={`font-semibold ${d.status === "expired" ? "text-red-600" : ""}`}>{d.expires_at || "-"}</span></div>
                <div className="flex justify-between items-center">
                  <span className="text-slate-500">Auto-renew</span>
                  <span className={`text-xs font-bold ${d.auto_renew ? "text-emerald-600" : "text-slate-400"}`}>{d.auto_renew ? "Aktif" : "Nonaktif"}</span>
                </div>
              </div>
              <button
                className="mt-4 w-full text-xs font-bold py-2 rounded-lg border border-slate-200 text-[#0a2350] hover:border-[#f5b120] transition-colors inline-flex items-center justify-center gap-1.5 disabled:opacity-60"
                data-testid={`domain-renew-${d.domain}`}
                disabled={d.status === "pending" || d.pending_renewal || busyDomain === d.domain}
                onClick={() => renew(d)}
              >
                <RefreshCw className="h-3.5 w-3.5" />
                {d.status === "pending" ? "Menunggu pembayaran" : d.pending_renewal ? "Perpanjangan menunggu bayar" : busyDomain === d.domain ? "Memproses..." : "Perpanjang"}
              </button>
            </Card>
          ))}
        </div>
      </div>
    </div>
  );
};

const ORDER_STEPS = ["unpaid", "processing", "active"];
const ORDER_STEP_LABELS = { unpaid: "Menunggu pembayaran", processing: "Diproses registrar", active: "Aktif" };

const DomainOrders = ({ domains }) => {
  const orders = [];
  (domains || []).forEach((d) => {
    if (d.status === "pending") {
      orders.push({ id: `${d.id}-reg`, domain: d.domain, type: "registrasi", price: d.price, status: "unpaid" });
    }
    if (d.pending_renewal) {
      orders.push({ id: `${d.id}-ren`, domain: d.domain, type: "perpanjangan", price: d.price, status: "unpaid" });
    }
  });
  if (orders.length === 0) return null;
  return (
    <Card className="p-6 mt-6" data-testid="domain-orders">
      <div className="text-sm font-extrabold text-[#0a2350] mb-1">Status Order Domain</div>
      <p className="text-[11px] text-slate-500 mb-3">
        Registrasi & perpanjangan yang menunggu pembayaran. Diproses otomatis begitu invoice lunas.{" "}
        <Link to="/portal/client/invoices" className="font-bold text-[#f5b120]">Bayar invoice →</Link>
      </p>
      <div className="divide-y divide-slate-100">
        {orders.map((o) => {
          const stepIdx = ORDER_STEPS.indexOf(o.status);
          return (
            <div key={o.id} className="py-3" data-testid={`domain-order-${o.domain}`}>
              <div className="flex items-center gap-3 text-sm">
                <span className="font-bold text-[#0a2350]">{o.domain}</span>
                <span className="text-[10px] font-bold uppercase text-[#f5b120]">{o.type}</span>
                <span className="ml-auto font-semibold">{idr(o.price)}</span>
                <StatusBadge status={o.status} />
              </div>
              <div className="mt-2 flex items-center gap-1.5">
                {ORDER_STEPS.map((s, i) => (
                  <span key={s} className={`h-1.5 flex-1 rounded-full ${i <= stepIdx ? "bg-[#f5b120]" : "bg-slate-200"}`} />
                ))}
              </div>
              <div className="mt-1 text-[10px] text-slate-500">{ORDER_STEP_LABELS[o.status]}</div>
            </div>
          );
        })}
      </div>
    </Card>
  );
};

export default ClientDomains;
