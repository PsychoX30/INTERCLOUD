import { Link, useNavigate, useParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { PencilSimple, Trash, ArrowLeft } from "@phosphor-icons/react";
import { api, formatApiError } from "@/lib/api";
import { formatIDR, formatDate } from "@/lib/format";
import { useI18n } from "@/context/I18nContext";
import { useAuth } from "@/context/AuthContext";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { Badge } from "@/components/ui/badge";

function Row({ label, value, testId, className = "" }) {
  return (
    <div className={className} data-testid={testId}>
      <div className="text-[10px] font-semibold uppercase tracking-widest text-slate-500">{label}</div>
      <div className="mt-1 text-sm font-medium text-slate-900 tabular-nums">{value}</div>
    </div>
  );
}

export default function AssetDetail() {
  const { id } = useParams();
  const { t } = useI18n();
  const { user } = useAuth();
  const navigate = useNavigate();
  const qc = useQueryClient();

  const { data, isLoading } = useQuery({
    queryKey: ["asset", id],
    queryFn: async () => (await api.get(`/assets/${id}`)).data,
  });

  const remove = async () => {
    try {
      await api.delete(`/assets/${id}`);
      toast.success("Aset dihapus");
      qc.invalidateQueries({ queryKey: ["assets"] });
      navigate("/assets");
    } catch (e) {
      toast.error(formatApiError(e.response?.data?.detail) || e.message);
    }
  };

  if (isLoading || !data)
    return <div className="text-sm text-slate-500">{t("common.loading")}</div>;

  const d = data.depreciation;

  return (
    <div className="space-y-6" data-testid="asset-detail-page">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <Link to="/assets" className="mb-2 inline-flex items-center gap-1 text-xs font-semibold uppercase tracking-wider text-slate-500 hover:text-slate-900">
            <ArrowLeft size={14} /> {t("common.assets")}
          </Link>
          <div className="flex items-center gap-3">
            <h1 className="font-display text-3xl font-bold tracking-tight text-slate-900">{data.name}</h1>
            <Badge variant="outline" className="rounded-full border-slate-200 px-2 py-0 font-mono text-[11px]">
              {data.code}
            </Badge>
          </div>
          <div className="mt-1 text-sm text-slate-500">
            {data.category_name || "—"} • {data.location_name || "—"}
          </div>
        </div>
        <div className="flex gap-2">
          <Button asChild variant="outline" className="h-10 gap-2 rounded-full px-4" data-testid="asset-detail-edit">
            <Link to={`/assets/${id}/edit`}>
              <PencilSimple size={16} /> {t("common.edit")}
            </Link>
          </Button>
          {user?.role === "admin" && (
            <AlertDialog>
              <AlertDialogTrigger asChild>
                <Button variant="outline" className="h-10 gap-2 rounded-full border-red-200 px-4 text-red-600 hover:bg-red-50" data-testid="asset-detail-delete">
                  <Trash size={16} /> {t("common.delete")}
                </Button>
              </AlertDialogTrigger>
              <AlertDialogContent>
                <AlertDialogHeader>
                  <AlertDialogTitle>{t("common.confirmDelete")}</AlertDialogTitle>
                  <AlertDialogDescription>
                    {data.code} — {data.name}
                  </AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                  <AlertDialogCancel>{t("common.cancel")}</AlertDialogCancel>
                  <AlertDialogAction onClick={remove} data-testid="asset-detail-delete-confirm" className="bg-red-600 hover:bg-red-700">
                    {t("common.delete")}
                  </AlertDialogAction>
                </AlertDialogFooter>
              </AlertDialogContent>
            </AlertDialog>
          )}
        </div>
      </div>

      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
        <Card className="ring-hair border-0 shadow-none">
          <CardContent className="p-5">
            <Row label={t("asset.acquisitionCost")} value={formatIDR(data.acquisition_cost)} testId="detail-cost" />
          </CardContent>
        </Card>
        <Card className="ring-hair border-0 shadow-none">
          <CardContent className="p-5">
            <Row label={t("asset.salvageValue")} value={formatIDR(data.salvage_value)} testId="detail-salvage" />
          </CardContent>
        </Card>
        <Card className="ring-hair border-0 shadow-none">
          <CardContent className="p-5">
            <Row label={t("asset.usefulLife")} value={`${data.useful_life_years} thn`} testId="detail-life" />
          </CardContent>
        </Card>
        <Card className="ring-hair border-0 shadow-none">
          <CardContent className="p-5">
            <Row label={t("asset.acquisitionDate")} value={formatDate(data.acquisition_date)} testId="detail-date" />
          </CardContent>
        </Card>
      </div>

      <Card className="ring-hair border-0 shadow-none" data-testid="detail-computed">
        <CardHeader>
          <CardTitle className="font-display text-base font-semibold">Penyusutan Terhitung</CardTitle>
        </CardHeader>
        <CardContent className="grid grid-cols-2 gap-6 md:grid-cols-4">
          <Row label={t("asset.annualDep")} value={formatIDR(d.annual_depreciation)} testId="detail-annual" />
          <Row label={t("asset.monthlyDep")} value={formatIDR(d.monthly_depreciation)} testId="detail-monthly" />
          <Row label={t("asset.accumulatedDep")} value={formatIDR(d.accumulated_depreciation)} testId="detail-acc" />
          <Row label={t("asset.bookValue")} value={formatIDR(d.book_value)} testId="detail-book" className="text-emerald-700" />
        </CardContent>
      </Card>

      <Card className="ring-hair border-0 shadow-none">
        <CardHeader>
          <CardTitle className="font-display text-base font-semibold">{t("asset.schedule")}</CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          <div className="overflow-x-auto">
            <table className="dense-table w-full text-sm" data-testid="detail-schedule-table">
              <thead className="bg-slate-50">
                <tr>
                  <th className="px-4 py-2 text-left">Tahun</th>
                  <th className="px-4 py-2 text-left">Periode</th>
                  <th className="px-4 py-2 text-right">Penyusutan</th>
                  <th className="px-4 py-2 text-right">Akumulasi</th>
                  <th className="px-4 py-2 text-right">Nilai Buku</th>
                </tr>
              </thead>
              <tbody>
                {(data.schedule || []).map((r) => (
                  <tr key={r.period} className="hover:bg-slate-50">
                    <td className="px-4 py-2 font-medium tabular-nums">{r.year}</td>
                    <td className="px-4 py-2 tabular-nums text-slate-600">{r.period} / {data.useful_life_years}</td>
                    <td className="px-4 py-2 text-right tabular-nums">{formatIDR(r.depreciation)}</td>
                    <td className="px-4 py-2 text-right tabular-nums text-amber-700">{formatIDR(r.accumulated_depreciation)}</td>
                    <td className="px-4 py-2 text-right tabular-nums text-emerald-700">{formatIDR(r.book_value)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>

      {data.notes && (
        <Card className="ring-hair border-0 shadow-none">
          <CardHeader>
            <CardTitle className="font-display text-base font-semibold">{t("asset.notes")}</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="whitespace-pre-wrap text-sm text-slate-700">{data.notes}</p>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
