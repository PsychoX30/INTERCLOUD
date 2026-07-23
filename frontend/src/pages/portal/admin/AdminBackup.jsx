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

  useEffect(() => { api.get("/admin/system/version").then(({ data }) => setVersion(data)).catch(() => {}); }, []);

  const runUpdate = async () => {
    if (!window.confirm("This will git-pull the latest release, install any new dependencies, rebuild the frontend, and restart the backend. A full DB backup is taken automatically before anything changes. Continue?")) return;
    setUpdating(true); setMsg(null); setUpdateLog("");
    try {
      const { data } = await api.post("/admin/system/update?confirm=UPDATE");
      setUpdateLog(data.log_tail || data.status || "");
      setMsg({ kind: "ok", text: `Update complete. ${data.status || ""}` });
      const v = await api.get("/admin/system/version");
      setVersion(v.data);
    } catch (e) {
      const detail = e?.response?.data?.detail || e.message;
      setUpdateLog(typeof detail === "string" ? detail : JSON.stringify(detail));
      setMsg({ kind: "error", text: `Update failed. See log below.` });
    } finally { setUpdating(false); }
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
      setMsg({ kind: "ok", text: `Restore complete — ${body.bytes_received} bytes replayed.` });
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
          Manage full snapshots of the portal — download a backup archive, restore from an existing
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
              Data is <b>always preserved</b> — a full DB snapshot is taken automatically before anything changes.
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

      {/* Factory Reset — DANGER ZONE */}
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
                <li><b>Deleted:</b> every other collection — clients, orders, invoices, tickets, services, MikroTik devices, articles, assets, etc.</li>
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
          <li>Best practice: download a backup <b>immediately before</b> any maintenance activity — MikroTik migrations, schema changes, bulk imports.</li>
          <li>Store archives off-server (cloud storage, S3, private git-lfs) so the loss of this preview environment doesn't also lose the recovery snapshot.</li>
          <li>Updates auto-snapshot the DB into <span className="font-mono">/var/backups/intercloud/pre-update-*.archive.gz</span> (30-day retention).</li>
        </ul>
      </div>
    </div>
  );
};

export default AdminBackup;

