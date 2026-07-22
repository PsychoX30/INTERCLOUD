import React from "react";
import { MapPin, ArrowRight, Building2, Server, Layers, Waypoints } from "lucide-react";
import { buildWaLink } from "../mock/data";
import { useLang } from "../i18n/LanguageContext";

const PoP = () => {
  const { t } = useLang();

  const items = [
    { id: "metta", icon: Server,   nameKey: "pop.item1.name", descKey: "pop.item1.desc", floor: "5F" },
    { id: "omni",  icon: Layers,   nameKey: "pop.item2.name", descKey: "pop.item2.desc", floor: "2F" },
    { id: "tifa",  icon: Building2, nameKey: "pop.item3.name", descKey: "pop.item3.desc", floor: "—"  },
    { id: "apjii", icon: Waypoints, nameKey: "pop.item4.name", descKey: "pop.item4.desc", floor: "1F" },
  ];

  return (
    <section
      id="pop"
      className="relative py-24 bg-[#0a2350] text-white overflow-hidden"
      data-testid="pop-section"
    >
      {/* Subtle overlays for depth */}
      <div className="absolute inset-0 grid-overlay opacity-25" />
      <div className="absolute -top-20 -left-16 h-80 w-80 rounded-full bg-[#f5b120]/10 blur-3xl" />
      <div className="absolute -bottom-24 -right-16 h-80 w-80 rounded-full bg-[#f5b120]/8 blur-3xl" />

      <div className="relative max-w-7xl mx-auto px-5 lg:px-8">
        <div className="text-center max-w-2xl mx-auto">
          <div className="text-[#f5b120] text-xs font-bold tracking-[0.2em] uppercase mb-3">
            {t("pop.eyebrow")}
          </div>
          <h2 className="text-3xl md:text-4xl font-extrabold text-white">
            {t("pop.title")}
          </h2>
          <div className="mx-auto mt-4 h-1 w-16 bg-[#f5b120] rounded-full" />
          <p className="mt-5 text-white/80 leading-relaxed">{t("pop.subtitle")}</p>
        </div>

        <div className="mt-14 grid sm:grid-cols-2 lg:grid-cols-4 gap-5">
          {items.map((p, idx) => {
            const Icon = p.icon;
            return (
              <div
                key={p.id}
                data-testid={`pop-card-${p.id}`}
                className="card-lift group relative rounded-2xl p-6 bg-white/5 border border-white/10 hover:border-[#f5b120] hover:bg-white/[0.07] transition-colors overflow-hidden"
              >
                {/* Corner badge */}
                <div className="absolute top-4 right-4 h-9 min-w-[36px] px-2 rounded-full border border-[#f5b120]/50 text-[#f5b120] text-[11px] font-extrabold flex items-center justify-center">
                  {String(idx + 1).padStart(2, "0")}
                </div>

                <div className="h-12 w-12 rounded-xl bg-[#f5b120] flex items-center justify-center mb-5">
                  <Icon className="h-6 w-6 text-[#0a2350]" strokeWidth={1.8} />
                </div>

                <div className="text-[10px] font-bold tracking-widest uppercase text-[#f5b120]/80 mb-1">
                  {t("pop.tagLabel")} · {p.floor}
                </div>
                <h3 className="text-lg font-extrabold text-white leading-tight">
                  {t(p.nameKey)}
                </h3>
                <p className="mt-3 text-sm text-white/75 leading-relaxed">
                  {t(p.descKey)}
                </p>

                <div className="mt-5 pt-4 border-t border-dashed border-white/10 flex items-center gap-2 text-[11px] text-white/60">
                  <MapPin className="h-3.5 w-3.5 text-[#f5b120]" />
                  Jakarta, Indonesia
                </div>
              </div>
            );
          })}
        </div>

        {/* CTA card */}
        <div
          className="mt-10 rounded-3xl bg-white/[0.06] border border-white/10 p-6 md:p-8 flex flex-col md:flex-row items-start md:items-center gap-6"
          data-testid="pop-cta"
        >
          <div className="h-14 w-14 rounded-2xl bg-[#f5b120] flex items-center justify-center flex-shrink-0">
            <MapPin className="h-7 w-7 text-[#0a2350]" strokeWidth={2} />
          </div>
          <div className="flex-1">
            <h4 className="text-lg md:text-xl font-extrabold text-white">{t("pop.cta.title")}</h4>
            <p className="text-white/80 text-sm mt-1">{t("pop.cta.body")}</p>
          </div>
          <a
            href={buildWaLink(t("wa.prefilled.pop"))}
            target="_blank"
            rel="noreferrer"
            data-testid="pop-cta-wa"
            className="inline-flex items-center gap-2 rounded-full bg-[#f5b120] hover:bg-[#ffc94a] text-[#0a2350] px-6 py-3 text-sm font-semibold transition-colors flex-shrink-0"
          >
            {t("cta.contactUs")} <ArrowRight className="h-4 w-4" />
          </a>
        </div>
      </div>
    </section>
  );
};

export default PoP;
