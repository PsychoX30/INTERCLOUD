import React, { useEffect, useMemo, useState } from "react";
import { ResponsiveContainer, LineChart, Line, XAxis, YAxis, Tooltip, CartesianGrid } from "recharts";
import { api } from "../../../portal/api";
import { PageHeader, Card, Loading, EmptyState } from "../ui";
import { Activity, TrendingUp, TrendingDown } from "lucide-react";

// Auto-scale bps → kbps → Mbps → Gbps → Tbps (1000-based prefix).
const fmtBps = (v) => {
  if (v == null || isNaN(v)) return "-";
  const units = ["bps", "kbps", "Mbps", "Gbps", "Tbps"];
  const sign = v < 0 ? "-" : "";
  let abs = Math.abs(v);
  let i = 0;
  while (abs >= 1000 && i < units.length - 1) { abs /= 1000; i++; }
  return `${sign}${abs.toFixed(i > 0 ? 2 : 0)} ${units[i]}`;
};

const RANGES = [
  { label: "1D", hours: 24 },
  { label: "1W", hours: 24 * 7 },
  { label: "1M", hours: 24 * 30 },
  { label: "1Y", hours: 24 * 365 },
];

const ClientMRTG = () => {
  const [graphs, setGraphs] = useState(null);
  const [selected, setSelected] = useState("");
  const [data, setData] = useState(null);
  const [hours, setHours] = useState(24 * 7);

  useEffect(() => {
    api.get("/client/monitoring/graphs").then((r) => {
      setGraphs(r.data);
      if (r.data.length > 0) setSelected(r.data[0].id);
    });
  }, []);

  useEffect(() => {
    if (!selected) return;
    setData(null);
    const t = new Date();
    const f = new Date(t.getTime() - hours * 3600 * 1000).toISOString();
    api.get(`/client/monitoring/graphs/${selected}/data`, {
      params: { from: f, to: t.toISOString(), resolution: "auto" },
    }).then((r) => setData(r.data)).catch(() => setData({ data: [] }));
  }, [selected, hours]);

  const graph = useMemo(() => (graphs || []).find((g) => g.id === selected), [graphs, selected]);
  const unit = graph?.unit || (graph?.type?.startsWith("snmp_traffic") ? "bps" : "");
  const isBps = unit === "bps";

  const samples = useMemo(() => (data?.data || []).map((s) => ({
    ...s,
    label: s.at ? new Date(s.at).toLocaleString() : "-",
  })), [data]);

  const stats = useMemo(() => {
    const vals = samples.map((s) => s.value).filter((v) => v != null && !Number.isNaN(v)).map(Number);
    if (!vals.length) return null;
    return {
      max: Math.max(...vals),
      avg: vals.reduce((a, b) => a + b, 0) / vals.length,
      last: vals[vals.length - 1],
    };
  }, [samples]);

  const fmt = (v) => (isBps ? fmtBps(v) : (v == null ? "-" : `${Number(v).toFixed(2)} ${unit}`.trim()));

  // Y-axis auto-scales to the peak value within the selected range (0 → peak).
  const yDomain = useMemo(() => {
    const vals = samples.map(s => s.value).filter(v => v != null && Number.isFinite(Number(v))).map(Number);
    if (!vals.length) return [0, "auto"];
    const peak = Math.max(...vals);
    if (peak <= 0) return [0, "auto"];
    return [0, Math.ceil(peak * 1.1)];
  }, [samples]);

  if (!graphs) return <Loading />;
  if (graphs.length === 0) return (
    <div>
      <PageHeader title="MRTG" />
      <EmptyState title="No SNMP graphs" body="Once an SNMP graph is assigned to your service, its MRTG data will show here." />
    </div>
  );

  return (
    <div>
      <PageHeader
        title="MRTG"
        subtitle="Historical traffic trends from SNMP polling."
      />
      <div className="mb-4 flex flex-wrap gap-2 items-center">
        {graphs.map((g) => (
          <button
            key={g.id}
            onClick={() => setSelected(g.id)}
            data-testid={`mrtg-graph-${g.id}`}
            className={`px-3 h-9 rounded-full border text-xs font-semibold transition-colors ${
              selected === g.id
                ? "bg-[#0a2350] text-white border-[#0a2350]"
                : "bg-white text-slate-600 border-slate-200 hover:border-slate-300"
            }`}
          >
            {g.display_name || g.name} <span className="text-[10px] opacity-70 ml-1">· {g.type}</span>
          </button>
        ))}
        <div className="flex items-center gap-1 ml-auto rounded-full bg-slate-100 p-1 text-xs" data-testid="mrtg-range">
          {RANGES.map((r) => (
            <button
              key={r.label}
              type="button"
              onClick={() => setHours(r.hours)}
              className={`px-2.5 h-7 rounded-full font-semibold ${
                hours === r.hours ? "bg-white text-[#0a2350]" : "text-slate-600 hover:text-[#0a2350]"
              }`}
              data-testid={`mrtg-range-${r.label}`}
            >{r.label}</button>
          ))}
        </div>
      </div>

      {!data && <Loading />}
      {data && samples.length > 0 && (
        <>
          <div className="grid sm:grid-cols-3 gap-4 mb-4">
            <Card className="p-5">
              <div className="text-[11px] uppercase font-bold tracking-widest text-slate-500 flex items-center gap-1.5"><Activity className="h-3.5 w-3.5 text-[#f5b120]" /> Latest</div>
              <div className="text-2xl font-extrabold text-[#0a2350] mt-1">{fmt(stats?.last)}</div>
            </Card>
            <Card className="p-5">
              <div className="text-[11px] uppercase font-bold tracking-widest text-slate-500 flex items-center gap-1.5"><TrendingUp className="h-3.5 w-3.5 text-blue-500" /> Peak</div>
              <div className="text-2xl font-extrabold text-[#0a2350] mt-1">{fmt(stats?.max)}</div>
            </Card>
            <Card className="p-5">
              <div className="text-[11px] uppercase font-bold tracking-widest text-slate-500 flex items-center gap-1.5"><TrendingDown className="h-3.5 w-3.5 text-emerald-500" /> Average</div>
              <div className="text-2xl font-extrabold text-[#0a2350] mt-1">{fmt(stats?.avg)}</div>
            </Card>
          </div>

          <Card className="p-6">
            <div className="flex items-center gap-2 mb-4">
              <Activity className="h-4 w-4 text-[#f5b120]" />
              <div className="font-extrabold text-[#0a2350]">
                Traffic ({unit || "value"}) — {data.resolution === "raw" ? "high-res samples" : data.resolution === "hourly" ? "hourly avg" : "daily avg"}
              </div>
            </div>
            <div className="h-96">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={samples}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="label" minTickGap={40} tick={{ fontSize: 10 }} />
                  <YAxis domain={yDomain} allowDataOverflow tickFormatter={(v) => (isBps ? fmtBps(v).replace(/\s.*/, "") : Number(v).toFixed(0))} tick={{ fontSize: 10 }} />
                  <Tooltip formatter={(v) => [fmt(v), unit || ""]} />
                  <Line type="monotone" dataKey="value" name={unit || "value"} stroke="#0a2350" strokeWidth={2} dot={false} connectNulls={false} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </Card>
        </>
      )}
      {data && samples.length === 0 && (
        <Card className="p-10 text-center" data-testid="mrtg-no-data">
          <Activity className="h-8 w-8 text-slate-300 mx-auto" />
          <div className="mt-3 font-extrabold text-[#0a2350]">No data in selected range</div>
          <p className="mt-1 text-sm text-slate-500 max-w-md mx-auto">
            Try a different time range, or wait for the next polling cycle if this graph was just assigned.
          </p>
        </Card>
      )}
    </div>
  );
};

export default ClientMRTG;