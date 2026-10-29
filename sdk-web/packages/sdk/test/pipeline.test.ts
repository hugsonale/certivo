import {
  type DeviceSigner,
  MemoryPacketBuffer,
  type PacketCodec,
  type ScorePacket,
  SdkError,
  scoreCodecV1,
} from "@certivo/sdk-core";
import type { Scorer } from "@certivo/sdk-inference";
import type { ScoreResult } from "@certivo/sdk-types";
import { describe, expect, it, vi } from "vitest";
import { type PipelineDeps, VerificationPipeline, type WaitingPacket } from "../src/index";

const result: ScoreResult = {
  confidenceMilli: 850,
  reasonCodes: ["consistent_motion"],
  signalMilli: { temporal: 900 },
  modelVersion: "test-0",
};

function setup(overrides: Partial<PipelineDeps> = {}, scorer?: Scorer, codecOverride?: PacketCodec) {
  const events: string[] = [];
  const frames: Array<{ close: ReturnType<typeof vi.fn> }> = [];
  const source = {
    start: async () => {},
    stop: () => {},
    grab: async () => {
      const frame = {
        width: 2,
        height: 2,
        timestampMs: 0,
        image: { tag: "pixels" } as unknown as ImageBitmap,
        close: vi.fn(() => events.push("frame closed")),
      };
      frames.push(frame);
      return frame;
    },
  };
  // The REAL codec, wrapped only to remember each packet it was given.
  const packets: ScorePacket[] = [];
  const real = codecOverride ?? scoreCodecV1;
  const codec: PacketCodec = {
    encodeForSigning: (p) => {
      packets.push(p);
      return real.encodeForSigning(p);
    },
    toWire: (p, signature) => real.toWire(p, signature),
  };
  const signer: DeviceSigner = {
    alg: "Ed25519",
    publicKeyRaw: async () => new Uint8Array(32),
    sign: async () => new Uint8Array(64).fill(7),
  };
  const bodies: unknown[] = [];
  let now = 1_760_000_000_000;
  const deps: PipelineDeps = {
    source,
    scorer: scorer ?? {
      score: async () => {
        events.push("scored");
        return result;
      },
    },
    signer,
    codec,
    send: async (body) => {
      events.push("sent");
      bodies.push(body);
    },
    buffer: new MemoryPacketBuffer<WaitingPacket>(10),
    clock: () => (now += 5000),
    sessionId: "cs_00000000000000000000000000000001",
    participantReference: "alice",
    deviceId: "dev_00000000000000000000000000000001",
    intervalMs: 5000,
    ...overrides,
  };
  return { pipeline: new VerificationPipeline(deps), deps, events, frames, packets, bodies };
}

describe("one turn of the verification loop", () => {
  it("scores a frame, CLOSES it, and only then builds, signs and sends the packet", async () => {
    const { pipeline, events, frames } = setup();
    expect(await pipeline.runInterval()).toEqual({ status: "sent", seq: 0 });
    expect(events).toEqual(["scored", "frame closed", "sent"]);
    expect(frames[0]?.close).toHaveBeenCalledTimes(1);
  });

  it("sends exactly what the platform accepts, and never a picture", async () => {
    const { pipeline, bodies } = setup();
    await pipeline.runInterval();
    const body = bodies[0] as Record<string, unknown>;
    expect(Object.keys(body).sort()).toEqual([
      "confidence_milli",
      "device_id",
      "device_signature",
      "explanation",
      "interval_end_ms",
      "interval_start_ms",
      "model_version",
      "participant_reference",
      "seq",
      "v",
    ]);
    expect(JSON.stringify(body)).not.toContain("pixels");
    expect(JSON.stringify(body)).not.toContain("image");
  });

  it("numbers packets 0, 1, 2 and makes each interval start where the last one ended", async () => {
    const { pipeline, packets } = setup();
    for (let i = 0; i < 3; i++) await pipeline.runInterval();
    expect(packets.map((p) => p.seq)).toEqual([0, 1, 2]);
    expect(packets[1]?.intervalStartMs).toBe(packets[0]?.intervalEndMs);
    expect(packets[2]?.intervalStartMs).toBe(packets[1]?.intervalEndMs);
  });

  it("sends no packet when there is no score (never a decision without a score), and still closes the frame", async () => {
    const failing: Scorer = { score: async () => Promise.reject(new Error("model_not_loaded")) };
    const { pipeline, deps, frames, bodies } = setup({}, failing);
    expect(await pipeline.runInterval()).toEqual({ status: "no_score", reason: "model_not_loaded" });
    expect(bodies).toEqual([]);
    expect(frames[0]?.close).toHaveBeenCalledTimes(1);
    expect(deps.buffer.size).toBe(0);
  });

  it("does not use up a sequence number on a turn that produced no score", async () => {
    let fail = true;
    const sometimes: Scorer = { score: async () => (fail ? Promise.reject(new Error("no")) : result) };
    const { pipeline, packets } = setup({}, sometimes);
    await pipeline.runInterval();
    fail = false;
    await pipeline.runInterval();
    expect(packets.map((p) => p.seq)).toEqual([0]);
  });

  it("keeps a signed packet in the buffer when the platform cannot be reached", async () => {
    const { pipeline, deps } = setup({ send: async () => Promise.reject(new SdkError("network_error", "offline")) });
    expect(await pipeline.runInterval()).toMatchObject({ status: "buffered", seq: 0 });
    expect(deps.buffer.size).toBe(1);
  });

  it("does not hide other failures (an expired token must be noticed), and still closes the frame", async () => {
    const { pipeline, frames } = setup({ send: async () => Promise.reject(new SdkError("token_expired", "expired")) });
    await expect(pipeline.runInterval()).rejects.toMatchObject({ code: "token_expired" });
    expect(frames[0]?.close).toHaveBeenCalledTimes(1);
  });

  it("refuses to send a score the platform would refuse (a model that gives a nonsense result)", async () => {
    const nonsense: Scorer = { score: async () => ({ ...result, confidenceMilli: 1500 }) };
    const { pipeline, bodies, frames } = setup({}, nonsense);
    await expect(pipeline.runInterval()).rejects.toMatchObject({ code: "invalid_packet" });
    expect(bodies).toEqual([]);
    expect(frames[0]?.close).toHaveBeenCalledTimes(1);
  });

  it("holds the observer role back: it is built, but nothing is signed or sent (the platform has no role field yet)", async () => {
    const { pipeline, packets, bodies, frames } = setup({ role: "observer", subjectParticipantReference: "bob" });
    await expect(pipeline.runInterval()).rejects.toMatchObject({ code: "not_implemented" });
    expect(packets[0]).toMatchObject({
      role: "observer",
      subjectParticipantReference: "bob",
      participantReference: "alice",
    });
    expect(bodies).toEqual([]);
    expect(frames[0]?.close).toHaveBeenCalledTimes(1);
  });

  it("uses the role 'self' when none is given", async () => {
    const { pipeline, packets } = setup();
    await pipeline.runInterval();
    expect(packets[0]?.role).toBe("self");
  });
});
