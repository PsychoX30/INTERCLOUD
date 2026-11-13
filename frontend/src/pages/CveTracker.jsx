import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { Helmet } from "react-helmet-async";
import {
  ShieldAlert, Search, RefreshCw, ChevronDown, ExternalLink, AlertTriangle,
  Flame, Loader2, ArrowUpRight, Database, Clock, ChevronRight,
} from "lucide-react";
import Header from "../components/Header";
import Footer from "../components/Footer";

const BASE = (process.env.REACT_APP_BACKEND_URL || "").replace(/\/$/, "");
const API = `${BASE}/api/portal`;

const PAGE_SIZE = 24;

// Severity palette mirrors the INTERCLOUD brand (navy #0a2350 / amber #f5b120).
const SEV = {
  critical: { label: "Critical", chip: "bg-red-600 text-white",     border: "border-red-300",    dot: "bg-red-500",     text: "text-red-700" },
  high:     { label: "High",     chip: "bg-orange-500 text-white",  border: "border-orange-300", dot: "bg-orange-500",  text: "text-orange-700" },
  medium:   { label: "Medium",   chip: "bg-amber-400 text-[#0a2350]", border: "border-amber-300", dot: "bg-amber-400",  text: "text-amber-700" },
  low:      { label: "Low",      chip: "bg-sky-500 text-white",     border: "border-sky-300",    dot: "bg-sky-500",     text: "text-sky-700" },
  none:     { label: "None",     chip: "bg-slate-400 text-white",   border: "border-slate-300",  dot: "bg-slate-400",   text: "text-slate-600" },
  unknown:  { label: "Unscored", chip: "bg-slate-400 text-white",   border: "border-slate-300",  dot: "bg-slate-400",   text: "text-slate-600" },
};
const sevMeta = (s) => SEV[String(s || "unknown").toLowerCase()] || SEV.unknown;

const SEVERITY_FILTERS = [
  { key: "", label: "All Severities" },
  { key: "critical", label: "Critical" },
  { key: "high", label: "High" },
  { key: "medium", label: "Medium" },
  { key: "low", label: "Low" },
];

const SORT_FILTERS = [
  { key: "newest", label: "Newest First" },
  { key: "severity", label: "By Severity" },
  { key: "cvss", label: "By CVSS Score" },
];

const fmtDate = (iso) => {
  if (!iso) return "-";
  try {
    return new Date(iso).toLocaleDateString("en-GB", {
      day: "2-digit", month: "short", year: "numeric",
    });
  } catch { return "-"; }
};

const fmtDateTime = (iso) => {
  if (!iso) return "-";
  try {
    return new Date(iso).toLocaleString("en-GB", {
      day: "2-digit", month: "short", year: "numeric",
      hour: "2-digit", minute: "2-digit", timeZone: "UTC",
    }) + " UTC";
  } catch { return "-"; }
};

const ageLabel = (iso) => {
  if (!iso) return "";
  const ms = Date.now() - new Date(iso).getTime();
  if (!Number.isFinite(ms) || ms < 0) return "";
  const mins = Math.floor(ms / 60000);
  if (mins < 60) return `${Math.max(1, mins)}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
};

// ---------------------------------------------------------------- cards ----
const StatCard = ({ title, value, icon: Icon, tone, delta, testid }) => (
  <div
    className={`relative overflow-hidden rounded-2xl border bg-white p-5 shadow-sm ${tone.border}`}
    data-testid={testid}
  >
    <div className="flex items-start justify-between">
      <div className={`inline-flex h-10 w-10 items-center justify-center rounded-xl ${tone.bg}`}>
        <Icon className={`h-5 w-5 ${tone.text}`} />
      </div>
      {delta != null && (
        <span className={`text-[11px] font-bold px-2 py-1 rounded-full ${
          delta > 0 ? "bg-red-50 text-red-600" : delta < 0 ? "bg-emerald-50 text-emerald-600" : "bg-slate-100 text-slate-500"
        }`}>
          {delta > 0 ? "+" : ""}{delta}%
        </span>
      )}
    </div>
    <div className="mt-4 text-3xl font-extrabold tracking-tight text-[#0a2350]" data-testid={`${testid}-value`}>
      {value == null ? "—" : Number(value).toLocaleString()}
    </div>
    <div className="mt-1 text-xs font-semibold uppercase tracking-widest text-slate-500">{title}</div>
  </div>
);

const CveCard = ({ c }) => {
  const meta = sevMeta(c.severity);
  const desc = c.description || "";
  return (
    <Link
      to={`/cve/${c.cve_id}`}
      data-testid={`cve-card-${c.cve_id}`}
      className={`group relative block rounded-2xl border bg-white p-5 transition-all hover:shadow-lg hover:-translate-y-0.5 ${meta.border} border-l-4`}
      style={{ borderLeftColor: undefined }}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="font-mono text-sm font-bold text-[#0a2350]" data-testid={`cve-id-${c.cve_id}`}>
            {c.cve_id}
          </span>
          {c.is_new && (
            <span className="text-[10px] font-extrabold uppercase tracking-wider px-1.5 py-0.5 rounded bg-[#f5b120] text-[#0a2350]" data-testid={`cve-new-${c.cve_id}`}>
              New
            </span>
          )}
          {c.has_exploit_ref && (
            <span className="inline-flex items-center gap-1 text-[10px] font-bold px-1.5 py-0.5 rounded bg-red-100 text-red-700">
              <Flame className="h-3 w-3" /> Exploit ref
            </span>
          )}
        </div>
        <span className={`shrink-0 text-[10px] font-extrabold uppercase tracking-wider px-2 py-1 rounded-md ${meta.chip}`}>
          {meta.label}
        </span>
      </div>

      <p className="mt-3 text-sm leading-relaxed text-slate-600 line-clamp-3">{desc}</p>

      <div className="mt-4 flex flex-wrap items-center gap-2">
        {c.cvss_score != null && (
          <span className={`inline-flex items-baseline gap-1 rounded-lg px-2 py-1 ${meta.chip}`}>
            <span className="text-sm font-extrabold">{c.cvss_score.toFixed(1)}</span>
            <span className="text-[10px] font-bold opacity-80">CVSS {c.cvss_version}</span>
          </span>
        )}
        {(c.cwes || []).slice(0, 2).map((w) => (
          <span key={w} className="text-[10px] font-mono px-1.5 py-1 rounded bg-slate-100 text-slate-600 border border-slate-200">{w}</span>
        ))}
      </div>

      <div className="mt-4 flex items-center justify-between border-t border-slate-100 pt-3 text-[11px] text-slate-500">
        <span className="inline-flex items-center gap-1.5">
          <Clock className="h-3 w-3" /> {fmtDate(c.published)}
          {ageLabel(c.published) && <span className="text-slate-400">· {ageLabel(c.published)}</span>}
        </span>
        <span className="inline-flex items-center gap-1 font-semibold text-[#0a2350] opacity-0 group-hover:opacity-100 transition-opacity">
          Detail <ArrowUpRight className="h-3 w-3" />
        </span>
      </div>
    </Link>
  );
};

const FaqItem = ({ q, a }) => {
  const [open, setOpen] = useState(false);
  return (
    <div className="border-b border-slate-200 last:border-0">
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center justify-between gap-4 py-4 text-left"
        data-testid="cve-faq-toggle"
      >
        <span className="text-sm font-bold text-[#0a2350]">{q}</span>
        <ChevronDown className={`h-4 w-4 shrink-0 text-slate-400 transition-transform ${open ? "rotate-180" : ""}`} />
      </button>
      {open && <p className="pb-4 text-sm leading-relaxed text-slate-600">{a}</p>}
    </div>
  );
};

const FAQS = [
  {
    q: "What is a CVE and why does it matter?",
    a: "CVE (Common Vulnerabilities and Exposures) is a standardised identifier for a publicly known security flaw in software or hardware. Each entry carries a unique ID, a description, a severity score and vendor references — which is what lets a security team prioritise patching instead of guessing.",
  },
  {
    q: "How often is this data refreshed?",
    a: "The catalogue syncs automatically from the NVD API 2.0 every two hours. Each sync run advances a persisted cursor, so the index keeps filling even across backend restarts, and the timestamp at the top of the page shows exactly when the data last landed.",
  },
  {
    q: "What do the CVSS severity bands mean?",
    a: "NVD scores runs from 0.0 to 10.0. Critical is 9.0–10.0, High is 7.0–8.9, Medium is 4.0–6.9 and Low is 0.1–3.9. We always display the NVD (Primary) score first; when a CNA published a different score, the detailed page shows both so you can see the disagreement.",
  },
  {
    q: "Where does the data come from?",
    a: "Directly from the National Vulnerability Database API 2.0 operated by NIST. We store the full NVD record — description, CVSS metrics, CWEs, CPE product matches and references — and never editorialise the severity.",
  },
  {
    q: "Can I use this to monitor my own stack?",
    a: "Yes. Search by product or CVE ID, or filter to Critical plus the last 7 days for a triage feed. INTERCLOUD managed customers also receive patch guidance as part of the managed security service — contact your account manager for onboarding.",
  },
];

// ----------------------------------------------------------------- page ----
const CveTracker = () => {
  const [params, setParams] = useSearchParams();
  const severity = params.get("severity") || "";
  const sort = params.get("sort") || "newest";
  const q = params.get("q") || "";
  const days = Number(params.get("days") || 0);

  const [stats, setStats] = useState(null);
  const [rows, setRows] = useState(null);
  const [total, setTotal] = useState(0);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState("");
  const [input, setInput] = useState(q);
  const reqId = useRef(0);

  const query = useMemo(() => {
    const p = new URLSearchParams();
    if (severity) p.set("severity", severity);
    if (sort && sort !== "newest") p.set("sort", sort);
    if (q) p.set("q", q);
    if (days) p.set("days", String(days));
    return p.toString();
  }, [severity, sort, q, days]);

  const loadStats = useCallback(() => {
    fetch(`${API}/public/cve/stats?days=${days || 7}`)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then(setStats)
      .catch(() => setStats(null));
  }, [days]);

  useEffect(() => { loadStats(); }, [loadStats]);

  // First page: reset the list whenever a filter changes.
  useEffect(() => {
    const id = ++reqId.current;
    setRows(null);
    setError("");
    fetch(`${API}/public/cve?limit=${PAGE_SIZE}&skip=0&${query}`)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then((d) => {
        if (id !== reqId.current) return;
        setRows(d.results || []);
        setTotal(d.total || 0);
      })
      .catch((e) => {
        if (id !== reqId.current) return;
        setError(e.message || "Failed to load CVE feed");
        setRows([]);
      });
  }, [query]);

  const loadMore = async () => {
    if (loadingMore || !rows || rows.length >= total) return;
    setLoadingMore(true);
    const id = reqId.current;
    try {
      const r = await fetch(`${API}/public/cve?limit=${PAGE_SIZE}&skip=${rows.length}&${query}`);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const d = await r.json();
      if (id !== reqId.current) return;
      // Dedup by CVE id: NVD can insert an entry between two page fetches and
      // shift the offset, which would otherwise render a duplicate card.
      setRows((prev) => {
        const seen = new Set((prev || []).map((x) => x.cve_id));
        return [...(prev || []), ...(d.results || []).filter((x) => !seen.has(x.cve_id))];
      });
      setTotal(d.total || 0);
    } catch (e) {
      setError(e.message || "Failed to load more");
    } finally {
      setLoadingMore(false);
    }
  };

  const apply = (patch) => {
    const next = new URLSearchParams(params);
    Object.entries(patch).forEach(([k, v]) => {
      if (v) next.set(k, String(v)); else next.delete(k);
    });
    setParams(next);
  };

  const submitSearch = (e) => {
    e.preventDefault();
    apply({ q: input.trim() });
  };

  const counts = stats?.counts || {};
  const delta = stats?.trend?.delta_pct;
  const shown = rows ? rows.length : 0;

  return (
    <div className="min-h-screen bg-slate-50">
      <Helmet>
        <title>CVE Intelligence Hub — INTERCLOUD</title>
        <meta name="description" content="Real-time CVE tracker powered by the NIST NVD API 2.0. Filter by severity, sort by CVSS, and track newly published vulnerabilities." />
        <link rel="canonical" href="https://intercloud-digital.com/cve" />
        <meta property="og:title" content="CVE Intelligence Hub — INTERCLOUD" />
        <meta property="og:description" content="Real-time CVE tracker powered by the NIST NVD API 2.0." />
        <meta property="og:url" content="https://intercloud-digital.com/cve" />
      </Helmet>
      <Header />

      <main className="pt-24 pb-20">
        {/* Hero */}
        <section className="bg-[#0a2350] text-white">
          <div className="max-w-6xl mx-auto px-6 py-14 md:py-16">
            <div className="flex flex-wrap items-center gap-3">
              <div className="inline-flex h-12 w-12 items-center justify-center rounded-2xl bg-[#f5b120] text-[#0a2350]">
                <ShieldAlert className="h-6 w-6" />
              </div>
              <div>
                <h1 className="text-3xl sm:text-4xl lg:text-5xl font-extrabold leading-tight">
                  CVE Intelligence Hub
                </h1>
                <p className="mt-1 text-sm text-white/60">
                  Powered by NVD API 2.0 · curated by PT Intercloud Digital Inovasi
                </p>
              </div>
            </div>

            <div className="mt-8 flex flex-wrap items-center gap-3">
              <span className="inline-flex items-center gap-1.5 rounded-full bg-white/10 border border-white/20 px-3 py-1.5 text-[11px] font-bold uppercase tracking-widest">
                <RefreshCw className={`h-3 w-3 ${stats?.last_sync_at ? "" : "opacity-50"}`} />
                Auto-sync every 2 hours
              </span>
              {stats?.last_sync_at && (
                <span className="inline-flex items-center gap-1.5 rounded-full bg-white/10 border border-white/20 px-3 py-1.5 text-[11px] text-white/70" data-testid="cve-last-sync">
                  <Clock className="h-3 w-3" /> Last sync {fmtDateTime(stats.last_sync_at)}
                </span>
              )}
              {stats?.stored_total > 0 && (
                <span className="inline-flex items-center gap-1.5 rounded-full bg-white/10 border border-white/20 px-3 py-1.5 text-[11px] text-white/70" data-testid="cve-stored-total">
                  <Database className="h-3 w-3" /> {Number(stats.stored_total).toLocaleString()} CVEs indexed
                </span>
              )}
            </div>
          </div>
        </section>

        {/* Stat cards */}
        <section className="max-w-6xl mx-auto px-6 -mt-8">
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
            <StatCard
              title={`Critical · last ${days || 7}d`} value={stats ? counts.critical : null}
              icon={AlertTriangle} testid="stat-critical"
              tone={{ border: "border-red-200", bg: "bg-red-50", text: "text-red-600" }}
              delta={delta}
            />
            <StatCard
              title={`High · last ${days || 7}d`} value={stats ? counts.high : null}
              icon={Flame} testid="stat-high"
              tone={{ border: "border-orange-200", bg: "bg-orange-50", text: "text-orange-600" }}
            />
            <StatCard
              title={`Medium · last ${days || 7}d`} value={stats ? counts.medium : null}
              icon={ShieldAlert} testid="stat-medium"
              tone={{ border: "border-amber-200", bg: "bg-amber-50", text: "text-amber-600" }}
            />
            <StatCard
              title={`Total · last ${days || 7}d`} value={stats ? stats.window_total : null}
              icon={Database} testid="stat-total"
              tone={{ border: "border-slate-200", bg: "bg-slate-100", text: "text-[#0a2350]" }}
            />
          </div>
        </section>

        {/* Search + filters */}
        <section className="max-w-6xl mx-auto px-6 mt-10">
          <form onSubmit={submitSearch} className="flex items-center gap-2">
            <div className="flex-1 flex items-center gap-3 h-12 rounded-xl bg-white border border-slate-200 px-4 focus-within:border-[#f5b120]">
              <Search className="h-4 w-4 text-slate-400" />
              <input
                value={input}
                onChange={(e) => setInput(e.target.value)}
                placeholder="Search CVE ID, product or keyword — e.g. CVE-2024-3094 or apache"
                className="flex-1 bg-transparent outline-none text-sm text-slate-700 placeholder-slate-400"
                data-testid="cve-search-input"
              />
            </div>
            <button
              type="submit"
              className="h-12 px-6 rounded-xl bg-[#0a2350] hover:bg-[#f5b120] hover:text-[#0a2350] text-white font-bold text-sm transition-colors"
              data-testid="cve-search-btn"
            >
              Search
            </button>
          </form>

          <div className="mt-4 flex flex-wrap items-center gap-2">
            {SEVERITY_FILTERS.map((f) => {
              const active = severity === f.key;
              return (
                <button
                  key={f.key || "all"}
                  onClick={() => apply({ severity: f.key })}
                  data-testid={`cve-filter-${f.key || "all"}`}
                  className={`h-9 px-4 rounded-full text-xs font-bold border transition-colors ${
                    active
                      ? "bg-[#0a2350] text-white border-[#0a2350]"
                      : "bg-white text-slate-600 border-slate-200 hover:border-[#f5b120]"
                  }`}
                >
                  {f.label}
                </button>
              );
            })}
            <span className="mx-1 h-6 w-px bg-slate-200" />
            {SORT_FILTERS.map((f) => {
              const active = sort === f.key;
              return (
                <button
                  key={f.key}
                  onClick={() => apply({ sort: f.key === "newest" ? "" : f.key })}
                  data-testid={`cve-sort-${f.key}`}
                  className={`h-9 px-4 rounded-full text-xs font-bold border transition-colors ${
                    active
                      ? "bg-[#f5b120] text-[#0a2350] border-[#f5b120]"
                      : "bg-white text-slate-600 border-slate-200 hover:border-[#f5b120]"
                  }`}
                >
                  {f.label}
                </button>
              );
            })}
            <span className="mx-1 h-6 w-px bg-slate-200" />
            <button
              onClick={() => apply({ days: days === 7 ? "" : "7" })}
              data-testid="cve-filter-7d"
              className={`h-9 px-4 rounded-full text-xs font-bold border transition-colors ${
                days === 7
                  ? "bg-[#0a2350] text-white border-[#0a2350]"
                  : "bg-white text-slate-600 border-slate-200 hover:border-[#f5b120]"
              }`}
            >
              Last 7 days
            </button>
            {(severity || sort !== "newest" || q || days) && (
              <button
                onClick={() => { setInput(""); setParams(new URLSearchParams()); }}
                className="h-9 px-3 rounded-full text-xs font-semibold text-slate-500 hover:text-[#0a2350] underline"
                data-testid="cve-clear"
              >
                Clear
              </button>
            )}
          </div>
        </section>

        {/* Feed */}
        <section className="max-w-6xl mx-auto px-6 mt-8">
          <div className="mb-4 flex items-center justify-between text-sm text-slate-500">
            <span data-testid="cve-results-count">
              {rows === null ? "Loading…" : `${shown.toLocaleString()} of ${total.toLocaleString()} matching CVEs`}
            </span>
            {q && <span className="text-xs">filtered by “{q}”</span>}
          </div>

          {error && (
            <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700" data-testid="cve-error">
              {error}
            </div>
          )}

          {rows === null && !error && (
            <div className="py-24 flex justify-center" data-testid="cve-loading">
              <Loader2 className="h-7 w-7 text-[#0a2350] animate-spin" />
            </div>
          )}

          {rows && rows.length === 0 && !error && (
            <div className="py-24 text-center" data-testid="cve-empty">
              <ShieldAlert className="h-10 w-10 text-slate-300 mx-auto" />
              <div className="mt-3 text-lg font-extrabold text-[#0a2350]">No CVEs match these filters</div>
              <p className="mt-1 text-sm text-slate-500">
                The index may still be filling, or the filter is too narrow. Try clearing it.
              </p>
            </div>
          )}

          {rows && rows.length > 0 && (
            <div className="grid md:grid-cols-2 gap-4">
              {rows.map((c) => <CveCard key={c.cve_id} c={c} />)}
            </div>
          )}

          {rows && rows.length > 0 && shown < total && (
            <div className="mt-8 flex justify-center">
              <button
                onClick={loadMore}
                disabled={loadingMore}
                data-testid="cve-load-more"
                className="inline-flex items-center gap-2 h-12 px-8 rounded-full bg-[#0a2350] text-white font-bold text-sm hover:bg-[#f5b120] hover:text-[#0a2350] transition-colors disabled:opacity-60"
              >
                {loadingMore ? <Loader2 className="h-4 w-4 animate-spin" /> : <ChevronRight className="h-4 w-4" />}
                {loadingMore ? "Loading…" : `Load More CVEs (${(total - shown).toLocaleString()} left)`}
              </button>
            </div>
          )}
        </section>

        {/* FAQ */}
        <section className="max-w-3xl mx-auto px-6 mt-20">
          <h2 className="text-2xl font-extrabold text-[#0a2350]">Frequently Asked Questions</h2>
          <div className="mt-4 rounded-2xl border border-slate-200 bg-white px-6">
            {FAQS.map((f) => <FaqItem key={f.q} q={f.q} a={f.a} />)}
          </div>

          <div className="mt-10 rounded-2xl bg-[#0a2350] p-8 text-white">
            <h3 className="text-xl font-extrabold">Need help triaging these across your estate?</h3>
            <p className="mt-2 text-sm text-white/70 leading-relaxed">
              INTERCLOUD monitors, patches and reports on the CVEs that actually affect your
              infrastructure — not the whole catalogue. Talk to us about managed security.
            </p>
            <Link
              to="/#contact"
              className="mt-5 inline-flex items-center gap-2 rounded-full bg-[#f5b120] px-6 h-11 text-sm font-bold text-[#0a2350] hover:bg-[#ffcc4d] transition-colors"
            >
              Contact us <ExternalLink className="h-4 w-4" />
            </Link>
          </div>
        </section>
      </main>
      <Footer />
    </div>
  );
};

export default CveTracker;
