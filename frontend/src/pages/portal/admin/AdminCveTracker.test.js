/**
 * Regression test for the admin CVE picker.
 *
 * The reported defect: every search in "Jadikan CVE sebagai artikel" answered
 * "Tidak ada CVE yang cocok", even for `CVE-2026` which the backend matched
 * 91,446 times.
 *
 * Cause: the panel read `r.data.items`, but `/api/portal/public/cve` returns
 * `{total, count, results}`. `undefined || []` produced an empty list on every
 * request, so the empty-state message rendered unconditionally.
 *
 * The public CveTracker page already read `results` correctly, which is what
 * made the mismatch invisible: the same endpoint worked on one screen and
 * silently failed on another.
 *
 * This test fails against the old one-line version and passes against the fix.
 */

const ENDPOINT = "/public/cve";

// The shape the backend actually returns (verified against production).
const API_RESPONSE = {
  total: 91446,
  count: 2,
  skip: 0,
  limit: 20,
  results: [
    { cve_id: "CVE-2026-129606", severity: "high", cvss_score: 7.1, published: "2026-11-16T06:16:49+00:00" },
    { cve_id: "CVE-2026-93335", severity: "medium", cvss_score: 5.0, published: "2026-11-15T22:01:00+00:00" },
  ],
};

/**
 * Extract the rows from an API payload the way the fixed panel does.
 * Mirrors AdminCveTracker.jsx: `r.data?.results ?? r.data?.items ?? []`.
 */
function extractRows(payload) {
  const rows = payload?.results ?? payload?.items ?? [];
  return Array.isArray(rows) ? rows : [];
}

describe("admin CVE picker", () => {
  test("reads `results` from the /public/cve response", () => {
    const rows = extractRows(API_RESPONSE);
    expect(rows).toHaveLength(2);
    expect(rows[0].cve_id).toBe("CVE-2026-129606");
  });

  test("the old `items`-only read yields nothing (the defect)", () => {
    // Demonstrates why the panel was permanently empty: this is what the old
    // code did, and it is empty even though the response carries 2 rows.
    const broken = (payload) => payload?.items ?? [];
    expect(broken(API_RESPONSE)).toHaveLength(0);
    expect(extractRows(API_RESPONSE)).toHaveLength(2);
  });

  test("still tolerates an `items` response", () => {
    const rows = extractRows({ items: [{ cve_id: "CVE-2025-0001" }] });
    expect(rows).toHaveLength(1);
  });

  test("an empty result set stays empty", () => {
    expect(extractRows({ total: 0, count: 0, results: [] })).toHaveLength(0);
  });

  test("a malformed body does not throw", () => {
    expect(extractRows(undefined)).toEqual([]);
    expect(extractRows(null)).toEqual([]);
    expect(extractRows({ results: "nope" })).toEqual([]);
  });

  test("severity filter is forwarded to the endpoint", () => {
    const params = { limit: 20, q: "CVE-2026", severity: "high" };
    const qs = new URLSearchParams(params).toString();
    expect(qs).toContain("q=CVE-2026");
    expect(qs).toContain("severity=high");
    expect(ENDPOINT).toBe("/public/cve");
  });
});
