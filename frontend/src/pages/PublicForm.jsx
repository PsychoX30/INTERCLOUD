import React, { useEffect, useMemo, useState } from "react";
import { useParams } from "react-router-dom";
import axios from "axios";
import { getRecaptchaToken } from "../portal/recaptcha";
import { CheckCircle2, Loader2, Lock } from "lucide-react";

const API = `${process.env.REACT_APP_BACKEND_URL}/api/portal`;

const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]{2,}$/;
const PHONE_RE = /^[0-9+()\-\s]{7,20}$/;
const URL_RE = /^https?:\/\/[^\s.]+\.[^\s]+$/i;
const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;
const TIME_RE = /^\d{2}:\d{2}(:\d{2})?$/;

/** Initial form state derived from the field defaults the builder saved. */
const initialValues = (fields) => {
  const out = {};
  for (const f of fields || []) {
    if (f.type === "section") continue;
    const d = f.default;
    if (f.type === "checkbox") out[f.key] = !!d;
    else if (f.type === "multiselect") out[f.key] = Array.isArray(d) ? [...d] : [];
    else if (f.type === "rating") out[f.key] = d === "" || d == null ? null : Number(d);
    else out[f.key] = d == null ? "" : String(d);
  }
  return out;
};

/** Client-side mirror of `_fb_validate_submission` for instant feedback. */
const validate = (fields, values) => {
  const es = {};
  for (const f of fields || []) {
    if (f.type === "section") continue;
    const v = values[f.key];
    const label = f.label || f.key;
    const empty =
      f.type === "checkbox" ? !v
        : f.type === "multiselect" ? !v || v.length === 0
          : f.type === "rating" ? v == null || v === ""
            : v === undefined || v === null || String(v).trim() === "";
    if (f.required && empty) { es[f.key] = `${label} wajib diisi`; continue; }
    if (empty) continue;
    if (f.type === "email" && !EMAIL_RE.test(String(v))) es[f.key] = "Format email tidak valid";
    else if (f.type === "phone" && !PHONE_RE.test(String(v))) es[f.key] = "Format nomor telepon tidak valid";
    else if (f.type === "number") {
      const n = Number(v);
      if (Number.isNaN(n)) es[f.key] = "Harus berupa angka";
      else if (f.min != null && n < f.min) es[f.key] = `Nilai minimum ${f.min}`;
      else if (f.max != null && n > f.max) es[f.key] = `Nilai maksimum ${f.max}`;
    } else if (f.type === "rating") {
      const n = Number(v);
      const top = f.rating_max || 5;
      if (!Number.isFinite(n) || n < 1 || n > top) es[f.key] = `Rating harus antara 1 dan ${top}`;
    } else if (f.type === "url" && !URL_RE.test(String(v))) es[f.key] = "URL harus diawali http:// atau https://";
    else if (f.type === "date" && !DATE_RE.test(String(v))) es[f.key] = "Format tanggal harus YYYY-MM-DD";
    else if (f.type === "time" && !TIME_RE.test(String(v))) es[f.key] = "Format jam harus HH:MM";
    else if (f.max != null && (f.type === "text" || f.type === "textarea") && String(v).length > f.max)
      es[f.key] = `Maksimum ${f.max} karakter`;
  }
  return es;
};

export default function PublicForm() {
  const { slug: identifier } = useParams();
  const [cfg, setCfg] = useState(null);
  const [err, setErr] = useState("");
  const [values, setValues] = useState({});
  const [fieldErrs, setFieldErrs] = useState({});
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState("");

  useEffect(() => {
    axios.get(`${API}/portal-public/forms/${identifier}`)
      .then((r) => {
        setCfg(r.data);
        setValues(initialValues(r.data.fields));
      })
      .catch(() => setErr("Form tidak ditemukan atau sudah nonaktif."));
  }, [identifier]);

  const set = (k, v) => {
    setValues((p) => ({ ...p, [k]: v }));
    setFieldErrs((p) => ({ ...p, [k]: null }));
  };

  const toggleMulti = (key, option) => {
    setValues((p) => {
      const cur = Array.isArray(p[key]) ? p[key] : [];
      const next = cur.includes(option) ? cur.filter((x) => x !== option) : [...cur, option];
      return { ...p, [key]: next };
    });
    setFieldErrs((p) => ({ ...p, [key]: null }));
  };

  const closedReason = cfg?.closed_reason || "";
  const visibleFields = useMemo(() => (cfg?.fields || []), [cfg]);

  const submit = async (e) => {
    e.preventDefault();
    if (closedReason) return;
    const es = validate(visibleFields, values);
    if (Object.keys(es).length) { setFieldErrs(es); return; }
    setBusy(true); setErr("");
    try {
      const recaptcha_token = await getRecaptchaToken("lead").catch(() => null);
      const r = await axios.post(`${API}/portal-public/forms/${identifier}/submit`,
        { ...values, recaptcha_token });
      setDone(r.data.message);
    } catch (er) {
      const d = er?.response?.data?.detail;
      if (d && d.errors) setFieldErrs(d.errors);
      else setErr(typeof d === "string" ? d : "Gagal mengirim, coba lagi.");
    } finally { setBusy(false); }
  };

  if (err && !cfg) return <Shell><div className="text-center text-slate-500 py-16" data-testid="public-form-error">{err}</div></Shell>;
  if (!cfg) return <Shell><div className="text-center py-16"><Loader2 className="h-6 w-6 animate-spin mx-auto text-[#f5b120]" /></div></Shell>;

  if (closedReason) return (
    <Shell>
      <div className="text-center py-14" data-testid="public-form-closed">
        <Lock className="h-14 w-14 text-slate-400 mx-auto" />
        <h2 className="mt-4 text-2xl font-extrabold text-[#0a2350]">{cfg.title || cfg.name}</h2>
        <p className="mt-2 text-slate-500">{closedReason}</p>
      </div>
    </Shell>
  );

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
  const labelCls = "block text-xs font-bold uppercase tracking-widest text-slate-500 mb-1.5";

  return (
    <Shell>
      <form onSubmit={submit} noValidate data-testid="public-form">
        <h1 className="text-2xl sm:text-3xl font-extrabold text-[#0a2350]">{cfg.title}</h1>
        {cfg.description && <p className="mt-2 text-slate-500 text-sm">{cfg.description}</p>}
        {err && <div className="mt-4 text-sm text-red-700 bg-red-50 border border-red-200 rounded-xl px-3 py-2">{err}</div>}
        <div className="mt-6 space-y-4">
          {visibleFields.map((f, idx) => (
            <div key={`${f.key}-${idx}`}>
              {f.type === "section" ? (
                <div className="pt-4 pb-1 border-t border-slate-200 first:border-0 first:pt-0" data-testid={`pf-section-${idx}`}>
                  <div className="text-base font-extrabold text-[#0a2350]">{f.label}</div>
                  {f.help && <p className="mt-0.5 text-xs text-slate-500">{f.help}</p>}
                </div>
              ) : (
                <>
                  <label className={labelCls} htmlFor={`pf-${f.key}`}>
                    {f.label}{f.required && <span className="text-red-500"> *</span>}
                  </label>
                  {f.help && <p className="mb-1.5 -mt-0.5 text-xs text-slate-500">{f.help}</p>}
                  {renderInput(f, values, set, toggleMulti, inputCls)}
                  {fieldErrs[f.key] && (
                    <div className="mt-1 text-xs text-red-600" data-testid={`pf-err-${f.key}`}>{fieldErrs[f.key]}</div>
                  )}
                </>
              )}
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

function renderInput(f, values, set, toggleMulti, inputCls) {
  const v = values[f.key];
  const tid = `pf-${f.key}`;

  switch (f.type) {
    case "textarea":
      return (
        <textarea id={tid} rows={4} value={v || ""} onChange={(e) => set(f.key, e.target.value)}
          placeholder={f.placeholder} maxLength={f.max || undefined}
          className={`${inputCls} h-auto py-2.5`} data-testid={tid} />
      );

    case "select":
      return (
        <select id={tid} value={v || ""} onChange={(e) => set(f.key, e.target.value)}
          className={inputCls} data-testid={tid}>
          <option value="">Pilih...</option>
          {(f.options || []).map((o) => <option key={o} value={o}>{o}</option>)}
        </select>
      );

    case "radio":
      return (
        <div className="space-y-2" data-testid={tid} role="radiogroup" aria-label={f.label}>
          {(f.options || []).map((o) => (
            <label key={o} className="flex items-center gap-2 text-sm text-slate-700 rounded-lg border border-slate-200 px-3 py-2 cursor-pointer hover:border-[#f5b120]">
              <input type="radio" name={f.key} value={o} checked={v === o}
                onChange={() => set(f.key, o)} data-testid={`${tid}-${slide(o)}`} />
              {o}
            </label>
          ))}
        </div>
      );

    case "multiselect":
      return (
        <div className="space-y-2" data-testid={tid}>
          {(f.options || []).map((o) => {
            const on = Array.isArray(v) && v.includes(o);
            return (
              <label key={o} className="flex items-center gap-2 text-sm text-slate-700 rounded-lg border border-slate-200 px-3 py-2 cursor-pointer hover:border-[#f5b120]">
                <input type="checkbox" checked={on} onChange={() => toggleMulti(f.key, o)}
                  data-testid={`${tid}-${slide(o)}`} />
                {o}
              </label>
            );
          })}
        </div>
      );

    case "checkbox":
      return (
        <label className="flex items-center gap-2 text-sm text-slate-600">
          <input type="checkbox" checked={!!v} onChange={(e) => set(f.key, e.target.checked)} data-testid={tid} />
          {f.placeholder || f.label}
        </label>
      );

    case "rating": {
      const top = f.rating_max || 5;
      return (
        <div className="flex items-center gap-1.5" data-testid={tid}>
          {Array.from({ length: top }, (_, i) => i + 1).map((n) => (
            <button key={n} type="button" onClick={() => set(f.key, n)}
              aria-label={`${n} dari ${top}`} data-testid={`${tid}-${n}`}
              className={`h-10 w-10 rounded-lg border text-sm font-bold transition-colors ${
                Number(v) >= n
                  ? "bg-[#f5b120] border-[#f5b120] text-[#0a2350]"
                  : "bg-white border-slate-300 text-slate-400 hover:border-[#f5b120]"
              }`}>{n}</button>
          ))}
        </div>
      );
    }

    case "date":
      return <input id={tid} type="date" value={v || ""} onChange={(e) => set(f.key, e.target.value)}
        className={inputCls} data-testid={tid} />;

    case "time":
      return <input id={tid} type="time" value={v || ""} onChange={(e) => set(f.key, e.target.value)}
        className={inputCls} data-testid={tid} />;

    case "number":
      return <input id={tid} type="number" value={v ?? ""} min={f.min ?? undefined} max={f.max ?? undefined}
        onChange={(e) => set(f.key, e.target.value)} placeholder={f.placeholder}
        className={inputCls} data-testid={tid} />;

    case "email":
      return <input id={tid} type="email" value={v || ""} onChange={(e) => set(f.key, e.target.value)}
        placeholder={f.placeholder} className={inputCls} data-testid={tid} />;

    case "url":
      return <input id={tid} type="url" value={v || ""} onChange={(e) => set(f.key, e.target.value)}
        placeholder={f.placeholder || "https://"} className={inputCls} data-testid={tid} />;

    default:
      return <input id={tid} type="text" value={v || ""} onChange={(e) => set(f.key, e.target.value)}
        placeholder={f.placeholder} maxLength={f.max || undefined}
        className={inputCls} data-testid={tid} />;
  }
}

/** Slug a label into a stable testid segment. */
function slide(s) {
  return String(s).toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
}

const Shell = ({ children }) => (
  <div className="min-h-screen bg-slate-50 flex items-center justify-center p-4">
    <div className="w-full max-w-lg bg-white rounded-3xl shadow-xl border border-slate-200 p-8 md:p-10">
      {children}
    </div>
  </div>
);
