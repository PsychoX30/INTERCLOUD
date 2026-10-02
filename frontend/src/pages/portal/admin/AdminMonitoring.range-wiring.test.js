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
});
