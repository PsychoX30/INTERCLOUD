import React from "react";
import { Link } from "react-router-dom";
import { Home, ArrowLeft } from "lucide-react";
import Header from "../components/Header";
import Footer from "../components/Footer";
import { useLang } from "../i18n/LanguageContext";

const COPY = {
  id: {
    tag: "404 — Halaman tidak ditemukan",
    title: "Kami tidak menemukan halaman yang Anda cari.",
    body: "Halaman ini mungkin sudah dipindahkan, dihapus, atau URL yang Anda ketik tidak tepat. Silakan kembali ke halaman utama atau jelajahi artikel terbaru kami.",
    ctaHome: "Kembali ke beranda",
    ctaBack: "Halaman sebelumnya",
    ctaArticles: "Lihat semua artikel",
  },
  en: {
    tag: "404 — Page not found",
    title: "We couldn't find the page you were looking for.",
    body: "This page may have been moved, deleted, or the URL you entered is incorrect. Please head back to the homepage or explore our latest articles.",
    ctaHome: "Back to home",
    ctaBack: "Previous page",
    ctaArticles: "Browse articles",
  },
};

/**
 * Real 404 page — resolves UAT finding C3: previously ANY unknown route
 * returned 200 with a blank SPA shell. React Router now catches unmatched
 * routes here so users (and crawlers) see a proper "page not found" UI.
 *
 * We can't send a real HTTP 404 status from the SPA (that would require
 * SSR), but the `<meta name="robots" content="noindex">` + `<link rel=
 * "canonical" href="/">` tags stop search engines from indexing the URL,
 * and the visible messaging makes the state unambiguous to users.
 */
const NotFound = () => {
  const { lang } = useLang();
  const t = COPY[lang] || COPY.id;

  React.useEffect(() => {
    // Tell crawlers NOT to index random 404 URLs — restores SEO hygiene.
    // Landing/other pages set a default <meta name="robots" content="index,
    // follow"> that we must OVERRIDE here (not just append), otherwise the
    // first meta wins.
    const existing = document.head.querySelector('meta[name="robots"]');
    const prev = existing?.getAttribute("content") || null;
    let ownMeta = existing;
    if (!ownMeta) {
      ownMeta = document.createElement("meta");
      ownMeta.setAttribute("name", "robots");
      document.head.appendChild(ownMeta);
    }
    ownMeta.setAttribute("content", "noindex, nofollow");

    const prevTitle = document.title;
    document.title = `${t.tag} — Intercloud`;
    return () => {
      // Restore whatever robots directive was there before we mounted.
      if (prev === null) {
        ownMeta.remove();
      } else {
        ownMeta.setAttribute("content", prev);
      }
      document.title = prevTitle;
    };
  }, [t.tag]);

  return (
    <div className="bg-white text-[#0a2350] min-h-screen flex flex-col">
      <Header />
      <main className="flex-1 flex items-center justify-center px-5 py-20" data-testid="not-found-page">
        <div className="max-w-2xl w-full text-center">
          <div className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full bg-[#f5b120]/15 text-[#0a2350] text-xs font-bold uppercase tracking-widest mb-6">
            {t.tag}
          </div>
          <div className="text-[128px] md:text-[180px] font-black leading-none text-[#0a2350] mb-4 select-none" aria-hidden>
            404
          </div>
          <h1 className="text-2xl md:text-3xl font-extrabold mb-4">
            {t.title}
          </h1>
          <p className="text-slate-600 text-base md:text-lg mb-10 max-w-xl mx-auto">
            {t.body}
          </p>
          <div className="flex flex-wrap items-center justify-center gap-3">
            <Link
              to="/"
              className="inline-flex items-center gap-2 rounded-full bg-[#f5b120] hover:bg-[#ffc94a] text-[#0a2350] px-6 py-3 text-sm font-bold transition-colors"
              data-testid="not-found-home-btn"
            >
              <Home className="h-4 w-4" /> {t.ctaHome}
            </Link>
            <button
              type="button"
              onClick={() => window.history.back()}
              className="inline-flex items-center gap-2 rounded-full border border-[#0a2350]/20 hover:border-[#0a2350] text-[#0a2350] px-6 py-3 text-sm font-bold transition-colors"
              data-testid="not-found-back-btn"
            >
              <ArrowLeft className="h-4 w-4" /> {t.ctaBack}
            </button>
            <Link
              to="/articles"
              className="text-[#0a2350] hover:text-[#f5b120] text-sm font-semibold underline underline-offset-4 px-2 py-3"
              data-testid="not-found-articles-link"
            >
              {t.ctaArticles} →
            </Link>
          </div>
        </div>
      </main>
      <Footer />
    </div>
  );
};

export default NotFound;
