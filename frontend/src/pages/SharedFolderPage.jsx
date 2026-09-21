import React, { useState, useEffect } from "react";
import { api } from "../portal/api";
import { FileText, Download, Lock, Eye, ExternalLink, AlertCircle } from "lucide-react";

const SharedFolderPage = ({ match }) => {
  const token = match.params.token;
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [showPassword, setShowPassword] = useState(false);
  const [password, setPassword] = useState("");
  const [unlockToken, setUnlockToken] = useState(null);
  const [unlocking, setUnlocking] = useState(false);

  const fetchFolder = async () => {
    try {
      const headers = unlockToken
        ? { Authorization: `Bearer ${unlockToken}`, "X-Skip-401-Redirect": "true" }
        : { "X-Skip-401-Redirect": "true" };
      const r = await api.get(`/documents/shared/${token}`, { headers });
      setData(r.data);
      setError("");
    } catch (e) {
      if (e.response?.status === 401 && e.response?.data?.detail?.includes("Password")) {
        setShowPassword(true);
        setError("Folder ini dilindungi password");
      } else {
        setError(e.response?.data?.detail || "Gagal memuat folder");
      }
    } finally {
      setLoading(false);
    }
  };

  const handleUnlock = async () => {
    setUnlocking(true);
    try {
      const r = await api.post(
        `/documents/shared/${token}/unlock`,
        { password },
        { headers: { "X-Skip-401-Redirect": "true" } }
      );
      setUnlockToken(r.data?.token);
      setShowPassword(false);
      setPassword("");
      await fetchFolder();
    } catch (e) {
      setError(e.response?.data?.detail || "Password salah");
    } finally {
      setUnlocking(false);
    }
  };

  useEffect(() => {
    fetchFolder();
  }, [token, unlockToken]);

  const downloadFile = (did, filename) => {
    const headers = unlockToken ? { Authorization: `Bearer ${unlockToken}` } : {};
    const url = `${api.defaults.baseURL}/documents/shared/${token}/file/${did}`;
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    a.target = "_blank";
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
  };

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-white">
        <div className="flex flex-col items-center gap-3">
          <div className="w-10 h-10 rounded-full border-2 border-[#0a2540] border-t-transparent animate-spin"></div>
          <div className="text-xs uppercase tracking-widest text-slate-500">Memuat…</div>
        </div>
      </div>
    );
  }

  if (error && !data) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-white px-4">
        <div className="max-w-md text-center">
          <AlertCircle className="h-16 w-16 text-red-400 mx-auto mb-4" />
          <h1 className="text-xl font-bold text-[#0a2350] mb-2">Tidak Dapat Membuka</h1>
          <p className="text-slate-600">{error}</p>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-white">
      <header className="border-b border-slate-200 bg-white">
        <div className="max-w-4xl mx-auto px-4 py-6">
          <div className="flex items-center gap-2 text-sm text-slate-500 mb-2">
            <span>INTERCLOUD</span>
            <span>/</span>
            <span>Shared Folder</span>
          </div>
          <h1 className="text-2xl font-bold text-[#0a2350]">{data?.folder?.name || "Folder"}</h1>
          <p className="text-sm text-slate-500 mt-1">{data?.folder?.path || ""}</p>
          {data?.folder?.path && (
            <p className="text-[11px] text-slate-400 mt-1 font-mono">{data.folder.path}</p>
          )}
        </div>
      </header>

      <main className="max-w-4xl mx-auto px-4 py-8">
        {showPassword && (
          <div className="rounded-xl border border-slate-200 p-6 mb-6 bg-slate-50" role="alert">
            <Lock className="h-5 w-5 text-slate-400 mb-2" />
            <h2 className="text-lg font-bold text-[#0a2350] mb-1">Folder Dilindungi Password</h2>
            <p className="text-sm text-slate-600 mb-4">Masukkan password untuk mengakses isi folder ini.</p>
            <div className="flex gap-2 max-w-xs">
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && handleUnlock()}
                className="flex-1 px-3 py-2 border border-slate-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-[#0a2350]"
                placeholder="Password"
                autoFocus
              />
              <button
                onClick={handleUnlock}
                disabled={unlocking || !password.trim()}
                className="px-4 py-2 bg-[#0a2350] text-white rounded-lg text-sm font-medium hover:bg-[#0a2350]/90 disabled:opacity-50"
              >
                {unlocking ? "Membuka…" : "Buka"}
              </button>
            </div>
            {error && <p className="text-red-600 text-sm mt-2">{error}</p>}
          </div>
        )}

        {data && (
          <>
            <div className="mb-4 flex items-center justify-between">
              <h2 className="text-lg font-bold text-[#0a2350]">Dokumen ({data.documents?.length || 0})</h2>
            </div>

            {data.documents?.length === 0 ? (
              <div className="rounded-xl border border-slate-200 p-8 text-center">
                <FileText className="h-12 w-12 text-slate-300 mx-auto mb-3" />
                <p className="text-slate-500">Tidak ada dokumen di folder ini.</p>
              </div>
            ) : (
              <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4">
                {data.documents.map((d) => (
                  <article
                    key={d.id}
                    className="rounded-xl border border-slate-200 p-5 hover:border-[#0a2350]/30 transition-colors"
                  >
                    <div className="flex items-start justify-between">
                      <div className="h-10 w-10 rounded-lg bg-[#0a2350] flex items-center justify-center">
                        <FileText className="h-5 w-5 text-[#f5b120]" />
                      </div>
                      <span className="text-[10px] font-bold uppercase tracking-widest text-[#f5b120]">
                        {d.category || "Dokumen"}
                      </span>
                    </div>
                    <h3 className="mt-4 text-base font-extrabold text-[#0a2350] leading-tight truncate" title={d.title}>
                      {d.title}
                    </h3>
                    <div className="text-xs text-slate-500 mt-1">
                      {d.customer_name || "-"} · {new Date(d.created_at).toLocaleDateString("id-ID", {
                        day: "numeric",
                        month: "short",
                        year: "numeric",
                      })}
                    </div>
                    <div className="mt-2 flex flex-wrap items-center gap-2 text-[10px] font-bold uppercase tracking-wider">
                      <span
                        className={`px-2 py-0.5 rounded-full border ${
                          d.content_type?.includes("pdf")
                            ? "bg-red-50 text-red-700 border-red-200"
                            : d.content_type?.includes("spreadsheet") || d.content_type?.includes("excel")
                            ? "bg-green-50 text-green-700 border-green-200"
                            : d.content_type?.includes("presentation") || d.content_type?.includes("powerpoint")
                            ? "bg-orange-50 text-orange-700 border-orange-200"
                            : d.content_type?.includes("word") || d.content_type?.includes("wordprocessingml")
                            ? "bg-blue-50 text-blue-700 border-blue-200"
                            : "bg-slate-50 text-slate-700 border-slate-200"
                        }`}
                      >
                        {d.content_type?.includes("pdf")
                          ? "PDF"
                          : d.content_type?.includes("spreadsheet") || d.content_type?.includes("excel")
                          ? "XLSX"
                          : d.content_type?.includes("presentation") || d.content_type?.includes("powerpoint")
                          ? "PPTX"
                          : d.content_type?.includes("word") || d.content_type?.includes("wordprocessingml")
                          ? "DOCX"
                          : "FILE"}
                      </span>
                    </div>
                    <div className="mt-4 flex flex-wrap gap-2">
                      {d.can_download && (
                        <button
                          onClick={() => downloadFile(d.id, d.filename || d.stored_name || "file")}
                          className="flex-1 flex items-center justify-center gap-1.5 px-3 py-2 bg-[#0a2350] text-white text-sm font-medium rounded-lg hover:bg-[#0a2350]/90"
                        >
                          <Download className="h-3.5 w-3.5" />
                          Download
                        </button>
                      )}
                      <a
                        href={`${api.defaults.baseURL}/documents/shared/${token}/file/${d.id}`}
                        target="_blank"
                        rel="noreferrer"
                        className="flex-1 flex items-center justify-center gap-1.5 px-3 py-2 border border-slate-300 text-slate-700 text-sm font-medium rounded-lg hover:bg-slate-50"
                      >
                        <ExternalLink className="h-3.5 w-3.5" />
                        Buka
                      </a>
                    </div>
                  </article>
                ))}
              </div>
            )}
          </>
        )}
      </main>

      <footer className="border-t border-slate-200 bg-white">
        <div className="max-w-4xl mx-auto px-4 py-4 text-center text-xs text-slate-400">
          INTERCLOUD · Shared Folder Access
        </div>
      </footer>
    </div>
  );
};

export default SharedFolderPage;