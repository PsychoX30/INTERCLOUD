import React, { useEffect, useState, useMemo } from "react";
import { Save, RotateCcw, Plus, Trash2, Loader2, HelpCircle } from "lucide-react";
import { api } from "../../../portal/api";

// Curated list of the highest-value editable i18n keys. Admins can still add
// arbitrary keys via the raw JSON tab — this is the polished form path.
const CURATED_KEYS = [
  { section: "Hero",     key: "hero.tag",         label: "Hero — Tagline" },
  { section: "Hero",     key: "hero.h1a",         label: "Hero — Headline (start)" },
  { section: "Hero",     key: "hero.h1_stable",   label: "Hero — Adjective 1" },
  { section: "Hero",     key: "hero.h1_secure",   label: "Hero — Adjective 2" },
  { section: "Hero",     key: "hero.h1c",         label: "Hero — Headline (end)" },
  { section: "Hero",     key: "hero.body",        label: "Hero — Body (start)" },
  { section: "Hero",     key: "hero.body3",       label: "Hero — Body (end)" },
  { section: "Features", key: "feat.title",       label: "Why-Us — Title" },
  { section: "Features", key: "feat.subtitle",    label: "Why-Us — Subtitle" },
  { section: "Services", key: "svc.title",        label: "Services — Title" },
  { section: "Services", key: "svc.subtitle",    label: "Services — Subtitle" },
  { section: "Pricing",  key: "pr.title",         label: "Pricing — Title" },
  { section: "Pricing",  key: "pr.subtitle",      label: "Pricing — Subtitle" },
  { section: "CTA",      key: "cta_sec.title_a",  label: "CTA — Title (start)" },
  { section: "CTA",      key: "cta_sec.title_b",  label: "CTA — Title (highlight)" },
  { section: "CTA",      key: "cta_sec.title_c",  label: "CTA — Title (end)" },
  { section: "CTA",      key: "cta_sec.body",     label: "CTA — Body" },
  { section: "FAQ",      key: "faq.title",        label: "FAQ — Title" },
  { section: "FAQ",      key: "faq.subtitle",     label: "FAQ — Subtitle" },
  { section: "FAQ",      key: "faq.helpTitle",    label: "FAQ — Help Card Title" },
  { section: "FAQ",      key: "faq.helpBody",     label: "FAQ — Help Card Body" },
  { section: "Footer",   key: "footer.tagline",   label: "Footer — Tagline" },
  { section: "Footer",   key: "footer.copy",      label: "Footer — Copyright line" },
];

const emptyFaq = () => ({
  q: { id: "", en: "" },
  a: { id: "", en: "" },
});

const AdminSiteContent = () => {
  const [content, setContent] = useState(null);
  const [tab, setTab] = useState("curated");        // curated | faqs | json
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null);
  const [jsonText, setJsonText] = useState("");

  useEffect(() => {
    api.get("/landing-content").then(({ data }) => {
      setContent(data);
      setJsonText(JSON.stringify(data, null, 2));
    });
  }, []);

  const setOverride = (key, lang, val) => {
    setContent((c) => ({
      ...c,
      overrides: {
        ...(c.overrides || {}),
        [key]: {
          ...((c.overrides || {})[key] || { id: "", en: "" }),
          [lang]: val,
        },
      },
    }));
  };

  const setFaq = (i, path, val) => {
    setContent((c) => {
      const faqs = [...(c.faqs || [])];
      const f = { ...(faqs[i] || emptyFaq()) };
      // path is one of "q.id", "q.en", "a.id", "a.en"
      const [field, lang] = path.split(".");
      f[field] = { ...(f[field] || { id: "", en: "" }), [lang]: val };
      faqs[i] = f;
      return { ...c, faqs };
    });
  };

  const addFaq = () => setContent((c) => ({ ...c, faqs: [...(c.faqs || []), emptyFaq()] }));
  const rmFaq  = (i) => setContent((c) => ({ ...c, faqs: (c.faqs || []).filter((_, idx) => idx !== i) }));

  const save = async () => {
    setBusy(true); setMsg(null);
    try {
      let body = content;
      if (tab === "json") {
        try { body = JSON.parse(jsonText); }
        catch (e) { setMsg({ kind: "error", text: `Invalid JSON: ${e.message}` }); setBusy(false); return; }
      }
      const { data } = await api.post("/admin/landing-content", body);
      setContent(data);
      setJsonText(JSON.stringify(data, null, 2));
      setMsg({ kind: "ok", text: "Saved — landing page will reflect changes on next load." });
    } catch (e) {
      setMsg({ kind: "error", text: e?.response?.data?.detail || e.message });
    } finally { setBusy(false); }
  };

  const resetAll = async () => {
    if (!window.confirm("Reset ALL landing content overrides to defaults?")) return;
    setBusy(true); setMsg(null);
    try {
      const { data } = await api.delete("/admin/landing-content");
      setContent(data);
      setJsonText(JSON.stringify(data, null, 2));
      setMsg({ kind: "ok", text: "All overrides cleared." });
    } catch (e) { setMsg({ kind: "error", text: e?.response?.data?.detail || e.message }); }
    finally { setBusy(false); }
  };

  const grouped = useMemo(() => {
    const g = {};
    for (const c of CURATED_KEYS) (g[c.section] = g[c.section] || []).push(c);
    return g;
  }, []);

  if (!content) {
    return <div className="p-8 text-slate-400">Loading…</div>;
  }

  return (
    <div className="p-6 md:p-8 max-w-6xl mx-auto" data-testid="admin-site-content-page">
      <div className="mb-6 flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-2xl md:text-3xl font-bold text-[#0a2350]">Landing Content (CMS)</h1>
          <p className="mt-1 text-sm text-slate-500 max-w-2xl">
            Override any text on the public landing page. Empty fields fall back to the shipped defaults.
            Bilingual (Indonesian &amp; English). Changes go live on the next page load.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={resetAll} disabled={busy} className="text-sm text-slate-500 hover:text-red-600 inline-flex items-center gap-1.5 disabled:opacity-50" data-testid="cms-reset-all">
            <RotateCcw className="h-4 w-4" /> Reset all
          </button>
          <button onClick={save} disabled={busy} className="px-5 py-2 rounded-lg bg-[#0a2350] text-white text-sm font-semibold inline-flex items-center gap-2 hover:bg-[#1a355c] disabled:opacity-50" data-testid="cms-save">
            {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />} Save
          </button>
        </div>
      </div>

      {msg && (
        <div className={`mb-5 rounded-xl px-4 py-3 text-sm border ${msg.kind === "error" ? "bg-red-50 border-red-200 text-red-800" : "bg-emerald-50 border-emerald-200 text-emerald-800"}`} data-testid="cms-msg">
          {msg.text}
        </div>
      )}

      <div className="mb-4 border-b border-slate-200 flex items-center gap-1">
        {[
          { k: "curated", label: "Text (curated)" },
          { k: "faqs",    label: `FAQs (${(content.faqs || []).length})` },
          { k: "json",    label: "Raw JSON" },
        ].map((t) => (
          <button key={t.k} onClick={() => { setTab(t.k); if (t.k === "json") setJsonText(JSON.stringify(content, null, 2)); }}
                  className={`px-4 py-2 text-sm font-semibold border-b-2 -mb-px transition-colors ${tab === t.k ? "border-[#0a2350] text-[#0a2350]" : "border-transparent text-slate-500 hover:text-[#0a2350]"}`}
                  data-testid={`cms-tab-${t.k}`}>
            {t.label}
          </button>
        ))}
      </div>

      {tab === "curated" && (
        <div className="space-y-6">
          {Object.entries(grouped).map(([section, keys]) => (
            <div key={section} className="rounded-2xl border border-slate-200 bg-white overflow-hidden">
              <div className="px-5 py-3 border-b border-slate-100 bg-slate-50/50">
                <div className="text-xs font-bold uppercase tracking-widest text-[#0a2350]">{section}</div>
              </div>
              <div className="p-5 space-y-4">
                {keys.map(({ key, label }) => {
                  const ov = (content.overrides || {})[key] || {};
                  return (
                    <div key={key} className="grid grid-cols-1 md:grid-cols-12 gap-3 items-start">
                      <div className="md:col-span-3">
                        <div className="text-xs font-semibold text-slate-700">{label}</div>
                        <div className="text-[10px] font-mono text-slate-400">{key}</div>
                      </div>
                      <div className="md:col-span-4">
                        <label className="text-[10px] text-slate-500 uppercase tracking-widest">Bahasa Indonesia</label>
                        <textarea rows={2} value={ov.id || ""}
                                  onChange={(e) => setOverride(key, "id", e.target.value)}
                                  placeholder="(uses default)"
                                  className="mt-0.5 w-full rounded-lg border border-slate-200 px-3 py-1.5 text-sm focus:outline-none focus:border-[#0a2350]/40"
                                  data-testid={`cms-input-${key}-id`} />
                      </div>
                      <div className="md:col-span-5">
                        <label className="text-[10px] text-slate-500 uppercase tracking-widest">English</label>
                        <textarea rows={2} value={ov.en || ""}
                                  onChange={(e) => setOverride(key, "en", e.target.value)}
                                  placeholder="(uses default)"
                                  className="mt-0.5 w-full rounded-lg border border-slate-200 px-3 py-1.5 text-sm focus:outline-none focus:border-[#0a2350]/40"
                                  data-testid={`cms-input-${key}-en`} />
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
            <div className="text-xs text-slate-500 flex items-center gap-1.5">
              <HelpCircle className="h-3.5 w-3.5" /> Empty list falls back to the shipped FAQs from <span className="font-mono">mock/data.js</span>.
            </div>
            <button onClick={addFaq} className="px-3 py-1.5 rounded-lg bg-[#0a2350] text-white text-xs font-semibold inline-flex items-center gap-1.5"
                    data-testid="cms-faq-add">
              <Plus className="h-3.5 w-3.5" /> Add FAQ
            </button>
          </div>
          <div className="space-y-4">
            {(content.faqs || []).map((f, i) => (
              <div key={i} className="rounded-2xl border border-slate-200 bg-white p-5" data-testid={`cms-faq-${i}`}>
                <div className="flex items-center justify-between mb-3">
                  <div className="text-xs font-bold uppercase tracking-widest text-[#0a2350]">FAQ #{i + 1}</div>
                  <button onClick={() => rmFaq(i)} className="text-xs text-red-600 inline-flex items-center gap-1" data-testid={`cms-faq-rm-${i}`}>
                    <Trash2 className="h-3.5 w-3.5" /> Remove
                  </button>
                </div>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                  <div>
                    <label className="text-[10px] uppercase tracking-widest text-slate-500">Question (ID)</label>
                    <input value={f?.q?.id || ""} onChange={(e) => setFaq(i, "q.id", e.target.value)}
                           className="w-full rounded-lg border border-slate-200 px-3 py-1.5 text-sm" />
                  </div>
                  <div>
                    <label className="text-[10px] uppercase tracking-widest text-slate-500">Question (EN)</label>
                    <input value={f?.q?.en || ""} onChange={(e) => setFaq(i, "q.en", e.target.value)}
                           className="w-full rounded-lg border border-slate-200 px-3 py-1.5 text-sm" />
                  </div>
                  <div>
                    <label className="text-[10px] uppercase tracking-widest text-slate-500">Answer (ID)</label>
                    <textarea rows={3} value={f?.a?.id || ""} onChange={(e) => setFaq(i, "a.id", e.target.value)}
                              className="w-full rounded-lg border border-slate-200 px-3 py-1.5 text-sm" />
                  </div>
                  <div>
                    <label className="text-[10px] uppercase tracking-widest text-slate-500">Answer (EN)</label>
                    <textarea rows={3} value={f?.a?.en || ""} onChange={(e) => setFaq(i, "a.en", e.target.value)}
                              className="w-full rounded-lg border border-slate-200 px-3 py-1.5 text-sm" />
                  </div>
                </div>
              </div>
            ))}
            {(content.faqs || []).length === 0 && (
              <div className="text-center py-12 text-slate-400 border border-dashed border-slate-200 rounded-2xl">
                No CMS FAQs — the public site is using the shipped defaults. Click "Add FAQ" to override.
              </div>
            )}
          </div>
        </div>
      )}

      {tab === "json" && (
        <div>
          <div className="mb-2 text-xs text-slate-500">
            Full document — for power users. Includes any key not surfaced in the "curated" tab.
          </div>
          <textarea rows={26} value={jsonText} onChange={(e) => setJsonText(e.target.value)}
                    className="w-full font-mono text-xs rounded-2xl border border-slate-200 p-4 bg-slate-50"
                    data-testid="cms-json-editor" />
        </div>
      )}
    </div>
  );
};

export default AdminSiteContent;
