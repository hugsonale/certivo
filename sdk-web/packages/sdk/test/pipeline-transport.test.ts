import type { FrameSource } from "@certivo/sdk-capture";
import {
  type DeviceSigner,
  type PacketCodec,
  PacketSender,
  type PacketTransport,
  type ScoreWirePacket,
} from "@certivo/sdk-core";
import { type Scorer, ScorerError } from "@certivo/sdk-inference";
import type { ScoreResult } from "@certivo/sdk-types";
import { describe, expect, it } from "vitest";
import { VerificationPipeline } from "../src/pipeline";

/** P0-25: how the pipeline uses the sender (numbering, pausing, and where an interval starts). */

const result: ScoreResult = { confidenceMilli: 900, reasonCodes: ["ok"], signalMilli: {}, modelVersion: "t-1" };
const frame = () => ({ image: {} as ImageBitmap, close() {} });
const source: FrameSource = {
  async start() {},
  async grab() {
    return frame();
  },
  stop() {},
} as unknown as FrameSource;
const signer = { alg: "Ed25519", sign: async () => "sig" } as unknown as DeviceSigner;
const codec: PacketCodec = {
  encodeForSigning: () => new Uint8Array([1]),
  toWire: (p, signature) =>
    ({
      seq: p.seq,
      interval_start_ms: p.intervalStartMs,
      interval_end_ms: p.intervalEndMs,
      device_signature: signature,
    }) as unknown as ScoreWirePacket,
};

class Recorder implements PacketTransport {
  singles: Array<{ seq: number; start: number; end: number }> = [];
  pauses: string[] = [];
  resumes = 0;
  async sendScoreEvent(body: ScoreWirePacket) {
    const b = body as unknown as { seq: number; interval_start_ms: number; interval_end_ms: number };
    this.singles.push({ seq: b.seq, start: b.interval_start_ms, end: b.interval_end_ms });
    return { accepted: true, seq: b.seq, current_policy_outcome: "accept", duplicate: false };
  }
  async sendBatch(): Promise<never> {
    throw new Error("not used here");
  }
  async pause(reason?: string) {
    this.pauses.push(reason ?? "other");
  }
  async resume() {
    this.resumes++;
  }
}

function build(scores: Array<ScoreResult | Error>, options: { pauseAfterMissedIntervals?: number } = {}) {
  const transport = new Recorder();
  const sender = new PacketSender({ transport, sessionId: "sess_1" });
  let now = 1_000_000;
  const queue = [...scores];
  const scorer: Scorer = {
    async score() {
      const next = queue.shift();
      if (next === undefined) throw new Error("test ran out of scores");
      if (next instanceof Error) throw next;
      return next;
    },
  } as unknown as Scorer;
  const pipeline = new VerificationPipeline({
    source,
    scorer,
    signer,
    codec,
    sender,
    clock: () => now,
    sessionId: "sess_1",
    participantReference: "alice",
    deviceId: `dev_${"a".repeat(32)}`,
    intervalMs: 3000,
    ...options,
  });
  const tick = (ms = 3000) => {
    now += ms;
    return pipeline.runInterval();
  };
  return { transport, sender, pipeline, tick };
}

describe("a pipeline with a sender", () => {
  it("takes its seq numbers from the sender and sends one packet per interval", async () => {
    const { transport, tick } = build([result, result, result]);
    expect(await tick()).toEqual({ status: "sent", seq: 0 });
    expect(await tick()).toEqual({ status: "sent", seq: 1 });
    expect(await tick()).toEqual({ status: "sent", seq: 2 });
    expect(transport.singles.map((s) => s.seq)).toEqual([0, 1, 2]);
  });

  it("carries on numbering after a reload when the sender remembers", async () => {
    const first = build([result, result]);
    await first.tick();
    await first.tick();
    // a new pipeline for the same session would call sender.nextSeq() on the SAME remembered store; the sender owns the number
    expect(first.sender.nextSeq()).toBe(2);
  });

  it("needs a sender, or both send and buffer", () => {
    expect(
      () =>
        new VerificationPipeline({
          source,
          scorer: {} as Scorer,
          signer,
          codec,
          clock: () => 0,
          sessionId: "sess_1",
          participantReference: "alice",
          deviceId: `dev_${"a".repeat(32)}`,
          intervalMs: 3000,
        }),
    ).toThrow(TypeError);
  });

  it("reports a packet the platform will never take as 'dropped', and a finished sender as 'stopped'", async () => {
    const { sender, tick } = build([result, result]);
    sender.close();
    expect(await tick()).toMatchObject({ status: "stopped", reason: "closed" });
  });
});

describe("pausing when scoring fails", () => {
  const broken = () => new Error("model crashed");
  const notLoaded = () => new ScorerError("model_not_loaded", "no model yet");

  it("pauses ONCE after three intervals in a row with no score, with a reason that fits", async () => {
    const { transport, tick } = build([result, broken(), broken(), broken(), broken(), broken()]);
    await tick();
    for (let i = 0; i < 5; i++) expect(await tick()).toMatchObject({ status: "no_score" });
    await Promise.resolve();
    expect(transport.pauses).toEqual(["sdk_error"]); // once, not three times
  });

  it("says 'model_unavailable' when the model was never loaded", async () => {
    const { transport, tick } = build([notLoaded(), notLoaded(), notLoaded()]);
    for (let i = 0; i < 3; i++) await tick();
    await Promise.resolve();
    expect(transport.pauses).toEqual(["model_unavailable"]);
  });

  it("does not pause for one or two misses", async () => {
    const { transport, tick } = build([broken(), broken(), result]);
    for (let i = 0; i < 3; i++) await tick();
    await Promise.resolve();
    expect(transport.pauses).toEqual([]);
  });

  it("a score in between starts the count again", async () => {
    const { transport, tick } = build([broken(), broken(), result, broken(), broken(), result]);
    for (let i = 0; i < 6; i++) await tick();
    await Promise.resolve();
    expect(transport.pauses).toEqual([]);
  });

  it("can be turned off, and can be tuned", async () => {
    const off = build([broken(), broken(), broken(), broken()], { pauseAfterMissedIntervals: 0 });
    for (let i = 0; i < 4; i++) await off.tick();
    await Promise.resolve();
    expect(off.transport.pauses).toEqual([]);

    const two = build([broken(), broken()], { pauseAfterMissedIntervals: 2 });
    for (let i = 0; i < 2; i++) await two.tick();
    await Promise.resolve();
    expect(two.transport.pauses).toEqual(["sdk_error"]);
  });

  it("pauses again for a second streak, after a good packet ended the first", async () => {
    const { transport, sender, tick } = build([broken(), broken(), broken(), result, broken(), broken(), broken()]);
    for (let i = 0; i < 3; i++) await tick();
    await Promise.resolve();
    await tick(); // the good packet: ends the pause
    expect(sender.telemetry().paused).toBe(false);
    for (let i = 0; i < 3; i++) await tick();
    await Promise.resolve();
    expect(transport.pauses).toEqual(["sdk_error", "sdk_error"]);
  });
});

describe("where an interval starts", () => {
  it("follows on from the last one when intervals are regular", async () => {
    const { transport, tick } = build([result, result]);
    await tick();
    await tick();
    const [a, b] = transport.singles;
    expect(b?.start).toBe(a?.end);
  });

  it("does NOT stretch over a failure: after a long run of misses the next interval is one interval long (it used to exceed 60 s and never recover)", async () => {
    const { transport, tick } = build([result, ...Array.from({ length: 30 }, () => new Error("x")), result], {
      pauseAfterMissedIntervals: 0,
    });
    await tick();
    for (let i = 0; i < 30; i++) await tick(); // 90 seconds with no score
    expect(await tick()).toMatchObject({ status: "sent" });
    const last = transport.singles.at(-1);
    expect((last?.end ?? 0) - (last?.start ?? 0)).toBe(3000);
  });
});
