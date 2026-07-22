import { useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import { useI18n } from "@/context/I18nContext";
import { api, formatApiError } from "@/lib/api";
import AuthShell from "@/components/AuthShell";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

export default function ResetPassword() {
  const { t } = useI18n();
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const [token, setToken] = useState(params.get("token") || "");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setLoading(true);
    try {
      await api.post("/auth/reset-password", { token, new_password: password });
      toast.success("Kata sandi diperbarui. Silakan masuk.");
      navigate("/login", { replace: true });
    } catch (err) {
      toast.error(formatApiError(err.response?.data?.detail) || err.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <AuthShell title={t("common.newPassword")} subtitle={t("auth.subtitle")} footer="© Intercloud Portal">
      <form onSubmit={handleSubmit} className="space-y-4" data-testid="reset-form">
        <div>
          <Label className="mb-1.5 block text-xs font-semibold uppercase tracking-widest text-slate-500">
            Token
          </Label>
          <Input
            required
            value={token}
            onChange={(e) => setToken(e.target.value)}
            data-testid="reset-token-input"
            className="h-11 font-mono text-xs"
          />
        </div>
        <div>
          <Label className="mb-1.5 block text-xs font-semibold uppercase tracking-widest text-slate-500">
            {t("common.newPassword")}
          </Label>
          <Input
            type="password"
            minLength={6}
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            data-testid="reset-password-input"
            className="h-11"
          />
        </div>
        <Button
          type="submit"
          disabled={loading}
          data-testid="reset-submit-button"
          className="h-11 w-full rounded-full bg-[#0F172A] text-sm font-semibold hover:bg-[#1e293b]"
        >
          {loading ? t("common.loading") : t("auth.resetCta")}
        </Button>
        <Link to="/login" className="block text-center text-sm text-slate-600 hover:underline">
          ← {t("common.backToLogin")}
        </Link>
      </form>
    </AuthShell>
  );
}
