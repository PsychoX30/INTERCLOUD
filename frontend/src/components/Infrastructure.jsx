import React from "react";
import { ServerCog, Warehouse, Cable, Globe2 } from "lucide-react";
import { useLang } from "../i18n/LanguageContext";

const CARDS = [
  {
    id: "dc",
    icon: Warehouse,
    titleKey: "infra.dc.title",
    bodyKey: "infra.dc.body",
    metaKey: "infra.dc.meta",
    image:
      "https://images.unsplash.com/photo-1558494949-ef010cbdcc31?w=1000&q=70&auto=format&fit=crop",
  },
  {
    id: "servers",
    icon: ServerCog,
    titleKey: "infra.servers.title",
    bodyKey: "infra.servers.body",
    metaKey: "infra.servers.meta",
    image:
      "https://images.unsplash.com/photo-1544197150-b99a580bb7a8?w=1000&q=70&auto=format&fit=crop",
  },
  {
    id: "fiber",
    icon: Cable,
    titleKey: "infra.fiber.title",
    bodyKey: "infra.fiber.body",
    metaKey: "infra.fiber.meta",
    image:
      "https://images.unsplash.com/photo-1516110833967-0b5716ca1387?w=1000&q=70&auto=format&fit=crop",
  },
  {
    id: "network",
    icon: Globe2,
    titleKey: "infra.network.title",
    bodyKey: "infra.network.body",
    metaKey: "infra.network.meta",
    image:
      "https://images.unsplash.com/photo-1451187580459-43490279c0fa?w=1000&q=70&auto=format&fit=crop",
  },
];

const Infrastructure = () => {
  const { t } = useLang();

  return (
    <section
      id="infrastructure"
      className="relative py-24 bg-slate-50 overflow-hidden"
      data-testid="infrastructure-section"
    >
      <div className="absolute inset-x-0 top-0 h-32 bg-gradient-to-b from-white to-transparent pointer-events-none" />
      <div className="relative max-w-7xl mx-auto px-5 lg:px-8">
        <div className="text-center max-w-3xl mx-auto">
          <div className="text-[#f5b120] text-xs font-bold tracking-[0.2em] uppercase mb-3">
            {t("infra.eyebrow")}
          </div>
          <h2 className="text-3xl md:text-4xl font-extrabold text-[#0a2350]">
            {t("infra.title_a")}{" "}
            <span className="text-[#f5b120]">{t("infra.title_b")}</span>
          </h2>
          <div className="mx-auto mt-4 h-1 w-16 bg-[#f5b120] rounded-full" />
          <p className="mt-5 text-slate-600 leading-relaxed">
            {t("infra.subtitle")}
          </p>
        </div>

        <div className="mt-14 grid sm:grid-cols-2 lg:grid-cols-4 gap-5">
          {CARDS.map((c, idx) => {
            const Icon = c.icon;
            return (
              <article
                key={c.id}
                data-testid={`infra-card-${c.id}`}
                className="card-lift group relative rounded-3xl overflow-hidden bg-white border border-slate-200 hover:border-[#f5b120] transition-colors"
              >
                <div className="relative h-48 overflow-hidden">
                  <img
                    src={c.image}
                    alt={t(c.titleKey)}
                    loading="lazy"
                    className="absolute inset-0 h-full w-full object-cover transition-transform duration-700 group-hover:scale-110"
                  />
                  <div className="absolute inset-0 bg-gradient-to-t from-[#0a2350] via-[#0a2350]/45 to-transparent" />
                  <div className="absolute top-4 left-4 h-11 w-11 rounded-xl bg-[#f5b120] flex items-center justify-center shadow-lg shadow-black/20">
                    <Icon className="h-5 w-5 text-[#0a2350]" strokeWidth={1.9} />
                  </div>
                  <div className="absolute top-4 right-4 h-8 min-w-[32px] px-2 rounded-full border border-white/30 text-white text-[11px] font-extrabold flex items-center justify-center bg-white/10 backdrop-blur-sm">
                    {String(idx + 1).padStart(2, "0")}
                  </div>
                  <div className="absolute bottom-3 left-4 right-4 text-[10px] font-bold uppercase tracking-widest text-[#f5b120]">
                    {t(c.metaKey)}
                  </div>
                </div>

                <div className="p-6">
                  <h3 className="text-lg font-extrabold text-[#0a2350] leading-tight">
                    {t(c.titleKey)}
                  </h3>
                  <p className="mt-3 text-sm text-slate-600 leading-relaxed">
                    {t(c.bodyKey)}
                  </p>
                </div>
              </article>
            );
          })}
        </div>

        {/* Journey strip — how the layers connect */}
        <div
          className="mt-12 rounded-3xl bg-[#0a2350] text-white p-6 md:p-8 relative overflow-hidden"
          data-testid="infra-journey"
        >
          <div className="absolute -top-16 -right-16 h-64 w-64 rounded-full bg-[#f5b120]/10 blur-3xl pointer-events-none" />
          <div className="relative grid md:grid-cols-4 gap-6 items-center">
            {[
              { k: "infra.flow.1", n: "01" },
              { k: "infra.flow.2", n: "02" },
              { k: "infra.flow.3", n: "03" },
              { k: "infra.flow.4", n: "04" },
            ].map((s, i, arr) => (
              <div key={s.n} className="relative flex items-start gap-3">
                <div className="h-9 min-w-[36px] px-2 rounded-full bg-[#f5b120] text-[#0a2350] text-xs font-extrabold flex items-center justify-center flex-shrink-0">
                  {s.n}
                </div>
                <span className="text-sm md:text-[15px] leading-snug text-white/90">
                  {t(s.k)}
                </span>
                {i < arr.length - 1 && (
                  <div className="hidden md:block absolute -right-3 top-1/2 h-px w-6 bg-[#f5b120]/40" />
                )}
              </div>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
};

export default Infrastructure;
