import React, { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { AlertTriangle, ArrowRight, CheckCircle2, RefreshCw, ShieldAlert } from "lucide-react";
import { api } from "../../../portal/api";
import { PageHeader, StatCard, Card, Loading, btnSecondary } from "../ui";

// The overview endpoint returns `null` for any counter it could not read.
// Rendering an em dash instead of 0 is deliberate: "unknown" and "zero" are
// different operational facts, and a confident 0 on a broken query is exactly
// the silent failure this page exists to prevent.
const num = (value) => (value === null || value === undefined ? "—" : value);

const LEVEL_STYLES = {
  critical: "border-red-200 bg-red-50 text-red-700",
  warning: "border-amber-200 bg-amber-50 text-amber-800",
  info: "border-slate-200 bg-slate-50 text-slate-700",
};

const AttentionRow = ({ item }) => (
  <Link
    to={item.link}
    data-testid={`ops-attention-${item.area}`}
    className={`flex items-start gap-3 rounded-xl border p-3 hover:shadow-sm transition-shadow ${
      LEVEL_STYLES[item.level] || LEVEL_STYLES.info
    }`}
  >
    <div className="mt-0.5">
      {item.level === "critical" ? (
        <ShieldAlert className="h-4 w-4" />
      ) : (
        <AlertTriangle className="h-4 w-4" />
      )}
    </div>
    <div className="min-w-0 flex-1">
      <div className="text-sm font-bold text-[#0a2350]">{item.title}</div>
      <div className="text-xs opacity-80">{item.detail}</div>
    </div>
    <ArrowRight className="h-4 w-4 opacity-60" />
  </Link>
);

const AdminOps = () => {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const res = await api.get("/admin/ops/overview");
      setData(res.data);
    } catch (e) {
      // Never paper over a failed aggregate: show the failure explicitly.
      setError(e?.response?.data?.detail || "Failed to load the operations overview.");
      setData(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const summary = data?.summary || {};
  const monitoring = summary.monitoring || {};
  const noc = summary.noc || {};
  const sla = summary.sla || {};
  const security = summary.security || {};
  const audit = summary.audit || {};
  const attention = data?.attention || [];
  const sourceStatus = data?.source_status || {};
  const degraded = Object.keys(sourceStatus);

  return (
    <div>
      <PageHeader
        title="Ops Overview"
        subtitle="One read-only view across monitoring, NOC, SLA, security, and audit. Every number is aggregated from the owning module — nothing is stored twice."
        actions={
          <button
            type="button"
            onClick={load}
            className={btnSecondary}
            data-testid="ops-refresh"
            disabled={loading}
          >
            <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} /> Refresh
          </button>
        }
      />

      {error && (
        <div className="mb-4 rounded-xl border border-red-200 bg-red-50 p-3 text-sm text-red-700" data-testid="ops-error">
          {error}
        </div>
      )}

      {loading && !data && <Loading label="Aggregating operations data…" />}

      {data && (
        <>
          {degraded.length > 0 && (
            <div
              className="mb-4 rounded-xl border border-amber-200 bg-amber-50 p-3 text-xs text-amber-800"
              data-testid="ops-degraded"
            >
              <span className="font-bold">Partial data.</span> These areas could not be fully read, so their
              counters show “—” instead of a number:{" "}
              {degraded.map((area) => (
                <span key={area} className="ml-1 inline-flex items-center rounded bg-white px-1.5 py-0.5 font-semibold uppercase tracking-wide">
                  {area}
                </span>
              ))}
            </div>
          )}

          <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-3 mb-6">
            <StatCard label="Checks" value={num(monitoring.checks)} hint="registered" testid="ops-checks" />
            <StatCard label="Down" value={num(monitoring.down)} hint="confirmed" tone={monitoring.down > 0 ? "danger" : "good"} testid="ops-down" />
            <StatCard label="Pending" value={num(monitoring.pending)} hint="retry window" tone={monitoring.pending > 0 ? "warn" : "default"} testid="ops-pending" />
            <StatCard label="Devices" value={num(noc.devices)} hint={`${num(noc.down)} down · ${num(noc.unknown)} unknown`} tone={noc.down > 0 ? "danger" : "default"} testid="ops-devices" />
            <StatCard label="Open SLA" value={num(sla.open_incidents)} hint="unresolved incidents" tone={sla.open_incidents > 0 ? "warn" : "good"} testid="ops-sla-open" />
            <StatCard label="Undelivered" value={num(monitoring.undelivered_alerts)} hint="alerts queued" tone={monitoring.undelivered_alerts > 0 ? "warn" : "default"} testid="ops-undelivered" />
          </div>

          <div className="grid lg:grid-cols-3 gap-4">
            <Card className="lg:col-span-2 p-4">
              <div className="flex items-center justify-between mb-3">
                <h2 className="text-sm font-extrabold uppercase tracking-widest text-slate-600">Needs attention</h2>
                <span className="text-xs text-slate-400" data-testid="ops-attention-count">
                  {attention.length} item{attention.length === 1 ? "" : "s"}
                </span>
              </div>
              {attention.length === 0 ? (
                <div className="flex items-center gap-2 py-10 justify-center text-sm text-emerald-700" data-testid="ops-all-clear">
                  <CheckCircle2 className="h-5 w-5" /> Nothing needs attention in the last {data.lookback_hours} hours.
                </div>
              ) : (
                <div className="space-y-2">
                  {attention.map((item, index) => (
                    <AttentionRow key={`${item.area}-${item.title}-${index}`} item={item} />
                  ))}
                </div>
              )}
            </Card>

            <Card className="p-4">
              <h2 className="text-sm font-extrabold uppercase tracking-widest text-slate-600 mb-3">Breakdown</h2>
              <dl className="space-y-2 text-sm">
                <div className="flex justify-between gap-2">
                  <dt className="text-slate-500">Alerts exhausted</dt>
                  <dd className="font-bold text-[#0a2350]">{num(monitoring.exhausted_alerts)}</dd>
                </div>
                <div className="flex justify-between gap-2">
                  <dt className="text-slate-500">Disabled checks</dt>
                  <dd className="font-bold text-[#0a2350]">{num(monitoring.disabled)}</dd>
                </div>
                <div className="flex justify-between gap-2">
                  <dt className="text-slate-500">NOC events (7d)</dt>
                  <dd className="font-bold text-[#0a2350]">{num(noc.recent_events)}</dd>
                </div>
                <div className="flex justify-between gap-2">
                  <dt className="text-slate-500">SLA incidents (7d)</dt>
                  <dd className="font-bold text-[#0a2350]">{num(sla.recent_incidents)}</dd>
                </div>
                <div className="flex justify-between gap-2">
                  <dt className="text-slate-500">Active IP blocks</dt>
                  <dd className="font-bold text-[#0a2350]">{num(security.active_blocks)}</dd>
                </div>
                <div className="flex justify-between gap-2">
                  <dt className="text-slate-500">Security notices (7d)</dt>
                  <dd className="font-bold text-[#0a2350]">{num(security.recent_notifications)}</dd>
                </div>
                <div className="flex justify-between gap-2">
                  <dt className="text-slate-500">Critical audit (7d)</dt>
                  <dd className="font-bold text-[#0a2350]">{num(audit.recent_critical)}</dd>
                </div>
              </dl>
              <div className="mt-4 border-t border-slate-100 pt-3 text-[11px] text-slate-400">
                Aggregated {data.generated_at ? new Date(data.generated_at).toLocaleString() : "—"} · read-only
              </div>
            </Card>
          </div>

          <div className="mt-4 grid sm:grid-cols-2 lg:grid-cols-5 gap-2">
            {[
              { to: "/portal/admin/monitoring", label: "Monitoring" },
              { to: "/portal/admin/noc", label: "NOC Monitor" },
              { to: "/portal/admin/sla", label: "SLA & Incidents" },
              { to: "/portal/admin/security", label: "Security" },
              { to: "/portal/admin/audit-log", label: "Audit Log" },
            ].map((link) => (
              <Link
                key={link.to}
                to={link.to}
                className="flex items-center justify-between rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm font-semibold text-[#0a2350] hover:border-[#f5b120]"
              >
                {link.label} <ArrowRight className="h-4 w-4" />
              </Link>
            ))}
          </div>
        </>
      )}
    </div>
  );
};

export default AdminOps;
