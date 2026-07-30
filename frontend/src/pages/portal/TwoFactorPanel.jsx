import React, { useEffect, useState } from "react";
import { api } from "../../portal/api";
import { Card, btnPrimary, btnSecondary, inputClass, labelClass } from "./ui";
import { ShieldCheck, ShieldOff, Loader2, Copy } from "lucide-react";
import { toast } from "sonner";

export const TwoFactorPanel = () => {
  const [status, setStatus] = useState(null);
  const [setup, setSetup] = useState(null);
  const [code, setCode] = useState("");
  const [recovery, setRecovery] = useState(null);
  const [disableCode, setDisableCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  const load = () => api.get("/auth/2fa/status").then((r) => setStatus(r.data));
  useEffect(() => { load(); }, []);

  const begin = async () => {
    setBusy(true); setErr("");
    try { const r = await api.post("/auth/2fa/setup"); setSetup(r.data); }
    finally { setBusy(false); }
  };

  const confirm = async (e) => {
    e.preventDefault(); setBusy(true); setErr("");
    try {
      const r = await api.post("/auth/2fa/verify-enable", { code: code.trim() });
      setRecovery(r.data.recovery_codes);
      setSetup(null); setCode("");
      load();
    } catch (er) { setErr(er?.response?.data?.detail || "Kode tidak valid"); }
    finally { setBusy(false); }
  };

  const disable = async (e) => {
    e.preventDefault(); setBusy(true); setErr("");
    try {
      await api.post("/auth/2fa/disable", { code: disableCode.trim() });
      toast.success("2FA dinonaktifkan");
      setDisableCode(""); setRecovery(null);
      load();
    } catch (er) { setErr(er?.response?.data?.detail || "Kode tidak valid"); }
    finally { setBusy(false); }
  };

  if (!status) return null;

  return (
    <Card className="p-6 mt-6" data-testid="twofa-panel">
      <div className="flex items-center gap-2">
        {status.enabled
          ? <ShieldCheck className="h-5 w-5 text-emerald-600" />
          : <ShieldOff className="h-5 w-5 text-slate-400" />}
        <h3 className="text-lg font-extrabold text-[#0a2350]">Two-Factor Authentication (2FA)</h3>
        <span className={`ml-auto text-[10px] font-bold uppercase tracking-widest rounded-full px-2.5 py-1 ${
          status.enabled ? "bg-emerald-100 text-emerald-700" : "bg-slate-100 text-slate-500"}`} data-testid="twofa-status-badge">
          {status.enabled ? "Aktif" : "Nonaktif"}
        </span>
      </div>
      <p className="mt-2 text-sm text-slate-500">
        Lapisan keamanan ekstra dengan kode 6 digit dari aplikasi authenticator (Google Authenticator, Authy, 1Password).
      </p>
      {err && <div className="mt-3 text-sm text-red-700 bg-red-50 border border-red-200 rounded-xl px-3 py-2" data-testid="twofa-panel-error">{err}</div>}

      {recovery && (
        <div className="mt-4 rounded-2xl border border-amber-300 bg-amber-50 p-4" data-testid="twofa-recovery-codes">
          <div className="text-sm font-extrabold text-amber-800">Simpan recovery codes ini sekarang (hanya ditampilkan sekali):</div>
          <pre className="mt-2 text-sm font-mono grid grid-cols-2 gap-x-8">{recovery.join("\n")}</pre>
          <button className={`${btnSecondary} mt-3`} onClick={() => { navigator.clipboard.writeText(recovery.join("\n")); toast.success("Recovery codes disalin"); }} data-testid="twofa-copy-recovery">
            <Copy className="h-4 w-4" /> Salin semua
          </button>
        </div>
      )}

      {!status.enabled && !setup && (
        <button className={`${btnPrimary} mt-4`} onClick={begin} disabled={busy} data-testid="twofa-enable-btn">
          {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <ShieldCheck className="h-4 w-4" />} Aktifkan 2FA
        </button>
      )}

      {setup && (
        <form onSubmit={confirm} className="mt-4 grid md:grid-cols-2 gap-6 items-start" data-testid="twofa-setup-wizard">
          <div className="text-center">
            <img src={setup.qr} alt="QR 2FA" className="mx-auto rounded-xl border border-slate-200 w-44 h-44" data-testid="twofa-qr" />
            <div className="mt-2 text-[11px] text-slate-500">Scan dengan aplikasi authenticator</div>
            <div className="mt-1 font-mono text-[11px] text-slate-400 break-all">atau masukkan manual: {setup.secret}</div>
          </div>
          <div>
            <div className={labelClass}>Masukkan kode 6 digit dari aplikasi</div>
            <input value={code} onChange={(e) => setCode(e.target.value)} inputMode="numeric" maxLength={6}
              className={`${inputClass} text-center text-xl font-mono tracking-[0.35em]`} placeholder="000000" required data-testid="twofa-verify-input" />
            <div className="mt-3 flex gap-2">
              <button type="submit" className={btnPrimary} disabled={busy || code.trim().length !== 6} data-testid="twofa-verify-btn">
                {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : null} Verifikasi & Aktifkan
              </button>
              <button type="button" className={btnSecondary} onClick={() => { setSetup(null); setCode(""); }}>Batal</button>
            </div>
          </div>
        </form>
      )}

      {status.enabled && (
        <form onSubmit={disable} className="mt-4 flex flex-wrap items-end gap-3" data-testid="twofa-disable-form">
          <div>
            <div className={labelClass}>Kode 2FA / recovery code untuk menonaktifkan</div>
            <input value={disableCode} onChange={(e) => setDisableCode(e.target.value)} maxLength={12}
              className={`${inputClass} w-48 text-center font-mono`} placeholder="000000" required data-testid="twofa-disable-input" />
          </div>
          <button type="submit" className={`${btnSecondary} text-red-600 border-red-200 hover:bg-red-50`} disabled={busy} data-testid="twofa-disable-btn">
            <ShieldOff className="h-4 w-4" /> Nonaktifkan 2FA
          </button>
          <div className="text-xs text-slate-400 w-full">Sisa recovery code: {status.recovery_codes_left}</div>
        </form>
      )}
    </Card>
  );
};
