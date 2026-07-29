import React, { useState } from "react";
import { Send, CheckCircle2, Loader2 } from "lucide-react";
import { useLang } from "../i18n/LanguageContext";
import { api } from "../portal/api";
import { getRecaptchaToken } from "../portal/recaptcha";

const TXT = {
  id: {
    tag: "Konsultasi Gratis",
    title_a: "Ceritakan kebutuhan Anda,",
    title_b: "tim kami yang urus sisanya.",
    body: "Isi form singkat ini dan tim solusi kami akan menghubungi Anda dalam 1x24 jam kerja.",
    name: "Nama lengkap",
    email: "Email kerja",
    company: "Perusahaan",
    phone: "No. WhatsApp",
    need: "Layanan yang diminati",
    needs: ["Cloud / VPS", "Dedicated Server", "Colocation", "Interconnect & BGP", "Web Hosting & Domain", "Lainnya"],
    message: "Ceritakan kebutuhan Anda",
    submit: "Kirim Permintaan",
    sending: "Mengirim...",
    success_t: "Permintaan terkirim!",
    success_b: "Terima kasih. Tim kami akan menghubungi Anda maksimal 1x24 jam kerja.",
    again: "Kirim permintaan lain",
  },
  en: {
    tag: "Free Consultation",
    title_a: "Tell us what you need,",
    title_b: "our team handles the rest.",
    body: "Fill in this short form and our solution team will reach out within 1 business day.",
    name: "Full name",
    email: "Work email",
    company: "Company",
    phone: "WhatsApp number",
    need: "Service of interest",
    needs: ["Cloud / VPS", "Dedicated Server", "Colocation", "Interconnect & BGP", "Web Hosting & Domain", "Other"],
    message: "Tell us about your needs",
    submit: "Send Request",
    sending: "Sending...",
    success_t: "Request sent!",
    success_b: "Thank you. Our team will contact you within 1 business day.",
    again: "Send another request",
  },
};

const inputCls = "w-full rounded-xl border border-slate-300 bg-white px-4 py-3 text-sm text-[#0a2350] placeholder:text-slate-400 focus:outline-none focus:border-[#f5b120] focus:ring-4 focus:ring-[#f5b120]/15 transition-colors";
const labelCls = "block text-xs font-bold uppercase tracking-widest text-slate-500 mb-1.5";

const LeadForm = () => {
  const { lang } = useLang();
  const t = TXT[lang] || TXT.id;
  const [f, setF] = useState({ name: "", email: "", company: "", phone: "", need: "", message: "" });
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState(false);
  const [err, setErr] = useState("");

  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true); setErr("");
    try {
      let token = null;
      try { token = await getRecaptchaToken("lead"); } catch { token = null; }
      await api.post("/portal-public/leads", {
        name: f.name, email: f.email, phone: f.phone, company: f.company,
        need: f.need, message: f.message, source: "landing", recaptcha_token: token,
      });
      setSent(true);
    } catch (er) {
      setErr(er?.response?.data?.detail || (lang === "en" ? "Failed to send. Please retry." : "Gagal mengirim. Silakan coba lagi."));
    } finally { setBusy(false); }
  };

  return (
    <section id="lead" className="py-24 bg-slate-50">
      <div className="max-w-7xl mx-auto px-5 lg:px-8 grid lg:grid-cols-12 gap-12 items-start">
        <div className="lg:col-span-5">
          <div className="text-xs font-bold uppercase tracking-[0.2em] text-[#f5b120]">{t.tag}</div>
          <h2 className="mt-3 text-3xl md:text-4xl font-extrabold text-[#0a2350] leading-tight">
            {t.title_a} <span className="text-[#f5b120]">{t.title_b}</span>
          </h2>
          <div className="mt-4 h-1 w-14 rounded-full bg-[#f5b120]" />
          <p className="mt-5 text-slate-600 leading-relaxed max-w-md">{t.body}</p>
        </div>

        <div className="lg:col-span-7">
          {sent ? (
            <div className="rounded-3xl bg-white border border-emerald-200 p-10 text-center shadow-sm" data-testid="lead-success">
              <div className="h-14 w-14 mx-auto rounded-full bg-emerald-100 flex items-center justify-center">
                <CheckCircle2 className="h-8 w-8 text-emerald-600" />
              </div>
              <h3 className="mt-4 text-xl font-extrabold text-[#0a2350]">{t.success_t}</h3>
              <p className="mt-2 text-sm text-slate-600">{t.success_b}</p>
              <button
                className="mt-5 text-sm font-bold text-[#0a2350] hover:text-[#f5b120] transition-colors"
                onClick={() => { setSent(false); setF({ name: "", email: "", company: "", phone: "", need: "", message: "" }); }}
                data-testid="lead-again"
              >
                {t.again}
              </button>
            </div>
          ) : (
            <form onSubmit={submit} className="rounded-3xl bg-white border border-slate-200 p-6 md:p-8 shadow-sm" data-testid="lead-form">
              {err && (
                <div className="mb-4 rounded-xl bg-red-50 border border-red-200 text-red-700 text-sm px-4 py-3" data-testid="lead-error">
                  {err}
                </div>
              )}
              <div className="grid sm:grid-cols-2 gap-4">
                <label><span className={labelCls}>{t.name} *</span>
                  <input required className={inputCls} value={f.name} onChange={set("name")} data-testid="lead-name" /></label>
                <label><span className={labelCls}>{t.email} *</span>
                  <input required type="email" className={inputCls} value={f.email} onChange={set("email")} data-testid="lead-email" /></label>
                <label><span className={labelCls}>{t.company}</span>
                  <input className={inputCls} value={f.company} onChange={set("company")} data-testid="lead-company" /></label>
                <label><span className={labelCls}>{t.phone} *</span>
                  <input required className={inputCls} value={f.phone} onChange={set("phone")} placeholder="08xxxxxxxxxx" data-testid="lead-phone" /></label>
                <label className="sm:col-span-2"><span className={labelCls}>{t.need} *</span>
                  <select required className={inputCls} value={f.need} onChange={set("need")} data-testid="lead-need">
                    <option value="" disabled>-</option>
                    {t.needs.map((n) => <option key={n} value={n}>{n}</option>)}
                  </select></label>
                <label className="sm:col-span-2"><span className={labelCls}>{t.message}</span>
                  <textarea rows={3} className={inputCls} value={f.message} onChange={set("message")} data-testid="lead-message" /></label>
              </div>
              <button
                type="submit"
                disabled={busy}
                className="mt-6 inline-flex items-center gap-2 rounded-full bg-[#0a2350] hover:bg-[#0d2c63] text-white px-7 py-3.5 text-sm font-semibold transition-colors disabled:opacity-60"
                data-testid="lead-submit"
              >
                {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
                {busy ? t.sending : t.submit}
              </button>
            </form>
          )}
        </div>
      </div>
    </section>
  );
};

export default LeadForm;
