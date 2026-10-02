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

export default presetWindow;
