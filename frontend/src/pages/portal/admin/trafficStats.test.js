import { trafficStats } from "./trafficStats";

function buildHourlyWithRamp({ hours = 24, avgBps = 10e6, maxTop = 100e6 } = {}) {
  const base = Date.UTC(2026, 0, 1, 0, 0, 0);
  return Array.from({ length: hours }, (_, h) => {
    const envelope = (maxTop * (h + 1)) / hours;
    return {
      ts: base + h * 3600 * 1000,
      in: avgBps, out: avgBps / 2,
      inMin: avgBps / 2, inMax: envelope,
      outMin: avgBps / 4, outMax: envelope / 2,
    };
  });
}

const hourlyOptions = { resolution: "hourly", intervalSec: 20 };

describe("trafficStats — LibreNMS-style semantics", () => {
  test("95th percentile is computed from AVG series, not MAX envelope", () => {
    const stats = trafficStats(buildHourlyWithRamp(), hourlyOptions);
    expect(stats.percentile95In).toBeCloseTo(10e6, -3);
    expect(stats.percentile95Out).toBeCloseTo(5e6, -3);
    expect(stats.maxIn).toBeCloseTo(100e6, -3);
    expect(stats.maxOut).toBeCloseTo(50e6, -3);
  });

  test("hourly total uses server resolution, not configured poll interval", () => {
    const stats = trafficStats(buildHourlyWithRamp(), hourlyOptions);
    expect(stats.totalInGB).toBeCloseTo((10e6 * 24 * 3600) / 8 / 1e9, 5);
    expect(stats.totalOutGB).toBeCloseTo((5e6 * 24 * 3600) / 8 / 1e9, 5);
    expect(stats.bucketSeconds).toBe(3600);
  });

  test("fivemin total uses 300s buckets even when poll interval is 20s", () => {
    const base = Date.UTC(2026, 0, 1, 0, 0, 0);
    const rows = Array.from({ length: 12 }, (_, i) => ({
      ts: base + i * 5 * 60 * 1000,
      in: 10e6,
      out: 5e6,
    }));
    const stats = trafficStats(rows, { resolution: "fivemin", intervalSec: 20 });
    expect(stats.bucketSeconds).toBe(300);
    expect(stats.totalInGB).toBeCloseTo((10e6 * 12 * 300) / 8 / 1e9, 5);
    expect(stats.totalOutGB).toBeCloseTo((5e6 * 12 * 300) / 8 / 1e9, 5);
  });

  test("split IN/OUT rows never collapse the step to their sub-second gap", () => {
    const base = Date.UTC(2026, 0, 1, 0, 0, 0);
    const rows = Array.from({ length: 10 }, (_, i) => [
      { ts: base + i * 20000 + 900, in: 100e6, inMax: 100e6 },
      { ts: base + (i + 1) * 20000 + 100, out: 50e6, outMax: 50e6 },
    ]).flat();
    const stats = trafficStats(rows, { resolution: "raw", intervalSec: 20 });
    expect(stats.bucketSeconds).toBe(20);
    expect(stats.totalInGB).toBeCloseTo((100e6 * 10 * 20) / 8 / 1e9, 5);
    expect(stats.totalOutGB).toBeCloseTo((50e6 * 10 * 20) / 8 / 1e9, 5);
  });

  test("outage gaps do not get charged as traffic", () => {
    const base = Date.UTC(2026, 0, 1, 0, 0, 0);
    const rows = [0, 1, 2, 5, 9, 14].map(h => ({ ts: base + h * 3600 * 1000, in: 10e6, out: 5e6 }));
    const stats = trafficStats(rows, hourlyOptions);
    expect(stats.totalInGB).toBeCloseTo((10e6 * 6 * 3600) / 8 / 1e9, 5);
    expect(stats.totalOutGB).toBeCloseTo((5e6 * 6 * 3600) / 8 / 1e9, 5);
  });

  test("clamps partial first and last rollup buckets to selected range", () => {
    const base = Date.UTC(2026, 0, 1, 1, 0, 0); // bucket starts 01:00 and 02:00
    const rows = [{ ts: base, in: 10e6 }, { ts: base + 3600 * 1000, in: 10e6 }];
    const stats = trafficStats(rows, {
      ...hourlyOptions,
      fromMs: base + 30 * 60 * 1000,
      toMs: base + 90 * 60 * 1000,
    });
    // 30m from first bucket + 30m from second bucket = one hour total.
    expect(stats.totalInGB).toBeCloseTo((10e6 * 3600) / 8 / 1e9, 5);
  });

  test("raw tier uses poll interval and empty input is null-safe", () => {
    const rows = [{ ts: 1, in: 100e6, out: 50e6 }];
    const stats = trafficStats(rows, { resolution: "raw", intervalSec: 20 });
    expect(stats.totalInGB).toBeCloseTo((100e6 * 20) / 8 / 1e9, 5);
    expect(trafficStats([]).totalInGB).toBeNull();
    expect(trafficStats([]).percentile95In).toBeNull();
  });
});
