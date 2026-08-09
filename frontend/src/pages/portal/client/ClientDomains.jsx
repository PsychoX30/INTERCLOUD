import React, { useEffect, useState } from "react";
import { api } from "../../../portal/api";
import { PageHeader, Loading, EmptyState, StatusBadge, Card, btnPrimary, btnSecondary, inputClass } from "../ui";
import { Globe, Settings, Server, ArrowRight, Mail, AlertTriangle, CheckCircle2, XCircle } from "lucide-react";

const idr = (v) => "Rp " + Number(v || 0).toLocaleString("id-ID");

const ClientDomainManager = ({ domain }) => {
  const [tab, setTab] = useState("dns");
  const [dns, setDns] = useState(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");

  const loadDns = async () => {
    try {
      const { data } = await api.get(`/client/domains/${domain.id}/dns`);
      setDns(data.records || []);
    } catch { setDns([]); }
  };

  useEffect(() => {
    if (domain.status === "active" && domain.order_ref) loadDns();
  }, [domain.id]);

  const tabs = [
    { key: "dns", label: "DNS Records", icon: Server },
    { key: "park", label: "Parking", icon: Globe },
    { key: "forward", label: "URL Forwarding", icon: ArrowRight },
    { key: "email", label: "Email Forwarding", icon: Mail },
  ];

  const doPark = async () => {
    setBusy(true); setMsg("");
    try {
      await api.post(`/client/domains/${domain.id}/park`, { ip: "157.20.32.183" });
      setMsg("Domain berhasil diparkir ke 157.20.32.183");
    } catch (e) { setMsg(e?.response?.data?.detail || "Gagal park domain"); }
    finally { setBusy(false); }
  };

  const doForward = async () => {
    const target = prompt("Masukkan URL / IP target forwarding:");
    if (!target) return;
    setBusy(true); setMsg("");
    try {
      await api.post(`/client/domains/${domain.id}/forward`, { target, type: target.includes("://") || target.includes(".") ? "url" : "ip" });
      setMsg(`Domain diforward ke ${target}`);
    } catch (e) { setMsg(e?.response?.data?.detail || "Gagal set forwarding"); }
    finally { setBusy(false); }
  };

  const doEmailFwd = async () => {
    const target = prompt("Masukkan email tujuan forwarding (contoh: user@gmail.com):");
    if (!target) return;
    setBusy(true); setMsg("");
    try {
      await api.post(`/client/domains/${domain.id}/email-forward`, { target });
      setMsg(`Email forwarding diatur ke ${target}`);
    } catch (e) { setMsg(e?.response?.data?.detail || "Gagal set email forwarding"); }
    finally { setBusy(false); }
  };

  if (!domain.order_ref || domain.status !== "active") {
    return (
      <div className="mt-4 p-4 rounded-xl bg-amber-50 border border-amber-200 text-sm text-amber-800 flex items-center gap-3">
        <AlertTriangle className="h-5 w-5 shrink-0" />
        <span>Domain management hanya tersedia untuk domain yang sudah aktif dan terdaftar di registrar.</span>
      </div>
    );
  }

  return (
    <div className="mt-4 border border-slate-200 rounded-xl overflow-hidden" data-testid={`domain-manager-${domain.id}`}>
      <div className="flex border-b border-slate-200 bg-slate-50">
        {tabs.map((t) => (
          <button
            key={t.key}
            className={`flex items-center gap-1.5 px-4 py-2.5 text-xs font-bold transition-colors ${tab === t.key ? "bg-white text-[#0a2350] border-b-2 border-[#f5b120] -mb-[2px]" : "text-slate-500 hover:text-slate-700"}`}
            onClick={() => setTab(t.key)}
            data-testid={`domain-mgr-tab-${t.key}`}
          >
            <t.icon className="h-3.5 w-3.5" /> {t.label}
          </button>
        ))}
      </div>
      <div className="p-4">
        {msg && (
          <div className={`mb-3 rounded-lg px-3 py-2 text-xs font-semibold ${msg.includes("Gagal") ? "bg-red-50 text-red-700" : "bg-emerald-50 text-emerald-700"}`}>
            {msg}
          </div>
        )}

        {tab === "dns" && (
          <div>
            <div className="text-xs font-semibold text-slate-500 mb-2">DNS Records (read-only via RNA.id)</div>
            {dns === null ? <Loading /> : dns.length === 0 ? (
              <div className="text-xs text-slate-400">Belum ada DNS records.</div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="text-left text-slate-500">
                      <th className="pb-1.5 font-semibold">Type</th>
                      <th className="pb-1.5 font-semibold">Name</th>
                      <th className="pb-1.5 font-semibold">Value</th>
                      <th className="pb-1.5 font-semibold">TTL</th>
                    </tr>
                  </thead>
                  <tbody>
                    {dns.map((r, i) => (
                      <tr key={i} className="border-t border-slate-100">
                        <td className="py-1.5 font-bold text-[#0a2350]">{r.type || "-"}</td>
                        <td className="py-1.5 font-mono">{r.name || "@"}</td>
                        <td className="py-1.5 font-mono text-slate-600">{r.value || r.content || "-"}</td>
                        <td className="py-1.5 text-slate-500">{r.ttl || "-"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}

        {tab === "park" && (
          <div className="text-sm space-y-3">
            <p className="text-slate-600">Parkir domain akan mengarahkan domain ke IP server parking (157.20.32.183) dengan halaman "Coming Soon".</p>
            <button className={btnPrimary} onClick={doPark} disabled={busy} data-testid="domain-park-btn">
              <Globe className="h-4 w-4" /> {busy ? "Memproses..." : "Parkir Domain"}
            </button>
          </div>
        )}

        {tab === "forward" && (
          <div className="text-sm space-y-3">
            <p className="text-slate-600">URL forwarding akan mengarahkan pengunjung domain ke alamat lain (contoh: https://tokoonline.com).</p>
            <button className={btnPrimary} onClick={doForward} disabled={busy} data-testid="domain-forward-btn">
              <ArrowRight className="h-4 w-4" /> {busy ? "Memproses..." : "Set Forwarding"}
            </button>
          </div>
        )}

        {tab === "email" && (
          <div className="text-sm space-y-3">
            <p className="text-slate-600">Email forwarding akan meneruskan email yang dikirim ke domain Anda ke alamat email lain.</p>
            <button className={btnPrimary} onClick={doEmailFwd} disabled={busy} data-testid="domain-email-fwd-btn">
              <Mail className="h-4 w-4" /> {busy ? "Memproses..." : "Set Email Forwarding"}
            </button>
          </div>
        )}
      </div>
    </div>
  );
};

/* ---------- Main ClientDomains (updated) ---------- */

const domainPrice = (domain, fallback, prices) => {
  const tld = "." + String(domain || "").split(".").slice(1).join(".");
  const p = prices?.[tld];
  return p?.register ?? fallback;
};

const daysUntil = (dateStr) => Math.ceil((new Date(dateStr) - new Date()) / 86400000);

const SuggestionList = ({ items, onRegister, busyDomain, prices }) => {
  if (!items || items.length === 0) return null;
  return (
    <div className="mt-4 rounded-xl border border-dashed border-[#f5b120]/60 bg-[#f5b120]/5 p-4" data-testid="domain-suggestions">
      <div className="text-sm font-extrabold text-[#0a2350] mb-2">Saran nama alternatif</div>
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
  const [priceSource, setPriceSource] = useState("");
  const [expandedManager, setExpandedManager] = useState(null);

  const load = () => api.get("/client/domains").then((r) => setDomains(r.data)).catch(() => setDomains([]));
  const loadPrices = () =>
    api.get("/client/domains/pricing")
      .then((r) => { setPrices(r.data.prices || {}); setPriceSource(r.data.source || ""); })
      .catch(() => { setPrices({}); setPriceSource(""); });
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

  const activeDomains = (domains || []).filter(d => d.status === "active" || d.status === "expiring" || d.status === "expired");
  const pendingDomains = (domains || []).filter(d => d.status === "pending");

  return (
    <div>
      <PageHeader
        title="Domain"
        subtitle="Cek ketersediaan, daftarkan domain baru, dan kelola domain Anda."
      />

      {notice && (
        <div className="mb-5 rounded-2xl border border-emerald-200 bg-emerald-50 text-emerald-800 p-4 flex items-center gap-3 text-sm" data-testid="domain-success-notice">
          <CheckCircle2 className="h-5 w-5 shrink-0" />
          <span className="font-semibold">{notice}</span>
        </div>
      )}
      {errMsg && (
        <div className="mb-5 rounded-2xl border border-red-200 bg-red-50 text-red-800 p-4 flex items-center gap-3 text-sm" data-testid="domain-error-notice">
          <XCircle className="h-5 w-5 shrink-0" />
          <span className="font-semibold">{errMsg}</span>
        </div>
      )}

      {/* Pending orders */}
      {pendingDomains.length > 0 && (
        <div className="mb-5">
          <div className="text-sm font-extrabold text-[#0a2350] mb-2">Menunggu Pembayaran</div>
          <div className="space-y-2">
            {pendingDomains.map((d) => (
              <Card key={d.id} className="p-4 flex items-center gap-3" data-testid={`pending-domain-${d.id}`}>
                <div className="h-8 w-8 rounded-lg bg-amber-100 flex items-center justify-center">
                  <Globe className="h-4 w-4 text-amber-600" />
                </div>
                <div className="flex-1 min-w-0">
                  <div className="text-sm font-bold text-[#0a2350]">{d.domain}</div>
                  <div className="text-[11px] text-slate-500">Menunggu pembayaran invoice — registrasi diproses setelah lunas</div>
                </div>
                <StatusBadge status="pending" />
                <div className="text-sm font-bold text-[#0a2350]">{idr(d.price)}</div>
              </Card>
            ))}
          </div>
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
            {checking ? "Mengecek..." : "Cek Ketersediaan"}
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

      {priceSource && priceSource !== "cache" && (
        <div className="mt-4 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-xs text-amber-800 flex items-center gap-2" data-testid="price-source-notice">
          <AlertTriangle className="h-4 w-4 shrink-0" />
          {priceSource === "fallback" && "Harga yang ditampilkan adalah harga default internal. Aktifkan integrasi RNA.id dan sync pricing untuk harga live registrar."}
          {priceSource === "stale" && "Sinkronisasi pricing terakhir tidak mengembalikan data dari RNA.id. Hubungi admin untuk memperbaiki integrasi."}
        </div>
      )}

      {/* My Active Domains with Management */}
      <div className="mt-6">
        <div className="text-sm font-extrabold text-[#0a2350] mb-3">Domain Saya</div>
        {domains === null && <Loading />}
        {domains !== null && activeDomains.length === 0 && pendingDomains.length === 0 && (
          <Card className="p-8 text-center text-sm text-slate-500" data-testid="my-domains-empty">
            Belum ada domain. Cari dan daftarkan domain pertama Anda di atas.
          </Card>
        )}
        <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4" data-testid="my-domains">
          {activeDomains.map((d) => (
            <Card key={d.id} className="p-5 min-w-0" data-testid={`domain-card-${d.domain}`}>
              <div className="flex items-start justify-between gap-2">
                <div className="h-10 w-10 rounded-xl bg-[#0a2350] flex items-center justify-center shrink-0">
                  <Globe className="h-5 w-5 text-[#f5b120]" strokeWidth={1.9} />
                </div>
                <StatusBadge status={d.status} />
              </div>
              <div className="mt-3 text-base font-extrabold text-[#0a2350] truncate">{d.domain}</div>
              {d.registered_under_intercloud && (
                <div
                  className="mt-3 rounded-xl border border-amber-300 bg-amber-50 p-3 text-[11px] text-amber-900 leading-snug"
                  data-testid={`domain-intercloud-notice-${d.domain}`}
                >
                  <div className="flex items-start gap-2">
                    <AlertTriangle className="h-3.5 w-3.5 shrink-0 mt-0.5 text-amber-700" />
                    <div>
                      <div className="font-extrabold">
                        Domain <span className="font-mono">{d.domain}</span> Anda didaftarkan atas nama Intercloud.
                      </div>
                      <div className="mt-1 text-amber-800">
                        Karena kelengkapan data profil belum mencukupi. Untuk merubahnya menjadi atas nama Anda sendiri,
                        lengkapi <span className="font-bold">Profil</span> dan kirim ticket dengan judul
                        <span className="font-mono"> Pelengkapan Data Untuk {d.domain}</span>.
                      </div>
                    </div>
                  </div>
                </div>
              )}
              <div className="mt-3 space-y-1 text-sm">
                <div className="flex justify-between"><span className="text-slate-500">Terdaftar</span><span className="font-semibold">{d.registered_at || "-"}</span></div>
                <div className="flex justify-between"><span className="text-slate-500">Kadaluarsa</span><span className={`font-semibold ${d.status === "expired" ? "text-red-600" : ""}`}>{d.expires_at || "-"}</span></div>
                <div className="flex justify-between items-center">
                  <span className="text-slate-500">Auto-renew</span>
                  <span className={`text-xs font-bold ${d.auto_renew ? "text-emerald-600" : "text-slate-400"}`}>{d.auto_renew ? "Aktif" : "Nonaktif"}</span>
                </div>
              </div>
              <div className="mt-3 flex gap-2">
                <button
                  className="flex-1 text-xs font-bold py-2 rounded-lg border border-slate-200 text-[#0a2350] hover:border-[#f5b120] transition-colors inline-flex items-center justify-center gap-1.5 disabled:opacity-60"
                  data-testid={`domain-renew-${d.domain}`}
                  disabled={d.status === "pending" || d.pending_renewal || busyDomain === d.domain}
                  onClick={() => renew(d)}
                >
                  {d.pending_renewal ? "Menunggu bayar" : busyDomain === d.domain ? "Memproses..." : "Perpanjang"}
                </button>
                <button
                  className={`text-xs font-bold px-3 py-2 rounded-lg border transition-colors ${expandedManager === d.id ? "border-[#f5b120] bg-[#f5b120]/10 text-[#0a2350]" : "border-slate-200 text-slate-500 hover:border-slate-300"}`}
                  onClick={() => setExpandedManager(expandedManager === d.id ? null : d.id)}
                  data-testid={`domain-manage-${d.domain}`}
                >
                  <Settings className="h-3.5 w-3.5" />
                </button>
              </div>
              {expandedManager === d.id && <ClientDomainManager domain={d} />}
            </Card>
          ))}
        </div>
      </div>
    </div>
  );
};

export default ClientDomains;