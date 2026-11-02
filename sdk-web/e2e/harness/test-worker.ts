import { installWorker, type ModelRunner, type WorkerScope } from "@certivo/sdk-inference";
import type { ScoreResult } from "@certivo/sdk-types";
import { allowed, type E2eState } from "./instrument";

/**
 * A stand-in for the real model (P0-37), used only by the browser test. It really does look at the pixels (it draws the
 * picture and reads it back) so the test proves pixels reached the worker, and it hands the page nothing but a score.
 * It also keeps a few raw samples of the pixels it saw: the test searches every outgoing request for them.
 */
const samples: number[][] = [];
let received = 0;
let closed = 0;

const closedPictures = new WeakSet<object>();
const bitmapPrototype = ImageBitmap.prototype as unknown as { close: () => void };
const realClose = bitmapPrototype.close;
bitmapPrototype.close = function (this: ImageBitmap) {
  if (!closedPictures.has(this)) {
    closedPictures.add(this);
    closed++;
  }
  return realClose.call(this);
};

const SAMPLE_BYTES = 24; // six whole pixels
const SAMPLES_PER_FRAME = 4;
const MAX_SAMPLES = 40;

const runner: ModelRunner = {
  async load() {},
  async score(image): Promise<ScoreResult> {
    received++;
    const canvas = new OffscreenCanvas(image.width, image.height);
    const context = canvas.getContext("2d");
    if (!context) throw new Error("no 2D drawing in the worker");
    context.drawImage(image, 0, 0);
    const { data } = context.getImageData(0, 0, image.width, image.height);
    let total = 0;
    for (let i = 0; i < data.length; i += 4)
      total += 0.299 * (data[i] ?? 0) + 0.587 * (data[i + 1] ?? 0) + 0.114 * (data[i + 2] ?? 0);
    const meanLuma = total / (data.length / 4);
    const stride = Math.floor(data.length / 4 / (SAMPLES_PER_FRAME + 1)) * 4;
    for (let k = 1; k <= SAMPLES_PER_FRAME; k++) {
      samples.push(Array.from(data.subarray(stride * k, stride * k + SAMPLE_BYTES)));
    }
    while (samples.length > MAX_SAMPLES) samples.shift();
    return {
      confidenceMilli: 900, // a fixed number: this stand-in says nothing about how good a real model is
      reasonCodes: ["e2e_standin"],
      signalMilli: { mean_luma: Math.round((meanLuma / 255) * 1000) },
      modelVersion: "e2e-standin-0",
    };
  },
};

const scope = self as unknown as WorkerScope & { postMessage(message: unknown): void };
installWorker(scope, runner);

// The test can ask the worker what it saw. This message is the test's own and is not part of the SDK.
const installed = scope.onmessage;
scope.onmessage = (event) => {
  if ((event.data as { type?: string } | null)?.type === "__stats") {
    const state = (globalThis as unknown as { __e2e: E2eState }).__e2e;
    allowed(() => scope.postMessage({ type: "__stats", received, closed, samples, events: state.events }));
    return;
  }
  installed?.call(scope, event);
};
