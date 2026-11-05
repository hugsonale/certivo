import { describe, expect, it } from "vitest";
import {
  calibrationCheck,
  cpuMsPerInterval,
  cpuPercent,
  kbps,
  mb,
  median,
  pairedOverhead,
  percentile,
  processCpuDelta,
  summarize,
} from "../overhead/stats";

describe("percentile and summarize", () => {
  it("finds the middle and the extremes", () => {
    const sorted = [1, 2, 3, 4, 5];
    expect(percentile(sorted, 0)).toBe(1);
    expect(percentile(sorted, 50)).toBe(3);
    expect(percentile(sorted, 100)).toBe(5);
  });
  it("steps between neighbours", () => {
    expect(percentile([10, 20], 50)).toBe(15);
    expect(percentile([0, 10, 20, 30], 95)).toBeCloseTo(28.5, 6);
  });
  it("copes with one value and with none", () => {
    expect(percentile([7], 95)).toBe(7);
    expect(percentile([], 50)).toBeNaN();
    expect(summarize([]).n).toBe(0);
    expect(summarize([]).p50).toBeNaN();
  });
  it("summarises unsorted input and ignores values that are not numbers", () => {
    const s = summarize([5, 1, 3, Number.NaN, 2, 4, Number.POSITIVE_INFINITY]);
    expect(s).toMatchObject({ n: 5, min: 1, p50: 3, max: 5, mean: 3 });
  });
  it("median is the 50th percentile", () => {
    expect(median([9, 1, 5])).toBe(5);
    expect(median([1, 2, 3, 4])).toBe(2.5);
  });
});

describe("processCpuDelta", () => {
  it("counts what each process used between the two readings, by type", () => {
    const before = [
      { id: 1, type: "browser", cpuTime: 10 },
      { id: 2, type: "renderer", cpuTime: 20 },
    ];
    const after = [
      { id: 1, type: "browser", cpuTime: 10.5 },
      { id: 2, type: "renderer", cpuTime: 23 },
    ];
    expect(processCpuDelta(before, after)).toEqual({ totalS: 3.5, byType: { browser: 0.5, renderer: 3 } });
  });
  it("counts everything a new process has used, and ignores one that ended", () => {
    const before = [
      { id: 1, type: "renderer", cpuTime: 5 },
      { id: 9, type: "utility", cpuTime: 100 },
    ];
    const after = [
      { id: 1, type: "renderer", cpuTime: 6 },
      { id: 3, type: "gpu", cpuTime: 2 },
    ];
    expect(processCpuDelta(before, after)).toEqual({ totalS: 3, byType: { renderer: 1, gpu: 2 } });
  });
  it("never reports negative CPU (a counter that restarted)", () => {
    expect(
      processCpuDelta([{ id: 1, type: "renderer", cpuTime: 9 }], [{ id: 1, type: "renderer", cpuTime: 2 }]).totalS,
    ).toBe(0);
  });
});

describe("conversions", () => {
  it("CPU percent is of one core", () => {
    expect(cpuPercent(1.5, 30)).toBeCloseTo(5, 9);
    expect(cpuPercent(60, 30)).toBe(200);
    expect(cpuPercent(1, 0)).toBeNaN();
  });
  it("CPU per interval is in milliseconds", () => {
    expect(cpuMsPerInterval(0.3, 10)).toBeCloseTo(30, 9);
    expect(cpuMsPerInterval(1, 0)).toBeNaN();
  });
  it("bandwidth and memory units", () => {
    expect(kbps(1000, 8)).toBe(1);
    expect(kbps(125_000, 1)).toBe(1000);
    expect(mb(1024 * 1024 * 3)).toBe(3);
  });
});

describe("pairedOverhead", () => {
  it("subtracts each run without the SDK from the matching run with it", () => {
    const s = pairedOverhead([10, 12, 11], [14, 15, 16]);
    expect(s.n).toBe(3);
    expect(s.min).toBe(3);
    expect(s.max).toBe(5);
    expect(s.p50).toBe(4);
  });
  it("uses only complete pairs", () => {
    expect(pairedOverhead([1, 2, 3], [2, 4]).n).toBe(2);
  });
  it("can be negative (noise), and says so honestly", () => {
    expect(pairedOverhead([10], [9]).p50).toBe(-1);
  });
});

describe("calibrationCheck", () => {
  it("accepts a reading near the known load and refuses one far from it", () => {
    expect(calibrationCheck(30, 33).ok).toBe(true);
    expect(calibrationCheck(30, 20).ok).toBe(true);
    expect(calibrationCheck(30, 5).ok).toBe(false);
    expect(calibrationCheck(30, 80).ok).toBe(false);
  });
  it("has a floor so a small load is not held to an impossible precision", () => {
    expect(calibrationCheck(4, 11).ok).toBe(true);
    expect(calibrationCheck(4, 40).ok).toBe(false);
  });
});
