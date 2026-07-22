import React, { useEffect, useMemo, useState } from "react";
import { api, fullDateTime } from "../../../portal/api";
import {
  PageHeader, Card, Loading, EmptyState,
  btnPrimary, btnSecondary, btnDanger, inputClass, labelClass,
} from "../ui";
import {
  Newspaper, FilePlus2, Save, Trash2, Search, Tag, Eye,
  Loader2, X, Sparkles, ImagePlus, Video, ExternalLink, Star,
  Bold, Italic, List, Link as LinkIcon, Heading1, Heading2, Quote,
} from "lucide-react";

const STATUS_TONE = {
  draft: "bg-slate-100 text-slate-600",
  published: "bg-emerald-100 text-emerald-700",
  archived: "bg-slate-200 text-slate-500",
};

const AdminArticles = () => {
  const [rows, setRows] = useState(null);
  const [q, setQ] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [tagFilter, setTagFilter] = useState("");
  const [tagFacet, setTagFacet] = useState([]);
  const [editing, setEditing] = useState(null);
  const [saveMsg, setSaveMsg] = useState("");

  const load = async () => {
    const params = new URLSearchParams();
    if (q) params.set("q", q);
    if (statusFilter) params.set("status", statusFilter);
    if (tagFilter) params.set("tag", tagFilter);
    const [r, t] = await Promise.all([
      api.get(`/admin/articles?${params.toString()}`),
      api.get("/admin/articles-tags"),
    ]);
    setRows(r.data);
    setTagFacet(t.data);
  };
  useEffect(() => { load(); /* eslint-disable-next-line */ }, [q, statusFilter, tagFilter]);

  const openEditor = (article) => setEditing(article || newArticle());

  if (!rows) return <Loading />;

  return (
    <div>
      <PageHeader
        title="Articles"
        subtitle="Publish product updates, insight pieces, and announcements to the public /articles page. Supports rich HTML, cover images, video embeds, tags, and SEO meta."
        actions={
          <button className={btnPrimary} onClick={() => openEditor(null)} data-testid="new-article-btn">
            <FilePlus2 className="h-4 w-4" /> New article
          </button>
        }
      />

      {saveMsg && <div className="mb-4 text-sm rounded-xl bg-emerald-50 border border-emerald-200 text-emerald-800 px-4 py-2" data-testid="save-msg">{saveMsg}</div>}

      <Card className="p-4 mb-4 flex flex-wrap items-center gap-3">
        <div className="flex-1 min-w-[240px] flex items-center gap-2 h-10 rounded-lg border border-slate-300 px-3 bg-white">
          <Search className="h-4 w-4 text-slate-400" />
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search title, body, or tags…" className="flex-1 outline-none text-sm" data-testid="articles-search" />
        </div>
        <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)} className={`${inputClass} w-auto min-w-[140px]`} data-testid="articles-status-filter">
          <option value="">All statuses</option>
          <option value="draft">Draft</option>
          <option value="published">Published</option>
          <option value="archived">Archived</option>
        </select>
        <select value={tagFilter} onChange={(e) => setTagFilter(e.target.value)} className={`${inputClass} w-auto min-w-[140px]`} data-testid="articles-tag-filter">
          <option value="">All tags</option>
          {tagFacet.map((t) => <option key={t.tag} value={t.tag}>#{t.tag} ({t.count})</option>)}
        </select>
      </Card>

      {rows.length === 0 ? (
        <EmptyState title="No articles yet" body="Click New article to draft your first post." />
      ) : (
        <div className="rounded-2xl bg-white border border-slate-200 overflow-x-auto" data-testid="articles-table">
          <table className="w-full min-w-[820px] text-sm">
            <thead className="bg-slate-50 text-[11px] font-bold uppercase tracking-widest text-slate-500">
              <tr>
                <th className="px-4 py-3 text-left">Title</th>
                <th className="px-4 py-3 text-left">Status</th>
                <th className="px-4 py-3 text-left">Tags</th>
                <th className="px-4 py-3 text-left">Author</th>
                <th className="px-4 py-3 text-right">Views</th>
                <th className="px-4 py-3 text-left">Updated</th>
                <th className="px-4 py-3 text-right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((a) => (
                <tr key={a.id} className="border-t border-slate-100" data-testid={`article-row-${a.slug}`}>
                  <td className="px-4 py-3">
                    <div className="font-bold text-[#0a2350] flex items-center gap-2">{a.is_featured && <Star className="h-3.5 w-3.5 text-[#f5b120] fill-current" />} {a.title}</div>
                    <div className="text-[11px] text-slate-500 truncate max-w-[380px]">/{a.slug}</div>
                  </td>
                  <td className="px-4 py-3"><span className={`px-2 py-0.5 rounded-full font-bold uppercase tracking-wide text-[10px] ${STATUS_TONE[a.status] || STATUS_TONE.draft}`}>{a.status}</span></td>
                  <td className="px-4 py-3 text-xs text-slate-600">
                    <div className="flex flex-wrap gap-1">{(a.tags || []).slice(0, 4).map((t) => <span key={t} className="px-1.5 py-0.5 rounded bg-slate-100 border border-slate-200">#{t}</span>)}</div>
                  </td>
                  <td className="px-4 py-3 text-xs text-slate-600">{a.author_name || "—"}</td>
                  <td className="px-4 py-3 text-right font-semibold text-slate-700">{a.view_count}</td>
                  <td className="px-4 py-3 text-xs text-slate-500 whitespace-nowrap">{fullDateTime(a.updated_at)}</td>
                  <td className="px-4 py-3 text-right">
                    <div className="inline-flex gap-1.5">
                      {a.status === "published" && (
                        <a href={`/articles/${a.slug}`} target="_blank" rel="noreferrer" className="p-1.5 rounded hover:bg-slate-100 text-slate-500 hover:text-[#0a2350]" title="View public" data-testid={`view-${a.slug}`}><ExternalLink className="h-4 w-4" /></a>
                      )}
                      <button className="p-1.5 rounded hover:bg-slate-100 text-slate-500 hover:text-[#0a2350]" onClick={() => openEditor(a)} title="Edit" data-testid={`edit-${a.slug}`}><Sparkles className="h-4 w-4" /></button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {editing && (
        <ArticleEditor
          article={editing}
          onClose={() => setEditing(null)}
          onSaved={async (msg) => { setEditing(null); setSaveMsg(msg); await load(); setTimeout(() => setSaveMsg(""), 4500); }}
        />
      )}
    </div>
  );
};

const newArticle = () => ({
  title: "", slug: "", excerpt: "", body_html: "",
  cover_image_url: "", video_url: "", author_name: "",
  tags: [], category: "", status: "draft", published_at: null,
  meta_title: "", meta_description: "", meta_keywords: [], og_image_url: "",
  is_featured: false,
});

const ArticleEditor = ({ article, onClose, onSaved }) => {
  const [form, setForm] = useState({ ...article });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [tab, setTab] = useState("write"); // write | media | seo
  const isNew = !article.id;

  const set = (k, v) => setForm((f) => ({ ...f, [k]: v }));

  const tagText = useMemo(() => (form.tags || []).join(", "), [form.tags]);
  const metaKwText = useMemo(() => (form.meta_keywords || []).join(", "), [form.meta_keywords]);

  const insertAtCursor = (before, after = "") => {
    const el = document.querySelector('[data-testid="editor-body"]');
    if (!el) return;
    const start = el.selectionStart, end = el.selectionEnd;
    const sel = form.body_html.slice(start, end);
    const next = form.body_html.slice(0, start) + before + sel + after + form.body_html.slice(end);
    set("body_html", next);
    setTimeout(() => { el.focus(); el.selectionStart = el.selectionEnd = start + before.length + sel.length; }, 0);
  };

  const save = async () => {
    setBusy(true); setErr("");
    try {
      const payload = {
        title: form.title, slug: form.slug || "",
        excerpt: form.excerpt || "",
        body_html: form.body_html || "",
        cover_image_url: form.cover_image_url || "",
        video_url: form.video_url || "",
        author_name: form.author_name || "",
        tags: (typeof form.tags === "string" ? form.tags.split(/[,\n]+/) : form.tags || []).map((t) => t.trim()).filter(Boolean),
        category: form.category || "",
        status: form.status || "draft",
        published_at: form.published_at || null,
        meta_title: form.meta_title || "",
        meta_description: form.meta_description || "",
        meta_keywords: (typeof form.meta_keywords === "string" ? form.meta_keywords.split(/[,\n]+/) : form.meta_keywords || []).map((t) => t.trim()).filter(Boolean),
        og_image_url: form.og_image_url || "",
        is_featured: !!form.is_featured,
      };
      if (isNew) await api.post("/admin/articles", payload);
      else await api.put(`/admin/articles/${article.id}`, payload);
      onSaved(`Article “${form.title}” saved.`);
    } catch (e) {
      setErr(e?.response?.data?.detail || "Save failed");
    } finally { setBusy(false); }
  };

  const remove = async () => {
    if (!window.confirm(`Delete “${form.title}”? This cannot be undone.`)) return;
    setBusy(true);
    try {
      await api.delete(`/admin/articles/${article.id}`);
      onSaved(`Article “${form.title}” deleted.`);
    } catch (e) {
      setErr(e?.response?.data?.detail || "Delete failed");
      setBusy(false);
    }
  };

  const embed = (form.video_url || "").trim();
  const videoEmbedSrc = (() => {
    if (!embed) return "";
    const yt = embed.match(/(?:youtu\.be\/|youtube\.com\/(?:watch\?v=|embed\/))([\w-]{11})/);
    if (yt) return `https://www.youtube.com/embed/${yt[1]}`;
    const vm = embed.match(/vimeo\.com\/(\d+)/);
    if (vm) return `https://player.vimeo.com/video/${vm[1]}`;
    return embed;
  })();

  return (
    <div className="fixed inset-0 z-50 bg-slate-900/50 flex items-start justify-center p-4 overflow-y-auto" onClick={onClose}>
      <div className="bg-white rounded-2xl w-full max-w-6xl my-6 max-h-[92vh] overflow-hidden flex flex-col" onClick={(e) => e.stopPropagation()}>
        <div className="p-4 border-b border-slate-200 flex items-start justify-between">
          <div className="min-w-0">
            <div className="text-[10px] uppercase tracking-widest font-bold text-[#f5b120]">{isNew ? "New article" : "Edit article"}</div>
            <div className="text-lg font-extrabold text-[#0a2350] mt-0.5 truncate">{form.title || "Untitled"}</div>
          </div>
          <button onClick={onClose} className="p-2 hover:bg-slate-100 rounded"><X className="h-4 w-4" /></button>
        </div>

        {/* Sub-tabs */}
        <div className="px-4 border-b border-slate-100 flex items-center gap-3 overflow-x-auto">
          {[["write", "Write"], ["media", "Media"], ["seo", "SEO & Tags"]].map(([k, label]) => (
            <button key={k} onClick={() => setTab(k)} data-testid={`editor-tab-${k}`}
              className={`px-3 h-11 -mb-px border-b-2 text-xs font-bold uppercase tracking-widest whitespace-nowrap ${tab === k ? "border-[#f5b120] text-[#0a2350]" : "border-transparent text-slate-500 hover:text-[#0a2350]"}`}>
              {label}
            </button>
          ))}
        </div>

        <div className="p-6 overflow-y-auto flex-1 grid lg:grid-cols-2 gap-6">
          <div className="space-y-3">
            {err && <div className="text-sm rounded-xl bg-red-50 border border-red-200 text-red-700 px-3 py-2" data-testid="editor-err">{err}</div>}

            {tab === "write" && (
              <>
                <label className="block">
                  <div className={labelClass}>Title</div>
                  <input value={form.title} onChange={(e) => set("title", e.target.value)} className={inputClass} data-testid="editor-title" />
                </label>
                <div className="grid sm:grid-cols-2 gap-3">
                  <label className="block">
                    <div className={labelClass}>Slug <span className="ml-1 text-slate-400 normal-case">(optional — auto)</span></div>
                    <input value={form.slug} onChange={(e) => set("slug", e.target.value)} className={inputClass} placeholder="auto-from-title" data-testid="editor-slug" />
                  </label>
                  <label className="block">
                    <div className={labelClass}>Category</div>
                    <input value={form.category} onChange={(e) => set("category", e.target.value)} className={inputClass} placeholder="Insight, Guide, Announcement…" data-testid="editor-category" />
                  </label>
                </div>
                <label className="block">
                  <div className={labelClass}>Excerpt</div>
                  <textarea rows={2} value={form.excerpt} onChange={(e) => set("excerpt", e.target.value)} className={`${inputClass} h-auto py-2`} data-testid="editor-excerpt" placeholder="A short summary that shows in the listing card and search results." />
                </label>
                {/* Toolbar */}
                <div className="flex flex-wrap gap-1 border border-slate-200 rounded-lg p-1 bg-slate-50">
                  <ToolbarBtn icon={Heading1} title="H1" onClick={() => insertAtCursor("<h1>", "</h1>")} />
                  <ToolbarBtn icon={Heading2} title="H2" onClick={() => insertAtCursor("<h2>", "</h2>")} />
                  <ToolbarBtn icon={Bold} title="Bold" onClick={() => insertAtCursor("<b>", "</b>")} />
                  <ToolbarBtn icon={Italic} title="Italic" onClick={() => insertAtCursor("<i>", "</i>")} />
                  <ToolbarBtn icon={List} title="List" onClick={() => insertAtCursor("<ul>\n  <li>", "</li>\n</ul>")} />
                  <ToolbarBtn icon={Quote} title="Quote" onClick={() => insertAtCursor("<blockquote>", "</blockquote>")} />
                  <ToolbarBtn icon={LinkIcon} title="Link" onClick={() => {
                    const url = window.prompt("Link URL:", "https://");
                    if (url) insertAtCursor(`<a href="${url}">`, "</a>");
                  }} />
                  <ToolbarBtn icon={ImagePlus} title="Image" onClick={() => {
                    const url = window.prompt("Image URL:", form.cover_image_url || "https://");
                    if (url) insertAtCursor(`<figure><img src="${url}" alt="" style="max-width:100%;border-radius:12px" /></figure>`);
                  }} />
                </div>
                <label className="block">
                  <div className={labelClass}>Body (HTML)</div>
                  <textarea rows={18} value={form.body_html} onChange={(e) => set("body_html", e.target.value)} className={`${inputClass} h-auto py-2 font-mono text-[12px]`} data-testid="editor-body" />
                </label>
              </>
            )}

            {tab === "media" && (
              <>
                <label className="block">
                  <div className={labelClass}>Cover image URL</div>
                  <input value={form.cover_image_url} onChange={(e) => set("cover_image_url", e.target.value)} className={inputClass} placeholder="https://…" data-testid="editor-cover" />
                </label>
                {form.cover_image_url && (
                  <div className="rounded-xl overflow-hidden border border-slate-200"><img src={form.cover_image_url} alt="cover" className="w-full max-h-[240px] object-cover" /></div>
                )}
                <label className="block">
                  <div className={labelClass}>Video URL <span className="ml-1 text-slate-400 normal-case">(YouTube / Vimeo / MP4)</span></div>
                  <input value={form.video_url} onChange={(e) => set("video_url", e.target.value)} className={inputClass} placeholder="https://youtu.be/…" data-testid="editor-video" />
                </label>
                {videoEmbedSrc && (
                  <div className="rounded-xl overflow-hidden border border-slate-200 aspect-video">
                    <iframe src={videoEmbedSrc} title="video preview" allow="fullscreen" className="w-full h-full" />
                  </div>
                )}
                <div className="rounded-xl border border-dashed border-slate-300 p-3 text-xs text-slate-500">
                  <b className="text-slate-700">Tip:</b> paste any image or video URL. Images are embedded via <code>&lt;img&gt;</code> and videos are auto-converted to embed players for YouTube/Vimeo. Direct MP4 URLs work too.
                </div>
              </>
            )}

            {tab === "seo" && (
              <>
                <label className="block">
                  <div className={labelClass}>Tags <span className="ml-1 text-slate-400 normal-case">(comma separated — auto-lowercased)</span></div>
                  <input value={tagText} onChange={(e) => set("tags", e.target.value.split(",").map((t) => t.trim()))} className={inputClass} placeholder="cloud, indonesia, guide" data-testid="editor-tags" />
                </label>
                <label className="block">
                  <div className={labelClass}>Meta title <span className="ml-1 text-slate-400 normal-case">(SEO — defaults to title)</span></div>
                  <input value={form.meta_title} onChange={(e) => set("meta_title", e.target.value)} className={inputClass} data-testid="editor-meta-title" />
                </label>
                <label className="block">
                  <div className={labelClass}>Meta description <span className="ml-1 text-slate-400 normal-case">(≤ 160 chars ideal)</span></div>
                  <textarea rows={3} value={form.meta_description} onChange={(e) => set("meta_description", e.target.value)} className={`${inputClass} h-auto py-2`} data-testid="editor-meta-description" />
                </label>
                <label className="block">
                  <div className={labelClass}>Meta keywords</div>
                  <input value={metaKwText} onChange={(e) => set("meta_keywords", e.target.value.split(",").map((t) => t.trim()))} className={inputClass} placeholder="cloud, colocation, vps" data-testid="editor-meta-keywords" />
                </label>
                <label className="block">
                  <div className={labelClass}>Open Graph image URL</div>
                  <input value={form.og_image_url} onChange={(e) => set("og_image_url", e.target.value)} className={inputClass} placeholder="https://… (1200 × 630 recommended)" data-testid="editor-og-image" />
                </label>
              </>
            )}
          </div>

          {/* Sidebar preview + publish */}
          <div className="space-y-3">
            <Card className="p-4">
              <div className="text-[10px] font-bold uppercase tracking-widest text-slate-500 mb-2">Publish</div>
              <label className="block mb-3">
                <div className={labelClass}>Status</div>
                <select value={form.status} onChange={(e) => set("status", e.target.value)} className={inputClass} data-testid="editor-status">
                  <option value="draft">Draft</option>
                  <option value="published">Published</option>
                  <option value="archived">Archived</option>
                </select>
              </label>
              <label className="block mb-3">
                <div className={labelClass}>Author name</div>
                <input value={form.author_name} onChange={(e) => set("author_name", e.target.value)} className={inputClass} placeholder="Auto — your account" data-testid="editor-author" />
              </label>
              <label className="flex items-center gap-2 text-sm">
                <input type="checkbox" checked={!!form.is_featured} onChange={(e) => set("is_featured", e.target.checked)} data-testid="editor-featured" />
                <span className="font-semibold text-slate-700"><Star className="inline h-3.5 w-3.5 text-[#f5b120] fill-current" /> Featured on public page</span>
              </label>
            </Card>

            <Card className="p-4">
              <div className="text-[10px] font-bold uppercase tracking-widest text-slate-500 mb-2 flex items-center justify-between">
                Live preview
                <span className="text-slate-400 normal-case font-normal">(what /articles/{form.slug || "…"} shows)</span>
              </div>
              <div className="rounded-lg border border-slate-200 overflow-hidden bg-white">
                {form.cover_image_url && <img src={form.cover_image_url} alt="" className="w-full h-40 object-cover" />}
                <div className="p-4">
                  <div className="text-[10px] uppercase tracking-widest font-bold text-[#f5b120]">{form.category || "Article"}</div>
                  <h2 className="mt-1 text-lg font-extrabold text-[#0a2350] leading-tight">{form.title || "Untitled article"}</h2>
                  <p className="mt-2 text-sm text-slate-600">{form.excerpt || "—"}</p>
                  <div className="mt-3 flex flex-wrap gap-1">
                    {(Array.isArray(form.tags) ? form.tags : String(form.tags || "").split(",")).map((t) => t && t.trim()).filter(Boolean).slice(0, 6).map((t) => (
                      <span key={t} className="text-[10px] px-1.5 py-0.5 rounded bg-slate-100 border border-slate-200 text-slate-600">#{t.toLowerCase().trim()}</span>
                    ))}
                  </div>
                </div>
              </div>
            </Card>
          </div>
        </div>

        <div className="p-4 border-t border-slate-200 flex flex-wrap gap-2 justify-end">
          {!isNew && (
            <button className={btnDanger} onClick={remove} disabled={busy} data-testid="editor-delete-btn"><Trash2 className="h-4 w-4" /> Delete</button>
          )}
          <button className={btnSecondary} onClick={onClose} disabled={busy}>Cancel</button>
          <button className={btnPrimary} onClick={save} disabled={busy || !form.title} data-testid="editor-save-btn">
            {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />} Save article
          </button>
        </div>
      </div>
    </div>
  );
};

const ToolbarBtn = ({ icon: Icon, title, onClick }) => (
  <button type="button" onClick={onClick} title={title} className="p-2 rounded hover:bg-white text-slate-500 hover:text-[#0a2350] transition-colors">
    <Icon className="h-3.5 w-3.5" />
  </button>
);

export default AdminArticles;
