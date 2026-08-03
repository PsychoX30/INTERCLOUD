import React, { useState, useRef, useEffect } from "react";
import { Download, Upload, ShieldAlert, Loader2, CheckCircle2, AlertTriangle, RefreshCw, GitBranch, Skull } from "lucide-react";
import { api } from "../../../portal/api";

const API_BASE = process.env.REACT_APP_BACKEND_URL;
const TOKEN_KEY = "ic_portal_token";

const AdminBackup = () => {
  const [downloading, setDownloading] = useState(false);
  const [restoring, setRestoring] = useState(false);
  const [msg, setMsg] = useState(null);
  const [file, setFile] = useState(null);
  const [confirmText, setConfirmText] = useState("");
  const fileRef = useRef(null);

  // ---------- Factory reset ----------
  const [frConfirmText, setFrConfirmText] = useState("");
  const [frPassword, setFrPassword] = useState("");
  const [factoryResetting, setFactoryResetting] = useState(false);
  const [frSummary, setFrSummary] = useState(null);

  const factoryReset = async () => {
    if (frConfirmText !== "FACTORY RESET") { setMsg({ kind: "error", text: 'Type "FACTORY RESET" exactly to confirm.' }); return; }
    if (!frPassword) { setMsg({ kind: "error", text: "Admin password is required." }); return; }
    if (!window.confirm("This will PERMANENTLY delete ALL data except the settings collection and admin users. A safety snapshot is taken automatically. Continue?")) return;
    setFactoryResetting(true); setMsg(null); setFrSummary(null);
    try {
      const { data } = await api.post("/admin/system/factory-reset", {
        admin_password: frPassword,
        confirm: "FACTORY RESET",
      });
      setFrSummary(data);
      setMsg({ kind: "ok", text: data.message || "Factory reset complete." });
      setFrConfirmText(""); setFrPassword("");
    } catch (e) {
      const detail = e?.response?.data?.detail || e.message;
      setMsg({ kind: "error", text: `Factory reset failed: ${typeof detail === "string" ? detail : JSON.stringify(detail)}` });
    } finally { setFactoryResetting(false); }
  };
  // -----------------------------------

  // ---------- System update ----------
  const [version, setVersion] = useState(null);
  const [updating, setUpdating] = useState(false);
  const [updateLog, setUpdateLog] = useState("");
  const pollRef = useRef(null);

  useEffect(() => { api.get("/admin/system/version").then(({ data }) => setVersion(data)).catch(() => {}); }, []);

  const pollOnce = async () => {
    try {
      const { data } = await api.get("/admin/system/update/status");
      if (data.log_tail) setUpdateLog(data.log_tail);
      if (data.running) return true;
      setUpdating(false);
      if (data.state === "ok") {
        setMsg({ kind: "ok", text: `Update selesai. ${data.status || ""}` });
      } else if (data.state === "failed") {
        setMsg({ kind: "error", text: `Update gagal (exit ${data.exit_code}). Lihat log di bawah.` });
      }
      api.get("/admin/system/version").then(({ data: v }) => setVersion(v)).catch(() => {});
      return false;
    } catch {
      return true; // backend sedang restart di tengah update - terus polling
    }
  };

  const startPolling = () => {
    if (pollRef.current) clearInterval(pollRef.current);
    pollRef.current = setInterval(async () => {
      const keep = await pollOnce();
      if (!keep && pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
    }, 3000);
  };

  useEffect(() => () => { if (pollRef.current) clearInterval(pollRef.current); }, []);

  // Resume tampilan bila update masih berjalan (mis. halaman di-refresh)
  useEffect(() => {
    api.get("/admin/system/update/status").then(({ data }) => {
      if (data.running) { setUpdating(true); setUpdateLog(data.log_tail || ""); startPolling(); }
    }).catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const runUpdate = async () => {
    if (!window.confirm("This will git-pull the latest release, install any new dependencies, rebuild the frontend, and restart the backend. A full DB backup is taken automatically before anything changes. Continue?")) return;
    setUpdating(true); setMsg(null); setUpdateLog("");
    try {
      await api.post("/admin/system/update?confirm=UPDATE");
      startPolling();
    } catch (e) {
      const detail = e?.response?.data?.detail || e.message;
      setUpdateLog(typeof detail === "string" ? detail : JSON.stringify(detail));
      setMsg({ kind: "error", text: `Update failed to start. See log below.` });
      setUpdating(false);
    }
  };
  // ---------------------------------

  const download = async () => {
    setDownloading(true); setMsg(null);
    try {
      const token = localStorage.getItem(TOKEN_KEY) || "";
      const res = await fetch(`${API_BASE}/api/portal/admin/backup/download`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}: ${await res.text()}`);
      const cd = res.headers.get("Content-Disposition") || "";
      const nameMatch = /filename="?([^"]+)"?/.exec(cd);
      const filename = nameMatch ? nameMatch[1] : `intercloud-backup-${Date.now()}.archive.gz`;
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url; a.download = filename; document.body.appendChild(a);
      a.click(); a.remove(); URL.revokeObjectURL(url);
      setMsg({ kind: "ok", text: `Downloaded ${filename} (${(blob.size / 1024).toFixed(1)} KB).` });
    } catch (e) {
      setMsg({ kind: "error", text: `Backup failed: ${e.message}` });
    } finally { setDownloading(false); }
  };

  const restore = async () => {
    if (!file) { setMsg({ kind: "error", text: "Pick a backup archive first." }); return; }
    if (confirmText !== "REPLACE") { setMsg({ kind: "error", text: "Type REPLACE to confirm." }); return; }
    if (!window.confirm(`This will WIPE every collection in the archive and restore the uploaded snapshot. Continue?`)) return;
    setRestoring(true); setMsg(null);
    try {
      const token = localStorage.getItem(TOKEN_KEY) || "";
      const res = await fetch(`${API_BASE}/api/portal/admin/backup/restore?confirm=REPLACE`, {
        method: "POST",
        headers: { "Authorization": `Bearer ${token}`, "Content-Type": "application/gzip" },
        body: file,
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(body.detail || `HTTP ${res.status}`);
      setMsg({ kind: "ok", text: `Restore complete - ${body.bytes_received} bytes replayed.` });
      setFile(null); setConfirmText("");
      if (fileRef.current) fileRef.current.value = "";
    } catch (e) {
      setMsg({ kind: "error", text: `Restore failed: ${e.message}` });
    } finally { setRestoring(false); }
  };

  return (
    <div className="p-6 md:p-8 max-w-4xl mx-auto" data-testid="admin-backup-page">
      <div className="mb-8">
        <h1 className="text-2xl md:text-3xl font-bold text-[#0a2350]">Backup, Restore &amp; Update</h1>
        <p className="mt-1.5 text-sm text-slate-500 max-w-2xl">
          Manage full snapshots of the portal - download a backup archive, restore from an existing
          one, or roll the running system forward to the latest release from GitHub.
        </p>
      </div>

      {msg && (
        <div className={`mb-6 rounded-xl px-4 py-3 text-sm border flex items-start gap-2 ${msg.kind === "error" ? "bg-red-50 border-red-200 text-red-800" : "bg-emerald-50 border-emerald-200 text-emerald-800"}`}
             data-testid="admin-backup-msg">
          {msg.kind === "error" ? <AlertTriangle className="h-4 w-4 flex-shrink-0 mt-0.5" /> : <CheckCircle2 className="h-4 w-4 flex-shrink-0 mt-0.5" />}
          <div>{msg.text}</div>
        </div>
      )}

      <BackupHistory />

      {/* System update */}
      <div className="rounded-2xl border border-slate-200 bg-white p-6 mb-6 shadow-sm" data-testid="admin-update-card">
        <div className="flex items-start gap-4">
          <div className="h-12 w-12 rounded-xl bg-indigo-100 text-indigo-700 flex items-center justify-center flex-shrink-0">
            <RefreshCw className="h-6 w-6" />
          </div>
          <div className="flex-1">
            <div className="text-lg font-bold text-[#0a2350]">Update system from GitHub</div>
            <div className="mt-1 text-sm text-slate-500">
              Pulls the latest release, installs any new dependencies, rebuilds the frontend, and restarts the backend.
              Data is <b>always preserved</b> - a full DB snapshot is taken automatically before anything changes.
            </div>

            {version && (
              <div className="mt-3 rounded-lg bg-slate-50 border border-slate-200 px-3 py-2 text-xs font-mono flex items-center gap-2 flex-wrap"
                   data-testid="admin-update-version">
                <span className="inline-flex items-center gap-1 text-slate-500"><GitBranch className="h-3.5 w-3.5" /> {version.branch || "?"}</span>
                <span className="text-slate-300">·</span>
                <span className="text-[#0a2350] font-bold">@ {version.short || version.sha?.slice(0, 7) || "unknown"}</span>
                {version.subject && (<><span className="text-slate-300">·</span><span className="text-slate-500 truncate max-w-md">{version.subject}</span></>)}
                {version.date && (<span className="ml-auto text-slate-400">{version.date.slice(0, 16)}</span>)}
              </div>
            )}

            <button onClick={runUpdate} disabled={updating}
                    className="mt-4 inline-flex items-center gap-2 px-5 py-2.5 rounded-lg bg-indigo-600 hover:bg-indigo-700 text-white text-sm font-semibold disabled:opacity-60"
                    data-testid="admin-update-run">
              {updating ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
              {updating ? "Updating (may take a few minutes)…" : "Update to latest release"}
            </button>

            {updateLog && (
              <pre className="mt-4 rounded-lg bg-slate-900 text-emerald-200 text-[11px] p-3 overflow-x-auto max-h-64 whitespace-pre-wrap"
                   data-testid="admin-update-log">{updateLog}</pre>
            )}
          </div>
        </div>
      </div>

      {/* Download */}
      <div className="rounded-2xl border border-slate-200 bg-white p-6 mb-6 shadow-sm">
        <div className="flex items-start gap-4">
          <div className="h-12 w-12 rounded-xl bg-emerald-100 text-emerald-700 flex items-center justify-center flex-shrink-0">
            <Download className="h-6 w-6" />
          </div>
          <div className="flex-1">
            <div className="text-lg font-bold text-[#0a2350]">Download full backup</div>
            <div className="mt-1 text-sm text-slate-500">
              A single <span className="font-mono">.archive.gz</span> file (mongodump format).
              Filename includes a UTC timestamp so you can keep multiple snapshots.
            </div>
            <button onClick={download} disabled={downloading}
                    className="mt-4 inline-flex items-center gap-2 px-5 py-2.5 rounded-lg bg-[#0a2350] hover:bg-[#1a355c] text-white text-sm font-semibold disabled:opacity-60"
                    data-testid="admin-backup-download">
              {downloading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />}
              {downloading ? "Preparing snapshot…" : "Download backup now"}
            </button>
          </div>
        </div>
      </div>

      {/* Restore */}
      <div className="rounded-2xl border border-red-200 bg-white p-6 shadow-sm">
        <div className="flex items-start gap-4">
          <div className="h-12 w-12 rounded-xl bg-red-100 text-red-700 flex items-center justify-center flex-shrink-0">
            <ShieldAlert className="h-6 w-6" />
          </div>
          <div className="flex-1">
            <div className="text-lg font-bold text-[#0a2350]">Restore from backup</div>
            <div className="mt-1 text-sm text-red-700 bg-red-50 border border-red-200 rounded-lg px-3 py-2">
              <b>Destructive action.</b> Every collection contained in the uploaded archive will be
              dropped and replaced. Data added since the backup was taken will be lost. Only use during
              a planned maintenance window or after a confirmed data-loss incident.
            </div>

            <div className="mt-5 space-y-4">
              <div>
                <label className="text-xs font-semibold text-slate-600 uppercase tracking-widest">
                  1. Choose backup archive
                </label>
                <input ref={fileRef} type="file" accept=".gz,.archive,application/gzip,application/octet-stream"
                       onChange={(e) => setFile(e.target.files?.[0] || null)}
                       className="mt-1.5 block w-full text-sm border border-slate-200 rounded-lg px-3 py-2"
                       data-testid="admin-backup-file" />
                {file && (
                  <div className="mt-1 text-xs text-slate-500">
                    {file.name} · {(file.size / 1024).toFixed(1)} KB
                  </div>
                )}
              </div>

              <div>
                <label className="text-xs font-semibold text-slate-600 uppercase tracking-widest">
                  2. Type <span className="font-mono text-red-700">REPLACE</span> to confirm
                </label>
                <input value={confirmText} onChange={(e) => setConfirmText(e.target.value.toUpperCase())}
                       placeholder="REPLACE"
                       className="mt-1.5 block w-full max-w-xs font-mono text-sm border border-slate-200 rounded-lg px-3 py-2"
                       data-testid="admin-backup-confirm" />
              </div>

              <button onClick={restore} disabled={restoring || !file || confirmText !== "REPLACE"}
                      className="inline-flex items-center gap-2 px-5 py-2.5 rounded-lg bg-red-600 hover:bg-red-700 text-white text-sm font-semibold disabled:opacity-40 disabled:cursor-not-allowed"
                      data-testid="admin-backup-restore">
                {restoring ? <Loader2 className="h-4 w-4 animate-spin" /> : <Upload className="h-4 w-4" />}
                {restoring ? "Restoring…" : "Restore backup"}
              </button>
            </div>
          </div>
        </div>
      </div>

      {/* Factory Reset - DANGER ZONE */}
      <div className="mt-6 rounded-2xl border-2 border-red-300 bg-gradient-to-br from-red-50/60 to-white p-6 shadow-sm" data-testid="admin-factory-reset-card">
        <div className="flex items-start gap-4">
          <div className="h-12 w-12 rounded-xl bg-red-600 text-white flex items-center justify-center flex-shrink-0">
            <Skull className="h-6 w-6" />
          </div>
          <div className="flex-1">
            <div className="text-lg font-bold text-red-800">Factory Reset (Reset to fresh install)</div>
            <div className="mt-1 text-sm text-red-800 bg-red-100 border border-red-300 rounded-lg px-3 py-2">
              <b>Irreversible.</b> This wipes every collection back to a fresh-install state.
              <ul className="list-disc pl-5 mt-1 text-[13px]">
                <li><b>Preserved:</b> the entire <span className="font-mono">settings</span> collection (branding + landing CMS) and all users with <span className="font-mono">role = admin</span>.</li>
                <li><b>Deleted:</b> every other collection - clients, orders, invoices, tickets, services, MikroTik devices, articles, assets, etc.</li>
                <li>A safety snapshot is taken automatically to <span className="font-mono">/var/backups/intercloud/pre-factory-reset-*.archive.gz</span> before anything is dropped.</li>
              </ul>
            </div>

            <div className="mt-5 space-y-4">
              <div>
                <label className="text-xs font-semibold text-slate-600 uppercase tracking-widest">
                  1. Type <span className="font-mono text-red-700">FACTORY RESET</span> to confirm
                </label>
                <input value={frConfirmText} onChange={(e) => setFrConfirmText(e.target.value.toUpperCase())}
                       placeholder="FACTORY RESET"
                       className="mt-1.5 block w-full max-w-xs font-mono text-sm border border-slate-200 rounded-lg px-3 py-2"
                       data-testid="admin-factory-reset-confirm" />
              </div>

              <div>
                <label className="text-xs font-semibold text-slate-600 uppercase tracking-widest">
                  2. Re-enter your admin password
                </label>
                <input type="password" value={frPassword} onChange={(e) => setFrPassword(e.target.value)}
                       placeholder="Admin password"
                       autoComplete="current-password"
                       className="mt-1.5 block w-full max-w-xs text-sm border border-slate-200 rounded-lg px-3 py-2"
                       data-testid="admin-factory-reset-password" />
              </div>

              <button onClick={factoryReset}
                      disabled={factoryResetting || frConfirmText !== "FACTORY RESET" || !frPassword}
                      className="inline-flex items-center gap-2 px-5 py-2.5 rounded-lg bg-red-700 hover:bg-red-800 text-white text-sm font-semibold disabled:opacity-40 disabled:cursor-not-allowed"
                      data-testid="admin-factory-reset-run">
                {factoryResetting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Skull className="h-4 w-4" />}
                {factoryResetting ? "Wiping database…" : "Factory reset now"}
              </button>

              {frSummary && (
                <div className="mt-4" data-testid="admin-factory-reset-summary">
                  {frSummary.safety_backup && (
                    <div className="text-xs font-mono text-slate-600 mb-2">
                      Safety snapshot: {frSummary.safety_backup}
                    </div>
                  )}
                  <div className="rounded-lg border border-slate-200 bg-white overflow-hidden">
                    <table className="w-full text-xs">
                      <thead className="bg-slate-50 text-slate-500 uppercase tracking-widest text-[10px]">
                        <tr>
                          <th className="text-left px-3 py-2">Collection</th>
                          <th className="text-right px-3 py-2">Result</th>
                        </tr>
                      </thead>
                      <tbody>
                        {Object.entries(frSummary.collections || {}).map(([name, info]) => (
                          <tr key={name} className="border-t border-slate-100">
                            <td className="px-3 py-1.5 font-mono">{name}</td>
                            <td className="px-3 py-1.5 text-right text-slate-600">
                              {info.dropped ? `dropped (${info.deleted ?? "?"} docs)` : `${info.deleted} deleted · kept ${info.kept}`}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      </div>

      <div className="mt-6 rounded-2xl border border-slate-200 bg-slate-50/40 p-5 text-sm text-slate-600">
        <div className="font-semibold text-[#0a2350] mb-1.5">Notes</div>
        <ul className="list-disc pl-5 space-y-1 text-[13px]">
          <li>Backups use <span className="font-mono">mongodump --archive --gzip</span>. Restores use <span className="font-mono">mongorestore --archive --gzip --drop</span>.</li>
          <li>Best practice: download a backup <b>immediately before</b> any maintenance activity - MikroTik migrations, schema changes, bulk imports.</li>
          <li>Store archives off-server (cloud storage, S3, private git-lfs) so the loss of this preview environment doesn't also lose the recovery snapshot.</li>
          <li>Updates auto-snapshot the DB into <span className="font-mono">/var/backups/intercloud/pre-update-*.archive.gz</span> (30-day retention).</li>
        </ul>
      </div>
    </div>
  );
};

const BackupHistory = () => {
  const [rows, setRows] = useState([]);
  const [busy, setBusy] = useState(false);
  const load = () => api.get("/admin/backup/history").then((r) => setRows(r.data)).catch(() => {});
  useEffect(() => { load(); }, []);
  const trigger = async () => {
    setBusy(true);
    try { await api.post("/admin/backup/trigger"); load(); } finally { setBusy(false); }
  };
  const dl = (b) => {
    const token = localStorage.getItem(TOKEN_KEY) || "";
    window.open(`${API_BASE}/api/portal/admin/backup/history/${b.id}/download?token=${encodeURIComponent(token)}`, "_blank");
  };
  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-6 mb-6 shadow-sm" data-testid="backup-history-card">
      <div className="flex items-center justify-between gap-3">
        <div>
          <div className="text-lg font-bold text-[#0a2350]">Riwayat backup</div>
          <div className="text-sm text-slate-500">Backup otomatis harian 03:30 + backup manual. 14 snapshot terjadwal terakhir disimpan.</div>
        </div>
        <button onClick={trigger} disabled={busy}
          className="px-4 py-2 rounded-xl bg-[#0a2350] text-white text-sm font-semibold inline-flex items-center gap-2 hover:bg-[#1a355c] disabled:opacity-50"
          data-testid="backup-trigger-btn">
          {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />} Backup sekarang
        </button>
      </div>
      {rows.length > 0 && (
        <div className="mt-4 divide-y divide-slate-100 text-sm" data-testid="backup-history-list">
          {rows.slice(0, 10).map((b) => (
            <div key={b.id} className="py-2 flex items-center gap-3">
              <span className="font-mono text-xs text-[#0a2350] flex-1 truncate">{b.filename}</span>
              <span className={`text-[9px] font-bold uppercase px-1.5 py-0.5 rounded ${b.kind === "scheduled" ? "bg-sky-100 text-sky-700" : "bg-amber-100 text-amber-700"}`}>{b.kind}</span>
              <span className="text-xs text-slate-400 whitespace-nowrap">{(b.size_bytes / 1024).toFixed(0)} KB</span>
              <span className="text-xs text-slate-400 whitespace-nowrap hidden sm:inline">{(b.created_at || "").slice(0, 16).replace("T", " ")}</span>
              <button onClick={() => dl(b)} className="text-slate-500 hover:text-[#f5b120]" title="Download" data-testid={`backup-dl-${b.id}`}><Download className="h-4 w-4" /></button>
            </div>
          ))}
        </div>
      )}
      {rows.length === 0 && <div className="mt-3 text-xs text-slate-400">Belum ada riwayat backup. Klik "Backup sekarang" untuk membuat snapshot pertama.</div>}
    </div>
  );
};

export default AdminBackup;

