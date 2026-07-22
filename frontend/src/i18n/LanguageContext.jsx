import React, { createContext, useContext, useEffect, useState, useCallback } from "react";

const LanguageContext = createContext({ lang: "id", setLang: () => {}, t: (x) => x });

const dict = {
  // Nav
  "nav.home": { id: "Home", en: "Home" },
  "nav.why": { id: "Kenapa Kami", en: "Why Us" },
  "nav.services": { id: "Layanan", en: "Services" },
  "nav.guide": { id: "Panduan", en: "Guide" },
  "nav.pricing": { id: "Harga", en: "Pricing" },
  "nav.partners": { id: "Partners", en: "Partners" },
  "nav.faq": { id: "FAQ", en: "FAQ" },
  "nav.contact": { id: "Kontak", en: "Contact" },

  // Common CTAs
  "cta.contactUs": { id: "Hubungi Kami", en: "Contact Us" },
  "cta.askWhatsApp": { id: "Tanya via WhatsApp", en: "Ask via WhatsApp" },
  "cta.orderWhatsApp": { id: "Pesan via WhatsApp", en: "Order via WhatsApp" },
  "cta.chatWhatsApp": { id: "Chat WhatsApp", en: "Chat on WhatsApp" },
  "cta.chatNow": { id: "Chat WhatsApp Sekarang", en: "Chat on WhatsApp Now" },
  "cta.viewServices": { id: "Lihat Layanan Kami", en: "View Our Services" },
  "cta.freeConsult": { id: "Konsultasi Gratis", en: "Free Consultation" },
  "cta.viewDetails": { id: "Lihat Detail Layanan", en: "View Service Details" },
  "cta.getQuote": { id: "Minta Penawaran", en: "Get a Quote" },
  "cta.sendEmail": { id: "Kirim Email", en: "Send Email" },
  "cta.startingFrom": { id: "Mulai dari", en: "Starting from" },
  "cta.perMonth": { id: "/bulan", en: "/month" },
  "cta.plusSetup": { id: "+ ", en: "+ " },

  // Hero
  "hero.tag": { id: "Powering Indonesia's Digital Infrastructure", en: "Powering Indonesia's Digital Infrastructure" },
  "hero.h1a": { id: "Bisnis digital butuh infrastruktur yang", en: "Your digital business needs infrastructure that is" },
  "hero.h1_stable": { id: "stabil", en: "stable" },
  "hero.h1_secure": { id: "aman", en: "secure" },
  "hero.h1c": { id: "dan siap berkembang.", en: "and ready to scale." },
  "hero.body": {
    id: "Kami membantu perusahaan menjaga operasional digital tetap berjalan dengan lebih stabil dan efisien. Mulai dari",
    en: "We help companies keep their digital operations running more stably and efficiently. From",
  },
  "hero.body2": {
    id: "hingga",
    en: "to",
  },
  "hero.body3": {
    id: "— semuanya kami dukung dengan solusi yang tepat.",
    en: "— we support you with the right solution.",
  },
  "hero.aud.company": { id: "Perusahaan", en: "Enterprises" },
  "hero.aud.software": { id: "Software House", en: "Software Houses" },
  "hero.aud.itsupport": { id: "Tim IT Support", en: "IT Teams" },
  "hero.stat.sla": { id: "SLA UPTIME", en: "SLA UPTIME" },
  "hero.stat.support": { id: "SUPPORT", en: "SUPPORT" },
  "hero.stat.dc": { id: "DATA CENTER", en: "DATA CENTER" },

  // Features / Why Us
  "feat.eyebrow": { id: "Why Choose Us", en: "Why Choose Us" },
  "feat.title": { id: "Kenapa Memilih Intercloud?", en: "Why Choose Intercloud?" },
  "feat.subtitle": {
    id: "Kami tidak hanya menyediakan layanan — kami menjadi partner strategis untuk pertumbuhan bisnis digital Anda.",
    en: "We're more than a service provider — we're a strategic partner for your digital growth.",
  },

  // Infrastructure (How it works)
  "infra.eyebrow": { id: "How We Power Your Business", en: "How We Power Your Business" },
  "infra.title_a": { id: "Empat lapisan yang menopang", en: "Four layers that keep" },
  "infra.title_b": { id: "operasional digital Anda", en: "your digital business online" },
  "infra.subtitle": {
    id: "Dari fasilitas fisik Tier III hingga konektivitas global — begini cara Intercloud menghadirkan infrastruktur yang stabil, aman, dan siap berkembang untuk bisnis Anda.",
    en: "From Tier III physical facilities to global connectivity — here's how Intercloud delivers stable, secure, and scalable infrastructure for your business.",
  },
  "infra.dc.title": { id: "Fasilitas Data Center", en: "Data Center Facility" },
  "infra.dc.meta": { id: "Layer 1 · Fasilitas Fisik", en: "Layer 1 · Physical Facility" },
  "infra.dc.body": {
    id: "Ruang Tier III bersertifikasi dengan power N+1, precision cooling, kontrol akses biometrik, dan CCTV 24/7 untuk melindungi hardware Anda.",
    en: "Certified Tier III facilities with N+1 power, precision cooling, biometric access control, and 24/7 CCTV to protect your hardware.",
  },
  "infra.servers.title": { id: "Server & Compute", en: "Servers & Compute" },
  "infra.servers.meta": { id: "Layer 2 · Compute", en: "Layer 2 · Compute" },
  "infra.servers.body": {
    id: "Rak server enterprise-grade, dedicated & shared compute, dan virtualisasi cloud siap-scale untuk berbagai skala workload.",
    en: "Enterprise-grade server racks, dedicated & shared compute, and scale-ready cloud virtualization for any workload size.",
  },
  "infra.fiber.title": { id: "Konektivitas Fiber", en: "Fiber Connectivity" },
  "infra.fiber.meta": { id: "Layer 3 · Konektivitas", en: "Layer 3 · Connectivity" },
  "infra.fiber.body": {
    id: "Backbone fiber optik antar Data Center Jakarta, cross-connect kapasitas tinggi, dan jalur redundan untuk zero-downtime.",
    en: "Fiber optic backbone across Jakarta data centers, high-capacity cross-connects, and redundant paths for zero-downtime.",
  },
  "infra.network.title": { id: "Jaringan Global", en: "Global Network" },
  "infra.network.meta": { id: "Layer 4 · Internet & Peering", en: "Layer 4 · Internet & Peering" },
  "infra.network.body": {
    id: "BGP peering multi-upstream, akses langsung ke APJII IIX & IXP lokal, serta transit Tier-1 global untuk trafik domestik dan internasional.",
    en: "Multi-upstream BGP peering, direct access to APJII IIX & local IXPs, and Tier-1 global transit for domestic and international traffic.",
  },
  "infra.flow.1": { id: "Anda kirim traffic ke domain / IP layanan.", en: "You send traffic to your domain / service IP." },
  "infra.flow.2": { id: "Routing kami arahkan lewat jalur tercepat.", en: "Our routing sends it through the fastest path." },
  "infra.flow.3": { id: "Server & compute memproses request Anda.", en: "Our servers & compute process the request." },
  "infra.flow.4": { id: "Response kembali stabil ke pengguna akhir.", en: "The response returns reliably to end users." },

  // Services
  "svc.eyebrow": { id: "Our Services", en: "Our Services" },
  "svc.title": { id: "Layanan Kami", en: "Our Services" },
  "svc.subtitle": {
    id: "Solusi infrastruktur IT end-to-end untuk perusahaan, startup, software house, dan tim IT yang butuh layanan server profesional.",
    en: "End-to-end IT infrastructure solutions for enterprises, startups, software houses, and IT teams that need professional server services.",
  },
  "svc.helperText": {
    id: "Klik kartu layanan untuk melihat detail fitur & mulai konsultasi via WhatsApp.",
    en: "Click any service card to see full details and start a WhatsApp consultation.",
  },
  "svc.modal.signals": { id: "Kapan bisnis butuh", en: "When your business needs" },
  "svc.modal.useCases": { id: "Cocok untuk", en: "Ideal for" },
  "svc.modal.comparison": { id: "Dibanding alternatif lain", en: "Compared to alternatives" },
  "svc.modal.features": { id: "Fitur & Spesifikasi", en: "Features & Specs" },

  // Decision Guide
  "dg.eyebrow": { id: "Panduan Pemilihan", en: "Decision Guide" },
  "dg.title_a": { id: "Kapan sebaiknya memilih", en: "When should you choose" },
  "dg.title_b": { id: "masing-masing layanan?", en: "each service?" },
  "dg.subtitle": {
    id: "Gunakan panduan sederhana ini untuk menyesuaikan pilihan server dengan skala, performa, dan kebutuhan operasional bisnis Anda.",
    en: "Use this simple guide to match the right server option with your business scale, performance and operational needs.",
  },
  "dg.hosting.title": { id: "Pilih Hosting", en: "Choose Hosting" },
  "dg.hosting.sub": { id: "Solusi paling praktis", en: "The most practical option" },
  "dg.hosting.body": {
    id: "Jika Anda butuh solusi paling praktis untuk website company profile, landing page, blog, atau aplikasi ringan dengan kebutuhan dasar.",
    en: "If you need the simplest solution for a company website, landing page, blog, or light application with basic requirements.",
  },
  "dg.vps.title": { id: "Pilih VPS", en: "Choose VPS" },
  "dg.vps.sub": { id: "Fleksibel & terisolasi", en: "Flexible & isolated" },
  "dg.vps.body": {
    id: "Jika traffic mulai meningkat dan Anda memerlukan resource lebih fleksibel serta kontrol yang lebih luas dengan full-root access.",
    en: "When traffic starts growing and you need more flexible resources plus wider control with full-root access.",
  },
  "dg.ded.title": { id: "Pilih Dedicated Server", en: "Choose Dedicated Server" },
  "dg.ded.sub": { id: "Performa maksimal", en: "Peak performance" },
  "dg.ded.body": {
    id: "Jika bisnis Anda membutuhkan performa tinggi, stabilitas maksimal, dan lingkungan server khusus untuk workload mission-critical.",
    en: "When your business needs high performance, maximum stability, and a dedicated server environment for mission-critical workloads.",
  },
  "dg.help.title": { id: "Belum yakin pilih yang mana?", en: "Not sure which to pick?" },
  "dg.help.body": {
    id: "Konsultasikan kebutuhan server Anda bersama tim Intercloud Digital Inovasi — kami bantu rekomendasikan solusi yang paling sesuai.",
    en: "Consult with the Intercloud Digital Inovasi team — we'll recommend the solution that fits you best.",
  },

  // Pricing
  "pr.eyebrow": { id: "Katalog Layanan", en: "Service Catalog" },
  "pr.title": { id: "Paket Lengkap untuk Skala Bisnis Anda", en: "Complete Plans for Every Business Scale" },
  "pr.subtitle": {
    id: "Harga transparan untuk Dedicated Server, Colocation, dan Interconnect & BGP Session — infrastruktur cloud terbaik dari Data Center Jakarta.",
    en: "Transparent pricing for Dedicated Server, Colocation, and Interconnect & BGP Session — top cloud infrastructure from Jakarta's data centers.",
  },
  "pr.tab.dedicated": { id: "Dedicated Server", en: "Dedicated Server" },
  "pr.tab.colocation": { id: "Colocation", en: "Colocation" },
  "pr.tab.interconnect": { id: "Interconnect & BGP", en: "Interconnect & BGP" },
  "pr.mostPopular": { id: "Most Popular", en: "Most Popular" },
  "pr.tnc": { id: "** Syarat & Ketentuan Berlaku", en: "** Terms & Conditions apply" },
  "pr.setupFee": { id: "setup fee", en: "setup fee" },
  "pr.custom.title": { id: "Butuh spesifikasi custom atau paket enterprise?", en: "Need custom specs or an enterprise plan?" },
  "pr.custom.body": {
    id: "Kami menyediakan custom quotation untuk Cloud, Firewall Solution, Lease to Own Appliance, dan kebutuhan hybrid infrastructure — sesuai kebutuhan bisnis Anda.",
    en: "We provide custom quotations for Cloud, Firewall Solution, Lease-to-Own Appliance, and hybrid infrastructure needs — tailored to your business.",
  },

  // Partners
  "pt.eyebrow": { id: "Trusted By", en: "Trusted By" },
  "pt.title": { id: "Partners & Clients", en: "Partners & Clients" },
  "pt.subtitle": {
    id: "Dipercaya oleh ISP, penyedia jaringan, dan brand ritel di seluruh Indonesia.",
    en: "Trusted by ISPs, network providers, and retail brands across Indonesia.",
  },
  "pt.count.label": { id: "Klien & Mitra Aktif", en: "Active Clients & Partners" },
  "pt.count.body": {
    id: "Dari operator fiber-to-the-home lokal hingga brand ritel — Intercloud mendukung koneksi, cloud, dan colocation mereka setiap hari.",
    en: "From local fiber-to-the-home operators to retail brands — Intercloud powers their connectivity, cloud, and colocation every day.",
  },

  // PoP
  "pop.eyebrow": { id: "Points of Presence", en: "Points of Presence" },
  "pop.title": { id: "Point of Presence Kami Saat Ini", en: "Our Current Points of Presence" },
  "pop.subtitle": {
    id: "Empat lokasi PoP strategis di Jakarta menghubungkan infrastruktur Anda ke jaringan Intercloud dengan latency rendah dan keandalan tinggi.",
    en: "Four strategic PoP locations in Jakarta connect your infrastructure to the Intercloud network with low latency and high reliability.",
  },
  "pop.tagLabel": { id: "Lokasi", en: "Location" },
  "pop.item1.name": { id: "Metta DC — Cyber 1, Lantai 5", en: "Metta DC — Cyber 1, 5th Floor" },
  "pop.item2.name": { id: "Omni DC — Cyber 1, Lantai 2", en: "Omni DC — Cyber 1, 2nd Floor" },
  "pop.item3.name": { id: "TIFA Building", en: "TIFA Building" },
  "pop.item4.name": { id: "APJII DC — Cyber 1, Lantai 1", en: "APJII DC — Cyber 1, 1st Floor" },
  "pop.item1.desc": {
    id: "PoP utama untuk BGP peering, interkoneksi domestik, dan konektivitas ke IXP lokal.",
    en: "Primary PoP for BGP peering, domestic interconnection, and local IXP connectivity.",
  },
  "pop.item2.desc": {
    id: "Kapasitas cross-connect tinggi untuk hybrid cloud & content delivery.",
    en: "High cross-connect capacity for hybrid cloud & content delivery.",
  },
  "pop.item3.desc": {
    id: "Lokasi carrier-neutral untuk redundansi jalur dan disaster recovery.",
    en: "Carrier-neutral location for path redundancy and disaster recovery.",
  },
  "pop.item4.desc": {
    id: "Terhubung langsung ke APJII IIX untuk trafik domestik yang optimal.",
    en: "Directly connected to APJII IIX for optimal domestic traffic.",
  },
  "pop.cta.title": { id: "Ingin tahu ketersediaan PoP untuk layanan Anda?", en: "Want to check PoP availability for your service?" },
  "pop.cta.body": {
    id: "Tim engineer kami dapat merekomendasikan PoP paling optimal berdasarkan tujuan trafik, latensi, dan kebutuhan redundansi Anda.",
    en: "Our engineers can recommend the best PoP based on your traffic destinations, latency, and redundancy needs.",
  },
  "wa.prefilled.pop": {
    id: "Halo Intercloud, saya ingin bertanya mengenai ketersediaan Point of Presence untuk kebutuhan konektivitas bisnis saya.",
    en: "Hello Intercloud, I'd like to ask about Point of Presence availability for my business's connectivity needs.",
  },

  // FAQ
  "faq.eyebrow": { id: "FAQ", en: "FAQ" },
  "faq.title": { id: "Frequently Asked Questions", en: "Frequently Asked Questions" },
  "faq.subtitle": {
    id: "Semua pertanyaan yang sering diajukan tentang Cloud, Hosting, VPS, Colocation, Firewall, dan DC to DC Connectivity.",
    en: "Common questions about Cloud, Hosting, VPS, Colocation, Firewall, and DC-to-DC Connectivity.",
  },
  "faq.helpTitle": { id: "Belum menemukan jawabannya?", en: "Can't find your answer?" },
  "faq.helpBody": { id: "Tim engineer kami siap membantu 24/7.", en: "Our engineers are ready to help 24/7." },

  // CTA
  "cta_sec.tag": { id: "Siap menskalakan infrastruktur bisnis Anda?", en: "Ready to scale your business infrastructure?" },
  "cta_sec.title_a": { id: "Mari diskusikan kebutuhan", en: "Let's discuss your" },
  "cta_sec.title_b": { id: "Cloud & Data Center", en: "Cloud & Data Center" },
  "cta_sec.title_c": { id: "Anda.", en: "needs." },
  "cta_sec.body": {
    id: "Konsultasi gratis dengan tim engineer kami. Dapatkan rekomendasi solusi terbaik yang sesuai skala dan budget bisnis Anda.",
    en: "Free consultation with our engineers. Get the best recommendation matching your scale and budget.",
  },
  "cta_sec.phone": { id: "Telepon / WhatsApp", en: "Phone / WhatsApp" },
  "cta_sec.email": { id: "Email", en: "Email" },
  "cta_sec.office": { id: "Kantor", en: "Office" },

  // Footer
  "footer.tagline": {
    id: "PT. Intercloud Digital Inovasi — penyedia layanan Cloud, Data Center, Konektivitas, dan Solusi IT terpercaya di Indonesia.",
    en: "PT. Intercloud Digital Inovasi — a trusted provider of Cloud, Data Center, Connectivity, and IT Solutions in Indonesia.",
  },
  "footer.pages": { id: "Pages", en: "Pages" },
  "footer.services": { id: "Layanan", en: "Services" },
  "footer.copy": {
    id: "PT. Intercloud Digital Inovasi. All rights reserved.",
    en: "PT. Intercloud Digital Inovasi. All rights reserved.",
  },
  "footer.made": { id: "Powered with care in Jakarta, Indonesia.", en: "Made with care in Jakarta, Indonesia." },

  // Misc
  "wa.prefilled.generic": {
    id: "Halo Intercloud Digital Inovasi, saya ingin konsultasi mengenai layanan infrastruktur IT bisnis saya.",
    en: "Hello Intercloud Digital Inovasi, I'd like to consult about IT infrastructure services for my business.",
  },
  "wa.prefilled.consult": {
    id: "Halo Intercloud, saya ingin konsultasi gratis kebutuhan infrastruktur IT bisnis saya.",
    en: "Hello Intercloud, I'd like a free consultation for my business's IT infrastructure needs.",
  },
  "wa.prefilled.decide": {
    id: "Halo Intercloud, saya butuh konsultasi untuk memilih layanan yang paling sesuai (Hosting / VPS / Dedicated Server) untuk kebutuhan bisnis saya.",
    en: "Hello Intercloud, I need help choosing the right service (Hosting / VPS / Dedicated Server) for my business.",
  },
  "wa.prefilled.customQuote": {
    id: "Halo Intercloud, saya ingin custom quotation untuk kebutuhan infrastruktur IT enterprise. Mohon informasi lebih lanjut.",
    en: "Hello Intercloud, I'd like a custom quotation for enterprise IT infrastructure. Please share more information.",
  },
  "wa.prefilled.svc": {
    id: (svcTitle) =>
      `Halo Intercloud Digital Inovasi, saya tertarik dengan layanan *${svcTitle}*. Mohon informasi paket, harga, dan proses onboarding-nya. Terima kasih.`,
    en: (svcTitle) =>
      `Hello Intercloud Digital Inovasi, I'm interested in *${svcTitle}*. Please share package details, pricing, and onboarding steps. Thank you.`,
  },
  "wa.prefilled.plan": {
    id: (planName, cat) =>
      `Halo Intercloud, saya ingin memesan paket *${planName}* (${cat}). Mohon informasi lebih lanjut.`,
    en: (planName, cat) =>
      `Hello Intercloud, I'd like to order the *${planName}* plan (${cat}). Please share more info.`,
  },

  // Toggle
  "lang.toggle.aria": { id: "Ganti bahasa", en: "Change language" },
};

export const LanguageProvider = ({ children }) => {
  const [lang, setLangState] = useState(() => {
    if (typeof window === "undefined") return "id";
    return localStorage.getItem("ic_lang") || "id";
  });

  useEffect(() => {
    document.documentElement.lang = lang;
    try { localStorage.setItem("ic_lang", lang); } catch (_) {}
  }, [lang]);

  const setLang = useCallback((next) => setLangState(next), []);

  const t = useCallback((key) => {
    const entry = dict[key];
    if (!entry) return key;
    const v = entry[lang];
    return v === undefined ? entry.id : v;
  }, [lang]);

  return (
    <LanguageContext.Provider value={{ lang, setLang, t }}>
      {children}
    </LanguageContext.Provider>
  );
};

export const useLang = () => useContext(LanguageContext);

/** Pick from {id, en} bilingual field. Falls back to raw string if not an object. */
export const pick = (field, lang) => {
  if (field == null) return "";
  if (typeof field === "string") return field;
  return field[lang] ?? field.id ?? "";
};
