import React, { useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { api } from "../../portal/api";
import { Lock, Loader2, AlertTriangle, CheckCircle2, Cloud } from "lucide-react";

const PortalResetPassword = () => {
  const [sp] = useSearchParams();
  const token = sp.get("token") || "";
  const navigate = useNavigate();
  const [pw, setPw] = useState("");
  const [pw2, setPw2] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [done, setDone] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setErr("");
    if (pw.length < 8) return setErr("Password must be at least 8 characters.");
    if (pw !== pw2) return setErr("Password confirmation does not match.");
    setBusy(true);
    try {
      await api.post("/auth/reset-password", { token, new_password: pw });
      setDone(true);
      setTimeout(() => navigate("/portal/login", { replace: true }), 2500);
    } catch (er) {
      setErr(er?.response?.data?.detail || "Failed to reset password");
    } finally { setBusy(false); }
  };

  return (
    <div className="min-h-screen grid md:grid-cols-[45%_55%] bg-[#0a2350] text-white ic-font">
      <div className="relative overflow-hidden hidden md:flex flex-col p-12 justify-between">
        <div className="absolute -top-24 -left-16 h-96 w-96 rounded-full bg-[#f5b120]/10 blur-3xl" />
        <div className="relative flex items-center gap-3">
          <div className="h-11 w-11 rounded-xl bg-[#f5b120] flex items-center justify-center"><Cloud className="h-6 w-6 text-[#0a2350]" strokeWidth={2} /></div>
          <div>
            <div className="text-xs font-bold tracking-widest text-[#f5b120]">SET A NEW PASSWORD</div>
            <div className="text-lg font-extrabold">Intercloud Digital Inovasi</div>
          </div>
        </div>
        <div className="relative max-w-md">
          <h1 className="text-4xl font-extrabold leading-tight">Choose a strong <span className="text-[#f5b120]">password</span>.</h1>
          <p className="mt-5 text-white/70 text-sm leading-relaxed">Use at least 8 characters. Mix upper/lower case + a number for extra strength.</p>
        </div>
        <div className="relative text-[11px] text-white/50">© {new Date().getFullYear()} PT Intercloud Digital Inovasi</div>
      </div>
      <div className="flex items-center justify-center p-6 md:p-10 bg-slate-50 text-[#0a2350]">
        <form onSubmit={submit} className="w-full max-w-md bg-white rounded-3xl shadow-xl border border-slate-200 p-8" data-testid="reset-form">
          <div className="text-[#f5b120] text-xs font-bold tracking-widest uppercase">Reset password</div>
          <h2 className="text-2xl md:text-3xl font-extrabold mt-1">Set a new password</h2>
          {!token && (
            <div className="mt-5 text-sm bg-red-50 border border-red-200 text-red-700 rounded-xl px-3 py-2.5">Missing or invalid reset token. Please request a new link.</div>
          )}
          {done ? (
            <div className="mt-6" data-testid="reset-done">
              <div className="flex items-start gap-2 text-sm bg-emerald-50 border border-emerald-200 text-emerald-800 rounded-xl px-3 py-3">
                <CheckCircle2 className="h-4 w-4 mt-0.5 flex-shrink-0" />
                <div><b>Password updated.</b><div className="mt-1">Redirecting you to sign in…</div></div>
              </div>
            </div>
          ) : (
            <>
              {err && (
                <div className="mt-4 flex items-start gap-2 text-sm bg-red-50 border border-red-200 text-red-700 rounded-xl px-3 py-2.5" data-testid="reset-error">
                  <AlertTriangle className="h-4 w-4 mt-0.5 flex-shrink-0" /><span>{err}</span>
                </div>
              )}
              <label className="block mt-5">
                <span className="text-sm font-bold text-[#0a2350]">New password</span>
                <input type="password" required minLength={8} value={pw} onChange={(e) => setPw(e.target.value)} data-testid="reset-new"
                  className="mt-1.5 w-full h-12 rounded-xl border border-slate-300 px-3 focus:outline-none focus:ring-2 focus:ring-[#f5b120] focus:border-[#f5b120] text-sm" />
              </label>
              <label className="block mt-4">
                <span className="text-sm font-bold text-[#0a2350]">Confirm password</span>
                <input type="password" required minLength={8} value={pw2} onChange={(e) => setPw2(e.target.value)} data-testid="reset-confirm"
                  className="mt-1.5 w-full h-12 rounded-xl border border-slate-300 px-3 focus:outline-none focus:ring-2 focus:ring-[#f5b120] focus:border-[#f5b120] text-sm" />
              </label>
              <button type="submit" disabled={busy || !token} data-testid="reset-submit"
                className="mt-5 w-full h-12 rounded-xl bg-[#0a2350] hover:bg-[#f5b120] hover:text-[#0a2350] text-white font-semibold text-sm inline-flex items-center justify-center gap-2 transition-colors disabled:opacity-70">
                {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Lock className="h-4 w-4" />}
                {busy ? "Updating…" : "Set new password"}
              </button>
              <div className="mt-5 text-xs text-slate-500 border-t border-slate-100 pt-4">
                <Link to="/portal/login" className="text-[#0a2350] font-semibold hover:text-[#f5b120]">Back to login</Link>
              </div>
            </>
          )}
        </form>
      </div>
    </div>
  );
};

export default PortalResetPassword;
