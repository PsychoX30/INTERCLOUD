import { presetWindow, chartXDomain } from "./graphRange";

// Regression guard for the "every range looks the same" visual collapse.
// A numeric time XAxis with domain={undefined} falls back to Recharts' default
// [0, "auto"], i.e. it starts at the 1970 epoch, so 2026 samples are squeezed
// into a sliver at the right edge for EVERY preset. The domain must be the
// selected window, or at worst the data extent — never undefined.
describe("chartXDomain", () => {
  const F = "2026-10-01T10:00:00.000Z";
  const T = "2026-10-02T10:00:00.000Z";

  it("uses the selected window when both ends are valid", () => {
    expect(chartXDomain(F, T)).toEqual([Date.parse(F), Date.parse(T)]);
  });

  it("falls back to the data extent instead of undefined when `to` is empty", () => {
    expect(chartXDomain(F, "")).toEqual(["dataMin", "dataMax"]);
  });

  it("falls back to the data extent for an inverted or invalid window", () => {
    expect(chartXDomain(T, F)).toEqual(["dataMin", "dataMax"]);
    expect(chartXDomain("garbage", T)).toEqual(["dataMin", "dataMax"]);
  });

  it("never returns a domain that starts at the epoch", () => {
    const d = chartXDomain("", "");
    expect(d).not.toBeUndefined();
    expect(d[0]).not.toBe(0);
  });
});

// Regression guard for the bug where clicking 1D / 1W / 1M / 1Y rendered the
// same series. `setRange` called setFrom(...) and then immediately loadData()
// WITHOUT passing the new window, so the request still carried the previous
// `from` from the stale React closure. Each preset must produce its own
// explicit window that can be handed straight to the data loader.
const NOW = Date.UTC(2026, 9, 2, 6, 0, 0); // 2026-10-02T06:00:00Z
const HOUR = 3600 * 1000;

describe("presetWindow", () => {
  it("returns an explicit from/to window for each preset", () => {
    const w = presetWindow(24, NOW);
    expect(w.to).toBe(new Date(NOW).toISOString());
    expect(w.from).toBe(new Date(NOW - 24 * HOUR).toISOString());
  });

  it("produces a distinct from for 1H, 1D, 1W, 1M and 1Y", () => {
    const froms = [1, 24, 24 * 7, 24 * 30, 24 * 365].map(
      (h) => presetWindow(h, NOW).from,
    );
    expect(new Set(froms).size).toBe(5);
  });

  it("spans exactly the requested number of hours", () => {
    [1, 24, 24 * 7, 24 * 30, 24 * 365].forEach((hours) => {
      const w = presetWindow(hours, NOW);
      const span = new Date(w.to).getTime() - new Date(w.from).getTime();
      expect(span).toBe(hours * HOUR);
    });
  });

  it("rejects a non-positive or non-finite hour count", () => {
    expect(presetWindow(0, NOW)).toBeNull();
    expect(presetWindow(-5, NOW)).toBeNull();
    expect(presetWindow(Number.NaN, NOW)).toBeNull();
    expect(presetWindow(undefined, NOW)).toBeNull();
  });

  it("defaults to the current clock when no reference time is given", () => {
    const before = Date.now();
    const w = presetWindow(1);
    const to = new Date(w.to).getTime();
    expect(to).toBeGreaterThanOrEqual(before);
    expect(to - new Date(w.from).getTime()).toBe(HOUR);
  });
});
