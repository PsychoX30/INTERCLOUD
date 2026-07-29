import React, { useState } from "react";
import { api } from "../../../portal/api";
import { Card, btnSecondary } from "../ui";
import { ShieldAlert, ShieldCheck, Loader2 } from "lucide-react";
import { Link } from "react-router-dom";

// MOCK incident feed - deteksi anomali live dari kolektor Netflow menyusul di fase backend.
const MOCK_INCIDENTS = [
  { id: "i1", target: "103.147.92.10", type: "UDP Flood", pps: "2.4M pps", bw: "9.8 Gbps", started: "5 menit lalu", severity: "critical" },
  { id: "i2", target: "103.147.92.55", type: "SYN Flood", pps: "890K pps", bw: "2.1 Gbps", started: "18 menit lalu", severity: "high" },
  { id: "i3", target: "103.147.93.7", type: "DNS Amplification", pps: "310K pps", bw: "1.3 Gbps", started: "42 menit lalu", severity: "medium" },
];

const sevCls = {
  critical: "bg-red-100 text-red-700 border-red-300",
  high: "bg-orange-100 text-orange-700 border-orange-300",
  medium: "bg-amber-100 text-amber-800 border-amber-300",
};

export const DDoSPanel = ({ devices }) => {
  const [busyId, setBusyId] = useState("");
  const [results, setResults] = useState({});

  const blackhole = async (inc) => {
    setBusyId(inc.id);
    try {
      const deviceId = devices?.[0]?.id;
      await api.post("/admin/mikrotik/blackhole", {
        device_id: deviceId,
        prefix: `${inc.target}/32`,
        comment: `ddos-${inc.type.toLowerCase().replace(/\s+/g, "-")}`,
      });
      setResults((r) => ({ ...r, [inc.id]: { ok: true, text: `Blackhole /32 diumumkan untuk ${inc.target}` } }));
    } catch (e) {
      setResults((r) => ({ ...r, [inc.id]: { ok: false, text: e?.response?.data?.detail || "Gagal announce blackhole (cek device MikroTik)" } }));
    } finally {
      setBusyId("");
    }
  };

  return (
    <Card className="overflow-hidden mb-6" data-testid="ddos-panel">
      <div className="px-5 py-3 border-b border-slate-200 bg-slate-50 flex items-center justify-between gap-3">
        <div>
          <div className="text-xs font-bold uppercase tracking-widest text-slate-600 flex items-center gap-2">
            <ShieldAlert className="h-3.5 w-3.5 text-red-500" /> Insiden DDoS Terdeteksi
          </div>
          <div className="text-xs text-slate-500 mt-0.5">
            Deteksi anomali (data tiruan). Tombol Blackhole memanggil API MikroTik live.
          </div>
        </div>
        <Link to="/portal/admin/mikrotik" className="text-xs font-bold text-[#f5b120] hover:text-[#0a2350] whitespace-nowrap">Kelola blackhole →</Link>
      </div>
      <div className="divide-y divide-slate-100">
        {MOCK_INCIDENTS.map((inc) => {
          const res = results[inc.id];
          return (
            <div key={inc.id} className="px-5 py-3.5 flex flex-wrap items-center gap-x-4 gap-y-2" data-testid={`ddos-incident-${inc.id}`}>
              <span className={`px-2 py-0.5 rounded-full border text-[10px] font-bold uppercase ${sevCls[inc.severity]}`}>{inc.severity}</span>
              <div className="min-w-[140px]">
                <div className="font-mono font-bold text-sm text-[#0a2350]">{inc.target}</div>
                <div className="text-[11px] text-slate-500">{inc.type}</div>
              </div>
              <div className="text-xs text-slate-600 tabular-nums">
                <b>{inc.bw}</b> · {inc.pps}
              </div>
              <div className="text-[11px] text-slate-400">{inc.started}</div>
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
