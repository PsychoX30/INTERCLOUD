import React, { useState } from "react";
import { Link } from "react-router-dom";
import { ArrowUpRight, CheckCircle2, X, MessageCircle, Lightbulb, Target, GitCompareArrows, Sparkles, LogIn } from "lucide-react";
import { services, buildWaLink } from "../mock/data";
import { useLang, pick } from "../i18n/LanguageContext";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "./ui/dialog";

const SectionHeader = ({ icon: Icon, label }) => (
  <div className="flex items-center gap-2 mb-3">
    <div className="h-8 w-8 rounded-lg bg-[#f5b120]/15 flex items-center justify-center">
      <Icon className="h-4 w-4 text-[#f5b120]" strokeWidth={2.2} />
    </div>
    <h4 className="text-xs font-bold tracking-[0.18em] text-[#0a2350] uppercase">
      {label}
    </h4>
  </div>
);

const Services = () => {
  const [active, setActive] = useState(null);
  const { lang, t } = useLang();

  return (
    <section id="services" className="relative py-24 bg-slate-50" data-testid="services-section">
      <div className="absolute inset-x-0 top-0 h-40 bg-gradient-to-b from-white to-transparent" />
      <div className="relative max-w-7xl mx-auto px-5 lg:px-8">
        <div className="flex flex-col md:flex-row md:items-end md:justify-between gap-6">
          <div className="max-w-2xl">
            <div className="text-[#f5b120] text-xs font-bold tracking-[0.2em] uppercase mb-3">
              {t("svc.eyebrow")}
            </div>
            <h2 className="text-3xl md:text-4xl font-extrabold text-[#0a2350] title-underline">
              {t("svc.title")}
            </h2>
            <p className="mt-6 text-slate-600 leading-relaxed">
              {t("svc.subtitle")}
            </p>
          </div>
          <p className="text-sm text-slate-500 max-w-xs">{t("svc.helperText")}</p>
        </div>

        <div className="mt-14 grid sm:grid-cols-2 lg:grid-cols-3 gap-5">
          {services.map((svc) => {
            const Icon = svc.icon;
            const title = pick(svc.title, lang);
            const tagline = pick(svc.tagline, lang);
            const short = pick(svc.short, lang);
            const startFrom = pick(svc.startFrom, lang);
            const tags = pick(svc.tags, lang) || [];
            return (
              <button
                key={svc.id}
                onClick={() => setActive(svc)}
                data-testid={`service-card-${svc.id}`}
                className="card-lift text-left group relative rounded-2xl border border-slate-200 bg-white p-7 hover:border-[#0a2350] focus:outline-none focus:ring-2 focus:ring-[#f5b120]"
              >
                <div className="flex items-start justify-between mb-6">
                  <div className="h-14 w-14 rounded-xl bg-[#0a2350] group-hover:bg-[#f5b120] transition-colors flex items-center justify-center">
                    <Icon className="h-7 w-7 text-[#f5b120] group-hover:text-[#0a2350] transition-colors" strokeWidth={1.7} />
                  </div>
                  <div className="h-9 w-9 rounded-full bg-slate-100 group-hover:bg-[#f5b120] flex items-center justify-center transition-colors">
                    <ArrowUpRight className="h-4 w-4 text-slate-500 group-hover:text-[#0a2350] transition-colors" />
                  </div>
                </div>
                <h3 className="text-xl font-extrabold text-[#0a2350]">{title}</h3>
                <p className="mt-1 text-sm text-[#f5b120] font-semibold">{tagline}</p>
                <p className="mt-3 text-sm text-slate-600 leading-relaxed">{short}</p>

                {tags?.length > 0 && (
                  <div className="mt-4 flex flex-wrap gap-2">
                    {tags.map((tg) => (
                      <span
                        key={tg}
                        className="inline-flex items-center gap-1 rounded-full border border-[#f5b120]/40 bg-[#f5b120]/10 text-[#0a2350] px-2.5 py-1 text-[11px] font-semibold"
                      >
                        <CheckCircle2 className="h-3 w-3 text-[#f5b120]" /> {tg}
                      </span>
                    ))}
                  </div>
                )}

                <div className="mt-5 pt-5 border-t border-dashed border-slate-200 flex items-center justify-between">
                  <span className="text-xs text-slate-500">{t("cta.startingFrom")}</span>
                  <span className="text-sm font-bold text-[#0a2350]">{startFrom}</span>
                </div>
              </button>
            );
          })}
        </div>
      </div>

      <Dialog open={!!active} onOpenChange={(o) => !o && setActive(null)}>
        <DialogContent
          className="max-w-3xl bg-white p-0 gap-0 border-none overflow-hidden max-h-[92vh] flex flex-col"
          data-testid="service-modal"
        >
          {active && (() => {
            const title = pick(active.title, lang);
            const tagline = pick(active.tagline, lang);
            const overview = pick(active.overview, lang);
            const signals = pick(active.signals, lang) || [];
            const comparison = pick(active.comparison, lang);
            const featuresList = pick(active.features, lang) || [];
            const startFrom = pick(active.startFrom, lang);
            const waTemplate = lang === "en"
              ? `Hello Intercloud Digital Inovasi, I'm interested in *${title}*. Please share package details, pricing, and onboarding steps. Thank you.`
              : `Halo Intercloud Digital Inovasi, saya tertarik dengan layanan *${title}*. Mohon informasi paket, harga, dan proses onboarding-nya. Terima kasih.`;
            return (
              <>
                <div className="relative bg-[#0a2350] text-white p-7 md:p-8 flex-shrink-0">
                  <div className="absolute -top-16 -right-16 h-64 w-64 rounded-full bg-[#f5b120]/10 blur-3xl pointer-events-none" />
                  <button
                    onClick={() => setActive(null)}
                    className="absolute top-4 right-4 h-9 w-9 rounded-full bg-white/10 hover:bg-white/20 flex items-center justify-center transition-colors z-10"
                    aria-label="close"
                    data-testid="service-modal-close"
                  >
                    <X className="h-4 w-4" />
                  </button>
                  <div className="relative flex items-start gap-4">
                    <div className="h-16 w-16 rounded-2xl bg-[#f5b120] flex items-center justify-center flex-shrink-0">
                      <active.icon className="h-8 w-8 text-[#0a2350]" strokeWidth={1.8} />
                    </div>
                    <div className="min-w-0">
                      <DialogHeader className="space-y-1 text-left">
                        <DialogTitle className="text-2xl md:text-3xl font-extrabold text-white leading-tight">
                          {title}
                        </DialogTitle>
                        <DialogDescription className="text-[#f5b120] font-semibold text-sm">
                          {tagline}
                        </DialogDescription>
                      </DialogHeader>
                    </div>
                  </div>
                </div>

                <div className="overflow-y-auto no-scrollbar bg-white flex-1">
                  <div className="p-7 md:p-8 space-y-8">
                    {overview && (
                      <p className="text-slate-700 text-[15px] leading-relaxed">{overview}</p>
                    )}

                    {signals?.length > 0 && (
                      <div>
                        <SectionHeader icon={Lightbulb} label={`${t("svc.modal.signals")} ${title}?`} />
                        <ul className="grid sm:grid-cols-2 gap-2.5">
                          {signals.map((s) => (
                            <li key={s} className="flex items-start gap-3 text-sm text-slate-700 rounded-lg bg-slate-50 border border-slate-100 px-3.5 py-2.5">
                              <span className="mt-1.5 h-1.5 w-1.5 flex-shrink-0 rounded-full bg-[#f5b120]" />
                              <span className="leading-snug">{s}</span>
                            </li>
                          ))}
                        </ul>
                      </div>
                    )}

                    {active.useCases?.length > 0 && (
                      <div>
                        <SectionHeader icon={Target} label={t("svc.modal.useCases")} />
                        <div className="grid sm:grid-cols-2 gap-2.5">
                          {active.useCases.map((u) => {
                            const UIcon = u.icon;
                            const uLabel = pick(u.label, lang);
                            return (
                              <div
                                key={uLabel}
                                className="flex items-center gap-3 rounded-xl border border-slate-200 bg-white px-3.5 py-3 hover:border-[#f5b120] transition-colors"
                              >
                                <div className="h-10 w-10 flex-shrink-0 rounded-lg bg-[#0a2350] flex items-center justify-center">
                                  <UIcon className="h-5 w-5 text-[#f5b120]" strokeWidth={1.8} />
                                </div>
                                <span className="text-sm font-medium text-[#0a2350]">{uLabel}</span>
                              </div>
                            );
                          })}
                        </div>
                      </div>
                    )}

                    {comparison && (
                      <div>
                        <SectionHeader icon={GitCompareArrows} label={t("svc.modal.comparison")} />
                        <p className="text-sm md:text-[15px] leading-relaxed text-slate-700 bg-[#0a2350]/[0.03] border-l-4 border-[#f5b120] rounded-r-lg px-4 py-3">
                          {comparison}
                        </p>
                      </div>
                    )}

                    {featuresList?.length > 0 && (
                      <div>
                        <SectionHeader icon={Sparkles} label={t("svc.modal.features")} />
                        <ul className="grid sm:grid-cols-2 gap-2.5">
                          {featuresList.map((feat) => (
                            <li key={feat} className="flex items-start gap-3 text-sm text-slate-700">
                              <CheckCircle2 className="h-5 w-5 text-[#f5b120] flex-shrink-0 mt-0.5" />
                              <span>{feat}</span>
                            </li>
                          ))}
                        </ul>
                      </div>
                    )}
                  </div>

                  <div className="sticky bottom-0 bg-white border-t border-slate-100 px-7 md:px-8 py-4">
                    <div className="flex flex-col sm:flex-row items-stretch sm:items-center justify-between gap-3 p-4 rounded-xl bg-slate-50 border border-slate-200">
                      <div>
                        <div className="text-[11px] text-slate-500 uppercase tracking-widest font-bold">
                          {t("cta.startingFrom")}
                        </div>
                        <div className="text-xl font-extrabold text-[#0a2350]">{startFrom}</div>
                      </div>
                      <div className="flex flex-col sm:flex-row items-stretch gap-2">
                        <Link
                          to="/portal/login"
                          data-testid={`service-modal-portal-${active.id}`}
                          className="inline-flex items-center justify-center gap-2 rounded-full bg-[#0a2350] hover:bg-[#f5b120] hover:text-[#0a2350] text-white px-5 py-3 text-sm font-semibold transition-colors"
                        >
                          <LogIn className="h-4 w-4" />
                          {lang === "en" ? "Order in Portal" : "Pesan di Portal"}
                        </Link>
                        <a
                          href={buildWaLink(waTemplate)}
                          target="_blank"
                          rel="noreferrer"
                          data-testid={`service-modal-wa-${active.id}`}
                          className="inline-flex items-center justify-center gap-2 rounded-full bg-[#25d366] hover:bg-[#20bd5a] text-white px-5 py-3 text-sm font-semibold transition-colors"
                        >
                          <MessageCircle className="h-4 w-4" />
                          {t("cta.askWhatsApp")}
                        </a>
                      </div>
                    </div>
                  </div>
                </div>
              </>
            );
          })()}
        </DialogContent>
      </Dialog>
    </section>
  );
};

export default Services;
