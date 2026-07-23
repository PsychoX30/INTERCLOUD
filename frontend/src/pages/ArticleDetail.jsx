import React, { useEffect, useMemo, useState } from "react";
import { Link, useParams, useNavigate } from "react-router-dom";
import axios from "axios";
import Header from "../components/Header";
import Footer from "../components/Footer";
import { Calendar, Eye, Tag, ArrowLeft, ArrowRight, User, Share2 } from "lucide-react";

const API = `${process.env.REACT_APP_BACKEND_URL}/api/portal`;

const upsertMeta = (attr, key, content) => {
  if (!content) return;
  let el = document.head.querySelector(`meta[${attr}="${key}"]`);
  if (!el) {
    el = document.createElement("meta");
    el.setAttribute(attr, key);
    document.head.appendChild(el);
  }
  el.setAttribute("content", content);
};

const upsertLink = (rel, href) => {
  if (!href) return;
  let el = document.head.querySelector(`link[rel="${rel}"]`);
  if (!el) {
    el = document.createElement("link");
    el.setAttribute("rel", rel);
    document.head.appendChild(el);
  }
  el.setAttribute("href", href);
};

const useArticleSEO = (a) => {
  useEffect(() => {
    if (!a) return;
    const title = a.meta_title || a.title;
    document.title = `${title} — Intercloud`;
    const desc = a.meta_description || a.excerpt || "";
    upsertMeta("name", "description", desc);
    upsertMeta("name", "keywords", (a.meta_keywords || a.tags || []).join(", "));
    // Open Graph
    upsertMeta("property", "og:title", title);
    upsertMeta("property", "og:description", desc);
    upsertMeta("property", "og:type", "article");
    upsertMeta("property", "og:image", a.og_image_url || a.cover_image_url || "");
    upsertMeta("property", "og:url", window.location.href);
    upsertMeta("property", "article:published_time", a.published_at || "");
    (a.tags || []).forEach((t) => upsertMeta("property", "article:tag", t));
    // Twitter
    upsertMeta("name", "twitter:card", a.cover_image_url ? "summary_large_image" : "summary");
    upsertMeta("name", "twitter:title", title);
    upsertMeta("name", "twitter:description", desc);
    upsertMeta("name", "twitter:image", a.og_image_url || a.cover_image_url || "");
    // Canonical
    upsertLink("canonical", window.location.origin + `/articles/${a.slug}`);
    // JSON-LD BlogPosting
    const existing = document.getElementById("article-jsonld");
    if (existing) existing.remove();
    const s = document.createElement("script");
    s.id = "article-jsonld";
    s.type = "application/ld+json";
    s.text = JSON.stringify({
      "@context": "https://schema.org",
      "@type": "BlogPosting",
      "headline": a.title,
      "description": desc,
      "image": [a.cover_image_url].filter(Boolean),
      "datePublished": a.published_at,
      "dateModified": a.updated_at,
      "author": { "@type": "Organization", "name": a.author_name || "PT Intercloud Digital Inovasi" },
      "publisher": {
        "@type": "Organization",
        "name": "PT Intercloud Digital Inovasi",
        "logo": { "@type": "ImageObject", "url": "https://customer-assets-lxgj4vgw.emergentagent.net/job_portal-straight-line/artifacts/40f397oz_logo_anang-02-1-1536x1536-1.png" },
      },
      "keywords": (a.meta_keywords || a.tags || []).join(", "),
      "mainEntityOfPage": window.location.href,
    });
    document.head.appendChild(s);

    // BreadcrumbList JSON-LD — helps Google surface breadcrumb rich results.
    const existingBc = document.getElementById("article-breadcrumb-jsonld");
    if (existingBc) existingBc.remove();
    const bc = document.createElement("script");
    bc.id = "article-breadcrumb-jsonld";
    bc.type = "application/ld+json";
    bc.text = JSON.stringify({
      "@context": "https://schema.org",
      "@type": "BreadcrumbList",
      "itemListElement": [
        { "@type": "ListItem", "position": 1, "name": "Home",     "item": window.location.origin + "/" },
        { "@type": "ListItem", "position": 2, "name": "Articles", "item": window.location.origin + "/articles" },
        { "@type": "ListItem", "position": 3, "name": a.title,     "item": window.location.origin + `/articles/${a.slug}` },
      ],
    });
    document.head.appendChild(bc);
    return () => {
      document.title = "Intercloud Digital Inovasi";
      const j = document.getElementById("article-jsonld");
      if (j) j.remove();
      const b = document.getElementById("article-breadcrumb-jsonld");
      if (b) b.remove();
    };
  }, [a]);
};

const formatDate = (iso) => {
  if (!iso) return "";
  try {
    return new Date(iso).toLocaleDateString("en-GB", { day: "numeric", month: "long", year: "numeric" });
  } catch { return ""; }
};

const embedFor = (url) => {
  const u = (url || "").trim();
  if (!u) return null;
  const yt = u.match(/(?:youtu\.be\/|youtube\.com\/(?:watch\?v=|embed\/))([\w-]{11})/);
  if (yt) return { type: "iframe", src: `https://www.youtube.com/embed/${yt[1]}` };
  const vm = u.match(/vimeo\.com\/(\d+)/);
  if (vm) return { type: "iframe", src: `https://player.vimeo.com/video/${vm[1]}` };
  return { type: "video", src: u };
};

const ArticleDetail = () => {
  const { slug } = useParams();
  const nav = useNavigate();
  const [article, setArticle] = useState(null);
  const [related, setRelated] = useState([]);
  const [notFound, setNotFound] = useState(false);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    setArticle(null); setRelated([]); setNotFound(false);
    axios.get(`${API}/public/articles/${slug}`)
      .then((r) => { setArticle(r.data.article); setRelated(r.data.related || []); })
      .catch((e) => { if (e?.response?.status === 404) setNotFound(true); });
  }, [slug]);

  useArticleSEO(article);

  useEffect(() => { window.scrollTo(0, 0); }, [slug]);

  const video = useMemo(() => embedFor(article?.video_url), [article]);

  const share = async () => {
    try {
      if (navigator.share) {
        await navigator.share({ title: article.title, text: article.excerpt, url: window.location.href });
      } else {
        await navigator.clipboard.writeText(window.location.href);
        setCopied(true); setTimeout(() => setCopied(false), 2000);
      }
    } catch {}
  };

  if (notFound) {
    return (
      <div className="min-h-screen bg-white">
        <Header />
        <main className="pt-32 pb-24 text-center max-w-xl mx-auto px-6">
          <div className="text-6xl font-extrabold text-[#0a2350]">404</div>
          <h1 className="mt-3 text-2xl font-extrabold text-[#0a2350]">Article not found</h1>
          <p className="mt-2 text-slate-500">This article may have been unpublished or the link is incorrect.</p>
          <Link to="/articles" className="mt-6 inline-flex items-center gap-2 px-5 h-11 rounded-full bg-[#0a2350] text-white text-sm font-bold hover:bg-[#f5b120] hover:text-[#0a2350] transition-colors">
            <ArrowLeft className="h-4 w-4" /> Browse all articles
          </Link>
        </main>
        <Footer />
      </div>
    );
  }

  if (!article) return <div className="min-h-screen"><Header /><div className="pt-32 text-center text-slate-500">Loading article…</div></div>;

  return (
    <div className="min-h-screen bg-white">
      <Header />
      <main className="pt-24 pb-24">
        {/* Hero */}
        <header className="max-w-4xl mx-auto px-6 pt-8 md:pt-14">
          <Link to="/articles" className="inline-flex items-center gap-2 text-xs font-bold uppercase tracking-widest text-slate-500 hover:text-[#0a2350]" data-testid="back-to-articles">
            <ArrowLeft className="h-3 w-3" /> All articles
          </Link>
          <div className="mt-6 text-[11px] font-bold uppercase tracking-widest text-[#f5b120]">{article.category || "Article"}</div>
          <h1 className="mt-2 text-3xl sm:text-4xl lg:text-5xl font-extrabold text-[#0a2350] leading-tight" data-testid="article-title">{article.title}</h1>
          {article.excerpt && <p className="mt-4 text-lg text-slate-600 leading-relaxed" data-testid="article-excerpt">{article.excerpt}</p>}
          <div className="mt-6 flex flex-wrap items-center gap-4 text-xs text-slate-500 border-y border-slate-200 py-4">
            <span className="inline-flex items-center gap-1.5"><User className="h-3.5 w-3.5" /> {article.author_name || "Intercloud"}</span>
            <span className="inline-flex items-center gap-1.5"><Calendar className="h-3.5 w-3.5" /> {formatDate(article.published_at)}</span>
            <span className="inline-flex items-center gap-1.5"><Eye className="h-3.5 w-3.5" /> {article.view_count} reads</span>
            <button onClick={share} className="ml-auto inline-flex items-center gap-1.5 px-3 h-8 rounded-full border border-slate-200 hover:border-[#f5b120] hover:text-[#0a2350] transition-colors" data-testid="share-btn">
              <Share2 className="h-3.5 w-3.5" /> {copied ? "Link copied" : "Share"}
            </button>
          </div>
        </header>

        {/* Cover */}
        {article.cover_image_url && (
          <div className="max-w-5xl mx-auto px-6 mt-10">
            <div className="rounded-3xl overflow-hidden bg-slate-100 aspect-video">
              <img src={article.cover_image_url} alt={article.cover_image_alt || article.title} className="w-full h-full object-cover" data-testid="article-cover" />
            </div>
          </div>
        )}

        {/* Video */}
        {video && (
          <div className="max-w-5xl mx-auto px-6 mt-8">
            <div className="rounded-3xl overflow-hidden bg-black aspect-video">
              {video.type === "iframe" ? (
                <iframe src={video.src} title="video" allow="autoplay; fullscreen; picture-in-picture" allowFullScreen className="w-full h-full" data-testid="article-video" />
              ) : (
                <video controls src={video.src} className="w-full h-full" data-testid="article-video" />
              )}
            </div>
          </div>
        )}

        {/* Body */}
        <article className="max-w-3xl mx-auto px-6 mt-12">
          <div
            className="prose prose-slate max-w-none prose-headings:text-[#0a2350] prose-headings:font-extrabold prose-a:text-[#0a2350] prose-a:font-semibold hover:prose-a:text-[#f5b120] prose-strong:text-[#0a2350] prose-img:rounded-xl prose-blockquote:border-l-4 prose-blockquote:border-[#f5b120] prose-blockquote:pl-4 prose-blockquote:italic prose-h2:mt-10 prose-h2:text-2xl prose-h3:text-xl prose-p:leading-relaxed prose-p:text-slate-700 prose-li:text-slate-700"
            dangerouslySetInnerHTML={{ __html: article.body_html }}
            data-testid="article-body"
          />
        </article>

        {/* Tags */}
        {(article.tags || []).length > 0 && (
          <div className="max-w-3xl mx-auto px-6 mt-12">
            <div className="text-[11px] font-bold uppercase tracking-widest text-slate-500 mb-3">Tagged</div>
            <div className="flex flex-wrap gap-2">
              {article.tags.map((t) => (
                <Link key={t} to={`/articles?tag=${encodeURIComponent(t)}`} className="text-xs px-3 h-8 inline-flex items-center gap-1 rounded-full bg-slate-100 border border-slate-200 text-slate-700 hover:border-[#f5b120] hover:text-[#0a2350] transition-colors" data-testid={`article-tag-${t}`}>
                  <Tag className="h-3 w-3" /> {t}
                </Link>
              ))}
            </div>
          </div>
        )}

        {/* Related */}
        {related.length > 0 && (
          <section className="max-w-6xl mx-auto px-6 mt-16 border-t border-slate-200 pt-12" data-testid="related-section">
            <div className="text-[11px] font-bold uppercase tracking-widest text-[#f5b120]">Read next</div>
            <h2 className="mt-2 text-2xl font-extrabold text-[#0a2350]">You might also like</h2>
            <div className="mt-6 grid sm:grid-cols-2 lg:grid-cols-3 gap-6">
              {related.map((a) => (
                <Link key={a.id} to={`/articles/${a.slug}`} className="group block rounded-2xl overflow-hidden bg-white border border-slate-200 hover:border-[#f5b120] transition-colors">
                  <div className="aspect-video overflow-hidden bg-slate-100">
                    {a.cover_image_url ? <img src={a.cover_image_url} alt={a.cover_image_alt || a.title} className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-500" loading="lazy" /> : <div className="w-full h-full bg-gradient-to-br from-[#0a2350] to-[#1a3a70]" />}
                  </div>
                  <div className="p-5">
                    <div className="text-[10px] font-bold uppercase tracking-widest text-[#f5b120]">{a.category || "Article"}</div>
                    <h3 className="mt-1 font-extrabold text-[#0a2350] leading-snug group-hover:text-[#f5b120] transition-colors line-clamp-2">{a.title}</h3>
                    <div className="mt-3 inline-flex items-center gap-1 text-xs font-bold text-[#0a2350] group-hover:text-[#f5b120]">Read <ArrowRight className="h-3 w-3" /></div>
                  </div>
                </Link>
              ))}
            </div>
          </section>
        )}
      </main>
      <Footer />
    </div>
  );
};

export default ArticleDetail;
