import React from "react";
import { ArrowRight, Mail, Phone, MapPin, Rocket } from "lucide-react";
import { useLang, useWaMessage } from "../i18n/LanguageContext";
import useContact from "../hooks/useContact";

const CTA = () => {
  const { t } = useLang();
  const contact = useContact();
  const waMsg = useWaMessage();
  const waLink = contact.waLink;
  const consultMsg = waMsg("wa.prefilled.consult");
  const consultLink = contact.waLinkWith(consultMsg);

  const contactList = [
    { icon: Phone, label: t("cta_sec.phone"), value: contact.phone, href: waLink },
    { icon: Mail, label: t("cta_sec.email"), value: contact.email, href: contact.mailtoHref },
    { icon: MapPin, label: t("cta_sec.office"), value: contact.addressText, href: contact.mapsUrl },
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
              href={consultLink}
              target="_blank"
              rel="noreferrer"
              data-testid="cta-chat-now"
              className="inline-flex items-center gap-2 rounded-full bg-[#f5b120] hover:bg-[#ffc94a] text-[#0a2350] px-6 py-3.5 text-sm font-semibold transition-colors"
            >
              {t("cta.chatNow")} <ArrowRight className="h-4 w-4" />
            </a>
            <a
              href={contact.mailtoHref}
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
