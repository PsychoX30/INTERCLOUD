import React from "react";
import { ArrowRight, PlayCircle, Building2, Code2, Headphones } from "lucide-react";
import { WHATSAPP_LINK_ID, WHATSAPP_LINK_EN } from "../mock/data";
import { useLang } from "../i18n/LanguageContext";

const CurvedAccent = () => (
  <svg
    viewBox="0 0 800 800"
    className="absolute -right-24 top-0 h-full w-[720px] opacity-90 pointer-events-none hidden md:block"
    xmlns="http://www.w3.org/2000/svg"
    fill="none"
  >
    <path
      d="M 900 -50 C 700 200 500 350 550 550 C 590 700 700 780 900 850"
      stroke="#f5b120"
      strokeWidth="3"
      strokeLinecap="round"
    />
    <path
      d="M 950 0 C 700 250 480 400 540 620 C 580 760 760 830 980 900"
      stroke="#f5b120"
      strokeOpacity="0.35"
      strokeWidth="1.5"
    />
  </svg>
);

const BottomWave = () => (
  <svg
    className="absolute bottom-0 left-0 right-0 w-full h-[80px]"
    viewBox="0 0 1440 80"
    preserveAspectRatio="none"
    xmlns="http://www.w3.org/2000/svg"
  >
    <path
      d="M0,40 C240,90 480,10 720,30 C960,50 1200,80 1440,40 L1440,80 L0,80 Z"
      fill="#f5b120"
      opacity="0.95"
    />
  </svg>
);

const Hero = () => {
  const { lang, t } = useLang();
  const waLink = lang === "en" ? WHATSAPP_LINK_EN : WHATSAPP_LINK_ID;

  return (
    <section
      id="home"
      className="relative overflow-hidden bg-[#0a2350] text-white pt-32 pb-24 md:pt-40 md:pb-32"
    >
      <div className="absolute inset-0 grid-overlay opacity-40" />
      <div className="absolute -top-20 -left-20 h-96 w-96 rounded-full bg-[#f5b120]/10 blur-3xl" />
      <CurvedAccent />

      <div className="relative max-w-7xl mx-auto px-5 lg:px-8 grid lg:grid-cols-12 gap-10 items-center">
        <div className="lg:col-span-7 fade-up">
          <div className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full bg-white/10 border border-white/15 text-xs font-medium text-white/90 mb-6">
            <span className="h-1.5 w-1.5 rounded-full bg-[#f5b120]" />
            {t("hero.tag")}
          </div>
          <h1 className="text-4xl md:text-5xl lg:text-6xl font-extrabold leading-[1.08] tracking-tight">
            {t("hero.h1a")}{" "}
            <span className="text-[#f5b120]">{t("hero.h1_stable")}</span>,{" "}
            <span className="text-[#f5b120]">{t("hero.h1_secure")}</span>
            <br className="hidden md:block" /> {t("hero.h1c")}
          </h1>
          <div className="mt-5 w-16 h-1 bg-[#f5b120] rounded-full" />
          <p className="mt-6 text-white/80 text-base md:text-lg max-w-2xl leading-relaxed">
            {t("hero.body")}{" "}
            <span className="text-white font-medium">Cloud, Hosting, VPS, Colocation, Dedicated Server, Firewall</span>,{" "}
            {t("hero.body2")}{" "}
            <span className="text-white font-medium">DC to DC Connectivity</span>{" "}
            {t("hero.body3")}
          </p>

          <div className="mt-8 flex flex-wrap gap-3">
            <a
              href="#services"
              data-testid="hero-primary-cta"
              className="inline-flex items-center gap-2 rounded-full bg-[#f5b120] hover:bg-[#ffc94a] text-[#0a2350] px-6 py-3.5 text-sm font-semibold transition-colors"
            >
              {t("cta.viewServices")} <ArrowRight className="h-4 w-4" />
            </a>
            <a
              href={waLink}
              target="_blank"
              rel="noreferrer"
              data-testid="hero-secondary-cta"
              className="inline-flex items-center gap-2 rounded-full bg-white/10 hover:bg-white/15 border border-white/20 text-white px-6 py-3.5 text-sm font-semibold transition-colors"
            >
              <PlayCircle className="h-4 w-4" /> {t("cta.freeConsult")}
            </a>
          </div>

          <div className="mt-10 grid grid-cols-3 gap-4 max-w-lg">
            {[
              { icon: Building2, label: t("hero.aud.company") },
              { icon: Code2, label: t("hero.aud.software") },
              { icon: Headphones, label: t("hero.aud.itsupport") },
            ].map(({ icon: Icon, label }) => (
              <div key={label} className="flex flex-col items-center text-center gap-2">
                <div className="h-14 w-14 rounded-xl bg-white/5 border border-white/15 flex items-center justify-center">
                  <Icon className="h-7 w-7 text-[#f5b120]" strokeWidth={1.6} />
                </div>
                <span className="text-white/85 text-xs md:text-sm">{label}</span>
              </div>
            ))}
          </div>
        </div>

        <div className="lg:col-span-5 relative fade-up hidden lg:block">
          <div className="relative aspect-[4/5] rounded-3xl overflow-hidden border border-white/10 shadow-2xl shadow-black/40">
            <img
              src="https://images.pexels.com/photos/17489163/pexels-photo-17489163.jpeg?auto=compress&cs=tinysrgb&dpr=2&h=750&w=600"
              alt="Data center servers"
              className="absolute inset-0 h-full w-full object-cover"
              loading="eager"
            />
            <div className="absolute inset-0 bg-gradient-to-t from-[#0a2350] via-[#0a2350]/30 to-transparent" />
            <div className="absolute bottom-4 left-4 right-4 bg-white/10 backdrop-blur-md border border-white/20 rounded-2xl p-4">
              <div className="flex items-center justify-between">
                <div>
                  <div className="text-[#f5b120] text-xs font-semibold">{t("hero.stat.sla")}</div>
                  <div className="text-white text-2xl font-extrabold">99.5%</div>
                </div>
                <div>
                  <div className="text-[#f5b120] text-xs font-semibold">{t("hero.stat.support")}</div>
                  <div className="text-white text-2xl font-extrabold">24/7</div>
                </div>
                <div>
                  <div className="text-[#f5b120] text-xs font-semibold">{t("hero.stat.dc")}</div>
                  <div className="text-white text-2xl font-extrabold">Tier III</div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <BottomWave />
    </section>
  );
};

export default Hero;
