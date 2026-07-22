import React from "react";
import { Wallet, HeadphonesIcon, Network, Gauge } from "lucide-react";
import { features } from "../mock/data";
import { useLang, pick } from "../i18n/LanguageContext";

const iconMap = {
  pricing: Wallet,
  support: HeadphonesIcon,
  network: Network,
  sla: Gauge,
};

const Features = () => {
  const { lang, t } = useLang();
  return (
    <section id="why" className="relative py-24 bg-white" data-testid="features-section">
      <div className="max-w-7xl mx-auto px-5 lg:px-8">
        <div className="max-w-2xl">
          <div className="text-[#f5b120] text-xs font-bold tracking-[0.2em] uppercase mb-3">
            {t("feat.eyebrow")}
          </div>
          <h2 className="text-3xl md:text-4xl font-extrabold text-[#0a2350] title-underline">
            {t("feat.title")}
          </h2>
          <p className="mt-6 text-slate-600 text-base leading-relaxed">
            {t("feat.subtitle")}
          </p>
        </div>

        <div className="mt-14 grid sm:grid-cols-2 lg:grid-cols-4 gap-5">
          {features.map((f) => {
            const Icon = iconMap[f.icon];
            return (
              <div
                key={f.icon}
                className="card-lift group relative rounded-2xl border border-slate-200 bg-white p-7 hover:border-[#f5b120]"
              >
                <div className="h-14 w-14 rounded-xl bg-[#0a2350] group-hover:bg-[#f5b120] transition-colors flex items-center justify-center mb-5">
                  <Icon className="h-7 w-7 text-[#f5b120] group-hover:text-[#0a2350] transition-colors" strokeWidth={1.8} />
                </div>
                <h3 className="text-lg font-bold text-[#0a2350]">{pick(f.title, lang)}</h3>
                <p className="mt-2 text-sm text-slate-600 leading-relaxed">{pick(f.desc, lang)}</p>
                <div className="absolute top-6 right-6 h-1 w-8 bg-slate-100 group-hover:bg-[#f5b120] transition-colors rounded-full" />
              </div>
            );
          })}
        </div>
      </div>
    </section>
  );
};

export default Features;
