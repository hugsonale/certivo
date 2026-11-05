import { describe, expect, it } from "vitest";
import {
  buildMarkdown,
  headline,
  type MachineInfo,
  machineLoad,
  type ReportInput,
  type RunResult,
  reportFileName,
  tierSummary,
} from "../overhead/report";

const machine: MachineInfo = {
  id: "RM-1",
  tier: "unclassified",
  hostname: "dev-box",
  os: "Windows_NT 10.0 (x64)",
  cpuModel: "Test CPU",
  logicalCores: 8,
  ramGb: 16,
  browser: "153.0",
  headless: false,
  hardwareConcurrency: 8,
  crossOriginIsolated: true,
  gitCommit: "abc1234",
};

function run(mode: RunResult["mode"], rep: number, cpuS: number, extra: Partial<RunResult> = {}): RunResult {
  const intervals = mode === "baseline" ? 0 : 10;
  return {
    mode,
    throttle: 1,
    rep,
    wallS: 30,
    intervalMs: 3000,
    intervals,
    cpu: { totalS: cpuS, byType: { renderer: cpuS }, source: "process" },
    memory: {
      startBytes: 50 * 1024 * 1024,
      endBytes: (mode === "baseline" ? 50 : 58) * 1024 * 1024,
      source: "measureUserAgentSpecificMemory",
    },
    bandwidth: {
      upBytes: mode === "baseline" ? 0 : 12_000,
      downBytes: mode === "baseline" ? 0 : 3_000,
      requests: intervals,
    },
    callBytesSent: 3_750_000,
    phases:
      mode === "baseline"
        ? { total: [], capture: [], model: [], sign: [], submit: [] }
        : { total: [30, 40, 50], capture: [10, 12, 14], model: [3, 4, 5], sign: [0.2, 0.3, 0.4], submit: [8, 9, 10] },
    workerModelMs: mode === "baseline" ? [] : [0.01, 0.02],
    longTasks: [],
    outcomes: mode === "baseline" ? {} : { sent: 10 },
    ...extra,
  };
}

const input = (overrides: Partial<ReportInput> = {}): ReportInput => ({
  generatedAt: "2026-11-04T10:00:00.000Z",
  machine,
  parameters: {
    repetitions: 2,
    windowS: 30,
    warmUpS: 5,
    intervalMs: 3000,
    throttles: [1],
    side: 224,
    call: { width: 640, height: 480, fps: 30 },
  },
  runs: [run("baseline", 1, 6), run("sdk", 1, 6.6), run("sdk", 2, 6.9), run("baseline", 2, 6.2)],
  calibration: { burnMs: 150, measuredMsPerInterval: 140, ok: true, toleranceMs: 75 },
  ...overrides,
});

describe("tierSummary", () => {
  it("pairs each run with the SDK against the matching run without it", () => {
    const t = tierSummary(input().runs, 1);
    expect(t.repetitions).toBe(2);
    // 6.0 s of 30 s is 20 percent; 6.6 s is 22 percent: a 2-point overhead. Repetition 2: 23 against 20.67.
    expect(t.cpuPercentBaseline.p50).toBeCloseTo((20 + 20.6667) / 2, 3);
    expect(t.cpuPercentOverhead.min).toBeCloseTo(2, 3);
    expect(t.cpuPercentOverhead.max).toBeCloseTo(2.3333, 3);
    // 0.6 s more CPU over 30 s, times a 3000 ms interval: 60 ms per interval
    expect(t.cpuMsPerIntervalOverhead.min).toBeCloseTo(60, 3);
    expect(t.memoryMbOverhead.p50).toBe(8);
    expect(t.upBytesPerInterval.p50).toBe(1200);
    expect(t.upKbps.p50).toBeCloseTo((12_000 * 8) / 1000 / 30, 6);
    expect(t.callKbps.p50).toBeCloseTo((3_750_000 * 8) / 1000 / 30, 6);
    expect(t.phases.total.n).toBe(6);
    expect(t.intervalsSdk).toBe(20);
    expect(t.outcomesSdk).toEqual({ sent: 20 });
  });
});

describe("machineLoad", () => {
  it("is calm when the browser used a small share of all the cores", () => {
    const load = machineLoad(input());
    expect(load.peak).toBeCloseTo(6.9 / (30 * 8), 6);
    expect(load.saturated).toBe(false);
  });
  it("flags a machine with no spare capacity", () => {
    const busy = input({
      machine: { ...machine, logicalCores: 1 },
      runs: [run("baseline", 1, 29.5), run("sdk", 1, 29.6)],
    });
    expect(machineLoad(busy).saturated).toBe(true);
  });
});

describe("the markdown report", () => {
  const text = buildMarkdown(input());

  it("says plainly that the model is a stand-in and that no budget is applied", () => {
    expect(text).toMatch(/The model is a stand-in/);
    expect(text).toMatch(/No pass budget is applied/);
  });
  it("never claims a result passes or fails: every budget cell reads 'not set'", () => {
    const rows = text
      .split("\n")
      .filter(
        (l) =>
          l.startsWith("| CPU") ||
          l.startsWith("| Memory at") ||
          l.startsWith("| Memory growth") ||
          l.startsWith("| Network"),
      );
    expect(rows.length).toBeGreaterThanOrEqual(6);
    for (const row of rows) expect(row.endsWith("| not set |")).toBe(true);
    expect(text).not.toMatch(/\b(PASS|FAIL|within budget|over budget)\b/);
  });
  it("names the machine, the tier, the browser and the commit so a report can be compared later", () => {
    expect(text).toContain("RM-1 (unclassified)");
    expect(text).toContain("Test CPU, 8 logical cores");
    expect(text).toContain("153.0 (with a window)");
    expect(text).toContain("abc1234");
  });
  it("shows the SDK overhead as the difference, in bold, with the range", () => {
    expect(text).toMatch(/\*\*2\.17 \(2\.00 to 2\.33\)\*\*/);
  });
  it("explains the slowed-down tiers are approximations and that the report has no TLS", () => {
    expect(text).toMatch(/slows only the page's main thread/);
    expect(text).toMatch(/no TLS/);
  });
  it("reports the self-check, and says when the numbers cannot be trusted", () => {
    expect(text).toMatch(/the CPU numbers can be trusted/);
    const bad = buildMarkdown(
      input({ calibration: { burnMs: 150, measuredMsPerInterval: 3, ok: false, toleranceMs: 75 } }),
    );
    expect(bad).toMatch(/THE CPU NUMBERS CANNOT BE TRUSTED/);
  });
  it("puts a loud warning at the top when the machine was saturated", () => {
    const busy = buildMarkdown(
      input({ machine: { ...machine, logicalCores: 1 }, runs: [run("baseline", 1, 29.5), run("sdk", 1, 29.6)] }),
    );
    expect(busy.indexOf("WARNING")).toBeGreaterThan(-1);
    expect(busy.indexOf("WARNING")).toBeLessThan(busy.indexOf("Read this first"));
    expect(text).not.toContain("WARNING");
  });
  it("lists the slowdown settings and the call size", () => {
    expect(text).toContain("640x480 at 30 frames a second");
    const slowed = buildMarkdown(
      input({
        parameters: { ...input().parameters, throttles: [1, 4] },
        runs: [...input().runs, ...input().runs.map((r) => ({ ...r, throttle: 4 }))],
      }),
    );
    expect(slowed).toContain("## Results at 4x (main thread slowed: approximate)");
  });
  it("copes with a run that measured no memory", () => {
    const noMemory = input({
      runs: input().runs.map((r) => ({ ...r, memory: { startBytes: null, endBytes: null, source: "none" } })),
    });
    expect(() => buildMarkdown(noMemory)).not.toThrow();
    expect(buildMarkdown(noMemory)).toContain("n/a");
  });
});

describe("reportFileName and headline", () => {
  it("makes a safe file name from the day and the machine", () => {
    expect(reportFileName("2026-11-04T10:00:00.000Z", "RM-1")).toBe("2026-11-04-RM-1");
    expect(reportFileName("2026-11-04T10:00:00.000Z", "My Laptop (old)!")).toBe("2026-11-04-My-Laptop-old");
    expect(reportFileName("2026-11-04T10:00:00.000Z", "///")).toBe("2026-11-04-machine");
  });
  it("keeps compact figures for comparing reports over time", () => {
    const [h] = headline(input());
    expect(h?.throttle).toBe(1);
    expect(h?.cpuMsPerIntervalOverheadMedian).toBeCloseTo(65, 0);
    expect(h?.memoryMbOverheadMedian).toBe(8);
  });
});
