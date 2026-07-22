import React, { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../../portal/api";
import { getRecaptchaToken } from "../../portal/recaptcha";
import { Lock, ArrowLeft, Loader2, AlertTriangle, CheckCircle2, Cloud } from "lucide-react";

/**
 * Public "Forgot password" screen. Always shows a neutral confirmation
 * regardless of whether the email exists — no user enumeration.
 */
const PortalForgotPassword = () => {
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);
  const [err, setErr] = useState("");

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true); setErr("");
    try {
      const recaptcha_token = await getRecaptchaToken("forgot").catch(() => null);
      await api.post("/auth/forgot-password", { email, recaptcha_token });
      setDone(true);
    } catch (er) {
      setErr(er?.response?.data?.detail || "Failed to submit");
    } finally { setBusy(false); }
  };

  return (
    <div className="min-h-screen grid md:grid-cols-[45%_55%] bg-[#0a2350] text-white ic-font">
      <div className="relative overflow-hidden hidden md:flex flex-col p-12 justify-between">
        <div className="absolute -top-24 -left-16 h-96 w-96 rounded-full bg-[#f5b120]/10 blur-3xl" />
        <div className="relative">
          <Link to="/portal/login" className="inline-flex items-center gap-2 text-white/70 hover:text-[#f5b120] transition-colors text-sm">
            <ArrowLeft className="h-4 w-4" /> Back to login
          </Link>
          <div className="mt-10 flex items-center gap-3">
            <div className="h-11 w-11 rounded-xl bg-[#f5b120] flex items-center justify-center">
              <Cloud className="h-6 w-6 text-[#0a2350]" strokeWidth={2} />
            </div>
            <div>
              <div className="text-xs font-bold tracking-widest text-[#f5b120]">FORGOT PASSWORD</div>
              <div className="text-lg font-extrabold">Intercloud Digital Inovasi</div>
            </div>
          </div>
        </div>
        <div className="relative max-w-md">
          <h1 className="text-4xl font-extrabold leading-tight">Reset your <span className="text-[#f5b120]">password</span> in seconds.</h1>
          <p className="mt-5 text-white/70 text-sm leading-relaxed">
            Enter your business email and we'll send you a secure one-time link. The link expires in 60 minutes.
          </p>
        </div>
        <div className="relative text-[11px] text-white/50">© {new Date().getFullYear()} PT Intercloud Digital Inovasi</div>
      </div>

      <div className="flex items-center justify-center p-6 md:p-10 bg-slate-50 text-[#0a2350]">
        <form onSubmit={submit} className="w-full max-w-md bg-white rounded-3xl shadow-xl border border-slate-200 p-8" data-testid="forgot-form">
          <div className="text-[#f5b120] text-xs font-bold tracking-widest uppercase">Forgot password</div>
          <h2 className="text-2xl md:text-3xl font-extrabold mt-1">Reset your password</h2>

          {done ? (
            <div className="mt-6" data-testid="forgot-done">
              <div className="flex items-start gap-2 text-sm bg-emerald-50 border border-emerald-200 text-emerald-800 rounded-xl px-3 py-3">
                <CheckCircle2 className="h-4 w-4 mt-0.5 flex-shrink-0" />
                <div>
                  <div className="font-bold">Check your inbox.</div>
                  <div className="mt-1">If an account exists for <b>{email}</b>, we've sent a password-reset link. Please check your inbox and spam folder.</div>
                </div>
              </div>
              <Link to="/portal/login" className="mt-5 block text-center text-[#0a2350] font-bold hover:text-[#f5b120]">Back to login</Link>
            </div>
          ) : (
            <>
              <p className="text-sm text-slate-500 mt-1.5">Enter your account email — we'll send a one-time link within a minute.</p>
              {err && (
                <div className="mt-4 flex items-start gap-2 text-sm bg-red-50 border border-red-200 text-red-700 rounded-xl px-3 py-2.5">
                  <AlertTriangle className="h-4 w-4 mt-0.5 flex-shrink-0" /><span>{err}</span>
                </div>
              )}
              <label className="block mt-5">
                <span className="text-sm font-bold text-[#0a2350]">Email</span>
                <input type="email" value={email} required onChange={(e) => setEmail(e.target.value)} data-testid="forgot-email" placeholder="you@company.co.id"
                  className="mt-1.5 w-full h-12 rounded-xl border border-slate-300 px-3 focus:outline-none focus:ring-2 focus:ring-[#f5b120] focus:border-[#f5b120] text-sm" />
              </label>
              <button type="submit" disabled={busy} data-testid="forgot-submit"
                className="mt-5 w-full h-12 rounded-xl bg-[#0a2350] hover:bg-[#f5b120] hover:text-[#0a2350] text-white font-semibold text-sm inline-flex items-center justify-center gap-2 transition-colors disabled:opacity-70">
                {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Lock className="h-4 w-4" />}
                {busy ? "Sending…" : "Send reset link"}
              </button>
              <div className="mt-5 text-xs text-slate-500 border-t border-slate-100 pt-4">
                Remembered? <Link to="/portal/login" className="text-[#0a2350] font-semibold hover:text-[#f5b120]">Sign in →</Link>
              </div>
            </>
          )}
        </form>
      </div>
    </div>
  );
};

export default PortalForgotPassword;
