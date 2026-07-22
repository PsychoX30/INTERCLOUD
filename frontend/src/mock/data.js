import {
  Cloud, Server, HardDrive, Network, ShieldCheck, Boxes, Cable, Globe2,
  Building2, Code2, Headphones, Rocket, TrendingUp, ServerCog,
  Landmark, CreditCard, Globe, Zap, Lock, Users,
  LayoutTemplate, Container, Warehouse, HandCoins, Waypoints,
} from "lucide-react";

// ---------- CONTACT ----------
export const WHATSAPP_PHONE = "+62 878-1239-7187";
export const WHATSAPP_NUMBER = "6287812397187";
export const EMAIL = "support@intercloud-digital.com";
export const WEBSITE = "intercloud-digital.com";
export const ADDRESS = {
  id: "Menara Cakrawala Lt 12, Unit 1205A, Jl. M.H. Thamrin No.9, RT.2/RW.1, Kb. Sirih, Kec. Menteng, Jakarta Pusat, DKI Jakarta 10340",
  en: "Menara Cakrawala 12th Fl, Unit 1205A, Jl. M.H. Thamrin No.9, RT.2/RW.1, Kb. Sirih, Menteng, Central Jakarta, DKI Jakarta 10340, Indonesia",
};

export const buildWaLink = (message) =>
  `https://wa.me/${WHATSAPP_NUMBER}?text=${encodeURIComponent(message)}`;

export const WHATSAPP_LINK_ID = buildWaLink(
  "Halo Intercloud Digital Inovasi, saya ingin konsultasi mengenai layanan infrastruktur IT bisnis saya."
);
export const WHATSAPP_LINK_EN = buildWaLink(
  "Hello Intercloud Digital Inovasi, I'd like to consult about IT infrastructure services for my business."
);
// Backwards-compat generic link (defaults to Indonesian)
export const WHATSAPP_LINK = WHATSAPP_LINK_ID;

// ---------- WHY US ----------
export const features = [
  {
    icon: "pricing",
    title: { id: "Harga Kompetitif", en: "Competitive Pricing" },
    desc: {
      id: "Value maksimal dengan harga bersaing untuk skala UMKM hingga enterprise.",
      en: "Maximum value with competitive pricing from SMB to enterprise scale.",
    },
  },
  {
    icon: "support",
    title: { id: "Support 24/7", en: "24/7 Support" },
    desc: {
      id: "Tim engineer bersertifikasi siap monitor, respons, & bantu Anda kapan pun.",
      en: "Certified engineers ready to monitor, respond, and help you anytime.",
    },
  },
  {
    icon: "network",
    title: { id: "Koneksi Stabil", en: "Stable Connectivity" },
    desc: {
      id: "Multi-upstream IIX, IX, dan Tier-1 global — cepat untuk domestik & internasional.",
      en: "Multi-upstream IIX, IX, and Tier-1 global links — fast for domestic and international traffic.",
    },
  },
  {
    icon: "sla",
    title: { id: "SLA 99,5%", en: "SLA 99.5%" },
    desc: {
      id: "Jaminan uptime tinggi dengan power N+1, cooling presisi, & data center Tier III.",
      en: "High-uptime guarantee with N+1 power, precision cooling, and Tier III data centers.",
    },
  },
];

// ---------- SERVICES ----------
export const services = [
  {
    id: "cloud",
    icon: Cloud,
    title: { id: "Cloud Service", en: "Cloud Service" },
    tagline: {
      id: "Cloud scalable, aman & siap berkembang",
      en: "Scalable, secure cloud ready to grow with you",
    },
    short: {
      id: "Infrastruktur cloud publik, privat, & hybrid dengan performa tinggi, auto-scaling, dan keamanan enterprise.",
      en: "Public, private, and hybrid cloud infrastructure with high performance, auto-scaling, and enterprise-grade security.",
    },
    overview: {
      id: "Cloud Service adalah infrastruktur komputasi virtual yang bisa dipakai on-demand — Anda bisa menaikkan atau menurunkan resource sesuai kebutuhan, tanpa perlu investasi hardware fisik. Cocok untuk perusahaan yang ingin bergerak cepat tanpa dibatasi oleh CAPEX.",
      en: "Cloud Service is on-demand virtual compute — you scale resources up or down without investing in physical hardware. Ideal for businesses that want to move fast without CAPEX constraints.",
    },
    signals: {
      id: [
        "Bisnis butuh scale up/down resource sesuai traffic",
        "Ingin bayar sesuai pemakaian (pay-as-you-go)",
        "Perlu deploy environment baru dalam hitungan menit",
        "Membangun aplikasi modern berbasis container / microservices",
        "Butuh disaster recovery & high availability multi-zone",
      ],
      en: [
        "You need to scale resources up/down with traffic",
        "You want pay-as-you-go billing",
        "You need to spin up new environments in minutes",
        "You're building modern container/microservice apps",
        "You need DR and multi-zone high availability",
      ],
    },
    useCases: [
      { icon: Rocket, label: { id: "Startup & SaaS builder", en: "Startups & SaaS builders" } },
      { icon: Code2, label: { id: "Software house & dev team", en: "Software houses & dev teams" } },
      { icon: TrendingUp, label: { id: "E-commerce & platform digital", en: "E-commerce & digital platforms" } },
      { icon: Building2, label: { id: "Enterprise dengan kebutuhan hybrid cloud", en: "Enterprises needing hybrid cloud" } },
    ],
    comparison: {
      id: "Dibanding on-premise, Cloud Service memberikan fleksibilitas resource, kecepatan deployment, dan model biaya operasional yang lebih ringan. Cocok jika bisnis Anda butuh kelincahan tanpa mengelola hardware sendiri.",
      en: "Versus on-premise, Cloud Service offers resource flexibility, faster deployments, and a lighter OPEX model. Ideal when your business needs agility without managing hardware itself.",
    },
    features: {
      id: [
        "Public, Private & Hybrid Cloud",
        "Auto-scaling & Load Balancer",
        "Snapshot & backup terjadwal",
        "Panel manajemen self-service",
        "SLA 99,5% dengan multi-upstream",
        "Integrasi API & DevOps ready",
      ],
      en: [
        "Public, Private & Hybrid Cloud",
        "Auto-scaling & Load Balancer",
        "Scheduled snapshots & backups",
        "Self-service management panel",
        "SLA 99.5% with multi-upstream",
        "API integration & DevOps ready",
      ],
    },
    startFrom: { id: "Rp 250.000/bulan", en: "Rp 250,000/month" },
    tags: {
      id: ["Skalabel", "Fleksibel", "Enterprise"],
      en: ["Scalable", "Flexible", "Enterprise"],
    },
  },
  {
    id: "hosting",
    icon: LayoutTemplate,
    title: { id: "Web Hosting", en: "Web Hosting" },
    tagline: {
      id: "Hosting cepat untuk website & aplikasi ringan",
      en: "Fast hosting for websites and lightweight apps",
    },
    short: {
      id: "Shared hosting NVMe SSD dengan cPanel, LiteSpeed, & keamanan lengkap — praktis dan mudah dikelola.",
      en: "NVMe SSD shared hosting with cPanel, LiteSpeed, and complete security — simple and easy to manage.",
    },
    overview: {
      id: "Web Hosting adalah solusi paling praktis untuk website company profile, landing page, blog, atau aplikasi skala kecil–menengah. Server dikelola oleh tim kami sehingga Anda tinggal fokus pada konten dan bisnis.",
      en: "Web Hosting is the simplest option for company websites, landing pages, blogs, and small-to-mid apps. Our team manages the servers so you focus on content and business.",
    },
    signals: {
      id: [
        "Butuh website online cepat tanpa urusan sysadmin",
        "Ingin panel yang mudah (cPanel) & install one-click",
        "Traffic website masih ringan sampai menengah",
        "Butuh email profesional @perusahaan-anda",
      ],
      en: [
        "You need a website live quickly without sysadmin work",
        "You want an easy panel (cPanel) & one-click installs",
        "Traffic is still light to medium",
        "You need professional email @yourcompany",
      ],
    },
    useCases: [
      { icon: Building2, label: { id: "Company profile & landing page", en: "Company profile & landing pages" } },
      { icon: Globe, label: { id: "Blog, portfolio, & microsite", en: "Blogs, portfolios & microsites" } },
      { icon: Rocket, label: { id: "MVP & aplikasi ringan", en: "MVPs & light apps" } },
      { icon: CreditCard, label: { id: "Toko online kecil-menengah", en: "Small–mid online stores" } },
    ],
    comparison: {
      id: "Dibanding VPS, Web Hosting jauh lebih praktis karena sudah full-managed — cocok kalau Anda belum butuh kontrol server penuh dan ingin biaya paling efisien.",
      en: "Versus VPS, Web Hosting is far simpler because it's fully managed — ideal when you don't need full server control and want the most cost-efficient option.",
    },
    features: {
      id: [
        "NVMe SSD Storage",
        "cPanel + LiteSpeed Web Server",
        "Free SSL Let's Encrypt",
        "Daily automatic backup",
        "Anti-malware & Imunify360",
        "Unlimited bandwidth (fair use)",
      ],
      en: [
        "NVMe SSD storage",
        "cPanel + LiteSpeed Web Server",
        "Free SSL (Let's Encrypt)",
        "Daily automatic backups",
        "Anti-malware & Imunify360",
        "Unlimited bandwidth (fair use)",
      ],
    },
    startFrom: { id: "Rp 25.000/bulan", en: "Rp 25,000/month" },
    tags: { id: ["Praktis", "Mudah dikelola"], en: ["Practical", "Easy to manage"] },
  },
  {
    id: "vps",
    icon: Container,
    title: { id: "VPS (Virtual Private Server)", en: "VPS (Virtual Private Server)" },
    tagline: {
      id: "Fleksibel dengan resource dedicated",
      en: "Flexible with dedicated resources",
    },
    short: {
      id: "VPS KVM full-root access dengan storage NVMe & jaringan 1Gbps — kontrol penuh untuk aplikasi custom.",
      en: "KVM VPS with full root access, NVMe storage & 1Gbps networking — full control for custom apps.",
    },
    overview: {
      id: "VPS adalah pilihan tepat ketika bisnis mulai membutuhkan resource lebih fleksibel dan kontrol lebih luas dibanding shared hosting. Anda mendapat root access, memilih OS, dan mengatur stack aplikasi sesuai kebutuhan.",
      en: "VPS is the right pick when your business needs more flexible resources and wider control than shared hosting. You get root access, pick the OS, and configure the app stack as you need.",
    },
    signals: {
      id: [
        "Website/aplikasi mulai butuh resource dedicated",
        "Ingin install stack custom (Node.js, Docker, dsb.)",
        "Butuh IP publik dedicated untuk mail server atau API",
        "Traffic meningkat & shared hosting tidak lagi cukup",
      ],
      en: [
        "Your website/app needs dedicated resources",
        "You want to install a custom stack (Node.js, Docker, etc.)",
        "You need a dedicated public IP for mail server or API",
        "Traffic is rising and shared hosting isn't enough",
      ],
    },
    useCases: [
      { icon: Code2, label: { id: "Development & staging environment", en: "Development & staging environments" } },
      { icon: TrendingUp, label: { id: "Website dengan traffic menengah", en: "Sites with medium traffic" } },
      { icon: ServerCog, label: { id: "API backend & microservices", en: "API backends & microservices" } },
      { icon: Globe, label: { id: "VPN privat & tunneling", en: "Private VPN & tunneling" } },
    ],
    comparison: {
      id: "Dibanding shared hosting, VPS memberi kontrol dan performa yang jauh lebih stabil. Dibanding Dedicated Server, VPS lebih hemat namun tetap memberi isolasi resource.",
      en: "Versus shared hosting, VPS gives more control and much steadier performance. Versus a Dedicated Server, VPS is cheaper while still offering isolated resources.",
    },
    features: {
      id: [
        "Virtualisasi KVM full-root access",
        "NVMe SSD storage",
        "Network 1Gbps unmetered lokal",
        "OS: Linux, Windows Server",
        "IPv4 dedicated + IPv6",
        "Deploy dalam hitungan menit",
      ],
      en: [
        "KVM virtualization with full root access",
        "NVMe SSD storage",
        "1Gbps unmetered local network",
        "OS: Linux, Windows Server",
        "Dedicated IPv4 + IPv6",
        "Deploy in minutes",
      ],
    },
    startFrom: { id: "Rp 150.000/bulan", en: "Rp 150,000/month" },
    tags: { id: ["Fleksibel", "Skalabel"], en: ["Flexible", "Scalable"] },
  },
  {
    id: "colocation",
    icon: Warehouse,
    title: { id: "Colocation", en: "Colocation" },
    tagline: {
      id: "Titipkan server Anda di Data Center Tier III",
      en: "House your servers in a Tier III data center",
    },
    short: {
      id: "Rack space 1U s/d full rack dengan power N+1, presisi cooling, & konektivitas premium multi-upstream.",
      en: "1U to full-rack space with N+1 power, precision cooling, and premium multi-upstream connectivity.",
    },
    overview: {
      id: "Colocation adalah layanan penempatan server fisik milik Anda di data center kami. Anda memiliki hardware-nya, kami menyediakan tempatnya — lengkap dengan power redundant, cooling, fire suppression, dan konektivitas kelas enterprise.",
      en: "Colocation lets you place your own physical servers inside our data center. You own the hardware, we provide the environment — with redundant power, cooling, fire suppression, and enterprise connectivity.",
    },
    signals: {
      id: [
        "Sudah punya hardware sendiri & ingin dijaga di DC profesional",
        "Butuh compliance / audit (perbankan, fintech, pemerintahan)",
        "Ingin kontrol penuh atas hardware tanpa membangun DC sendiri",
        "Perlu redundant power & cooling 24/7",
      ],
      en: [
        "You already own hardware and want it hosted in a professional DC",
        "You need compliance/audit-ready hosting (banking, fintech, gov)",
        "You want full hardware control without building your own DC",
        "You need redundant power and 24/7 cooling",
      ],
    },
    useCases: [
      { icon: Landmark, label: { id: "Perbankan, fintech & lembaga keuangan", en: "Banks, fintech & financial institutions" } },
      { icon: Building2, label: { id: "Enterprise & korporasi", en: "Enterprises & large corporates" } },
      { icon: Lock, label: { id: "Aplikasi compliance-sensitive", en: "Compliance-sensitive applications" } },
      { icon: ServerCog, label: { id: "Perusahaan dengan tim IT internal", en: "Companies with in-house IT teams" } },
    ],
    comparison: {
      id: "Dibanding membangun data center sendiri, Colocation memangkas biaya operasional listrik, cooling, dan sertifikasi. Anda hanya fokus pada server dan aplikasi.",
      en: "Versus building your own DC, Colocation cuts operational costs for power, cooling, and certifications. You just focus on servers and applications.",
    },
    features: {
      id: [
        "Data Center bersertifikasi Tier III",
        "Redundant power N+1 (450W – 20A)",
        "Presisi cooling & fire suppression",
        "1Gbps local & CDN, 100Mbps global",
        "IP Public + remote hand support",
        "Access 24/7 dengan biometric",
      ],
      en: [
        "Tier III certified data center",
        "Redundant N+1 power (450W – 20A)",
        "Precision cooling & fire suppression",
        "1Gbps local & CDN, 100Mbps global",
        "Public IP + remote hand support",
        "24/7 biometric access",
      ],
    },
    startFrom: { id: "Rp 1.500.000/bulan", en: "Rp 1,500,000/month" },
    tags: { id: ["Enterprise", "Compliance-ready"], en: ["Enterprise", "Compliance-ready"] },
  },
  {
    id: "dedicated",
    icon: Server,
    title: { id: "Dedicated Server", en: "Dedicated Server" },
    tagline: {
      id: "Server fisik khusus untuk performa maksimal",
      en: "A physical server dedicated to peak performance",
    },
    short: {
      id: "Bare-metal server high-performance yang seluruh resource-nya dedicated untuk Anda — cocok untuk workload berat & database.",
      en: "High-performance bare-metal server where every resource is dedicated to you — perfect for heavy workloads and databases.",
    },
    overview: {
      id: "Dedicated Server adalah layanan server khusus yang digunakan oleh satu pelanggan saja. Artinya, seluruh resource server tidak dibagi dengan pengguna lain, sehingga performa lebih stabil, keamanan lebih terjaga, dan pengelolaan teknis lebih leluasa.",
      en: "A Dedicated Server is a server used by a single customer. Every resource is exclusively yours — leading to steadier performance, tighter security, and greater technical flexibility.",
    },
    signals: {
      id: [
        "Website atau aplikasi sering lambat",
        "Trafik pengguna semakin meningkat",
        "Membutuhkan resource server khusus",
        "Mengelola aplikasi penting perusahaan",
        "Membutuhkan kontrol server yang lebih fleksibel",
      ],
      en: [
        "Your site or app is often slow",
        "User traffic keeps rising",
        "You need dedicated server resources",
        "You run mission-critical business applications",
        "You need more flexible server control",
      ],
    },
    useCases: [
      { icon: Rocket, label: { id: "Startup dan software house", en: "Startups & software houses" } },
      { icon: Building2, label: { id: "Aplikasi internal perusahaan", en: "Internal enterprise applications" } },
      { icon: Globe, label: { id: "Website dengan trafik tinggi", en: "High-traffic websites" } },
      { icon: CreditCard, label: { id: "Sistem transaksi online", en: "Online transaction systems" } },
      { icon: TrendingUp, label: { id: "Platform digital yang terus berkembang", en: "Growing digital platforms" } },
    ],
    comparison: {
      id: "Dibanding layanan hosting biasa, Dedicated Server memberikan ruang yang lebih besar untuk performa, keamanan, dan pengelolaan teknis. Namun, pemilihan spesifikasi tetap perlu disesuaikan dengan kebutuhan bisnis.",
      en: "Versus ordinary hosting, a Dedicated Server gives more room for performance, security, and technical management. Still, pick specs that match your actual business needs.",
    },
    features: {
      id: [
        "CPU 8 Core / 16 Thread",
        "16GB DDR4 – upgradeable",
        "2 x 300GB SAS / opsional NVMe",
        "Local BW up to 1Gbps",
        "Global BW up to 100Mbps",
        "1 IPv4 + remote KVM",
      ],
      en: [
        "CPU 8-core / 16-thread",
        "16GB DDR4 – upgradeable",
        "2 x 300GB SAS / optional NVMe",
        "Local BW up to 1Gbps",
        "Global BW up to 100Mbps",
        "1 IPv4 + remote KVM",
      ],
    },
    startFrom: { id: "Rp 950.000/bulan", en: "Rp 950,000/month" },
    tags: { id: ["Performa tinggi", "Kontrol penuh"], en: ["High performance", "Full control"] },
  },
  {
    id: "lease",
    icon: HandCoins,
    title: { id: "Lease to Own Appliance", en: "Lease-to-Own Appliance" },
    tagline: {
      id: "Miliki hardware enterprise tanpa beban CAPEX besar",
      en: "Own enterprise hardware without a heavy CAPEX outlay",
    },
    short: {
      id: "Skema sewa dengan opsi kepemilikan untuk server, router, firewall & switch enterprise brand ternama.",
      en: "Lease-with-ownership scheme for enterprise servers, routers, firewalls, and switches from leading brands.",
    },
    overview: {
      id: "Lease to Own Appliance memungkinkan bisnis Anda menggunakan hardware enterprise (Dell, HP, Cisco, Mikrotik, Huawei) dengan skema cicilan fleksibel — termasuk instalasi, maintenance, dan spare part. Di akhir kontrak, hardware sepenuhnya menjadi milik Anda.",
      en: "Lease-to-Own Appliance lets your business use enterprise hardware (Dell, HP, Cisco, Mikrotik, Huawei) with flexible installments — including installation, maintenance, and spare parts. At contract end, the hardware becomes yours.",
    },
    signals: {
      id: [
        "Ingin hardware baru tanpa pengeluaran CAPEX besar di awal",
        "Butuh spesifikasi upgrade tapi cash-flow terbatas",
        "Ingin biaya maintenance & sparepart sudah termasuk",
        "Membutuhkan opsi kepemilikan di akhir kontrak",
      ],
      en: [
        "You want new hardware without a big upfront CAPEX",
        "You need higher specs but cash flow is tight",
        "You want maintenance & spare parts included",
        "You want ownership at the end of the contract",
      ],
    },
    useCases: [
      { icon: Building2, label: { id: "Kantor cabang & perusahaan multi-lokasi", en: "Branch offices & multi-site companies" } },
      { icon: Users, label: { id: "SME yang ingin scale hardware secara bertahap", en: "SMBs scaling hardware gradually" } },
      { icon: ServerCog, label: { id: "Tim IT yang butuh predictable OPEX", en: "IT teams that need predictable OPEX" } },
      { icon: Landmark, label: { id: "Lembaga pendidikan & pemerintah", en: "Education & government institutions" } },
    ],
    comparison: {
      id: "Dibanding beli langsung, skema lease-to-own menjaga cash-flow tetap sehat dan memberi jalur upgrade rutin. Dibanding sewa biasa, akhirnya hardware menjadi aset Anda.",
      en: "Versus outright purchase, lease-to-own keeps cash flow healthy and gives a regular upgrade path. Versus plain rental, you eventually own the hardware.",
    },
    features: {
      id: [
        "Brand ternama: Dell, HP, Cisco, Mikrotik, Huawei",
        "Cicilan fleksibel 12/24/36 bulan",
        "Free instalasi & konfigurasi",
        "Maintenance & sparepart included",
        "Upgrade path setiap 24 bulan",
        "Ownership transfer di akhir kontrak",
      ],
      en: [
        "Leading brands: Dell, HP, Cisco, Mikrotik, Huawei",
        "Flexible 12/24/36-month installments",
        "Free installation & configuration",
        "Maintenance & spare parts included",
        "Upgrade path every 24 months",
        "Ownership transfer at contract end",
      ],
    },
    startFrom: { id: "Custom quotation", en: "Custom quotation" },
    tags: { id: ["OPEX-friendly", "Ownership"], en: ["OPEX-friendly", "Ownership"] },
  },
  {
    id: "firewall",
    icon: ShieldCheck,
    title: { id: "Firewall Solution", en: "Firewall Solution" },
    tagline: {
      id: "Proteksi Next-Gen untuk seluruh jaringan",
      en: "Next-Gen protection for your entire network",
    },
    short: {
      id: "NGFW managed dengan IPS/IDS, deep packet inspection, web filtering, & SSL VPN — 24/7 monitored.",
      en: "Managed NGFW with IPS/IDS, deep packet inspection, web filtering, and SSL VPN — monitored 24/7.",
    },
    overview: {
      id: "Firewall Solution kami menggunakan Next-Generation Firewall (Fortinet, Palo Alto, Sophos) yang di-manage penuh oleh tim security engineer kami. Anda mendapat perlindungan enterprise-grade tanpa perlu memikirkan konfigurasi, patching, atau update signature.",
      en: "Our Firewall Solution uses Next-Generation Firewalls (Fortinet, Palo Alto, Sophos) fully managed by our security engineers. You get enterprise-grade protection without worrying about configuration, patching, or signature updates.",
    },
    signals: {
      id: [
        "Bisnis menyimpan data sensitif atau customer PII",
        "Perlu compliance ISO 27001 / PCI DSS / OJK",
        "Sudah pernah kena percobaan DDoS / phishing",
        "Butuh remote access VPN untuk karyawan work-from-anywhere",
      ],
      en: [
        "You store sensitive data or customer PII",
        "You need ISO 27001 / PCI DSS / OJK compliance",
        "You've experienced DDoS or phishing attempts",
        "You need remote-access VPN for a work-from-anywhere team",
      ],
    },
    useCases: [
      { icon: Landmark, label: { id: "Bank, fintech & payment gateway", en: "Banks, fintech & payment gateways" } },
      { icon: Building2, label: { id: "Enterprise multi-branch", en: "Multi-branch enterprises" } },
      { icon: Lock, label: { id: "Sektor kesehatan & pendidikan", en: "Healthcare & education sectors" } },
      { icon: TrendingUp, label: { id: "E-commerce dengan volume transaksi tinggi", en: "High-volume e-commerce" } },
    ],
    comparison: {
      id: "Dibanding firewall software gratis, NGFW managed kami memberi threat intelligence real-time, response time cepat, dan tim security yang selalu standby.",
      en: "Versus free software firewalls, our managed NGFW delivers real-time threat intelligence, fast response times, and a security team on standby.",
    },
    features: {
      id: [
        "Next-Gen Firewall (Fortinet/Palo Alto)",
        "IPS/IDS real-time protection",
        "Deep packet inspection",
        "VPN site-to-site & SSL VPN",
        "Web filtering & app control",
        "24/7 managed monitoring",
      ],
      en: [
        "Next-Gen Firewall (Fortinet/Palo Alto)",
        "IPS/IDS real-time protection",
        "Deep packet inspection",
        "Site-to-site VPN & SSL VPN",
        "Web filtering & app control",
        "24/7 managed monitoring",
      ],
    },
    startFrom: { id: "Hubungi kami untuk harga", en: "Contact us for pricing" },
    tags: { id: ["Enterprise Security", "Managed"], en: ["Enterprise Security", "Managed"] },
  },
  {
    id: "dcinterconnect",
    icon: Waypoints,
    title: { id: "DC to DC Connectivity", en: "DC-to-DC Connectivity" },
    tagline: {
      id: "Interkoneksi antar Data Center Layer 2 low-latency",
      en: "Low-latency Layer-2 interconnection between data centers",
    },
    short: {
      id: "Dedicated port Layer 2 antar DC untuk replikasi, DR, & hybrid infrastructure — latency intra-Jakarta < 5ms.",
      en: "Dedicated Layer-2 ports between DCs for replication, DR, and hybrid infrastructure — intra-Jakarta latency under 5ms.",
    },
    overview: {
      id: "DC to DC Connectivity adalah link dedicated Layer 2 yang menghubungkan dua atau lebih data center. Ideal untuk replikasi database real-time, disaster recovery site, hybrid cloud, dan multi-cloud architecture.",
      en: "DC-to-DC Connectivity is a dedicated Layer-2 link between two or more data centers. Ideal for real-time database replication, DR sites, hybrid cloud, and multi-cloud architectures.",
    },
    signals: {
      id: [
        "Butuh replikasi database real-time antar DC",
        "Membangun disaster recovery site di lokasi berbeda",
        "Menggabungkan private cloud + public cloud (hybrid)",
        "Sensitif terhadap latency & butuh performa konsisten",
      ],
      en: [
        "You need real-time DB replication between DCs",
        "You're building a DR site in a different location",
        "You're combining private + public cloud (hybrid)",
        "You're latency-sensitive and need consistent performance",
      ],
    },
    useCases: [
      { icon: Landmark, label: { id: "Perbankan (BCP / DRP)", en: "Banking (BCP / DRP)" } },
      { icon: Building2, label: { id: "Enterprise multi-DC", en: "Multi-DC enterprises" } },
      { icon: Zap, label: { id: "Real-time trading & payment", en: "Real-time trading & payments" } },
      { icon: ServerCog, label: { id: "Hybrid & multi-cloud setup", en: "Hybrid & multi-cloud setups" } },
    ],
    comparison: {
      id: "Dibanding VPN over internet, dedicated Layer 2 memberi latency lebih rendah, bandwidth stabil, dan keamanan lebih baik karena tidak melewati internet publik.",
      en: "Versus VPN over the internet, dedicated Layer-2 links give lower latency, steadier bandwidth, and stronger security by staying off the public internet.",
    },
    features: {
      id: [
        "Dedicated Port Layer 2 (EPL / EVPL)",
        "Interkoneksi antar Data Center",
        "Latency < 5ms intra-Jakarta",
        "Bandwidth 10Mbps – 10Gbps",
        "Redundant path opsional",
        "Exclude FO & UTP",
      ],
      en: [
        "Dedicated Layer-2 Port (EPL / EVPL)",
        "Data-center to data-center interconnection",
        "Latency < 5ms intra-Jakarta",
        "Bandwidth 10Mbps – 10Gbps",
        "Optional redundant path",
        "Excludes FO & UTP",
      ],
    },
    startFrom: { id: "Rp 500.000/bulan", en: "Rp 500,000/month" },
    tags: { id: ["Low-latency", "Layer 2"], en: ["Low-latency", "Layer 2"] },
  },
];

// ---------- PRICING CATALOG (bilingual only where text differs) ----------
const p = (idText, enText) => ({ id: idText, en: enText });

export const dedicatedTiers = [
  {
    id: "ded-8", name: p("Dedicated Server 8 Core", "Dedicated Server 8-Core"),
    price: "Rp 950.000", setup: p("Rp 250.000 setup fee", "Rp 250,000 setup fee"),
    items: {
      id: ["CPU 8 Core 16 Thread", "16GB RAM DDR4", "2 x 300GB SAS Storage", "Local Bandwidth Up to 1Gbps", "Global Bandwidth Up to 100Mbps", "1 IPv4"],
      en: ["CPU 8-core 16-thread", "16GB RAM DDR4", "2 x 300GB SAS storage", "Local bandwidth up to 1Gbps", "Global bandwidth up to 100Mbps", "1 IPv4"],
    },
    note: p("Minimum Kontrak 6 Bulan", "Minimum 6-month contract"),
  },
  {
    id: "ded-16", name: p("Dedicated Server 16 Core", "Dedicated Server 16-Core"),
    price: "Rp 1.580.000", setup: p("Rp 250.000 setup fee", "Rp 250,000 setup fee"),
    items: {
      id: ["CPU 16 Core 32 Thread", "32GB RAM DDR4", "2 x 600GB SAS Storage", "Local Bandwidth Up to 1Gbps", "Global Bandwidth Up to 100Mbps", "1 IPv4"],
      en: ["CPU 16-core 32-thread", "32GB RAM DDR4", "2 x 600GB SAS storage", "Local bandwidth up to 1Gbps", "Global bandwidth up to 100Mbps", "1 IPv4"],
    },
    note: p("Minimum Kontrak 6 Bulan", "Minimum 6-month contract"),
    featured: true,
  },
  {
    id: "ded-24", name: p("Dedicated Server 24 Core", "Dedicated Server 24-Core"),
    price: "Rp 2.750.000", setup: p("Rp 250.000 setup fee", "Rp 250,000 setup fee"),
    items: {
      id: ["CPU 24 Core 48 Thread", "32GB RAM DDR4", "2 x 600GB SAS Storage", "Local Bandwidth Up to 1Gbps", "Global Bandwidth Up to 100Mbps", "1 IPv4"],
      en: ["CPU 24-core 48-thread", "32GB RAM DDR4", "2 x 600GB SAS storage", "Local bandwidth up to 1Gbps", "Global bandwidth up to 100Mbps", "1 IPv4"],
    },
    note: p("Minimum Kontrak 6 Bulan", "Minimum 6-month contract"),
  },
  {
    id: "ded-32", name: p("Dedicated Server 32 Core", "Dedicated Server 32-Core"),
    price: "Rp 3.780.000", setup: p("Rp 250.000 setup fee", "Rp 250,000 setup fee"),
    items: {
      id: ["CPU 32 Core 64 Thread", "32GB RAM DDR4", "2 x 600GB SAS Storage", "Local Bandwidth Up to 1Gbps", "Global Bandwidth Up to 100Mbps", "1 IPv4"],
      en: ["CPU 32-core 64-thread", "32GB RAM DDR4", "2 x 600GB SAS storage", "Local bandwidth up to 1Gbps", "Global bandwidth up to 100Mbps", "1 IPv4"],
    },
    note: p("Minimum Kontrak 6 Bulan", "Minimum 6-month contract"),
  },
];

export const colocationTiers = [
  { id: "co-1u", name: p("1U - Server", "1U - Server"), price: "Rp 1.500.000",
    setup: p("Rp 250.000 setup fee", "Rp 250,000 setup fee"),
    items: {
      id: ["1Gbps Shared Local & CDN Bandwidth", "100Mbps Shared Global Bandwidth", "450 Watt Power Capacity", "1 IP Public", "Location Cyber 1 - Jakarta"],
      en: ["1Gbps shared local & CDN bandwidth", "100Mbps shared global bandwidth", "450 Watt power capacity", "1 public IP", "Location: Cyber 1 - Jakarta"],
    }},
  { id: "co-2u", name: p("2U - Server", "2U - Server"), price: "Rp 2.300.000",
    setup: p("Rp 250.000 setup fee", "Rp 250,000 setup fee"),
    items: {
      id: ["1Gbps Shared Local & CDN Bandwidth", "100Mbps Shared Global Bandwidth", "450 Watt Power Capacity", "1 IP Public", "Location Cyber 1 - Jakarta"],
      en: ["1Gbps shared local & CDN bandwidth", "100Mbps shared global bandwidth", "450 Watt power capacity", "1 public IP", "Location: Cyber 1 - Jakarta"],
    }},
  { id: "co-4u", name: p("4U - Server", "4U - Server"), price: "Rp 3.000.000",
    setup: p("Rp 250.000 setup fee", "Rp 250,000 setup fee"),
    items: {
      id: ["1Gbps Shared Local & CDN Bandwidth", "100Mbps Shared Global Bandwidth", "450 Watt Power Capacity", "5 IP Public", "Location Cyber 1 - Jakarta"],
      en: ["1Gbps shared local & CDN bandwidth", "100Mbps shared global bandwidth", "450 Watt power capacity", "5 public IPs", "Location: Cyber 1 - Jakarta"],
    }},
  { id: "co-5u", name: p("5U - Rack Space", "5U - Rack Space"), price: "Rp 3.500.000",
    setup: p("Rp 500.000 setup fee", "Rp 500,000 setup fee"),
    items: {
      id: ["1Gbps Shared Local & CDN Bandwidth", "100Mbps Shared Global Bandwidth", "550 Watt Power Capacity", "5 IP Public", "Location Cyber 1 - Jakarta"],
      en: ["1Gbps shared local & CDN bandwidth", "100Mbps shared global bandwidth", "550 Watt power capacity", "5 public IPs", "Location: Cyber 1 - Jakarta"],
    }, featured: true },
  { id: "co-10u", name: p("10U - Rack Space", "10U - Rack Space"), price: "Rp 5.550.000",
    setup: p("Rp 500.000 setup fee", "Rp 500,000 setup fee"),
    items: {
      id: ["1Gbps Shared Local & CDN Bandwidth", "150Mbps Shared Global Bandwidth", "750 Watt Power Capacity", "5 IP Public", "Location Cyber 1 - Jakarta"],
      en: ["1Gbps shared local & CDN bandwidth", "150Mbps shared global bandwidth", "750 Watt power capacity", "5 public IPs", "Location: Cyber 1 - Jakarta"],
    }},
  { id: "co-20u", name: p("20U / Half Rack", "20U / Half Rack"), price: "Rp 8.350.000",
    setup: p("Rp 500.000 setup fee", "Rp 500,000 setup fee"),
    items: {
      id: ["1Gbps Shared Local & CDN Bandwidth", "180Mbps Shared Global Bandwidth", "1000 Watt Power Capacity", "5 IP Public", "Location Cyber 1 - Jakarta"],
      en: ["1Gbps shared local & CDN bandwidth", "180Mbps shared global bandwidth", "1000 Watt power capacity", "5 public IPs", "Location: Cyber 1 - Jakarta"],
    }},
  { id: "co-40u", name: p("40U / Full Rack", "40U / Full Rack"), price: "Rp 15.500.000",
    setup: p("Rp 1.000.000 setup fee", "Rp 1,000,000 setup fee"),
    items: {
      id: ["1Gbps Shared Local & CDN Bandwidth", "200Mbps Shared Global Bandwidth", "2000 Watt Power Capacity", "13 IP Public", "Location Cyber 1 - Jakarta"],
      en: ["1Gbps shared local & CDN bandwidth", "200Mbps shared global bandwidth", "2000 Watt power capacity", "13 public IPs", "Location: Cyber 1 - Jakarta"],
    }},
  { id: "co-router", name: p("1U - Router/Switch (APJII)", "1U - Router/Switch (APJII)"), price: "Rp 2.500.000",
    setup: p("Rp 250.000 setup fee", "Rp 250,000 setup fee"),
    items: {
      id: ["Khusus Router & Switch", "250Mbps Shared Local Bandwidth", "50Mbps Shared Global Bandwidth", "Free BGP Session", "1 IP Public"],
      en: ["Router & switch only", "250Mbps shared local bandwidth", "50Mbps shared global bandwidth", "Free BGP session", "1 public IP"],
    }},
];

export const interconnectTiers = [
  { id: "ic-dc", name: p("DC Interconnect", "DC Interconnect"), price: "Rp 500.000",
    setup: p("Rp 350.000 setup fee", "Rp 350,000 setup fee"),
    items: {
      id: ["Interkoneksi Antar Data Center", "Dedicated Port (Layer 2)", "Exclude FO & UTP", "Minimum Kontrak 12 Bulan"],
      en: ["Data-center interconnection", "Dedicated Layer-2 port", "Excludes FO & UTP", "Minimum 12-month contract"],
    }},
  { id: "ic-remote-ix", name: p("Local Remote-IX", "Local Remote-IX"), price: "Rp 750.000",
    setup: p("Rp 250.000 setup fee", "Rp 250,000 setup fee"),
    items: {
      id: ["Terhubung ke Internet Exchange Anda mau", "Melalui Koneksi L2 Intercloud", "Delivered Direct to Customer Port", "Bandwidth mengikuti layanan saat ini", "Tersedia di APJII Cyber 1 & seluruh PoP Intercloud", "Available for: JKT-IX, BATAM-IX, CENTRO-IX, CXC, IIX, ATHARVA-IX"],
      en: ["Connect to any Internet Exchange you want", "Via Intercloud's L2 connection", "Delivered direct to customer port", "Bandwidth matches your current plan", "Available at APJII Cyber 1 & all Intercloud PoPs", "Available for: JKT-IX, BATAM-IX, CENTRO-IX, CXC, IIX, ATHARVA-IX"],
    },
    subtle: p("Biaya layanan Internet Exchange ditanggung pelanggan", "Internet Exchange service fees are borne by the customer"),
  },
  { id: "ic-bgp-domestik", name: p("BGP Session - Domestik", "BGP Session - Domestic"), price: "Rp 2.000.000",
    setup: p("Rp 500.000 setup fee", "Rp 500,000 setup fee"),
    items: {
      id: ["Unlimited Bandwidth", "Up to 1Gbps Local (OIXP, IIX, CXC, JKT-IX, Centro-IX, GPMIX, Metta-IX)", "SLA 99,5%", "Cross Connect @ APJII - Cyber 1"],
      en: ["Unlimited bandwidth", "Up to 1Gbps local (OIXP, IIX, CXC, JKT-IX, Centro-IX, GPMIX, Metta-IX)", "SLA 99.5%", "Cross connect @ APJII - Cyber 1"],
    },
    featured: true },
  { id: "ic-bgp-mix", name: p("BGP Session - Content Mix", "BGP Session - Content Mix"), price: "Rp 3.500.000",
    setup: p("Rp 500.000 setup fee", "Rp 500,000 setup fee"),
    items: {
      id: ["Unlimited Bandwidth", "Up to 1Gbps Local (OIXP, IIX, CXC, JKT-IX, Centro-IX, GPMIX)", "Up to 1Gbps Content (Meta, Akamai, CloudFlare, Alibaba, ByteDance)", "Up to 1Gbps GGC", "SLA 99,5%", "Cross Connect @ APJII - Cyber 1"],
      en: ["Unlimited bandwidth", "Up to 1Gbps local (OIXP, IIX, CXC, JKT-IX, Centro-IX, GPMIX)", "Up to 1Gbps content (Meta, Akamai, CloudFlare, Alibaba, ByteDance)", "Up to 1Gbps GGC", "SLA 99.5%", "Cross connect @ APJII - Cyber 1"],
    }},
  { id: "ic-bgp-sgix", name: p("BGP Session - SGIX", "BGP Session - SGIX"), price: "Rp 15.000.000",
    setup: p("Rp 1.000.000 setup fee", "Rp 1,000,000 setup fee"),
    items: {
      id: ["Unlimited Bandwidth", "Direct Connect to SGIX", "Up to 1Gbps SGIX Content", "SLA 99,5%", "Cross Connect @ APJII - Cyber 1"],
      en: ["Unlimited bandwidth", "Direct connect to SGIX", "Up to 1Gbps SGIX content", "SLA 99.5%", "Cross connect @ APJII - Cyber 1"],
    }},
];

// ---------- FAQ ----------
export const faqs = [
  {
    q: {
      id: "Apa itu Cloud Service dan siapa yang cocok memakainya?",
      en: "What is Cloud Service and who is it for?",
    },
    a: {
      id: "Cloud Service adalah infrastruktur komputasi virtual yang bisa dipakai on-demand, tanpa perlu investasi hardware fisik. Cocok untuk startup, software house, e-commerce, dan enterprise yang ingin scalable, cepat deploy, dan bayar sesuai pemakaian. Layanan cloud Intercloud mencakup Public, Private, dan Hybrid Cloud dengan SLA 99,5%.",
      en: "Cloud Service is on-demand virtual compute infrastructure — no physical hardware investment needed. Ideal for startups, software houses, e-commerce, and enterprises that want to scale, deploy quickly, and pay for what they use. Intercloud's cloud covers Public, Private, and Hybrid Cloud with a 99.5% SLA.",
    },
  },
  {
    q: {
      id: "Apa perbedaan Web Hosting, VPS, dan Dedicated Server?",
      en: "What's the difference between Web Hosting, VPS, and Dedicated Server?",
    },
    a: {
      id: "Web Hosting berbagi resource dengan pengguna lain (shared) — cocok untuk website skala kecil-menengah. VPS memberi resource terisolasi dengan full-root access untuk aplikasi custom. Dedicated Server adalah server fisik penuh khusus untuk Anda — performa maksimal untuk database berat, gaming, atau aplikasi mission-critical.",
      en: "Web Hosting shares resources with other users (shared) — ideal for small-to-mid websites. VPS provides isolated resources with full root access for custom applications. A Dedicated Server is a full physical server exclusively for you — peak performance for heavy databases, gaming, or mission-critical apps.",
    },
  },
  {
    q: {
      id: "Kapan sebaiknya bisnis migrasi ke Dedicated Server?",
      en: "When should a business migrate to a Dedicated Server?",
    },
    a: {
      id: "Beberapa tanda bisnis Anda perlu Dedicated Server: (1) website/aplikasi sering lambat, (2) trafik pengguna terus meningkat, (3) butuh resource server khusus, (4) mengelola aplikasi mission-critical perusahaan, atau (5) butuh kontrol server yang lebih fleksibel. Dedicated Server memberi ruang lebih besar untuk performa, keamanan, dan pengelolaan teknis.",
      en: "Signs you need a Dedicated Server: (1) your site/app is often slow, (2) user traffic keeps growing, (3) you need dedicated server resources, (4) you run mission-critical apps, or (5) you need more flexible server control. A Dedicated Server gives more room for performance, security, and technical management.",
    },
  },
  {
    q: {
      id: "Bagaimana cara kerja layanan Colocation?",
      en: "How does the Colocation service work?",
    },
    a: {
      id: "Anda memiliki server fisik sendiri, kami menyediakan tempatnya. Server Anda kami tempatkan di rack data center bersertifikasi Tier III yang memiliki power redundant N+1, presisi cooling, fire suppression, keamanan biometric 24/7, serta konektivitas premium multi-upstream. Anda cukup fokus pada aplikasi, kami urus infrastrukturnya.",
      en: "You own the physical server; we provide the location. We place your server in a Tier III certified data-center rack with N+1 redundant power, precision cooling, fire suppression, biometric 24/7 security, and premium multi-upstream connectivity. You focus on applications — we handle the infrastructure.",
    },
  },
  {
    q: {
      id: "Apa keunggulan Firewall Solution dari Intercloud?",
      en: "What makes Intercloud's Firewall Solution stand out?",
    },
    a: {
      id: "Kami menggunakan Next-Generation Firewall dari brand enterprise (Fortinet, Palo Alto, Sophos) dengan fitur IPS/IDS real-time, deep packet inspection, web filtering, application control, hingga SSL VPN. Semua di-manage 24/7 oleh tim security engineer kami sehingga Anda tidak perlu memikirkan konfigurasi & update.",
      en: "We use Next-Generation Firewalls from enterprise brands (Fortinet, Palo Alto, Sophos) with real-time IPS/IDS, deep packet inspection, web filtering, application control, and SSL VPN. Everything is managed 24/7 by our security engineers — you don't have to worry about configuration or updates.",
    },
  },
  {
    q: {
      id: "Apa itu DC to DC Connectivity dan kapan dibutuhkan?",
      en: "What is DC-to-DC Connectivity and when do you need it?",
    },
    a: {
      id: "DC to DC Connectivity (Data Center Interconnect) adalah link dedicated Layer 2 yang menghubungkan dua atau lebih data center. Dibutuhkan untuk replikasi database real-time, disaster recovery, hybrid cloud architecture, atau menghubungkan private cloud Anda dengan cloud provider lain (multi-cloud). Latency intra-Jakarta bisa di bawah 5ms.",
      en: "DC-to-DC Connectivity (Data Center Interconnect) is a dedicated Layer-2 link between two or more data centers. It's used for real-time database replication, disaster recovery, hybrid cloud architecture, or linking your private cloud with another cloud provider (multi-cloud). Intra-Jakarta latency can go below 5ms.",
    },
  },
  {
    q: {
      id: "Berapa lama proses aktivasi layanan?",
      en: "How long does service activation take?",
    },
    a: {
      id: "VPS & Cloud aktif dalam 15–30 menit setelah pembayaran. Dedicated Server dalam 1–3 hari kerja. Colocation & DC Interconnect membutuhkan survey teknis 2–5 hari kerja tergantung kompleksitas. Firewall Solution & Lease to Own biasanya 3–7 hari kerja setelah kontrak ditandatangani.",
      en: "VPS & Cloud activate within 15–30 minutes after payment. Dedicated Server in 1–3 business days. Colocation & DC Interconnect require a 2–5 business-day technical survey depending on complexity. Firewall Solution & Lease-to-Own usually take 3–7 business days after the contract is signed.",
    },
  },
  {
    q: {
      id: "Bagaimana skema Lease to Own Appliance?",
      en: "How does the Lease-to-Own Appliance work?",
    },
    a: {
      id: "Anda menyewa hardware enterprise (server, router, firewall, switch) dari brand ternama seperti Dell, HP, Cisco, Mikrotik dengan skema cicilan 12/24/36 bulan. Sudah termasuk instalasi, konfigurasi, sparepart & maintenance. Di akhir masa kontrak, hardware bisa menjadi milik Anda tanpa biaya tambahan.",
      en: "You lease enterprise hardware (server, router, firewall, switch) from leading brands like Dell, HP, Cisco, Mikrotik on a 12/24/36-month installment plan. Installation, configuration, spare parts and maintenance are included. At contract end, the hardware becomes yours at no extra cost.",
    },
  },
  {
    q: {
      id: "Bagaimana cara menghubungi tim support?",
      en: "How do I contact your support team?",
    },
    a: {
      id: "Tim support kami siap 24/7 melalui WhatsApp di +62 878-1239-7187, email support@intercloud-digital.com, atau telepon langsung ke kantor kami di Menara Cakrawala Jakarta. Response time rata-rata < 15 menit untuk isu critical.",
      en: "Our support team is available 24/7 via WhatsApp at +62 878-1239-7187, email support@intercloud-digital.com, or call our office at Menara Cakrawala Jakarta. Average response time is under 15 minutes for critical issues.",
    },
  },
];

// ---------- PARTNERS ----------
// Real clients & partners of PT Intercloud Digital Inovasi.
// Logos are pulled from Google's favicon CDN at 128px — reliable for small
// Indonesian ISPs & startups that don't have hosted vector logos.
// Instagram-only brands fall back to an initials badge (no `domain`).
export const partners = [
  { name: "Atharva",     domain: "atharva.co.id",   href: "https://www.atharva.co.id/" },
  { name: "Hayat",       domain: "hayat.net.id",    href: "https://hayat.net.id/" },
  { name: "Erka Fiber",  domain: null,              href: "https://www.instagram.com/erka_fiber" },
  { name: "Jabnet",      domain: "jabnet.id",       href: "https://www.jabnet.id/" },
  { name: "JMC Net",     domain: "jmcnet.id",       href: "https://www.jmcnet.id/" },
  { name: "Hanoman",     domain: "hanoman.id",      href: "https://hanoman.id/" },
  { name: "Rameza",      domain: "rameza.id",       href: "https://rameza.id/" },
  { name: "Link Net",    domain: "linknet.co.id",   href: "https://linknet.co.id/id" },
  { name: "Mizora",      domain: "mizora.jewelry",  href: "https://mizora.jewelry/" },
  { name: "Fusena",      domain: "fusena.net.id",   href: "http://fusena.net.id/" },
  { name: "Jelajah ID",  domain: "jelajahid.id",    href: "https://jelajahid.id/" },
  { name: "Aminco JP",   domain: null,              href: "https://www.instagram.com/amincojp" },
  { name: "IWS Net",     domain: "iwsnet.id",       href: "https://www.iwsnet.id/" },
  { name: "VT Net",      domain: "vtnet.id",        href: "https://www.vtnet.id/" },
];
