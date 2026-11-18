import React, { useEffect, useMemo } from "react";
import Header from "../components/Header";
import Hero from "../components/Hero";
import Features from "../components/Features";
import Infrastructure from "../components/Infrastructure";
import Services from "../components/Services";
import DecisionGuide from "../components/DecisionGuide";
import Pricing from "../components/Pricing";
import PoP from "../components/PoP";
import Partners from "../components/Partners";
import FAQ from "../components/FAQ";
import LeadForm from "../components/LeadForm";
import Testimonials from "../components/Testimonials";
import CTA from "../components/CTA";
import Footer from "../components/Footer";
import { MessageCircle } from "lucide-react";
import { WHATSAPP_LINK_ID, WHATSAPP_LINK_EN } from "../mock/data";
import { useLang } from "../i18n/LanguageContext";
import DefaultSeo from "../components/DefaultSeo";

const CANONICAL = "https://intercloud-digital.com/";
const BREADCRUMB_ID = "landing-breadcrumb-jsonld";
const WEBSITE_ID    = "landing-website-jsonld";

const upsertLink = (rel, href) => {
  let el = document.head.querySelector(`link[rel="${rel}"]`);
  if (!el) {
    el = document.createElement("link");
    el.setAttribute("rel", rel);
    document.head.appendChild(el);
  }
  el.setAttribute("href", href);
};

const upsertScript = (id, obj) => {
  const existing = document.getElementById(id);
  if (existing) existing.remove();
  const s = document.createElement("script");
  s.id = id;
  s.type = "application/ld+json";
  s.text = JSON.stringify(obj);
  document.head.appendChild(s);
};

const useLandingSEO = () => {
  useEffect(() => {
    upsertLink("canonical", CANONICAL);
    upsertScript(BREADCRUMB_ID, {
      "@context": "https://schema.org",
      "@type": "BreadcrumbList",
      "itemListElement": [
        { "@type": "ListItem", "position": 1, "name": "Home", "item": CANONICAL },
      ],
    });
    upsertScript(WEBSITE_ID, {
      "@context": "https://schema.org",
      "@type": "WebSite",
      "name": "PT. Intercloud Digital Inovasi",
      "url": CANONICAL,
      "potentialAction": {
        "@type": "SearchAction",
        "target": CANONICAL + "articles?q={search_term_string}",
        "query-input": "required name=search_term_string",
      },
    });
    return () => {
      document.getElementById(BREADCRUMB_ID)?.remove();
      document.getElementById(WEBSITE_ID)?.remove();
    };
  }, []);
};

const FloatingWA = () => {
  const { lang } = useLang();
  const waLink = lang === "en" ? WHATSAPP_LINK_EN : WHATSAPP_LINK_ID;
  return (
    <a
      href={waLink}
      target="_blank"
      rel="noreferrer"
      aria-label="Chat WhatsApp"
      data-testid="floating-whatsapp-btn"
      className="fixed bottom-6 right-6 z-50 h-14 w-14 rounded-full bg-[#25d366] text-white flex items-center justify-center shadow-xl hover:bg-[#20bd5a] transition-colors wa-pulse"
    >
      <MessageCircle className="h-6 w-6" />
    </a>
  );
};

// Section key -> component. The keys match `data-cms-section` and are the same
// keys the backend validates against LANDING_SECTIONS, so a layout coming from
// the CMS can only ever name a section that has a component here.
const SECTION_COMPONENTS = {
  hero: Hero,
  features: Features,
  infra: Infrastructure,
  services: Services,
  guide: DecisionGuide,
  pricing: Pricing,
  pop: PoP,
  partners: Partners,
  testimonials: Testimonials,
  faqsec: FAQ,
  leadform: LeadForm,
  cta: CTA,
};

// Shipped order, used when the CMS has no layout (first paint before the fetch
// resolves, backend unreachable, or a document that predates this feature).
// Falls back to what the page looked like before reordering existed, never to
// an empty page.
const DEFAULT_ORDER = [
  "hero", "features", "infra", "services", "guide", "pricing",
  "pop", "partners", "testimonials", "faqsec", "leadform", "cta",
];

const Landing = () => {
  useLandingSEO();
  const { cmsLayout } = useLang();

  // navbar and footer are the page frame: they render outside <main> and are
  // never reordered or hidden, matching the pinning the backend enforces.
  const middle = useMemo(() => {
    const rows = Array.isArray(cmsLayout) && cmsLayout.length ? cmsLayout : null;
    if (!rows) return DEFAULT_ORDER;
    // Two different things look alike here and must not be confused:
    //   - a key MISSING from the layout  -> render it (old CMS document)
    //   - a key PRESENT but visible:false -> do not render it (deliberate)
    // `declared` tracks the first case, which is why it is filled before the
    // visibility test and not after.
    const declared = new Set();
    const ordered = [];
    for (const row of rows) {
      const key = row && row.key;
      if (!key || key === "navbar" || key === "footer") continue;
      if (!SECTION_COMPONENTS[key] || declared.has(key)) continue;
      declared.add(key);
      if (row.visible === false) continue;
      ordered.push(key);
    }
    for (const key of DEFAULT_ORDER) {
      if (!declared.has(key)) ordered.push(key);
    }
    return ordered;
  }, [cmsLayout]);

  return (
    <div className="bg-white text-[#0a2350]">
      <DefaultSeo />
      <div data-cms-section="navbar" id="navbar"><Header /></div>
      <main>
        {middle.map((key) => {
          const Section = SECTION_COMPONENTS[key];
          return (
            <div key={key} data-cms-section={key} id={key}>
              <Section />
            </div>
          );
        })}
      </main>
      <div data-cms-section="footer" id="footer"><Footer /></div>
      <FloatingWA />
    </div>
  );
};

export default Landing;
