import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  LineChart,
  Line,
  CartesianGrid,
  Legend,
} from "recharts";
import { Package, Coins, TrendUp, Bank } from "@phosphor-icons/react";
import { api } from "@/lib/api";
import { formatIDR } from "@/lib/format";
import { useI18n } from "@/context/I18nContext";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

function KpiCard({ label, value, sub, icon: Icon, testId, accent = "#0F172A" }) {
  return (
    <Card className="ring-hair border-0 shadow-none" data-testid={testId}>
      <CardContent className="p-5">
        <div className="flex items-start justify-between">
          <div>
            <div className="text-[11px] font-semibold uppercase tracking-[0.2em] text-slate-500">
              {label}
            </div>
            <div className="mt-2 font-display text-2xl font-bold tracking-tight text-slate-900 tabular-nums">
              {value}
            </div>
            {sub && <div className="mt-1 text-xs text-slate-500 tabular-nums">{sub}</div>}
          </div>
          <div
            className="grid h-9 w-9 place-items-center rounded-md text-white"
            style={{ backgroundColor: accent }}
          >
            <Icon size={18} weight="regular" />
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

export default function Dashboard() {
  const { t } = useI18n();
  const summary = useQuery({
    queryKey: ["dashboard-summary"],
    queryFn: async () => (await api.get("/dashboard/summary")).data,
  });
  const timeline = useQuery({
    queryKey: ["dashboard-timeline"],
    queryFn: async () => (await api.get("/reports/timeline?years=5")).data,
  });

  const s = summary.data;

  return (
    <div className="space-y-6" data-testid="dashboard-page">
      <div>
        <div className="text-[11px] font-semibold uppercase tracking-[0.25em] text-slate-500">
          Overview
        </div>
        <h1 className="mt-1 font-display text-3xl font-bold tracking-tight text-slate-900 sm:text-4xl">
          {t("common.dashboard")}
        </h1>
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-4">
        <KpiCard
          testId="kpi-total-assets"
          label={t("dashboard.totalAssets")}
          value={s ? s.total_assets : "—"}
          sub={s ? `${s.active_assets} aktif` : ""}
          icon={Package}
          accent="#0F172A"
        />
        <KpiCard
          testId="kpi-total-cost"
          label={t("dashboard.totalCost")}
          value={s ? formatIDR(s.total_acquisition_cost) : "—"}
          icon={Coins}
          accent="#004AAD"
        />
        <KpiCard
          testId="kpi-total-acc-dep"
          label={t("dashboard.totalAccDep")}
          value={s ? formatIDR(s.total_accumulated_depreciation) : "—"}
          icon={TrendUp}
          accent="#B45309"
        />
        <KpiCard
          testId="kpi-total-book"
          label={t("dashboard.totalBook")}
          value={s ? formatIDR(s.total_book_value) : "—"}
          icon={Bank}
          accent="#166534"
        />
      </div>

      {/* Charts grid */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <Card className="ring-hair border-0 shadow-none lg:col-span-2">
          <CardHeader className="pb-2">
            <CardTitle className="font-display text-base font-semibold">
              {t("dashboard.forecast")}
            </CardTitle>
          </CardHeader>
          <CardContent className="pb-4">
            <div className="h-64 w-full" data-testid="chart-forecast">
              <ResponsiveContainer>
                <LineChart data={timeline.data?.series || []}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#eef1f5" vertical={false} />
                  <XAxis dataKey="year" tickLine={false} axisLine={false} tick={{ fontSize: 11 }} />
                  <YAxis tickLine={false} axisLine={false} tick={{ fontSize: 11 }} tickFormatter={(v) => `${(v / 1_000_000).toFixed(0)}Jt`} />
                  <Tooltip formatter={(v) => formatIDR(v)} />
                  <Legend wrapperStyle={{ fontSize: 12 }} />
                  <Line type="monotone" dataKey="book_value" name="Nilai Buku" stroke="#004AAD" strokeWidth={2} dot={false} />
                  <Line type="monotone" dataKey="accumulated_depreciation" name="Akumulasi Penyusutan" stroke="#B45309" strokeWidth={2} dot={false} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </CardContent>
        </Card>

        <Card className="ring-hair border-0 shadow-none">
          <CardHeader className="pb-2">
            <CardTitle className="font-display text-base font-semibold">{t("dashboard.byCategory")}</CardTitle>
          </CardHeader>
          <CardContent className="pb-4">
            <div className="h-64 w-full" data-testid="chart-category">
              <ResponsiveContainer>
                <BarChart data={s?.category_breakdown || []} layout="vertical" margin={{ left: 10, right: 10 }}>
                  <XAxis type="number" hide />
                  <YAxis dataKey="name" type="category" width={110} tick={{ fontSize: 11 }} axisLine={false} tickLine={false} />
                  <Tooltip formatter={(v) => formatIDR(v)} />
                  <Bar dataKey="book_value" fill="#0F172A" radius={[0, 4, 4, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Bottom band: location breakdown */}
      <Card className="ring-hair border-0 shadow-none">
        <CardHeader className="pb-2">
          <CardTitle className="font-display text-base font-semibold">{t("dashboard.byLocation")}</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="overflow-x-auto">
            <table className="dense-table w-full text-sm">
              <thead>
                <tr>
                  <th className="px-3 py-2 text-left">{t("common.name")}</th>
                  <th className="px-3 py-2 text-right">Aset</th>
                  <th className="px-3 py-2 text-right">{t("dashboard.totalCost")}</th>
                  <th className="px-3 py-2 text-right">{t("dashboard.totalBook")}</th>
                </tr>
              </thead>
              <tbody>
                {(s?.location_breakdown || []).map((row) => (
                  <tr key={row.id} className="hover:bg-slate-50">
                    <td className="px-3 py-2 font-medium text-slate-800">{row.name}</td>
                    <td className="px-3 py-2 text-right tabular-nums">{row.count}</td>
                    <td className="px-3 py-2 text-right tabular-nums">{formatIDR(row.acquisition_cost)}</td>
                    <td className="px-3 py-2 text-right tabular-nums">{formatIDR(row.book_value)}</td>
                  </tr>
                ))}
                {(!s || s.location_breakdown.length === 0) && (
                  <tr>
                    <td className="px-3 py-6 text-center text-slate-400" colSpan={4}>
                      {t("common.empty")}
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
