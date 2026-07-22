import React, { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { UserPlus, Loader2, AlertTriangle, Cloud, ArrowLeft, CheckCircle2 } from "lucide-react";
import { useAuth } from "../../portal/AuthContext";

/**
 * Public self-registration form.
 * On success, backend issues a JWT + mirrors the new user into `crm_customers`.
 */
const PortalRegister = () => {
  const { user, register } = useAuth();
  const navigate = useNavigate();

  const [f, setF] = useState({
    name: "",
    email: "",
    phone: "",
    password: "",
    confirm: "",
    company: "",
    industry: "",
    attention: "",
    address_line1: "",
    address_line2: "",
    city: "",
    province: "",
    postal_code: "",
    country: "Indonesia",
    npwp: "",
    accepts_tos: false,
  });
  const [step, setStep] = useState(1); // 1: account, 2: billing
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  useEffect(() => {
    if (user && user.role === "client") navigate("/portal/client/dashboard", { replace: true });
    else if (user) navigate("/portal/admin/dashboard", { replace: true });
  }, [user, navigate]);

  const set = (k) => (e) => setF({ ...f, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value });

  const nextStep = (e) => {
    e.preventDefault();
    setErr("");
    if (!f.name.trim() || !f.email.trim() || !f.password) return setErr("Name, email, and password are required.");
    if (f.password.length < 8) return setErr("Password must be at least 8 characters.");
    if (f.password !== f.confirm) return setErr("Password confirmation does not match.");
    if (!f.accepts_tos) return setErr("Please accept the Terms of Service to continue.");
    setStep(2);
  };

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true); setErr("");
    try {
      // strip client-only "confirm" field before submitting
      const { confirm, ...payload } = f;
      const u = await register(payload);
      navigate(u.role === "client" ? "/portal/client/dashboard" : "/portal/admin/dashboard", { replace: true });
    } catch (e2) {
      setErr(e2.message || "Registration failed");
      setStep(1); // let user re-verify credentials if backend rejects them
    } finally {
      setBusy(false);
    }
  };

  const inputCls = "mt-1.5 w-full h-11 rounded-xl border border-slate-300 px-3 focus:outline-none focus:ring-2 focus:ring-[#f5b120] focus:border-[#f5b120] text-sm";
  const labelCls = "block text-sm";
  const labelTxt = "text-slate-700 font-semibold";

  return (
    <div className="min-h-screen grid md:grid-cols-[45%_55%] bg-[#0a2350] text-white ic-font">
      {/* Left brand panel */}
      <div className="relative overflow-hidden hidden md:flex flex-col p-12 justify-between">
        <div className="absolute inset-0 grid-overlay opacity-30" />
        <div className="absolute -top-24 -left-16 h-96 w-96 rounded-full bg-[#f5b120]/10 blur-3xl" />
        <div className="relative">
          <Link to="/" className="inline-flex items-center gap-2 text-white/70 hover:text-[#f5b120] transition-colors text-sm">
            <ArrowLeft className="h-4 w-4" /> Back to website
          </Link>
          <div className="mt-10 flex items-center gap-3">
            <div className="h-11 w-11 rounded-xl bg-[#f5b120] flex items-center justify-center">
              <Cloud className="h-6 w-6 text-[#0a2350]" strokeWidth={2} />
            </div>
            <div>
              <div className="text-xs font-bold tracking-widest text-[#f5b120]">CREATE ACCOUNT</div>
              <div className="text-lg font-extrabold">Intercloud Digital Inovasi</div>
            </div>
          </div>
        </div>
        <div className="relative max-w-md">
          <h1 className="text-4xl font-extrabold leading-tight">
            Start with <span className="text-[#f5b120]">Intercloud</span> in minutes.
          </h1>
          <p className="mt-5 text-white/70 text-sm leading-relaxed">
            One account for every service — cloud, hosting, VPS, colocation & interconnect.
            Order online, get an invoice instantly, and auto-provision the moment payment is verified.
          </p>
          <ul className="mt-6 space-y-2 text-sm text-white/80">
            {[
              "Real-time invoices & PDF receipts",
              "24/7 technical support ticketing",
              "Auto-provisioning on paid orders",
              "Bilingual (EN / ID) throughout",
            ].map((x) => (
              <li key={x} className="flex items-center gap-2">
                <CheckCircle2 className="h-4 w-4 text-[#f5b120]" /> {x}
              </li>
            ))}
          </ul>
        </div>
        <div className="relative text-[11px] text-white/50">
          © {new Date().getFullYear()} PT Intercloud Digital Inovasi
        </div>
      </div>

      {/* Right form panel */}
      <div className="flex items-center justify-center p-6 md:p-10 bg-slate-50 text-[#0a2350]">
        <form
          onSubmit={step === 1 ? nextStep : submit}
          className="w-full max-w-xl bg-white rounded-3xl shadow-xl border border-slate-200 p-7 md:p-9"
          data-testid="portal-register-form"
        >
          <div className="md:hidden mb-5">
            <Link to="/" className="text-sm text-slate-500 hover:text-[#f5b120] inline-flex items-center gap-1">
              <ArrowLeft className="h-4 w-4" /> Back to website
            </Link>
          </div>

          <div className="flex items-center justify-between">
            <div>
              <div className="text-[#f5b120] text-xs font-bold tracking-widest uppercase">Create Account</div>
              <h2 className="text-2xl md:text-3xl font-extrabold mt-1">Register your business</h2>
              <p className="text-sm text-slate-500 mt-1">Takes about a minute. Two quick steps.</p>
            </div>
            <div className="text-xs text-slate-500">
              Step <span className="font-extrabold text-[#0a2350]">{step}</span> / 2
            </div>
          </div>

          {/* progress */}
          <div className="mt-4 flex gap-1.5">
            <div className={`h-1 flex-1 rounded ${step >= 1 ? "bg-[#f5b120]" : "bg-slate-200"}`} />
            <div className={`h-1 flex-1 rounded ${step >= 2 ? "bg-[#f5b120]" : "bg-slate-200"}`} />
          </div>

          {err && (
            <div className="mt-5 flex items-start gap-2 text-sm bg-red-50 border border-red-200 text-red-700 rounded-xl px-3 py-2.5" data-testid="register-error">
              <AlertTriangle className="h-4 w-4 mt-0.5 flex-shrink-0" />
              <span>{err}</span>
            </div>
          )}

          {step === 1 && (
            <div className="mt-5 grid grid-cols-2 gap-3.5">
              <label className={`${labelCls} col-span-2`}>
                <span className={labelTxt}>Full name *</span>
                <input value={f.name} onChange={set("name")} required data-testid="reg-name" className={inputCls} placeholder="Budi Santoso" />
              </label>
              <label className={`${labelCls} col-span-2`}>
                <span className={labelTxt}>Business email *</span>
                <input type="email" value={f.email} onChange={set("email")} required data-testid="reg-email" className={inputCls} placeholder="you@company.co.id" autoComplete="email" />
              </label>
              <label className={labelCls}>
                <span className={labelTxt}>Phone / WhatsApp</span>
                <input value={f.phone} onChange={set("phone")} data-testid="reg-phone" className={inputCls} placeholder="+62 812-3456-7890" autoComplete="tel" />
              </label>
              <label className={labelCls}>
                <span className={labelTxt}>Company</span>
                <input value={f.company} onChange={set("company")} data-testid="reg-company" className={inputCls} placeholder="PT Contoh Digital" autoComplete="organization" />
              </label>
              <label className={labelCls}>
                <span className={labelTxt}>Password *</span>
                <input type="password" value={f.password} onChange={set("password")} minLength={8} required data-testid="reg-password" className={inputCls} placeholder="min 8 characters" autoComplete="new-password" />
              </label>
              <label className={labelCls}>
                <span className={labelTxt}>Confirm password *</span>
                <input type="password" value={f.confirm} onChange={set("confirm")} minLength={8} required data-testid="reg-confirm" className={inputCls} autoComplete="new-password" />
              </label>

              <label className="col-span-2 flex items-start gap-2 text-sm mt-1">
                <input type="checkbox" checked={f.accepts_tos} onChange={set("accepts_tos")} data-testid="reg-accept-tos" className="mt-0.5" />
                <span className="text-slate-600">
                  I have read and agree to the <Link to="/legal/terms" target="_blank" className="text-[#0a2350] font-semibold hover:text-[#f5b120] underline">Terms of Service</Link>,
                  <Link to="/legal/aup" target="_blank" className="text-[#0a2350] font-semibold hover:text-[#f5b120] underline mx-1">Acceptable Use Policy</Link>
                  and <Link to="/legal/sla" target="_blank" className="text-[#0a2350] font-semibold hover:text-[#f5b120] underline">SLA</Link>.
                </span>
              </label>
            </div>
          )}

          {step === 2 && (
            <div className="mt-5 grid grid-cols-2 gap-3.5">
              <p className="col-span-2 text-xs text-slate-500 -mb-1">
                Billing details appear on invoices &amp; quotations. All fields are optional but we recommend completing them so invoices are payment-ready.
              </p>
              <label className={`${labelCls} col-span-2`}>
                <span className={labelTxt}>ATTN (person invoices should be addressed to)</span>
                <input value={f.attention} onChange={set("attention")} data-testid="reg-attn" className={inputCls} placeholder={f.name || "Contact person"} />
              </label>
              <label className={`${labelCls} col-span-2`}>
                <span className={labelTxt}>Address line 1</span>
                <input value={f.address_line1} onChange={set("address_line1")} data-testid="reg-addr1" className={inputCls} placeholder="Jl. Sudirman Kav. 52-53" />
              </label>
              <label className={`${labelCls} col-span-2`}>
                <span className={labelTxt}>Address line 2</span>
                <input value={f.address_line2} onChange={set("address_line2")} data-testid="reg-addr2" className={inputCls} placeholder="Building, floor, unit" />
              </label>
              <label className={labelCls}>
                <span className={labelTxt}>City</span>
                <input value={f.city} onChange={set("city")} data-testid="reg-city" className={inputCls} placeholder="Jakarta Selatan" />
              </label>
              <label className={labelCls}>
                <span className={labelTxt}>Province / State</span>
                <input value={f.province} onChange={set("province")} data-testid="reg-province" className={inputCls} placeholder="DKI Jakarta" />
              </label>
              <label className={labelCls}>
                <span className={labelTxt}>Postal code</span>
                <input value={f.postal_code} onChange={set("postal_code")} data-testid="reg-postal" className={inputCls} placeholder="12190" />
              </label>
              <label className={labelCls}>
                <span className={labelTxt}>Country</span>
                <input value={f.country} onChange={set("country")} data-testid="reg-country" className={inputCls} />
              </label>
              <label className={`${labelCls} col-span-2`}>
                <span className={labelTxt}>NPWP (tax ID)</span>
                <input value={f.npwp} onChange={set("npwp")} data-testid="reg-npwp" className={inputCls} placeholder="00.000.000.0-000.000" />
              </label>
              <label className={`${labelCls} col-span-2`}>
                <span className={labelTxt}>Industry (optional — helps us tailor onboarding)</span>
                <select value={f.industry} onChange={set("industry")} data-testid="reg-industry" className={inputCls}>
                  <option value="">Select…</option>
                  <option>Digital / Media</option>
                  <option>E-Commerce</option>
                  <option>SaaS / Tech Startup</option>
                  <option>Financial Services</option>
                  <option>Manufacturing</option>
                  <option>Education</option>
                  <option>Government</option>
                  <option>Other</option>
                </select>
              </label>
            </div>
          )}

          <div className="mt-6 flex items-center gap-2">
            {step === 2 && (
              <button
                type="button"
                onClick={() => setStep(1)}
                className="h-11 px-4 rounded-xl border border-slate-300 text-sm font-semibold text-[#0a2350] hover:bg-slate-100"
                data-testid="reg-back"
              >
                ← Back
              </button>
            )}
            <button
              type="submit"
              disabled={busy}
              data-testid={step === 1 ? "reg-next" : "reg-submit"}
              className="flex-1 h-11 rounded-xl bg-[#0a2350] hover:bg-[#f5b120] hover:text-[#0a2350] text-white font-semibold text-sm inline-flex items-center justify-center gap-2 transition-colors disabled:opacity-70"
            >
              {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <UserPlus className="h-4 w-4" />}
              {busy ? "Creating account…" : step === 1 ? "Continue" : "Create my account"}
            </button>
          </div>

          <div className="mt-5 text-xs text-slate-500 border-t border-slate-100 pt-4">
            Already have an account?{" "}
            <Link to="/portal/login" className="text-[#0a2350] font-semibold hover:text-[#f5b120]" data-testid="reg-goto-login">
              Sign in →
            </Link>
          </div>
        </form>
      </div>
    </div>
  );
};

export default PortalRegister;
