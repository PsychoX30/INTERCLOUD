import { presetWindow, chartXDomain, earliestSampleMs, historyGapNote, parseApiTs, formatGraphTick, DISPLAY_TZ } from "./graphRange";

// Timezone defect (prod 6082a52): the API serialises naive UTC datetimes
// without an offset ("2026-10-02T15:05:00.063000"). `new Date()` treats an
// offset-less ISO date-time as DEVICE-LOCAL time, and tick labels used the
// device zone — so labels showed UTC/device time instead of Jakarta time and,
// on a WIB device, samples were shifted 7h relative to the requested window.
describe("parseApiTs", () => {
  it("treats an offset-less API timestamp as UTC", () => {
    expect(parseApiTs("2026-10-02T15:05:00.063000")).toBe(Date.UTC(2026, 9, 2, 15, 5, 0, 63));
    expect(parseApiTs("2026-10-02T16:00:00")).toBe(Date.UTC(2026, 9, 2, 16, 0, 0));
  });

  it("respects an explicit offset or Z suffix", () => {
    expect(parseApiTs("2026-10-02T16:00:00Z")).toBe(Date.UTC(2026, 9, 2, 16, 0, 0));
    expect(parseApiTs("2026-10-02T23:00:00+07:00")).toBe(Date.UTC(2026, 9, 2, 16, 0, 0));
  });

  it("returns null for empty or invalid input", () => {
    expect(parseApiTs("")).toBeNull();
    expect(parseApiTs(null)).toBeNull();
    expect(parseApiTs("garbage")).toBeNull();
  });
});

describe("formatGraphTick (Asia/Jakarta)", () => {
  const T = Date.UTC(2026, 9, 2, 16, 5, 0); // 23:05 WIB
  const DAY = 86400000;

  it("pins the display zone to Asia/Jakarta", () => {
    expect(DISPLAY_TZ).toBe("Asia/Jakarta");
  });

  it("shows Jakarta 24h time for short spans regardless of device zone", () => {
    expect(formatGraphTick(T, DAY)).toBe("23:05");
  });

  it("rolls the date over in Jakarta, not UTC", () => {
    // 2026-10-02T18:00Z is already 3 Oct 01:00 in Jakarta.
    expect(formatGraphTick(Date.UTC(2026, 9, 2, 18, 0, 0), 7 * DAY)).toBe("03 Oct");
  });

  it("uses month + year for long spans", () => {
    expect(formatGraphTick(T, 365 * DAY)).toBe("Oct 2026");
  });

  it("returns empty for a missing timestamp", () => {
    expect(formatGraphTick(null, DAY)).toBe("");
  });
});

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

// History-gap indicator. When a long preset (1W/1M/1Y) is selected but the
// graph only has a few days of samples, the full requested window is kept
// (honest gaps) — the operator just needs a hint about WHERE the data starts
// so the empty left side is not mistaken for a rendering defect.
describe("earliestSampleMs", () => {
  const rows = [
    { ts: Date.UTC(2026, 9, 1, 0, 0, 0) },
    { ts: Date.UTC(2026, 9, 1, 12, 0, 0) },
    { ts: Date.UTC(2026, 9, 2, 0, 0, 0) },
  ];

  it("returns the earliest finite sample timestamp", () => {
    expect(earliestSampleMs(rows)).toBe(Date.UTC(2026, 9, 1, 0, 0, 0));
  });

  it("ignores null and non-finite timestamps", () => {
    expect(earliestSampleMs([{ ts: null }, { ts: Number.NaN }, ...rows])).toBe(Date.UTC(2026, 9, 1, 0, 0, 0));
  });

  it("returns null when there are no usable samples", () => {
    expect(earliestSampleMs([])).toBeNull();
    expect(earliestSampleMs([{ ts: null }])).toBeNull();
  });

  it("is robust to a null row list", () => {
    expect(earliestSampleMs(null)).toBeNull();
  });
});

describe("historyGapNote", () => {
  const WIN_FROM = Date.UTC(2026, 9, 1, 0, 0, 0);   // 2026-10-01
  const WIN_TO   = Date.UTC(2026, 9, 8, 0, 0, 0);   // 2026-10-08 (1W window)
  const DATA_AT  = Date.UTC(2026, 9, 6, 6, 0, 0);   // data starts 5.25 days in

  it("reports the gap when data starts well after the window start", () => {
    const note = historyGapNote(WIN_FROM, WIN_TO, DATA_AT);
    expect(note).toEqual({
      dataFrom: DATA_AT,
      gapMs: DATA_AT - WIN_FROM,
      windowFrom: WIN_FROM,
      windowTo: WIN_TO,
    });
  });

  it("returns null when there is no usable first sample", () => {
    expect(historyGapNote(WIN_FROM, WIN_TO, null)).toBeNull();
  });

  it("returns null when the window is not fully known", () => {
    expect(historyGapNote("", WIN_TO, DATA_AT)).toBeNull();
    expect(historyGapNote(WIN_FROM, "", DATA_AT)).toBeNull();
  });

  it("returns null when the data effectively starts at the window start", () => {
    expect(historyGapNote(WIN_FROM, WIN_TO, WIN_FROM + 60 * 1000)).toBeNull();
  });

  it("does not flag a gap smaller than 15% of the window span", () => {
    const SHORT_FROM = Date.UTC(2026, 9, 2, 11, 0, 0);
    const SHORT_TO   = Date.UTC(2026, 9, 2, 12, 0, 0); // 1H window
    // 5 minutes into a 1-hour window is 8.3% — polling jitter, not history.
    expect(historyGapNote(SHORT_FROM, SHORT_TO, SHORT_FROM + 5 * 60 * 1000)).toBeNull();
  });

  it("requires the gap to be at least 15% of the window span", () => {
    const SHORT_FROM = Date.UTC(2026, 9, 2, 11, 0, 0);
    const SHORT_TO   = Date.UTC(2026, 9, 2, 12, 0, 0); // 1H window
    // 10 minutes = 16.7% of an hour → flagged.
    expect(historyGapNote(SHORT_FROM, SHORT_TO, SHORT_FROM + 10 * 60 * 1000)).not.toBeNull();
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
