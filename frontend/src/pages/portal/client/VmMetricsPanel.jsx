import React, { useEffect, useRef, useState } from "react";
import { api } from "../../../portal/api";
import { Card } from "../ui";
import { Activity } from "lucide-react";
import {
  ResponsiveContainer, AreaChart, Area, XAxis, YAxis, Tooltip, CartesianGrid, Legend,
} from "recharts";

const fmtTime = (t) => new Date(t * 1000).toLocaleTimeString("id-ID", { hour: "2-digit", minute: "2-digit" });
const fmtKb = (v) => (v >= 1024 ? `${(v / 1024).toFixed(1)} MB/s` : `${Math.round(v)} KB/s`);

const ChartBox = ({ title, children, testid }) => (
  <div data-testid={testid}>
    <div className="text-[11px] font-bold uppercase tracking-widest text-slate-500 mb-1">{title}</div>
    <div className="h-40">{children}</div>
  </div>
);

export const VmMetricsPanel = ({ serviceId }) => {
  const [data, setData] = useState(null);
  const [updatedAt, setUpdatedAt] = useState(null);
  const timerRef = useRef(null);

  useEffect(() => {
    let alive = true;
    const load = () => {
      api.get(`/client/services/${serviceId}/vm/metrics?timeframe=hour`)
        .then((r) => { if (alive) { setData(r.data); setUpdatedAt(new Date()); } })
        .catch(() => { if (alive) setData({ available: false, message: "Gagal memuat metrik." }); });
    };
    load();
    timerRef.current = setInterval(load, 10000);
    return () => { alive = false; clearInterval(timerRef.current); };
  }, [serviceId]);

  if (!data) return null;
  if (!data.available) {
    return (
      <Card className="p-5" data-testid="vm-metrics-panel">
        <div className="text-sm font-extrabold text-[#0a2350] mb-1 flex items-center gap-2"><Activity className="h-4 w-4" /> Resource monitor</div>
        <p className="text-xs text-slate-500" data-testid="vm-metrics-unavailable">{data.message || "Metrik belum tersedia."}</p>
      </Card>
    );
  }

  const series = (data.series || []).map((p) => ({ ...p, time: fmtTime(p.t) }));
  const memTotal = series.length ? series[series.length - 1].mem_total_mb : 0;

  return (
    <Card className="p-5" data-testid="vm-metrics-panel">
      <div className="flex items-center justify-between mb-4">
        <div className="text-sm font-extrabold text-[#0a2350] flex items-center gap-2">
          <Activity className="h-4 w-4" /> Resource monitor <span className="text-[10px] font-bold text-slate-400 uppercase">1 jam terakhir</span>
        </div>
        <span className="text-[10px] text-slate-400" data-testid="vm-metrics-updated">
          {updatedAt ? `Diperbarui ${updatedAt.toLocaleTimeString("id-ID")} · refresh 10 dtk` : ""}
        </span>
      </div>
      <div className="space-y-5">
        <ChartBox title="CPU (%)" testid="vm-metrics-cpu">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={series} margin={{ top: 4, right: 8, left: -18, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
              <XAxis dataKey="time" tick={{ fontSize: 10 }} minTickGap={40} />
              <YAxis tick={{ fontSize: 10 }} domain={[0, 100]} unit="%" />
              <Tooltip formatter={(v) => [`${v}%`, "CPU"]} labelStyle={{ fontSize: 11 }} contentStyle={{ fontSize: 12 }} />
              <Area type="monotone" dataKey="cpu_pct" name="CPU" stroke="#0a2350" fill="#0a2350" fillOpacity={0.15} strokeWidth={2} isAnimationActive={false} />
            </AreaChart>
          </ResponsiveContainer>
        </ChartBox>

        <ChartBox title={`RAM (MB${memTotal ? ` / total ${Math.round(memTotal)} MB` : ""})`} testid="vm-metrics-ram">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={series} margin={{ top: 4, right: 8, left: -12, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
              <XAxis dataKey="time" tick={{ fontSize: 10 }} minTickGap={40} />
              <YAxis tick={{ fontSize: 10 }} domain={[0, memTotal || "auto"]} />
              <Tooltip formatter={(v) => [`${Math.round(v)} MB`, "RAM terpakai"]} labelStyle={{ fontSize: 11 }} contentStyle={{ fontSize: 12 }} />
              <Area type="monotone" dataKey="mem_used_mb" name="RAM terpakai" stroke="#f5b120" fill="#f5b120" fillOpacity={0.2} strokeWidth={2} isAnimationActive={false} />
            </AreaChart>
          </ResponsiveContainer>
        </ChartBox>

        <ChartBox title="Disk I/O (KB/s)" testid="vm-metrics-disk">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={series} margin={{ top: 4, right: 8, left: -12, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
              <XAxis dataKey="time" tick={{ fontSize: 10 }} minTickGap={40} />
              <YAxis tick={{ fontSize: 10 }} />
              <Tooltip formatter={(v, n) => [fmtKb(v), n]} labelStyle={{ fontSize: 11 }} contentStyle={{ fontSize: 12 }} />
              <Legend wrapperStyle={{ fontSize: 11 }} />
              <Area type="monotone" dataKey="disk_read_kb" name="Read" stroke="#059669" fill="#059669" fillOpacity={0.12} strokeWidth={2} isAnimationActive={false} />
              <Area type="monotone" dataKey="disk_write_kb" name="Write" stroke="#dc2626" fill="#dc2626" fillOpacity={0.12} strokeWidth={2} isAnimationActive={false} />
            </AreaChart>
          </ResponsiveContainer>
        </ChartBox>
      </div>
    </Card>
  );
};

export default VmMetricsPanel;
