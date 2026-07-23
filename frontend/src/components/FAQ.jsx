import React from "react";
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "./ui/accordion";
import { HelpCircle, MessageCircle } from "lucide-react";
import { faqs as fallbackFaqs, WHATSAPP_LINK_ID, WHATSAPP_LINK_EN } from "../mock/data";
import { useLang, pick } from "../i18n/LanguageContext";

const FAQ = () => {
  const { lang, t, cmsFaqs } = useLang();
  const waLink = lang === "en" ? WHATSAPP_LINK_EN : WHATSAPP_LINK_ID;
  // Admin ▸ Site Content overrides win; empty CMS list falls back to defaults.
  const faqs = (cmsFaqs && cmsFaqs.length) ? cmsFaqs : fallbackFaqs;

  return (
    <section id="faq" className="relative py-24 bg-white" data-testid="faq-section">
      <div className="max-w-6xl mx-auto px-5 lg:px-8 grid lg:grid-cols-12 gap-12">
        <div className="lg:col-span-4">
          <div className="text-[#f5b120] text-xs font-bold tracking-[0.2em] uppercase mb-3">
            {t("faq.eyebrow")}
          </div>
          <h2 className="text-3xl md:text-4xl font-extrabold text-[#0a2350] title-underline">
            {t("faq.title")}
          </h2>
          <p className="mt-6 text-slate-600 leading-relaxed">{t("faq.subtitle")}</p>

          <div className="mt-8 rounded-2xl bg-[#0a2350] text-white p-6">
            <HelpCircle className="h-8 w-8 text-[#f5b120] mb-3" strokeWidth={1.6} />
            <h4 className="font-bold text-lg">{t("faq.helpTitle")}</h4>
            <p className="text-white/75 text-sm mt-1">{t("faq.helpBody")}</p>
            <a
              href={waLink}
              target="_blank"
              rel="noreferrer"
              className="mt-5 inline-flex items-center gap-2 rounded-full bg-[#f5b120] hover:bg-[#ffc94a] text-[#0a2350] px-5 py-2.5 text-sm font-semibold transition-colors"
            >
              <MessageCircle className="h-4 w-4" /> {t("cta.chatWhatsApp")}
            </a>
          </div>
        </div>

        <div className="lg:col-span-8">
          <Accordion type="single" collapsible className="w-full space-y-3">
            {faqs.map((item, idx) => (
              <AccordionItem
                key={idx}
                value={`item-${idx}`}
                className="border border-slate-200 rounded-xl px-5 data-[state=open]:border-[#f5b120] data-[state=open]:bg-slate-50 transition-colors"
              >
                <AccordionTrigger className="text-left text-[#0a2350] font-semibold hover:no-underline py-5">
                  {pick(item.q, lang)}
                </AccordionTrigger>
                <AccordionContent className="text-slate-600 text-sm leading-relaxed pb-5">
                  {pick(item.a, lang)}
                </AccordionContent>
              </AccordionItem>
            ))}
          </Accordion>
        </div>
      </div>
    </section>
  );
};

export default FAQ;
