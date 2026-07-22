import React from "react";
import { CheckCircle2, ArrowRight, MessageCircle } from "lucide-react";
import { Globe2, Boxes, HardDrive } from "lucide-react";
import { buildWaLink } from "../mock/data";
import { useLang } from "../i18n/LanguageContext";

const DecisionGuide = () => {
  const { lang, t } = useLang();

  const guides = [
    {
      step: "01",
      icon: Globe2,
      title: t("dg.hosting.title"),
      subtitle: t("dg.hosting.sub"),
      body: t("dg.hosting.body"),
      tags: lang === "en" ? ["Practical", "Easy to manage"] : ["Praktis", "Mudah dikelola"],
      id: "hosting",
    },
    {
      step: "02",
      icon: Boxes,
      title: t("dg.vps.title"),
      subtitle: t("dg.vps.sub"),
      body: t("dg.vps.body"),
      tags: lang === "en" ? ["Flexible", "Scalable"] : ["Fleksibel", "Skalabel"],
      id: "vps",
      featured: true,
    },
    {
      step: "03",
      icon: HardDrive,
      title: t("dg.ded.title"),
      subtitle: t("dg.ded.sub"),
      body: t("dg.ded.body"),
      tags: lang === "en" ? ["High performance", "Full control"] : ["Performa tinggi", "Kontrol penuh"],
      id: "dedicated",
    },
  ];

  const waMsg = lang === "en"
    ? "Hello Intercloud, I need help choosing the right service (Hosting / VPS / Dedicated Server) for my business."
    : "Halo Intercloud, saya butuh konsultasi untuk memilih layanan yang paling sesuai (Hosting / VPS / Dedicated Server) untuk kebutuhan bisnis saya.";

  return (
    <section id="decision-guide" className="relative py-24 bg-white" data-testid="decision-guide-section">
      <div className="max-w-7xl mx-auto px-5 lg:px-8">
        <div className="text-center max-w-3xl mx-auto">
          <div className="text-[#f5b120] text-xs font-bold tracking-[0.2em] uppercase mb-3">
            {t("dg.eyebrow")}
          </div>
          <h2 className="text-3xl md:text-4xl font-extrabold text-[#0a2350]">
            {t("dg.title_a")} <span className="text-[#f5b120]">{t("dg.title_b")}</span>
          </h2>
          <div className="mx-auto mt-4 h-1 w-16 bg-[#f5b120] rounded-full" />
          <p className="mt-5 text-slate-600 leading-relaxed">{t("dg.subtitle")}</p>
        </div>

        <div className="mt-14 grid md:grid-cols-3 gap-6">
          {guides.map((g) => {
            const Icon = g.icon;
            return (
              <div
                key={g.step}
                data-testid={`guide-card-${g.id}`}
                className={`card-lift relative rounded-3xl p-8 border transition-colors ${
                  g.featured
                    ? "bg-[#0a2350] text-white border-[#0a2350] shadow-xl"
                    : "bg-white text-[#0a2350] border-slate-200 hover:border-[#f5b120]"
                }`}
              >
                <div className="flex items-start justify-between mb-6">
                  <div className={`h-14 w-14 rounded-xl flex items-center justify-center ${
                    g.featured ? "bg-[#f5b120]" : "bg-[#0a2350]"
                  }`}>
                    <Icon
                      className={`h-7 w-7 ${g.featured ? "text-[#0a2350]" : "text-[#f5b120]"}`}
                      strokeWidth={1.7}
                    />
                  </div>
                  <div className={`h-10 w-10 rounded-full border-2 flex items-center justify-center font-extrabold text-sm ${
                    g.featured ? "border-[#f5b120] text-[#f5b120]" : "border-[#f5b120]/50 text-[#f5b120]"
                  }`}>
                    {g.step}
                  </div>
                </div>
                <h3 className={`text-xl font-extrabold ${g.featured ? "text-white" : "text-[#0a2350]"}`}>
                  {g.title}
                </h3>
                <div className="text-sm font-semibold mt-1 text-[#f5b120]">{g.subtitle}</div>
                <p className={`mt-4 text-sm leading-relaxed ${g.featured ? "text-white/85" : "text-slate-600"}`}>
                  {g.body}
                </p>

                <div className="mt-5 flex flex-wrap gap-2">
                  {g.tags.map((tg) => (
                    <span
                      key={tg}
                      className={`inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-[11px] font-semibold ${
                        g.featured
                          ? "bg-white/10 text-white border border-white/20"
                          : "bg-[#f5b120]/10 text-[#0a2350] border border-[#f5b120]/40"
                      }`}
                    >
                      <CheckCircle2 className="h-3 w-3 text-[#f5b120]" />
                      {tg}
                    </span>
                  ))}
                </div>

                <a
                  href="#services"
                  data-testid={`guide-cta-${g.id}`}
                  className={`mt-7 inline-flex items-center gap-2 text-sm font-semibold ${
                    g.featured ? "text-[#f5b120] hover:text-[#ffc94a]" : "text-[#0a2350] hover:text-[#f5b120]"
                  }`}
                >
                  {t("cta.viewDetails")} <ArrowRight className="h-4 w-4" />
                </a>
              </div>
            );
          })}
        </div>

        <div className="mt-10 rounded-3xl bg-[#0a2350] text-white p-6 md:p-8 flex flex-col md:flex-row items-start md:items-center gap-6" data-testid="decision-guide-cta">
          <div className="h-14 w-14 rounded-2xl bg-[#f5b120] flex items-center justify-center flex-shrink-0">
            <MessageCircle className="h-7 w-7 text-[#0a2350]" strokeWidth={2} />
          </div>
          <div className="flex-1">
            <h4 className="text-lg md:text-xl font-extrabold text-white">{t("dg.help.title")}</h4>
            <p className="text-white/80 text-sm mt-1">{t("dg.help.body")}</p>
          </div>
          <a
            href={buildWaLink(waMsg)}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-2 rounded-full bg-[#f5b120] hover:bg-[#ffc94a] text-[#0a2350] px-6 py-3 text-sm font-semibold transition-colors flex-shrink-0"
          >
            {t("cta.contactUs")} <ArrowRight className="h-4 w-4" />
          </a>
        </div>
      </div>
    </section>
  );
};

export default DecisionGuide;
