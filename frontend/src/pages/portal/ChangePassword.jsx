import React, { useState } from "react";
import { api } from "../../portal/api";
import { PageHeader, Card, btnPrimary, inputClass, labelClass } from "./ui";
import { Lock, Loader2, AlertTriangle, CheckCircle2 } from "lucide-react";
import { useAuth } from "../../portal/AuthContext";

/**
 * Change-password screen — available to every logged-in role (client and staff).
 * Route: /portal/settings/password
 */
const ChangePassword = () => {
  const { user } = useAuth();
  const [f, setF] = useState({ current_password: "", new_password: "", confirm: "" });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [ok, setOk] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setErr(""); setOk(false);
    if (f.new_password.length < 8) return setErr("New password must be at least 8 characters.");
    if (f.new_password !== f.confirm) return setErr("Password confirmation does not match.");
    if (f.new_password === f.current_password) return setErr("New password must differ from the current one.");
    setBusy(true);
    try {
      await api.post("/auth/change-password", {
        current_password: f.current_password, new_password: f.new_password,
      });
      setOk(true);
      setF({ current_password: "", new_password: "", confirm: "" });
    } catch (er) {
      setErr(er?.response?.data?.detail || "Failed to change password");
    } finally { setBusy(false); }
  };

  return (
    <div>
      <PageHeader
        title="Change password"
        subtitle={`Signed in as ${user?.name || user?.email}. Choose a new password — you'll stay logged in on this device.`}
      />
      <div className="max-w-lg">
        <Card className="p-6">
          <form onSubmit={submit} data-testid="change-pw-form">
            {ok && (
              <div className="mb-4 flex items-start gap-2 text-sm bg-emerald-50 border border-emerald-200 text-emerald-800 rounded-xl px-3 py-2.5" data-testid="change-pw-success">
                <CheckCircle2 className="h-4 w-4 mt-0.5 flex-shrink-0" />
                <span>Password updated.</span>
              </div>
            )}
            {err && (
              <div className="mb-4 flex items-start gap-2 text-sm bg-red-50 border border-red-200 text-red-700 rounded-xl px-3 py-2.5" data-testid="change-pw-error">
                <AlertTriangle className="h-4 w-4 mt-0.5 flex-shrink-0" /><span>{err}</span>
              </div>
            )}
            <label className="block">
              <div className={labelClass}>Current password</div>
              <input type="password" required value={f.current_password}
                     onChange={(e) => setF({ ...f, current_password: e.target.value })}
                     data-testid="change-pw-current" className={`${inputClass} mt-1`} autoComplete="current-password" />
            </label>
            <label className="block mt-4">
              <div className={labelClass}>New password (min 8 characters)</div>
              <input type="password" required minLength={8} value={f.new_password}
                     onChange={(e) => setF({ ...f, new_password: e.target.value })}
                     data-testid="change-pw-new" className={`${inputClass} mt-1`} autoComplete="new-password" />
            </label>
            <label className="block mt-4">
              <div className={labelClass}>Confirm new password</div>
              <input type="password" required minLength={8} value={f.confirm}
                     onChange={(e) => setF({ ...f, confirm: e.target.value })}
                     data-testid="change-pw-confirm" className={`${inputClass} mt-1`} autoComplete="new-password" />
            </label>
            <button type="submit" disabled={busy} className={`${btnPrimary} mt-6 w-full`} data-testid="change-pw-submit">
              {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Lock className="h-4 w-4" />}
              {busy ? "Updating…" : "Change password"}
            </button>
          </form>
        </Card>
      </div>
    </div>
  );
};

export default ChangePassword;
