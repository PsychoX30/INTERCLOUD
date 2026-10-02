// Build the explicit absolute window for a range preset (1H / 1D / 1W / 1M / 1Y).
//
// Why this exists: the range buttons used to call setFrom(...) and then
// immediately trigger the data load. React state updates are not synchronous,
// so the loader still read the PREVIOUS `from` out of its closure and every
// preset requested the same window — 1D, 1W, 1M and 1Y rendered identically.
// Computing the window here lets the caller pass it straight to the loader
// instead of depending on state that has not been applied yet.
// Return a safe numeric time domain for Recharts. Never leave a numeric XAxis
// without a domain: Recharts can include the Unix epoch and squeeze modern data
// into the right edge of the plot.
export const chartXDomain = (from, to) => {
  const fromMs = Date.parse(from || "");
  const toMs = Date.parse(to || "");
  if (Number.isFinite(fromMs) && Number.isFinite(toMs) && toMs > fromMs) {
    return [fromMs, toMs];
  }
  return ["dataMin", "dataMax"];
};

export const presetWindow = (hours, nowMs) => {
  const h = Number(hours);
  if (!Number.isFinite(h) || h <= 0) return null;
  const end = Number.isFinite(Number(nowMs)) ? Number(nowMs) : Date.now();
  return {
    from: new Date(end - h * 3600 * 1000).toISOString(),
    to: new Date(end).toISOString(),
  };
};

// Monitoring samples originate from Python's UTC datetimes. Older API payloads
// omit the Z suffix, and JavaScript otherwise interprets those as browser-local
// time. Normalize that wire format before plotting or comparing it to a range.
export const parseApiTs = (value) => {
  if (typeof value !== "string" || !value) return null;
  const normalized = /(?:Z|[+-]\d\d:\d\d)$/.test(value) ? value : `${value}Z`;
  const ms = Date.parse(normalized);
  return Number.isFinite(ms) ? ms : null;
};

export const DISPLAY_TZ = "Asia/Jakarta";

// Number(null) === 0 is finite, so a bare Number.isFinite check turns a missing
// timestamp into the 1970 epoch. Reject null/undefined/"" explicitly.
const finiteMs = (value) => {
  if (value == null || value === "") return null;
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
};

// Accept either epoch milliseconds or an API/ISO timestamp string.
const toMs = (value) => (typeof value === "string" ? parseApiTs(value) : finiteMs(value));

export const formatGraphTick = (timestamp, spanMs) => {
  const ms = finiteMs(timestamp);
  if (ms == null) return "";
  const date = new Date(ms);
  const common = { timeZone: DISPLAY_TZ, hour12: false };
  if (spanMs <= 2 * 86400000) {
    return new Intl.DateTimeFormat("en-GB", { ...common, hour: "2-digit", minute: "2-digit" }).format(date);
  }
  if (spanMs <= 180 * 86400000) {
    return new Intl.DateTimeFormat("en-GB", { ...common, day: "2-digit", month: "short" }).format(date);
  }
  return new Intl.DateTimeFormat("en-GB", { ...common, month: "short", year: "numeric" }).format(date);
};

export const earliestSampleMs = (rows) => {
  const values = (rows || []).map((row) => finiteMs(row?.ts)).filter((v) => v != null);
  return values.length ? Math.min(...values) : null;
};

// Only display a note for a material history gap. Small gaps are normal polling
// jitter; 15% of the selected window is large enough to affect interpretation.
// Window bounds are accepted as ISO strings (component state) or epoch ms (tests).
export const historyGapNote = (from, to, dataFrom) => {
  const windowFrom = toMs(from);
  const windowTo = toMs(to);
  const first = finiteMs(dataFrom);
  if (windowFrom == null || windowTo == null || windowTo <= windowFrom || first == null) return null;
  const gapMs = first - windowFrom;
  if (gapMs < (windowTo - windowFrom) * 0.15) return null;
  return { windowFrom, windowTo, dataFrom: first, gapMs };
};

export default presetWindow;
