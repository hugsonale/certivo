import { installWorker, type ModelRunner, type WorkerScope } from "@certivo/sdk-inference";
import type { ScoreResult } from "@certivo/sdk-types";

/**
 * The model slot of the overhead harness. Today it is a STAND-IN: it does no real work, or, for the harness self-check,
 * burns a KNOWN amount of CPU per picture (`?burn=30` in the worker's address means 30 ms), so the harness can prove it
 * measures CPU correctly. When the real model exists (P0-37) it replaces this file; the harness around it stays.
 *
 * It records how long each score took inside the worker, which the page collects when the measurement ends.
 */
const burnMs = Number(new URLSearchParams(self.location.search).get("burn") ?? 0);
let modelMs: number[] = [];

const runner: ModelRunner = {
  async load() {},
  async score(): Promise<ScoreResult> {
    const started = performance.now();
    if (burnMs > 0) while (performance.now() - started < burnMs) {} // a busy loop: it really uses the CPU
    modelMs.push(performance.now() - started);
    return {
      confidenceMilli: 900,
      reasonCodes: ["overhead_standin"],
      signalMilli: { scripted: 1000 },
      modelVersion: "overhead-standin-0",
    };
  },
};

const scope = self as unknown as WorkerScope & { postMessage(message: unknown): void };
installWorker(scope, runner);
const installed = scope.onmessage;
scope.onmessage = (event) => {
  if ((event.data as { type?: string } | null)?.type === "__reset") {
    modelMs = [];
    return;
  }
  if ((event.data as { type?: string } | null)?.type === "__stats") {
    scope.postMessage({ type: "__stats", modelMs });
    return;
  }
  installed?.call(scope, event);
};
