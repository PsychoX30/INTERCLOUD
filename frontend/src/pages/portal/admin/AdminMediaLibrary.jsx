import React, { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../../../portal/api";
import { PageHeader, Card, Loading, EmptyState, btnPrimary, btnSecondary, btnDanger, inputClass, labelClass } from "../ui";
import { UploadCloud, Trash2, Tag, Search, Copy, CheckCircle2, X, Loader2 } from "lucide-react";
import { toast } from "sonner";

const BACKEND = process.env.REACT_APP_BACKEND_URL;
export const mediaUrl = (m) => (m?.url?.startsWith("http") ? m.url : `${BACKEND}${m?.url || ""}`);

const AdminMediaLibrary = () => {
  const [rows, setRows] = useState(null);
  const [q, setQ] = useState("");
  const [tag, setTag] = useState("");
  const [uploading, setUploading] = useState(false);
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
        toast.error(`Still in use: ${list || "referenced elsewhere"} — detach it first.`);
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
        subtitle="Shared images for articles, branding, and campaigns. Uploaded files are served from this portal — reuse them anywhere via their URL."
        actions={
          <>
            <input ref={fileRef} type="file" accept="image/*" className="hidden"
                   onChange={(e) => upload(e.target.files?.[0])} data-testid="media-file-input" />
            <button className={btnPrimary} disabled={uploading}
                    onClick={() => fileRef.current?.click()} data-testid="media-upload-btn">
              {uploading ? <Loader2 className="h-4 w-4 animate-spin" /> : <UploadCloud className="h-4 w-4" />}
              {uploading ? "Uploading…" : "Upload image"}
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
              ? "Upload your first image — it becomes instantly reusable as an article cover, branding asset, or campaign visual."
              : "Try clearing the search box or tag filter."}
          />
          {rows.length === 0 && (
            <div className="text-center mt-4">
              <button className={btnPrimary} onClick={() => fileRef.current?.click()} data-testid="media-empty-upload">
                <UploadCloud className="h-4 w-4" /> Upload your first image
              </button>
            </div>
          )}
        </Card>
      ) : (
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-3">
          {filtered.map((m) => <MediaCard key={m.id} m={m} onDelete={() => remove(m)} onSaved={load} />)}
        </div>
      )}
    </div>
  );
};

const MediaCard = ({ m, onDelete, onSaved }) => {
  const [editing, setEditing] = useState(false);
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    await navigator.clipboard.writeText(mediaUrl(m));
    setCopied(true);
    toast.success("Image URL copied");
    setTimeout(() => setCopied(false), 1500);
  };
  return (
    <div className="rounded-2xl bg-white border border-slate-200 overflow-hidden group focus-within:ring-2 focus-within:ring-[#f5b120]" data-testid={`media-card-${m.id}`}>
      <div className="aspect-square bg-slate-100 relative">
        <img src={mediaUrl(m)} alt={m.alt_text || m.filename} className="w-full h-full object-cover" loading="lazy" />
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
          <button onClick={() => setEditing(true)} className="h-8 px-2 rounded-lg border border-slate-200 text-xs font-bold text-slate-600 hover:border-[#f5b120] focus-visible:ring-2 focus-visible:ring-[#f5b120]" data-testid={`media-edit-${m.id}`}>Edit</button>
          <button onClick={onDelete} className="h-8 px-2 rounded-lg border border-slate-200 text-slate-500 hover:text-red-600 hover:border-red-300 focus-visible:ring-2 focus-visible:ring-red-300" data-testid={`media-delete-${m.id}`}>
            <Trash2 className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>
      {editing && <EditModal m={m} onClose={() => setEditing(false)} onSaved={() => { setEditing(false); onSaved(); }} />}
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

// Reusable picker modal — used by AdminArticles (cover) and AdminBranding (logo)
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
                <img src={mediaUrl(m)} alt={m.alt_text || m.filename} className="aspect-square w-full object-cover" loading="lazy" />
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
