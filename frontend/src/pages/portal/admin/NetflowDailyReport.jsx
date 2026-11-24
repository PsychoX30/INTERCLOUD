import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Activity, ArrowDownToLine, ArrowUpFromLine, Globe2, HelpCircle, MapPin,
  RefreshCw, Radio, AlertTriangle, ChevronDown, Search, ExternalLink,
  ShieldQuestion, Layers, Network,
} from "lucide-react";
import { api } from "../../../portal/api";
import { Card } from "../ui";

// DAILY FLOW REPORT - the NOC netflow surface.
//
// This replaces the Source -> Destination Sankey. The Sankey was not broken by
// a bug; it was fed the wrong thing. Its only source was the goflow2
// collector's tail, which is a ~50 second rolling window (measured on
// production 2026-11-24: 142,709 records spanning 49.3 s). Ranking the top-12
// (src,dst) pairs out of thousands inside a few seconds produces a *different*
// random sample on every refresh, so the diagram appeared to lose its links
// every 30 s. A report with real hourly history is the honest answer.
//
// Every number here carries its provenance:
//   * `source: "rollup"`   - aggregated from every flow record, exact
//   * `source: "backfill"` - rebuilt from flow_samples (top-50 links/min), a
//                            lower bound, drawn with a hatch
//   * `source: "none"`     - no data; drawn as an empty slot, never as zero
//   * `partial: true`      - the hour is still running, or the aggregator only
//                            started part-way through it
// A dip in the chart is therefore always either real or labelled.

const fmtBytes = (b) => {
  const v = Number(b) || 0;
  if (v >= 1e12) return `${(v / 1e12).toFixed(2)} TB`;
  if (v >= 1e9) return `${(v / 1e9).toFixed(2)} GB`;
  if (v >= 1e6) return `${(v / 1e6).toFixed(1)} MB`;
  if (v >= 1e3) return `${(v / 1e3).toFixed(1)} KB`;
  return `${Math.round(v)} B`;
};

const fmtBps = (bps) => {
  const v = Number(bps) || 0;
  if (v >= 1e12) return `${(v / 1e12).toFixed(2)} Tbps`;
  if (v >= 1e9) return `${(v / 1e9).toFixed(2)} Gbps`;
  if (v >= 1e6) return `${(v / 1e6).toFixed(1)} Mbps`;
  if (v >= 1e3) return `${(v / 1e3).toFixed(1)} Kbps`;
  return `${Math.round(v)} bps`;
};

const fmtPct = (s, digits = 1) => `${((Number(s) || 0) * 100).toFixed(digits)}%`;

// The server reports hours in UTC; the operator reads them in WIB. Formatting
// happens here so the API stays timezone-free.
const hourLabel = (iso) => {
  if (!iso) return "-";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "-";
  return `${String(d.getHours()).padStart(2, "0")}:00`;
};
const dayLabel = (iso) => {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleDateString(undefined, { day: "2-digit", month: "short" });
};

const asLabel = (row) => {
  // A tail row is not an unresolved network: it is the sum of every peer below
  // the write cap. Saying "AS tidak dikenal" for it would blame bgp.tools for a
  // limit this report chose, so it is named as an aggregate instead.
  if (row?.tail) return "peer lain (di luar 400 teratas per jam)";
  const name = row?.as_name || null;
  if (row?.asn && name) return `AS${row.asn} · ${name}`;
  if (row?.asn) return `AS${row.asn}`;
  return "AS tidak dikenal";
};

const flagOf = (cc) => {
  if (!cc || cc.length !== 2) return null;
  const base = 0x1f1e6;
  return String.fromCodePoint(
    base + (cc.toUpperCase().charCodeAt(0) - 65),
    base + (cc.toUpperCase().charCodeAt(1) - 65),
  );
};

const geoName = (cc) => {
  if (!cc) return "unknown";
  try {
    return new Intl.DisplayNames(["id"], { type: "region" }).of(cc) || cc;
  } catch {
    return cc;
  }
};

// ---------------------------------------------------------------------------
// primitives
// ---------------------------------------------------------------------------

const Sparkline = ({ data, color = "#0a2350", height = 34, width = 220, fill = true }) => {
  const vals = (data || []).map((v) => Number(v) || 0);
  if (vals.length < 2) return <div style={{ height }} />;
  const max = Math.max(...vals, 1e-9);
  const step = width / (vals.length - 1);
  const pts = vals.map((v, i) => [i * step, height - (v / max) * (height - 4) - 2]);
  const line = pts.map((p, i) => `${i ? "L" : "M"}${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(" ");
  const area = `${line} L${width},${height} L0,${height} Z`;
  const gid = `sg-${color.replace(/[^a-z0-9]/gi, "")}-${height}`;
  return (
    <svg viewBox={`0 0 ${width} ${height}`} width="100%" height={height} preserveAspectRatio="none"
         role="img" aria-hidden="true">
      <defs>
        <linearGradient id={gid} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity="0.28" />
          <stop offset="100%" stopColor={color} stopOpacity="0.02" />
        </linearGradient>
      </defs>
      {fill && <path d={area} fill={`url(#${gid})`} />}
      <path d={line} fill="none" stroke={color} strokeWidth="1.6"
            strokeLinejoin="round" strokeLinecap="round" />
    </svg>
  );
};

const MiniBars = ({ data, color = "#0a2350", height = 26, width = 120 }) => {
  const vals = (data || []).map((v) => Number(v) || 0);
  if (!vals.length) return <div style={{ height }} />;
  const max = Math.max(...vals, 1e-9);
  const bw = width / vals.length;
  return (
    <svg viewBox={`0 0 ${width} ${height}`} width="100%" height={height}
         preserveAspectRatio="none" aria-hidden="true">
      {vals.map((v, i) => {
        const h = Math.max(1, (v / max) * (height - 3));
        return <rect key={i} x={i * bw + 0.5} y={height - h} width={Math.max(1, bw - 1)}
                     height={h} fill={color} opacity={0.35 + 0.6 * (v / max)} rx="0.5" />;
      })}
    </svg>
  );
};

const Metric = ({ label, value, sub, Icon, tone = "default", testid }) => {
  const tones = {
    default: "text-[#0a2350]",
    in: "text-emerald-600",
    out: "text-sky-600",
    warn: "text-amber-600",
  };
  return (
    <div className="rounded-xl border border-slate-200 bg-white px-4 py-3" data-testid={testid}>
      <div className="flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-widest text-slate-500">
        {Icon && <Icon className="h-3 w-3" />} {label}
      </div>
      <div className={`mt-1 text-xl font-black tabular-nums ${tones[tone] || tones.default}`}>{value}</div>
      {sub && <div className="text-[11px] text-slate-500 mt-0.5 truncate" title={sub}>{sub}</div>}
    </div>
  );
};

// Honest bucket fill: solid = exact rollup, hatched = backfilled lower bound,
// hollow = no data, dashed outline = hour still in progress.
const bucketStyle = (b) => {
  if (b.source === "none") return { fill: "url(#nf-empty)", stroke: "#e2e8f0", dash: null };
  if (b.source === "backfill") return { fill: "url(#nf-backfill)", stroke: "#94a3b8", dash: "3 3" };
  if (b.partial) return { fill: "#0a2350", stroke: "#0a2350", dash: "4 3" };
  return { fill: "#0a2350", stroke: "#0a2350", dash: null };
};

const DailyChart = ({ buckets, height = 190 }) => {
  const [hover, setHover] = useState(null);
  const w = 1000;
  const vals = buckets.flatMap((b) => [b.in_bps || 0, b.out_bps || 0]);
  const max = Math.max(...vals, 1e-9);
  const n = Math.max(1, buckets.length);
  const slot = w / n;
  const barW = Math.max(2, slot * 0.34);

  return (
    <div className="relative">
      <svg viewBox={`0 0 ${w} ${height}`} width="100%" height={height}
           preserveAspectRatio="none" data-testid="netflow-chart">
        <defs>
          <pattern id="nf-backfill" width="6" height="6" patternUnits="userSpaceOnUse"
                   patternTransform="rotate(45)">
            <rect width="6" height="6" fill="#cbd5e1" />
            <line x1="0" y1="0" x2="0" y2="6" stroke="#94a3b8" strokeWidth="2" />
          </pattern>
          <pattern id="nf-empty" width="6" height="6" patternUnits="userSpaceOnUse">
            <rect width="6" height="6" fill="#f8fafc" />
          </pattern>
        </defs>
        {[0.25, 0.5, 0.75, 1].map((f) => (
          <line key={f} x1="0" x2={w} y1={height - f * (height - 16)} y2={height - f * (height - 16)}
                stroke="#e2e8f0" strokeWidth="1" strokeDasharray="2 4" />
        ))}
        {buckets.map((b, i) => {
          const x = i * slot;
          const hi = ((b.in_bps || 0) / max) * (height - 16);
          const ho = ((b.out_bps || 0) / max) * (height - 16);
          const si = bucketStyle(b);
          const so = bucketStyle(b);
          return (
            <g key={b.hour} onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)}>
              <rect x={x} y="0" width={slot} height={height} fill="transparent" />
              <rect x={x + slot / 2 - barW - 1} y={height - hi} width={barW} height={Math.max(hi, 1)}
                    fill={si.fill} stroke={si.stroke} strokeDasharray={si.dash || undefined}
                    strokeWidth="0.6" />
              <rect x={x + slot / 2 + 1} y={height - ho} width={barW} height={Math.max(ho, 1)}
                    fill={so.fill} opacity="0.55" stroke={so.stroke}
                    strokeDasharray={so.dash || undefined} strokeWidth="0.6" />
              {hover === i && (
                <rect x={x} y="0" width={slot} height={height} fill="#0a2350" opacity="0.05" />
              )}
            </g>
          );
        })}
      </svg>
      <div className="flex justify-between text-[10px] text-slate-400 mt-1 tabular-nums">
        {buckets.filter((_, i) => i % Math.max(1, Math.ceil(n / 8)) === 0).map((b) => (
          <span key={b.hour}>{hourLabel(b.hour)}</span>
        ))}
      </div>
      {hover != null && buckets[hover] && (
        <div className="absolute -top-1 right-0 rounded-lg border border-slate-200 bg-white shadow-lg px-3 py-2 text-[11px] z-20"
             data-testid="netflow-chart-tip">
          <div className="font-bold text-[#0a2350]">
            {dayLabel(buckets[hover].hour)} {hourLabel(buckets[hover].hour)} WIB
          </div>
          <div className="mt-1 flex items-center gap-2">
            <span className="h-2 w-2 rounded-sm bg-emerald-600" />
            <span className="text-slate-500">IN</span>
            <span className="font-mono font-semibold ml-auto">{fmtBps(buckets[hover].in_bps)}</span>
          </div>
          <div className="flex items-center gap-2">
            <span className="h-2 w-2 rounded-sm bg-sky-600" />
            <span className="text-slate-500">OUT</span>
            <span className="font-mono font-semibold ml-auto">{fmtBps(buckets[hover].out_bps)}</span>
          </div>
          <div className="mt-1 text-[10px] text-slate-500">
            {buckets[hover].source === "rollup" ? "agregat penuh"
              : buckets[hover].source === "backfill" ? "perkiraan bawah (top-50 link/menit)"
              : "tidak ada data"}
            {buckets[hover].partial ? " · jam belum selesai" : ""}
          </div>
        </div>
      )}
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 mt-2 text-[10px] text-slate-500">
        <span className="inline-flex items-center gap-1.5">
          <span className="h-2.5 w-2.5 rounded-sm bg-emerald-600" /> IN (download)
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="h-2.5 w-2.5 rounded-sm bg-sky-600 opacity-60" /> OUT (upload)
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="h-2.5 w-2.5 rounded-sm border border-slate-400"
                style={{ backgroundImage: "repeating-linear-gradient(45deg,#cbd5e1 0 2px,#fff 2px 4px)" }} />
          perkiraan bawah
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="h-2.5 w-2.5 rounded-sm border border-dashed border-[#0a2350]" /> jam berjalan
        </span>
      </div>
    </div>
  );
};

const PeerRow = ({ row, rank, testid }) => {
  const pct = Math.max(0.4, (row.share || 0) * 100);
  return (
    <div className="py-2 border-b border-slate-100 last:border-0" data-testid={testid}>
      <div className="flex items-baseline gap-2">
        <span className="text-[10px] font-black text-slate-300 w-5 shrink-0 tabular-nums">
          {String(rank).padStart(2, "0")}
        </span>
        <span className="font-mono text-xs font-bold text-[#0a2350] truncate">
          {row.tail ? "peer lain" : row.peer}
        </span>
        <span className="ml-auto font-mono text-xs font-bold text-[#0a2350] tabular-nums">
          {fmtBps(row.avg_bps)}
        </span>
      </div>
      <div className="flex items-center gap-2 mt-0.5 pl-5">
        <span className="text-[10px] text-slate-500 truncate" title={asLabel(row)}>
          {row.cc ? `${flagOf(row.cc)} ` : ""}{asLabel(row)}
        </span>
        <span className="ml-auto text-[10px] text-slate-400 tabular-nums shrink-0">
          {fmtBytes(row.bytes)} · {fmtPct(row.share)}
        </span>
      </div>
      <div className="mt-1 ml-5 h-1.5 rounded-full bg-slate-100 overflow-hidden">
        <div className="h-full rounded-full bg-[#f5b120]" style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
};

const BarRow = ({ label, sub, value, share, bytes, color = "#0a2350", testid }) => (
  <div className="py-1.5" data-testid={testid}>
    <div className="flex items-baseline gap-2 text-[11px]">
      <span className="font-mono font-bold text-[#0a2350] truncate">{label}</span>
      {sub && <span className="text-slate-400 truncate">{sub}</span>}
      <span className="ml-auto font-mono tabular-nums text-slate-600 shrink-0">
        {value || fmtPct(share)}
      </span>
    </div>
    <div className="mt-1 h-1.5 rounded-full bg-slate-100 overflow-hidden">
      <div className="h-full rounded-full" style={{ width: `${Math.max(0.6, (share || 0) * 100)}%`, background: color }} />
    </div>
    {bytes != null && <div className="text-[10px] text-slate-400 mt-0.5">{fmtBytes(bytes)}</div>}
  </div>
);

// ---------------------------------------------------------------------------
// main
// ---------------------------------------------------------------------------

export const NetflowDailyReport = ({ refreshMs = 60000 }) => {
  const [payload, setPayload] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [hours, setHours] = useState(24);
  const [prefix, setPrefix] = useState("");
  const [auto, setAuto] = useState(true);
  const [tabIn, setTabIn] = useState("as");
  const [lookupQ, setLookupQ] = useState("");
  const [lookup, setLookup] = useState(null);
  const [lookupBusy, setLookupBusy] = useState(false);
  // Keep the last good report across a failed poll: a transient API error is
  // not the same event as "the network went quiet", and blanking the panel on
  // one 500 would read as a traffic outage.
  const lastGood = useRef(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await api.get("/admin/noc/netflow/daily-report", {
        params: { hours, ...(prefix ? { prefix } : {}) },
      });
      if (data && data.ok) {
        lastGood.current = data;
        setPayload(data);
        setError(null);
        if (!prefix && data.prefix) setPrefix(data.prefix);
      } else {
        setError(data?.error || data?.hint || "Laporan tidak tersedia");
        if (lastGood.current) setPayload(lastGood.current);
      }
    } catch (e) {
      setError(e?.response?.data?.detail || e.message || "Gagal memuat laporan");
      if (lastGood.current) setPayload(lastGood.current);
    } finally {
      setLoading(false);
    }
  }, [hours, prefix]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    if (!auto) return undefined;
    const t = setInterval(load, refreshMs);
    return () => clearInterval(t);
  }, [auto, load, refreshMs]);

  const doLookup = useCallback(async () => {
    const q = lookupQ.trim();
    if (!q) return;
    setLookupBusy(true);
    try {
      const { data } = await api.get("/admin/noc/netflow/bgp-lookup", { params: { q } });
      setLookup(data);
    } catch (e) {
      setLookup({ ok: false, error: e?.response?.data?.detail || e.message });
    } finally {
      setLookupBusy(false);
    }
  }, [lookupQ]);

  const buckets = payload?.buckets || [];
  const totals = payload?.totals || {};
  const geo = payload?.geo || {};
  const coverage = payload?.coverage || {};
  const collector = coverage.collector || {};
  const errors = payload?.errors || [];

  const stale = collector.exists === false || (collector.file_age_s != null && collector.file_age_s > 300);
  const lagging = collector.rollup?.lag_s != null && collector.rollup.lag_s > 180;

  const topSources = payload?.top_sources || [];
  const topDest = payload?.top_destinations || [];
  const talkers = payload?.top_talkers || [];

  const geoTotal = useMemo(() => {
    const d = geo.domestic?.bytes || 0;
    const i = geo.international?.bytes || 0;
    const u = geo.unknown?.bytes || 0;
    return d + i + u;
  }, [geo]);

  const asByDirection = useMemo(() => {
    const rows = payload?.as_breakdown || [];
    return { in: rows.filter((r) => r.direction === "in").slice(0, 6),
             out: rows.filter((r) => r.direction === "out").slice(0, 6) };
  }, [payload]);

  return (
    <Card className="overflow-hidden mb-6" data-testid="netflow-daily-report">
      {/* ---------------- header ---------------- */}
      <div className="px-5 py-3 border-b border-slate-200 bg-[#0a2350] text-white">
        <div className="flex flex-wrap items-center gap-3">
          <div className="flex items-center gap-2">
            <span className={`h-2.5 w-2.5 rounded-full ${stale ? "bg-red-400" : lagging ? "bg-amber-400" : "bg-emerald-400"}`} />
            <span className="text-xs font-black uppercase tracking-[0.2em]">Daily Flow Report</span>
          </div>

          <div className="flex items-center gap-2 ml-1">
            <select
              value={prefix}
              onChange={(e) => setPrefix(e.target.value)}
              className="bg-white/10 border border-white/20 rounded-lg px-2.5 py-1 text-xs font-bold text-white focus:outline-none focus:ring-2 focus:ring-[#f5b120]"
              data-testid="netflow-prefix-select"
            >
              {(payload?.prefixes || []).map((p) => (
                <option key={p.prefix} value={p.prefix} className="text-slate-900">
                  {p.prefix}{p.configured ? "" : " *"}
                </option>
              ))}
              {!payload?.prefixes?.length && prefix && (
                <option value={prefix} className="text-slate-900">{prefix}</option>
              )}
            </select>
            <select
              value={hours}
              onChange={(e) => setHours(Number(e.target.value))}
              className="bg-white/10 border border-white/20 rounded-lg px-2 py-1 text-xs font-bold text-white focus:outline-none focus:ring-2 focus:ring-[#f5b120]"
              data-testid="netflow-hours-select"
            >
              {[6, 12, 24, 48, 72, 168].map((h) => (
                <option key={h} value={h} className="text-slate-900">{h} jam</option>
              ))}
            </select>
          </div>

          <div className="ml-auto flex items-center gap-3 text-[11px]">
            <span className="inline-flex items-center gap-1.5" data-testid="netflow-window">
              <Activity className="h-3 w-3 opacity-70" />
              {payload?.window ? `${hoursLabelShort(payload.window)}` : "-"}
            </span>
            <span className="inline-flex items-center gap-1.5" title="jam dengan agregat penuh / perkiraan / kosong"
                  data-testid="netflow-coverage">
              <Layers className="h-3 w-3 opacity-70" />
              {coverage.rollup_hours ?? 0} penuh · {coverage.backfill_hours ?? 0} perkiraan · {coverage.empty_hours ?? 0} kosong
            </span>
            <label className="inline-flex items-center gap-1.5 cursor-pointer select-none">
              <input type="checkbox" checked={auto} onChange={(e) => setAuto(e.target.checked)}
                     className="accent-[#f5b120]" data-testid="netflow-auto" />
              auto
            </label>
            <button
              type="button"
              onClick={load}
              disabled={loading}
              className="inline-flex items-center gap-1.5 font-bold rounded-lg px-2.5 py-1 bg-white/10 hover:bg-white/20 border border-white/20 disabled:opacity-50 focus-visible:ring-2 focus-visible:ring-[#f5b120]"
              data-testid="netflow-refresh-btn"
            >
              <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} /> Muat ulang
            </button>
          </div>
        </div>

        <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-[10px] text-white/60">
          <span className="inline-flex items-center gap-1">
            <Radio className="h-3 w-3" />
            {collector.exists === false
              ? "collector goflow2 tidak ditemukan"
              : `NetFlow goflow2 · file ${collector.file_age_s != null ? `${Math.round(collector.file_age_s)}s lalu` : "-"}`}
          </span>
          {collector.rollup?.lag_s != null && (
            <span>rollup lag {Math.round(collector.rollup.lag_s)}s</span>
          )}
          {collector.gaps > 0 && (
            <span className="text-amber-300">gap rotasi: {collector.gaps}</span>
          )}
          {coverage.first_rollup_at && <span>agregat mulai {dayLabel(coverage.first_rollup_at)} {hourLabel(coverage.first_rollup_at)}</span>}
          <span className="opacity-70">data ASN: bgp.tools</span>
        </div>
      </div>

      {stale && (
        <div className="px-5 py-2.5 bg-red-50 border-b border-red-200 text-red-800 text-xs flex items-center gap-2"
             data-testid="netflow-stale">
          <AlertTriangle className="h-4 w-4 shrink-0" />
          Collector flow berhenti menulis. Angka di bawah ini adalah data terakhir yang tersimpan, bukan kondisi saat ini.
        </div>
      )}
      {!stale && lagging && (
        <div className="px-5 py-2.5 bg-amber-50 border-b border-amber-200 text-amber-800 text-xs flex items-center gap-2"
             data-testid="netflow-lagging">
          <AlertTriangle className="h-4 w-4 shrink-0" />
          Agregator tertinggal {Math.round(collector.rollup.lag_s)}s. Jam berjalan mungkin belum lengkap.
        </div>
      )}
      {error && (
        <div className="px-5 py-2.5 bg-amber-50 border-b border-amber-200 text-amber-800 text-xs flex items-center gap-2"
             data-testid="netflow-error">
          <AlertTriangle className="h-4 w-4 shrink-0" /> {error}
        </div>
      )}

      <div className="p-5">
        {/* ---------------- headline metrics ---------------- */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
          <Metric label="Avg In" value={fmtBps(totals.avg_in_bps)} tone="in"
                  Icon={ArrowDownToLine} testid="netflow-avg-in"
                  sub={`puncak ${fmtBps(totals.peak_in_bps)} @ ${hourLabel(totals.peak_in_hour)}`} />
          <Metric label="Avg Out" value={fmtBps(totals.avg_out_bps)} tone="out"
                  Icon={ArrowUpFromLine} testid="netflow-avg-out"
                  sub={`puncak ${fmtBps(totals.peak_out_bps)} @ ${hourLabel(totals.peak_out_hour)}`} />
          <Metric label="Volume" value={fmtBytes(totals.bytes_total)} Icon={Layers}
                  testid="netflow-volume"
                  sub={`↓ ${fmtBytes(totals.bytes_in)} · ↑ ${fmtBytes(totals.bytes_out)}`} />
          <Metric label="Avg Total" value={fmtBps(totals.avg_total_bps)} Icon={Activity}
                  testid="netflow-avg-total"
                  sub={payload?.prefix ? `artefak ${payload.prefix}` : ""} />
        </div>

        {/* ---------------- domestic vs international ---------------- */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3 mt-4">
          {[
            { key: "domestic", label: "Domestic", tone: "#0a2350", Icon: MapPin, testid: "netflow-geo-domestic",
              note: "peer dengan kode negara ID" },
            { key: "international", label: "International", tone: "#f5b120", Icon: Globe2, testid: "netflow-geo-intl",
              note: "peer di luar Indonesia" },
          ].map(({ key, label, tone, Icon, testid, note }) => {
            const g = geo[key] || {};
            return (
              <div key={key} className="rounded-xl border border-slate-200 bg-white p-4" data-testid={testid}>
                <div className="flex items-center gap-2 text-xs font-bold uppercase tracking-widest text-slate-500">
                  <Icon className="h-3.5 w-3.5" /> {label}
                </div>
                <div className="mt-2 flex items-end gap-3">
                  <div className="text-2xl font-black text-[#0a2350] tabular-nums">{fmtBytes(g.bytes)}</div>
                  <div className="text-sm font-bold text-slate-400 mb-0.5 tabular-nums">{fmtPct(g.share)}</div>
                </div>
                <div className="mt-2 h-2 rounded-full bg-slate-100 overflow-hidden">
                  <div className="h-full rounded-full" style={{ width: `${Math.max(0.5, (g.share || 0) * 100)}%`, background: tone }} />
                </div>
                <div className="mt-2 flex flex-wrap gap-x-4 text-[11px] text-slate-500">
                  <span>{g.peers || 0} peer /24</span>
                  <span>{g.asns || 0} AS</span>
                  <span>avg {fmtBps(g.avg_bps)}</span>
                </div>
                <div className="mt-1 text-[10px] text-slate-400">{note}</div>
              </div>
            );
          })}
        </div>
        {(geo.unknown?.bytes || 0) > 0 && (
          <div className="mt-2 text-[11px] text-slate-500 flex items-center gap-1.5" data-testid="netflow-geo-unknown">
            <ShieldQuestion className="h-3.5 w-3.5 text-slate-400" />
            {fmtBytes(geo.unknown.bytes)} ({fmtPct(geo.unknown.share)}) belum punya kode negara di bgp.tools -
            {" "}{geo.unknown.peers} peer /24. Tidak dihitung sebagai domestic maupun international.
          </div>
        )}

        {/* ---------------- download / upload with sparkline ---------------- */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3 mt-4">
          {[
            { k: "download", label: "DOWNLOAD", tone: "#059669", Icon: ArrowDownToLine, testid: "netflow-download" },
            { k: "upload", label: "UPLOAD", tone: "#0284c7", Icon: ArrowUpFromLine, testid: "netflow-upload" },
          ].map(({ k, label, tone, Icon, testid }) => {
            const d = payload?.[k] || {};
            return (
              <div key={k} className="rounded-xl border border-slate-200 bg-white p-4" data-testid={testid}>
                <div className="flex items-center gap-2 text-xs font-bold uppercase tracking-widest text-slate-500">
                  <Icon className="h-3.5 w-3.5" style={{ color: tone }} /> {label}
                  <span className="ml-auto font-mono text-[10px] text-slate-400">
                    {dayLabel(payload?.window?.from)} → {dayLabel(payload?.window?.to)}
                  </span>
                </div>
                <div className="mt-2 flex items-baseline gap-3">
                  <span className="text-xl font-black tabular-nums" style={{ color: tone }}>{fmtBps(d.avg_bps)}</span>
                  <span className="text-[11px] text-slate-500">rata-rata</span>
                  <span className="ml-auto text-[11px] text-slate-500">
                    puncak <b className="text-[#0a2350]">{fmtBps(d.peak_bps)}</b>
                    {d.peak_hour ? ` @ ${dayLabel(d.peak_hour)} ${hourLabel(d.peak_hour)}` : ""}
                  </span>
                </div>
                <div className="mt-2">
                  <Sparkline data={d.series} color={tone} height={40} />
                </div>
              </div>
            );
          })}
        </div>

        {/* ---------------- top sources / destinations ---------------- */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-3 mt-4">
          <div className="rounded-xl border border-slate-200 bg-white p-4" data-testid="netflow-top-sources">
            <div className="flex items-center gap-2 text-xs font-bold uppercase tracking-widest text-slate-500">
              <ArrowDownToLine className="h-3.5 w-3.5 text-emerald-600" /> Top Sources
              <span className="ml-auto normal-case tracking-normal font-normal text-[10px] text-slate-400">
                peer /24 pengirim terbanyak
              </span>
            </div>
            <div className="mt-2">
              {topSources.length === 0
                ? <div className="text-xs text-slate-400 py-6 text-center" data-testid="netflow-sources-empty">
                    Belum ada data sumber pada jendela ini.
                  </div>
                : topSources.map((r, i) => (
                    <PeerRow key={r.peer} row={r} rank={i + 1} testid={`netflow-source-${i}`} />
                  ))}
            </div>
          </div>

          <div className="rounded-xl border border-slate-200 bg-white p-4" data-testid="netflow-top-destinations">
            <div className="flex items-center gap-2 text-xs font-bold uppercase tracking-widest text-slate-500">
              <ArrowUpFromLine className="h-3.5 w-3.5 text-sky-600" /> Top Destinations
              <span className="ml-auto normal-case tracking-normal font-normal text-[10px] text-slate-400">
                peer /24 tujuan terbanyak
              </span>
            </div>
            <div className="mt-2">
              {topDest.length === 0
                ? <div className="text-xs text-slate-400 py-6 text-center" data-testid="netflow-dest-empty">
                    Belum ada data tujuan pada jendela ini.
                  </div>
                : topDest.map((r, i) => (
                    <PeerRow key={r.peer} row={r} rank={i + 1} testid={`netflow-dest-${i}`} />
                  ))}
            </div>
          </div>
        </div>

        {/* ---------------- AS breakdown ---------------- */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-3 mt-4">
          {[["in", "AS penyumbang inbound", asByDirection.in, "#0a2350", "netflow-as-in"],
            ["out", "AS tujuan outbound", asByDirection.out, "#f5b120", "netflow-as-out"]].map(
            ([dirn, title, rows, color, testid]) => (
              <div key={dirn} className="rounded-xl border border-slate-200 bg-white p-4" data-testid={testid}>
                <div className="text-xs font-bold uppercase tracking-widest text-slate-500 flex items-center gap-2">
                  <Network className="h-3.5 w-3.5" /> {title}
                </div>
                <div className="mt-2">
                  {rows.length === 0
                    ? <div className="text-xs text-slate-400 py-4 text-center">tidak ada data</div>
                    : rows.map((r) => (
                        <BarRow key={`${r.asn}-${dirn}-${r.as_name}`} testid={`${testid}-row`}
                                label={r.asn ? `AS${r.asn}` : "belum terpetakan"}
                                sub={r.asn
                                  ? `${r.cc ? flagOf(r.cc) + " " : ""}${r.as_name || "nama tidak tersedia"} · ${r.peers} /24`
                                  : `${r.peers} /24 - bgp.tools tidak memetakan blok ini`}
                                share={r.share} value={fmtBps(r.bytes * 8 / ((payload?.window?.span_hours || 1) * 3600))}
                                bytes={r.bytes} color={color} />
                      ))}
                </div>
              </div>
            ))}
        </div>

        {/* ---------------- talkers: per-AS view and flat per-IP view ------ */}
        <div className="mt-4 rounded-xl border border-slate-200 bg-white">
          <div className="flex flex-wrap items-center gap-2 px-4 pt-4">
            <div className="inline-flex rounded-lg border border-slate-200 overflow-hidden">
              {[["as", "Top IP per AS"], ["flat", "Top IP (semua)"]].map(([k, label]) => (
                <button key={k} type="button" onClick={() => setTabIn(k)}
                        data-testid={`netflow-talker-tab-${k}`}
                        className={`px-3 py-1.5 text-[11px] font-bold ${tabIn === k
                          ? "bg-[#0a2350] text-white" : "bg-white text-slate-600 hover:bg-slate-50"}`}>
                  {label}
                </button>
              ))}
            </div>
            <span className="ml-auto text-[10px] text-slate-400">
              alamat tunggal, dianotasi AS-nya lewat bgp.tools
            </span>
          </div>

          <div className="p-4 overflow-x-auto">
            {tabIn === "as" ? <PerAsTalkerTable rows={talkers} />
                            : <FlatTalkerTable payload={payload} />}
          </div>
        </div>

        {/* ---------------- protocol + port ---------------- */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-3 mt-4">
          <div className="rounded-xl border border-slate-200 bg-white p-4" data-testid="netflow-protocols">
            <div className="text-xs font-bold uppercase tracking-widest text-slate-500">Protocol Breakdown</div>
            {["in", "out"].map((dirn) => (
              <div key={dirn} className="mt-3">
                <div className="text-[10px] font-bold text-slate-400 mb-1">
                  {dirn === "in" ? "INBOUND" : "OUTBOUND"}
                </div>
                {(payload?.protocols?.[dirn] || []).length === 0
                  ? <div className="text-[11px] text-slate-400">tidak ada data</div>
                  : (payload?.protocols?.[dirn] || []).map((p) => (
                      <BarRow key={`${dirn}-${p.key}`} testid={`netflow-proto-${dirn}-${p.key}`}
                              label={p.tail ? "protokol lain" : p.key}
                              sub={p.tail
                                ? `${p.grouped || 0} entri di luar daftar`
                                : undefined}
                              share={p.share} bytes={p.bytes}
                              color={dirn === "in" ? "#059669" : "#0284c7"} />
                    ))}
              </div>
            ))}
          </div>

          <div className="rounded-xl border border-slate-200 bg-white p-4" data-testid="netflow-ports">
            <div className="text-xs font-bold uppercase tracking-widest text-slate-500">Top Destination Ports</div>
            {["in", "out"].map((dirn) => (
              <div key={dirn} className="mt-3">
                <div className="text-[10px] font-bold text-slate-400 mb-1">
                  {dirn === "in" ? "INBOUND" : "OUTBOUND"}
                  {payload?.port_coverage?.[dirn]?.missing_share > 0.005 && (
                    <span className="ml-2 font-normal normal-case tracking-normal text-slate-400">
                      {fmtPct(payload.port_coverage[dirn].missing_share)} volume tanpa port tujuan
                      (GRE/ESP/ICMP)
                    </span>
                  )}
                </div>
                {(payload?.ports?.[dirn] || []).length === 0
                  ? <div className="text-[11px] text-slate-400">tidak ada data</div>
                  : (payload?.ports?.[dirn] || []).map((p) => (
                      <BarRow key={`${dirn}-${p.key}`} testid={`netflow-port-${dirn}-${p.key}`}
                              label={p.tail ? "port lain" : `:${p.key}`}
                              sub={p.tail
                                ? `${p.grouped || 0} port di luar 15 teratas`
                                : (p.service || undefined)}
                              share={p.share} bytes={p.bytes}
                              color={dirn === "in" ? "#059669" : "#0284c7"} />
                    ))}
              </div>
            ))}
          </div>
        </div>

        {/* ---------------- daily chart ---------------- */}
        <div className="mt-4 rounded-xl border border-slate-200 bg-white p-4" data-testid="netflow-daily-chart">
          <div className="flex flex-wrap items-center gap-2 text-xs font-bold uppercase tracking-widest text-slate-500">
            <Activity className="h-3.5 w-3.5 text-[#f5b120]" /> Download / Upload Rate
            <span className="normal-case tracking-normal font-normal text-[10px] text-slate-400">
              per jam · {payload?.prefix}
            </span>
            <span className="ml-auto inline-flex items-center gap-1 normal-case tracking-normal font-normal text-[10px] text-slate-400"
                  title="Rata-rata dan puncak dihitung dari agregat yang tersimpan, bukan dari sampel sesaat.">
              <HelpCircle className="h-3 w-3" /> avg {fmtBps((totals.avg_in_bps || 0) + (totals.avg_out_bps || 0))}
            </span>
          </div>
          <div className="mt-3">
            {buckets.length === 0
              ? <div className="text-xs text-slate-400 py-10 text-center" data-testid="netflow-chart-empty">
                  Belum ada bucket. Agregator mengisi data sejak deploy; history di luar jendela
                  flow_samples tidak tersedia.
                </div>
              : <DailyChart buckets={buckets} />}
          </div>
        </div>

        {/* ---------------- bgp.tools lookup ---------------- */}
        <div className="mt-4 rounded-xl border border-slate-200 bg-white p-4" data-testid="netflow-bgp-lookup">
          <div className="flex items-center gap-2 text-xs font-bold uppercase tracking-widest text-slate-500">
            <Search className="h-3.5 w-3.5" /> BGP Lookup (bgp.tools)
            <a href="https://bgp.tools/kb/api" target="_blank" rel="noreferrer"
               className="ml-auto inline-flex items-center gap-1 normal-case tracking-normal font-normal text-[10px] text-slate-400 hover:text-[#0a2350]">
              <ExternalLink className="h-3 w-3" /> sumber data
            </a>
          </div>
          <div className="mt-2 flex flex-wrap gap-2">
            <input
              value={lookupQ}
              onChange={(e) => setLookupQ(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") doLookup(); }}
              placeholder="IP, /24, atau ASN - mis. 8.8.8.8 / 157.20.32.0/24 / as7713"
              className="flex-1 min-w-[260px] rounded-lg border border-slate-300 px-3 py-2 text-xs font-mono focus:outline-none focus:ring-2 focus:ring-[#f5b120]"
              data-testid="netflow-lookup-input"
            />
            <button type="button" onClick={doLookup} disabled={lookupBusy || !lookupQ.trim()}
                    className="inline-flex items-center gap-1.5 rounded-lg bg-[#0a2350] px-3 py-2 text-xs font-bold text-white disabled:opacity-50 focus-visible:ring-2 focus-visible:ring-[#f5b120]"
                    data-testid="netflow-lookup-btn">
              <Search className={`h-3.5 w-3.5 ${lookupBusy ? "animate-pulse" : ""}`} /> Cari
            </button>
          </div>
          {lookup && (
            <div className="mt-3 text-xs" data-testid="netflow-lookup-result">
              {lookup.ok === false
                ? <div className="text-amber-700">{lookup.error || "gagal"}</div>
                : (
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                    {[["Query", lookup.query],
                      ["AS", lookup.asn ? `AS${lookup.asn}` : "-"],
                      ["AS Name", lookup.as_name || "-"],
                      ["Country", lookup.cc ? `${flagOf(lookup.cc)} ${lookup.cc} · ${geoName(lookup.cc)}` : "-"],
                      ["Origin prefix", lookup.prefix || "-"],
                      ["Registry", lookup.registry || "-"],
                      ["Allocated", lookup.allocated || "-"],
                      ["Cache", lookup.cached ? "ya" : "baru"]].map(([k, v]) => (
                      <div key={k} className="rounded-lg bg-slate-50 border border-slate-200 px-3 py-2">
                        <div className="text-[10px] font-bold uppercase tracking-widest text-slate-400">{k}</div>
                        <div className="font-mono text-[11px] text-[#0a2350] break-all">{v || "-"}</div>
                      </div>
                    ))}
                  </div>
                )}
            </div>
          )}
        </div>

        {/* ---------------- notes / provenance ---------------- */}
        {(errors.length > 0 || (coverage.evicted_peer_rows || 0) > 0) && (
          <div className="mt-3 rounded-xl border border-slate-200 bg-slate-50 p-3 text-[11px] text-slate-600"
               data-testid="netflow-notes">
            <div className="font-bold text-slate-700 mb-1">Catatan data</div>
            <ul className="list-disc pl-4 space-y-0.5">
              {errors.map((e, i) => <li key={i}>{e.detail || e.source}</li>)}
              {coverage.evicted_peer_rows > 0 && (
                <li>{coverage.evicted_peer_rows} jam-peer di luar 400 teratas dilebur ke baris
                  &quot;peer lain&quot; - volume total tetap dihitung penuh, dan barisnya
                  ditampilkan terpisah supaya daftar tidak terlihat lebih lengkap dari aslinya.</li>
              )}
            </ul>
          </div>
        )}
      </div>
    </Card>
  );
};

const DirectionTag = ({ direction }) => (
  <span className={`text-[10px] font-bold ${direction === "in" ? "text-emerald-600" : "text-sky-600"}`}>
    {direction === "in" ? "↓ IN" : "↑ OUT"}
  </span>
);

// "Top IP per AS": one block per AS, its heaviest addresses underneath. This is
// the shape the operator asked for - the question is "which network is talking,
// and through which address", so the AS has to own the row, not repeat on it.
const PerAsTalkerTable = ({ rows }) => {
  if (!rows.length) {
    return (
      <div className="text-xs text-slate-400 py-6 text-center" data-testid="netflow-talkers-empty">
        Belum ada alamat yang bisa dipetakan ke AS. Agregator butuh satu siklus penuh
        sebelum anotasi bgp.tools terisi.
      </div>
    );
  }
  return (
    <div className="space-y-3" data-testid="netflow-talkers-by-as">
      {rows.map((t) => (
        <div key={`${t.direction}-${t.asn ?? t.peer ?? "na"}`}
             className="rounded-lg border border-slate-200 overflow-hidden">
          <div className="flex items-center gap-2 bg-slate-50 px-3 py-1.5 border-b border-slate-200">
            <DirectionTag direction={t.direction} />
            <span className="font-mono text-[11px] font-black text-[#0a2350]">
              {t.asn ? `AS${t.asn}` : t.peer || "belum terpetakan"}
            </span>
            <span className="text-[11px] text-slate-600 truncate" title={asLabel(t)}>
              {t.asn
                ? `${t.cc ? flagOf(t.cc) + " " : ""}${t.as_name || "nama tidak tersedia"}`
                : "bgp.tools tidak memetakan blok ini"}
            </span>
            <span className="ml-auto text-[10px] text-slate-500 tabular-nums shrink-0">
              {fmtBytes(t.bytes)}
            </span>
          </div>
          <table className="w-full text-xs">
            <tbody>
              {t.ips.map((ip) => (
                <tr key={ip.ip} className="border-b border-slate-50 last:border-0">
                  <td className="py-1.5 px-3 font-mono font-bold text-[#0a2350]">
                    {ip.tail ? <span className="not-italic font-sans text-slate-500">alamat lain</span> : ip.ip}
                  </td>
                  <td className="py-1.5 pr-3 text-slate-400 font-mono text-[10px]">{t.peer || "—"}</td>
                  <td className="py-1.5 pr-3 text-right font-mono tabular-nums">{fmtBytes(ip.bytes)}</td>
                  <td className="py-1.5 pr-3 text-right font-mono tabular-nums text-slate-500 w-16">
                    {fmtPct(ip.share)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ))}
    </div>
  );
};

// "Top IP (semua)": the peer /24 leaderboard flattened, one row per network,
// sorted by volume. Complements the per-AS view when the operator is hunting a
// specific block rather than a specific network operator.
const FlatTalkerTable = ({ payload }) => {
  const rows = [
    ...(payload?.top_sources || []).map((r) => ({ ...r, direction: "in" })),
    ...(payload?.top_destinations || []).map((r) => ({ ...r, direction: "out" })),
  ].sort((a, b) => (b.bytes || 0) - (a.bytes || 0));
  if (!rows.length) {
    return <div className="text-xs text-slate-400 py-6 text-center">Belum ada data.</div>;
  }
  return (
    <table className="w-full text-xs" data-testid="netflow-talkers-table">
      <thead>
        <tr className="text-[10px] uppercase tracking-widest text-slate-400 border-b border-slate-200">
          <th className="text-left py-1.5 pr-3">Arah</th>
          <th className="text-left py-1.5 pr-3">Peer /24</th>
          <th className="text-left py-1.5 pr-3">AS</th>
          <th className="text-left py-1.5 pr-3">Negara</th>
          <th className="text-right py-1.5 pr-3">Volume</th>
          <th className="text-right py-1.5">Rata-rata</th>
        </tr>
      </thead>
      <tbody>
        {rows.slice(0, 30).map((r, i) => (
          <tr key={`${r.direction}-${r.peer}-${i}`} className="border-b border-slate-50 last:border-0">
            <td className="py-1.5 pr-3"><DirectionTag direction={r.direction} /></td>
            <td className="py-1.5 pr-3 font-mono text-[#0a2350]">{r.peer}</td>
            <td className="py-1.5 pr-3 text-slate-500 truncate max-w-[240px]" title={asLabel(r)}>{asLabel(r)}</td>
            <td className="py-1.5 pr-3 text-slate-500">{r.cc ? `${flagOf(r.cc)} ${r.cc}` : "—"}</td>
            <td className="py-1.5 pr-3 text-right font-mono tabular-nums">{fmtBytes(r.bytes)}</td>
            <td className="py-1.5 text-right font-mono tabular-nums">{fmtBps(r.avg_bps)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
};

const hoursLabelShort = (w) => {
  if (!w?.from || !w?.to) return "-";
  const f = new Date(w.from);
  const t = new Date(w.to);
  if (Number.isNaN(f.getTime()) || Number.isNaN(t.getTime())) return "-";
  const sameDay = f.toDateString() === t.toDateString();
  const fmt = (d) => `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
  return sameDay ? `${fmt(f)} → ${fmt(t)} WIB` : `${dayLabel(w.from)} ${fmt(f)} → ${dayLabel(w.to)} ${fmt(t)}`;
};

export default NetflowDailyReport;
