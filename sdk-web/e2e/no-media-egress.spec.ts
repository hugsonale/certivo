/**
 * Guide P0-24: "Automated network-interception test proves no media leaves the page; memory profile shows no frame
 * retention." A real Chromium runs the real SDK code (capture, worker scorer, pipeline, signing, session client)
 * against a pretend platform, with a stand-in model in the worker, and these tests look at everything that happened.
 *
 * The test is only as good as its detector, so the last test sends a picture out ON PURPOSE and checks that it is caught.
 */
import { createServer, type Server } from "node:http";
import type { AddressInfo } from "node:net";
import { fileURLToPath } from "node:url";
import { type Browser, type BrowserContext, expect, type Page, test } from "@playwright/test";
import { build } from "esbuild";
import type { E2eEvent } from "./harness/instrument";
import type { CycleSummary, E2eApi, WorkerStats } from "./harness/page";
import { findLeaks, type RecordedRequest, unexpectedDestination } from "./leak-detector";

type W = { __certivoE2E: E2eApi };

const here = (file: string) => fileURLToPath(new URL(file, import.meta.url));
const SCORE_PATH = /^\/internal\/v1\/sessions\/continuous\/[A-Za-z0-9_-]+\/score-events$/;

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

interface PretendPlatform {
  origin: string;
  /** Every request that reached the server, with its body exactly as sent. */
  requests: RecordedRequest[];
  close(): Promise<void>;
}

async function startPretendPlatform(pageJs: string, workerJs: string): Promise<PretendPlatform> {
  const requests: RecordedRequest[] = [];
  let origin = "";
  const server: Server = createServer((req, res) => {
    const chunks: Buffer[] = [];
    req.on("data", (chunk: Buffer) => chunks.push(chunk));
    req.on("end", () => {
      const body = chunks.length ? new Uint8Array(Buffer.concat(chunks)) : null;
      const path = (req.url ?? "/").split("?")[0] ?? "/";
      requests.push({
        method: req.method ?? "GET",
        url: `${origin}${req.url ?? "/"}`,
        body,
        contentType: req.headers["content-type"],
      });
      if (req.method === "GET" && path === "/") {
        res.writeHead(200, { "Content-Type": "text/html" });
        res.end('<!doctype html><meta charset="utf-8"><title>Certivo e2e</title><script src="/page.js"></script>');
      } else if (req.method === "GET" && path === "/page.js") {
        res.writeHead(200, { "Content-Type": "text/javascript" });
        res.end(pageJs);
      } else if (req.method === "GET" && path === "/worker.js") {
        res.writeHead(200, { "Content-Type": "text/javascript" });
        res.end(workerJs);
      } else if (req.method === "POST" && SCORE_PATH.test(path)) {
        res.writeHead(200, { "Content-Type": "application/json" });
        res.end(JSON.stringify({ accepted: true, seq: 0, current_policy_outcome: "allow", duplicate: false }));
      } else {
        res.writeHead(404);
        res.end();
      }
    });
  });
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  origin = `http://127.0.0.1:${(server.address() as AddressInfo).port}`;
  return {
    origin,
    requests,
    close: () => new Promise<void>((resolve) => server.close(() => resolve())),
  };
}

const WARM_UP_CYCLES = 30;
const MAIN_CYCLES = 150;

test.describe.configure({ mode: "serial" });

test.describe("P0-24: no media leaves the page, no frame is kept", () => {
  let platform: PretendPlatform;
  let browser: Browser;
  let context: BrowserContext;
  let page: Page;
  /** Every request the browser itself reported, including ones that never reached the server. */
  const seenByBrowser: Array<{ url: string; method: string }> = [];
  const blocked: string[] = [];
  let warm: CycleSummary;
  let main: CycleSummary;
  let stats: WorkerStats;
  let pageEvents: E2eEvent[];
  let videoElementsAfterStop = -1;
  let heapAfterWarmUp = 0;
  let heapAfterMain = 0;
  let requestsBeforeSanityCheck = 0;

  test.beforeAll(async ({ browser: launched }) => {
    browser = launched;
    platform = await startPretendPlatform(
      await bundle(here("./harness/page-entry.ts")),
      await bundle(here("./harness/worker-entry.ts")),
    );
    context = await browser.newContext();
    // Anything that is not the test server is refused, and written down.
    await context.route("**/*", async (route) => {
      const request = route.request();
      seenByBrowser.push({ url: request.url(), method: request.method() });
      if (new URL(request.url()).origin === platform.origin) await route.continue();
      else {
        blocked.push(request.url());
        await route.abort();
      }
    });
    page = await context.newPage();
    await page.goto(platform.origin);
    await page.waitForFunction(() => "__certivoE2E" in window);

    const cdp = await context.newCDPSession(page);
    await cdp.send("Performance.enable");
    const heap = async () => {
      await cdp.send("HeapProfiler.collectGarbage");
      const { metrics } = await cdp.send("Performance.getMetrics");
      return metrics.find((m) => m.name === "JSHeapUsedSize")?.value ?? 0;
    };

    await page.evaluate(() => (window as unknown as W).__certivoE2E.setup());
    warm = await page.evaluate((n) => (window as unknown as W).__certivoE2E.runCycles(n), WARM_UP_CYCLES);
    heapAfterWarmUp = await heap();
    main = await page.evaluate((n) => (window as unknown as W).__certivoE2E.runCycles(n), MAIN_CYCLES);
    heapAfterMain = await heap();
    stats = await page.evaluate(() => (window as unknown as W).__certivoE2E.workerStats());
    pageEvents = await page.evaluate(() => (window as unknown as W).__certivoE2E.pageEvents());
    await page.evaluate(() => (window as unknown as W).__certivoE2E.teardown());
    videoElementsAfterStop = await page.evaluate(() => (window as unknown as W).__certivoE2E.videoElementsInPage());
    requestsBeforeSanityCheck = platform.requests.length;
  });

  test.afterAll(async () => {
    await context?.close();
    await platform?.close();
  });

  test("the pretend call really ran (so the checks below are looking at something)", () => {
    const total = main.outcomes.sent + main.outcomes.buffered + main.outcomes.no_score;
    expect(main.errors, "errors during the run").toEqual([]);
    expect(main.reasons, "intervals that produced no score").toEqual([]);
    expect(total).toBe(MAIN_CYCLES);
    expect(main.outcomes.sent).toBe(MAIN_CYCLES);
    expect(warm.outcomes.sent).toBe(WARM_UP_CYCLES);
    // the worker really received and looked at the pictures
    expect(stats.received).toBeGreaterThanOrEqual(WARM_UP_CYCLES + MAIN_CYCLES);
    expect(stats.samples.length).toBeGreaterThan(0);
    expect(stats.events.filter((e) => e.kind === "pixels:read").length).toBeGreaterThan(0);
  });

  test("the only requests are the test page's own files and small JSON score packets", () => {
    const packets = platform.requests.slice(0, requestsBeforeSanityCheck).filter((r) => r.method === "POST");
    expect(packets.length).toBeGreaterThanOrEqual(WARM_UP_CYCLES + MAIN_CYCLES);

    const canary = stats.samples.map((s) => Uint8Array.from(s));
    expect(canary.length).toBeGreaterThan(0);
    for (const request of platform.requests.slice(0, requestsBeforeSanityCheck)) {
      expect(unexpectedDestination(request.url, platform.origin), `${request.method} ${request.url}`).toBeUndefined();
      expect(findLeaks(request, canary), `${request.method} ${request.url}`).toEqual([]);
    }
  });

  test("the browser tried to reach nowhere else", () => {
    expect(blocked, "requests to any other address").toEqual([]);
    for (const request of seenByBrowser) {
      expect(unexpectedDestination(request.url, platform.origin), `${request.method} ${request.url}`).toBeUndefined();
    }
  });

  test("the page code never encodes, records, reads or stores a picture, and opens no other connection", () => {
    const pageSide = pageEvents.filter((e) => e.where === "page");
    // The only network call the page makes is the score packet, and it was checked above.
    for (const event of pageSide.filter((e) => e.kind.startsWith("network:"))) {
      expect(event.kind, event.detail).toBe("network:fetch");
      const url = /^POST (\S+)/.exec(event.detail)?.[1] ?? "";
      expect(new URL(url).pathname, event.detail).toMatch(SCORE_PATH);
    }
    expect(
      pageSide.filter((e) => e.kind.startsWith("encode:")),
      "picture encoding in the page",
    ).toEqual([]);
    expect(
      pageSide.filter((e) => e.kind === "pixels:read"),
      "pixels read in the page",
    ).toEqual([]);
    expect(
      pageSide.filter((e) => e.kind === "capture:capturestream"),
      "capture streams made by SDK code",
    ).toEqual([]);
    expect(
      pageSide.filter((e) => e.kind === "storage:cache" || e.kind === "storage:opfs" || e.kind === "storage:web"),
    ).toEqual([]);

    // The one thing the SDK may keep is its device key (P0-23). Nothing stored may be a picture or anything big.
    for (const event of pageSide.filter((e) => e.kind === "storage:idb")) {
      expect(event.detail, "stored in IndexedDB").not.toMatch(/ImageBitmap|ImageData|Blob|File|VideoFrame|Canvas/);
      for (const bytes of event.detail.matchAll(/(\d+) bytes/g)) expect(Number(bytes[1])).toBeLessThan(1024);
    }

    const workerSide = stats.events.filter((e) => e.where === "worker");
    for (const prefix of ["network:", "encode:", "storage:", "capture:"]) {
      expect(
        workerSide.filter((e) => e.kind.startsWith(prefix)),
        `worker events: ${prefix}`,
      ).toEqual([]);
    }
  });

  test("a picture goes into the worker and only numbers and code words come out", () => {
    const toWorker = pageEvents.filter((e) => e.kind === "message:to-worker");
    expect(toWorker.length).toBeGreaterThanOrEqual(WARM_UP_CYCLES + MAIN_CYCLES);
    for (const event of toWorker) {
      expect(event.detail).toMatch(
        /^\$\.type: string 5; \$\.id: number; \$\.image: \[object ImageBitmap\] \| transfer=\[object ImageBitmap\]$/,
      );
    }

    const fromWorker = stats.events.filter((e) => e.kind === "message:from-worker");
    expect(fromWorker.length).toBeGreaterThanOrEqual(WARM_UP_CYCLES + MAIN_CYCLES);
    for (const event of fromWorker) {
      for (const leaf of event.detail.split("; ")) {
        expect(leaf, "something other than a number or a word leaves the worker").toMatch(
          /: (number|string \d{1,64}|boolean)$/,
        );
      }
      expect(event.detail).toMatch(/\$\.result\.confidenceMilli: number/);
      expect(event.detail).toMatch(/\$\.result\.reasonCodes\[0\]: string/);
    }
  });

  test("no frame is kept: every picture is closed after every interval", () => {
    // In the page: after each interval, not one picture still holds pixels.
    for (const [name, summary] of [
      ["warm-up", warm],
      ["main run", main],
    ] as const) {
      expect(summary.livePicturesAfterEach.length, name).toBeGreaterThan(0);
      expect(Math.max(...summary.livePicturesAfterEach), `${name}: pictures still open after an interval`).toBe(0);
    }
    // In the worker: every picture that arrived was closed.
    expect(stats.closed).toBe(stats.received);
    // After stopping, the hidden video element is gone.
    expect(videoElementsAfterStop).toBe(0);
  });

  test("memory does not climb while the call runs (coarse backstop)", () => {
    // A leaked 128x96 picture is only ~49 KB of pixel memory and lives outside the JavaScript heap, so the exact check
    // is the picture count above. This one only catches a slow leak of ordinary objects (buffers, listeners, timers).
    const growthMb = (heapAfterMain - heapAfterWarmUp) / 1024 / 1024;
    test.info().annotations.push({ type: "js-heap-growth-mb", description: growthMb.toFixed(2) });
    expect(growthMb, `JS heap grew by ${growthMb.toFixed(2)} MB over ${MAIN_CYCLES} intervals`).toBeLessThan(8);
  });

  test("SANITY CHECK: the monitor catches a picture that is sent out on purpose", async () => {
    const canary = stats.samples.map((s) => Uint8Array.from(s));
    const first = stats.samples[0];
    expect(first).toBeDefined();

    await page.goto(platform.origin);
    await page.waitForFunction(() => "__certivoE2E" in window);
    await page.evaluate(() => (window as unknown as W).__certivoE2E.leakOnPurpose("png"));
    await page.evaluate((pixels) => (window as unknown as W).__certivoE2E.leakOnPurpose("pixels", pixels), first);
    const events = await page.evaluate(() => (window as unknown as W).__certivoE2E.pageEvents());

    const leaked = platform.requests.slice(requestsBeforeSanityCheck).filter((r) => r.method === "POST");
    expect(leaked).toHaveLength(2);
    const [png, pixels] = leaked as [RecordedRequest, RecordedRequest];
    expect(findLeaks(png, canary).map((l) => l.rule)).toEqual(expect.arrayContaining(["not-json", "file-signature"]));
    expect(findLeaks(pixels, canary).map((l) => l.rule)).toContain("pixel-copy");
    // ...and the page-side watcher saw the encoding and the upload too.
    expect(events.map((e) => e.kind)).toEqual(expect.arrayContaining(["encode:toblob", "network:fetch"]));
  });
});
