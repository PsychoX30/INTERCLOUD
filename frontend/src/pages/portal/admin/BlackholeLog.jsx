import React, { useState } from "react";
import { Card } from "../ui";
import { ShieldAlert, ShieldOff, Search } from "lucide-react";
import { Link } from "react-router-dom";

// MOCK log aktivitas blackhole - log live tercatat di Audit Log saat aksi via API.
const LOG = [
  { id: "b1", at: "2026-07-29 14:23", prefix: "103.147.92.10/32", action: "add", by: "auto-mitigasi (Anti UDP Flood)", source: "auto", device: "core-router-01" },
  { id: "b2", at: "2026-07-29 06:02", prefix: "185.220.101.4/32", action: "add", by: "admin@intercloud-digital.com", source: "manual", device: "core-router-01" },
  { id: "b3", at: "2026-07-28 22:47", prefix: "185.220.101.4/32", action: "remove", by: "admin@intercloud-digital.com", source: "manual", device: "core-router-01" },
  { id: "b4", at: "2026-07-25 19:06", prefix: "103.147.93.7/32", action: "add", by: "auto-mitigasi (DNS Amp Guard)", source: "auto", device: "edge-router-02" },
  { id: "b5", at: "2026-07-25 21:30", prefix: "103.147.93.7/32", action: "remove", by: "noc@intercloud-digital.com", source: "manual", device: "edge-router-02" },
];

export const BlackholeLog = () => {
  const [q, setQ] = useState("");
  const rows = LOG.filter((l) => !q || l.prefix.includes(q) || l.by.toLowerCase().includes(q.toLowerCase()));
  return (
    <Card className="overflow-hidden mb-6" data-testid="blackhole-log">
      <div className="px-5 py-3 border-b border-slate-200 bg-slate-50 flex flex-wrap items-center justify-between gap-3">
        <div>
          <div className="text-xs font-bold uppercase tracking-widest text-slate-600 flex items-center gap-2">
            <ShieldAlert className="h-3.5 w-3.5 text-[#f5b120]" /> Log Aktivitas Blackhole
          </div>
          <div className="text-xs text-slate-500 mt-0.5">
            Jejak announce/remove blackhole (data tiruan). Aksi live tercatat otomatis di{" "}
            <Link to="/portal/admin/audit-log" className="text-[#f5b120] font-bold">Audit Log</Link>.
          </div>
        </div>
        <div className="relative">
          <Search className="h-3.5 w-3.5 text-slate-400 absolute left-2.5 top-1/2 -translate-y-1/2" />
          <input
            className="rounded-lg border border-slate-300 pl-8 pr-3 py-1.5 text-xs w-56"
            placeholder="Cari prefix / aktor..."
            value={q}
            onChange={(e) => setQ(e.target.value)}
            data-testid="blackhole-log-search"
          />
        </div>
      </div>
      {rows.length === 0 ? (
        <div className="px-5 py-6 text-sm text-slate-500" data-testid="blackhole-log-empty">Tidak ada entri yang cocok.</div>
      ) : (
        <div className="divide-y divide-slate-100">
          {rows.map((l) => (
            <div key={l.id} className="px-5 py-3 flex flex-wrap items-center gap-x-4 gap-y-1.5 text-sm" data-testid={`blackhole-log-row-${l.id}`}>
              <span className="font-mono text-xs text-slate-500 whitespace-nowrap">{l.at}</span>
              <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full border text-[10px] font-bold uppercase ${
                l.action === "add" ? "bg-red-100 text-red-700 border-red-300" : "bg-emerald-100 text-emerald-700 border-emerald-300"}`}>
                {l.action === "add" ? <ShieldAlert className="h-3 w-3" /> : <ShieldOff className="h-3 w-3" />}
                {l.action === "add" ? "Announce" : "Remove"}
              </span>
              <span className="font-mono font-bold text-[#0a2350]">{l.prefix}</span>
              <span className="text-xs text-slate-500">via {l.device}</span>
              <span className="ml-auto flex items-center gap-2">
                <span className={`text-[10px] font-bold uppercase px-2 py-0.5 rounded-full ${l.source === "auto" ? "bg-[#0a2350] text-white" : "bg-slate-100 text-slate-600 border border-slate-200"}`}>
                  {l.source}
                </span>
                <span className="text-xs text-slate-600">{l.by}</span>
              </span>
            </div>
          ))}
        </div>
      )}
    </Card>
  );
};

export default BlackholeLog;
