import React, { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import axios from "axios";
import { getRecaptchaToken } from "../portal/recaptcha";
import { CheckCircle2, Loader2 } from "lucide-react";

const API = `${process.env.REACT_APP_BACKEND_URL}/api/portal`;

export default function PublicForm() {
  const { slug } = useParams();
  const [cfg, setCfg] = useState(null);
  const [err, setErr] = useState("");
  const [values, setValues] = useState({});
  const [fieldErrs, setFieldErrs] = useState({});
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState("");

  useEffect(() => {
    axios.get(`${API}/portal-public/forms/${slug}`)
      .then((r) => setCfg(r.data))
      .catch(() => setErr("Form tidak ditemukan atau sudah nonaktif."));
  }, [slug]);

  const set = (k, v) => { setValues((p) => ({ ...p, [k]: v })); setFieldErrs((p) => ({ ...p, [k]: null })); };

  const validate = () => {
    const es = {};
    for (const f of cfg.fields) {
      const v = values[f.key];
      if (f.required && (v === undefined || v === "" || v === false)) es[f.key] = `${f.label} wajib diisi`;
      else if (v && f.type === "email" && !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(v)) es[f.key] = "Format email tidak valid";
      else if (v && f.type === "phone" && !/^[0-9+()\-\s]{7,20}$/.test(v)) es[f.key] = "Format nomor telepon tidak valid";
    }
    setFieldErrs(es);
    return Object.keys(es).length === 0;
  };

  const submit = async (e) => {
    e.preventDefault();
    if (!validate()) return;
    setBusy(true); setErr("");
    try {
      const recaptcha_token = await getRecaptchaToken("lead").catch(() => null);
      const r = await axios.post(`${API}/portal-public/forms/${slug}/submit`, { ...values, recaptcha_token });
      setDone(r.data.message);
    } catch (er) {
      const d = er?.response?.data?.detail;
      if (d && d.errors) setFieldErrs(d.errors);
      else setErr(typeof d === "string" ? d : "Gagal mengirim, coba lagi.");
    } finally { setBusy(false); }
  };

  if (err && !cfg) return <Shell><div className="text-center text-slate-500 py-16" data-testid="public-form-error">{err}</div></Shell>;
  if (!cfg) return <Shell><div className="text-center py-16"><Loader2 className="h-6 w-6 animate-spin mx-auto text-[#f5b120]" /></div></Shell>;
  if (done) return (
    <Shell>
      <div className="text-center py-14" data-testid="public-form-success">
        <CheckCircle2 className="h-14 w-14 text-emerald-500 mx-auto" />
        <h2 className="mt-4 text-2xl font-extrabold text-[#0a2350]">Terkirim!</h2>
        <p className="mt-2 text-slate-500">{done}</p>
      </div>
    </Shell>
  );

  const inputCls = "w-full h-11 rounded-xl border border-slate-300 px-3 text-sm focus:outline-none focus:ring-2 focus:ring-[#f5b120] focus:border-[#f5b120] bg-white";

  return (
    <Shell>
      <form onSubmit={submit} noValidate data-testid="public-form">
        <h1 className="text-2xl sm:text-3xl font-extrabold text-[#0a2350]">{cfg.title}</h1>
        {cfg.description && <p className="mt-2 text-slate-500 text-sm">{cfg.description}</p>}
        {err && <div className="mt-4 text-sm text-red-700 bg-red-50 border border-red-200 rounded-xl px-3 py-2">{err}</div>}
        <div className="mt-6 space-y-4">
          {cfg.fields.map((f) => (
            <div key={f.key}>
              <label className="block text-xs font-bold uppercase tracking-widest text-slate-500 mb-1.5">
                {f.label}{f.required && <span className="text-red-500"> *</span>}
              </label>
              {f.type === "textarea" ? (
                <textarea rows={4} value={values[f.key] || ""} onChange={(e) => set(f.key, e.target.value)}
                  placeholder={f.placeholder} className={`${inputCls} h-auto py-2.5`} data-testid={`pf-${f.key}`} />
              ) : f.type === "select" ? (
                <select value={values[f.key] || ""} onChange={(e) => set(f.key, e.target.value)} className={inputCls} data-testid={`pf-${f.key}`}>
                  <option value="">Pilih...</option>
                  {(f.options || []).map((o) => <option key={o} value={o}>{o}</option>)}
                </select>
              ) : f.type === "checkbox" ? (
                <label className="flex items-center gap-2 text-sm text-slate-600">
                  <input type="checkbox" checked={!!values[f.key]} onChange={(e) => set(f.key, e.target.checked)} data-testid={`pf-${f.key}`} />
                  {f.placeholder || f.label}
                </label>
              ) : (
                <input type={f.type === "number" ? "number" : "text"} value={values[f.key] || ""}
                  onChange={(e) => set(f.key, e.target.value)} placeholder={f.placeholder}
                  className={inputCls} data-testid={`pf-${f.key}`} />
              )}
              {fieldErrs[f.key] && <div className="mt-1 text-xs text-red-600" data-testid={`pf-err-${f.key}`}>{fieldErrs[f.key]}</div>}
            </div>
          ))}
        </div>
        <button type="submit" disabled={busy} data-testid="pf-submit"
          className="mt-6 w-full h-12 rounded-xl bg-[#0a2350] hover:bg-[#f5b120] hover:text-[#0a2350] text-white font-bold text-sm transition-colors inline-flex items-center justify-center gap-2 disabled:opacity-60">
          {busy && <Loader2 className="h-4 w-4 animate-spin" />} {cfg.submit_label}
        </button>
        <div className="mt-3 text-center text-[10px] text-slate-400">Dilindungi reCAPTCHA · Intercloud Digital Inovasi</div>
      </form>
    </Shell>
  );
}

const Shell = ({ children }) => (
  <div className="min-h-screen bg-slate-50 flex items-center justify-center p-4">
    <div className="w-full max-w-lg bg-white rounded-3xl shadow-xl border border-slate-200 p-8 md:p-10">
      {children}
    </div>
  </div>
);
