import React from "react";
import { Quote, Star } from "lucide-react";
import { useLang } from "../i18n/LanguageContext";

// MOCK testimonials - dapat dikelola via CMS di fase berikutnya.
const DATA = {
  id: {
    tag: "Testimoni Klien",
    title_a: "Dipercaya bisnis yang",
    title_b: "tidak boleh down.",
    items: [
      {
        quote: "Migrasi 40+ VM kami ke Intercloud selesai tanpa downtime. Tim NOC-nya responsif bahkan tengah malam.",
        name: "Rizky Pratama",
        role: "Head of IT, perusahaan logistik nasional",
        rating: 5,
      },
      {
        quote: "Latensi turun drastis setelah pindah colocation ke rack mereka. Harga jelas, SLA ditepati.",
        name: "Sari Wulandari",
        role: "CTO, startup fintech",
        rating: 5,
      },
      {
        quote: "Support 24/7-nya bukan sekadar jargon. Tiket kami selalu dijawab engineer, bukan bot.",
        name: "Andi Kurniawan",
        role: "IT Manager, grup media",
        rating: 5,
      },
    ],
  },
  en: {
    tag: "Client Testimonials",
    title_a: "Trusted by businesses that",
    title_b: "cannot afford downtime.",
    items: [
      {
        quote: "Migrating our 40+ VMs to Intercloud was completed with zero downtime. Their NOC responds even at midnight.",
        name: "Rizky Pratama",
        role: "Head of IT, national logistics company",
        rating: 5,
      },
      {
        quote: "Latency dropped drastically after moving colocation to their racks. Transparent pricing, SLA honored.",
        name: "Sari Wulandari",
        role: "CTO, fintech startup",
        rating: 5,
      },
      {
        quote: "Their 24/7 support is not just a slogan. Our tickets are always answered by engineers, not bots.",
        name: "Andi Kurniawan",
        role: "IT Manager, media group",
        rating: 5,
      },
    ],
  },
};

const Testimonials = () => {
  const { lang } = useLang();
  const t = DATA[lang] || DATA.id;
  return (
    <section id="testimonials" className="py-24 bg-white">
      <div className="max-w-7xl mx-auto px-5 lg:px-8">
        <div className="max-w-2xl">
          <div className="text-xs font-bold uppercase tracking-[0.2em] text-[#f5b120]">{t.tag}</div>
          <h2 className="mt-3 text-3xl md:text-4xl font-extrabold text-[#0a2350] leading-tight">
            {t.title_a} <span className="text-[#f5b120]">{t.title_b}</span>
          </h2>
          <div className="mt-4 h-1 w-14 rounded-full bg-[#f5b120]" />
        </div>

        <div className="mt-12 grid md:grid-cols-3 gap-6" data-testid="testimonials-grid">
          {t.items.map((x, i) => (
            <figure
              key={x.name}
              className={`relative rounded-3xl border p-7 flex flex-col ${
                i === 1
                  ? "bg-[#0a2350] border-[#0a2350] text-white md:-mt-4 md:mb-4 shadow-xl"
                  : "bg-slate-50 border-slate-200 text-[#0a2350]"
              }`}
              data-testid={`testimonial-${i}`}
            >
              <Quote className={`h-8 w-8 ${i === 1 ? "text-[#f5b120]" : "text-[#f5b120]/70"}`} strokeWidth={1.5} />
              <blockquote className={`mt-4 text-sm leading-relaxed flex-1 ${i === 1 ? "text-white/90" : "text-slate-600"}`}>
                "{x.quote}"
              </blockquote>
              <div className="mt-5 flex items-center gap-1">
                {Array.from({ length: x.rating }).map((_, s) => (
                  <Star key={s} className="h-3.5 w-3.5 fill-[#f5b120] text-[#f5b120]" />
                ))}
              </div>
              <figcaption className="mt-3">
                <div className={`text-sm font-extrabold ${i === 1 ? "text-white" : "text-[#0a2350]"}`}>{x.name}</div>
                <div className={`text-xs ${i === 1 ? "text-white/60" : "text-slate-500"}`}>{x.role}</div>
              </figcaption>
            </figure>
          ))}
        </div>
      </div>
    </section>
  );
};

export default Testimonials;
