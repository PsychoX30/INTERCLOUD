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
});
