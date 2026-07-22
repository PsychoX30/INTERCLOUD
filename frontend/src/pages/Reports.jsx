import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Printer, DownloadSimple } from "@phosphor-icons/react";
import { api } from "@/lib/api";
import { formatIDR, formatDate, todayISO } from "@/lib/format";
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

export default function Reports() {
  const { t } = useI18n();
  const [asOf, setAsOf] = useState(todayISO());
  const [category, setCategory] = useState("all");
  const [location, setLocation] = useState("all");

  const cats = useQuery({ queryKey: ["cats"], queryFn: async () => (await api.get("/categories")).data });
  const locs = useQuery({ queryKey: ["locs"], queryFn: async () => (await api.get("/locations")).data });

  const report = useQuery({
    queryKey: ["report-dep", asOf, category, location],
    queryFn: async () => {
      const params = { as_of: asOf };
      if (category !== "all") params.category_id = category;
      if (location !== "all") params.location_id = location;
      return (await api.get("/reports/depreciation", { params })).data;
    },
  });

  const exportCSV = () => {
    if (!report.data) return;
    const rows = report.data.rows;
    const headers = [
      "Code", "Name", "Category", "Location", "Acquisition Date",
      "Acquisition Cost", "Salvage Value", "Useful Life (yr)",
      "Annual Dep", "Accumulated Dep", "Book Value",
    ];
    const lines = [headers.join(",")];
    for (const r of rows) {
      lines.push([
        r.code, `"${(r.name || "").replaceAll('"', '""')}"`,
        r.category_name || "", r.location_name || "",
        r.acquisition_date, r.acquisition_cost, r.salvage_value, r.useful_life_years,
        r.annual_depreciation, r.accumulated_depreciation, r.book_value,
      ].join(","));
    }
    const blob = new Blob([lines.join("\n")], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `depreciation-${asOf}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="space-y-6" data-testid="reports-page">
      <div>
        <div className="text-[11px] font-semibold uppercase tracking-[0.25em] text-slate-500">Report</div>
        <h1 className="mt-1 font-display text-3xl font-bold tracking-tight text-slate-900 sm:text-4xl">
          {t("reports.title")}
        </h1>
      </div>

      <Card className="ring-hair border-0 shadow-none no-print">
        <CardContent className="p-4">
          <div className="grid grid-cols-1 gap-3 md:grid-cols-4">
            <div>
              <Label className="mb-1.5 block text-xs font-semibold uppercase tracking-widest text-slate-500">
                {t("reports.asOf")}
              </Label>
              <Input type="date" value={asOf} onChange={(e) => setAsOf(e.target.value)} className="h-10" data-testid="reports-asof-input" />
            </div>
            <div>
              <Label className="mb-1.5 block text-xs font-semibold uppercase tracking-widest text-slate-500">
                {t("common.categories")}
              </Label>
              <Select value={category} onValueChange={setCategory}>
                <SelectTrigger className="h-10" data-testid="reports-filter-category"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">{t("common.all")}</SelectItem>
                  {(cats.data || []).map((c) => <SelectItem key={c.id} value={c.id}>{c.name}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
            <div>
              <Label className="mb-1.5 block text-xs font-semibold uppercase tracking-widest text-slate-500">
                {t("common.locations")}
              </Label>
              <Select value={location} onValueChange={setLocation}>
                <SelectTrigger className="h-10" data-testid="reports-filter-location"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">{t("common.all")}</SelectItem>
                  {(locs.data || []).map((l) => <SelectItem key={l.id} value={l.id}>{l.name}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
            <div className="flex items-end gap-2">
              <Button onClick={exportCSV} className="h-10 gap-2 rounded-full bg-[#004AAD] hover:bg-[#003a8a]" data-testid="reports-export-csv">
                <DownloadSimple size={16} /> CSV
              </Button>
              <Button onClick={() => window.print()} variant="outline" className="h-10 gap-2 rounded-full" data-testid="reports-print">
                <Printer size={16} /> Print
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>

      <Card className="ring-hair border-0 shadow-none">
        <CardHeader className="pb-2">
          <CardTitle className="font-display text-base font-semibold">
            Per {formatDate(asOf)}
          </CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          <div className="overflow-x-auto">
            <table className="dense-table w-full text-sm" data-testid="reports-table">
              <thead className="bg-slate-50">
                <tr>
                  <th className="px-4 py-2 text-left">{t("common.code")}</th>
                  <th className="px-4 py-2 text-left">{t("common.name")}</th>
                  <th className="px-4 py-2 text-left">{t("common.categories")}</th>
                  <th className="px-4 py-2 text-left">{t("common.locations")}</th>
                  <th className="px-4 py-2 text-right">{t("asset.acquisitionCost")}</th>
                  <th className="px-4 py-2 text-right">{t("asset.annualDep")}</th>
                  <th className="px-4 py-2 text-right">{t("asset.accumulatedDep")}</th>
                  <th className="px-4 py-2 text-right">{t("asset.bookValue")}</th>
                </tr>
              </thead>
              <tbody>
                {(report.data?.rows || []).map((r) => (
                  <tr key={r.id} className="hover:bg-slate-50">
                    <td className="px-4 py-2 font-mono text-xs text-slate-700">{r.code}</td>
                    <td className="px-4 py-2 font-medium text-slate-900">{r.name}</td>
                    <td className="px-4 py-2 text-slate-700">{r.category_name || "—"}</td>
                    <td className="px-4 py-2 text-slate-700">{r.location_name || "—"}</td>
                    <td className="px-4 py-2 text-right tabular-nums">{formatIDR(r.acquisition_cost)}</td>
                    <td className="px-4 py-2 text-right tabular-nums">{formatIDR(r.annual_depreciation)}</td>
                    <td className="px-4 py-2 text-right tabular-nums text-amber-700">{formatIDR(r.accumulated_depreciation)}</td>
                    <td className="px-4 py-2 text-right tabular-nums text-emerald-700">{formatIDR(r.book_value)}</td>
                  </tr>
                ))}
                {(report.data?.rows || []).length === 0 && (
                  <tr>
                    <td colSpan={8} className="px-4 py-16 text-center text-slate-400">{t("common.empty")}</td>
                  </tr>
                )}
              </tbody>
              {report.data && report.data.rows.length > 0 && (
                <tfoot className="bg-slate-50 font-semibold">
                  <tr>
                    <td colSpan={4} className="px-4 py-3 text-right text-xs uppercase tracking-widest text-slate-600">
                      {t("common.total")}
                    </td>
                    <td className="px-4 py-3 text-right tabular-nums">{formatIDR(report.data.totals.acquisition_cost)}</td>
                    <td className="px-4 py-3"></td>
                    <td className="px-4 py-3 text-right tabular-nums text-amber-700">{formatIDR(report.data.totals.accumulated_depreciation)}</td>
                    <td className="px-4 py-3 text-right tabular-nums text-emerald-700">{formatIDR(report.data.totals.book_value)}</td>
                  </tr>
                </tfoot>
              )}
            </table>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
