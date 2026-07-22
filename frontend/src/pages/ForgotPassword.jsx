import { useState } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { useI18n } from "@/context/I18nContext";
import { api, formatApiError } from "@/lib/api";
import AuthShell from "@/components/AuthShell";
import TurnstileWidget from "@/components/TurnstileWidget";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

export default function ForgotPassword() {
  const { t } = useI18n();
  const [email, setEmail] = useState("");
  const [captchaToken, setCaptchaToken] = useState("");
  const [loading, setLoading] = useState(false);
  const [sent, setSent] = useState(null); // { token } for dev display

  const handleSubmit = async (e) => {
    e.preventDefault();
    setLoading(true);
    try {
      const { data } = await api.post("/auth/forgot-password", { email, captcha_token: captchaToken });
      setSent({ token: data.reset_token || null });
      toast.success("Jika email terdaftar, tautan reset telah dibuat.");
    } catch (err) {
      toast.error(formatApiError(err.response?.data?.detail) || err.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <AuthShell title={t("common.forgot")} subtitle={t("auth.subtitle")} footer="© Intercloud Portal">
      {sent ? (
        <div className="space-y-4" data-testid="forgot-success">
          <p className="text-sm text-slate-700">
            Jika email tersebut terdaftar, Anda akan menerima instruksi reset kata sandi.
          </p>
          {sent.token && (
            <div className="rounded-md border border-slate-200 bg-slate-50 p-3 text-xs">
              <div className="mb-1 font-semibold uppercase tracking-wider text-slate-500">
                Dev Token
              </div>
              <div className="break-all font-mono text-slate-800">{sent.token}</div>
              <Link
                to={`/reset-password?token=${sent.token}`}
                className="mt-2 inline-block text-[#004AAD] hover:underline"
                data-testid="forgot-use-token-link"
              >
                Buka halaman reset →
              </Link>
            </div>
          )}
          <Link to="/login" className="block text-sm text-slate-600 hover:underline" data-testid="forgot-back-link">
            ← {t("common.backToLogin")}
          </Link>
        </div>
      ) : (
        <form onSubmit={handleSubmit} className="space-y-4" data-testid="forgot-form">
          <div>
            <Label className="mb-1.5 block text-xs font-semibold uppercase tracking-widest text-slate-500">
              {t("common.email")}
            </Label>
            <Input
              type="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              data-testid="forgot-email-input"
              className="h-11"
            />
          </div>
          <TurnstileWidget onToken={setCaptchaToken} />
          <Button
            type="submit"
            disabled={loading}
            data-testid="forgot-submit-button"
            className="h-11 w-full rounded-full bg-[#0F172A] text-sm font-semibold hover:bg-[#1e293b]"
          >
            {loading ? t("common.loading") : t("auth.forgotCta")}
          </Button>
          <Link to="/login" className="block text-center text-sm text-slate-600 hover:underline" data-testid="forgot-back-to-login">
            ← {t("common.backToLogin")}
          </Link>
        </form>
      )}
    </AuthShell>
  );
}
