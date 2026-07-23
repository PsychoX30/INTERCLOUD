import React, { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import axios from "axios";
import Header from "../components/Header";
import Footer from "../components/Footer";
import { Search, Tag, Calendar, Eye, ArrowRight, X } from "lucide-react";

const API = `${process.env.REACT_APP_BACKEND_URL}/api/portal`;

const usePageMeta = ({ title, description }) => {
  useEffect(() => {
    if (title) document.title = title;
    if (description) {
      let el = document.querySelector('meta[name="description"]');
      if (!el) { el = document.createElement("meta"); el.name = "description"; document.head.appendChild(el); }
      el.content = description;
    }
    return () => { document.title = "Intercloud Digital Inovasi"; };
  }, [title, description]);
};

const formatDate = (iso) => {
  if (!iso) return "";
  try {
    return new Date(iso).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
  } catch { return ""; }
};

const ArticlesList = () => {
  const [params, setParams] = useSearchParams();
  const q = params.get("q") || "";
  const tag = params.get("tag") || "";
  const [rows, setRows] = useState(null);
  const [total, setTotal] = useState(0);
  const [tags, setTags] = useState([]);
  const [input, setInput] = useState(q);

  usePageMeta({
    title: q ? `Search: “${q}” — Intercloud Articles`
             : tag ? `#${tag} — Intercloud Articles`
             : "Articles & Insights — PT Intercloud Digital Inovasi",
    description: "Product updates, industry insights, and announcements from PT Intercloud Digital Inovasi — Indonesia’s trusted cloud, colocation, and connectivity provider.",
  });

  useEffect(() => {
    const p = new URLSearchParams();
    if (q) p.set("q", q);
    if (tag) p.set("tag", tag);
    p.set("limit", "24");
    axios.get(`${API}/public/articles?${p.toString()}`).then((r) => {
      setRows(r.data.results);
      setTotal(r.data.total);
    });
    axios.get(`${API}/public/articles/tags`).then((r) => setTags(r.data));
  }, [q, tag]);

  const featured = useMemo(() => (rows || []).find((a) => a.is_featured), [rows]);
  const rest = useMemo(() => (rows || []).filter((a) => !featured || a.id !== featured.id), [rows, featured]);

  const submit = (e) => {
    e.preventDefault();
    const next = new URLSearchParams(params);
    if (input) next.set("q", input); else next.delete("q");
    setParams(next);
  };

  const clearFilters = () => setParams({});

  return (
    <div className="min-h-screen bg-white">
      <Header />
      <main className="pt-24 pb-16">
        <section className="bg-[#0a2350] text-white">
          <div className="max-w-6xl mx-auto px-6 py-16 md:py-20">
            <div className="text-[11px] font-bold uppercase tracking-widest text-[#f5b120]">Articles & Insights</div>
            <h1 className="mt-3 text-4xl sm:text-5xl lg:text-6xl font-extrabold leading-tight max-w-3xl">
              What we're building, seeing, and learning.
            </h1>
            <p className="mt-4 text-base text-white/70 max-w-2xl leading-relaxed">
              Product releases, engineering deep-dives, industry perspectives, and behind-the-scenes stories from PT Intercloud Digital Inovasi.
            </p>
            <form onSubmit={submit} className="mt-8 flex items-center gap-2 max-w-xl">
              <div className="flex-1 flex items-center gap-3 h-12 rounded-full bg-white/10 border border-white/20 px-5">
                <Search className="h-4 w-4 text-white/60" />
                <input value={input} onChange={(e) => setInput(e.target.value)} placeholder="Search articles…" className="flex-1 bg-transparent outline-none placeholder-white/50 text-sm" data-testid="articles-search-input" />
              </div>
              <button type="submit" className="h-12 px-6 rounded-full bg-[#f5b120] hover:bg-[#ffcc4d] text-[#0a2350] font-bold text-sm transition-colors" data-testid="articles-search-btn">
                Search
              </button>
            </form>
            {(q || tag) && (
              <div className="mt-4 flex items-center gap-2 text-sm text-white/80" data-testid="active-filters">
                <span>Active filter{q && tag ? "s" : ""}:</span>
                {q && <span className="inline-flex items-center gap-1 px-3 py-1 rounded-full bg-white/10 border border-white/20">“{q}”</span>}
                {tag && <span className="inline-flex items-center gap-1 px-3 py-1 rounded-full bg-white/10 border border-white/20"><Tag className="h-3 w-3" /> #{tag}</span>}
                <button onClick={clearFilters} className="ml-2 inline-flex items-center gap-1 underline text-white/60 hover:text-white text-xs" data-testid="clear-filters"><X className="h-3 w-3" /> clear</button>
              </div>
            )}
          </div>
        </section>

        <section className="max-w-6xl mx-auto px-6 mt-12">
          {tags.length > 0 && (
            <div className="mb-8 flex flex-wrap items-center gap-2">
              <span className="text-[11px] font-bold uppercase tracking-widest text-slate-500">Topics:</span>
              {tags.slice(0, 12).map((t) => {
                const active = tag === t.tag;
                return (
                  <button key={t.tag} onClick={() => {
                    const next = new URLSearchParams(params);
                    if (active) next.delete("tag"); else next.set("tag", t.tag);
                    setParams(next);
                  }} data-testid={`tag-chip-${t.tag}`}
                    className={`text-xs px-3 h-8 inline-flex items-center gap-1 rounded-full border transition-colors ${active ? "bg-[#0a2350] text-white border-[#0a2350]" : "bg-white text-slate-600 border-slate-200 hover:border-[#f5b120] hover:text-[#0a2350]"}`}>
                    <Tag className="h-3 w-3" /> {t.tag} <span className="text-slate-400 text-[10px]">({t.count})</span>
                  </button>
                );
              })}
            </div>
          )}

          {rows === null && <div className="py-20 text-center text-slate-500">Loading articles…</div>}
          {rows && rows.length === 0 && (
            <div className="py-20 text-center">
              <div className="text-xl font-extrabold text-[#0a2350]">No articles match your search.</div>
              <p className="mt-2 text-sm text-slate-500">Try a different keyword or clear the filters to see everything.</p>
              <button onClick={clearFilters} className="mt-4 inline-flex items-center gap-2 px-5 h-11 rounded-full bg-[#0a2350] text-white text-sm font-bold hover:bg-[#f5b120] hover:text-[#0a2350] transition-colors">
                Show all articles
              </button>
            </div>
          )}

          {featured && !q && !tag && (
            <Link to={`/articles/${featured.slug}`} className="block group mb-10" data-testid={`featured-${featured.slug}`}>
              <div className="grid md:grid-cols-2 gap-8 rounded-3xl overflow-hidden bg-white border border-slate-200 hover:border-[#f5b120] transition-colors">
                <div className="aspect-video md:aspect-auto overflow-hidden bg-slate-100">
                  {featured.cover_image_url && <img src={featured.cover_image_url} alt={featured.cover_image_alt || featured.title} className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-500" />}
                </div>
                <div className="p-6 md:p-10 flex flex-col justify-center">
                  <div className="text-[10px] font-bold uppercase tracking-widest text-[#f5b120]">Featured · {featured.category || "Article"}</div>
                  <h2 className="mt-3 text-2xl md:text-3xl font-extrabold text-[#0a2350] leading-tight group-hover:text-[#f5b120] transition-colors">{featured.title}</h2>
                  <p className="mt-3 text-slate-600 leading-relaxed">{featured.excerpt}</p>
                  <div className="mt-5 flex items-center gap-4 text-xs text-slate-500">
                    <span className="inline-flex items-center gap-1"><Calendar className="h-3 w-3" /> {formatDate(featured.published_at)}</span>
                    <span className="inline-flex items-center gap-1"><Eye className="h-3 w-3" /> {featured.view_count} reads</span>
                  </div>
                  <div className="mt-5 inline-flex items-center gap-2 text-sm font-bold text-[#0a2350] group-hover:text-[#f5b120]">Read the story <ArrowRight className="h-4 w-4" /></div>
                </div>
              </div>
            </Link>
          )}

          {rows && rows.length > 0 && (
            <>
              <div className="mb-6 flex items-center justify-between">
                <div className="text-sm text-slate-500" data-testid="results-count">
                  {total} article{total === 1 ? "" : "s"}{q || tag ? " match" : ""}
                </div>
              </div>
              <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-6">
                {rest.map((a) => <ArticleCard key={a.id} a={a} />)}
              </div>
            </>
          )}
        </section>
      </main>
      <Footer />
    </div>
  );
};

const ArticleCard = ({ a }) => (
  <Link to={`/articles/${a.slug}`} className="group block rounded-2xl overflow-hidden bg-white border border-slate-200 hover:border-[#f5b120] transition-colors" data-testid={`article-card-${a.slug}`}>
    <div className="aspect-video overflow-hidden bg-slate-100">
      {a.cover_image_url ? (
        <img src={a.cover_image_url} alt={a.cover_image_alt || a.title} className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-500" loading="lazy" />
      ) : (
        <div className="w-full h-full bg-gradient-to-br from-[#0a2350] to-[#1a3a70] flex items-center justify-center text-white/40 text-xs font-bold uppercase tracking-widest">Intercloud</div>
      )}
    </div>
    <div className="p-5">
      <div className="text-[10px] font-bold uppercase tracking-widest text-[#f5b120]">{a.category || "Article"}</div>
      <h3 className="mt-2 text-lg font-extrabold text-[#0a2350] leading-snug group-hover:text-[#f5b120] transition-colors line-clamp-2">{a.title}</h3>
      <p className="mt-2 text-sm text-slate-600 line-clamp-3">{a.excerpt}</p>
      <div className="mt-4 flex flex-wrap gap-1.5">
        {(a.tags || []).slice(0, 3).map((t) => (
          <span key={t} className="text-[10px] px-1.5 py-0.5 rounded bg-slate-100 border border-slate-200 text-slate-600">#{t}</span>
        ))}
      </div>
      <div className="mt-4 flex items-center gap-4 text-[11px] text-slate-500">
        <span className="inline-flex items-center gap-1"><Calendar className="h-3 w-3" /> {formatDate(a.published_at)}</span>
        <span className="inline-flex items-center gap-1"><Eye className="h-3 w-3" /> {a.view_count}</span>
      </div>
    </div>
  </Link>
);

export default ArticlesList;
