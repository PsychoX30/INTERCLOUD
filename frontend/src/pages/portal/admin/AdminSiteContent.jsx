import React, { useEffect, useRef, useState, useMemo, useCallback } from "react";
import { Save, RotateCcw, Plus, Trash2, Loader2, Monitor, Tablet, Smartphone, RefreshCw, Eye, UploadCloud } from "lucide-react";
import { api } from "../../../portal/api";

// Full landing-page coverage grouped by the sections a visitor scrolls through.
// Friendly Indonesian labels so non-technical (creative) team members can edit
// every headline, subheadline and button on the public site.
const SECTIONS = [
  { id: "navbar", title: "Menu Navigasi", keys: [
    { key: "nav.home", label: "Menu - Home" },
    { key: "nav.why", label: "Menu - Kenapa Kami" },
    { key: "nav.services", label: "Menu - Layanan" },
    { key: "nav.guide", label: "Menu - Panduan" },
    { key: "nav.pricing", label: "Menu - Harga" },
    { key: "nav.partners", label: "Menu - Partners" },
    { key: "nav.faq", label: "Menu - FAQ" },
    { key: "nav.contact", label: "Menu - Kontak" },
  ]},
  { id: "hero", title: "Hero (bagian paling atas)", keys: [
    { key: "hero.tag", label: "Label kecil di atas judul" },
    { key: "hero.h1a", label: "Judul utama (awal)" },
    { key: "hero.h1_stable", label: "Kata sorot 1 (mis. stabil)" },
    { key: "hero.h1_secure", label: "Kata sorot 2 (mis. aman)" },
    { key: "hero.h1c", label: "Judul utama (akhir)" },
    { key: "hero.body", label: "Paragraf (awal)" },
    { key: "hero.body2", label: "Paragraf (penghubung)" },
    { key: "hero.body3", label: "Paragraf (akhir)" },
    { key: "hero.aud.company", label: "Audiens - Perusahaan" },
    { key: "hero.aud.software", label: "Audiens - Software House" },
    { key: "hero.aud.itsupport", label: "Audiens - Tim IT" },
    { key: "hero.stat.sla", label: "Statistik - label SLA" },
    { key: "hero.stat.support", label: "Statistik - label Support" },
    { key: "hero.stat.dc", label: "Statistik - label Data Center" },
  ]},
  { id: "features", title: "Kenapa Memilih Kami", keys: [
    { key: "feat.eyebrow", label: "Label kecil" },
    { key: "feat.title", label: "Judul" },
    { key: "feat.subtitle", label: "Subjudul" },
  ]},
  { id: "infra", title: "Infrastruktur (Cara Kerja)", keys: [
    { key: "infra.eyebrow", label: "Label kecil" },
    { key: "infra.title_a", label: "Judul (awal)" },
    { key: "infra.title_b", label: "Judul (akhir)" },
    { key: "infra.subtitle", label: "Subjudul" },
    { key: "infra.dc.title", label: "Layer 1 - Judul" },
    { key: "infra.dc.body", label: "Layer 1 - Deskripsi" },
    { key: "infra.servers.title", label: "Layer 2 - Judul" },
    { key: "infra.servers.body", label: "Layer 2 - Deskripsi" },
    { key: "infra.fiber.title", label: "Layer 3 - Judul" },
    { key: "infra.fiber.body", label: "Layer 3 - Deskripsi" },
    { key: "infra.network.title", label: "Layer 4 - Judul" },
    { key: "infra.network.body", label: "Layer 4 - Deskripsi" },
  ]},
  { id: "services", title: "Layanan", keys: [
    { key: "svc.eyebrow", label: "Label kecil" },
    { key: "svc.title", label: "Judul" },
    { key: "svc.subtitle", label: "Subjudul" },
    { key: "svc.helperText", label: "Teks bantuan" },
  ]},
  { id: "guide", title: "Panduan Pemilihan", keys: [
    { key: "dg.eyebrow", label: "Label kecil" },
    { key: "dg.title_a", label: "Judul (awal)" },
    { key: "dg.title_b", label: "Judul (akhir)" },
    { key: "dg.subtitle", label: "Subjudul" },
    { key: "dg.hosting.title", label: "Hosting - Judul" },
    { key: "dg.hosting.body", label: "Hosting - Deskripsi" },
    { key: "dg.vps.title", label: "VPS - Judul" },
    { key: "dg.vps.body", label: "VPS - Deskripsi" },
    { key: "dg.ded.title", label: "Dedicated - Judul" },
    { key: "dg.ded.body", label: "Dedicated - Deskripsi" },
    { key: "dg.help.title", label: "Kartu bantuan - Judul" },
    { key: "dg.help.body", label: "Kartu bantuan - Deskripsi" },
  ]},
  { id: "pricing", title: "Harga", keys: [
    { key: "pr.eyebrow", label: "Label kecil" },
    { key: "pr.title", label: "Judul" },
    { key: "pr.subtitle", label: "Subjudul" },
    { key: "pr.custom.title", label: "Custom - Judul" },
    { key: "pr.custom.body", label: "Custom - Deskripsi" },
  ]},
  { id: "partners", title: "Partners & Clients", keys: [
    { key: "pt.eyebrow", label: "Label kecil" },
    { key: "pt.title", label: "Judul" },
    { key: "pt.subtitle", label: "Subjudul" },
    { key: "pt.count.label", label: "Statistik - label" },
    { key: "pt.count.body", label: "Statistik - deskripsi" },
  ]},
  { id: "pop", title: "Point of Presence", keys: [
    { key: "pop.eyebrow", label: "Label kecil" },
    { key: "pop.title", label: "Judul" },
    { key: "pop.subtitle", label: "Subjudul" },
    { key: "pop.item1.name", label: "PoP 1 - Nama" },
    { key: "pop.item1.desc", label: "PoP 1 - Deskripsi" },
    { key: "pop.item2.name", label: "PoP 2 - Nama" },
    { key: "pop.item2.desc", label: "PoP 2 - Deskripsi" },
    { key: "pop.item3.name", label: "PoP 3 - Nama" },
    { key: "pop.item3.desc", label: "PoP 3 - Deskripsi" },
    { key: "pop.item4.name", label: "PoP 4 - Nama" },
    { key: "pop.item4.desc", label: "PoP 4 - Deskripsi" },
    { key: "pop.cta.title", label: "CTA - Judul" },
    { key: "pop.cta.body", label: "CTA - Deskripsi" },
  ]},
  { id: "faqsec", title: "FAQ (judul)", keys: [
    { key: "faq.eyebrow", label: "Label kecil" },
    { key: "faq.title", label: "Judul" },
    { key: "faq.subtitle", label: "Subjudul" },
    { key: "faq.helpTitle", label: "Kartu bantuan - Judul" },
    { key: "faq.helpBody", label: "Kartu bantuan - Deskripsi" },
  ]},
  { id: "cta", title: "Ajakan (CTA bawah)", keys: [
    { key: "cta_sec.tag", label: "Label kecil" },
    { key: "cta_sec.title_a", label: "Judul (awal)" },
    { key: "cta_sec.title_b", label: "Judul (sorot)" },
    { key: "cta_sec.title_c", label: "Judul (akhir)" },
    { key: "cta_sec.body", label: "Deskripsi" },
    { key: "cta_sec.phone", label: "Label Telepon/WA" },
    { key: "cta_sec.email", label: "Label Email" },
    { key: "cta_sec.office", label: "Label Kantor" },
  ]},
  { id: "buttons", title: "Teks Tombol Umum", keys: [
    { key: "cta.contactUs", label: "Hubungi Kami" },
    { key: "cta.askWhatsApp", label: "Tanya via WhatsApp" },
    { key: "cta.orderWhatsApp", label: "Pesan via WhatsApp" },
    { key: "cta.chatNow", label: "Chat Sekarang" },
    { key: "cta.viewServices", label: "Lihat Layanan" },
    { key: "cta.freeConsult", label: "Konsultasi Gratis" },
    { key: "cta.getQuote", label: "Minta Penawaran" },
  ]},
  { id: "footer", title: "Footer", keys: [
    { key: "footer.tagline", label: "Tagline" },
    { key: "footer.pages", label: "Judul kolom Pages" },
    { key: "footer.services", label: "Judul kolom Layanan" },
    { key: "footer.copy", label: "Teks copyright" },
    { key: "footer.made", label: "Baris penutup" },
  ]},
];

const emptyFaq = () => ({ q: { id: "", en: "" }, a: { id: "", en: "" } });

// Landing-page image slots that can be overridden from the CMS.
// Defaults live in the components (Hero.jsx / Infrastructure.jsx) and are only
// used when no override URL is set.
const IMAGE_SLOTS = [
  { slot: "hero_main",      label: "Hero - Gambar utama (kanan)" },
  { slot: "infra_dc",       label: "Infrastruktur - Data Center" },
  { slot: "infra_servers",  label: "Infrastruktur - Server" },
  { slot: "infra_fiber",    label: "Infrastruktur - Fiber" },
  { slot: "infra_network",  label: "Infrastruktur - Network" },
];

const DEVICES = {
  desktop: { w: "100%", icon: Monitor, label: "Desktop" },
  tablet: { w: "834px", icon: Tablet, label: "Tablet" },
  mobile: { w: "390px", icon: Smartphone, label: "Mobile" },
};

const AdminSiteContent = () => {
  const [content, setContent] = useState(null);
  const [tab, setTab] = useState("editor");     // editor | faqs | images | json
  const [device, setDevice] = useState("desktop");
  const [previewLang, setPreviewLang] = useState("id");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null);
  const [jsonText, setJsonText] = useState("");
  const iframeRef = useRef(null);
  const editorScrollRef = useRef(null);
  const [mediaRows, setMediaRows] = useState([]);
  const [mediaLoading, setMediaLoading] = useState(false);
  const [mediaTag, setMediaTag] = useState("");
  const [uploadingSlot, setUploadingSlot] = useState("");

  useEffect(() => {
    api.get("/landing-content").then(({ data }) => {
      setContent(data);
      setJsonText(JSON.stringify(data, null, 2));
    });
  }, []);

  // Load media library for the image picker
  const loadMedia = async () => {
    setMediaLoading(true);
    try {
      const r = await api.get("/admin/media", { params: { tag: mediaTag || undefined } });
      setMediaRows(r.data || []);
    } catch (_) {
      setMediaRows([]);
    } finally {
      setMediaLoading(false);
    }
  };

  useEffect(() => { loadMedia(); }, [mediaTag]);

  const previewUrl = useMemo(() => `${window.location.origin}/?cmsPreview=1`, []);

  const pushPreview = useCallback((c = content, lang = previewLang) => {
    const win = iframeRef.current && iframeRef.current.contentWindow;
    if (!win || !c) return;
    win.postMessage({
      type: "ic-cms-preview",
      overrides: c.overrides || {},
      faqs: Array.isArray(c.faqs) ? c.faqs : [],
      contact: c.contact || null,
      images: c.images || {},
      lang,
    }, window.location.origin);
  }, [content, previewLang]);

  // When the preview iframe signals ready, push the current draft.
  useEffect(() => {
    const onMsg = (e) => {
      if (e.origin !== window.location.origin) return;
      if (e.data && e.data.type === "ic-cms-preview-ready") pushPreview();
    };
    window.addEventListener("message", onMsg);
    return () => window.removeEventListener("message", onMsg);
  }, [pushPreview]);

  // Debounced live push on any content / language change.
  useEffect(() => {
    if (!content) return;
    const t = setTimeout(() => pushPreview(content, previewLang), 250);
    return () => clearTimeout(t);
  }, [content, previewLang, pushPreview]);

  const setOverride = (key, lang, val) => {
    setContent((c) => ({
      ...c,
      overrides: {
        ...(c.overrides || {}),
        [key]: { ...((c.overrides || {})[key] || { id: "", en: "" }), [lang]: val },
      },
    }));
  };

  const setFaq = (i, path, val) => {
    setContent((c) => {
      const faqs = [...(c.faqs || [])];
      const f = { ...(faqs[i] || emptyFaq()) };
      const [field, lang] = path.split(".");
      f[field] = { ...(f[field] || { id: "", en: "" }), [lang]: val };
      faqs[i] = f;
      return { ...c, faqs };
    });
  };
  const addFaq = () => setContent((c) => ({ ...c, faqs: [...(c.faqs || []), emptyFaq()] }));
  const rmFaq = (i) => setContent((c) => ({ ...c, faqs: (c.faqs || []).filter((_, idx) => idx !== i) }));

  const setImage = (slot, field, val) => {
    setContent((c) => ({
      ...c,
      images: {
        ...(c.images || {}),
        [slot]: {
          url: (c.images || {})[slot]?.url || "",
          alt_id: (c.images || {})[slot]?.alt_id || "",
          alt_en: (c.images || {})[slot]?.alt_en || "",
          ...(field ? { [field]: val } : {}),
        },
      },
    }));
  };
  const clearImage = (slot) => {
    setContent((c) => {
      const images = { ...(c.images || {}) };
      delete images[slot];
      return { ...c, images };
    });
  };

  const uploadImage = async (slot, file) => {
    if (!file) return;
    setUploadingSlot(slot);
    setMsg(null);
    try {
      const form = new FormData();
      form.append("file", file);
      form.append("alt_text", (content.images || {})[slot]?.alt_id || "");
      form.append("tags", "landing,cms");
      const { data } = await api.post("/admin/media", form, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      if (!data?.url) throw new Error("Server tidak mengembalikan URL media");
      setImage(slot, "url", data.url);
      setMediaRows((rows) => [data, ...rows.filter((m) => m.id !== data.id)]);
      setMsg({ kind: "ok", text: `${file.name} berhasil diunggah dan dipilih. Klik Simpan untuk menerbitkan.` });
    } catch (e) {
      setMsg({ kind: "error", text: e?.response?.data?.detail || e.message || "Upload gagal" });
    } finally {
      setUploadingSlot("");
    }
  };

  const jumpTo = (secId) => {
    const el = editorScrollRef.current && editorScrollRef.current.querySelector(`#sec-${secId}`);
    if (el) el.scrollIntoView({ behavior: "smooth", block: "start" });
    const win = iframeRef.current && iframeRef.current.contentWindow;
    if (win) win.postMessage({ type: "ic-cms-preview", overrides: content?.overrides || {}, faqs: content?.faqs || [], lang: previewLang, scrollTo: secId }, window.location.origin);
  };

  const save = async () => {
    setBusy(true); setMsg(null);
    try {
      let body = content;
      if (tab === "json") {
        try { body = JSON.parse(jsonText); }
        catch (e) { setMsg({ kind: "error", text: `JSON tidak valid: ${e.message}` }); setBusy(false); return; }
      }
      const { data } = await api.post("/admin/landing-content", body);
      setContent(data);
      setJsonText(JSON.stringify(data, null, 2));
      pushPreview(data, previewLang);
      setMsg({ kind: "ok", text: "Tersimpan - perubahan sudah live di landing page." });
    } catch (e) {
      setMsg({ kind: "error", text: e?.response?.data?.detail || e.message });
    } finally { setBusy(false); }
  };

  const resetAll = async () => {
    if (!window.confirm("Reset SEMUA teks landing ke bawaan?")) return;
    setBusy(true); setMsg(null);
    try {
      const { data } = await api.delete("/admin/landing-content");
      setContent(data);
      setJsonText(JSON.stringify(data, null, 2));
      pushPreview(data, previewLang);
      setMsg({ kind: "ok", text: "Semua override dihapus." });
    } catch (e) { setMsg({ kind: "error", text: e?.response?.data?.detail || e.message }); }
    finally { setBusy(false); }
  };

  if (!content) return <div className="p-8 text-slate-400">Loading…</div>;

  return (
    <div className="h-[calc(100vh-4rem)] flex flex-col" data-testid="admin-site-content-page">
      {/* Toolbar */}
      <div className="px-4 md:px-6 py-3 border-b border-slate-200 bg-white flex items-center justify-between gap-3 flex-wrap">
        <div>
          <h1 className="text-lg md:text-xl font-bold text-[#0a2350]">Landing Content (CMS)</h1>
          <p className="text-xs text-slate-500">Edit teks landing page dengan pratinjau langsung. Kolom kosong = pakai teks bawaan.</p>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={resetAll} disabled={busy}
                  className="text-xs text-slate-500 hover:text-red-600 inline-flex items-center gap-1.5 disabled:opacity-50"
                  data-testid="cms-reset-all">
            <RotateCcw className="h-4 w-4" /> Reset semua
          </button>
          <button onClick={save} disabled={busy}
                  className="px-5 py-2 rounded-lg bg-[#0a2350] text-white text-sm font-semibold inline-flex items-center gap-2 hover:bg-[#1a355c] disabled:opacity-50"
                  data-testid="cms-save">
            {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />} Simpan
          </button>
        </div>
      </div>

      {msg && (
        <div className={`px-4 md:px-6 py-2 text-sm border-b ${msg.kind === "error" ? "bg-red-50 border-red-200 text-red-800" : "bg-emerald-50 border-emerald-200 text-emerald-800"}`} data-testid="cms-msg">
          {msg.text}
        </div>
      )}

      <div className="flex-1 min-h-0 flex flex-col lg:flex-row">
        {/* ---------- Left: editor ---------- */}
        <div className="lg:w-[46%] xl:w-[42%] flex flex-col border-r border-slate-200 min-h-0">
          <div className="px-4 md:px-6 pt-3 flex items-center gap-1 border-b border-slate-100">
            {[
              { k: "editor", label: "Teks per Bagian" },
              { k: "faqs", label: `FAQ (${(content.faqs || []).length})` },
              { k: "images", label: "Gambar" },
              { k: "json", label: "JSON" },
            ].map((t) => (
              <button key={t.k}
                      onClick={() => { setTab(t.k); if (t.k === "json") setJsonText(JSON.stringify(content, null, 2)); }}
                      className={`px-3 py-2 text-sm font-semibold border-b-2 -mb-px transition-colors ${tab === t.k ? "border-[#0a2350] text-[#0a2350]" : "border-transparent text-slate-500 hover:text-[#0a2350]"}`}
                      data-testid={`cms-tab-${t.k}`}>
                {t.label}
              </button>
            ))}
          </div>

          {/* Section jump chips */}
          {tab === "editor" && (
            <div className="px-4 md:px-6 py-2 border-b border-slate-100 flex gap-1.5 overflow-x-auto">
              {SECTIONS.map((s) => (
                <button key={s.id} onClick={() => jumpTo(s.id)}
                        className="whitespace-nowrap px-2.5 py-1 rounded-full bg-slate-100 hover:bg-[#0a2350] hover:text-white text-[11px] font-semibold text-slate-600 transition-colors"
                        data-testid={`cms-jump-${s.id}`}>
                  {s.title}
                </button>
              ))}
            </div>
          )}

          <div ref={editorScrollRef} className="flex-1 overflow-y-auto p-4 md:p-6">
            {tab === "editor" && (
              <div className="space-y-6">
                {SECTIONS.map((s) => (
                  <div key={s.id} id={`sec-${s.id}`} className="rounded-2xl border border-slate-200 bg-white overflow-hidden scroll-mt-4">
                    <div className="px-4 py-2.5 border-b border-slate-100 bg-slate-50/60">
                      <div className="text-xs font-bold uppercase tracking-widest text-[#0a2350]">{s.title}</div>
                    </div>
                    <div className="p-4 space-y-4">
                      {s.keys.map(({ key, label }) => {
                        const ov = (content.overrides || {})[key] || {};
                        return (
                          <div key={key} className="space-y-1.5">
                            <div className="text-xs font-semibold text-slate-700">{label}</div>
                            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                              <div>
                                <label className="text-[10px] text-slate-400 uppercase tracking-widest">Indonesia</label>
                                <textarea rows={2} value={ov.id || ""}
                                          onChange={(e) => setOverride(key, "id", e.target.value)}
                                          placeholder="(pakai bawaan)"
                                          className="mt-0.5 w-full rounded-lg border border-slate-200 px-3 py-1.5 text-sm focus:outline-none focus:border-[#0a2350]/40"
                                          data-testid={`cms-input-${key}-id`} />
                              </div>
                              <div>
                                <label className="text-[10px] text-slate-400 uppercase tracking-widest">English</label>
                                <textarea rows={2} value={ov.en || ""}
                                          onChange={(e) => setOverride(key, "en", e.target.value)}
                                          placeholder="(use default)"
                                          className="mt-0.5 w-full rounded-lg border border-slate-200 px-3 py-1.5 text-sm focus:outline-none focus:border-[#0a2350]/40"
                                          data-testid={`cms-input-${key}-en`} />
                              </div>
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                ))}
              </div>
            )}

            {tab === "faqs" && (
              <div>
                <div className="mb-3 flex items-center justify-between">
                  <div className="text-xs text-slate-500">Kosong = pakai FAQ bawaan.</div>
                  <button onClick={addFaq} className="px-3 py-1.5 rounded-lg bg-[#0a2350] text-white text-xs font-semibold inline-flex items-center gap-1.5" data-testid="cms-faq-add">
                    <Plus className="h-3.5 w-3.5" /> Tambah FAQ
                  </button>
                </div>
                <div className="space-y-4">
                  {(content.faqs || []).map((f, i) => (
                    <div key={i} className="rounded-2xl border border-slate-200 bg-white p-4" data-testid={`cms-faq-${i}`}>
                      <div className="flex items-center justify-between mb-3">
                        <div className="text-xs font-bold uppercase tracking-widest text-[#0a2350]">FAQ #{i + 1}</div>
                        <button onClick={() => rmFaq(i)} className="text-xs text-red-600 inline-flex items-center gap-1" data-testid={`cms-faq-rm-${i}`}>
                          <Trash2 className="h-3.5 w-3.5" /> Hapus
                        </button>
                      </div>
                      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                        <div>
                          <label className="text-[10px] uppercase tracking-widest text-slate-500">Pertanyaan (ID)</label>
                          <input value={f?.q?.id || ""} onChange={(e) => setFaq(i, "q.id", e.target.value)} className="w-full rounded-lg border border-slate-200 px-3 py-1.5 text-sm" />
                        </div>
                        <div>
                          <label className="text-[10px] uppercase tracking-widest text-slate-500">Question (EN)</label>
                          <input value={f?.q?.en || ""} onChange={(e) => setFaq(i, "q.en", e.target.value)} className="w-full rounded-lg border border-slate-200 px-3 py-1.5 text-sm" />
                        </div>
                        <div>
                          <label className="text-[10px] uppercase tracking-widest text-slate-500">Jawaban (ID)</label>
                          <textarea rows={3} value={f?.a?.id || ""} onChange={(e) => setFaq(i, "a.id", e.target.value)} className="w-full rounded-lg border border-slate-200 px-3 py-1.5 text-sm" />
                        </div>
                        <div>
                          <label className="text-[10px] uppercase tracking-widest text-slate-500">Answer (EN)</label>
                          <textarea rows={3} value={f?.a?.en || ""} onChange={(e) => setFaq(i, "a.en", e.target.value)} className="w-full rounded-lg border border-slate-200 px-3 py-1.5 text-sm" />
                        </div>
                      </div>
                    </div>
                  ))}
                  {(content.faqs || []).length === 0 && (
                    <div className="text-center py-12 text-slate-400 border border-dashed border-slate-200 rounded-2xl">
                      Belum ada FAQ kustom - situs memakai FAQ bawaan. Klik "Tambah FAQ".
                    </div>
                  )}
                </div>
              </div>
            )}

            {tab === "images" && (
              <div>
                <div className="mb-4 text-xs text-slate-500">
                  Ganti gambar landing (hero &amp; 4 kartu infrastruktur). Kosong = pakai gambar bawaan.
                  Upload langsung, pilih dari Media Library, atau tempel URL eksternal.
                </div>
                <div className="space-y-4">
                  {IMAGE_SLOTS.map(({ slot, label }) => {
                    const entry = (content.images || {})[slot] || {};
                    return (
                      <div key={slot} className="rounded-2xl border border-slate-200 bg-white p-4" data-testid={`cms-image-${slot}`}>
                        <div className="flex items-center justify-between mb-3">
                          <div className="text-xs font-bold uppercase tracking-widest text-[#0a2350]">{label}</div>
                          {entry.url && (
                            <button onClick={() => clearImage(slot)}
                                    className="text-xs text-red-600 inline-flex items-center gap-1"
                                    data-testid={`cms-image-clear-${slot}`}>
                              <RotateCcw className="h-3.5 w-3.5" /> Pakai bawaan
                            </button>
                          )}
                        </div>

                        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                          {/* Preview */}
                          <div>
                            <label className="text-[10px] uppercase tracking-widest text-slate-400">Pratinjau</label>
                            <div className="mt-1 aspect-[4/3] rounded-xl border border-slate-200 overflow-hidden bg-slate-50 flex items-center justify-center">
                              {entry.url ? (
                                <img src={entry.url} alt={label} className="h-full w-full object-cover"
                                     onError={(e) => { e.currentTarget.style.display = "none"; }} />
                              ) : (
                                <span className="text-xs text-slate-400">(gambar bawaan)</span>
                              )}
                            </div>
                          </div>

                          {/* Controls */}
                          <div className="space-y-3">
                            <div>
                              <label className="text-[10px] uppercase tracking-widest text-slate-400">Upload gambar baru</label>
                              <label className={`mt-1 w-full px-3 py-2 rounded-lg border border-dashed text-xs font-semibold inline-flex items-center justify-center gap-2 transition-colors ${uploadingSlot === slot ? "cursor-wait border-slate-200 bg-slate-50 text-slate-400" : "cursor-pointer border-[#0a2350]/30 text-[#0a2350] hover:border-[#f5b120] hover:bg-amber-50"}`}>
                                {uploadingSlot === slot ? <Loader2 className="h-4 w-4 animate-spin" /> : <UploadCloud className="h-4 w-4" />}
                                {uploadingSlot === slot ? "Mengunggah…" : "Pilih file dari komputer"}
                                <input type="file"
                                       accept="image/png,image/jpeg,image/webp,image/gif,image/svg+xml"
                                       disabled={!!uploadingSlot}
                                       onChange={(e) => {
                                         const file = e.target.files?.[0];
                                         e.target.value = "";
                                         uploadImage(slot, file);
                                       }}
                                       className="sr-only"
                                       data-testid={`cms-image-upload-${slot}`} />
                              </label>
                              <div className="mt-1 text-[10px] text-slate-400">PNG, JPEG, WebP, GIF, atau SVG; maksimum 8 MB.</div>
                            </div>
                            <div>
                              <label className="text-[10px] uppercase tracking-widest text-slate-400">URL gambar</label>
                              <input value={entry.url || ""}
                                     onChange={(e) => setImage(slot, "url", e.target.value)}
                                     placeholder="/api/portal/media/file/... atau https://..."
                                     className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-1.5 text-sm font-mono"
                                     data-testid={`cms-image-url-${slot}`} />
                            </div>
                            <div>
                              <label className="text-[10px] uppercase tracking-widest text-slate-400">Pilih dari Media Library</label>
                              {mediaLoading ? (
                                <div className="text-xs text-slate-400 mt-1">Memuat media…</div>
                              ) : mediaRows.length === 0 ? (
                                <div className="text-xs text-slate-400 mt-1">
                                  Belum ada media. Gunakan tombol upload di atas.
                                </div>
                              ) : (
                                <div className="mt-1 grid grid-cols-4 gap-1.5 max-h-28 overflow-y-auto">
                                  {mediaRows.map((m) => (
                                    <button key={m.id} type="button" onClick={() => setImage(slot, "url", m.url)}
                                            title={m.filename}
                                            className={`aspect-square rounded-lg border overflow-hidden bg-slate-50 hover:border-[#f5b120] transition-colors ${entry.url === m.url ? "border-[#f5b120] ring-2 ring-[#f5b120]/40" : "border-slate-200"}`}>
                                      <img src={m.url} alt={m.alt_text || m.filename} className="h-full w-full object-cover" loading="lazy" />
                                    </button>
                                  ))}
                                </div>
                              )}
                            </div>
                            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                              <div>
                                <label className="text-[10px] uppercase tracking-widest text-slate-400">Alt (Indonesia)</label>
                                <input value={entry.alt_id || ""}
                                       onChange={(e) => setImage(slot, "alt_id", e.target.value)}
                                       placeholder="teks alternatif (ID)"
                                       className="mt-0.5 w-full rounded-lg border border-slate-200 px-3 py-1.5 text-sm" />
                              </div>
                              <div>
                                <label className="text-[10px] uppercase tracking-widest text-slate-400">Alt (English)</label>
                                <input value={entry.alt_en || ""}
                                       onChange={(e) => setImage(slot, "alt_en", e.target.value)}
                                       placeholder="alt text (EN)"
                                       className="mt-0.5 w-full rounded-lg border border-slate-200 px-3 py-1.5 text-sm" />
                              </div>
                            </div>
                          </div>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            )}

            {tab === "json" && (
              <div>
                <div className="mb-2 text-xs text-slate-500">Dokumen lengkap - untuk power user.</div>
                <textarea rows={26} value={jsonText} onChange={(e) => setJsonText(e.target.value)}
                          className="w-full font-mono text-xs rounded-2xl border border-slate-200 p-4 bg-slate-50"
                          data-testid="cms-json-editor" />
              </div>
            )}
          </div>
        </div>

        {/* ---------- Right: live preview ---------- */}
        <div className="flex-1 min-h-0 flex flex-col bg-slate-100">
          <div className="px-4 py-2 border-b border-slate-200 bg-white flex items-center justify-between gap-2 flex-wrap">
            <div className="flex items-center gap-1.5 text-xs font-semibold text-slate-500">
              <Eye className="h-4 w-4 text-[#f5b120]" /> Pratinjau langsung
            </div>
            <div className="flex items-center gap-2">
              {/* language toggle */}
              <div className="flex rounded-lg border border-slate-200 overflow-hidden text-[11px] font-bold">
                {["id", "en"].map((l) => (
                  <button key={l} onClick={() => setPreviewLang(l)}
                          className={`px-2.5 py-1 uppercase ${previewLang === l ? "bg-[#0a2350] text-white" : "bg-white text-slate-500"}`}
                          data-testid={`cms-preview-lang-${l}`}>
                    {l}
                  </button>
                ))}
              </div>
              {/* device toggle */}
              <div className="flex rounded-lg border border-slate-200 overflow-hidden">
                {Object.entries(DEVICES).map(([k, v]) => {
                  const Ic = v.icon;
                  return (
                    <button key={k} onClick={() => setDevice(k)} title={v.label}
                            className={`px-2.5 py-1.5 ${device === k ? "bg-[#0a2350] text-white" : "bg-white text-slate-500"}`}
                            data-testid={`cms-device-${k}`}>
                      <Ic className="h-4 w-4" />
                    </button>
                  );
                })}
              </div>
              <button onClick={() => { if (iframeRef.current) iframeRef.current.src = previewUrl; }}
                      title="Muat ulang pratinjau"
                      className="px-2.5 py-1.5 rounded-lg border border-slate-200 bg-white text-slate-500 hover:text-[#0a2350]"
                      data-testid="cms-preview-reload">
                <RefreshCw className="h-4 w-4" />
              </button>
            </div>
          </div>
          <div className="flex-1 min-h-0 overflow-auto p-3 flex justify-center">
            <iframe
              ref={iframeRef}
              title="Landing preview"
              src={previewUrl}
              onLoad={() => pushPreview()}
              className="bg-white rounded-xl shadow-lg border border-slate-200 flex-shrink-0"
              style={{ width: DEVICES[device].w, height: "100%", transition: "width 0.25s ease" }}
              data-testid="cms-preview-iframe"
            />
          </div>
        </div>
      </div>
    </div>
  );
};

export default AdminSiteContent;
