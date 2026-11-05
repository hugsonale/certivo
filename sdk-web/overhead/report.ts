import { cpuPercent, kbps, mb, pairedOverhead, type Summary, summarize } from "./stats";

/** What one measured run of the harness produced. The spec fills it in; the report only reads it. */
export interface RunResult {
  mode: "baseline" | "sdk" | "calibration";
  /** 1 means no slowing down. 4 means the page's main thread is slowed to a quarter speed (an approximation). */
  throttle: number;
  rep: number;
  wallS: number;
  intervalMs: number;
  intervals: number;
  cpu: { totalS: number; byType: Record<string, number>; source: "process" | "main-thread" };
  memory: { startBytes: number | null; endBytes: number | null; source: string };
  /** Bytes on the wire (headers included) between the page and the platform during the window. */
  bandwidth: { upBytes: number; downBytes: number; requests: number };
  callBytesSent: number;
  phases: { total: number[]; capture: number[]; model: number[]; sign: number[]; submit: number[] };
  workerModelMs: number[];
  longTasks: number[];
  outcomes: Record<string, number>;
  /** For a calibration run: the CPU the worker was told to burn per picture. */
  burnMs?: number;
}

export interface MachineInfo {
  /** The name this machine goes by in docs/spec/reference-machines.md, for example "RM-1". */
  id: string;
  /** The device tier this machine stands for ("unclassified" until the tier definitions are confirmed). */
  tier: string;
  hostname: string;
  os: string;
  cpuModel: string;
  logicalCores: number;
  ramGb: number;
  browser: string;
  headless: boolean;
  hardwareConcurrency: number;
  crossOriginIsolated: boolean;
  gitCommit: string;
}

export interface ReportInput {
  generatedAt: string;
  machine: MachineInfo;
  parameters: {
    repetitions: number;
    windowS: number;
    warmUpS: number;
    intervalMs: number;
    throttles: number[];
    side: number;
    call: { width: number; height: number; fps: number };
  };
  runs: RunResult[];
  calibration: { burnMs: number; measuredMsPerInterval: number; ok: boolean; toleranceMs: number } | undefined;
}

const fmt = (value: number, digits = 1): string => (Number.isFinite(value) ? value.toFixed(digits) : "n/a");
const range = (s: Summary, digits = 1): string =>
  s.n === 0
    ? "n/a"
    : s.n === 1
      ? fmt(s.p50, digits)
      : `${fmt(s.p50, digits)} (${fmt(s.min, digits)} to ${fmt(s.max, digits)})`;

const runsFor = (runs: readonly RunResult[], mode: RunResult["mode"], throttle: number) =>
  runs.filter((r) => r.mode === mode && r.throttle === throttle).sort((a, b) => a.rep - b.rep);

const cpuPct = (r: RunResult) => cpuPercent(r.cpu.totalS, r.wallS);
const memEnd = (r: RunResult) => (r.memory.endBytes === null ? Number.NaN : mb(r.memory.endBytes));
const memGrowth = (r: RunResult) =>
  r.memory.endBytes === null || r.memory.startBytes === null ? Number.NaN : mb(r.memory.endBytes - r.memory.startBytes);
const upKbps = (r: RunResult) => kbps(r.bandwidth.upBytes, r.wallS);
const downKbps = (r: RunResult) => kbps(r.bandwidth.downBytes, r.wallS);

/** The overhead for one device tier setting: the SDK run minus the matching run without it, for every measure. */
export function tierSummary(runs: readonly RunResult[], throttle: number) {
  const base = runsFor(runs, "baseline", throttle);
  const sdk = runsFor(runs, "sdk", throttle);
  const interval = sdk[0]?.intervalMs ?? base[0]?.intervalMs ?? 3000;
  const cpuMsPerIntervalOf = (r: RunResult) => (r.cpu.totalS / r.wallS) * r.intervalMs;
  return {
    throttle,
    repetitions: Math.min(base.length, sdk.length),
    intervalMs: interval,
    cpuPercentBaseline: summarize(base.map(cpuPct)),
    cpuPercentSdk: summarize(sdk.map(cpuPct)),
    cpuPercentOverhead: pairedOverhead(base.map(cpuPct), sdk.map(cpuPct)),
    cpuMsPerIntervalOverhead: pairedOverhead(base.map(cpuMsPerIntervalOf), sdk.map(cpuMsPerIntervalOf)),
    memoryMbBaseline: summarize(base.map(memEnd)),
    memoryMbSdk: summarize(sdk.map(memEnd)),
    memoryMbOverhead: pairedOverhead(base.map(memEnd), sdk.map(memEnd)),
    memoryGrowthMbSdk: summarize(sdk.map(memGrowth)),
    upKbps: summarize(sdk.map(upKbps)),
    downKbps: summarize(sdk.map(downKbps)),
    upBytesPerInterval: summarize(sdk.map((r) => r.bandwidth.upBytes / Math.max(r.intervals, 1))),
    downBytesPerInterval: summarize(sdk.map((r) => r.bandwidth.downBytes / Math.max(r.intervals, 1))),
    callKbps: summarize(base.concat(sdk).map((r) => kbps(r.callBytesSent, r.wallS))),
    phases: {
      total: summarize(sdk.flatMap((r) => r.phases.total)),
      capture: summarize(sdk.flatMap((r) => r.phases.capture)),
      model: summarize(sdk.flatMap((r) => r.phases.model)),
      workerModel: summarize(sdk.flatMap((r) => r.workerModelMs)),
      sign: summarize(sdk.flatMap((r) => r.phases.sign)),
      submit: summarize(sdk.flatMap((r) => r.phases.submit)),
    },
    longTasksBaseline: base.reduce((n, r) => n + r.longTasks.length, 0),
    longTasksSdk: sdk.reduce((n, r) => n + r.longTasks.length, 0),
    longTaskMaxMsSdk: Math.max(0, ...sdk.flatMap((r) => r.longTasks)),
    intervalsSdk: sdk.reduce((n, r) => n + r.intervals, 0),
    outcomesSdk: sdk.reduce<Record<string, number>>((acc, r) => {
      for (const [k, v] of Object.entries(r.outcomes)) acc[k] = (acc[k] ?? 0) + v;
      return acc;
    }, {}),
    cpuSource: sdk[0]?.cpu.source ?? base[0]?.cpu.source ?? "process",
    memorySource: sdk[0]?.memory.source ?? "none",
  };
}

/** A name for the report files that is safe on every operating system. */
export function reportFileName(generatedAt: string, machineId: string): string {
  const day = generatedAt.slice(0, 10);
  const safe = machineId.replace(/[^A-Za-z0-9_-]+/g, "-").replace(/^-+|-+$/g, "") || "machine";
  return `${day}-${safe}`;
}

/** How close to full the machine was. Above about 85 percent of all cores the CPU numbers cannot be trusted. */
export function machineLoad(input: ReportInput): { peak: number; saturated: boolean } {
  const cores = Math.max(input.machine.logicalCores, 1);
  const peak = Math.max(0, ...input.runs.map((r) => (r.wallS > 0 ? r.cpu.totalS / (r.wallS * cores) : 0)));
  return { peak, saturated: peak > 0.85 };
}

export function buildMarkdown(input: ReportInput): string {
  const { machine: m, parameters: p } = input;
  const lines: string[] = [];
  const push = (...l: string[]) => lines.push(...l);
  const load = machineLoad(input);
  push(
    `# SDK overhead report: ${m.id} (${m.tier})`,
    "",
    `Generated ${input.generatedAt} by the overhead harness (guide step P0-27, requirement NFR-C.2) at commit \`${m.gitCommit}\`.`,
    "",
    ...(load.saturated
      ? [
          `> **WARNING: the machine was nearly saturated.** At its busiest, the browser used ${fmt(load.peak * 100, 0)} percent of ALL this machine's cores during a run. When a machine has no spare capacity, extra work cannot show up as extra CPU, so **the CPU overhead below is unreliable (it reads too low)**. Use a smaller fake call (OVERHEAD_CALL), close other programs, or use a faster machine.`,
          "",
        ]
      : []),
    "## Read this first",
    "",
    '- **The model is a stand-in.** There is no real model yet (P0-37). The "model" time below is a worker that does no real work, so these numbers are the cost of everything AROUND a model: capture, moving the picture to the worker, packet building and signing, and sending. **The real model\'s cost is not in this report.**',
    "- **No pass budget is applied.** The budget is agreed with the first partner (P0-71). This report states measurements only, so no row says pass or fail.",
    "- **Overhead means the difference.** Every run is done twice on the same machine: a loopback video call alone, and the same call with the SDK running on the same video. The SDK's cost is the second minus the first.",
    "- **Capture time is mostly waiting.** The capture stage includes waiting for the camera's next frame (up to one frame time, about 33 ms at 30 frames a second), so it is a delay, not CPU work. The CPU rows are the cost.",
    "- **Memory.** When the browser can measure the whole page and its worker, that is used. Otherwise only the main thread's JavaScript heap is measured (shown in brackets in the table), which leaves out the worker and the browser's own buffers, so it understates the SDK's memory.",
    "- **Percentages of one core.** 100 means one whole core busy; 250 means two and a half. On a machine with several cores the same work looks smaller as a share of the whole machine.",
    "- **Slowed-down tiers are approximations.** A tier above 1x slows only the page's main thread. The worker (where the model will run) is NOT slowed, so worker timings under a slowed tier do not represent a slower device. Real devices are needed for that.",
    "- **Bandwidth here has no TLS.** The test server is plain HTTP on this machine, so encryption adds a little more on a real network.",
    "",
    "## Machine",
    "",
    `| | |`,
    `| :-- | :-- |`,
    `| Machine | ${m.id} (${m.hostname}) |`,
    `| Device tier | ${m.tier} |`,
    `| Operating system | ${m.os} |`,
    `| Processor | ${m.cpuModel}, ${m.logicalCores} logical cores |`,
    `| Memory | ${fmt(m.ramGb, 1)} GB |`,
    `| Browser | ${m.browser}${m.headless ? " (headless)" : " (with a window)"} |`,
    `| Page sees | ${m.hardwareConcurrency} cores, cross-origin isolated: ${m.crossOriginIsolated ? "yes" : "no"} |`,
    "",
    "## How it was run",
    "",
    `${p.repetitions} repetition(s) of each of the two setups, alternating. Each run: ${p.warmUpS} s warm-up (not measured), then ${p.windowS} s measured, one interval every ${p.intervalMs} ms, ` +
      `the fake call video is ${p.call.width}x${p.call.height} at ${p.call.fps} frames a second, pictures for the SDK are scaled to ${p.side} px on the long side, in a fresh browser each time. Slowdown settings tried: ${p.throttles.map((t) => `${t}x`).join(", ")}.`,
    "",
  );

  for (const throttle of p.throttles) {
    const t = tierSummary(input.runs, throttle);
    push(
      `## Results at ${throttle}x ${throttle === 1 ? "(no slowdown)" : "(main thread slowed: approximate)"}`,
      "",
      `${t.repetitions} paired repetition(s); ${t.intervalsSdk} intervals measured with the SDK. Typical value, with the lowest and highest repetition in brackets.`,
      "",
      "| Measure | Call alone | Call with the SDK | **SDK overhead** | Budget |",
      "| :-- | --: | --: | --: | :-- |",
      `| CPU, percent of one core (${t.cpuSource === "process" ? "all browser processes" : "main thread only"}) | ${range(t.cpuPercentBaseline)} | ${range(t.cpuPercentSdk)} | **${range(t.cpuPercentOverhead, 2)}** | not set |`,
      `| CPU, milliseconds per interval | | | **${range(t.cpuMsPerIntervalOverhead, 1)}** | not set |`,
      `| Memory at the end, MB (${t.memorySource === "measureUserAgentSpecificMemory" ? "whole page and worker" : t.memorySource === "jsHeap" ? "main-thread JavaScript heap only" : "not measured"}) | ${range(t.memoryMbBaseline)} | ${range(t.memoryMbSdk)} | **${range(t.memoryMbOverhead)}** | not set |`,
      `| Memory growth during the window, MB (SDK run) | | ${range(t.memoryGrowthMbSdk, 2)} | | not set |`,
      `| Network sent by the SDK, kbit/s | | ${range(t.upKbps, 2)} | **${range(t.upKbps, 2)}** | not set |`,
      `| Network received by the SDK, kbit/s | | ${range(t.downKbps, 2)} | **${range(t.downKbps, 2)}** | not set |`,
      `| Network sent per interval, bytes | | ${range(t.upBytesPerInterval, 0)} | **${range(t.upBytesPerInterval, 0)}** | not set |`,
      "",
      `The loopback call itself sent about ${range(t.callKbps, 0)} kbit/s of video, for scale.`,
      "",
      "### Time per interval (milliseconds, every interval of every repetition)",
      "",
      "| Stage | Median | 95th percentile | Longest | Intervals |",
      "| :-- | --: | --: | --: | --: |",
      `| Whole interval | ${fmt(t.phases.total.p50)} | ${fmt(t.phases.total.p95)} | ${fmt(t.phases.total.max)} | ${t.phases.total.n} |`,
      `| Capture (wait for a new camera frame, then copy it) | ${fmt(t.phases.capture.p50)} | ${fmt(t.phases.capture.p95)} | ${fmt(t.phases.capture.max)} | ${t.phases.capture.n} |`,
      `| Model, round trip to the worker (STAND-IN) | ${fmt(t.phases.model.p50)} | ${fmt(t.phases.model.p95)} | ${fmt(t.phases.model.max)} | ${t.phases.model.n} |`,
      `| Model, inside the worker only (STAND-IN) | ${fmt(t.phases.workerModel.p50, 2)} | ${fmt(t.phases.workerModel.p95, 2)} | ${fmt(t.phases.workerModel.max, 2)} | ${t.phases.workerModel.n} |`,
      `| Sign the packet | ${fmt(t.phases.sign.p50, 2)} | ${fmt(t.phases.sign.p95, 2)} | ${fmt(t.phases.sign.max, 2)} | ${t.phases.sign.n} |`,
      `| Send and get the reply | ${fmt(t.phases.submit.p50)} | ${fmt(t.phases.submit.p95)} | ${fmt(t.phases.submit.max)} | ${t.phases.submit.n} |`,
      "",
      `Main-thread tasks over 50 ms: **${t.longTasksSdk}** with the SDK (longest ${fmt(t.longTaskMaxMsSdk, 0)} ms) against ${t.longTasksBaseline} without it. ` +
        `Outcomes of the intervals: ${
          Object.entries(t.outcomesSdk)
            .map(([k, v]) => `${k} ${v}`)
            .join(", ") || "none"
        }.`,
      "",
    );
  }

  if (input.calibration) {
    const c = input.calibration;
    push(
      "## Harness self-check",
      "",
      `A worker was told to burn **${c.burnMs} ms** of CPU per interval. The harness measured **${fmt(c.measuredMsPerInterval)} ms** extra per interval (allowed difference ${fmt(c.toleranceMs)} ms): **${c.ok ? "the CPU numbers can be trusted" : "THE CPU NUMBERS CANNOT BE TRUSTED"}**.`,
      "",
    );
  }
  push(
    "## What this report does not say",
    "",
    "- Nothing about the real model's speed, memory or battery use.",
    "- Nothing about phones or other real devices unless they are listed as reference machines and were run with this harness.",
    "- Nothing about whether the cost is acceptable: that needs the budget agreed with a partner.",
    "",
  );
  return lines.join("\n");
}

/** The compact figures kept in the JSON file, for comparing reports over time. */
export function headline(input: ReportInput) {
  return input.parameters.throttles.map((throttle) => {
    const t = tierSummary(input.runs, throttle);
    return {
      throttle,
      cpuPercentOverheadMedian: t.cpuPercentOverhead.p50,
      cpuMsPerIntervalOverheadMedian: t.cpuMsPerIntervalOverhead.p50,
      memoryMbOverheadMedian: t.memoryMbOverhead.p50,
      upKbpsMedian: t.upKbps.p50,
      wholeIntervalP95Ms: t.phases.total.p95,
      machineLoadPeak: machineLoad(input).peak,
    };
  });
}
