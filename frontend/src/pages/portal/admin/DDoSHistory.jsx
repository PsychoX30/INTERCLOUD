import React, { useState } from "react";
import { Card } from "../ui";
import { History, Mail, ShieldCheck, ShieldOff, Filter } from "lucide-react";

// MOCK riwayat insiden - histori live dari kolektor + notifier menyusul di fase backend.
const HISTORY = [
  { id: "h1", at: "2026-07-29 14:22", target: "103.147.92.10", type: "UDP Flood", peak: "9.8 Gbps", action: "auto_blackhole", notified: ["noc@intercloud-digital.com"], status: "mitigated" },
  { id: "h2", at: "2026-07-28 03:41", target: "103.147.92.55", type: "SYN Flood", peak: "2.1 Gbps", action: "alert", notified: ["noc@intercloud-digital.com", "oncall@intercloud-digital.com"], status: "resolved" },
  { id: "h3", at: "2026-07-25 19:05", target: "103.147.93.7", type: "DNS Amplification", peak: "1.3 Gbps", action: "auto_blackhole", notified: ["noc@intercloud-digital.com"], status: "mitigated" },
  { id: "h4", at: "2026-07-21 08:17", target: "103.147.94.2", type: "HTTP Flood", peak: "640 Mbps", action: "alert", notified: ["noc@intercloud-digital.com"], status: "false_positive" },
];

const STATUS_META = {
  mitigated: { label: "Dimitigasi", cls: "bg-emerald-100 text-emerald-700 border-emerald-300", icon: ShieldCheck },
  resolved: { label: "Selesai", cls: "bg-sky-100 text-sky-700 border-sky-300", icon: ShieldCheck },
  false_positive: { label: "False positive", cls: "bg-slate-100 text-slate-600 border-slate-300", icon: ShieldOff },
};

const FILTERS = [
  { key: "all", label: "Semua" },
  { key: "mitigated", label: "Dimitigasi" },
  { key: "resolved", label: "Selesai" },
  { key: "false_positive", label: "False positive" },
];

export const DDoSHistory = () => {
  const [filter, setFilter] = useState("all");
  const rows = filter === "all" ? HISTORY : HISTORY.filter((h) => h.status === filter);
  return (
    <Card className="overflow-hidden mb-6" data-testid="ddos-history">
      <div className="px-5 py-3 border-b border-slate-200 bg-slate-50 flex flex-wrap items-center justify-between gap-3">
        <div>
          <div className="text-xs font-bold uppercase tracking-widest text-slate-600 flex items-center gap-2">
            <History className="h-3.5 w-3.5 text-[#f5b120]" /> Riwayat Notifikasi Insiden DDoS
          </div>
          <div className="text-xs text-slate-500 mt-0.5">Histori insiden & channel notifikasi (data tiruan).</div>
        </div>
        <div className="flex items-center gap-1.5">
          <Filter className="h-3.5 w-3.5 text-slate-400" />
          {FILTERS.map((f) => (
            <button
              key={f.key}
              onClick={() => setFilter(f.key)}
              className={`px-2.5 py-1 rounded-full text-[11px] font-bold transition-colors ${filter === f.key ? "bg-[#0a2350] text-white" : "bg-white border border-slate-200 text-slate-600 hover:border-[#f5b120]"}`}
              data-testid={`ddos-history-filter-${f.key}`}
            >
              {f.label}
            </button>
          ))}
        </div>
      </div>
      {rows.length === 0 ? (
        <div className="px-5 py-6 text-sm text-slate-500" data-testid="ddos-history-empty">Tidak ada insiden dengan status ini.</div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-[11px] uppercase tracking-widest text-slate-500">
              <tr>
                <th className="text-left px-4 py-2.5">Waktu</th>
                <th className="text-left px-4 py-2.5">Target</th>
                <th className="text-left px-4 py-2.5">Jenis</th>
                <th className="text-right px-4 py-2.5">Puncak</th>
                <th className="text-left px-4 py-2.5">Aksi</th>
                <th className="text-left px-4 py-2.5">Notifikasi Ke</th>
                <th className="text-left px-4 py-2.5">Status</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((h) => {
                const m = STATUS_META[h.status];
                return (
                  <tr key={h.id} className="border-t border-slate-100" data-testid={`ddos-history-row-${h.id}`}>
                    <td className="px-4 py-2.5 font-mono text-xs text-slate-600 whitespace-nowrap">{h.at}</td>
                    <td className="px-4 py-2.5 font-mono font-bold text-[#0a2350]">{h.target}</td>
                    <td className="px-4 py-2.5 text-slate-600">{h.type}</td>
                    <td className="px-4 py-2.5 text-right font-semibold tabular-nums">{h.peak}</td>
                    <td className="px-4 py-2.5 text-xs">{h.action === "auto_blackhole" ? "Auto-blackhole" : "Alert"}</td>
                    <td className="px-4 py-2.5">
                      <div className="flex flex-wrap gap-1">
                        {h.notified.map((e) => (
                          <span key={e} className="inline-flex items-center gap-1 text-[10px] bg-slate-100 border border-slate-200 rounded-full px-2 py-0.5 text-slate-600">
                            <Mail className="h-2.5 w-2.5" /> {e}
                          </span>
                        ))}
                      </div>
                    </td>
                    <td className="px-4 py-2.5">
                      <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full border text-[10px] font-bold uppercase ${m.cls}`}>
                        <m.icon className="h-3 w-3" /> {m.label}
                      </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
};

export default DDoSHistory;
