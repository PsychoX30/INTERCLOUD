import React, { useState } from "react";
import { PageHeader, Card, StatusBadge, btnPrimary, inputClass } from "../ui";
import { Globe, Search, RefreshCw, CheckCircle2, XCircle, FileSearch, Lightbulb, AlertTriangle } from "lucide-react";

// MOCK DATA - akan diganti dengan integrasi RNA.id (rdash.id) di fase backend.
const MOCK_DOMAINS = [
  { id: "d1", domain: "intercloud-demo.com", status: "active", registered: "2025-08-01", expiry: "2026-08-01", auto_renew: true, nameservers: ["ns1.intercloud-digital.com", "ns2.intercloud-digital.com"] },
  { id: "d2", domain: "tokosaya.co.id", status: "active", registered: "2025-11-15", expiry: "2026-11-15", auto_renew: false, nameservers: ["ns1.intercloud-digital.com", "ns2.intercloud-digital.com"] },
  { id: "d3", domain: "startup-keren.id", status: "expired", registered: "2024-06-10", expiry: "2026-06-10", auto_renew: false, nameservers: [] },
];

const TLD_PRICES = { ".com": 165000, ".id": 250000, ".co.id": 300000, ".net": 185000, ".org": 175000, ".my.id": 25000 };

const mockCheck = (name) => {
  const taken = ["google", "intercloud", "facebook", "tokopedia"];
  const base = name.toLowerCase().replace(/\..*$/, "");
  return Object.entries(TLD_PRICES).map(([tld, price]) => ({
    domain: `${base}${tld}`,
    available: !taken.includes(base) && (base + tld).length % 7 !== 0,
    price,
  }));
};

// MOCK WHOIS - akan diganti query live via backend/RNA.id di fase backend.
const mockWhois = (domain) => ({
  domain,
  registrar: "RNA.id (Rumah Nama Anda)",
  status: ["clientTransferProhibited", "serverDeleteProhibited"],
  created: "2021-03-14",
  updated: "2026-02-11",
  expiry: "2027-03-14",
  registrant: "REDACTED FOR PRIVACY",
  nameservers: ["ns1.intercloud-digital.com", "ns2.intercloud-digital.com"],
  dnssec: "unsigned",
});

const WhoisCard = () => {
  const [q, setQ] = useState("");
  const [data, setData] = useState(null);
  const [busy, setBusy] = useState(false);

  const lookup = () => {
    if (!q.trim() || !q.includes(".")) return;
    setBusy(true);
    setTimeout(() => {
      setData(mockWhois(q.trim().toLowerCase()));
      setBusy(false);
    }, 500);
  };

  return (
    <Card className="p-6 mt-6" data-testid="whois-card">
      <div className="text-sm font-extrabold text-[#0a2350] mb-1">WHOIS Lookup</div>
      <p className="text-[11px] text-slate-500 mb-3">Lihat informasi registrasi domain yang sudah terdaftar.</p>
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
      {data && (
        <div className="mt-4 rounded-xl bg-slate-50 border border-slate-200 p-4" data-testid="whois-result">
          <div className="text-sm font-extrabold text-[#0a2350] mb-2">{data.domain}</div>
          <div className="grid sm:grid-cols-2 gap-x-6 gap-y-1.5 text-sm">
            {[["Registrar", data.registrar],
              ["Registrant", data.registrant],
              ["Dibuat", data.created],
              ["Diperbarui", data.updated],
              ["Kadaluarsa", data.expiry],
              ["DNSSEC", data.dnssec]].map(([l, v]) => (
              <div key={l} className="flex justify-between gap-3">
                <span className="text-xs uppercase tracking-widest text-slate-500 font-semibold shrink-0">{l}</span>
                <span className="font-semibold text-[#0a2350] text-right truncate">{v}</span>
              </div>
            ))}
          </div>
          <div className="mt-3 pt-3 border-t border-slate-200">
            <div className="text-xs uppercase tracking-widest text-slate-500 font-semibold mb-1">Nameservers</div>
            <div className="flex flex-wrap gap-1.5">
              {data.nameservers.map((ns) => (
                <span key={ns} className="font-mono text-xs bg-white border border-slate-200 rounded-lg px-2 py-1">{ns}</span>
              ))}
            </div>
            <div className="mt-2 flex flex-wrap gap-1.5">
              {data.status.map((st) => (
                <span key={st} className="text-[10px] font-bold uppercase bg-[#0a2350] text-white rounded-full px-2 py-0.5">{st}</span>
              ))}
            </div>
          </div>
          <p className="mt-3 text-[11px] text-slate-500">Data WHOIS masih tiruan - query live menyusul di fase backend.</p>
        </div>
      )}
    </Card>
  );
};

// MOCK suggestion alternatif - engine asli (RNA.id suggestion API) menyusul di fase backend.
const mockSuggest = (name) => {
  const base = name.toLowerCase().replace(/\..*$/, "");
  const variants = [
    `get${base}.com`, `${base}online.com`, `${base}-id.com`, `my${base}.id`,
    `${base}store.com`, `${base}.web.id`, `${base}hq.com`, `${base}.biz.id`,
  ];
  return variants.map((v, i) => ({
    domain: v,
    available: i % 4 !== 3,
    price: TLD_PRICES[Object.keys(TLD_PRICES).find((t) => v.endsWith(t))] || 95000,
  }));
};

const SuggestionList = ({ query }) => {
  const items = mockSuggest(query);
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
            <span className="ml-auto text-xs font-bold text-[#0a2350] shrink-0">Rp {r.price.toLocaleString("id-ID")}</span>
            <button
              className={`text-[10px] font-bold px-2 py-1 rounded-md border shrink-0 ${r.available ? "border-[#f5b120] text-[#0a2350] hover:bg-[#f5b120]/10" : "border-slate-200 text-slate-300 cursor-not-allowed"}`}
              disabled={!r.available}
              data-testid={`suggestion-register-${r.domain}`}
            >
              Daftarkan
            </button>
          </div>
        ))}
      </div>
    </div>
  );
};

const daysUntil = (dateStr) => {
  const diff = new Date(dateStr) - new Date();
  return Math.ceil(diff / 86400000);
};

const ExpiryReminder = () => {
  const expiring = MOCK_DOMAINS
    .map((d) => ({ ...d, days: daysUntil(d.expiry) }))
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
              ? <>sudah kadaluarsa sejak <b>{d.expiry}</b>. Perpanjang sekarang sebelum masuk masa redemption.</>
              : <>akan kadaluarsa dalam <b>{d.days} hari</b> ({d.expiry}). Perpanjang untuk menghindari downtime.</>}
          </div>
        </div>
      ))}
    </div>
  );
};

const ClientDomains = () => {
  const [q, setQ] = useState("");
  const [results, setResults] = useState(null);
  const [checking, setChecking] = useState(false);
  const [orders, setOrders] = useState([
    { id: "o1", domain: "webbaru-saya.com", type: "registrasi", price: 165000, status: "processing" },
  ]);
  const [notice, setNotice] = useState(null);

  const renew = (d) => {
    const tld = Object.keys(TLD_PRICES).find((t) => d.domain.endsWith(t));
    setOrders((prev) => [...prev, {
      id: `o${Date.now()}`,
      domain: d.domain,
      type: "perpanjangan",
      price: TLD_PRICES[tld] || 165000,
      status: "unpaid",
    }]);
    setNotice(`Order perpanjangan ${d.domain} berhasil dibuat. Selesaikan pembayaran untuk memproses.`);
    window.clearTimeout(renew._t);
    renew._t = window.setTimeout(() => setNotice(null), 5000);
  };

  const check = () => {
    if (!q.trim()) return;
    setChecking(true);
    setTimeout(() => {
      setResults(mockCheck(q.trim()));
      setChecking(false);
    }, 600);
  };

  return (
    <div>
      <PageHeader
        title="Domain"
        subtitle="Cek ketersediaan, daftarkan domain baru, dan kelola perpanjangan domain Anda."
      />

      <ExpiryReminder />

      {notice && (
        <div className="mb-5 rounded-2xl border border-emerald-200 bg-emerald-50 text-emerald-800 p-4 flex items-center gap-3 text-sm" data-testid="domain-success-notice">
          <CheckCircle2 className="h-5 w-5 shrink-0" />
          <span className="font-semibold">{notice}</span>
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
                  {r.available ? "Tersedia" : "Tidak tersedia"}
                </span>
                <span className="ml-auto font-extrabold text-[#0a2350]">Rp {r.price.toLocaleString("id-ID")}<span className="text-[10px] font-semibold text-slate-500">/thn</span></span>
                <button
                  className={`text-xs font-bold px-3 py-1.5 rounded-lg border transition-colors ${r.available ? "border-[#f5b120] text-[#0a2350] hover:bg-[#f5b120]/10" : "border-slate-200 text-slate-400 cursor-not-allowed"}`}
                  disabled={!r.available}
                  data-testid={`domain-register-${r.domain}`}
                >
                  Daftarkan
                </button>
              </div>
            ))}
            <p className="pt-3 text-[11px] text-slate-500">Hasil pengecekan masih data tiruan - integrasi live WHOIS/RNA.id menyusul di fase backend.</p>
          </div>
        )}
        {results && <SuggestionList query={q} />}
      </Card>

      <WhoisCard />

      <DomainOrders orders={orders} />

      <div className="mt-6">
        <div className="text-sm font-extrabold text-[#0a2350] mb-3">Domain Saya</div>
        <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4" data-testid="my-domains">
          {MOCK_DOMAINS.map((d) => (
            <Card key={d.id} className="p-5 min-w-0" data-testid={`domain-card-${d.domain}`}>
              <div className="flex items-start justify-between gap-2">
                <div className="h-10 w-10 rounded-xl bg-[#0a2350] flex items-center justify-center shrink-0">
                  <Globe className="h-5 w-5 text-[#f5b120]" strokeWidth={1.9} />
                </div>
                <StatusBadge status={d.status} />
              </div>
              <div className="mt-3 text-base font-extrabold text-[#0a2350] truncate">{d.domain}</div>
              <div className="mt-3 space-y-1 text-sm">
                <div className="flex justify-between"><span className="text-slate-500">Terdaftar</span><span className="font-semibold">{d.registered}</span></div>
                <div className="flex justify-between"><span className="text-slate-500">Kadaluarsa</span><span className={`font-semibold ${d.status === "expired" ? "text-red-600" : ""}`}>{d.expiry}</span></div>
                <div className="flex justify-between items-center">
                  <span className="text-slate-500">Auto-renew</span>
                  <span className={`text-xs font-bold ${d.auto_renew ? "text-emerald-600" : "text-slate-400"}`}>{d.auto_renew ? "Aktif" : "Nonaktif"}</span>
                </div>
              </div>
              <button
                className="mt-4 w-full text-xs font-bold py-2 rounded-lg border border-slate-200 text-[#0a2350] hover:border-[#f5b120] transition-colors inline-flex items-center justify-center gap-1.5 disabled:opacity-60"
                data-testid={`domain-renew-${d.domain}`}
                disabled={orders.some((o) => o.domain === d.domain && o.status !== "active")}
                onClick={() => renew(d)}
              >
                <RefreshCw className="h-3.5 w-3.5" />
                {orders.some((o) => o.domain === d.domain && o.status !== "active") ? "Menunggu pembayaran" : "Perpanjang"}
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

const DomainOrders = ({ orders }) => {
  if (orders.length === 0) return null;
  return (
    <Card className="p-6 mt-6" data-testid="domain-orders">
      <div className="text-sm font-extrabold text-[#0a2350] mb-1">Status Order Domain</div>
      <p className="text-[11px] text-slate-500 mb-3">Registrasi & perpanjangan yang sedang berjalan. Status live dari RNA.id menyusul di fase backend.</p>
      <div className="divide-y divide-slate-100">
        {orders.map((o) => {
          const stepIdx = ORDER_STEPS.indexOf(o.status);
          return (
            <div key={o.id} className="py-3" data-testid={`domain-order-${o.domain}`}>
              <div className="flex items-center gap-3 text-sm">
                <span className="font-bold text-[#0a2350]">{o.domain}</span>
                <span className="text-[10px] font-bold uppercase text-[#f5b120]">{o.type}</span>
                <span className="ml-auto font-semibold">Rp {o.price.toLocaleString("id-ID")}</span>
                <StatusBadge status={o.status} />
              </div>
              <div className="mt-2 flex items-center gap-1.5">
                {ORDER_STEPS.map((s, i) => (
                  <React.Fragment key={s}>
                    <span className={`h-1.5 flex-1 rounded-full ${i <= stepIdx ? "bg-[#f5b120]" : "bg-slate-200"}`} />
                  </React.Fragment>
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
