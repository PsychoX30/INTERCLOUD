import fs from "fs";
import path from "path";

// This guards the actual stale-closure regression in the component, not merely
// the arithmetic helper. Range-click must pass the just-created window to BOTH
// primary and IN/OUT sibling data loads. Calling loadData(expandedId) alone
// reuses the old `from` captured before React applies setFrom().
describe("AdminMonitoring preset range wiring", () => {
  const source = fs.readFileSync(
    path.join(__dirname, "AdminMonitoring.jsx"),
    "utf8",
  );

  it("passes the newly computed window to both graph requests", () => {
    const start = source.indexOf("const setRange = (hours) => {");
    const end = source.indexOf("const RANGES = [", start);
    const body = source.slice(start, end);
    expect(body).toContain("const window = presetWindow(hours);");
    expect(body).toContain("loadData(expandedId, window);");
    expect(body).toContain("loadPairData(pair.id, window);");
  });

  it("does not issue the stale no-option primary request", () => {
    const start = source.indexOf("const setRange = (hours) => {");
    const end = source.indexOf("const RANGES = [", start);
    const body = source.slice(start, end);
    expect(body).not.toMatch(/loadData\(expandedId\);/);
    expect(body).not.toMatch(/loadPairData\(pair\.id\);/);
  });

  // Auto-refresh in preset mode must recompute BOTH ends of the window from
  // rangeHours. The old code left `from` frozen at click time and only slid
  // `to`, so a "1D" view silently grew to 2d, 3d... as time passed.
  it("recomputes a fresh sliding window on preset auto-refresh", () => {
    const start = source.indexOf("const refreshData = useCallback");
    const end = source.indexOf("}, [expandedId", start);
    const body = source.slice(start, end);
    expect(body).toContain("presetWindow(rangeHours)");
    // the recomputed window must flow into both loaders
    expect(body).toMatch(/loadData\(expandedId, win\)/);
    expect(body).toMatch(/loadPairData\(pair\.id, win\)/);
  });

  // Visual-collapse defect (prod 52738f5): preset mode stored to="" so the
  // chart panel got toMs=null, xDomain=undefined and Recharts drew the X axis
  // from epoch 0 — every preset looked identical. Preset state must hold the
  // concrete window end, and auto-refresh must slide BOTH stored ends.
  it("stores the concrete window end for presets, not an empty string", () => {
    const start = source.indexOf("const setRange = (hours) => {");
    const end = source.indexOf("const RANGES = [", start);
    const body = source.slice(start, end);
    expect(body).toContain("setTo(window.to);");
    expect(body).not.toContain('setTo("")');
  });

  it("slides both stored ends of the window on preset auto-refresh", () => {
    const start = source.indexOf("const refreshData = useCallback");
    const end = source.indexOf("}, [expandedId", start);
    const body = source.slice(start, end);
    expect(body).toMatch(/setFrom\(win\.from\)/);
    expect(body).toMatch(/setTo\(win\.to\)/);
  });

  it("derives the chart X domain via chartXDomain, never a bare undefined", () => {
    expect(source).toContain("chartXDomain(from, to)");
    expect(source).not.toMatch(/: undefined;\s*\n\s*\/\/ Merge timelines/);
  });

  // Latest-wins: a slow response from a previous range click must not overwrite
  // the freshest selection. Each loader stamps a monotonic seq and bails if a
  // newer request has superseded it before applying state.
  it("guards primary and pair loaders against stale-response overwrite", () => {
    expect(source).toContain("const dataSeq = useRef(0);");
    expect(source).toContain("const pairSeq = useRef(0);");

    const ld = source.slice(
      source.indexOf("const loadData = useCallback"),
      source.indexOf("const loadPairData = useCallback"),
    );
    expect(ld).toContain("const seq = ++dataSeq.current;");
    expect(ld).toMatch(/if \(seq !== dataSeq\.current\) return/);

    const lp = source.slice(
      source.indexOf("const loadPairData = useCallback"),
      source.indexOf("const refreshData = useCallback"),
    );
    expect(lp).toContain("const seq = ++pairSeq.current;");
    expect(lp).toMatch(/if \(seq !== pairSeq\.current\) return/);
  });

  // Double-request defect (found by frontend review of 1840b5b): the sibling
  // effect depended on the loadPairData identity, which changes whenever
  // from/to change. setRange already loads the pair explicitly, so the effect
  // fired a SECOND pair request on every preset/custom range change. The effect
  // must react only to graph selection, reading the loader through a ref.
  it("fires the sibling pair effect on selection only, not on loader identity", () => {
    const start = source.indexOf("// Load sibling pair data whenever a graph is selected");
    const end = source.indexOf("const refreshIntervalMs", start);
    const body = source.slice(start, end);
    expect(source).toContain("const loadPairRef = useRef(loadPairData);");
    expect(body).toContain("loadPairRef.current(pair.id)");
    expect(body).not.toMatch(/\}, \[expandedId, graphs, loadPairData\]\);/);
  });

  // History-gap indicator: 1W/1M/1Y presets keep the FULL requested window on
  // the X axis (honest gaps, no autofit). Young graphs then show a mostly
  // empty left side, which reads like a broken chart. The panel must derive a
  // gap note from the actual first sample and render it, not hide the gap.
  it("renders a history-gap note derived from the first sample", () => {
    expect(source).toContain("historyGapNote(from, to,");
    expect(source).toContain("earliestSampleMs(");
    expect(source).toContain('data-testid="history-gap-note"');
  });

  it("parses API sample timestamps as UTC and formats ticks in Jakarta", () => {
    expect(source).toContain("parseApiTs(s.at)");
    expect(source).toContain("formatGraphTick(value, spanMs)");
  });

  // Every timestamp on the Monitoring page must be shown in WIB, not in the
  // viewer's device zone: ping history labels, "last probe", alert events and
  // maintenance windows all render through `stamp()`.
  it("renders non-chart monitoring timestamps in WIB", () => {
    expect(source).toContain("const stamp = (value) => formatWibDateTime(value);");
    expect(source).toContain("label: formatWibTime(s.at)");
    expect(source).not.toMatch(/new Date\(value\)\.toLocaleString\(\)/);
    expect(source).not.toMatch(/new Date\(s\.at\)\.toLocaleTimeString\(\)/);
  });

  it("scales to the two plotted averages without hidden MAX lines", () => {
    const start = source.indexOf("const visibleVals = merged.flatMap");
    const end = source.indexOf("];", start);
    const body = source.slice(start, end);
    // Y-axis scales to exactly the plotted series; no hidden inMax/outMax
    // envelope inflating the domain. MAX for the table comes from trafficStats.
    expect(body).toContain("row.in");
    expect(body).toContain("row.out");
    expect(body).not.toContain("row.inMax");
    expect(body).not.toContain("row.outMax");
    expect(source).toContain('dataKey="in" name="IN"');
    expect(source).toContain('dataKey="out" name="OUT"');
    expect(source).not.toContain('dataKey="inMax" name="IN max"');
    expect(source).not.toContain('dataKey="outMax" name="OUT max"');
  });

  // User decision: chart shows only two lines — no 95th ReferenceLine on chart.
  // Values remain in the stats table; chart is clean IN + OUT only.
  it("does not render 95th percentile ReferenceLines on the chart", () => {
    const chartBlock = source.slice(
      source.indexOf("<AreaChart data={merged}>"),
      source.indexOf("</AreaChart>"),
    );
    expect(chartBlock).not.toContain("<ReferenceLine");
    expect(chartBlock).not.toContain("percentile");
  });
});
