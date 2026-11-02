import {
  type IntervalOutcome,
  IntervalRunner,
  MemoryPacketBuffer,
  provisionDevice,
  SDK_VERSION,
  SessionClient,
  scoreCodecV1,
  VerificationPipeline,
  VideoElementFrameSource,
  type WaitingPacket,
  WorkerScorer,
} from "@certivo/sdk";
import { allowed, type E2eEvent, type E2eState, liveBitmaps, pruneBitmaps } from "./instrument";

/** The pretend call the browser test runs. It uses the real SDK code, with a stand-in model in the worker. */

export interface WorkerStats {
  received: number;
  closed: number;
  samples: number[][];
  events: E2eEvent[];
}

export interface CycleSummary {
  outcomes: { sent: number; buffered: number; no_score: number };
  reasons: string[];
  errors: string[];
  /** After each interval: how many pictures made in the page still held pixels. */
  livePicturesAfterEach: number[];
}

export interface E2eApi {
  setup(): Promise<void>;
  runCycles(count: number): Promise<CycleSummary>;
  workerStats(): Promise<WorkerStats>;
  pageEvents(): E2eEvent[];
  videoElementsInPage(): number;
  teardown(): Promise<void>;
  /** On purpose: sends a picture or its pixels out, to prove the test notices. */
  leakOnPurpose(kind: "png" | "pixels", pixels?: number[]): Promise<void>;
}

const SESSION_ID = "sess_e2e_1";
const SIDE = 128; // a small picture; the leak rules do not depend on its size

interface Running {
  worker: Worker;
  scorer: WorkerScorer;
  source: VideoElementFrameSource;
  pipeline: VerificationPipeline;
  stopCamera(): void;
}
let running: Running | undefined;

/** A camera made of random noise: every frame is new and full of detail, so copies of its pixels are easy to spot. */
function makeNoiseCamera(): { stream: MediaStream; stop(): void } {
  const canvas = document.createElement("canvas");
  canvas.width = SIDE;
  canvas.height = (SIDE * 3) / 4;
  const context = canvas.getContext("2d");
  if (!context) throw new Error("no 2D canvas");
  const picture = context.createImageData(canvas.width, canvas.height);
  const draw = () => {
    crypto.getRandomValues(picture.data);
    for (let i = 3; i < picture.data.length; i += 4) picture.data[i] = 255;
    context.putImageData(picture, 0, 0);
  };
  draw();
  const timer = setInterval(draw, 33);
  const stream = allowed(() => canvas.captureStream(30));
  return {
    stream,
    stop() {
      clearInterval(timer);
      for (const track of stream.getTracks()) track.stop();
    },
  };
}

function need(): Running {
  if (!running) throw new Error("setup() has not been called");
  return running;
}

const api: E2eApi = {
  async setup() {
    const camera = makeNoiseCamera();
    const device = await provisionDevice({
      // A real partner backend would forward the public key to the platform. Here the id is made up.
      register: async () => ({ deviceId: `dev_${"0123456789abcdef".repeat(2)}` }),
    });
    const worker = new Worker("/worker.js");
    const scorer = new WorkerScorer(worker);
    const source = new VideoElementFrameSource(camera.stream, { maxSide: SIDE });
    await source.start();
    const client = new SessionClient({
      baseUrl: location.origin,
      sessionId: SESSION_ID,
      sdkToken: "tok_e2e_not_a_secret",
      sdkVersion: SDK_VERSION,
      platform: "web",
    });
    const pipeline = new VerificationPipeline({
      source,
      scorer,
      signer: device.signer,
      codec: scoreCodecV1,
      send: (body) => client.sendScoreEvent(body),
      buffer: new MemoryPacketBuffer<WaitingPacket>(),
      clock: () => Date.now(),
      sessionId: SESSION_ID,
      participantReference: "p_e2e",
      deviceId: device.deviceId,
      intervalMs: 100,
    });
    running = { worker, scorer, source, pipeline, stopCamera: camera.stop };
  },

  runCycles(count) {
    const { pipeline } = need();
    const summary: CycleSummary = {
      outcomes: { sent: 0, buffered: 0, no_score: 0 },
      reasons: [],
      errors: [],
      livePicturesAfterEach: [],
    };
    return new Promise<CycleSummary>((resolve) => {
      let done = 0;
      const finishOne = () => {
        summary.livePicturesAfterEach.push(liveBitmaps());
        pruneBitmaps();
        done++;
        if (done === count) void runner.stop().then(() => resolve(summary));
      };
      const runner = new IntervalRunner({
        intervalMs: 100,
        run: () => pipeline.runInterval(),
        onOutcome: (outcome: IntervalOutcome) => {
          summary.outcomes[outcome.status]++;
          if (outcome.status !== "sent") summary.reasons.push(outcome.reason);
          finishOne();
        },
        onError: (error) => {
          summary.errors.push(String(error));
          finishOne();
        },
      });
      runner.start();
    });
  },

  workerStats() {
    const { worker } = need();
    return new Promise<WorkerStats>((resolve) => {
      const onMessage = (event: MessageEvent) => {
        if ((event.data as { type?: string } | null)?.type !== "__stats") return;
        worker.removeEventListener("message", onMessage);
        resolve(event.data as WorkerStats);
      };
      worker.addEventListener("message", onMessage);
      allowed(() => worker.postMessage({ type: "__stats" }));
    });
  },

  pageEvents() {
    return (globalThis as unknown as { __e2e: E2eState }).__e2e.events;
  },

  videoElementsInPage() {
    return document.querySelectorAll("video").length;
  },

  async teardown() {
    const current = need();
    current.source.stop();
    current.scorer.dispose();
    current.stopCamera();
    running = undefined;
  },

  async leakOnPurpose(kind, pixels) {
    const url = `${location.origin}/internal/v1/sessions/continuous/sess_leak/score-events`;
    if (kind === "png") {
      const canvas = document.createElement("canvas");
      canvas.width = 32;
      canvas.height = 32;
      const context = canvas.getContext("2d");
      if (!context) throw new Error("no 2D canvas");
      const picture = context.createImageData(32, 32);
      crypto.getRandomValues(picture.data);
      context.putImageData(picture, 0, 0);
      const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, "image/png"));
      await fetch(url, { method: "POST", headers: { "Content-Type": "image/png" }, body: blob });
    } else {
      const text = btoa(String.fromCharCode(...(pixels ?? [])));
      await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ note: "looks harmless", frame_excerpt: text }),
      });
    }
  },
};

(window as unknown as { __certivoE2E: E2eApi }).__certivoE2E = api;
