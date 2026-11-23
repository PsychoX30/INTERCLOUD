import React, { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../../../portal/api";
import { useAuth } from "../../../portal/AuthContext";
import { PageHeader, Card, Loading, EmptyState, btnPrimary, btnSecondary, btnDanger, inputClass, labelClass } from "../ui";
import { UploadCloud, Trash2, Tag, Search, Copy, CheckCircle2, X, Loader2, MessageSquare, Settings2, Play, Music } from "lucide-react";
import { useUploadPolicy, acceptAttr, parseExtInput } from "./uploadPolicy";
import { toast } from "sonner";

const BACKEND = process.env.REACT_APP_BACKEND_URL;
export const mediaUrl = (m) => (m?.url?.startsWith("http") ? m.url : `${BACKEND}${m?.url || ""}`);

const AdminMediaLibrary = () => {
  const { policy, save } = useUploadPolicy();
  const [rows, setRows] = useState(null);
  const [q, setQ] = useState("");
  const [tag, setTag] = useState("");
  const [uploading, setUploading] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const fileRef = useRef(null);

  const load = async () => {
    const r = await api.get("/admin/media");
    setRows(r.data || []);
  };
  useEffect(() => { load(); }, []);

  const allTags = useMemo(() => {
    const s = new Set();
    (rows || []).forEach((m) => (m.tags || []).forEach((t) => s.add(t)));
    return [...s].sort();
  }, [rows]);

  const filtered = useMemo(() => (rows || []).filter((m) => {
    if (tag && !(m.tags || []).includes(tag)) return false;
    if (q && !(`${m.filename} ${m.alt_text}`.toLowerCase().includes(q.toLowerCase()))) return false;
    return true;
  }), [rows, q, tag]);

  const upload = async (file) => {
    if (!file) return;
    const ext = (file.name.split(".").pop() || "").toLowerCase();
    if (!policy.media_extensions.includes(ext)) {
      toast.error(`Format .${ext} belum diizinkan. Tambahkan lewat Upload settings.`);
      return;
    }
    if (file.size > policy.media_max_mb * 1024 * 1024) {
      toast.error(`${(file.size / 1024 / 1024).toFixed(1)} MB melebihi batas ${policy.media_max_mb} MB`);
      return;
    }
    setUploading(true);
    try {
      const fd = new FormData();
      fd.append("file", file);
      fd.append("alt_text", "");
      fd.append("tags", tag || "");
      await api.post("/admin/media", fd, { headers: { "Content-Type": "multipart/form-data" } });
      toast.success(`"${file.name}" uploaded to the library`);
      await load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Upload failed");
    } finally {
      setUploading(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  };

  const remove = async (m) => {
    if (!window.confirm(`Delete "${m.filename}" from the library?`)) return;
    try {
      await api.delete(`/admin/media/${m.id}`);
      toast.success(`"${m.filename}" deleted`);
      await load();
    } catch (e) {
      const d = e?.response?.data?.detail;
      if (e?.response?.status === 409) {
        const list = (d?.used_in || []).map((u) => u.label).join(", ");
        toast.error(`Still in use: ${list || "referenced elsewhere"} - detach it first.`);
      } else {
        toast.error(typeof d === "string" ? d : "Delete failed");
      }
    }
  };

  if (rows === null) return <Loading label="Loading media library…" />;

  return (
    <div data-testid="media-library-page">
      <PageHeader
        title="Media Library"
        subtitle="Shared assets for articles, branding, and campaigns. Images, audio and video are served from this portal - reuse them anywhere via their URL."
        actions={
          <>
            <input ref={fileRef} type="file" accept={acceptAttr(policy.media_extensions)} className="hidden"
                   onChange={(e) => upload(e.target.files?.[0])} data-testid="media-file-input" />
            {policy.can_edit && (
              <button className={btnSecondary} onClick={() => setSettingsOpen(true)} data-testid="media-settings-btn">
                <Settings2 className="h-4 w-4" /> Upload settings
              </button>
            )}
            <button className={btnPrimary} disabled={uploading}
                    onClick={() => fileRef.current?.click()} data-testid="media-upload-btn">
              {uploading ? <Loader2 className="h-4 w-4 animate-spin" /> : <UploadCloud className="h-4 w-4" />}
              {uploading ? "Uploading…" : "Upload file"}
            </button>
          </>
        }
      />

      <div className="flex flex-wrap items-center gap-2 mb-4">
        <div className="relative">
          <Search className="h-4 w-4 absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search filename / alt text…"
                 className={`${inputClass} pl-9 w-64`} data-testid="media-search" />
        </div>
        <button onClick={() => setTag("")}
                className={`px-3 h-8 rounded-full text-xs font-bold border transition-colors ${!tag ? "bg-[#0a2350] text-white border-[#0a2350]" : "bg-white text-slate-600 border-slate-200 hover:border-[#f5b120]"}`}
                data-testid="media-tag-all">All</button>
        {allTags.map((t) => (
          <button key={t} onClick={() => setTag(t === tag ? "" : t)}
                  className={`px-3 h-8 rounded-full text-xs font-bold border inline-flex items-center gap-1 transition-colors ${tag === t ? "bg-[#0a2350] text-white border-[#0a2350]" : "bg-white text-slate-600 border-slate-200 hover:border-[#f5b120]"}`}
                  data-testid={`media-tag-${t}`}>
            <Tag className="h-3 w-3" /> {t}
          </button>
        ))}
      </div>

      {filtered.length === 0 ? (
        <Card className="p-8">
          <EmptyState
            title={rows.length === 0 ? "The media library is empty" : "No assets match your filter"}
            body={rows.length === 0
              ? "Upload your first asset - images, audio or video become instantly reusable as article covers, branding assets, or campaign media."
              : "Try clearing the search box or tag filter."}
          />
          {rows.length === 0 && (
            <div className="text-center mt-4">
              <button className={btnPrimary} onClick={() => fileRef.current?.click()} data-testid="media-empty-upload">
                <UploadCloud className="h-4 w-4" /> Upload your first asset
              </button>
            </div>
          )}
        </Card>
      ) : (
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-3">
          {filtered.map((m) => <MediaCard key={m.id} m={m} onDelete={() => remove(m)} onSaved={load} />)}
        </div>
      )}
      {settingsOpen && (
        <UploadSettingsModal policy={policy} onSave={save} onClose={() => setSettingsOpen(false)} />
      )}
    </div>
  );
};

export const UploadSettingsModal = ({ policy, onSave, onClose }) => {
  const [docExt, setDocExt] = useState((policy.document_extensions || []).join(", "));
  const [mediaExt, setMediaExt] = useState((policy.media_extensions || []).join(", "));
  const [docMb, setDocMb] = useState(policy.document_max_mb || 50);
  const [mediaMb, setMediaMb] = useState(policy.media_max_mb || 300);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true); setErr("");
    try {
      await onSave({
        document_extensions: parseExtInput(docExt),
        media_extensions: parseExtInput(mediaExt),
        document_max_mb: Number(docMb) || 50,
        media_max_mb: Number(mediaMb) || 300,
      });
      toast.success("Upload settings saved");
      onClose();
    } catch (e2) {
      setErr(e2?.response?.data?.detail || "Gagal menyimpan pengaturan");
    } finally { setBusy(false); }
  };

  return (
    <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4" onClick={onClose}>
      <form onClick={(e) => e.stopPropagation()} onSubmit={submit}
            className="w-full max-w-xl bg-white rounded-3xl p-6 max-h-[90vh] overflow-y-auto"
            data-testid="upload-settings-modal">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-lg font-extrabold text-[#0a2350]">Upload settings</h3>
          <button type="button" onClick={onClose} className="text-slate-400 hover:text-slate-700"><X className="h-5 w-5" /></button>
        </div>
        {err && <div className="mb-3 rounded-xl bg-red-50 border border-red-200 text-red-700 text-sm px-3 py-2">{err}</div>}
        <label className="block mb-3">
          <div className={labelClass}>Ekstensi dokumen yang diizinkan</div>
          <textarea rows={3} value={docExt} onChange={(e) => setDocExt(e.target.value)}
                    className={`${inputClass} h-auto py-2`} data-testid="upload-settings-doc-ext" />
          <div className="text-[11px] text-slate-500 mt-1">Pisahkan dengan koma. Contoh: pdf, docx, flac</div>
        </label>
        <label className="block mb-3">
          <div className={labelClass}>Batas ukuran dokumen (MB)</div>
          <input type="number" min={1} max={1024} value={docMb} onChange={(e) => setDocMb(e.target.value)}
                 className={inputClass} data-testid="upload-settings-doc-mb" />
        </label>
        <label className="block mb-3">
          <div className={labelClass}>Ekstensi media yang diizinkan</div>
          <textarea rows={3} value={mediaExt} onChange={(e) => setMediaExt(e.target.value)}
                    className={`${inputClass} h-auto py-2`} data-testid="upload-settings-media-ext" />
        </label>
        <label className="block mb-4">
          <div className={labelClass}>Batas ukuran media (MB)</div>
          <input type="number" min={1} max={2048} value={mediaMb} onChange={(e) => setMediaMb(e.target.value)}
                 className={inputClass} data-testid="upload-settings-media-mb" />
        </label>
        <div className="flex justify-end gap-2">
          <button type="button" className={btnSecondary} onClick={onClose}>Cancel</button>
          <button type="submit" className={btnPrimary} disabled={busy} data-testid="upload-settings-save">
            {busy ? "Saving…" : "Save"}
          </button>
        </div>
      </form>
    </div>
  );
};

export const mediaKind = (m) => {
  const ct = (m?.content_type || "").toLowerCase();
  if (ct.startsWith("video/")) return "video";
  if (ct.startsWith("audio/")) return "audio";
  if (ct.startsWith("image/")) return "image";
  const ext = (m?.filename || "").split(".").pop().toLowerCase();
  if (["mp4", "webm", "mov", "mkv", "avi", "ogv"].includes(ext)) return "video";
  if (["mp3", "ogg", "wav", "m4a", "flac", "aac"].includes(ext)) return "audio";
  return "image";
};

const MediaCard = ({ m, onDelete, onSaved }) => {
  const [editing, setEditing] = useState(false);
  const [commenting, setCommenting] = useState(false);
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    await navigator.clipboard.writeText(mediaUrl(m));
    setCopied(true);
    toast.success("Asset URL copied");
    setTimeout(() => setCopied(false), 1500);
  };
  const kind = mediaKind(m);
  return (
    <div className="rounded-2xl bg-white border border-slate-200 overflow-hidden group focus-within:ring-2 focus-within:ring-[#f5b120]" data-testid={`media-card-${m.id}`}>
      <div className="aspect-square bg-slate-100 relative">
        {kind === "video" ? (
          <video src={mediaUrl(m)} className="w-full h-full object-cover bg-black"
                 muted preload="metadata" playsInline data-testid={`media-video-${m.id}`} />
        ) : kind === "audio" ? (
          <div className="w-full h-full flex flex-col items-center justify-center gap-2 text-slate-400">
            <Music className="h-8 w-8" />
            <audio src={mediaUrl(m)} controls className="w-[85%]" data-testid={`media-audio-${m.id}`} />
          </div>
        ) : (
          <img src={mediaUrl(m)} alt={m.alt_text || m.filename} className="w-full h-full object-cover" loading="lazy" />
        )}
        {kind !== "image" && (
          <span className="absolute bottom-2 right-2 px-1.5 py-0.5 rounded bg-[#0a2350]/85 text-white text-[10px] font-bold inline-flex items-center gap-1">
            {kind === "video" ? <Play className="h-2.5 w-2.5" /> : <Music className="h-2.5 w-2.5" />}
            {kind.toUpperCase()}
          </span>
        )}
        {(m.used_in || []).length > 0 && (
          <span className="absolute top-2 left-2 px-2 py-0.5 rounded-full bg-[#0a2350]/85 text-white text-[10px] font-bold" title={(m.used_in || []).map((u) => u.label).join(", ")}>
            in use ×{m.used_in.length}
          </span>
        )}
      </div>
      <div className="p-3">
        <div className="text-xs font-bold text-[#0a2350] truncate" title={m.filename}>{m.filename}</div>
        <div className="text-[10px] text-slate-400">{(m.size_bytes / 1024).toFixed(0)} KB · {(m.tags || []).join(", ") || "no tags"}</div>
        <div className="flex items-center gap-1 mt-2">
          <button onClick={copy} className="flex-1 h-8 rounded-lg border border-slate-200 text-xs font-bold text-slate-600 hover:border-[#f5b120] inline-flex items-center justify-center gap-1 focus-visible:ring-2 focus-visible:ring-[#f5b120]" data-testid={`media-copy-${m.id}`}>
            {copied ? <CheckCircle2 className="h-3.5 w-3.5 text-emerald-600" /> : <Copy className="h-3.5 w-3.5" />} URL
          </button>
          <button onClick={() => setCommenting(true)} className="h-8 px-2 rounded-lg border border-slate-200 text-xs font-bold text-slate-600 hover:border-[#f5b120] inline-flex items-center gap-1 focus-visible:ring-2 focus-visible:ring-[#f5b120]" data-testid={`media-comments-${m.id}`} title="Feedback tim">
            <MessageSquare className="h-3.5 w-3.5" />
          </button>
          <button onClick={() => setEditing(true)} className="h-8 px-2 rounded-lg border border-slate-200 text-xs font-bold text-slate-600 hover:border-[#f5b120] focus-visible:ring-2 focus-visible:ring-[#f5b120]" data-testid={`media-edit-${m.id}`}>Edit</button>
          <button onClick={onDelete} className="h-8 px-2 rounded-lg border border-slate-200 text-slate-500 hover:text-red-600 hover:border-red-300 focus-visible:ring-2 focus-visible:ring-red-300" data-testid={`media-delete-${m.id}`}>
            <Trash2 className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>
      {editing && <EditModal m={m} onClose={() => setEditing(false)} onSaved={() => { setEditing(false); onSaved(); }} />}
      {commenting && <CommentsModal m={m} onClose={() => setCommenting(false)} />}
    </div>
  );
};

const EditModal = ({ m, onClose, onSaved }) => {
  const [alt, setAlt] = useState(m.alt_text || "");
  const [tags, setTags] = useState((m.tags || []).join(", "));
  const [busy, setBusy] = useState(false);
  const save = async () => {
    setBusy(true);
    try {
      await api.put(`/admin/media/${m.id}`, { alt_text: alt, tags });
      toast.success("Media details updated");
      onSaved();
    } catch { toast.error("Update failed"); }
    finally { setBusy(false); }
  };
  return (
    <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4" onClick={onClose}>
      <div onClick={(e) => e.stopPropagation()} className="w-full max-w-md bg-white rounded-3xl p-6">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-lg font-extrabold text-[#0a2350]">Edit media</h3>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-700"><X className="h-5 w-5" /></button>
        </div>
        <label className="block mb-3"><div className={labelClass}>Alt text</div>
          <input value={alt} onChange={(e) => setAlt(e.target.value)} className={inputClass} data-testid="media-alt-input" /></label>
        <label className="block mb-4"><div className={labelClass}>Tags (comma-separated)</div>
          <input value={tags} onChange={(e) => setTags(e.target.value)} className={inputClass} placeholder="hero, campaign-q3" data-testid="media-tags-input" /></label>
        <div className="flex justify-end gap-2">
          <button className={btnSecondary} onClick={onClose}>Cancel</button>
          <button className={btnPrimary} onClick={save} disabled={busy} data-testid="media-save-btn">{busy ? "Saving…" : "Save details"}</button>
        </div>
      </div>
    </div>
  );
};

const CommentsModal = ({ m, onClose }) => {
  const { user } = useAuth();
  const [rows, setRows] = useState(null);
  const [body, setBody] = useState("");
  const [busy, setBusy] = useState(false);

  const load = async () => {
    try {
      const r = await api.get(`/admin/media/${m.id}/comments`);
      setRows(r.data || []);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Gagal memuat komentar");
      setRows([]);
    }
  };
  useEffect(() => { load(); }, [m.id]);

  const submit = async (e) => {
    e.preventDefault();
    const text = body.trim();
    if (!text) return;
    setBusy(true);
    try {
      await api.post(`/admin/media/${m.id}/comments`, { body: text });
      setBody("");
      await load();
    } catch (e2) {
      toast.error(e2?.response?.data?.detail || "Gagal menambah komentar");
    } finally { setBusy(false); }
  };

  const remove = async (id) => {
    if (!window.confirm("Hapus komentar ini?")) return;
    try {
      await api.delete(`/admin/media/${m.id}/comments/${id}`);
      await load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Gagal menghapus komentar");
    }
  };

  return (
    <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4" onClick={onClose}>
      <div onClick={(e) => e.stopPropagation()} className="w-full max-w-lg bg-white rounded-3xl p-6 max-h-[85vh] flex flex-col" data-testid={`media-comments-modal-${m.id}`}>
        <div className="flex items-center justify-between mb-4">
          <div>
            <h3 className="text-lg font-extrabold text-[#0a2350]">Feedback desain</h3>
            <p className="text-xs text-slate-500 truncate max-w-[360px]">{m.filename}</p>
          </div>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-700"><X className="h-5 w-5" /></button>
        </div>
        <div className="flex-1 overflow-y-auto space-y-3 min-h-[130px] pr-1">
          {rows === null ? <Loading label="Memuat komentar…" /> : rows.length === 0 ? (
            <p className="text-sm text-slate-500 text-center py-8">Belum ada feedback. Mulai diskusi desain di bawah.</p>
          ) : rows.map((c) => {
            const canDelete = user?.role === "admin" || c.author_id === user?.id;
            return <div key={c.id} className="rounded-xl border border-slate-200 p-3" data-testid={`media-comment-${c.id}`}>
              <div className="flex gap-2 text-xs">
                <b className="text-[#0a2350]">{c.author_name || "Staff"}</b>
                <span className="text-slate-400 uppercase">{c.author_role}</span>
                {canDelete && <button onClick={() => remove(c.id)} className="ml-auto text-red-600 hover:underline" data-testid={`media-comment-delete-${c.id}`}>Hapus</button>}
              </div>
              <p className="mt-1 text-sm text-slate-700 whitespace-pre-wrap">{c.body}</p>
            </div>;
          })}
        </div>
        <form onSubmit={submit} className="border-t border-slate-100 mt-4 pt-4 flex gap-2">
          <textarea value={body} onChange={(e) => setBody(e.target.value)} rows={2} placeholder="Tulis masukan untuk desain ini…" className={`${inputClass} h-auto py-2 resize-none`} data-testid={`media-comment-input-${m.id}`} />
          <button type="submit" className={btnPrimary} disabled={busy || !body.trim()} data-testid={`media-comment-send-${m.id}`}>{busy ? "…" : "Kirim"}</button>
        </form>
      </div>
    </div>
  );
};

// Reusable picker modal - used by AdminArticles (cover) and AdminBranding (logo)
export const MediaPickerModal = ({ onPick, onClose }) => {
  const [rows, setRows] = useState(null);
  useEffect(() => { api.get("/admin/media").then((r) => setRows(r.data || [])); }, []);
  return (
    <div className="fixed inset-0 bg-black/50 z-[60] flex items-center justify-center p-4" onClick={onClose}>
      <div onClick={(e) => e.stopPropagation()} className="w-full max-w-3xl bg-white rounded-3xl p-6 max-h-[85vh] overflow-y-auto">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-lg font-extrabold text-[#0a2350]">Pick from Media Library</h3>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-700" data-testid="media-picker-close"><X className="h-5 w-5" /></button>
        </div>
        {rows === null ? <Loading label="Loading media…" /> : rows.length === 0 ? (
          <EmptyState title="Library is empty" body="Upload images in Media Library first, then pick them here." />
        ) : (
          <div className="grid grid-cols-3 sm:grid-cols-4 gap-3">
            {rows.map((m) => (
              <button key={m.id} onClick={() => onPick(mediaUrl(m), m)}
                      className="rounded-xl overflow-hidden border border-slate-200 hover:border-[#f5b120] focus-visible:ring-2 focus-visible:ring-[#f5b120]"
                      data-testid={`media-pick-${m.id}`}>
                {mediaKind(m) === "image" ? (
                  <img src={mediaUrl(m)} alt={m.alt_text || m.filename} className="aspect-square w-full object-cover" loading="lazy" />
                ) : (
                  <div className="aspect-square w-full bg-slate-900 flex items-center justify-center text-slate-300">
                    {mediaKind(m) === "video" ? <Play className="h-6 w-6" /> : <Music className="h-6 w-6" />}
                  </div>
                )}
                <div className="px-2 py-1 text-[10px] text-slate-500 truncate">{m.filename}</div>
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
};

export default AdminMediaLibrary;
