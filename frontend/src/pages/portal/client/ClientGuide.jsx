import React, { useEffect, useState } from "react";
import { api } from "../../../portal/api";
import { PageHeader, Card, Loading } from "../ui";
import { ChevronDown, BookOpen, Lightbulb } from "lucide-react";

const FALLBACK_GUIDES = [
  {
    key: "order",
    title: "Cara Order Layanan",
    excerpt: "Pesan VPS, hosting, domain, atau layanan lain langsung dari portal. Invoice terbit otomatis setelah checkout.",
    steps: [
      "Buka menu Order Service di sidebar kiri.",
      "Pilih kategori dan produk yang diinginkan, lalu tentukan paket / spesifikasi.",
      "Tambahkan add-on bila perlu (IP tambahan, backup, dll), lalu periksa ringkasan harga.",
      "Klik Checkout. Invoice akan otomatis terbit dan muncul di menu Invoices.",
      "Setelah invoice dibayar, layanan diproses otomatis. Status bisa dipantau di My Services.",
    ],
    tip: "Butuh penawaran khusus atau spesifikasi custom? Buka tiket ke tim Sales, kami siapkan quotation untuk Anda.",
  },
  {
    key: "invoice",
    title: "Cara Membayar Invoice",
    excerpt: "Pembayaran diproses otomatis melalui payment gateway Duitku: Virtual Account, QRIS, e-wallet, dan retail.",
    steps: [
      "Buka menu Invoices, pilih invoice berstatus Unpaid.",
      "Klik tombol Bayar / Pay Now pada detail invoice.",
      "Pilih metode pembayaran (Virtual Account bank, QRIS, e-wallet, atau gerai retail).",
      "Selesaikan pembayaran sesuai instruksi. Status invoice berubah menjadi Paid secara otomatis (biasanya kurang dari 5 menit).",
      "Kuitansi / bukti pembayaran dapat diunduh dalam format PDF dari detail invoice.",
    ],
    tip: "Invoice perpanjangan terbit otomatis sebelum tanggal jatuh tempo layanan. Aktifkan notifikasi email agar tidak terlewat.",
  },
  {
    key: "ticket",
    title: "Cara Membuka Tiket Support",
    excerpt: "Tim support kami siap membantu kendala teknis, billing, maupun pertanyaan umum melalui sistem tiket.",
    steps: [
      "Buka menu Tickets, lalu klik New Ticket.",
      "Pilih layanan terkait (bila ada) dan tentukan prioritas sesuai dampak masalah.",
      "Tulis judul singkat dan jelaskan masalah selengkap mungkin: pesan error, waktu kejadian, langkah yang sudah dicoba.",
      "Kirim tiket. Balasan tim support akan muncul di halaman tiket dan dikirim ke email Anda.",
      "Balas di tiket yang sama untuk diskusi lanjutan. Tutup tiket bila masalah sudah selesai.",
    ],
    tip: "Semakin lengkap informasi awal (screenshot, log, IP), semakin cepat tim kami menemukan solusinya.",
  },
  {
    key: "account",
    title: "Keamanan Akun & Profil",
    excerpt: "Lindungi akun Anda dan lengkapi data perusahaan agar invoice dan faktur pajak akurat.",
    steps: [
      "Lengkapi profil perusahaan dan NPWP melalui menu profil agar data invoice benar.",
      "Aktifkan 2FA (autentikasi dua langkah) untuk keamanan login ekstra.",
      "Ganti password secara berkala melalui menu Settings > Change Password.",
      "Jangan bagikan kredensial akun. Semua aktivitas penting tercatat di sistem kami.",
    ],
    tip: "Lupa password? Gunakan tautan Forgot Password di halaman login, tautan reset dikirim ke email terdaftar.",
  },
];

const GuideSection = ({ guide, open, onToggle }) => {
  const [body, setBody] = useState(null);
  const [loadingBody, setLoadingBody] = useState(false);

  useEffect(() => {
    if (open && guide.slug && body === null) {
      setLoadingBody(true);
      api.get(`/public/articles/${guide.slug}`)
        .then((r) => setBody(r.data?.article?.body_html || ""))
        .catch(() => setBody(""))
        .finally(() => setLoadingBody(false));
    }
  }, [open, guide.slug, body]);

  return (
    <Card className="p-0 overflow-hidden" data-testid={`guide-section-${guide.id || guide.key}`}>
      <button
        type="button"
        onClick={onToggle}
        data-testid={`guide-toggle-${guide.id || guide.key}`}
        className="w-full flex items-center gap-3 px-5 py-4 text-left hover:bg-slate-50 transition-colors"
      >
        <span className="h-10 w-10 rounded-xl bg-[#0a2350] flex items-center justify-center shrink-0">
          <BookOpen className="h-5 w-5 text-[#f5b120]" />
        </span>
        <span className="flex-1">
          <span className="block font-bold text-[#0a2350]">{guide.title}</span>
          <span className="block text-xs text-slate-500 mt-0.5">{guide.excerpt || guide.intro}</span>
        </span>
        <ChevronDown className={`h-5 w-5 text-slate-400 transition-transform ${open ? "rotate-180" : ""}`} />
      </button>
      {open && (
        <div className="px-5 pb-5 pt-1 border-t border-slate-100">
          {guide.steps ? (
            <ol className="space-y-3 mt-4">
              {guide.steps.map((s, i) => (
                <li key={i} className="flex items-start gap-3 text-sm text-slate-700">
                  <span className="h-6 w-6 rounded-full bg-[#f5b120]/15 text-[#0a2350] font-bold text-xs flex items-center justify-center shrink-0 mt-0.5">
                    {i + 1}
                  </span>
                  <span className="leading-relaxed">{s}</span>
                </li>
              ))}
            </ol>
          ) : loadingBody ? (
            <div className="mt-4 text-sm text-slate-400">Loading…</div>
          ) : body ? (
            <div
              className="mt-4 prose prose-sm max-w-none text-slate-700"
              dangerouslySetInnerHTML={{ __html: body }}
            />
          ) : (
            <div className="mt-4 text-sm text-slate-500 italic">No content available.</div>
          )}
          {guide.tip && (
            <div className="mt-4 flex items-start gap-2 rounded-xl bg-amber-50 border border-amber-200 px-4 py-3 text-xs text-amber-800">
              <Lightbulb className="h-4 w-4 mt-0.5 shrink-0" />
              <span>{guide.tip}</span>
            </div>
          )}
        </div>
      )}
    </Card>
  );
};

const ClientGuide = () => {
  const [guides, setGuides] = useState(null);
  const [open, setOpen] = useState("");

  useEffect(() => {
    api.get("/public/articles?type=kb&limit=50")
      .then((r) => {
        const kbArticles = (r.data?.results || []).filter((a) => a.status === "published");
        if (kbArticles.length > 0) {
          setGuides(kbArticles);
          setOpen(kbArticles[0].id);
        } else {
          setGuides(FALLBACK_GUIDES);
          setOpen(FALLBACK_GUIDES[0].key);
        }
      })
      .catch(() => {
        setGuides(FALLBACK_GUIDES);
        setOpen(FALLBACK_GUIDES[0].key);
      });
  }, []);

  if (!guides) return <Loading />;

  return (
    <div data-testid="client-guide-page">
      <PageHeader
        title="Panduan"
        subtitle="Knowledge base: panduan penggunaan layanan Intercloud. Diambil dari artikel KB yang selalu diperbarui."
      />
      <div className="flex items-center gap-2 mb-5 text-xs text-slate-500">
        <BookOpen className="h-4 w-4 text-[#f5b120]" />
        Klik setiap topik untuk melihat isinya.
      </div>
      <div className="space-y-3 max-w-3xl">
        {guides.map((g) => (
          <GuideSection
            key={g.id || g.key}
            guide={g}
            open={open === (g.id || g.key)}
            onToggle={() => setOpen(open === (g.id || g.key) ? "" : (g.id || g.key))}
          />
        ))}
      </div>
    </div>
  );
};

export default ClientGuide;