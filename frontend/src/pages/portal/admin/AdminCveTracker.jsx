import React, { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  RefreshCw, Database, AlertTriangle, CheckCircle2, Loader2, Play,
  RotateCcw, ExternalLink, Clock, FileText, Search,
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

  // CVE -> article picker. Publishing used to mean copying a CVE by hand into
  // the article editor; the references are long enough that transcriptions rot.
  const [pickQ, setPickQ] = useState("");
  const [pickSev, setPickSev] = useState("");
  const [picks, setPicks] = useState(null);
  const [pickLoading, setPickLoading] = useState(false);
  const [publishBusy, setPublishBusy] = useState("");
  const [published, setPublished] = useState(null);

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

  const searchCves = useCallback(async () => {
    setPickLoading(true);
    try {
      const params = { limit: 20 };
      if (pickQ.trim()) params.q = pickQ.trim();
      if (pickSev) params.severity = pickSev;
      const r = await api.get("/public/cve", { params });
      setPicks(r.data.items || []);
    } catch (e) {
      setErr(formatApiError(e));
      setPicks([]);
    } finally { setPickLoading(false); }
  }, [pickQ, pickSev]);

  const publishAsArticle = async (cveId, status) => {
    setPublishBusy(cveId);
    setPublished(null);
    setErr("");
    try {
      const r = await api.post(`/admin/cve/${cveId}/publish-article`, { status });
      setPublished(r.data);
      setMsg(
        r.data.action === "created"
          ? `${cveId} dijadikan artikel (${status}). Buka di menu Artikel untuk menyunting.`
          : `Artikel untuk ${cveId} diperbarui (${status}).`
      );
    } catch (e) {
      setErr(formatApiError(e));
    } finally { setPublishBusy(""); }
  };

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

        <div className="mt-6 rounded-2xl border border-slate-200 bg-white p-5">
          <div className="text-sm font-extrabold text-[#0a2350] flex items-center gap-2">
            <FileText className="h-4 w-4 text-[#f5b120]" /> Jadikan CVE sebagai artikel
          </div>
          <p className="mt-1 text-xs text-slate-500">
            Ambil CVE dari indeks, lalu terbitkan sebagai artikel blog dalam satu klik. Ringkasan,
            skor, produk terdampak, dan tautan referensi disusun otomatis dari data NVD.
            Menerbitkan ulang CVE yang sama akan memperbarui artikel lama, bukan membuat duplikat.
          </p>

          <div className="mt-4 flex flex-wrap items-end gap-2">
            <div className="min-w-[220px] flex-1">
              <label className="block text-[11px] font-bold uppercase tracking-widest text-slate-500 mb-1">
                Cari CVE
              </label>
              <input
                value={pickQ}
                onChange={(e) => setPickQ(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter") searchCves(); }}
                placeholder="CVE-2026-… atau kata kunci produk"
                className="w-full h-10 rounded-lg border border-slate-300 px-3 text-sm"
                data-testid="cve-pick-query"
              />
            </div>
            <div>
              <label className="block text-[11px] font-bold uppercase tracking-widest text-slate-500 mb-1">
                Keparahan
              </label>
              <select
                value={pickSev}
                onChange={(e) => setPickSev(e.target.value)}
                className="h-10 rounded-lg border border-slate-300 px-3 text-sm"
                data-testid="cve-pick-severity"
              >
                <option value="">Semua</option>
                <option value="critical">Critical</option>
                <option value="high">High</option>
                <option value="medium">Medium</option>
                <option value="low">Low</option>
              </select>
            </div>
            <button
              onClick={searchCves}
              disabled={pickLoading}
              className="inline-flex items-center gap-2 h-10 px-4 rounded-lg bg-[#0a2350] text-white text-sm font-bold hover:bg-[#f5b120] hover:text-[#0a2350] disabled:opacity-60"
              data-testid="cve-pick-search"
            >
              {pickLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />}
              Cari
            </button>
          </div>

          {picks && picks.length === 0 && (
            <div className="mt-4 text-sm text-slate-500" data-testid="cve-pick-empty">
              Tidak ada CVE yang cocok.
            </div>
          )}

          {picks && picks.length > 0 && (
            <div className="mt-4 overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-[10px] uppercase tracking-widest text-slate-500 border-b border-slate-200">
                    <th className="py-2 pr-3">CVE</th>
                    <th className="py-2 pr-3">Keparahan</th>
                    <th className="py-2 pr-3">Skor</th>
                    <th className="py-2 pr-3">Terbit</th>
                    <th className="py-2">Aksi</th>
                  </tr>
                </thead>
                <tbody>
                  {picks.map((c) => (
                    <tr key={c.cve_id} className="border-b border-slate-100 last:border-0">
                      <td className="py-2 pr-3 font-mono font-semibold text-[#0a2350]">{c.cve_id}</td>
                      <td className="py-2 pr-3">
                        <span className="text-[11px] font-bold uppercase">{c.severity}</span>
                      </td>
                      <td className="py-2 pr-3 tabular-nums">{c.cvss_score ?? "—"}</td>
                      <td className="py-2 pr-3 text-[12px] text-slate-500">
                        {c.published ? String(c.published).slice(0, 10) : "—"}
                      </td>
                      <td className="py-2">
                        <div className="flex gap-2">
                          <button
                            onClick={() => publishAsArticle(c.cve_id, "draft")}
                            disabled={publishBusy === c.cve_id}
                            className="inline-flex items-center gap-1 text-[12px] font-bold text-slate-700 border border-slate-300 rounded-lg px-2.5 py-1.5 hover:border-[#f5b120] disabled:opacity-50"
                            data-testid={`cve-publish-draft-${c.cve_id}`}
                          >
                            {publishBusy === c.cve_id
                              ? <Loader2 className="h-3.5 w-3.5 animate-spin" />
                              : <FileText className="h-3.5 w-3.5" />} Draft
                          </button>
                          <button
                            onClick={() => publishAsArticle(c.cve_id, "published")}
                            disabled={publishBusy === c.cve_id}
                            className="inline-flex items-center gap-1 text-[12px] font-bold text-white bg-[#0a2350] rounded-lg px-2.5 py-1.5 hover:bg-[#f5b120] hover:text-[#0a2350] disabled:opacity-50"
                            data-testid={`cve-publish-live-${c.cve_id}`}
                          >
                            Terbitkan
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {published && (
            <div className="mt-3 rounded-xl border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-800" data-testid="cve-publish-result">
              <div className="font-bold">{published.title}</div>
              <div className="mt-1 text-[12px]">
                status: <b>{published.status}</b> · aksi: {published.action} ·{" "}
                <a href={published.url} target="_blank" rel="noreferrer" className="underline">
                  lihat artikel <ExternalLink className="inline h-3 w-3" />
                </a>
              </div>
            </div>
          )}
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
