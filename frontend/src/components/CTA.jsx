import React from "react";
import { ArrowRight, Mail, Phone, MapPin, Rocket } from "lucide-react";
import { WHATSAPP_LINK_ID, WHATSAPP_LINK_EN, WHATSAPP_PHONE, EMAIL, ADDRESS, buildWaLink } from "../mock/data";
import { useLang, pick } from "../i18n/LanguageContext";

const CTA = () => {
  const { lang, t } = useLang();
  const waLink = lang === "en" ? WHATSAPP_LINK_EN : WHATSAPP_LINK_ID;
  const consultMsg = lang === "en"
    ? "Hello Intercloud, I'd like a free consultation for my business's IT infrastructure needs."
    : "Halo Intercloud, saya ingin konsultasi gratis kebutuhan infrastruktur IT bisnis saya.";

  const contactList = [
    { icon: Phone, label: t("cta_sec.phone"), value: WHATSAPP_PHONE, href: waLink },
    { icon: Mail, label: t("cta_sec.email"), value: EMAIL, href: `mailto:${EMAIL}` },
    { icon: MapPin, label: t("cta_sec.office"), value: pick(ADDRESS, lang), href: "https://maps.google.com/?q=Menara+Cakrawala+Jl+MH+Thamrin+No+9+Jakarta+Pusat" },
  ];

  return (
    <section id="contact" className="relative py-24 bg-[#0a2350] text-white overflow-hidden">
      <div className="absolute inset-0 grid-overlay opacity-30" />
      <div className="absolute -top-24 -right-24 h-96 w-96 rounded-full bg-[#f5b120]/10 blur-3xl" />

      <div className="relative max-w-7xl mx-auto px-5 lg:px-8 grid lg:grid-cols-12 gap-10 items-center">
        <div className="lg:col-span-7">
          <div className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full bg-white/10 border border-white/15 text-xs font-medium text-white/90 mb-5">
            <Rocket className="h-3.5 w-3.5 text-[#f5b120]" />
            {t("cta_sec.tag")}
          </div>
          <h2 className="text-3xl md:text-5xl font-extrabold leading-tight">
            {t("cta_sec.title_a")}{" "}
            <span className="text-[#f5b120]">{t("cta_sec.title_b")}</span>{" "}
            {t("cta_sec.title_c")}
          </h2>
          <p className="mt-6 text-white/80 leading-relaxed max-w-xl">{t("cta_sec.body")}</p>

          <div className="mt-8 flex flex-wrap gap-3">
            <a
              href={buildWaLink(consultMsg)}
              target="_blank"
              rel="noreferrer"
              data-testid="cta-chat-now"
              className="inline-flex items-center gap-2 rounded-full bg-[#f5b120] hover:bg-[#ffc94a] text-[#0a2350] px-6 py-3.5 text-sm font-semibold transition-colors"
            >
              {t("cta.chatNow")} <ArrowRight className="h-4 w-4" />
            </a>
            <a
              href={`mailto:${EMAIL}`}
              className="inline-flex items-center gap-2 rounded-full bg-white/10 hover:bg-white/15 border border-white/20 text-white px-6 py-3.5 text-sm font-semibold transition-colors"
            >
              <Mail className="h-4 w-4" /> {t("cta.sendEmail")}
            </a>
          </div>
        </div>

        <div className="lg:col-span-5 space-y-4">
          {contactList.map((c) => {
            const Icon = c.icon;
            return (
              <a
                key={c.label}
                href={c.href}
                target={c.href.startsWith("http") ? "_blank" : undefined}
                rel="noreferrer"
                className="flex items-start gap-4 p-5 rounded-2xl bg-white/5 border border-white/10 hover:bg-white/10 hover:border-[#f5b120] transition-colors"
              >
                <div className="h-11 w-11 rounded-xl bg-[#f5b120] flex items-center justify-center flex-shrink-0">
                  <Icon className="h-5 w-5 text-[#0a2350]" strokeWidth={2} />
                </div>
                <div>
                  <div className="text-[#f5b120] text-xs font-bold uppercase tracking-widest">{c.label}</div>
                  <div className="text-white text-sm mt-1 leading-relaxed">{c.value}</div>
                </div>
              </a>
            );
          })}
        </div>
      </div>
    </section>
  );
};

export default CTA;
