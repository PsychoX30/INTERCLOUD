import React, { useEffect, useMemo, useState } from "react";
import { api } from "../../../portal/api";
import { PageHeader, Card, Loading, StatCard, btnPrimary, btnSecondary, inputClass, labelClass } from "../ui";
import {
  ShieldCheck, ShieldAlert, Activity, Users2, MapPin, TrendingUp, RefreshCw,
  Ban, ListChecks, BellRing, Save, Trash2, Plus, Send, CheckCircle2, XCircle, Loader2, AlertTriangle,
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

const TABS = [
  { key: "analytics",     label: "Analytics",      icon: Activity },
  { key: "rules",         label: "Block Rules",    icon: ListChecks },
  { key: "blocked",       label: "Blocked IPs",    icon: Ban },
  { key: "notifications", label: "Notifications",  icon: BellRing },
];

// ============================================================
const AdminSecurity = () => {
  const [tab, setTab] = useState("analytics");

  return (
    <div>
      <PageHeader
        title="Security"
        subtitle="Login analytics, auto-block rules, active blocks, and notification channels."
      />

      {/* Tabs */}
      <div className="flex flex-wrap gap-1 mb-5 bg-white border border-slate-200 rounded-xl p-1 w-fit" data-testid="security-tabs">
        {TABS.map((t) => {
          const Icon = t.icon;
          return (
            <button
              key={t.key}
              type="button"
              onClick={() => setTab(t.key)}
              data-testid={`security-tab-${t.key}`}
              className={`px-3 py-1.5 rounded-lg text-xs font-semibold flex items-center gap-1.5 transition-colors ${
                tab === t.key ? "bg-[#0a2350] text-white" : "text-slate-600 hover:text-[#0a2350]"
              }`}
            >
              <Icon className="h-3.5 w-3.5" /> {t.label}
            </button>
          );
        })}
      </div>

      {tab === "analytics"     && <AnalyticsPanel />}
      {tab === "rules"         && <RulesPanel />}
      {tab === "blocked"       && <BlockedIPsPanel />}
      {tab === "notifications" && <NotificationsPanel />}
    </div>
  );
};

// ============================================================
// Analytics
// ============================================================
const AnalyticsPanel = () => {
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
    Success: s.success, Failed: s.failed, "reCAPTCHA": s.recaptcha_block,
  }));

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <div className="flex rounded-xl border border-slate-200 bg-white p-1">
          {WINDOWS.map((w) => (
            <button key={w.key} data-testid={`security-window-${w.key}`} onClick={() => setWin(w.key)}
              className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition-colors ${
                win === w.key ? "bg-[#0a2350] text-white" : "text-slate-600 hover:text-[#0a2350]"
              }`}>{w.label}</button>
          ))}
        </div>
        <button className={btnSecondary} onClick={load} disabled={busy}>
          <RefreshCw className={`h-4 w-4 ${busy ? "animate-spin" : ""}`} /> Refresh
        </button>
      </div>

      <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
        <StatCard label="Total Attempts" value={T.attempts} testid="stat-attempts" />
        <StatCard label="Success Rate" value={`${T.success_rate}%`} tone="good" testid="stat-success-rate" />
        <StatCard label="Failed" value={T.failures} tone="warn" testid="stat-failures" />
        <StatCard label="Blocked by reCAPTCHA" value={T.recaptcha_blocks} tone={T.recaptcha_blocks > 0 ? "warn" : "muted"} testid="stat-recaptcha-blocks" />
      </div>

      <div className="grid lg:grid-cols-3 gap-4 mb-6">
        <Card className="lg:col-span-2 p-5">
          <div className="flex items-center gap-2 mb-3"><Activity className="h-4 w-4 text-[#0a2350]" /><h3 className="text-sm font-bold text-[#0a2350]">Attempts over time</h3></div>
          <div style={{ width: "100%", height: 260 }}>
            <ResponsiveContainer>
              <LineChart data={seriesData} margin={{ top: 8, right: 16, bottom: 4, left: -8 }}>
                <CartesianGrid stroke="#eef1f5" strokeDasharray="3 3" vertical={false} />
                <XAxis dataKey="bucket" tick={{ fontSize: 10 }} axisLine={false} tickLine={false} />
                <YAxis tick={{ fontSize: 10 }} axisLine={false} tickLine={false} allowDecimals={false} />
                <Tooltip contentStyle={{ fontSize: 12 }} />
                <Legend wrapperStyle={{ fontSize: 11 }} />
                <Line type="monotone" dataKey="Success" stroke="#16a34a" strokeWidth={2} dot={false} />
                <Line type="monotone" dataKey="Failed" stroke="#dc2626" strokeWidth={2} dot={false} />
                <Line type="monotone" dataKey="reCAPTCHA" stroke="#f5b120" strokeWidth={2} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </Card>
        <Card className="p-5">
          <div className="flex items-center gap-2 mb-1"><ShieldCheck className="h-4 w-4 text-emerald-600" /><h3 className="text-sm font-bold text-[#0a2350]">reCAPTCHA score distribution</h3></div>
          <div className="text-[11px] text-slate-500 mb-3">{data.score_distribution.total_scored} scored attempts</div>
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
        <Card className="p-5">
          <div className="flex items-center gap-2 mb-3"><MapPin className="h-4 w-4 text-red-600" /><h3 className="text-sm font-bold text-[#0a2350]">Top offending IPs</h3><span className="text-[10px] text-slate-500 ml-auto">Failed attempts</span></div>
          {data.top_ips.length === 0 ? <div className="text-sm text-slate-400 py-6 text-center">No failed attempts.</div> :
            <table className="w-full text-sm"><tbody>
              {data.top_ips.map((row) => <tr key={row.ip} className="border-t border-slate-100"><td className="py-2 font-mono text-xs">{row.ip}</td><td className="py-2 text-right font-bold text-red-700">{row.count}</td></tr>)}
            </tbody></table>}
        </Card>
        <Card className="p-5">
          <div className="flex items-center gap-2 mb-3"><Users2 className="h-4 w-4 text-amber-600" /><h3 className="text-sm font-bold text-[#0a2350]">Top targeted emails</h3></div>
          {data.top_emails.length === 0 ? <div className="text-sm text-slate-400 py-6 text-center">No failed attempts.</div> :
            <table className="w-full text-sm"><tbody>
              {data.top_emails.map((row) => <tr key={row.email} className="border-t border-slate-100"><td className="py-2 truncate max-w-[240px]" title={row.email}>{row.email}</td><td className="py-2 text-right font-bold text-amber-700">{row.count}</td></tr>)}
            </tbody></table>}
        </Card>
      </div>

      <Card className="p-5 mb-6">
        <div className="flex items-center gap-2 mb-3"><TrendingUp className="h-4 w-4 text-[#0a2350]" /><h3 className="text-sm font-bold text-[#0a2350]">Outcome breakdown</h3></div>
        <div className="flex flex-wrap gap-2">
          {data.reason_breakdown.map((r) => (
            <span key={r.reason} className={`px-3 py-1.5 rounded-full text-xs font-semibold border ${REASON_TONE[r.reason] || "bg-slate-50 text-slate-600 border-slate-200"}`}>
              {REASON_LABEL[r.reason] || r.reason} · {r.count}
            </span>
          ))}
          {data.reason_breakdown.length === 0 && <span className="text-sm text-slate-400">No data.</span>}
        </div>
      </Card>

      <Card className="p-0 overflow-hidden">
        <div className="px-5 py-4 border-b border-slate-100 flex items-center gap-2">
          <ShieldAlert className="h-4 w-4 text-[#0a2350]" />
          <h3 className="text-sm font-bold text-[#0a2350]">Recent attempts</h3>
          <span className="text-[10px] text-slate-500 ml-auto">Showing {data.recent.length} of {T.attempts}</span>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[720px] text-sm">
            <thead className="bg-slate-50 text-[10px] font-bold uppercase tracking-widest text-slate-500">
              <tr><th className="px-4 py-3 text-left">Time</th><th className="px-4 py-3 text-left">Email</th><th className="px-4 py-3 text-left">Action</th><th className="px-4 py-3 text-left">IP</th><th className="px-4 py-3 text-left">Outcome</th><th className="px-4 py-3 text-right">Score</th></tr>
            </thead>
            <tbody>
              {data.recent.map((r) => (
                <tr key={r.id} className="border-t border-slate-100">
                  <td className="px-4 py-2 text-xs text-slate-500">{fmtTime(r.created_at)}</td>
                  <td className="px-4 py-2 truncate max-w-[220px]" title={r.email}>{r.email || "—"}</td>
                  <td className="px-4 py-2 uppercase text-[10px] font-bold text-[#f5b120]">{r.action}</td>
                  <td className="px-4 py-2 font-mono text-xs">{r.ip}</td>
                  <td className="px-4 py-2">
                    <span className={`px-2 py-0.5 rounded-full text-[10px] font-bold border ${r.success ? "bg-emerald-50 text-emerald-700 border-emerald-200" : "bg-red-50 text-red-700 border-red-200"}`}>
                      {r.success ? "OK" : (REASON_LABEL[r.reason] || r.reason)}
                    </span>
                  </td>
                  <td className="px-4 py-2 text-right font-mono text-xs">
                    {typeof r.recaptcha_score === "number" ? r.recaptcha_score.toFixed(2) : "—"}
                  </td>
                </tr>
              ))}
              {data.recent.length === 0 && <tr><td colSpan={6} className="px-4 py-12 text-center text-slate-400">No login attempts recorded.</td></tr>}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
};

// ============================================================
// Block Rules
// ============================================================
const RulesPanel = () => {
  const [s, setS] = useState(null);
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState("");
  const [test, setTest] = useState(null);
  const [testing, setTesting] = useState(false);

  const load = async () => {
    const { data } = await api.get("/admin/security/settings");
    setS(data);
  };
  useEffect(() => { load(); }, []);
  if (!s) return <Loading />;

  const set = (k, v) => setS({ ...s, [k]: v });

  const save = async () => {
    setSaving(true); setMsg("");
    try {
      const { data } = await api.put("/admin/security/settings", {
        ...s,
        notify_emails: (typeof s.notify_emails === "string" ? s.notify_emails.split(/[,\n]/) : s.notify_emails).map((x) => (x || "").trim()).filter(Boolean),
        whitelist_ips: (typeof s.whitelist_ips === "string" ? s.whitelist_ips.split(/[,\n]/) : s.whitelist_ips).map((x) => (x || "").trim()).filter(Boolean),
      });
      setS(data); setMsg("Saved");
    } catch (e) {
      setMsg(e?.response?.data?.detail || e.message);
    } finally { setSaving(false); }
  };

  const runTest = async () => {
    setTesting(true); setTest(null);
    try {
      const { data } = await api.post("/admin/security/notifications/test", {});
      setTest(data);
    } catch (e) {
      setTest({ error: e?.response?.data?.detail || e.message });
    } finally { setTesting(false); }
  };

  const emailsText = Array.isArray(s.notify_emails) ? s.notify_emails.join("\n") : (s.notify_emails || "");
  const wlText = Array.isArray(s.whitelist_ips) ? s.whitelist_ips.join("\n") : (s.whitelist_ips || "");

  return (
    <div className="grid lg:grid-cols-2 gap-5" data-testid="security-rules">
      <Card className="p-5">
        <div className="flex items-center gap-2 mb-4">
          <ListChecks className="h-5 w-5 text-[#0a2350]" />
          <h3 className="text-base font-bold text-[#0a2350]">Auto-block rules</h3>
        </div>

        <label className="flex items-center gap-3 py-3 border-b border-slate-100" data-testid="rules-toggle">
          <input type="checkbox" checked={!!s.auto_block_enabled} onChange={(e) => set("auto_block_enabled", e.target.checked)} className="h-4 w-4" data-testid="rules-auto-block-toggle" />
          <div>
            <div className="text-sm font-bold text-[#0a2350]">Enable auto-block</div>
            <div className="text-xs text-slate-500">Automatically block IPs that fail too many logins in a short window.</div>
          </div>
        </label>

        <div className="grid grid-cols-3 gap-3 py-3">
          <div>
            <div className={labelClass}>Threshold (fails)</div>
            <input type="number" min="1" max="100" value={s.fail_threshold} onChange={(e) => set("fail_threshold", e.target.value)} className={inputClass} data-testid="rules-threshold" />
          </div>
          <div>
            <div className={labelClass}>Window (minutes)</div>
            <input type="number" min="1" max="1440" value={s.window_minutes} onChange={(e) => set("window_minutes", e.target.value)} className={inputClass} data-testid="rules-window" />
          </div>
          <div>
            <div className={labelClass}>Ban (minutes)</div>
            <input type="number" min="1" max="10080" value={s.ban_minutes} onChange={(e) => set("ban_minutes", e.target.value)} className={inputClass} data-testid="rules-ban" />
          </div>
        </div>

        <div className="text-xs text-slate-500 bg-slate-50 rounded-lg px-3 py-2 mb-3">
          Currently: block after <b>{s.fail_threshold}</b> failed attempts within <b>{s.window_minutes} min</b>, ban for <b>{s.ban_minutes} min</b>. Set threshold higher (e.g. 20/30) to reduce false positives.
        </div>

        <div className="py-3">
          <div className={labelClass}>Whitelist (IPs / CIDR, one per line)</div>
          <textarea rows={4} value={wlText} onChange={(e) => set("whitelist_ips", e.target.value)} className={`${inputClass} font-mono text-xs`} placeholder="127.0.0.1&#10;10.0.0.0/8&#10;192.168.1.100" data-testid="rules-whitelist" />
          <div className="text-[10px] text-slate-500 mt-1">Whitelisted IPs are <b>never</b> auto-blocked. Supports exact IPv4/IPv6 or CIDR ranges.</div>
        </div>

        <div className="flex items-center justify-end mt-2">
          <button onClick={save} disabled={saving} className={btnPrimary} data-testid="rules-save">
            {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />} Save rules
          </button>
        </div>
        {msg && <div className={`mt-3 text-xs ${msg === "Saved" ? "text-emerald-700" : "text-red-700"}`}>{msg}</div>}
      </Card>

      <Card className="p-5">
        <div className="flex items-center gap-2 mb-4">
          <BellRing className="h-5 w-5 text-[#0a2350]" />
          <h3 className="text-base font-bold text-[#0a2350]">Notification channels</h3>
        </div>

        <label className="flex items-center gap-3 py-3 border-b border-slate-100">
          <input type="checkbox" checked={!!s.email_notify_enabled} onChange={(e) => set("email_notify_enabled", e.target.checked)} className="h-4 w-4" data-testid="rules-email-toggle" />
          <div>
            <div className="text-sm font-bold text-[#0a2350]">Send email alerts</div>
            <div className="text-xs text-slate-500">Requires the <b>SMTP</b> integration to be configured & enabled.</div>
          </div>
        </label>
        <div className="py-3">
          <div className={labelClass}>Recipient emails (one per line)</div>
          <textarea rows={3} value={emailsText} onChange={(e) => set("notify_emails", e.target.value)} className={`${inputClass} font-mono text-xs`} placeholder="ops@example.com&#10;security@example.com" data-testid="rules-emails" />
        </div>

        <label className="flex items-center gap-3 py-3 border-t border-slate-100">
          <input type="checkbox" checked={!!s.telegram_notify_enabled} onChange={(e) => set("telegram_notify_enabled", e.target.checked)} className="h-4 w-4" data-testid="rules-telegram-toggle" />
          <div>
            <div className="text-sm font-bold text-[#0a2350]">Send Telegram alerts</div>
            <div className="text-xs text-slate-500">Requires the <b>Telegram Bot</b> integration to be configured & enabled.</div>
          </div>
        </label>

        <div className="flex items-center justify-end gap-2 mt-4">
          <button onClick={runTest} disabled={testing} className={btnSecondary} data-testid="rules-test-btn">
            {testing ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />} Send test alert
          </button>
          <button onClick={save} disabled={saving} className={btnPrimary}>
            {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />} Save channels
          </button>
        </div>
        {test && (
          <div className="mt-4 bg-slate-50 rounded-lg p-3 text-xs" data-testid="rules-test-result">
            <div className="font-bold text-slate-700 mb-2">Test result</div>
            <TestChannel name="Email" result={test.email} />
            <TestChannel name="Telegram" result={test.telegram} />
          </div>
        )}
      </Card>
    </div>
  );
};

const TestChannel = ({ name, result }) => {
  if (!result) return null;
  const ok = !!result.ok;
  const attempted = !!result.attempted;
  const Icon = ok ? CheckCircle2 : XCircle;
  return (
    <div className="flex items-start gap-2 py-1">
      <Icon className={`h-4 w-4 mt-0.5 ${ok ? "text-emerald-600" : (attempted ? "text-red-600" : "text-slate-400")}`} />
      <div className="flex-1">
        <div className="font-bold">{name}: {attempted ? (ok ? "sent" : "failed") : "not attempted"}</div>
        {result.reason && <div className="text-slate-500">{result.reason}</div>}
        {result.sent_to && <div className="text-slate-500">Recipients: {result.sent_to.join(", ")}</div>}
        {result.errors && result.errors.length > 0 && (
          <ul className="list-disc ml-4 text-red-700">{result.errors.map((e, i) => <li key={i}>{e}</li>)}</ul>
        )}
      </div>
    </div>
  );
};

// ============================================================
// Blocked IPs
// ============================================================
const BlockedIPsPanel = () => {
  const [rows, setRows] = useState(null);
  const [activeOnly, setActiveOnly] = useState(false);
  const [busy, setBusy] = useState(false);
  const [manualIp, setManualIp] = useState("");
  const [manualBan, setManualBan] = useState(60);

  const load = async () => {
    setBusy(true);
    try {
      const { data } = await api.get(`/admin/security/blocked-ips?active_only=${activeOnly}`);
      setRows(data);
    } finally { setBusy(false); }
  };
  useEffect(() => { load(); /* eslint-disable-line */ }, [activeOnly]);
  if (!rows) return <Loading />;

  const unblock = async (ip) => {
    if (!window.confirm(`Unblock ${ip}?`)) return;
    await api.delete(`/admin/security/blocked-ips/${encodeURIComponent(ip)}`);
    load();
  };

  const addManual = async (e) => {
    e.preventDefault();
    await api.post("/admin/security/blocked-ips", { ip: manualIp.trim(), ban_minutes: Number(manualBan), reason: "manual_block" });
    setManualIp(""); setManualBan(60); load();
  };

  return (
    <div data-testid="security-blocked">
      <div className="grid lg:grid-cols-3 gap-4 mb-5">
        <Card className="p-5 lg:col-span-2">
          <div className="flex items-center gap-2 mb-3">
            <Ban className="h-5 w-5 text-red-600" />
            <h3 className="text-base font-bold text-[#0a2350]">Blocked IPs</h3>
            <div className="ml-auto flex items-center gap-2">
              <label className="flex items-center gap-1 text-xs">
                <input type="checkbox" checked={activeOnly} onChange={(e) => setActiveOnly(e.target.checked)} className="h-3.5 w-3.5" data-testid="blocked-active-only" />
                Active only
              </label>
              <button onClick={load} disabled={busy} className={btnSecondary}>
                <RefreshCw className={`h-4 w-4 ${busy ? "animate-spin" : ""}`} />
              </button>
            </div>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 text-[10px] font-bold uppercase tracking-widest text-slate-500">
                <tr><th className="px-3 py-2 text-left">IP</th><th className="px-3 py-2 text-left">Blocked</th><th className="px-3 py-2 text-left">Expires</th><th className="px-3 py-2 text-left">Reason</th><th className="px-3 py-2 text-right">Hits</th><th className="px-3 py-2 text-left">State</th><th className="px-3 py-2"></th></tr>
              </thead>
              <tbody>
                {rows.length === 0 && <tr><td colSpan={7} className="px-3 py-10 text-center text-slate-400">No blocks recorded.</td></tr>}
                {rows.map((r) => (
                  <tr key={r.ip} className="border-t border-slate-100" data-testid={`blocked-row-${r.ip}`}>
                    <td className="px-3 py-2 font-mono text-xs font-bold">{r.ip}</td>
                    <td className="px-3 py-2 text-xs text-slate-500">{fmtTime(r.blocked_at)}</td>
                    <td className="px-3 py-2 text-xs text-slate-500">{fmtTime(r.expires_at)}</td>
                    <td className="px-3 py-2 text-xs uppercase font-bold text-amber-700">{r.reason}</td>
                    <td className="px-3 py-2 text-right tabular-nums">{r.hits}</td>
                    <td className="px-3 py-2">
                      <span className={`px-2 py-0.5 rounded-full text-[10px] font-bold border ${r.active ? "bg-red-50 text-red-700 border-red-200" : "bg-slate-50 text-slate-500 border-slate-200"}`}>
                        {r.active ? "ACTIVE" : "expired"}
                      </span>
                    </td>
                    <td className="px-3 py-2 text-right">
                      {r.active && (
                        <button onClick={() => unblock(r.ip)} className="text-xs text-red-600 hover:text-red-800" data-testid={`blocked-unblock-${r.ip}`}>
                          <Trash2 className="h-3 w-3 inline" /> Unblock
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>

        <Card className="p-5">
          <div className="flex items-center gap-2 mb-3">
            <Plus className="h-4 w-4 text-[#0a2350]" />
            <h3 className="text-base font-bold text-[#0a2350]">Manual block</h3>
          </div>
          <form onSubmit={addManual} className="space-y-3">
            <div>
              <div className={labelClass}>IP address</div>
              <input required value={manualIp} onChange={(e) => setManualIp(e.target.value)} className={`${inputClass} font-mono`} placeholder="203.0.113.42" data-testid="blocked-manual-ip" />
            </div>
            <div>
              <div className={labelClass}>Ban duration (minutes)</div>
              <input type="number" min="1" value={manualBan} onChange={(e) => setManualBan(e.target.value)} className={inputClass} data-testid="blocked-manual-min" />
            </div>
            <button type="submit" className={btnPrimary} data-testid="blocked-manual-submit">
              <Ban className="h-4 w-4" /> Block IP
            </button>
          </form>
        </Card>
      </div>
    </div>
  );
};

// ============================================================
// Notifications feed
// ============================================================
const NotificationsPanel = () => {
  const [rows, setRows] = useState(null);
  const load = async () => {
    const { data } = await api.get("/admin/security/notifications?limit=100");
    setRows(data);
  };
  useEffect(() => { load(); }, []);
  const markAll = async () => { await api.post("/admin/security/notifications/mark-read", {}); load(); };
  if (!rows) return <Loading />;

  return (
    <Card className="p-0 overflow-hidden" data-testid="security-notifications">
      <div className="px-5 py-4 border-b border-slate-100 flex items-center gap-2">
        <BellRing className="h-5 w-5 text-[#0a2350]" />
        <h3 className="text-base font-bold text-[#0a2350]">Security notifications</h3>
        <button onClick={markAll} className="ml-auto text-xs text-[#0a2350] hover:text-[#f5b120]" data-testid="notif-mark-all">Mark all read</button>
        <button onClick={load} className={btnSecondary}><RefreshCw className="h-3.5 w-3.5" /></button>
      </div>
      <div>
        {rows.length === 0 && <div className="px-5 py-10 text-center text-slate-400 text-sm">No notifications yet.</div>}
        {rows.map((n) => (
          <div key={n.id} className={`px-5 py-3 border-b border-slate-100 flex items-start gap-3 ${!n.read ? "bg-red-50/40" : ""}`} data-testid={`notif-${n.id}`}>
            <AlertTriangle className={`h-4 w-4 mt-0.5 ${!n.read ? "text-red-600" : "text-slate-400"}`} />
            <div className="flex-1 min-w-0">
              <div className="text-sm font-bold text-[#0a2350]">
                {n.kind === "ip_auto_blocked"
                  ? <>IP <span className="font-mono">{n.ip}</span> auto-blocked · {n.hits} failures</>
                  : n.kind}
              </div>
              <div className="text-xs text-slate-500">{fmtTime(n.created_at)} · ban {n.ban_minutes} min · window {n.window_minutes} min</div>
            </div>
            {!n.read && <span className="px-2 py-0.5 rounded-full text-[10px] font-bold border bg-red-50 text-red-700 border-red-200">NEW</span>}
          </div>
        ))}
      </div>
    </Card>
  );
};

export default AdminSecurity;
