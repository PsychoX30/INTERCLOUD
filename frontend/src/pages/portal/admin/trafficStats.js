// Aggregate stats for an IN/OUT traffic series.
//
// LibreNMS-compatible semantics:
// - 95th percentile uses the plotted AVERAGE series, never the MAX envelope.
// - Maximum still uses server-provided per-bucket MAX values.
// - Transfer volume integrates every row using the API's resolved tier step.
//   It never infers width from adjacent timestamps: missing buckets, split
//   IN/OUT rows, and mixed archive sources must not change a bucket's width.

const RESOLUTION_SECONDS = {
  halfhour: 30 * 60,
  hourly: 60 * 60,
  daily: 24 * 60 * 60,
};

const resolutionStep = (resolution, intervalSec) => {
  const name = String(resolution || "").toLowerCase();
  if (name.startsWith("halfhour")) return RESOLUTION_SECONDS.halfhour;
  if (name.startsWith("hourly")) return RESOLUTION_SECONDS.hourly;
  if (name.startsWith("daily")) return RESOLUTION_SECONDS.daily;
  return Number(intervalSec) > 0 ? Number(intervalSec) : 300;
};

export function trafficStats(merged, options = {}) {
  // Keep the old numeric argument compatible for callers outside this module.
  const normalized = typeof options === "number" ? { intervalSec: options } : (options || {});
  const { intervalSec = 300, resolution = "raw", fromMs = null, toMs = null } = normalized;
  const stepSec = resolutionStep(resolution, intervalSec);
  const stepMs = stepSec * 1000;

  const nums = (arr) => arr.filter(v => v != null && Number.isFinite(Number(v))).map(Number);
  const inVals = nums(merged.map(d => d.in));
  const outVals = nums(merged.map(d => d.out));
  const inExtremes = nums(merged.map(d => d.inMax));
  const outExtremes = nums(merged.map(d => d.outMax));
  const avg = (arr) => (arr.length ? arr.reduce((a, b) => a + b, 0) / arr.length : null);
  const percentile95 = (arr) => {
    if (!arr.length) return null;
    const sorted = [...arr].sort((a, b) => a - b);
    const idx = Math.ceil(sorted.length * 0.95) - 1;
    return sorted[Math.max(0, idx)];
  };

  // A rollup timestamp is the bucket start. Clamp boundary buckets to the
  // requested range. Raw points use the configured poll interval because they
  // are observations, not calendar-aligned rollup buckets.
  const rowSeconds = (row) => {
    if (String(resolution || "").toLowerCase().startsWith("raw")) return stepSec;
    const start = Number(row?.ts);
    if (!Number.isFinite(start)) return stepSec;
    const hasFrom = fromMs != null && Number.isFinite(Number(fromMs));
    const hasTo = toMs != null && Number.isFinite(Number(toMs));
    const left = hasFrom ? Math.max(start, Number(fromMs)) : start;
    const end = start + stepMs;
    const right = hasTo ? Math.min(end, Number(toMs)) : end;
    return Math.max(0, right - left) / 1000;
  };
  const transferGB = (dir) => {
    let bitSeconds = 0;
    let count = 0;
    merged.forEach((row) => {
      const value = Number(row?.[dir]);
      if (!Number.isFinite(value)) return;
      bitSeconds += value * rowSeconds(row);
      count += 1;
    });
    return count ? bitSeconds / 8 / 1e9 : null;
  };
  const peakOf = (vals, extremes) => {
    const candidates = [...vals, ...extremes];
    return candidates.length ? Math.max(...candidates) : null;
  };

  return {
    maxIn: peakOf(inVals, inExtremes),
    maxOut: peakOf(outVals, outExtremes),
    avgIn: avg(inVals),
    avgOut: avg(outVals),
    percentile95In: percentile95(inVals),
    percentile95Out: percentile95(outVals),
    totalInGB: transferGB("in"),
    totalOutGB: transferGB("out"),
    bucketSeconds: stepSec,
    currentIn: inVals.length ? inVals[inVals.length - 1] : null,
    currentOut: outVals.length ? outVals[outVals.length - 1] : null,
    peaksFromRollup: inExtremes.length > 0 || outExtremes.length > 0,
  };
}

export default trafficStats;
