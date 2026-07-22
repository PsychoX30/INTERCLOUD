import React, { useEffect, useState } from "react";
import { api } from "../../../portal/api";
import { PageHeader, Card, Loading, EmptyState } from "../ui";
import { Activity, TrendingUp, TrendingDown } from "lucide-react";

const ClientTraffic = () => {
  const [services, setServices] = useState(null);
  const [selected, setSelected] = useState("");
  const [data, setData] = useState(null);

  useEffect(() => {
    api.get("/client/services").then((r) => {
      setServices(r.data);
      if (r.data.length > 0) setSelected(r.data[0].id);
    });
  }, []);

  useEffect(() => {
    if (!selected) return;
    setData(null);
    api.get(`/client/services/${selected}/traffic`).then((r) => setData(r.data));
  }, [selected]);

  if (!services) return <Loading />;
  if (services.length === 0) return (
    <div>
      <PageHeader title="Traffic Report" />
      <EmptyState title="No services with traffic tracking" body="Once a VPS, dedicated, or interconnect service is active, its 24h traffic report will show here." />
    </div>
  );

  return (
    <div>
      <PageHeader
        title="Traffic Report"
        subtitle="24-hour ingress / egress by service. Data is refreshed hourly from our carrier switches."
      />
      <div className="mb-4 flex flex-wrap gap-2">
        {services.map((s) => (
          <button
            key={s.id}
            onClick={() => setSelected(s.id)}
            data-testid={`traffic-svc-${s.id}`}
            className={`px-3 h-9 rounded-full border text-xs font-semibold transition-colors ${
              selected === s.id
                ? "bg-[#0a2350] text-white border-[#0a2350]"
                : "bg-white text-slate-600 border-slate-200 hover:border-slate-300"
            }`}
          >
            {s.name} <span className="text-[10px] opacity-70 ml-1">· {s.category}</span>
          </button>
        ))}
      </div>

      {!data && <Loading />}
      {data && (
        <>
          <div className="grid sm:grid-cols-4 gap-4 mb-4">
            <Card className="p-5">
              <div className="text-[11px] uppercase font-bold tracking-widest text-slate-500 flex items-center gap-1.5"><TrendingDown className="h-3.5 w-3.5 text-emerald-500" /> Inbound (24h)</div>
              <div className="text-2xl font-extrabold text-[#0a2350] mt-1">{data.totals.in_gb} GB</div>
            </Card>
            <Card className="p-5">
              <div className="text-[11px] uppercase font-bold tracking-widest text-slate-500 flex items-center gap-1.5"><TrendingUp className="h-3.5 w-3.5 text-blue-500" /> Outbound (24h)</div>
              <div className="text-2xl font-extrabold text-[#0a2350] mt-1">{data.totals.out_gb} GB</div>
            </Card>
            <Card className="p-5">
              <div className="text-[11px] uppercase font-bold tracking-widest text-slate-500">Peak In</div>
              <div className="text-2xl font-extrabold text-[#0a2350] mt-1">{data.peak_in_mbps.toFixed(1)} <span className="text-sm text-slate-500">Mbps</span></div>
            </Card>
            <Card className="p-5">
              <div className="text-[11px] uppercase font-bold tracking-widest text-slate-500">Peak Out</div>
              <div className="text-2xl font-extrabold text-[#0a2350] mt-1">{data.peak_out_mbps.toFixed(1)} <span className="text-sm text-slate-500">Mbps</span></div>
            </Card>
          </div>

          <Card className="p-6">
            <div className="flex items-center gap-2 mb-4">
              <Activity className="h-4 w-4 text-[#f5b120]" />
              <div className="font-extrabold text-[#0a2350]">Bandwidth (Mbps) — last 24 hours</div>
            </div>
            <TrafficChart points={data.points} />
            <div className="mt-4 flex items-center gap-6 text-xs text-slate-500">
              <span className="flex items-center gap-1.5"><span className="h-2 w-2 rounded-full bg-emerald-500" /> Inbound</span>
              <span className="flex items-center gap-1.5"><span className="h-2 w-2 rounded-full bg-blue-500" /> Outbound</span>
            </div>
          </Card>
          <p className="mt-3 text-[11px] text-slate-500">Traffic data is currently mocked. Wire your carrier or router SNMP / MikroTik integration under Admin → Integrations to serve live data.</p>
        </>
      )}
    </div>
  );
};

const TrafficChart = ({ points }) => {
  const W = 800, H = 220, PAD = 30;
  const max = Math.max(...points.flatMap((p) => [p.in_mbps, p.out_mbps]), 1) * 1.1;
  const xStep = (W - PAD * 2) / (points.length - 1);
  const y = (v) => H - PAD - (v / max) * (H - PAD * 2);

  const toPath = (key) =>
    points.map((p, i) => `${i === 0 ? "M" : "L"} ${PAD + i * xStep} ${y(p[key])}`).join(" ");

  return (
    <div className="w-full overflow-x-auto">
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full min-w-[600px] h-56">
        {/* grid */}
        {[0, 0.25, 0.5, 0.75, 1].map((t) => (
          <line key={t} x1={PAD} x2={W - PAD} y1={PAD + t * (H - PAD * 2)} y2={PAD + t * (H - PAD * 2)} stroke="#e2e8f0" strokeDasharray="3 3" />
        ))}
        {/* areas */}
        <path d={`${toPath("in_mbps")} L ${PAD + (points.length - 1) * xStep} ${H - PAD} L ${PAD} ${H - PAD} Z`} fill="rgba(16,185,129,0.12)" />
        <path d={`${toPath("out_mbps")} L ${PAD + (points.length - 1) * xStep} ${H - PAD} L ${PAD} ${H - PAD} Z`} fill="rgba(59,130,246,0.10)" />
        {/* lines */}
        <path d={toPath("in_mbps")} fill="none" stroke="#10b981" strokeWidth="2" />
        <path d={toPath("out_mbps")} fill="none" stroke="#3b82f6" strokeWidth="2" />
        {/* x labels */}
        {points.map((p, i) =>
          i % 4 === 0 ? (
            <text key={i} x={PAD + i * xStep} y={H - 8} fontSize="10" textAnchor="middle" fill="#64748b">{p.t}</text>
          ) : null
        )}
      </svg>
    </div>
  );
};

export default ClientTraffic;
