/**
 * Guide P0-27, the overhead harness: "Measure CPU, memory, bandwidth and inference time per interval on defined
 * reference machines; produce a report per device tier (NFR-C.2)."
 *
 * It runs the same fake video call twice, with and without the Web SDK, several times each and alternating, in a fresh
 * browser every time, and reports the difference. It also checks itself: a worker that burns a known amount of CPU
 * must show up as that much CPU.
 *
 * Settings come from environment variables (all optional; see overhead/README.md).
 */
import { execFileSync } from "node:child_process";
import { mkdir, writeFile } from "node:fs/promises";
import { createServer } from "node:http";
import type { AddressInfo } from "node:net";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { type Browser, chromium, expect, test } from "@playwright/test";
import { build } from "esbuild";
import type { MemoryReading, OverheadApi, WindowMetrics } from "./harness/page";
import { buildMarkdown, headline, type MachineInfo, type ReportInput, type RunResult, reportFileName } from "./report";
import { calibrationCheck, type ProcessCpu, processCpuDelta } from "./stats";

type W = { __overhead: OverheadApi };

const number = (name: string, fallback: number): number => {
  const value = Number(process.env[name]);
  return Number.isFinite(value) && value > 0 ? value : fallback;
};
const here = (file: string) => fileURLToPath(new URL(file, import.meta.url));

const REPS = Math.floor(number("OVERHEAD_REPS", 3));
const WINDOW_S = number("OVERHEAD_WINDOW_S", 45);
const WARM_UP_S = number("OVERHEAD_WARMUP_S", 6);
const INTERVAL_MS = Math.floor(number("OVERHEAD_INTERVAL_MS", 3000));
const SIDE = Math.floor(number("OVERHEAD_SIDE", 224));
// The size and rate of the fake call video, "640x480@30" by default. A smaller call is a fairer test of a weaker machine.
const CALL = /^(\d{2,4})x(\d{2,4})@(\d{1,2})$/.exec(process.env.OVERHEAD_CALL ?? "640x480@30");
const CAMERA = { width: Number(CALL?.[1] ?? 640), height: Number(CALL?.[2] ?? 480), fps: Number(CALL?.[3] ?? 30) };
const THROTTLES = (process.env.OVERHEAD_THROTTLES ?? "1")
  .split(",")
  .map((v) => Number(v.trim()))
  .filter((v) => Number.isFinite(v) && v >= 1);
const CALIBRATE = process.env.OVERHEAD_CALIBRATE !== "0";
// Big enough to stand out from noise: 5 percent of an interval, and never under 30 ms.
const BURN_MS = number("OVERHEAD_BURN_MS", Math.max(30, Math.round(number("OVERHEAD_INTERVAL_MS", 3000) * 0.05)));
const MACHINE_ID = process.env.OVERHEAD_MACHINE ?? "RM-unnamed";
const TIER = process.env.OVERHEAD_TIER ?? "unclassified";
const CHANNEL = process.env.OVERHEAD_CHANNEL; // for example "chrome" or "msedge" to use the browser installed on the machine
const HEADED = process.env.OVERHEAD_HEADED === "1";
const CHROMIUM_PATH = process.env.OVERHEAD_CHROMIUM_PATH;
const EXTRA_ARGS = (process.env.OVERHEAD_EXTRA_ARGS ?? "").split(" ").filter(Boolean);
const OUT_DIR = path.resolve(process.env.OVERHEAD_OUT ?? here("../../docs/reports/overhead"));

async function bundle(entry: string): Promise<string> {
  const result = await build({
    entryPoints: [entry],
    bundle: true,
    write: false,
    format: "iife",
    platform: "browser",
    target: "es2022",
    logLevel: "silent",
  });
  return result.outputFiles[0]?.text ?? "";
}

/** A pretend platform that takes every packet. The page is served with the headers that let it measure its own memory. */
async function startServer(pageJs: string, workerJs: string): Promise<{ origin: string; close(): Promise<void> }> {
  const isolation = {
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Embedder-Policy": "require-corp",
    "Cross-Origin-Resource-Policy": "same-origin",
  };
  const server = createServer((req, res) => {
    const chunks: Buffer[] = [];
    req.on("data", (c: Buffer) => chunks.push(c));
    req.on("end", () => {
      const pathname = (req.url ?? "/").split("?")[0] ?? "/";
      if (req.method === "GET" && pathname === "/") {
        res.writeHead(200, { "Content-Type": "text/html", ...isolation });
        res.end('<!doctype html><meta charset="utf-8"><title>Certivo overhead</title><script src="/page.js"></script>');
      } else if (req.method === "GET" && pathname === "/page.js") {
        res.writeHead(200, { "Content-Type": "text/javascript", ...isolation });
        res.end(pageJs);
      } else if (req.method === "GET" && pathname === "/worker.js") {
        res.writeHead(200, { "Content-Type": "text/javascript", ...isolation });
        res.end(workerJs);
      } else if (req.method === "POST" && /\/score-events$/.test(pathname)) {
        let seq = 0;
        try {
          seq = (JSON.parse(Buffer.concat(chunks).toString()) as { seq?: number }).seq ?? 0;
        } catch {
          // ignore
        }
        res.writeHead(200, { "Content-Type": "application/json", ...isolation });
        res.end(JSON.stringify({ accepted: true, seq, current_policy_outcome: "accept", duplicate: false }));
      } else {
        res.writeHead(404, isolation);
        res.end();
      }
    });
  });
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  return {
    origin: `http://127.0.0.1:${(server.address() as AddressInfo).port}`,
    close: () => new Promise<void>((r) => server.close(() => r())),
  };
}

const sleep = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));

async function launch(): Promise<Browser> {
  return chromium.launch({
    headless: !HEADED,
    ...(CHANNEL ? { channel: CHANNEL } : {}),
    ...(CHROMIUM_PATH ? { executablePath: CHROMIUM_PATH } : {}),
    args: [
      "--autoplay-policy=no-user-gesture-required",
      // a window the harness cannot see must not be slowed down behind its back
      "--disable-background-timer-throttling",
      "--disable-renderer-backgrounding",
      "--disable-backgrounding-occluded-windows",
      ...EXTRA_ARGS,
    ],
  });
}

async function readProcesses(cdp: { send(method: string): Promise<unknown> }): Promise<ProcessCpu[] | undefined> {
  try {
    const reply = (await cdp.send("SystemInfo.getProcessInfo")) as {
      processInfo: Array<{ id: number; type: string; cpuTime: number }>;
    };
    return reply.processInfo.map((p) => ({ id: p.id, type: p.type, cpuTime: p.cpuTime }));
  } catch {
    return undefined;
  }
}

async function runOnce(
  origin: string,
  spec: { mode: RunResult["mode"]; throttle: number; rep: number; burnMs?: number },
  windowS: number,
): Promise<{ run: RunResult; environment: ReturnType<OverheadApi["environment"]>; browserVersion: string }> {
  const browser = await launch();
  try {
    const context = await browser.newContext();
    const page = await context.newPage();
    const pageCdp = await context.newCDPSession(page);
    await pageCdp.send("Performance.enable").catch(() => {});
    if (spec.throttle > 1) await pageCdp.send("Emulation.setCPUThrottlingRate", { rate: spec.throttle });
    const browserCdp = await browser.newBrowserCDPSession();

    let up = 0;
    let down = 0;
    let requests = 0;
    let counting = false;
    const pending: Promise<void>[] = [];
    page.on("requestfinished", (request) => {
      if (!counting || !/\/score-events/.test(request.url())) return;
      pending.push(
        request.sizes().then((s) => {
          up += s.requestHeadersSize + s.requestBodySize;
          down += s.responseHeadersSize + s.responseBodySize;
          requests++;
        }),
      );
    });

    await page.goto(`${origin}/${spec.burnMs ? `?burn=${spec.burnMs}` : ""}`);
    await page.waitForFunction(() => "__overhead" in window);
    const mode = spec.mode === "baseline" ? "baseline" : "sdk";
    await page.evaluate((o) => (window as unknown as W).__overhead.start(o), {
      mode,
      intervalMs: INTERVAL_MS,
      side: SIDE,
      camera: CAMERA,
    } as const);
    await sleep(WARM_UP_S * 1000);

    // The page's own memory reading covers the page AND its worker when the browser allows it. When it does not, fall back to the
    // main thread's JavaScript heap measured through the debugging channel right after a garbage collection (exact, but it
    // leaves out the worker and the browser's own buffers).
    const readMemory = async (): Promise<MemoryReading> => {
      const reading: MemoryReading = await page.evaluate(() => (window as unknown as W).__overhead.memory());
      if (reading.source === "measureUserAgentSpecificMemory") return reading;
      try {
        await pageCdp.send("HeapProfiler.enable");
        await pageCdp.send("HeapProfiler.collectGarbage");
        await pageCdp.send("HeapProfiler.collectGarbage"); // twice: the first pass can leave work for the second
        const reply = (await pageCdp.send("Performance.getMetrics")) as {
          metrics: Array<{ name: string; value: number }>;
        };
        const used = reply.metrics.find((m) => m.name === "JSHeapUsedSize")?.value;
        if (used !== undefined) return { bytes: used, source: "jsHeap" };
      } catch {
        // keep the coarser reading
      }
      return reading;
    };

    // ---- the measured window
    const memoryStart: MemoryReading = await readMemory();
    const before = await readProcesses(browserCdp);
    const taskSeconds = async (): Promise<number> => {
      const reply = (await pageCdp.send("Performance.getMetrics").catch(() => ({ metrics: [] }))) as {
        metrics: Array<{ name: string; value: number }>;
      };
      return reply.metrics.find((m) => m.name === "TaskDuration")?.value ?? 0;
    };
    const m0 = await taskSeconds();
    counting = true;
    const startedAt = Date.now();
    await page.evaluate(() => (window as unknown as W).__overhead.beginWindow());
    await sleep(windowS * 1000);
    const metrics: WindowMetrics = await page.evaluate(() => (window as unknown as W).__overhead.endWindow());
    const wallS = (Date.now() - startedAt) / 1000;
    counting = false;
    const after = await readProcesses(browserCdp);
    const m1 = await taskSeconds();
    const memoryEnd: MemoryReading = await readMemory();
    await Promise.all(pending);

    const cpu =
      before && after
        ? { ...processCpuDelta(before, after), source: "process" as const }
        : { totalS: Math.max(0, m1 - m0), byType: { renderer: Math.max(0, m1 - m0) }, source: "main-thread" as const };
    const environment = await page.evaluate(() => (window as unknown as W).__overhead.environment());
    await page.evaluate(() => (window as unknown as W).__overhead.stop());
    const browserVersion = browser.version();
    return {
      run: {
        mode: spec.mode,
        throttle: spec.throttle,
        rep: spec.rep,
        wallS,
        intervalMs: INTERVAL_MS,
        intervals: metrics.intervals,
        cpu,
        memory: { startBytes: memoryStart.bytes, endBytes: memoryEnd.bytes, source: memoryEnd.source },
        bandwidth: { upBytes: up, downBytes: down, requests },
        callBytesSent: metrics.callBytesSent,
        phases: metrics.phases,
        workerModelMs: metrics.workerModelMs,
        longTasks: metrics.longTasks,
        outcomes: metrics.outcomes,
        ...(spec.burnMs ? { burnMs: spec.burnMs } : {}),
      },
      environment,
      browserVersion,
    };
  } finally {
    await browser.close();
  }
}

function gitCommit(): string {
  try {
    return execFileSync("git", ["rev-parse", "--short", "HEAD"], {
      encoding: "utf8",
      stdio: ["ignore", "pipe", "ignore"],
    }).trim();
  } catch {
    return "unknown";
  }
}

test("P0-27: measure the SDK's overhead and write the report", async () => {
  test.setTimeout(0);
  const pageJs = await bundle(here("./harness/page.ts"));
  const workerJs = await bundle(here("./harness/model-worker.ts"));
  const server = await startServer(pageJs, workerJs);
  const runs: RunResult[] = [];
  let environment: ReturnType<OverheadApi["environment"]> | undefined;
  let browserVersion = "unknown";
  const log = (text: string) => process.stdout.write(`${text}\n`);

  try {
    for (const throttle of THROTTLES) {
      for (let rep = 1; rep <= REPS; rep++) {
        // alternate which setup goes first, so slow drift on the machine hits both alike
        const order: RunResult["mode"][] = rep % 2 === 1 ? ["baseline", "sdk"] : ["sdk", "baseline"];
        for (const mode of order) {
          log(
            `  ${throttle}x, repetition ${rep} of ${REPS}: ${mode === "baseline" ? "call alone" : "call with the SDK"} ...`,
          );
          const result = await runOnce(server.origin, { mode, throttle, rep }, WINDOW_S);
          environment ??= result.environment;
          browserVersion = result.browserVersion;
          runs.push(result.run);
        }
      }
    }

    let calibration: ReportInput["calibration"];
    if (CALIBRATE) {
      log(`  self-check: a worker that burns ${BURN_MS} ms per interval ...`);
      const burn = await runOnce(
        server.origin,
        { mode: "calibration", throttle: 1, rep: 1, burnMs: BURN_MS },
        Math.max(20, WINDOW_S / 2),
      );
      const plain = await runOnce(server.origin, { mode: "sdk", throttle: 1, rep: 99 }, Math.max(20, WINDOW_S / 2));
      const extraMs = ((burn.run.cpu.totalS - plain.run.cpu.totalS) / burn.run.wallS) * INTERVAL_MS;
      const check = calibrationCheck(BURN_MS, extraMs);
      calibration = { burnMs: BURN_MS, measuredMsPerInterval: extraMs, ...check };
    }

    const machine: MachineInfo = {
      id: MACHINE_ID,
      tier: TIER,
      hostname: os.hostname(),
      os: `${os.type()} ${os.release()} (${os.arch()})`,
      cpuModel: os.cpus()[0]?.model.trim() ?? "unknown",
      logicalCores: os.cpus().length,
      ramGb: os.totalmem() / 1024 ** 3,
      browser: browserVersion,
      headless: !HEADED,
      hardwareConcurrency: environment?.hardwareConcurrency ?? 0,
      crossOriginIsolated: environment?.crossOriginIsolated ?? false,
      gitCommit: gitCommit(),
    };
    const input: ReportInput = {
      generatedAt: new Date().toISOString(),
      machine,
      parameters: {
        repetitions: REPS,
        windowS: WINDOW_S,
        warmUpS: WARM_UP_S,
        intervalMs: INTERVAL_MS,
        throttles: THROTTLES,
        side: SIDE,
        call: CAMERA,
      },
      runs,
      calibration,
    };
    await mkdir(OUT_DIR, { recursive: true });
    const base = path.join(OUT_DIR, reportFileName(input.generatedAt, MACHINE_ID));
    await writeFile(`${base}.md`, buildMarkdown(input), "utf8");
    await writeFile(`${base}.json`, `${JSON.stringify({ ...input, headline: headline(input) }, null, 2)}\n`, "utf8");
    log(`\n  Report saved: ${base}.md\n  Raw data:     ${base}.json`);

    // the harness must be able to trust itself, and the runs must have been real
    for (const run of runs) {
      expect(run.mode === "baseline" || run.intervals > 0, `a ${run.mode} run measured no intervals`).toBe(true);
      expect(run.cpu.totalS, "no CPU use was measured").toBeGreaterThan(0);
    }
    if (calibration)
      expect(
        calibration.ok,
        `self-check failed: burned ${BURN_MS} ms, measured ${calibration.measuredMsPerInterval.toFixed(1)} ms`,
      ).toBe(true);
  } finally {
    await server.close();
  }
});
