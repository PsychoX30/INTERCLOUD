import { useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Plus, MagnifyingGlass, PencilSimple, ArrowUpRight } from "@phosphor-icons/react";
import { api } from "@/lib/api";
import { formatIDR, formatDate } from "@/lib/format";
import { useI18n } from "@/context/I18nContext";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Badge } from "@/components/ui/badge";

const STATUS_COLORS = {
  active: "bg-emerald-50 text-emerald-700 border-emerald-200",
  disposed: "bg-slate-100 text-slate-600 border-slate-200",
  in_repair: "bg-amber-50 text-amber-700 border-amber-200",
};

export default function Assets() {
  const { t } = useI18n();
  const navigate = useNavigate();
  const [q, setQ] = useState("");
  const [category, setCategory] = useState("all");
  const [location, setLocation] = useState("all");
  const [status, setStatus] = useState("all");
  const [page, setPage] = useState(1);
  const pageSize = 20;

  const cats = useQuery({
    queryKey: ["cats"],
    queryFn: async () => (await api.get("/categories")).data,
  });
  const locs = useQuery({
    queryKey: ["locs"],
    queryFn: async () => (await api.get("/locations")).data,
  });

  const assets = useQuery({
    queryKey: ["assets", { q, category, location, status, page }],
    queryFn: async () => {
      const params = { page, page_size: pageSize };
      if (q) params.q = q;
      if (category !== "all") params.category_id = category;
      if (location !== "all") params.location_id = location;
      if (status !== "all") params.status = status;
      return (await api.get("/assets", { params })).data;
    },
    keepPreviousData: true,
  });

  const totalPages = useMemo(() => {
    if (!assets.data) return 1;
    return Math.max(1, Math.ceil(assets.data.total / pageSize));
  }, [assets.data]);

  return (
    <div className="space-y-6" data-testid="assets-page">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <div className="text-[11px] font-semibold uppercase tracking-[0.25em] text-slate-500">
            Master
          </div>
          <h1 className="mt-1 font-display text-3xl font-bold tracking-tight text-slate-900 sm:text-4xl">
            {t("common.assets")}
          </h1>
        </div>
        <Button
          data-testid="assets-new-button"
          onClick={() => navigate("/assets/new")}
          className="h-10 gap-2 rounded-full bg-[#0F172A] px-5 text-sm font-semibold hover:bg-[#1e293b]"
        >
          <Plus size={16} />
          {t("asset.newAsset")}
        </Button>
      </div>

      <Card className="ring-hair border-0 shadow-none">
        <CardContent className="p-4">
          <div className="grid grid-cols-1 gap-3 md:grid-cols-4">
            <div className="relative md:col-span-2">
              <MagnifyingGlass size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
              <Input
                data-testid="assets-search-input"
                value={q}
                onChange={(e) => {
                  setQ(e.target.value);
                  setPage(1);
                }}
                placeholder={`${t("common.search")}…`}
                className="h-10 pl-9"
              />
            </div>
            <Select value={category} onValueChange={(v) => { setCategory(v); setPage(1); }}>
              <SelectTrigger data-testid="assets-filter-category" className="h-10">
                <SelectValue placeholder={t("common.categories")} />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">{t("common.all")} — {t("common.categories")}</SelectItem>
                {(cats.data || []).map((c) => (
                  <SelectItem key={c.id} value={c.id}>{c.name}</SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Select value={location} onValueChange={(v) => { setLocation(v); setPage(1); }}>
              <SelectTrigger data-testid="assets-filter-location" className="h-10">
                <SelectValue placeholder={t("common.locations")} />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">{t("common.all")} — {t("common.locations")}</SelectItem>
                {(locs.data || []).map((l) => (
                  <SelectItem key={l.id} value={l.id}>{l.name}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </CardContent>
      </Card>

      <Card className="ring-hair border-0 shadow-none">
        <CardContent className="p-0">
          <div className="overflow-x-auto">
            <table className="dense-table w-full text-sm" data-testid="assets-table">
              <thead className="bg-slate-50">
                <tr>
                  <th className="px-4 py-2 text-left">{t("common.code")}</th>
                  <th className="px-4 py-2 text-left">{t("common.name")}</th>
                  <th className="px-4 py-2 text-left">{t("common.categories")}</th>
                  <th className="px-4 py-2 text-left">{t("common.locations")}</th>
                  <th className="px-4 py-2 text-left">{t("asset.acquisitionDate")}</th>
                  <th className="px-4 py-2 text-right">{t("asset.acquisitionCost")}</th>
                  <th className="px-4 py-2 text-right">{t("asset.accumulatedDep")}</th>
                  <th className="px-4 py-2 text-right">{t("asset.bookValue")}</th>
                  <th className="px-4 py-2 text-left">{t("common.status")}</th>
                  <th className="px-4 py-2"></th>
                </tr>
              </thead>
              <tbody>
                {assets.isLoading && (
                  <tr>
                    <td colSpan={10} className="px-4 py-12 text-center text-slate-400">
                      {t("common.loading")}
                    </td>
                  </tr>
                )}
                {!assets.isLoading && (assets.data?.items || []).length === 0 && (
                  <tr>
                    <td colSpan={10} className="px-4 py-16 text-center">
                      <div className="mx-auto max-w-sm">
                        <div className="font-display text-lg font-semibold text-slate-700">
                          {t("common.empty")}
                        </div>
                        <p className="mt-1 text-sm text-slate-500">
                          Tambahkan aset pertama untuk memulai perhitungan penyusutan garis lurus.
                        </p>
                        <Button
                          onClick={() => navigate("/assets/new")}
                          className="mt-4 h-10 gap-2 rounded-full bg-[#0F172A] hover:bg-[#1e293b]"
                          data-testid="assets-empty-cta"
                        >
                          <Plus size={16} /> {t("asset.newAsset")}
                        </Button>
                      </div>
                    </td>
                  </tr>
                )}
                {(assets.data?.items || []).map((a) => (
                  <tr key={a.id} className="hover:bg-slate-50" data-testid={`asset-row-${a.code}`}>
                    <td className="px-4 py-2 font-mono text-xs text-slate-700">{a.code}</td>
                    <td className="px-4 py-2">
                      <Link
                        to={`/assets/${a.id}`}
                        className="font-medium text-slate-900 hover:text-[#004AAD]"
                      >
                        {a.name}
                      </Link>
                    </td>
                    <td className="px-4 py-2 text-slate-700">{a.category_name || "—"}</td>
                    <td className="px-4 py-2 text-slate-700">{a.location_name || "—"}</td>
                    <td className="px-4 py-2 text-slate-700 tabular-nums">{formatDate(a.acquisition_date)}</td>
                    <td className="px-4 py-2 text-right font-medium tabular-nums">{formatIDR(a.acquisition_cost)}</td>
                    <td className="px-4 py-2 text-right tabular-nums text-amber-700">{formatIDR(a.depreciation.accumulated_depreciation)}</td>
                    <td className="px-4 py-2 text-right font-medium tabular-nums text-emerald-700">{formatIDR(a.depreciation.book_value)}</td>
                    <td className="px-4 py-2">
                      <Badge variant="outline" className={`rounded-full border px-2 py-0 text-[10px] font-semibold uppercase tracking-wider ${STATUS_COLORS[a.status] || ""}`}>
                        {t(`asset.${a.status}`)}
                      </Badge>
                    </td>
                    <td className="px-4 py-2">
                      <div className="flex items-center justify-end gap-1">
                        <Button asChild variant="ghost" size="sm" className="h-8 w-8 p-0">
                          <Link to={`/assets/${a.id}`} data-testid={`asset-view-${a.code}`}>
                            <ArrowUpRight size={16} />
                          </Link>
                        </Button>
                        <Button asChild variant="ghost" size="sm" className="h-8 w-8 p-0">
                          <Link to={`/assets/${a.id}/edit`} data-testid={`asset-edit-${a.code}`}>
                            <PencilSimple size={16} />
                          </Link>
                        </Button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Pagination */}
          {(assets.data?.total || 0) > 0 && (
            <div className="flex items-center justify-between border-t border-slate-200 px-4 py-3 text-xs text-slate-600">
              <div>
                {assets.data.total} {t("common.total").toLowerCase()} • Page {page} / {totalPages}
              </div>
              <div className="flex gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  disabled={page <= 1}
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                  data-testid="assets-page-prev"
                >
                  Prev
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  disabled={page >= totalPages}
                  onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                  data-testid="assets-page-next"
                >
                  Next
                </Button>
              </div>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
