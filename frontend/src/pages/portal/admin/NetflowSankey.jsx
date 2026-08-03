import React, { useEffect, useMemo, useState, useCallback } from "react";
import { Sankey, Tooltip, ResponsiveContainer, Layer, Rectangle } from "recharts";
import { api } from "../../../portal/api";
import { Card } from "../ui";
import { Network, HelpCircle, RefreshCw, AlertTriangle } from "lucide-react";

// Data flows dimuat HANYA dari endpoint live (torch MikroTik: perangkat
// MikroTik Ops + integrasi legacy dari menu Integrations). Unit adaptif
// (bps/Kbps/Mbps/Gbps) agar trafik kecil tetap terlihat.

export const fmtBps = (bps) => {
  const v = Number(bps) || 0;
  if (v >= 1e9) return `${(v / 1e9).toFixed(2)} Gbps`;
  if (v >= 1e6) return `${(v / 1e6).toFixed(1)} Mbps`;
  if (v >= 1e3) return `${(v / 1e3).toFixed(0)} Kbps`;
  return `${Math.round(v)} bps`;
};

const buildSankey = (flows) => {
  const names = [];
  const idx = (n) => {
    let i = names.indexOf(n);
    if (i === -1) { names.push(n); i = names.length - 1; }
    return i;
  };
  // value dalam Kbps (min 0.001) supaya link kecil tetap tergambar
  const links = flows.map((f) => ({
    source: idx(f.src), target: idx(f.dst),
    value: Math.max((f.bps ?? (f.gbps || 0) * 1e9) / 1e3, 0.001),
    bps: f.bps ?? (f.gbps || 0) * 1e9,
  }));
  return { nodes: names.map((name) => ({ name })), links };
};

const SankeyNode = ({ x, y, width, height, payload }) => (
  <Layer>
    <Rectangle x={x} y={y} width={width} height={height} fill="#f5b120" fillOpacity={0.9} radius={2} />
    <text
      x={x < 300 ? x + width + 8 : x - 8}
      y={y + height / 2}
      textAnchor={x < 300 ? "start" : "end"}
      dominantBaseline="middle"
      className="fill-[#0a2350]"
      fontSize={12}
      fontWeight={700}
    >
      {payload.name}
    </text>
    {typeof payload.value === "number" && payload.value > 0 && (
      <text
        x={x < 300 ? x + width + 8 : x - 8}
        y={y + height / 2 + 15}
        textAnchor={x < 300 ? "start" : "end"}
        fill="#64748b"
        fontSize={10}
      >
        {fmtBps(payload.value * 1e3)}
      </text>
    )}
  </Layer>
);

export const NetflowSankey = () => {
  const [hover, setHover] = useState(null);
  const [payload, setPayload] = useState(null); // response penuh backend
  const [loading, setLoading] = useState(true);

  const load = useCallback(() => {
    setLoading(true);
    api.get("/admin/noc/netflow/sankey")
      .then((r) => setPayload(r.data || {}))
      .catch((e) => setPayload({ live: false, flows: [], errors: [{ device: "-", interface: "-", error: e?.response?.data?.detail || e.message }] }))
      .finally(() => setLoading(false));
  }, []);
  useEffect(() => { load(); }, [load]);

  const flows = payload?.flows || [];
  const live = !!payload?.live && flows.length > 0;
  const errors = payload?.errors || [];
  const interfaces = payload?.interfaces || [];
  const data = useMemo(() => buildSankey(flows), [flows]);

  return (
    <Card className="overflow-hidden mb-6" data-testid="netflow-sankey">
      <div className="px-5 py-3 border-b border-slate-200 bg-slate-50 flex items-center justify-between">
        <div>
          <div className="text-xs font-bold uppercase tracking-widest text-slate-600 flex items-center gap-2">
            <Network className="h-3.5 w-3.5 text-[#f5b120]" /> Netflow: Source → Destination
            <span className="relative group normal-case tracking-normal font-normal">
              <HelpCircle className="h-3.5 w-3.5 text-slate-400 cursor-help" data-testid="sankey-help-icon" />
              <span
                className="pointer-events-none absolute left-1/2 -translate-x-1/2 top-6 z-40 hidden group-hover:block w-72 rounded-xl bg-[#0a2350] text-white text-[11px] leading-relaxed p-3.5 shadow-xl"
                data-testid="sankey-help-tooltip"
              >
                <b className="block mb-1 text-[#f5b120]">Cara membaca diagram ini</b>
                Kolom kiri = sumber trafik (IP/upstream), kolom kanan = tujuan (server/layanan Anda).
                Lebar pita menunjukkan besarnya trafik: makin tebal, makin besar throughput.
                Arahkan kursor ke pita untuk melihat angka pastinya. Pita yang tiba-tiba menebal
                dapat menandakan lonjakan abnormal atau serangan.
              </span>
            </span>
          </div>
          <div className="text-xs text-slate-500 mt-0.5">
            Visualisasi arah trafik{" "}
            {live
              ? <span className="text-emerald-600 font-bold" data-testid="sankey-live-badge">(live dari MikroTik{interfaces.length ? `: ${interfaces.join(", ")}` : ""})</span>
              : <span data-testid="sankey-waiting-badge">(menunggu data live dari perangkat MikroTik)</span>}
          </div>
        </div>
        <div className="flex items-center gap-2">
          {hover && (
            <div className="text-xs font-bold text-[#0a2350] bg-[#f5b120]/15 border border-[#f5b120]/40 rounded-lg px-3 py-1.5" data-testid="sankey-hover-info">
              {hover}
            </div>
          )}
          <button
            onClick={load}
            disabled={loading}
            className="inline-flex items-center gap-1.5 text-[11px] font-bold text-slate-600 hover:text-[#0a2350] border border-slate-200 rounded-lg px-2.5 py-1.5 bg-white disabled:opacity-50"
            data-testid="sankey-refresh-btn"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} /> Sampling ulang
          </button>
        </div>
      </div>
      <div className="p-4" style={{ height: 360 }}>
        {loading && !payload ? (
          <div className="h-full flex items-center justify-center text-sm text-slate-400" data-testid="sankey-loading">
            Mengambil sampel trafik live…
          </div>
        ) : !live ? (
          <div className="h-full flex flex-col items-center justify-center text-center px-6 overflow-y-auto" data-testid="sankey-empty">
            <Network className="h-10 w-10 text-slate-300 mb-3" />
            <div className="font-bold text-[#0a2350] text-sm">
              {payload?.live ? "Perangkat tersambung, belum ada arus trafik terdeteksi" : "Belum ada data trafik live"}
            </div>
            <p className="mt-1 text-xs text-slate-500 max-w-md leading-relaxed">
              {payload?.live
                ? <>Sampling berhasil di <b>{interfaces.join(", ") || "-"}</b> namun tidak ada flow aktif saat ini. Coba "Sampling ulang" saat ada trafik, atau set <b>Main Interface</b> perangkat di Admin &gt; MikroTik Ops &gt; Devices ke interface uplink yang benar.</>
                : <>Diagram ini dibangun dari sampel torch RouterOS. Tambahkan router di <b>Admin &gt; MikroTik Ops &gt; Devices</b> atau aktifkan integrasi MikroTik di <b>Admin &gt; Integrations</b>, lalu diagram akan menampilkan arus trafik source → destination secara real-time.</>}
            </p>
            {errors.length > 0 && (
              <div className="mt-3 w-full max-w-md text-left rounded-xl border border-amber-200 bg-amber-50 p-3" data-testid="sankey-errors">
                <div className="text-[11px] font-bold text-amber-800 flex items-center gap-1.5 mb-1">
                  <AlertTriangle className="h-3.5 w-3.5" /> Diagnosa sampling
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
            nodePadding={28}
            margin={{ top: 10, right: 160, bottom: 10, left: 10 }}
            link={{ stroke: "#0a2350", strokeOpacity: 0.25 }}
            onMouseEnter={(item) => {
              if (item?.payload?.source?.name) {
                setHover(`${item.payload.source.name} → ${item.payload.target.name}: ${fmtBps(item.payload.value * 1e3)}`);
              }
            }}
            onMouseLeave={() => setHover(null)}
          >
            <Tooltip
              formatter={(v) => [fmtBps(v * 1e3), "Throughput"]}
              separator=" - "
            />
          </Sankey>
        </ResponsiveContainer>
        )}
      </div>
    </Card>
  );
};

export default NetflowSankey;
