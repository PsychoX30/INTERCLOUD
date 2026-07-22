import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { toast } from "sonner";
import { api, formatApiError } from "@/lib/api";
import { formatIDR, todayISO } from "@/lib/format";
import { useI18n } from "@/context/I18nContext";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";

const EMPTY = {
  code: "",
  name: "",
  category_id: "",
  location_id: "",
  acquisition_cost: "",
  salvage_value: "",
  useful_life_years: "",
  acquisition_date: todayISO(),
  status: "active",
  notes: "",
};

export default function AssetForm() {
  const { t } = useI18n();
  const navigate = useNavigate();
  const { id } = useParams();
  const isEdit = Boolean(id);

  const [form, setForm] = useState(EMPTY);
  const [loading, setLoading] = useState(false);

  const cats = useQuery({ queryKey: ["cats"], queryFn: async () => (await api.get("/categories")).data });
  const locs = useQuery({ queryKey: ["locs"], queryFn: async () => (await api.get("/locations")).data });

  useEffect(() => {
    if (!isEdit) return;
    (async () => {
      try {
        const { data } = await api.get(`/assets/${id}`);
        setForm({
          code: data.code,
          name: data.name,
          category_id: data.category_id || "",
          location_id: data.location_id || "",
          acquisition_cost: data.acquisition_cost,
          salvage_value: data.salvage_value,
          useful_life_years: data.useful_life_years,
          acquisition_date: data.acquisition_date.slice(0, 10),
          status: data.status,
          notes: data.notes || "",
        });
      } catch (e) {
        toast.error(formatApiError(e.response?.data?.detail) || e.message);
      }
    })();
  }, [id, isEdit]);

  const onChange = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target?.value ?? e }));

  const preview = useMemo(() => {
    const cost = Number(form.acquisition_cost || 0);
    const salvage = Number(form.salvage_value || 0);
    const life = Number(form.useful_life_years || 0);
    if (life <= 0) return null;
    const base = Math.max(cost - salvage, 0);
    const annual = base / life;
    return { annual, monthly: annual / 12 };
  }, [form.acquisition_cost, form.salvage_value, form.useful_life_years]);

  const submit = async (e) => {
    e.preventDefault();
    setLoading(true);
    try {
      const payload = {
        ...form,
        category_id: form.category_id || null,
        location_id: form.location_id || null,
        acquisition_cost: Number(form.acquisition_cost),
        salvage_value: Number(form.salvage_value),
        useful_life_years: Number(form.useful_life_years),
      };
      if (isEdit) {
        await api.put(`/assets/${id}`, payload);
        toast.success("Aset diperbarui");
      } else {
        const { data } = await api.post("/assets", payload);
        toast.success("Aset dibuat");
        navigate(`/assets/${data.id}`, { replace: true });
        return;
      }
      navigate(`/assets/${id}`);
    } catch (err) {
      toast.error(formatApiError(err.response?.data?.detail) || err.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="mx-auto max-w-4xl space-y-6" data-testid="asset-form-page">
      <div>
        <div className="text-[11px] font-semibold uppercase tracking-[0.25em] text-slate-500">
          {isEdit ? "Edit" : "New"}
        </div>
        <h1 className="mt-1 font-display text-3xl font-bold tracking-tight text-slate-900">
          {isEdit ? t("asset.editAsset") : t("asset.newAsset")}
        </h1>
        <p className="mt-1 text-xs text-slate-500 tabular-nums">{t("asset.formula")}</p>
      </div>

      <form onSubmit={submit} className="space-y-6">
        <Card className="ring-hair border-0 shadow-none">
          <CardHeader>
            <CardTitle className="font-display text-base font-semibold">Identitas</CardTitle>
          </CardHeader>
          <CardContent className="grid grid-cols-1 gap-4 md:grid-cols-2">
            <div>
              <Label className="mb-1.5 block text-xs font-semibold uppercase tracking-widest text-slate-500">
                {t("common.code")}
              </Label>
              <Input required value={form.code} onChange={onChange("code")} data-testid="asset-code-input" className="h-10" />
            </div>
            <div>
              <Label className="mb-1.5 block text-xs font-semibold uppercase tracking-widest text-slate-500">
                {t("common.name")}
              </Label>
              <Input required value={form.name} onChange={onChange("name")} data-testid="asset-name-input" className="h-10" />
            </div>
            <div>
              <Label className="mb-1.5 block text-xs font-semibold uppercase tracking-widest text-slate-500">
                {t("common.categories")}
              </Label>
              <Select value={form.category_id || "none"} onValueChange={(v) => setForm((f) => ({ ...f, category_id: v === "none" ? "" : v }))}>
                <SelectTrigger className="h-10" data-testid="asset-category-select">
                  <SelectValue placeholder="—" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="none">—</SelectItem>
                  {(cats.data || []).map((c) => (
                    <SelectItem key={c.id} value={c.id}>{c.name}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div>
              <Label className="mb-1.5 block text-xs font-semibold uppercase tracking-widest text-slate-500">
                {t("common.locations")}
              </Label>
              <Select value={form.location_id || "none"} onValueChange={(v) => setForm((f) => ({ ...f, location_id: v === "none" ? "" : v }))}>
                <SelectTrigger className="h-10" data-testid="asset-location-select">
                  <SelectValue placeholder="—" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="none">—</SelectItem>
                  {(locs.data || []).map((l) => (
                    <SelectItem key={l.id} value={l.id}>{l.name}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div>
              <Label className="mb-1.5 block text-xs font-semibold uppercase tracking-widest text-slate-500">
                {t("common.status")}
              </Label>
              <Select value={form.status} onValueChange={(v) => setForm((f) => ({ ...f, status: v }))}>
                <SelectTrigger className="h-10" data-testid="asset-status-select">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="active">{t("asset.active")}</SelectItem>
                  <SelectItem value="in_repair">{t("asset.in_repair")}</SelectItem>
                  <SelectItem value="disposed">{t("asset.disposed")}</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div>
              <Label className="mb-1.5 block text-xs font-semibold uppercase tracking-widest text-slate-500">
                {t("asset.acquisitionDate")}
              </Label>
              <Input
                type="date"
                required
                value={form.acquisition_date}
                onChange={onChange("acquisition_date")}
                data-testid="asset-acquisition-date-input"
                className="h-10"
              />
            </div>
          </CardContent>
        </Card>

        <Card className="ring-hair border-0 shadow-none">
          <CardHeader>
            <CardTitle className="font-display text-base font-semibold">
              Nilai & Penyusutan (Garis Lurus)
            </CardTitle>
          </CardHeader>
          <CardContent className="grid grid-cols-1 gap-4 md:grid-cols-3">
            <div>
              <Label className="mb-1.5 block text-xs font-semibold uppercase tracking-widest text-slate-500">
                {t("asset.acquisitionCost")}
              </Label>
              <Input
                type="number"
                min="0"
                step="0.01"
                required
                value={form.acquisition_cost}
                onChange={onChange("acquisition_cost")}
                data-testid="asset-cost-input"
                className="h-10 text-right tabular-nums"
              />
            </div>
            <div>
              <Label className="mb-1.5 block text-xs font-semibold uppercase tracking-widest text-slate-500">
                {t("asset.salvageValue")}
              </Label>
              <Input
                type="number"
                min="0"
                step="0.01"
                required
                value={form.salvage_value}
                onChange={onChange("salvage_value")}
                data-testid="asset-salvage-input"
                className="h-10 text-right tabular-nums"
              />
            </div>
            <div>
              <Label className="mb-1.5 block text-xs font-semibold uppercase tracking-widest text-slate-500">
                {t("asset.usefulLife")}
              </Label>
              <Input
                type="number"
                min="1"
                max="100"
                required
                value={form.useful_life_years}
                onChange={onChange("useful_life_years")}
                data-testid="asset-life-input"
                className="h-10 text-right tabular-nums"
              />
            </div>
            <div className="md:col-span-3 rounded-md border border-dashed border-slate-300 bg-slate-50 p-4" data-testid="asset-preview">
              <div className="mb-2 text-[10px] font-semibold uppercase tracking-widest text-slate-500">
                Preview
              </div>
              {preview ? (
                <div className="grid grid-cols-1 gap-3 text-sm md:grid-cols-2">
                  <div>
                    <div className="text-xs text-slate-500">{t("asset.annualDep")}</div>
                    <div className="mt-0.5 font-display text-xl font-bold tabular-nums text-slate-900">
                      {formatIDR(preview.annual)}
                    </div>
                  </div>
                  <div>
                    <div className="text-xs text-slate-500">{t("asset.monthlyDep")}</div>
                    <div className="mt-0.5 font-display text-xl font-bold tabular-nums text-slate-900">
                      {formatIDR(preview.monthly)}
                    </div>
                  </div>
                </div>
              ) : (
                <div className="text-sm text-slate-500">Isi nilai untuk melihat preview.</div>
              )}
            </div>
          </CardContent>
        </Card>

        <Card className="ring-hair border-0 shadow-none">
          <CardHeader>
            <CardTitle className="font-display text-base font-semibold">{t("asset.notes")}</CardTitle>
          </CardHeader>
          <CardContent>
            <Textarea
              rows={4}
              value={form.notes}
              onChange={onChange("notes")}
              data-testid="asset-notes-input"
            />
          </CardContent>
        </Card>

        <div className="flex items-center justify-end gap-3">
          <Button
            type="button"
            variant="outline"
            onClick={() => navigate(-1)}
            data-testid="asset-form-cancel"
            className="h-10 rounded-full px-5"
          >
            {t("common.cancel")}
          </Button>
          <Button
            type="submit"
            disabled={loading}
            data-testid="asset-form-submit"
            className="h-10 rounded-full bg-[#0F172A] px-6 text-sm font-semibold hover:bg-[#1e293b]"
          >
            {loading ? t("common.loading") : t("common.save")}
          </Button>
        </div>
      </form>
    </div>
  );
}
