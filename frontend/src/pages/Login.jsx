import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { useAuth } from "@/context/AuthContext";
import { useI18n } from "@/context/I18nContext";
import { formatApiError } from "@/lib/api";
import AuthShell from "@/components/AuthShell";
import TurnstileWidget from "@/components/TurnstileWidget";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

export default function Login() {
  const { login } = useAuth();
  const { t } = useI18n();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [captchaToken, setCaptchaToken] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      await login({ email, password, captcha_token: captchaToken });
      toast.success("Selamat datang kembali!");
      navigate("/dashboard", { replace: true });
    } catch (err) {
      const msg = formatApiError(err.response?.data?.detail) || err.message;
      setError(msg);
      toast.error(msg);
    } finally {
      setLoading(false);
    }
  };

  return (
    <AuthShell
      title={t("auth.loginCta")}
      subtitle={t("auth.subtitle")}
      footer="© Intercloud Portal"
    >
      <form onSubmit={handleSubmit} className="space-y-4" data-testid="login-form">
        <div>
          <Label htmlFor="email" className="mb-1.5 block text-xs font-semibold uppercase tracking-widest text-slate-500">
            {t("common.email")}
          </Label>
          <Input
            id="email"
            type="email"
            required
            autoComplete="email"
            data-testid="login-email-input"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className="h-11"
            placeholder="admin@intercloud.io"
          />
        </div>
        <div>
          <div className="mb-1.5 flex items-center justify-between">
            <Label htmlFor="password" className="text-xs font-semibold uppercase tracking-widest text-slate-500">
              {t("common.password")}
            </Label>
            <Link
              to="/forgot-password"
              data-testid="login-forgot-link"
              className="text-xs font-medium text-[#004AAD] hover:underline"
            >
              {t("common.forgot")}?
            </Link>
          </div>
          <Input
            id="password"
            type="password"
            required
            autoComplete="current-password"
            data-testid="login-password-input"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="h-11"
            placeholder="••••••••"
          />
        </div>

        <TurnstileWidget onToken={setCaptchaToken} />

        {error && (
          <div
            data-testid="login-error"
            className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700"
          >
            {error}
          </div>
        )}

        <Button
          type="submit"
          disabled={loading}
          data-testid="login-submit-button"
          className="h-11 w-full rounded-full bg-[#0F172A] text-sm font-semibold hover:bg-[#1e293b]"
        >
          {loading ? t("common.loading") : t("common.login")}
        </Button>

        <div className="text-center text-sm text-slate-600">
          {t("auth.noAccount")}{" "}
          <Link to="/register" data-testid="login-register-link" className="font-semibold text-[#004AAD] hover:underline">
            {t("common.register")}
          </Link>
        </div>
      </form>
    </AuthShell>
  );
}
