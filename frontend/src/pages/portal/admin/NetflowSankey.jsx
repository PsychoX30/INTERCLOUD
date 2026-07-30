import React, { useEffect, useMemo, useState } from "react";
import { Sankey, Tooltip, ResponsiveContainer, Layer, Rectangle } from "recharts";
import { api } from "../../../portal/api";
import { Card } from "../ui";
import { Network, HelpCircle } from "lucide-react";

// Data flows dimuat HANYA dari endpoint live (torch MikroTik). Tanpa perangkat
// yang bisa disampling, komponen menampilkan empty state - tidak ada data sampel.

const buildSankey = (flows) => {
  const names = [];
  const idx = (n) => {
    let i = names.indexOf(n);
    if (i === -1) { names.push(n); i = names.length - 1; }
    return i;
  };
  const links = flows.map((f) => ({ source: idx(f.src), target: idx(f.dst), value: f.gbps }));
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
        {`${Number(payload.value).toFixed(1)} Gbps`}
      </text>
    )}
  </Layer>
);

export const NetflowSankey = () => {
  const [hover, setHover] = useState(null);
  const [flows, setFlows] = useState(null);
  const [live, setLive] = useState(false);
  useEffect(() => {
    api.get("/admin/noc/netflow/sankey")
      .then((r) => {
        if (r.data?.live && (r.data.flows || []).length > 0) {
          setFlows(r.data.flows);
          setLive(true);
        } else {
          setFlows([]);
        }
      })
      .catch(() => setFlows([]));
  }, []);
  const data = useMemo(() => buildSankey(flows || []), [flows]);
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
                Lebar pita menunjukkan besarnya trafik: makin tebal, makin besar throughput (Gbps).
                Arahkan kursor ke pita untuk melihat angka pastinya. Pita yang tiba-tiba menebal
                dapat menandakan lonjakan abnormal atau serangan.
              </span>
            </span>
          </div>
          <div className="text-xs text-slate-500 mt-0.5">
            Visualisasi arah trafik{" "}
            {live
              ? <span className="text-emerald-600 font-bold" data-testid="sankey-live-badge">(live dari MikroTik)</span>
              : <span data-testid="sankey-waiting-badge">(menunggu data live dari perangkat MikroTik)</span>}
          </div>
        </div>
        {hover && (
          <div className="text-xs font-bold text-[#0a2350] bg-[#f5b120]/15 border border-[#f5b120]/40 rounded-lg px-3 py-1.5" data-testid="sankey-hover-info">
            {hover}
          </div>
        )}
      </div>
      <div className="p-4" style={{ height: 360 }}>
        {flows === null ? (
          <div className="h-full flex items-center justify-center text-sm text-slate-400" data-testid="sankey-loading">
            Mengambil sampel trafik live…
          </div>
        ) : !live || flows.length === 0 ? (
          <div className="h-full flex flex-col items-center justify-center text-center px-6" data-testid="sankey-empty">
            <Network className="h-10 w-10 text-slate-300 mb-3" />
            <div className="font-bold text-[#0a2350] text-sm">Belum ada data trafik live</div>
            <p className="mt-1 text-xs text-slate-500 max-w-md leading-relaxed">
              Diagram ini dibangun dari sampel torch RouterOS. Tambahkan router di
              <b> Admin &gt; MikroTik Ops &gt; Devices</b> (host + kredensial API), lalu diagram
              akan otomatis menampilkan arus trafik source → destination secara real-time.
            </p>
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
                setHover(`${item.payload.source.name} → ${item.payload.target.name}: ${item.payload.value} Gbps`);
              }
            }}
            onMouseLeave={() => setHover(null)}
          >
            <Tooltip
              formatter={(v) => [`${v} Gbps`, "Throughput"]}
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
