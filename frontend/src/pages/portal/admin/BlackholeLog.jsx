import React, { useEffect, useState, useCallback } from "react";
import { api } from "../../../portal/api";
import { Card } from "../ui";
import { ShieldAlert, ShieldOff, Search } from "lucide-react";
import { Link } from "react-router-dom";
import { TablePager } from "./TablePager";

export const BlackholeLog = () => {
  const [q, setQ] = useState("");
  const [action, setAction] = useState("");
  const [source, setSource] = useState("");
  const [order, setOrder] = useState("desc");
  const [page, setPage] = useState(0);
  const LIMIT = 25;
  const [log, setLog] = useState(null);
  const [total, setTotal] = useState(0);

  const load = useCallback(() => {
    const params = { limit: LIMIT, skip: page * LIMIT, order, paginate: true };
    if (q)      params.q      = q;
    if (action) params.action = action;
    if (source) params.source = source;
    api.get("/admin/noc/blackhole-log", { params })
      .then((r) => { setLog(r.data?.items ?? []); setTotal(r.data?.total ?? 0); })
      .catch(() => { setLog([]); setTotal(0); });
  }, [q, action, source, order, page]);

  useEffect(() => { load(); }, [load]);

  const handleQ = (v) => { setQ(v); setPage(0); };
  const handleAction = (v) => { setAction(v); setPage(0); };
  const handleSource = (v) => { setSource(v); setPage(0); };
  const handleOrder  = (v) => { setOrder(v);  setPage(0); };

  return (
    <Card className="overflow-hidden mb-6" data-testid="blackhole-log">
      <div className="px-5 py-3 border-b border-slate-200 bg-slate-50 flex flex-wrap items-center justify-between gap-3">
        <div>
          <div className="text-xs font-bold uppercase tracking-widest text-slate-600 flex items-center gap-2">
            <ShieldAlert className="h-3.5 w-3.5 text-[#f5b120]" /> Log Aktivitas Blackhole
          </div>
          <div className="text-xs text-slate-500 mt-0.5">
            Jejak announce/remove blackhole (live: manual + auto-mitigasi). Aksi juga tercatat di{" "}
            <Link to="/portal/admin/audit-log" className="text-[#f5b120] font-bold">Audit Log</Link>.
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <div className="relative">
            <Search className="h-3.5 w-3.5 text-slate-400 absolute left-2.5 top-1/2 -translate-y-1/2" />
            <input
              className="rounded-lg border border-slate-300 pl-8 pr-3 py-1.5 text-xs w-48"
              placeholder="Cari prefix / aktor..."
              value={q}
              onChange={(e) => handleQ(e.target.value)}
              data-testid="blackhole-log-search"
            />
          </div>
          <select className="rounded-lg border border-slate-300 px-2 py-1.5 text-xs" value={action} onChange={(e) => handleAction(e.target.value)}>
            <option value="">Semua aksi</option>
            <option value="add">Announce</option>
            <option value="remove">Remove</option>
          </select>
          <select className="rounded-lg border border-slate-300 px-2 py-1.5 text-xs" value={source} onChange={(e) => handleSource(e.target.value)}>
            <option value="">Semua sumber</option>
            <option value="auto">Auto</option>
            <option value="manual">Manual</option>
          </select>
          <select className="rounded-lg border border-slate-300 px-2 py-1.5 text-xs" value={order} onChange={(e) => handleOrder(e.target.value)}>
            <option value="desc">Terbaru</option>
            <option value="asc">Terlama</option>
          </select>
        </div>
      </div>
      {log === null ? (
        <div className="px-5 py-6 text-sm text-slate-500">Memuat log...</div>
      ) : log.length === 0 ? (
        <div className="px-5 py-6 text-sm text-slate-500" data-testid="blackhole-log-empty">
          {total === 0 && !q && !action && !source ? "Belum ada aktivitas blackhole tercatat." : "Tidak ada entri yang cocok."}
        </div>
      ) : (
        <div className="divide-y divide-slate-100">
          {log.map((l) => (
            <div key={l.id} className="px-5 py-3 flex flex-wrap items-center gap-x-4 gap-y-1.5 text-sm" data-testid={`blackhole-log-row-${l.id}`}>
              <span className="font-mono text-xs text-slate-500 whitespace-nowrap">{(l.at || "").slice(0, 16).replace("T", " ")}</span>
              <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full border text-[10px] font-bold uppercase ${
                l.action === "add" ? "bg-red-100 text-red-700 border-red-300" : "bg-emerald-100 text-emerald-700 border-emerald-300"}`}>
                {l.action === "add" ? <ShieldAlert className="h-3 w-3" /> : <ShieldOff className="h-3 w-3" />}
                {l.action === "add" ? "Announce" : "Remove"}
              </span>
              <span className="font-mono font-bold text-[#0a2350]">{l.prefix}</span>
              <span className="text-xs text-slate-500">via {l.device || "-"}</span>
              {l.ok === false && <span className="text-[10px] font-bold uppercase text-red-600">gagal</span>}
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
      {total > LIMIT && (
        <TablePager page={page} total={total} limit={LIMIT} onPage={setPage} testid="blackhole-log-pager" />
      )}
    </Card>
  );
};

export default BlackholeLog;
