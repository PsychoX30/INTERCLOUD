import React, { useState } from "react";
import { partners } from "../mock/data";
import { useLang } from "../i18n/LanguageContext";

// Google's s2 endpoint reliably returns a PNG favicon for any domain at the
// requested size — good enough to represent small Indonesian ISPs & startups
// that don't publish a hosted vector logo.
const faviconUrl = (domain) =>
  `https://www.google.com/s2/favicons?domain=${domain}&sz=128`;

const getInitials = (name) =>
  name
    .split(" ")
    .filter(Boolean)
    .slice(0, 2)
    .map((w) => w[0])
    .join("")
    .toUpperCase();

const PartnerLogo = ({ p }) => {
  const [broken, setBroken] = useState(false);
  const hasLogo = !!p.domain && !broken;

  return (
    <div
      data-testid={`partner-${p.name.toLowerCase().replace(/\s+/g, "-")}`}
      title={p.name}
      className="group flex items-center gap-3 h-20 min-w-[200px] px-5 rounded-2xl bg-white border border-slate-200 hover:border-[#f5b120] hover:shadow-lg hover:-translate-y-0.5 transition-all"
    >
      <div className="h-11 w-11 flex-shrink-0 rounded-lg bg-slate-50 border border-slate-100 group-hover:border-[#f5b120]/40 flex items-center justify-center overflow-hidden">
        {hasLogo ? (
          <img
            src={faviconUrl(p.domain)}
            alt={`${p.name} logo`}
            className="h-8 w-8 object-contain"
            loading="lazy"
            onError={() => setBroken(true)}
          />
        ) : (
          <span className="text-[11px] font-extrabold tracking-tight text-[#0a2350]">
            {getInitials(p.name)}
          </span>
        )}
      </div>
      <div className="text-sm font-extrabold text-[#0a2350] leading-tight truncate">
        {p.name}
      </div>
    </div>
  );
};

const Partners = () => {
  const { t } = useLang();
  const loop = [...partners, ...partners];

  return (
    <section
      id="partners"
      className="relative py-24 bg-slate-50 overflow-hidden"
      data-testid="partners-section"
    >
      <div className="max-w-7xl mx-auto px-5 lg:px-8">
        <div className="text-center max-w-2xl mx-auto">
          <div className="text-[#f5b120] text-xs font-bold tracking-[0.2em] uppercase mb-3">
            {t("pt.eyebrow")}
          </div>
          <h2 className="text-3xl md:text-4xl font-extrabold text-[#0a2350]">
            {t("pt.title")}
          </h2>
          <div className="mx-auto mt-4 h-1 w-16 bg-[#f5b120] rounded-full" />
          <p className="mt-5 text-slate-600">{t("pt.subtitle")}</p>
        </div>
      </div>

      <div className="mt-14 relative">
        <div className="absolute inset-y-0 left-0 w-24 bg-gradient-to-r from-slate-50 to-transparent z-10 pointer-events-none" />
        <div className="absolute inset-y-0 right-0 w-24 bg-gradient-to-l from-slate-50 to-transparent z-10 pointer-events-none" />
        <div className="marquee-track flex gap-4" data-testid="partners-marquee">
          {loop.map((p, i) => (
            <PartnerLogo key={`${p.name}-${i}`} p={p} />
          ))}
        </div>
      </div>
    </section>
  );
};

export default Partners;
