import React, { useEffect, useMemo, useState } from "react";
import { Sankey, Tooltip, ResponsiveContainer, Layer, Rectangle } from "recharts";
import { api } from "../../../portal/api";
import { Card } from "../ui";
import { Network, HelpCircle } from "lucide-react";

// Fallback sample flows - dipakai bila belum ada perangkat MikroTik yang bisa disampling.
const FLOWS = [
  { src: "203.0.113.10", dst: "VM Web Cluster", gbps: 4.2 },
  { src: "203.0.113.10", dst: "VM Database", gbps: 1.1 },
  { src: "198.51.100.24", dst: "VM Web Cluster", gbps: 2.6 },
  { src: "198.51.100.24", dst: "Mail Server", gbps: 0.8 },
  { src: "IX Peering (IIX)", dst: "VM Web Cluster", gbps: 3.4 },
  { src: "IX Peering (IIX)", dst: "CDN Cache", gbps: 5.1 },
  { src: "Transit Tier-1", dst: "CDN Cache", gbps: 2.2 },
  { src: "Transit Tier-1", dst: "VM Database", gbps: 0.6 },
  { src: "Transit Tier-1", dst: "Mail Server", gbps: 0.4 },
];

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
  const [flows, setFlows] = useState(FLOWS);
  const [live, setLive] = useState(false);
  useEffect(() => {
    api.get("/admin/noc/netflow/sankey")
      .then((r) => {
        if (r.data?.live && (r.data.flows || []).length > 0) {
          setFlows(r.data.flows);
          setLive(true);
        }
      })
      .catch(() => {});
  }, []);
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
              : <span data-testid="sankey-sample-badge">(data sampel - menampilkan live otomatis saat perangkat MikroTik tersambung)</span>}
          </div>
        </div>
        {hover && (
          <div className="text-xs font-bold text-[#0a2350] bg-[#f5b120]/15 border border-[#f5b120]/40 rounded-lg px-3 py-1.5" data-testid="sankey-hover-info">
            {hover}
          </div>
        )}
      </div>
      <div className="p-4" style={{ height: 360 }}>
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
      </div>
    </Card>
  );
};

export default NetflowSankey;
