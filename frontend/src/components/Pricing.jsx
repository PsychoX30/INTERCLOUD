import React from "react";
import { Check, Sparkles, MessageCircle, ArrowRight } from "lucide-react";
import {
  dedicatedTiers,
  colocationTiers,
  interconnectTiers,
  buildWaLink,
} from "../mock/data";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "./ui/tabs";
import { useLang, pick } from "../i18n/LanguageContext";

const PlanCard = ({ p, categoryName }) => {
  const { lang, t } = useLang();
  const name = pick(p.name, lang);
  const setup = pick(p.setup, lang);
  const items = pick(p.items, lang) || [];
  const note = pick(p.note, lang);
  const subtle = pick(p.subtle, lang);

  const waMsg = lang === "en"
    ? `Hello Intercloud, I'd like to order the *${name}* plan (${categoryName}). Please share more info.`
    : `Halo Intercloud, saya ingin memesan paket *${name}* (${categoryName}). Mohon informasi lebih lanjut.`;

  return (
    <div
      data-testid={`pricing-card-${p.id}`}
      className={`relative rounded-3xl p-7 border card-lift flex flex-col ${
        p.featured
          ? "bg-[#0a2350] text-white border-[#0a2350] shadow-xl"
          : "bg-white text-[#0a2350] border-slate-200 hover:border-[#f5b120]"
      }`}
    >
      {p.featured && (
        <div className="absolute -top-3 left-1/2 -translate-x-1/2 inline-flex items-center gap-1 bg-[#f5b120] text-[#0a2350] text-[11px] font-extrabold px-3 py-1 rounded-full">
          <Sparkles className="h-3 w-3" /> {t("pr.mostPopular")}
        </div>
      )}
      <h3 className={`text-lg font-extrabold ${p.featured ? "text-white" : "text-[#0a2350]"}`}>
        {name}
      </h3>
      <div className="mt-3 flex items-baseline gap-1 flex-wrap">
        <span className={`text-2xl md:text-3xl font-extrabold ${p.featured ? "text-[#f5b120]" : "text-[#0a2350]"}`}>
          {p.price}
        </span>
        <span className={`text-sm ${p.featured ? "text-white/70" : "text-slate-500"}`}>
          {t("cta.perMonth")}
        </span>
      </div>
      <div className={`text-[11px] mt-1 ${p.featured ? "text-white/70" : "text-slate-500"}`}>
        + {setup}
      </div>

      <ul className="mt-5 space-y-2.5 flex-1">
        {items.map((it) => (
          <li key={it} className="flex items-start gap-2.5 text-[13px] leading-snug">
            <Check className="h-4 w-4 flex-shrink-0 mt-0.5 text-[#f5b120]" />
            <span className={p.featured ? "text-white/90" : "text-slate-700"}>{it}</span>
          </li>
        ))}
      </ul>

      {note && (
        <div className={`mt-4 text-[11px] font-semibold ${p.featured ? "text-[#f5b120]" : "text-[#0a2350]/70"}`}>
          *** {note}
        </div>
      )}
      {subtle && (
        <div className={`mt-4 text-[11px] italic ${p.featured ? "text-white/70" : "text-slate-500"}`}>
          {subtle}
        </div>
      )}

      <a
        href={buildWaLink(waMsg)}
        target="_blank"
        rel="noreferrer"
        data-testid={`pricing-cta-${p.id}`}
        className={`mt-6 inline-flex w-full items-center justify-center gap-2 rounded-full px-5 py-2.5 text-sm font-semibold transition-colors ${
          p.featured
            ? "bg-[#f5b120] hover:bg-[#ffc94a] text-[#0a2350]"
            : "bg-[#0a2350] hover:bg-[#143a80] text-white"
        }`}
      >
        <MessageCircle className="h-4 w-4" /> {t("cta.orderWhatsApp")}
      </a>

      <div className={`mt-3 text-[10px] ${p.featured ? "text-white/60" : "text-slate-400"}`}>
        {t("pr.tnc")}
      </div>
    </div>
  );
};

const CategoryGrid = ({ tiers, categoryName }) => (
  <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-5">
    {tiers.map((p) => (
      <PlanCard key={p.id} p={p} categoryName={categoryName} />
    ))}
  </div>
);

const TAB_STYLES =
  "data-[state=active]:bg-[#0a2350] data-[state=active]:text-white " +
  "data-[state=inactive]:bg-white data-[state=inactive]:text-[#0a2350] " +
  "rounded-full px-5 py-2.5 text-sm font-semibold border border-slate-200 " +
  "hover:border-[#f5b120] transition-colors h-auto shadow-none";

const Pricing = () => {
  const { lang, t } = useLang();
  const customQuoteMsg = lang === "en"
    ? "Hello Intercloud, I'd like a custom quotation for enterprise IT infrastructure. Please share more information."
    : "Halo Intercloud, saya ingin custom quotation untuk kebutuhan infrastruktur IT enterprise. Mohon informasi lebih lanjut.";

  return (
    <section id="pricing" className="relative py-24 bg-slate-50" data-testid="pricing-section">
      <div className="max-w-7xl mx-auto px-5 lg:px-8">
        <div className="text-center max-w-2xl mx-auto">
          <div className="text-[#f5b120] text-xs font-bold tracking-[0.2em] uppercase mb-3">
            {t("pr.eyebrow")}
          </div>
          <h2 className="text-3xl md:text-4xl font-extrabold text-[#0a2350]">
            {t("pr.title")}
          </h2>
          <div className="mx-auto mt-4 h-1 w-16 bg-[#f5b120] rounded-full" />
          <p className="mt-5 text-slate-600 leading-relaxed">{t("pr.subtitle")}</p>
        </div>

        <Tabs defaultValue="dedicated" className="mt-12">
          <TabsList
            data-testid="pricing-tabs"
            className="mx-auto mb-10 flex flex-wrap justify-center gap-2 bg-transparent p-0 h-auto"
          >
            <TabsTrigger value="dedicated" data-testid="tab-dedicated" className={TAB_STYLES}>
              {t("pr.tab.dedicated")}
            </TabsTrigger>
            <TabsTrigger value="colocation" data-testid="tab-colocation" className={TAB_STYLES}>
              {t("pr.tab.colocation")}
            </TabsTrigger>
            <TabsTrigger value="interconnect" data-testid="tab-interconnect" className={TAB_STYLES}>
              {t("pr.tab.interconnect")}
            </TabsTrigger>
          </TabsList>

          <TabsContent value="dedicated" className="mt-0" data-testid="tab-content-dedicated">
            <CategoryGrid tiers={dedicatedTiers} categoryName={t("pr.tab.dedicated")} />
          </TabsContent>

          <TabsContent value="colocation" className="mt-0" data-testid="tab-content-colocation">
            <CategoryGrid tiers={colocationTiers} categoryName={t("pr.tab.colocation")} />
          </TabsContent>

          <TabsContent value="interconnect" className="mt-0" data-testid="tab-content-interconnect">
            <CategoryGrid tiers={interconnectTiers} categoryName={t("pr.tab.interconnect")} />
          </TabsContent>
        </Tabs>

        <div className="mt-14 rounded-3xl bg-white border border-slate-200 p-6 md:p-8 flex flex-col md:flex-row items-start md:items-center gap-6" data-testid="custom-quote-cta">
          <div className="h-14 w-14 rounded-2xl bg-[#f5b120] flex items-center justify-center flex-shrink-0">
            <Sparkles className="h-7 w-7 text-[#0a2350]" strokeWidth={2} />
          </div>
          <div className="flex-1">
            <h4 className="text-lg md:text-xl font-extrabold text-[#0a2350]">{t("pr.custom.title")}</h4>
            <p className="text-slate-600 text-sm mt-1">{t("pr.custom.body")}</p>
          </div>
          <a
            href={buildWaLink(customQuoteMsg)}
            target="_blank"
            rel="noreferrer"
            data-testid="custom-quote-wa"
            className="inline-flex items-center gap-2 rounded-full bg-[#0a2350] hover:bg-[#143a80] text-white px-6 py-3 text-sm font-semibold transition-colors flex-shrink-0"
          >
            {t("cta.getQuote")} <ArrowRight className="h-4 w-4" />
          </a>
        </div>
      </div>
    </section>
  );
};

export default Pricing;
