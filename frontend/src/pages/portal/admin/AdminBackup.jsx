import React, { useState, useRef } from "react";
import { Download, Upload, ShieldAlert, Loader2, CheckCircle2, AlertTriangle } from "lucide-react";
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
        <h1 className="text-2xl md:text-3xl font-bold text-[#0a2350]">Backup &amp; Restore</h1>
        <p className="mt-1.5 text-sm text-slate-500 max-w-2xl">
          Download a full, gzipped snapshot of every database collection — users, invoices, tickets,
          MikroTik devices, articles, branding, everything. Keep the file safe; restoring from it
          will wipe and replace the live data.
        </p>
      </div>

      {msg && (
        <div className={`mb-6 rounded-xl px-4 py-3 text-sm border flex items-start gap-2 ${msg.kind === "error" ? "bg-red-50 border-red-200 text-red-800" : "bg-emerald-50 border-emerald-200 text-emerald-800"}`}
             data-testid="admin-backup-msg">
          {msg.kind === "error" ? <AlertTriangle className="h-4 w-4 flex-shrink-0 mt-0.5" /> : <CheckCircle2 className="h-4 w-4 flex-shrink-0 mt-0.5" />}
          <div>{msg.text}</div>
        </div>
      )}

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

      <div className="mt-6 rounded-2xl border border-slate-200 bg-slate-50/40 p-5 text-sm text-slate-600">
        <div className="font-semibold text-[#0a2350] mb-1.5">Notes</div>
        <ul className="list-disc pl-5 space-y-1 text-[13px]">
          <li>Backups use <span className="font-mono">mongodump --archive --gzip</span>. Restores use <span className="font-mono">mongorestore --archive --gzip --drop</span>.</li>
          <li>Best practice: download a backup <b>immediately before</b> any maintenance activity — MikroTik migrations, schema changes, bulk imports.</li>
          <li>Store archives off-server (cloud storage, S3, private git-lfs) so the loss of this preview environment doesn't also lose the recovery snapshot.</li>
          <li>Restore triggers all indexes to be rebuilt at first read; expect a brief burst of CPU right after.</li>
        </ul>
      </div>
    </div>
  );
};

export default AdminBackup;
