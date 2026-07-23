import React, { useEffect, useState } from "react";
import { Link, useNavigate, useLocation } from "react-router-dom";
import { LogIn, Loader2, AlertTriangle, Cloud, ArrowLeft, ShieldCheck } from "lucide-react";
import { useAuth } from "../../portal/AuthContext";
import { isRecaptchaEnabled } from "../../portal/recaptcha";

const PortalLogin = () => {
  const { user, login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const expired = new URLSearchParams(location.search).get("expired");

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(expired ? "Session expired. Please sign in again." : "");
  const [captchaOn, setCaptchaOn] = useState(false);

  useEffect(() => {
    isRecaptchaEnabled().then(setCaptchaOn);
  }, []);

  useEffect(() => {
    if (user && user.role) {
      const target = user.role === "client" ? "/portal/client/dashboard" : "/portal/admin/dashboard";
      navigate(target, { replace: true });
    }
  }, [user, navigate]);

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    setErr("");
    try {
      const u = await login(email.trim(), password);
      const target = u.role === "client" ? "/portal/client/dashboard" : "/portal/admin/dashboard";
      navigate(target, { replace: true });
    } catch (e2) {
      setErr(e2.message || "Login failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="min-h-screen grid md:grid-cols-2 bg-[#0a2350] text-white ic-font">
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
              <div className="text-xs font-bold tracking-widest text-[#f5b120]">CLIENT PORTAL</div>
              <div className="text-lg font-extrabold">Intercloud Digital Inovasi</div>
            </div>
          </div>
        </div>
        <div className="relative max-w-md">
          <h1 className="text-4xl font-extrabold leading-tight">
            Manage your <span className="text-[#f5b120]">cloud, hosting</span> & <span className="text-[#f5b120]">colocation</span> from one place.
          </h1>
          <p className="mt-5 text-white/70 text-sm leading-relaxed">
            View active services, pay invoices, open a ticket to our 24/7 engineers,
            and order new products — all in a single dashboard.
          </p>
          <div className="mt-8 grid grid-cols-3 gap-3 text-center text-xs">
            <div className="rounded-xl border border-white/10 py-4">
              <div className="text-[#f5b120] font-extrabold text-lg">99.5%</div>
              <div className="text-white/70">SLA</div>
            </div>
            <div className="rounded-xl border border-white/10 py-4">
              <div className="text-[#f5b120] font-extrabold text-lg">24/7</div>
              <div className="text-white/70">Support</div>
            </div>
            <div className="rounded-xl border border-white/10 py-4">
              <div className="text-[#f5b120] font-extrabold text-lg">Tier III</div>
              <div className="text-white/70">Data Center</div>
            </div>
          </div>
        </div>
        <div className="relative text-[11px] text-white/50">
          © {new Date().getFullYear()} PT Intercloud Digital Inovasi
        </div>
      </div>

      {/* Right form panel */}
      <div className="flex items-center justify-center p-6 md:p-12 bg-slate-50 text-[#0a2350]">
        <form
          onSubmit={submit}
          className="w-full max-w-md bg-white rounded-3xl shadow-xl border border-slate-200 p-8 md:p-10"
          data-testid="portal-login-form"
        >
          <div className="md:hidden mb-6">
            <Link to="/" className="text-sm text-slate-500 hover:text-[#f5b120] inline-flex items-center gap-1">
              <ArrowLeft className="h-4 w-4" /> Back to website
            </Link>
          </div>
          <div className="text-[#f5b120] text-xs font-bold tracking-widest uppercase">Client Portal</div>
          <h2 className="text-2xl md:text-3xl font-extrabold mt-2">Sign in to your account</h2>
          <p className="text-sm text-slate-500 mt-2">Use the credentials issued by our team.</p>

          {err && (
            <div className="mt-5 flex items-start gap-2 text-sm bg-red-50 border border-red-200 text-red-700 rounded-xl px-3 py-2.5" data-testid="login-error">
              <AlertTriangle className="h-4 w-4 mt-0.5 flex-shrink-0" />
              <span>{err}</span>
            </div>
          )}

          <label className="block mt-6 text-sm">
            <span className="text-slate-700 font-semibold">Email</span>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              autoComplete="email"
              required
              data-testid="login-email"
              className="mt-1.5 w-full h-11 rounded-xl border border-slate-300 px-3 focus:outline-none focus:ring-2 focus:ring-[#f5b120] focus:border-[#f5b120]"
              placeholder="admin@intercloud-digital.com"
            />
          </label>
          <label className="block mt-4 text-sm">
            <span className="text-slate-700 font-semibold">Password</span>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="current-password"
              required
              data-testid="login-password"
              className="mt-1.5 w-full h-11 rounded-xl border border-slate-300 px-3 focus:outline-none focus:ring-2 focus:ring-[#f5b120] focus:border-[#f5b120]"
              placeholder="••••••••"
            />
          </label>

          <div className="mt-2 text-right">
            <Link to="/portal/forgot-password" className="text-xs text-slate-500 hover:text-[#f5b120] font-semibold" data-testid="login-goto-forgot">
              Forgot password?
            </Link>
          </div>

          <button
            type="submit"
            disabled={busy}
            data-testid="login-submit"
            className="mt-6 w-full h-11 rounded-xl bg-[#0a2350] hover:bg-[#f5b120] hover:text-[#0a2350] text-white font-semibold text-sm inline-flex items-center justify-center gap-2 transition-colors disabled:opacity-70"
          >
            {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <LogIn className="h-4 w-4" />}
            {busy ? "Signing in…" : "Sign In"}
          </button>

          {captchaOn && (
            <div className="mt-3 text-[11px] text-slate-500 flex items-center gap-1.5" data-testid="login-recaptcha-badge">
              <ShieldCheck className="h-3.5 w-3.5 text-emerald-600" />
              Protected by Google reCAPTCHA v3 — <a className="underline" href="https://policies.google.com/privacy" target="_blank" rel="noreferrer">Privacy</a> · <a className="underline" href="https://policies.google.com/terms" target="_blank" rel="noreferrer">Terms</a>
            </div>
          )}

          <div className="mt-6 text-xs text-slate-500 border-t border-slate-100 pt-5">
            <div>
              Don't have an account?{" "}
              <Link to="/portal/register" className="text-[#0a2350] font-semibold hover:text-[#f5b120]" data-testid="login-goto-register">
                Create one →
              </Link>
            </div>
          </div>
        </form>
      </div>
    </div>
  );
};

export default PortalLogin;
