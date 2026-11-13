import React, { useEffect, useState, useCallback } from "react";
import { Activity, AlertTriangle, WifiOff, RefreshCw } from "lucide-react";
import { api } from "../../../portal/api";

// Sampling pipeline health, derived from the live netflow snapshot endpoint.
//
// Why this exists: after the goflow2 socket-buffer fix, a collector that stops
// writing is the failure mode that silently turns every NOC widget into
// "nothing is happening". A page showing "0 attacks" is indistinguishable from
// "sampling is dead" unless the pipeline itself is surfaced. This badge makes
// that distinction explicit and shared across every NOC surface.
//
// The thresholds mirror the backend contract in `GoFlow2Client`:
//   STALE_AFTER_S = 300  -> the collector is considered stalled
// A file age under 60s is fresh; 60-300s is degraded (things are lagging);
// past 300s it is down and any DDoS conclusion is invalid.
const FRESH_S = 60;
const STALE_S = 300;

const derive = (payload) => {
  if (!payload) return { state: "unknown", ageS: null, source: null };
  const ageS = typeof payload.file_age_s === "number" ? payload.file_age_s : null;
  const source = payload.source || null;
  if (payload.stale) return { state: "down", ageS, source };
  if (ageS == null) return { state: "unknown", ageS, source };
  if (ageS <= FRESH_S) return { state: "fresh", ageS, source };
  if (ageS <= STALE_S) return { state: "degraded", ageS, source };
  return { state: "down", ageS, source };
};

const humanAge = (s) => {
  if (s == null) return "unknown";
  if (s < 60) return `${Math.round(s)}s ago`;
  if (s < 3600) return `${Math.round(s / 60)}m ago`;
  return `${Math.round(s / 3600)}h ago`;
};

const TONE = {
  fresh: {
    cls: "bg-emerald-50 text-emerald-700 border-emerald-200",
    dot: "bg-emerald-500",
    label: "Sampling live",
    Icon: Activity,
  },
  degraded: {
    cls: "bg-amber-50 text-amber-800 border-amber-200",
    dot: "bg-amber-500 motion-safe:animate-pulse",
    label: "Sampling lagging",
    Icon: AlertTriangle,
  },
  down: {
    cls: "bg-red-50 text-red-700 border-red-200",
    dot: "bg-red-500 motion-safe:animate-pulse",
    label: "Sampling stalled",
    Icon: WifiOff,
  },
  unknown: {
    cls: "bg-slate-100 text-slate-600 border-slate-300",
    dot: "bg-slate-400",
    label: "Sampling unknown",
    Icon: AlertTriangle,
  },
};

/**
 * Compact freshness pill. `compact` renders the inline variant used in page
 * headers; the default renders the full pill with source + age.
 */
export const SamplingBadge = ({ payload, compact = false, testid = "sampling-badge" }) => {
  const { state, ageS, source } = derive(payload);
  const tone = TONE[state];
  const Icon = tone.Icon;
  const title =
    state === "down"
      ? `The flow collector has not written anything for ${humanAge(ageS)}. DDoS detection cannot conclude "no attack" while sampling is stalled.`
      : `Source: ${source || "unknown"} · last write ${humanAge(ageS)}`;

  if (compact) {
    return (
      <span
        title={title}
        data-testid={testid}
        data-state={state}
        className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full border text-[10px] font-bold uppercase tracking-widest ${tone.cls}`}
      >
        <span className={`h-1.5 w-1.5 rounded-full ${tone.dot}`} />
        {tone.label}
      </span>
    );
  }

  return (
    <span
      title={title}
      data-testid={testid}
      data-state={state}
      className={`inline-flex items-center gap-2 px-3 py-1.5 rounded-lg border text-xs font-semibold ${tone.cls}`}
    >
      <Icon className="h-3.5 w-3.5" />
      {tone.label}
      {ageS != null && <span className="font-normal opacity-80">· {humanAge(ageS)}</span>}
      {source && <span className="font-mono text-[10px] opacity-60">[{source}]</span>}
    </span>
  );
};

/**
 * Fetches the netflow snapshot and exposes its freshness, so a page can gate
 * DDoS/NOC conclusions on the pipeline actually being alive.
 */
export const useSamplingHealth = (pollMs = 30000) => {
  const [payload, setPayload] = useState(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setBusy(true);
    try {
      const { data } = await api.get("/admin/noc/netflow/sankey");
      setPayload(data);
    } catch {
      // Keep the previous reading: a transient API failure is not the same
      // event as the collector going silent, and must not be reported as such.
    } finally {
      setBusy(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    if (!pollMs) return undefined;
    const t = setInterval(load, pollMs);
    return () => clearInterval(t);
  }, [load, pollMs]);

  const derived = derive(payload);
  return { payload, ...derived, reload: load, busy };
};

/**
 * Full-width warning strip. Renders nothing when sampling is healthy so it
 * never becomes wallpaper that operators learn to ignore.
 */
export const SamplingAlert = ({ health, context = "DDoS detection" }) => {
  if (!health || (health.state !== "down" && health.state !== "degraded")) return null;
  const down = health.state === "down";
  return (
    <div
      data-testid="sampling-alert"
      data-state={health.state}
      className={`mb-4 rounded-xl border p-4 text-sm flex items-start gap-3 ${
        down ? "bg-red-50 border-red-200 text-red-800" : "bg-amber-50 border-amber-200 text-amber-800"
      }`}
    >
      {down ? <WifiOff className="h-5 w-5 mt-0.5 shrink-0" /> : <AlertTriangle className="h-5 w-5 mt-0.5 shrink-0" />}
      <div>
        <div className="font-bold">
          {down ? "Flow sampling is stalled" : "Flow sampling is lagging"}
        </div>
        <div className="mt-0.5">
          Last collector write was <b>{humanAge(health.ageS)}</b>
          {health.source ? <> via <b className="font-mono">{health.source}</b></> : null}.
          {" "}{down
            ? `${context} cannot conclude "no attack" on stale data — fix the collector before trusting the numbers below.`
            : `Rates below may be undercounted until the collector catches up.`}
        </div>
        <div className="mt-1.5 flex items-center gap-2 text-xs">
          <button
            type="button"
            onClick={health.reload}
            disabled={health.busy}
            className="inline-flex items-center gap-1 font-semibold underline hover:no-underline disabled:opacity-50"
            data-testid="sampling-alert-refresh"
          >
            <RefreshCw className={`h-3 w-3 ${health.busy ? "animate-spin" : ""}`} /> Re-check now
          </button>
        </div>
      </div>
    </div>
  );
};

export default SamplingBadge;
