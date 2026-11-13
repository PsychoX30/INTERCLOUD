import React, { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { Helmet } from "react-helmet-async";
import {
  ArrowLeft, ExternalLink, Loader2, ShieldAlert, Flame, Clock, Tag,
  Server, Link2, AlertTriangle,
} from "lucide-react";
import Header from "../components/Header";
import Footer from "../components/Footer";

const BASE = (process.env.REACT_APP_BACKEND_URL || "").replace(/\/$/, "");
const API = `${BASE}/api/portal`;

const SEV = {
  critical: { label: "Critical", chip: "bg-red-600 text-white", text: "text-red-700", bg: "bg-red-50 border-red-200" },
  high:     { label: "High",     chip: "bg-orange-500 text-white", text: "text-orange-700", bg: "bg-orange-50 border-orange-200" },
  medium:   { label: "Medium",   chip: "bg-amber-400 text-[#0a2350]", text: "text-amber-700", bg: "bg-amber-50 border-amber-200" },
  low:      { label: "Low",      chip: "bg-sky-500 text-white", text: "text-sky-700", bg: "bg-sky-50 border-sky-200" },
  none:     { label: "None",     chip: "bg-slate-400 text-white", text: "text-slate-600", bg: "bg-slate-50 border-slate-200" },
  unknown:  { label: "Unscored", chip: "bg-slate-400 text-white", text: "text-slate-600", bg: "bg-slate-50 border-slate-200" },
};
const sevMeta = (s) => SEV[String(s || "unknown").toLowerCase()] || SEV.unknown;

const fmtDateTime = (iso) => {
  if (!iso) return "-";
  try {
    return new Date(iso).toLocaleString("en-GB", {
      day: "2-digit", month: "short", year: "numeric", hour: "2-digit",
      minute: "2-digit", timeZone: "UTC",
    }) + " UTC";
  } catch { return "-"; }
};

const MetricRow = ({ label, value }) => (
  <div className="flex items-start justify-between gap-4 py-2 border-b border-slate-100 last:border-0">
    <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</span>
    <span className="text-sm text-[#0a2350] text-right break-all">{value || "—"}</span>
  </div>
);

const CveDetail = () => {
  const { cveId } = useParams();
  const [d, setD] = useState(null);
  const [error, setError] = useState("");
  const [notFound, setNotFound] = useState(false);

  useEffect(() => {
    let alive = true;
    setD(null); setError(""); setNotFound(false);
    fetch(`${API}/public/cve/${encodeURIComponent(cveId)}`)
      .then(async (r) => {
        if (r.status === 404) { if (alive) setNotFound(true); return null; }
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then((j) => { if (alive && j) setD(j); })
      .catch((e) => { if (alive) setError(e.message || "Failed to load CVE"); });
    return () => { alive = false; };
  }, [cveId]);

  const meta = sevMeta(d?.severity);
  const desc = d?.description || "";

  return (
    <div className="min-h-screen bg-slate-50">
      <Helmet>
        <title>{d ? `${d.cve_id} — ${meta.label} — INTERCLOUD CVE Hub` : `${cveId} — INTERCLOUD CVE Hub`}</title>
        <meta name="description" content={desc.slice(0, 300)} />
        <link rel="canonical" href={`https://intercloud-digital.com/cve/${cveId}`} />
        <meta property="og:title" content={d ? `${d.cve_id} — ${meta.label}` : `${cveId}`} />
        <meta property="og:description" content={desc.slice(0, 300)} />
      </Helmet>
      <Header />

      <main className="pt-24 pb-20">
        <section className="bg-[#0a2350] text-white">
          <div className="max-w-5xl mx-auto px-6 py-12">
            <Link to="/cve" className="inline-flex items-center gap-2 text-xs font-bold uppercase tracking-widest text-white/60 hover:text-[#f5b120]" data-testid="cve-back">
              <ArrowLeft className="h-3.5 w-3.5" /> All CVEs
            </Link>

            <div className="mt-5 flex flex-wrap items-center gap-3">
              <h1 className="font-mono text-2xl sm:text-3xl lg:text-4xl font-extrabold break-all" data-testid="cve-detail-id">
                {d?.cve_id || cveId}
              </h1>
              {d && (
                <span className={`text-[11px] font-extrabold uppercase tracking-wider px-2.5 py-1 rounded-md ${meta.chip}`} data-testid="cve-detail-severity">
                  {meta.label}
                </span>
              )}
              {d?.is_new && (
                <span className="text-[11px] font-extrabold uppercase tracking-wider px-2.5 py-1 rounded bg-[#f5b120] text-[#0a2350]">New</span>
              )}
              {d?.has_exploit_ref && (
                <span className="inline-flex items-center gap-1 text-[11px] font-bold px-2.5 py-1 rounded bg-red-500/20 text-red-200 border border-red-400/40">
                  <Flame className="h-3 w-3" /> Exploit reference available
                </span>
              )}
            </div>

            {d?.cvss_score != null && (
              <div className="mt-5 flex items-baseline gap-2">
                <span className="text-5xl font-extrabold text-[#f5b120]" data-testid="cve-detail-score">
                  {d.cvss_score.toFixed(1)}
                </span>
                <span className="text-sm text-white/60">CVSS {d.cvss_version} · {d.cvss_source || "NVD"}</span>
              </div>
            )}
          </div>
        </section>

        <section className="max-w-5xl mx-auto px-6 -mt-6">
          {notFound && (
            <div className="rounded-2xl border border-slate-200 bg-white p-10 text-center" data-testid="cve-detail-notfound">
              <ShieldAlert className="h-10 w-10 text-slate-300 mx-auto" />
              <div className="mt-3 text-lg font-extrabold text-[#0a2350]">CVE not in the index</div>
              <p className="mt-1 text-sm text-slate-500">
                {cveId} has not been synced yet. The catalogue fills in on a 2-hour interval.
              </p>
              <Link to="/cve" className="mt-5 inline-flex items-center gap-2 rounded-full bg-[#0a2350] px-5 h-10 text-sm font-bold text-white hover:bg-[#f5b120] hover:text-[#0a2350]">
                Back to the hub
              </Link>
            </div>
          )}

          {error && (
            <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700" data-testid="cve-detail-error">
              {error}
            </div>
          )}

          {!d && !error && !notFound && (
            <div className="py-24 flex justify-center" data-testid="cve-detail-loading">
              <Loader2 className="h-7 w-7 text-[#0a2350] animate-spin" />
            </div>
          )}

          {d && (
            <div className="grid lg:grid-cols-3 gap-6">
              <div className="lg:col-span-2 space-y-6">
                <article className="rounded-2xl border border-slate-200 bg-white p-6">
                  <h2 className="text-xs font-extrabold uppercase tracking-widest text-slate-500">Description</h2>
                  <p className="mt-3 text-[15px] leading-relaxed text-slate-700 whitespace-pre-line" data-testid="cve-detail-description">
                    {d.description || "No English description was published for this entry."}
                  </p>
                </article>

                {d.cvss_vector && (
                  <article className="rounded-2xl border border-slate-200 bg-white p-6">
                    <h2 className="text-xs font-extrabold uppercase tracking-widest text-slate-500">CVSS Vector</h2>
                    <code className="mt-3 block rounded-lg bg-slate-50 border border-slate-200 p-3 text-xs text-slate-700 break-all font-mono">
                      {d.cvss_vector}
                    </code>
                    {(d.cvss_all || []).length > 1 && (
                      <div className="mt-4 space-y-2">
                        <div className="text-xs font-semibold text-slate-500">All scores on record</div>
                        {(d.cvss_all || []).map((m, i) => (
                          <div key={i} className="flex items-center justify-between rounded-lg border border-slate-200 px-3 py-2 text-xs">
                            <span className="font-mono text-slate-600">{m.source || "unknown"} · v{m.version}</span>
                            <span className={`font-extrabold ${sevMeta(m.severity).text}`}>{m.score.toFixed(1)} {m.severity}</span>
                          </div>
                        ))}
                      </div>
                    )}
                  </article>
                )}

                <article className="rounded-2xl border border-slate-200 bg-white p-6">
                  <h2 className="flex items-center gap-2 text-xs font-extrabold uppercase tracking-widest text-slate-500">
                    <Link2 className="h-3.5 w-3.5" /> References ({(d.references || []).length})
                  </h2>
                  {(d.references || []).length === 0 && (
                    <p className="mt-3 text-sm text-slate-500">NVD published no external references for this entry.</p>
                  )}
                  <ul className="mt-3 space-y-2">
                    {(d.references || []).map((r, i) => (
                      <li key={`${r.url}-${i}`}>
                        <a
                          href={r.url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="group flex items-start gap-2 rounded-lg border border-slate-200 p-3 hover:border-[#f5b120]"
                        >
                          <ExternalLink className="mt-0.5 h-3.5 w-3.5 shrink-0 text-slate-400 group-hover:text-[#0a2350]" />
                          <span className="min-w-0">
                            <span className="block truncate text-sm text-[#0a2350] group-hover:underline">{r.url}</span>
                            <span className="mt-1 flex flex-wrap gap-1">
                              {(r.tags || []).map((t) => (
                                <span key={t} className="text-[10px] px-1.5 py-0.5 rounded bg-slate-100 border border-slate-200 text-slate-600">{t}</span>
                              ))}
                            </span>
                          </span>
                        </a>
                      </li>
                    ))}
                  </ul>
                </article>
              </div>

              <aside className="space-y-6">
                <div className={`rounded-2xl border p-6 ${meta.bg}`}>
                  <div className="flex items-center gap-2">
                    <AlertTriangle className={`h-4 w-4 ${meta.text}`} />
                    <span className="text-xs font-extrabold uppercase tracking-widest text-slate-600">Severity</span>
                  </div>
                  <div className={`mt-2 text-2xl font-extrabold ${meta.text}`}>{meta.label}</div>
                  {d.cvss_score != null && (
                    <div className="mt-1 text-sm text-slate-600">Base score {d.cvss_score.toFixed(1)}</div>
                  )}
                </div>

                <div className="rounded-2xl border border-slate-200 bg-white p-6">
                  <h2 className="text-xs font-extrabold uppercase tracking-widest text-slate-500">Timeline</h2>
                  <div className="mt-2">
                    <MetricRow label="Published" value={fmtDateTime(d.published)} />
                    <MetricRow label="Last modified" value={fmtDateTime(d.last_modified)} />
                    <MetricRow label="Status" value={d.vuln_status} />
                  </div>
                </div>

                {(d.cwes || []).length > 0 && (
                  <div className="rounded-2xl border border-slate-200 bg-white p-6">
                    <h2 className="flex items-center gap-2 text-xs font-extrabold uppercase tracking-widest text-slate-500">
                      <Tag className="h-3.5 w-3.5" /> Weaknesses
                    </h2>
                    <div className="mt-3 flex flex-wrap gap-1.5">
                      {d.cwes.map((w) => (
                        <span key={w} className="text-xs font-mono px-2 py-1 rounded bg-slate-100 border border-slate-200 text-slate-700">{w}</span>
                      ))}
                    </div>
                  </div>
                )}

                {(d.products || []).length > 0 && (
                  <div className="rounded-2xl border border-slate-200 bg-white p-6">
                    <h2 className="flex items-center gap-2 text-xs font-extrabold uppercase tracking-widest text-slate-500">
                      <Server className="h-3.5 w-3.5" /> Affected products
                    </h2>
                    <div className="mt-3 flex flex-wrap gap-1.5">
                      {d.products.map((p) => (
                        <span key={p} className="text-xs font-mono px-2 py-1 rounded bg-slate-100 border border-slate-200 text-slate-700">{p}</span>
                      ))}
                    </div>
                  </div>
                )}

                <div className="rounded-2xl border border-slate-200 bg-white p-6">
                  <h2 className="text-xs font-extrabold uppercase tracking-widest text-slate-500">Source</h2>
                  <div className="mt-2">
                    <MetricRow label="Assigner" value={d.source_identifier} />
                    <MetricRow label="CVSS source" value={d.cvss_source} />
                    <MetricRow label="Indexed" value={fmtDateTime(d.fetched_at)} />
                  </div>
                  <a
                    href={`https://nvd.nist.gov/vuln/detail/${d.cve_id}`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="mt-4 inline-flex items-center gap-1.5 text-xs font-bold text-[#0a2350] hover:text-[#f5b120]"
                  >
                    Open on NVD <ExternalLink className="h-3 w-3" />
                  </a>
                </div>
              </aside>
            </div>
          )}
        </section>
      </main>
      <Footer />
    </div>
  );
};

export default CveDetail;
