import React, { useEffect, useState } from "react";
import { api } from "../../../portal/api";
import { Card, btnSecondary } from "../ui";
import { ShieldAlert, ShieldCheck, Loader2, RadioTower } from "lucide-react";
import { Link } from "react-router-dom";

const sevCls = {
  critical: "bg-red-100 text-red-700 border-red-300",
  high: "bg-orange-100 text-orange-700 border-orange-300",
  medium: "bg-amber-100 text-amber-800 border-amber-300",
  low: "bg-slate-100 text-slate-600 border-slate-300",
};

const fmtBps = (v) => v >= 1e9 ? `${(v / 1e9).toFixed(1)} Gbps` : `${(v / 1e6).toFixed(0)} Mbps`;
const fmtPps = (v) => v >= 1e6 ? `${(v / 1e6).toFixed(1)}M pps` : `${(v / 1e3).toFixed(0)}K pps`;

export const DDoSPanel = ({ devices }) => {
  const [incidents, setIncidents] = useState(null);
  const [busyId, setBusyId] = useState("");
  const [running, setRunning] = useState(false);
  const [results, setResults] = useState({});

  const load = () => api.get("/admin/noc/ddos/incidents", { params: { status: "active" } })
    .then((r) => setIncidents(r.data))
    .catch(() => setIncidents([]));
  useEffect(() => { load(); }, []);

  const runDetect = async () => {
    setRunning(true);
    try { await api.post("/admin/noc/ddos/run-detect"); await load(); }
    finally { setRunning(false); }
  };

  const blackhole = async (inc) => {
    setBusyId(inc.id);
    try {
      const deviceId = devices?.[0]?.id;
      await api.post("/admin/mikrotik/blackhole", {
        device_id: deviceId,
        prefix: `${inc.target}/32`,
        comment: `ddos-${(inc.attack_type || "attack").toLowerCase().replace(/\s+/g, "-")}`,
      });
      await api.put(`/admin/noc/ddos/incidents/${inc.id}/status`, { status: "mitigated" });
      setResults((r) => ({ ...r, [inc.id]: { ok: true, text: `Blackhole /32 diumumkan untuk ${inc.target}` } }));
      load();
    } catch (e) {
      setResults((r) => ({ ...r, [inc.id]: { ok: false, text: e?.response?.data?.detail || "Gagal announce blackhole (cek device MikroTik)" } }));
    } finally {
      setBusyId("");
    }
  };

  return (
    <Card className="overflow-hidden mb-6" data-testid="ddos-panel">
      <div className="px-5 py-3 border-b border-slate-200 bg-slate-50 flex items-center justify-between gap-3 flex-wrap">
        <div>
          <div className="text-xs font-bold uppercase tracking-widest text-slate-600 flex items-center gap-2">
            <ShieldAlert className="h-3.5 w-3.5 text-red-500" /> Insiden DDoS Terdeteksi
          </div>
          <div className="text-xs text-slate-500 mt-0.5">
            Deteksi live: rule ambang batas dievaluasi tiap 5 menit terhadap trafik MikroTik.
          </div>
        </div>
        <div className="flex items-center gap-3">
          <button className={btnSecondary} onClick={runDetect} disabled={running} data-testid="ddos-run-detect">
            {running ? <Loader2 className="h-4 w-4 animate-spin" /> : <RadioTower className="h-4 w-4" />} Deteksi sekarang
          </button>
          <Link to="/portal/admin/mikrotik" className="text-xs font-bold text-[#f5b120] hover:text-[#0a2350] whitespace-nowrap">Kelola blackhole →</Link>
        </div>
      </div>
      <div className="divide-y divide-slate-100">
        {incidents === null && <div className="px-5 py-5 text-sm text-slate-500">Memuat insiden...</div>}
        {incidents !== null && incidents.length === 0 && (
          <div className="px-5 py-5 flex items-center gap-2 text-sm text-emerald-700" data-testid="ddos-no-incident">
            <ShieldCheck className="h-4 w-4" /> Tidak ada insiden aktif. Jaringan dalam kondisi normal.
          </div>
        )}
        {(incidents || []).map((inc) => {
          const res = results[inc.id];
          return (
            <div key={inc.id} className="px-5 py-3.5 flex flex-wrap items-center gap-x-4 gap-y-2" data-testid={`ddos-incident-${inc.id}`}>
              <span className={`px-2 py-0.5 rounded-full border text-[10px] font-bold uppercase ${sevCls[inc.severity] || sevCls.medium}`}>{inc.severity}</span>
              <div className="min-w-[140px]">
                <div className="font-mono font-bold text-sm text-[#0a2350]">{inc.target}</div>
                <div className="text-[11px] text-slate-500">{inc.attack_type}</div>
              </div>
              <div className="text-xs text-slate-600 tabular-nums">
                <b>{fmtBps(inc.bps)}</b> · {fmtPps(inc.pps)}
              </div>
              <div className="text-[11px] text-slate-400">{(inc.started_at || "").slice(0, 16).replace("T", " ")}</div>
              <div className="ml-auto flex items-center gap-3">
                {res && (
                  <span className={`text-[11px] font-semibold ${res.ok ? "text-emerald-600" : "text-red-600"}`} data-testid={`ddos-result-${inc.id}`}>
                    {res.ok ? <ShieldCheck className="h-3.5 w-3.5 inline mr-1" /> : null}{res.text}
                  </span>
                )}
                <button
                  className={btnSecondary}
                  disabled={busyId === inc.id || res?.ok}
                  onClick={() => blackhole(inc)}
                  data-testid={`ddos-blackhole-${inc.id}`}
                >
                  {busyId === inc.id ? <Loader2 className="h-4 w-4 animate-spin" /> : <ShieldAlert className="h-4 w-4" />}
                  {res?.ok ? "Blackholed" : "Blackhole IP"}
                </button>
              </div>
            </div>
          );
        })}
      </div>
    </Card>
  );
};

export default DDoSPanel;
