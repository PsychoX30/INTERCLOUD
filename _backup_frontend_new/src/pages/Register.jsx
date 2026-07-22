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

export default function Register() {
  const { register } = useAuth();
  const { t } = useI18n();
  const navigate = useNavigate();
  const [form, setForm] = useState({ name: "", email: "", password: "" });
  const [captchaToken, setCaptchaToken] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const onChange = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      await register({ ...form, captcha_token: captchaToken });
      toast.success("Akun berhasil dibuat!");
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
      title={t("auth.registerCta")}
      subtitle={t("auth.subtitle")}
      footer="© Intercloud Portal"
    >
      <form onSubmit={handleSubmit} className="space-y-4" data-testid="register-form">
        <div>
          <Label htmlFor="name" className="mb-1.5 block text-xs font-semibold uppercase tracking-widest text-slate-500">
            {t("common.name")}
          </Label>
          <Input
            id="name"
            required
            data-testid="register-name-input"
            value={form.name}
            onChange={onChange("name")}
            className="h-11"
          />
        </div>
        <div>
          <Label htmlFor="email" className="mb-1.5 block text-xs font-semibold uppercase tracking-widest text-slate-500">
            {t("common.email")}
          </Label>
          <Input
            id="email"
            type="email"
            required
            data-testid="register-email-input"
            value={form.email}
            onChange={onChange("email")}
            className="h-11"
          />
        </div>
        <div>
          <Label htmlFor="password" className="mb-1.5 block text-xs font-semibold uppercase tracking-widest text-slate-500">
            {t("common.password")}
          </Label>
          <Input
            id="password"
            type="password"
            minLength={6}
            required
            data-testid="register-password-input"
            value={form.password}
            onChange={onChange("password")}
            className="h-11"
          />
        </div>

        <TurnstileWidget onToken={setCaptchaToken} />

        {error && (
          <div data-testid="register-error" className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
            {error}
          </div>
        )}

        <Button
          type="submit"
          disabled={loading}
          data-testid="register-submit-button"
          className="h-11 w-full rounded-full bg-[#0F172A] text-sm font-semibold hover:bg-[#1e293b]"
        >
          {loading ? t("common.loading") : t("common.register")}
        </Button>

        <div className="text-center text-sm text-slate-600">
          {t("auth.hasAccount")}{" "}
          <Link to="/login" data-testid="register-login-link" className="font-semibold text-[#004AAD] hover:underline">
            {t("common.login")}
          </Link>
        </div>
      </form>
    </AuthShell>
  );
}
