import React, { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  RefreshCw, Database, AlertTriangle, CheckCircle2, Loader2, Play,
  RotateCcw, ExternalLink, Clock,
} from "lucide-react";
import { api, formatApiError } from "../../../portal/api";

const fmt = (v) => (v == null ? "—" : Number(v).toLocaleString());
const fmtWhen = (iso) => {
  if (!iso) return "never";
  try {
    return new Date(iso).toLocaleString("id-ID", {
      day: "2-digit", month: "short", year: "numeric",
      hour: "2-digit", minute: "2-digit", timeZone: "UTC",
    }) + " UTC";
  } catch { return iso; }
};

const Stat = ({ label, value, icon: Icon, tone = "slate" }) => (
  <div className="rounded-xl border border-slate-200 bg-white p-4">
    <div className="flex items-center gap-2 text-slate-500">
      <Icon className="h-3.5 w-3.5" />
      <span className="text-[10px] font-bold uppercase tracking-widest">{label}</span>
    </div>
    <div className={`mt-2 text-2xl font-extrabold text-${tone}-700`}>{value}</div>
  </div>
);

const AdminCveTracker = () => {
  const [state, setState] = useState(null);
  const [busy, setBusy] = useState("");
  const [msg, setMsg] = useState(null);
  const [err, setErr] = useState("");

  const load = useCallback(async () => {
    try {
      const r = await api.get("/admin/cve/sync-status");
      setState(r.data);
    } catch (e) {
      setErr(formatApiError(e));
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const runSync = async () => {
    setBusy("sync"); setMsg(null); setErr("");
    try {
      const r = await api.post("/admin/cve/sync?max_pages=2");
      const d = r.data;
      setMsg(
        d.error
          ? `Sync selesai dengan error: ${d.error}`
          : `Sync OK — ${fmt(d.processed)} diproses, ${fmt(d.written)} ditulis, total indeks ${fmt(d.stored_total)}.`
      );
      await load();
    } catch (e) {
      setErr(formatApiError(e));
    } finally { setBusy(""); }
  };

  const rebuild = async () => {
    setBusy("rebuild"); setMsg(null); setErr("");
    try {
      const r = await api.post("/admin/cve/sync/rebuild");
      setMsg(`Kursor di-reset ke ${r.data.cursor}. ${fmt(r.data.stored_total)} dokumen tetap tersimpan; sync berikutnya berjalan dari entri terbaru.`);
      await load();
    } catch (e) {
      setErr(formatApiError(e));
    } finally { setBusy(""); }
  };

  const progress = state && state.total_available
    ? Math.min(100, Math.round((state.cursor / state.total_available) * 100))
    : 0;

  return (
    <div className="p-4 md:p-6" data-testid="admin-cve-tracker">
      <div className="max-w-5xl mx-auto">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <h1 className="text-2xl font-extrabold text-[#0a2530]" data-testid="cve-admin-title">
              CVE Intelligence Hub
            </h1>
            <p className="mt-1 text-sm text-slate-500">
              Sinkronisasi NVD API 2.0 · jadwal otomatis tiap 2 jam · halaman publik di{" "}
              <Link to="/cve" target="_blank" className="inline-flex items-center gap-1 font-semibold text-[#0a2350] underline">
                /cve <ExternalLink className="h-3 w-3" />
              </Link>
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <button
              onClick={runSync}
              disabled={!!busy}
              data-testid="cve-sync-now"
              className="inline-flex items-center gap-2 h-10 px-4 rounded-lg bg-[#0a2350] text-white text-sm font-bold hover:bg-[#f5b120] hover:text-[#0a2350] transition-colors disabled:opacity-60"
            >
              {busy === "sync" ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
              Sync sekarang
            </button>
            <button
              onClick={rebuild}
              disabled={!!busy}
              data-testid="cve-sync-rebuild"
              className="inline-flex items-center gap-2 h-10 px-4 rounded-lg border border-slate-300 bg-white text-sm font-bold text-slate-700 hover:border-[#f5b120] transition-colors disabled:opacity-60"
            >
              {busy === "rebuild" ? <Loader2 className="h-4 w-4 animate-spin" /> : <RotateCcw className="h-4 w-4" />}
              Rebuild kursor
            </button>
            <button
              onClick={load}
              disabled={!!busy}
              className="inline-flex items-center justify-center h-10 w-10 rounded-lg border border-slate-300 bg-white text-slate-700 hover:border-[#f5b120] disabled:opacity-60"
              aria-label="Muat ulang status"
            >
              <RefreshCw className="h-4 w-4" />
            </button>
          </div>
        </div>

        {msg && (
          <div className="mt-5 rounded-xl border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-800" data-testid="cve-admin-msg">
            <CheckCircle2 className="inline h-4 w-4 mr-1.5 -mt-0.5" />
            {msg}
          </div>
        )}
        {err && (
          <div className="mt-5 rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700" data-testid="cve-admin-error">
            <AlertTriangle className="inline h-4 w-4 mr-1.5 -mt-0.5" />
            {err}
          </div>
        )}
        {state?.last_error && (
          <div className="mt-5 rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800" data-testid="cve-admin-last-error">
            <AlertTriangle className="inline h-4 w-4 mr-1.5 -mt-0.5" />
            Error sync terakhir: {state.last_error}
          </div>
        )}

        <div className="mt-6 grid grid-cols-2 lg:grid-cols-4 gap-3">
          <Stat label="Dokumen terindeks" value={state ? fmt(state.stored_total) : "—"} icon={Database} tone="slate" />
          <Stat label="Total di NVD" value={state ? fmt(state.total_available) : "—"} icon={Database} tone="slate" />
          <Stat label="Batch terakhir" value={state ? fmt(state.last_run_written) : "—"} icon={RefreshCw} tone="emerald" />
          <Stat label="Durasi terakhir" value={state?.last_run_seconds != null ? `${state.last_run_seconds}s` : "—"} icon={Clock} tone="slate" />
        </div>

        <div className="mt-6 rounded-2xl border border-slate-200 bg-white p-5">
          <div className="flex items-center justify-between text-sm">
            <span className="font-bold text-slate-700">Progres indeks (dari entri terbaru ke terlama)</span>
            <span className="text-slate-500" data-testid="cve-progress">
              {state ? `${fmt(state.cursor)} / ${fmt(state.total_available)}` : "—"}
            </span>
          </div>
          <div className="mt-3 h-2.5 w-full rounded-full bg-slate-100 overflow-hidden">
            <div className="h-full rounded-full bg-[#f5b120] transition-all" style={{ width: `${progress}%` }} />
          </div>
          <div className="mt-4 grid sm:grid-cols-2 gap-x-6 gap-y-2 text-sm">
            <div className="flex justify-between border-b border-slate-100 py-1.5">
              <span className="text-slate-500">Sync terakhir</span>
              <span className="font-semibold text-[#0a2350]">{fmtWhen(state?.last_run_at)}</span>
            </div>
            <div className="flex justify-between border-b border-slate-100 py-1.5">
              <span className="text-slate-500">Siklus penuh terakhir</span>
              <span className="font-semibold text-[#0a2350]">{fmtWhen(state?.last_completed_at)}</span>
            </div>
            <div className="flex justify-between border-b border-slate-100 py-1.5">
              <span className="text-slate-500">Halaman terakhir</span>
              <span className="font-semibold text-[#0a2350]">{fmt(state?.last_run_pages)}</span>
            </div>
            <div className="flex justify-between border-b border-slate-100 py-1.5">
              <span className="text-slate-500">Bootstrap</span>
              <span className="font-semibold text-[#0a2350]">{state?.bootstrap_done ? "selesai" : "berjalan"}</span>
            </div>
          </div>
        </div>

        <div className="mt-6 rounded-2xl border border-slate-200 bg-white p-5 text-sm text-slate-600 leading-relaxed">
          <div className="text-xs font-bold uppercase tracking-widest text-slate-500 mb-2">Cara kerja</div>
          <ul className="space-y-1.5 list-disc pl-5">
            <li>NVD memaginasi <strong>ascending</strong> berdasarkan tanggal publikasi, jadi sinkronisasi berjalan dari ekor katalog (entri terbaru) mundur ke belakang — kartu statistik langsung terisi.</li>
            <li>Kursor disimpan per halaman; restart backend tidak menghilangkan progres.</li>
            <li>Setiap run dibatasi agar lease scheduler tidak ditahan lama; run berikutnya melanjutkan otomatis.</li>
            <li>Tanpa <code>NVD_API_KEY</code> laju dibatasi 5 request / 30 detik (jeda 7 s). Set environment variable tersebut untuk jeda 1 s.</li>
          </ul>
        </div>
      </div>
    </div>
  );
};

export default AdminCveTracker;
