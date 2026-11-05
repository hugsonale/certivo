import {
  IntervalRunner,
  PacketSender,
  provisionDevice,
  SDK_VERSION,
  SessionClient,
  scoreCodecV1,
  VerificationPipeline,
  VideoElementFrameSource,
  WorkerScorer,
} from "@certivo/sdk";

/**
 * The page the overhead harness measures (guide P0-27). Both modes run the SAME workload: a fake camera (a canvas
 * stream) sent through a loopback video call inside the page (encode and decode, like a real call). In "sdk" mode the
 * Web SDK ALSO runs on that same stream. The difference between the two is the cost of the SDK.
 */
export interface WindowMetrics {
  /** Milliseconds each interval spent in each stage, one entry per interval. */
  phases: { total: number[]; capture: number[]; model: number[]; sign: number[]; submit: number[] };
  /** How long each score took inside the worker (from the worker's own clock). */
  workerModelMs: number[];
  /** Main-thread tasks longer than 50 ms during the window (milliseconds each). */
  longTasks: number[];
  /** Bytes the loopback call's video sent during the window (context for the SDK's bandwidth). */
  callBytesSent: number;
  /** Outcomes of the intervals that ran. */
  outcomes: Record<string, number>;
  intervals: number;
}

export interface MemoryReading {
  bytes: number | null;
  source: "measureUserAgentSpecificMemory" | "jsHeap" | "none";
}

export interface OverheadApi {
  start(options: {
    mode: "baseline" | "sdk";
    intervalMs: number;
    side: number;
    camera: { width: number; height: number; fps: number };
  }): Promise<void>;
  beginWindow(): Promise<void>;
  endWindow(): Promise<WindowMetrics>;
  memory(): Promise<MemoryReading>;
  /** What the page reports about itself, for the machine record. */
  environment(): {
    hardwareConcurrency: number;
    deviceMemoryGb: number | null;
    crossOriginIsolated: boolean;
    userAgent: string;
  };
  stop(): Promise<void>;
}

function makeCamera(WIDTH: number, HEIGHT: number, fps: number): { stream: MediaStream; stop(): void } {
  const canvas = document.createElement("canvas");
  canvas.width = WIDTH;
  canvas.height = HEIGHT;
  const context = canvas.getContext("2d");
  if (!context) throw new Error("no 2D canvas");
  const draw = () => {
    const t = performance.now() / 1000;
    context.fillStyle = "#12263f";
    context.fillRect(0, 0, WIDTH, HEIGHT);
    context.fillStyle = "#7fb7ff";
    context.beginPath();
    context.arc(WIDTH / 2 + Math.sin(t * 1.4) * 120, HEIGHT * 0.45 + Math.cos(t * 2.1) * 20, 90, 0, Math.PI * 2);
    context.fill();
    context.fillRect(WIDTH / 2 - 110 + Math.sin(t * 1.4) * 120, HEIGHT * 0.45 + 100, 220, 130);
  };
  draw();
  const timer = setInterval(draw, Math.round(1000 / fps));
  const stream = canvas.captureStream(fps);
  return {
    stream,
    stop() {
      clearInterval(timer);
      for (const track of stream.getTracks()) track.stop();
    },
  };
}

/** A video call from this page to itself: the stream is encoded, "sent", decoded and played, as in a real call. */
async function startLoopbackCall(stream: MediaStream): Promise<{ stats(): Promise<number>; stop(): void }> {
  const sender = new RTCPeerConnection();
  const receiver = new RTCPeerConnection();
  sender.onicecandidate = (e) => e.candidate && void receiver.addIceCandidate(e.candidate);
  receiver.onicecandidate = (e) => e.candidate && void sender.addIceCandidate(e.candidate);
  const remote = document.createElement("video");
  remote.muted = true;
  remote.autoplay = true;
  remote.playsInline = true;
  document.body.append(remote);
  receiver.ontrack = (e) => {
    remote.srcObject = e.streams[0] ?? new MediaStream([e.track]);
  };
  for (const track of stream.getVideoTracks()) sender.addTrack(track, stream);
  await sender.setLocalDescription(await sender.createOffer());
  await receiver.setRemoteDescription(sender.localDescription as RTCSessionDescriptionInit);
  await receiver.setLocalDescription(await receiver.createAnswer());
  await sender.setRemoteDescription(receiver.localDescription as RTCSessionDescriptionInit);
  return {
    async stats() {
      let bytes = 0;
      for (const report of (await sender.getStats()).values()) {
        if (report.type === "outbound-rtp" && report.kind === "video") bytes += report.bytesSent ?? 0;
      }
      return bytes;
    },
    stop() {
      sender.close();
      receiver.close();
      remote.remove();
    },
  };
}

const empty = (): WindowMetrics["phases"] => ({ total: [], capture: [], model: [], sign: [], submit: [] });

let camera: ReturnType<typeof makeCamera> | undefined;
let call: Awaited<ReturnType<typeof startLoopbackCall>> | undefined;
const phases = empty();
let outcomes: Record<string, number> = {};
let intervals = 0;
let longTasks: number[] = [];
let callBytesAtStart = 0;
let stopSdk: (() => Promise<void>) | undefined;
let workerHandle: Worker | undefined;
let observer: PerformanceObserver | undefined;

/** Times each call of `object[method]` into `into`, without changing what it does. */
function timed<T extends object>(object: T, method: keyof T & string, into: number[]): T {
  return new Proxy(object, {
    get(target, property) {
      const value = Reflect.get(target, property, target) as unknown;
      if (property !== method || typeof value !== "function")
        return typeof value === "function" ? value.bind(target) : value;
      return async (...args: unknown[]) => {
        const started = performance.now();
        try {
          return await (value as (...a: unknown[]) => unknown).apply(target, args);
        } finally {
          into.push(performance.now() - started);
        }
      };
    },
  });
}

const api: OverheadApi = {
  async start({ mode, intervalMs, side, camera: size }) {
    camera = makeCamera(size.width, size.height, size.fps);
    call = await startLoopbackCall(camera.stream);
    try {
      observer = new PerformanceObserver((list) => {
        for (const entry of list.getEntries()) longTasks.push(entry.duration);
      });
      observer.observe({ type: "longtask", buffered: false });
    } catch {
      observer = undefined; // long-task timing is not available in every browser
    }
    if (mode === "baseline") return;

    const device = await provisionDevice({
      register: async () => ({ deviceId: `dev_${"0123456789abcdef".repeat(2)}` }),
    });
    const workerUrl = `/worker.js${location.search}`;
    workerHandle = new Worker(workerUrl);
    const scorer = timed(new WorkerScorer(workerHandle), "score", phases.model);
    const source = timed(new VideoElementFrameSource(camera.stream, { maxSide: side }), "grab", phases.capture);
    await source.start();
    const client = new SessionClient({
      baseUrl: location.origin,
      sessionId: "sess_overhead_1",
      sdkToken: "tok_overhead_not_a_secret",
      sdkVersion: SDK_VERSION,
      platform: "web",
    });
    const sender = timed(
      new PacketSender({ transport: client, sessionId: "sess_overhead_1" }),
      "submit",
      phases.submit,
    );
    const pipeline = new VerificationPipeline({
      source,
      scorer,
      signer: timed(device.signer, "sign", phases.sign),
      codec: scoreCodecV1,
      sender,
      clock: () => Date.now(),
      sessionId: "sess_overhead_1",
      participantReference: "p_overhead",
      deviceId: device.deviceId,
      intervalMs,
    });
    const runner = new IntervalRunner({
      intervalMs,
      run: async () => {
        const started = performance.now();
        try {
          return await pipeline.runInterval();
        } finally {
          phases.total.push(performance.now() - started);
        }
      },
      onOutcome: (outcome) => {
        intervals++;
        outcomes[outcome.status] = (outcomes[outcome.status] ?? 0) + 1;
      },
      onError: () => {
        intervals++;
        outcomes.error = (outcomes.error ?? 0) + 1;
      },
    });
    runner.start();
    stopSdk = async () => {
      await runner.stop();
      source.stop();
      sender.close();
      scorer.dispose();
    };
  },

  async beginWindow() {
    phases.total.length = 0;
    phases.capture.length = 0;
    phases.model.length = 0;
    phases.sign.length = 0;
    phases.submit.length = 0;
    outcomes = {};
    intervals = 0;
    longTasks = [];
    callBytesAtStart = (await call?.stats()) ?? 0;
    workerHandle?.postMessage({ type: "__reset" });
  },

  async endWindow() {
    const callBytesSent = ((await call?.stats()) ?? 0) - callBytesAtStart;
    const workerModelMs = workerHandle
      ? await new Promise<number[]>((resolve) => {
          const handle = workerHandle as Worker;
          const onMessage = (event: MessageEvent) => {
            if ((event.data as { type?: string } | null)?.type !== "__stats") return;
            handle.removeEventListener("message", onMessage);
            resolve((event.data as { modelMs: number[] }).modelMs);
          };
          handle.addEventListener("message", onMessage);
          handle.postMessage({ type: "__stats" });
        })
      : [];
    return {
      phases: { ...phases },
      workerModelMs,
      longTasks: [...longTasks],
      callBytesSent,
      outcomes: { ...outcomes },
      intervals,
    };
  },

  async memory(): Promise<MemoryReading> {
    const measure = (performance as unknown as { measureUserAgentSpecificMemory?: () => Promise<{ bytes: number }> })
      .measureUserAgentSpecificMemory;
    if (typeof measure === "function" && crossOriginIsolated) {
      try {
        return { bytes: (await measure.call(performance)).bytes, source: "measureUserAgentSpecificMemory" };
      } catch {
        // fall through to the coarser reading
      }
    }
    const heap = (performance as unknown as { memory?: { usedJSHeapSize: number } }).memory;
    return heap ? { bytes: heap.usedJSHeapSize, source: "jsHeap" } : { bytes: null, source: "none" };
  },

  environment() {
    return {
      hardwareConcurrency: navigator.hardwareConcurrency,
      deviceMemoryGb: (navigator as unknown as { deviceMemory?: number }).deviceMemory ?? null,
      crossOriginIsolated,
      userAgent: navigator.userAgent,
    };
  },

  async stop() {
    observer?.disconnect();
    await stopSdk?.();
    workerHandle?.terminate();
    call?.stop();
    camera?.stop();
  },
};

(window as unknown as { __overhead: OverheadApi }).__overhead = api;
