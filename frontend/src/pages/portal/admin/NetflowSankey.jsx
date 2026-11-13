import React, { useEffect, useMemo, useState, useCallback } from "react";
import { Sankey, Tooltip, ResponsiveContainer, Layer, Rectangle } from "recharts";
import { api } from "../../../portal/api";
import { Card } from "../ui";
import {
  Network, HelpCircle, RefreshCw, AlertTriangle, Radio, Clock, Gauge,
} from "lucide-react";

// Diagram arus trafik Source → Destination.
//
// Sumber data adalah collector goflow2 (NetFlow/IPFIX dari MikroTik) yang
// menulis flow secara real-time; `/tool/torch` hanya dipakai sebagai
// fallback karena setiap panggilan memblokir 2 detik per interface. Panel
// ini WAJIB membedakan tiga keadaan yang dulu tampak sama semua:
//   - ada data          → gambar diagram
//   - collector mati    → peringatan keras (file tidak tumbuh)
//   - tidak ada trafik  → diagram kosong, tanpa alarm palsu

export const fmtBps = (bps) => {
  const v = Number(bps) || 0;
  if (v >= 1e9) return `${(v / 1e9).toFixed(2)} Gbps`;
  if (v >= 1e6) return `${(v / 1e6).toFixed(1)} Mbps`;
  if (v >= 1e3) return `${(v / 1e3).toFixed(0)} Kbps`;
  return `${Math.round(v)} bps`;
};

const fmtPps = (pps) => {
  const v = Number(pps) || 0;
  if (v >= 1e6) return `${(v / 1e6).toFixed(2)} Mpps`;
  if (v >= 1e3) return `${(v / 1e3).toFixed(1)} Kpps`;
  return `${Math.round(v)} pps`;
};

// Warna per kategori supaya pita mudah dibedakan seperti di akvorado:
// internal→internet (hijau), internet→internal (biru), internal→internal (abu).
const FLOW_COLORS = {
  outbound: "#0ea5e9",
  inbound: "#22c55e",
  internal: "#94a3b8",
};
const INTERNAL_PREFIX = /^(157\.20\.32\.|10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.)/;

const classify = (src) => (INTERNAL_PREFIX.test(src || "") ? "internal" : "external");

const buildSankey = (flows) => {
  // Recharts 3.6.0 crashes (RangeError: Maximum call stack size exceeded)
  // when a node has no incident link, or when there are fewer than 2 nodes.
  const valid = (flows || []).filter(
    (f) => f && f.src && f.dst && f.src !== f.dst && Number(f.bps) > 0
  );
  if (valid.length < 1) {
    return { nodes: [], links: [] };
  }
  // Sumber dan tujuan memakai namespace terpisah: jaringan nyata punya
  // trafik dua arah (A→B dan B→A); berbagi node membuat siklus dan
  // Recharts rekursi sampai stack overflow.
  const nodes = [];
  const indexes = new Map();
  const idx = (side, name) => {
    const key = `${side}:${name}`;
    if (!indexes.has(key)) {
      indexes.set(key, nodes.length);
      nodes.push({ name, side });
    }
    return indexes.get(key);
  };
  // `value` is only the ribbon thickness. Recharts reserves a few pixels per
  // link, so a handful of tiny links (sub-kbps background) would each claim
  // the same minimum and swallow the canvas, squeezing the real flows to a
  // hairline. Normalise against the largest link and give every ribbon a
  // visible floor instead of deriving it from raw bps.
  const peak = Math.max(...valid.map((f) => Number(f.bps) || 0), 1);
  const links = valid.map((f) => {
    const srcInternal = classify(f.src) === "internal";
    const dstInternal = classify(f.dst) === "internal";
    const kind = srcInternal && dstInternal ? "internal" : srcInternal ? "outbound" : "inbound";
    const bps = f.bps ?? (f.gbps || 0) * 1e9;
    return {
      source: idx("source", f.src),
      target: idx("destination", f.dst),
      value: Math.max((bps / peak) * 100, 1),
      bps,
      color: FLOW_COLORS[kind],
      kind,
    };
  });
  return { nodes, links };
};

const SankeyNode = ({ x, y, width, height, payload, containerWidth }) => {
  // Label di kiri untuk kolom sumber, di kanan untuk kolom tujuan.
  const isLeft = x < (containerWidth || 600) / 2;
  return (
    <Layer>
      <Rectangle x={x} y={y} width={width} height={height} fill="#f5b120" fillOpacity={0.9} radius={2} />
      <text
        x={isLeft ? x + width + 8 : x - 8}
        y={y + height / 2}
        textAnchor={isLeft ? "start" : "end"}
        dominantBaseline="middle"
        fill="#0a2350"
        fontSize={11}
        fontWeight={700}
      >
        {payload.name}
      </text>
    </Layer>
  );
};

export const NetflowSankey = ({ refreshMs = 30000 }) => {
  const [hover, setHover] = useState(null);
  const [payload, setPayload] = useState(null);
  const [loading, setLoading] = useState(true);
  const [auto, setAuto] = useState(true);

  const load = useCallback(() => {
    setLoading(true);
    api.get("/admin/noc/netflow/sankey")
      .then((r) => setPayload(r.data || {}))
      .catch((e) => setPayload({
        live: false, flows: [], source: "none", stale: true,
        errors: [{ device: "-", interface: "-", error: e?.response?.data?.detail || e.message }],
      }))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => { load(); }, [load]);

  // Auto-refresh ringan: endpoint sekarang hanya membaca file collector
  // (~0.5 s), tidak lagi memblokir router dengan Torch.
  useEffect(() => {
    if (!auto) return undefined;
    const t = setInterval(load, refreshMs);
    return () => clearInterval(t);
  }, [auto, load, refreshMs]);

  const flows = payload?.flows || [];
  const source = payload?.source || "none";
  const stale = !!payload?.stale;
  const errors = payload?.errors || [];
  const totalBps = payload?.total_bps || flows.reduce((a, f) => a + (f.bps || 0), 0);
  const data = useMemo(() => buildSankey(flows), [flows]);
  const hasChart = data.nodes.length >= 2 && data.links.length >= 1;
  const sourceLabel = {
    goflow2: "NetFlow (goflow2)",
    history: "riwayat tersimpan",
    torch: "Torch fallback",
    none: "tidak ada sumber",
  }[source] || source;

  return (
    <Card className="overflow-hidden mb-6" data-testid="netflow-sankey">
      <div className="px-5 py-3 border-b border-slate-200 bg-slate-50 flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="text-xs font-bold uppercase tracking-widest text-slate-600 flex items-center gap-2">
            <Network className="h-3.5 w-3.5 text-[#f5b120]" /> Netflow: Source → Destination
            <span className="relative group normal-case tracking-normal font-normal">
              <HelpCircle className="h-3.5 w-3.5 text-slate-400 cursor-help" data-testid="sankey-help-icon" />
              <span className="pointer-events-none absolute left-1/2 -translate-x-1/2 top-6 z-40 hidden group-hover:block w-80 rounded-xl bg-[#0a2350] text-white text-[11px] leading-relaxed p-3.5 shadow-xl">
                <b className="block mb-1 text-[#f5b120]">Cara membaca diagram ini</b>
                Kolom kiri = sumber trafik, kolom kanan = tujuan. Lebar pita = besar
                throughput. Warna: <b className="text-sky-400">biru</b> internal→internet,{" "}
                <b className="text-emerald-400">hijau</b> internet→internal,{" "}
                <b className="text-slate-300">abu</b> internal→internal. Pita yang tiba-tiba
                menebal dapat menandakan lonjakan atau serangan.
              </span>
            </span>
          </div>
          <div className="text-xs text-slate-500 mt-0.5 flex flex-wrap items-center gap-x-3 gap-y-1">
            {stale ? (
              <span className="inline-flex items-center gap-1 font-bold text-red-600" data-testid="sankey-stale-badge">
                <AlertTriangle className="h-3.5 w-3.5" /> Collector berhenti menulis
                {payload?.file_age_s != null && ` (${Math.round(payload.file_age_s / 60)} menit lalu)`}
              </span>
            ) : hasChart ? (
              <span className="inline-flex items-center gap-1 font-bold text-emerald-600" data-testid="sankey-live-badge">
                <Radio className="h-3.5 w-3.5" /> live · {sourceLabel}
              </span>
            ) : (
              <span className="inline-flex items-center gap-1 font-semibold text-slate-500" data-testid="sankey-idle-badge">
                <Clock className="h-3.5 w-3.5" /> tidak ada trafik pada jendela ini
              </span>
            )}
            {payload?.window_s > 0 && (
              <span className="inline-flex items-center gap-1" data-testid="sankey-window">
                <Clock className="h-3 w-3" /> jendela {payload.window_s.toFixed(1)} s
              </span>
            )}
            {payload?.batch_pps > 0 && (
              <span className="inline-flex items-center gap-1 font-mono" data-testid="sankey-pps">
                <Gauge className="h-3 w-3" /> {fmtPps(payload.batch_pps)}
              </span>
            )}
            {totalBps > 0 && (
              <span className="font-mono font-bold text-[#0a2350]" data-testid="sankey-total">
                {fmtBps(totalBps)}
              </span>
            )}
            {payload?.coverage?.total_links > 0 && (
              <span
                className="inline-flex items-center gap-1 text-slate-500"
                title={`${payload.coverage.kept_links} dari ${payload.coverage.total_links} tautan ditampilkan, mencakup ${(payload.coverage.top_share * 100).toFixed(1)}% throughput`}
                data-testid="sankey-coverage"
              >
                <Network className="h-3 w-3" />
                {payload.coverage.kept_links}/{payload.coverage.total_links} tautan
                ({(payload.coverage.top_share * 100).toFixed(0)}%)
              </span>
            )}
          </div>
        </div>
        <div className="flex items-center gap-2">
          {hover && (
            <div className="text-xs font-bold text-[#0a2350] bg-[#f5b120]/15 border border-[#f5b120]/40 rounded-lg px-3 py-1.5" data-testid="sankey-hover-info">
              {hover}
            </div>
          )}
          <label className="inline-flex items-center gap-1.5 text-[11px] text-slate-600 select-none cursor-pointer">
            <input type="checkbox" checked={auto} onChange={(e) => setAuto(e.target.checked)}
                   className="accent-[#f5b120]" data-testid="sankey-auto" />
            auto
          </label>
          <button
            onClick={load}
            disabled={loading}
            className="inline-flex items-center gap-1.5 text-[11px] font-bold text-slate-600 hover:text-[#0a2350] border border-slate-200 rounded-lg px-2.5 py-1.5 bg-white disabled:opacity-50 focus-visible:ring-2 focus-visible:ring-[#f5b120]"
            data-testid="sankey-refresh-btn"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} /> Muat ulang
          </button>
        </div>
      </div>
      <div className="p-4" style={{ height: Math.max(380, 40 + data.nodes.length * 26) }}>
        {loading && !payload ? (
          <div className="h-full flex items-center justify-center text-sm text-slate-400" data-testid="sankey-loading">
            Membaca flow collector…
          </div>
        ) : !hasChart ? (
          <div className="h-full flex flex-col items-center justify-center text-center px-6 overflow-y-auto" data-testid="sankey-empty">
            <Network className="h-10 w-10 text-slate-300 mb-3" />
            <div className="font-bold text-[#0a2350] text-sm">
              {stale ? "Collector flow berhenti menulis" : "Belum ada arus trafik pada jendela ini"}
            </div>
            <p className="mt-1 text-xs text-slate-500 max-w-md leading-relaxed">
              {stale
                ? <>File collector tidak bertambah. Periksa service <code className="bg-slate-100 px-1 rounded">goflow2</code> di server collector, dan pastikan rule firewall UDP 2055 mengizinkan IP MikroTik yang benar-benar mengirim flow.</>
                : <>Tidak ada flow tercatat dalam beberapa detik terakhir. Nyalakan <b>auto</b> agar panel menyegarkan sendiri, atau tunggu trafik berikutnya.</>}
            </p>
            {errors.length > 0 && (
              <div className="mt-3 w-full max-w-md text-left rounded-xl border border-amber-200 bg-amber-50 p-3" data-testid="sankey-errors">
                <div className="text-[11px] font-bold text-amber-800 flex items-center gap-1.5 mb-1">
                  <AlertTriangle className="h-3.5 w-3.5" /> Diagnosa
                </div>
                {errors.slice(0, 4).map((e, i) => (
                  <div key={i} className="text-[11px] text-amber-800/90 truncate">
                    <b>{e.device}</b> ({e.interface}): {e.error}
                  </div>
                ))}
              </div>
            )}
          </div>
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            <Sankey
              data={data}
              node={<SankeyNode />}
              nodePadding={Math.max(8, Math.min(18, Math.floor(300 / Math.max(1, data.nodes.length))))}
              margin={{ top: 8, right: 180, bottom: 8, left: 8 }}
              link={(props) => (
                <path
                  d={props?.payload?.d || ""}
                  fill="none"
                  stroke={props?.payload?.color || "#0a2350"}
                  strokeOpacity={0.28}
                  strokeWidth={props?.payload?.width ? Math.max(1, props.payload.width) : 1}
                />
              )}
              onMouseEnter={(item) => {
                if (item?.payload?.source?.name) {
                  setHover(`${item.payload.source.name} → ${item.payload.target.name}: ${fmtBps(item.payload.value * 1e3)}`);
                }
              }}
              onMouseLeave={() => setHover(null)}
            >
              <Tooltip formatter={(v) => [fmtBps(v * 1e3), "Throughput"]} separator=" - " />
            </Sankey>
          </ResponsiveContainer>
        )}
      </div>
    </Card>
  );
};

export default NetflowSankey;
