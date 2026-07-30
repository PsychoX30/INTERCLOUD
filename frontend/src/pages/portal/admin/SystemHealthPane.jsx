import React, { useCallback, useEffect, useState } from "react";
import { api } from "../../../portal/api";
import { Card, btnPrimary } from "../ui";
import {
  Loader2, RefreshCw, Database, HardDrive, MemoryStick, Cpu, Lock,
  Clock3, Timer, Server, CheckCircle2, AlertTriangle, XCircle, MinusCircle,
} from "lucide-react";

const ICONS = {
  database: Database, disk: HardDrive, memory: MemoryStick, cpu: Cpu,
  ssl: Lock, scheduler: Clock3, uptime: Timer, svc_mongod: Server, svc_nginx: Server,
};

const STATUS = {
  ok:   { label: "OK",        chip: "bg-emerald-50 border-emerald-200 text-emerald-700", Icon: CheckCircle2 },
  warn: { label: "PERHATIAN", chip: "bg-amber-50 border-amber-200 text-amber-700",       Icon: AlertTriangle },
  fail: { label: "GAGAL",     chip: "bg-red-50 border-red-200 text-red-700",             Icon: XCircle },
  off:  { label: "OFF",       chip: "bg-slate-50 border-slate-200 text-slate-500",       Icon: MinusCircle },
};

const OVERALL = {
  ok:   { cls: "bg-emerald-50 border-emerald-200 text-emerald-800", msg: "Semua komponen sehat" },
  warn: { cls: "bg-amber-50 border-amber-200 text-amber-800",       msg: "Sistem berjalan, ada komponen yang perlu perhatian" },
  fail: { cls: "bg-red-50 border-red-200 text-red-800",             msg: "Ada komponen bermasalah - segera periksa" },
};

const UsageBar = ({ pct }) => (
  <div className="mt-2 h-1.5 w-full rounded-full bg-slate-100 overflow-hidden">
    <div
      className={`h-full rounded-full ${pct >= 90 ? "bg-red-500" : pct >= 80 ? "bg-amber-400" : "bg-emerald-500"}`}
      style={{ width: `${Math.min(pct, 100)}%` }}
    />
  </div>
);

export const SystemHealthPane = () => {
  const [data, setData] = useState(null);
  const [busy, setBusy] = useState(true);
  const [err, setErr] = useState("");

  const load = useCallback(async () => {
    setBusy(true); setErr("");
    try {
      const r = await api.get("/admin/system/health");
      setData(r.data);
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message);
    } finally {
      setBusy(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const ov = data ? (OVERALL[data.overall] || OVERALL.warn) : null;
  const OvIcon = data ? (STATUS[data.overall] || STATUS.warn).Icon : Loader2;

  return (
    <div data-testid="system-health-pane">
      <div className="flex items-center justify-between mb-4">
        <div className="text-xs text-slate-500">
          {data ? `Diperiksa: ${new Date(data.generated_at).toLocaleString("id-ID")}` : ""}
        </div>
        <button type="button" onClick={load} disabled={busy} className={btnPrimary} data-testid="system-health-refresh">
          {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
          {busy ? "Memeriksa…" : "Periksa Ulang"}
        </button>
      </div>

      {err && (
        <Card className="p-4 mb-4 bg-red-50 border border-red-200 text-red-700" data-testid="system-health-error">
          <div className="flex items-center gap-2 text-sm">
            <AlertTriangle className="h-4 w-4" /> {typeof err === "string" ? err : JSON.stringify(err)}
          </div>
        </Card>
      )}

      {busy && !data && (
        <Card className="p-10 flex items-center justify-center text-slate-400 gap-2">
          <Loader2 className="h-5 w-5 animate-spin" /> Menjalankan pemeriksaan sistem…
        </Card>
      )}

      {data && (
        <>
          <div className={`rounded-xl border px-5 py-4 mb-5 flex items-center gap-3 ${ov.cls}`} data-testid="system-health-overall">
            <OvIcon className="h-6 w-6 shrink-0" />
            <div>
              <div className="font-bold text-sm uppercase tracking-wide">Status: {(STATUS[data.overall] || STATUS.warn).label}</div>
              <div className="text-sm">{ov.msg}</div>
            </div>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
            {data.checks.map((c) => {
              const st = STATUS[c.status] || STATUS.warn;
              const Icon = ICONS[c.key] || Server;
              const pct = c.metrics?.used_percent;
              return (
                <Card key={c.key} className="p-4" data-testid={`health-check-${c.key}`}>
                  <div className="flex items-center justify-between gap-2">
                    <div className="flex items-center gap-2 font-bold text-sm text-[#0a2350]">
                      <Icon className="h-4 w-4 text-[#f5b120]" /> {c.name}
                    </div>
                    <span className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider ${st.chip}`}>
                      <st.Icon className="h-3 w-3" /> {st.label}
                    </span>
                  </div>
                  <div className="mt-2 text-xs text-slate-600 leading-relaxed">{c.detail}</div>
                  {typeof pct === "number" && <UsageBar pct={pct} />}
                </Card>
              );
            })}
          </div>
        </>
      )}
    </div>
  );
};

export default SystemHealthPane;
