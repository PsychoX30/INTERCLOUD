import React, { useEffect, useMemo, useState } from "react";
import { api } from "../../../portal/api";
import { PageHeader, Card, Loading, StatCard, btnPrimary, btnSecondary } from "../ui";
import {
  ShieldCheck, ShieldAlert, Activity, Users2, MapPin, TrendingUp, RefreshCw,
} from "lucide-react";
import {
  ResponsiveContainer, LineChart, Line, XAxis, YAxis, Tooltip, CartesianGrid, Legend,
  BarChart, Bar,
} from "recharts";

const WINDOWS = [
  { key: "24h", label: "Last 24h" },
  { key: "7d",  label: "Last 7 days" },
  { key: "30d", label: "Last 30 days" },
];

const REASON_LABEL = {
  ok: "OK",
  invalid_credentials: "Invalid credentials",
  recaptcha_missing: "reCAPTCHA missing",
  recaptcha_failed: "reCAPTCHA failed",
  recaptcha_low_score: "reCAPTCHA low score",
  account_exists: "Account exists",
  tos_required: "TOS not accepted",
};

const REASON_TONE = {
  ok: "text-emerald-700 bg-emerald-50 border-emerald-200",
  invalid_credentials: "text-red-700 bg-red-50 border-red-200",
  recaptcha_missing: "text-amber-700 bg-amber-50 border-amber-200",
  recaptcha_failed: "text-amber-700 bg-amber-50 border-amber-200",
  recaptcha_low_score: "text-amber-700 bg-amber-50 border-amber-200",
};

const fmtTime = (iso) => {
  if (!iso) return "—";
  try { return new Date(iso).toLocaleString("id-ID", { hour: "2-digit", minute: "2-digit", month: "short", day: "2-digit" }); }
  catch { return iso.slice(0, 19); }
};

const AdminSecurity = () => {
  const [win, setWin] = useState("24h");
  const [data, setData] = useState(null);
  const [busy, setBusy] = useState(false);

  const load = async () => {
    setBusy(true);
    try {
      const { data } = await api.get(`/admin/security/login-analytics?window=${win}&limit=100`);
      setData(data);
    } finally { setBusy(false); }
  };

  useEffect(() => { load(); /* eslint-disable-line */ }, [win]);
  if (!data) return <Loading />;

  const T = data.totals;
  const seriesData = (data.series || []).map((s) => ({
    bucket: s.bucket.length > 10 ? s.bucket.slice(11) : s.bucket,
    Success: s.success,
    Failed: s.failed,
    "reCAPTCHA": s.recaptcha_block,
  }));

  return (
    <div>
      <PageHeader
        title="Login Attempt Analytics"
        subtitle="Track authentication traffic, spot brute-force patterns, and monitor Google reCAPTCHA v3 score distribution."
        actions={
          <div className="flex items-center gap-2" data-testid="security-toolbar">
            <div className="flex rounded-xl border border-slate-200 bg-white p-1">
              {WINDOWS.map((w) => (
                <button
                  key={w.key}
                  data-testid={`security-window-${w.key}`}
                  onClick={() => setWin(w.key)}
                  className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition-colors ${
                    win === w.key
                      ? "bg-[#0a2350] text-white"
                      : "text-slate-600 hover:text-[#0a2350]"
                  }`}
                >{w.label}</button>
              ))}
            </div>
            <button className={btnSecondary} onClick={load} disabled={busy} data-testid="security-refresh">
              <RefreshCw className={`h-4 w-4 ${busy ? "animate-spin" : ""}`} /> Refresh
            </button>
          </div>
        }
      />

      <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
        <StatCard label="Total Attempts" value={T.attempts} testid="stat-attempts" />
        <StatCard label="Success Rate" value={`${T.success_rate}%`} tone="good" testid="stat-success-rate" />
        <StatCard label="Failed" value={T.failures} tone="warn" testid="stat-failures" />
        <StatCard label="Blocked by reCAPTCHA" value={T.recaptcha_blocks} tone={T.recaptcha_blocks > 0 ? "warn" : "muted"} testid="stat-recaptcha-blocks" />
      </div>

      <div className="grid lg:grid-cols-3 gap-4 mb-6">
        {/* Attempts over time */}
        <Card className="lg:col-span-2 p-5" data-testid="chart-attempts-over-time">
          <div className="flex items-center gap-2 mb-3">
            <Activity className="h-4 w-4 text-[#0a2350]" />
            <h3 className="text-sm font-bold text-[#0a2350]">Attempts over time</h3>
          </div>
          <div style={{ width: "100%", height: 260 }}>
            <ResponsiveContainer>
              <LineChart data={seriesData} margin={{ top: 8, right: 16, bottom: 4, left: -8 }}>
                <CartesianGrid stroke="#eef1f5" strokeDasharray="3 3" vertical={false} />
                <XAxis dataKey="bucket" tick={{ fontSize: 10 }} axisLine={false} tickLine={false} />
                <YAxis tick={{ fontSize: 10 }} axisLine={false} tickLine={false} allowDecimals={false} />
                <Tooltip contentStyle={{ fontSize: 12 }} />
                <Legend wrapperStyle={{ fontSize: 11 }} />
                <Line type="monotone" dataKey="Success" stroke="#16a34a" strokeWidth={2} dot={false} />
                <Line type="monotone" dataKey="Failed"  stroke="#dc2626" strokeWidth={2} dot={false} />
                <Line type="monotone" dataKey="reCAPTCHA" stroke="#f5b120" strokeWidth={2} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </Card>

        {/* reCAPTCHA score histogram */}
        <Card className="p-5" data-testid="chart-recaptcha-scores">
          <div className="flex items-center gap-2 mb-1">
            <ShieldCheck className="h-4 w-4 text-emerald-600" />
            <h3 className="text-sm font-bold text-[#0a2350]">reCAPTCHA score distribution</h3>
          </div>
          <div className="text-[11px] text-slate-500 mb-3">
            {data.score_distribution.total_scored} scored attempts
          </div>
          <div style={{ width: "100%", height: 220 }}>
            <ResponsiveContainer>
              <BarChart data={data.score_distribution.buckets} margin={{ top: 8, right: 8, bottom: 4, left: -12 }}>
                <CartesianGrid stroke="#eef1f5" strokeDasharray="3 3" vertical={false} />
                <XAxis dataKey="bucket" tick={{ fontSize: 10 }} axisLine={false} tickLine={false} />
                <YAxis tick={{ fontSize: 10 }} axisLine={false} tickLine={false} allowDecimals={false} />
                <Tooltip contentStyle={{ fontSize: 12 }} />
                <Bar dataKey="count" fill="#0a2350" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </Card>
      </div>

      <div className="grid lg:grid-cols-2 gap-4 mb-6">
        <Card className="p-5" data-testid="table-top-ips">
          <div className="flex items-center gap-2 mb-3">
            <MapPin className="h-4 w-4 text-red-600" />
            <h3 className="text-sm font-bold text-[#0a2350]">Top offending IPs</h3>
            <span className="text-[10px] text-slate-500 ml-auto">Failed attempts</span>
          </div>
          {data.top_ips.length === 0 ? (
            <div className="text-sm text-slate-400 py-6 text-center">No failed attempts in this window.</div>
          ) : (
            <table className="w-full text-sm">
              <tbody>
                {data.top_ips.map((row) => (
                  <tr key={row.ip} className="border-t border-slate-100">
                    <td className="py-2 font-mono text-xs">{row.ip}</td>
                    <td className="py-2 text-right font-bold text-red-700">{row.count}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>

        <Card className="p-5" data-testid="table-top-emails">
          <div className="flex items-center gap-2 mb-3">
            <Users2 className="h-4 w-4 text-amber-600" />
            <h3 className="text-sm font-bold text-[#0a2350]">Top targeted emails</h3>
            <span className="text-[10px] text-slate-500 ml-auto">Failed attempts</span>
          </div>
          {data.top_emails.length === 0 ? (
            <div className="text-sm text-slate-400 py-6 text-center">No failed attempts in this window.</div>
          ) : (
            <table className="w-full text-sm">
              <tbody>
                {data.top_emails.map((row) => (
                  <tr key={row.email} className="border-t border-slate-100">
                    <td className="py-2 truncate max-w-[240px]" title={row.email}>{row.email}</td>
                    <td className="py-2 text-right font-bold text-amber-700">{row.count}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>
      </div>

      {/* Reason breakdown pill row */}
      <Card className="p-5 mb-6" data-testid="reason-breakdown">
        <div className="flex items-center gap-2 mb-3">
          <TrendingUp className="h-4 w-4 text-[#0a2350]" />
          <h3 className="text-sm font-bold text-[#0a2350]">Outcome breakdown</h3>
        </div>
        <div className="flex flex-wrap gap-2">
          {data.reason_breakdown.map((r) => (
            <span key={r.reason}
                  className={`px-3 py-1.5 rounded-full text-xs font-semibold border ${REASON_TONE[r.reason] || "bg-slate-50 text-slate-600 border-slate-200"}`}>
              {REASON_LABEL[r.reason] || r.reason} · {r.count}
            </span>
          ))}
          {data.reason_breakdown.length === 0 && (
            <span className="text-sm text-slate-400">No data in this window.</span>
          )}
        </div>
      </Card>

      {/* Recent attempts table */}
      <Card className="p-0 overflow-hidden" data-testid="table-recent">
        <div className="px-5 py-4 border-b border-slate-100 flex items-center gap-2">
          <ShieldAlert className="h-4 w-4 text-[#0a2350]" />
          <h3 className="text-sm font-bold text-[#0a2350]">Recent attempts</h3>
          <span className="text-[10px] text-slate-500 ml-auto">Showing {data.recent.length} of {T.attempts}</span>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[720px] text-sm">
            <thead className="bg-slate-50 text-[10px] font-bold uppercase tracking-widest text-slate-500">
              <tr>
                <th className="px-4 py-3 text-left">Time</th>
                <th className="px-4 py-3 text-left">Email</th>
                <th className="px-4 py-3 text-left">Action</th>
                <th className="px-4 py-3 text-left">IP</th>
                <th className="px-4 py-3 text-left">Outcome</th>
                <th className="px-4 py-3 text-right">Score</th>
              </tr>
            </thead>
            <tbody>
              {data.recent.map((r) => (
                <tr key={r.id} className="border-t border-slate-100" data-testid={`recent-row-${r.id}`}>
                  <td className="px-4 py-2 text-xs text-slate-500">{fmtTime(r.created_at)}</td>
                  <td className="px-4 py-2 truncate max-w-[220px]" title={r.email}>{r.email || "—"}</td>
                  <td className="px-4 py-2 uppercase text-[10px] font-bold text-[#f5b120]">{r.action}</td>
                  <td className="px-4 py-2 font-mono text-xs">{r.ip}</td>
                  <td className="px-4 py-2">
                    <span className={`px-2 py-0.5 rounded-full text-[10px] font-bold border ${
                      r.success
                        ? "bg-emerald-50 text-emerald-700 border-emerald-200"
                        : "bg-red-50 text-red-700 border-red-200"
                    }`}>{r.success ? "OK" : (REASON_LABEL[r.reason] || r.reason)}</span>
                  </td>
                  <td className="px-4 py-2 text-right font-mono text-xs">
                    {typeof r.recaptcha_score === "number" ? r.recaptcha_score.toFixed(2) : "—"}
                  </td>
                </tr>
              ))}
              {data.recent.length === 0 && (
                <tr><td colSpan={6} className="px-4 py-12 text-center text-slate-400">No login attempts recorded in this window.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
};

export default AdminSecurity;
