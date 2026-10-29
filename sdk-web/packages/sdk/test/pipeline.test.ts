import {
  type DeviceSigner,
  MemoryPacketBuffer,
  type PacketCodec,
  type ScorePacket,
  SdkError,
  unimplementedCodec,
} from "@certivo/sdk-core";
import type { Scorer } from "@certivo/sdk-inference";
import type { ScoreResult } from "@certivo/sdk-types";
import { describe, expect, it, vi } from "vitest";
import { type PipelineDeps, VerificationPipeline, type WaitingPacket } from "../src/index";

const result: ScoreResult = { confidence: 0.85, reasonCodes: ["consistent_face"], modelVersion: "test-0" };

function setup(overrides: Partial<PipelineDeps> = {}, scorer?: Scorer) {
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
  const packets: ScorePacket[] = [];
  const codec: PacketCodec = {
    encodeForSigning: (p) => {
      packets.push(p);
      return new TextEncoder().encode(JSON.stringify(p));
    },
    toWire: (p, signature) => ({ seq: p.seq, role: p.role, result: p.result, signature: Array.from(signature) }),
  };
  const signer: DeviceSigner = {
    alg: "Ed25519",
    publicKeyRaw: async () => new Uint8Array(32),
    sign: async () => new Uint8Array([9, 9]),
  };
  const bodies: unknown[] = [];
  let now = 10_000;
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
    sessionId: "cs_1",
    participantRef: "p1",
    deviceId: "dev_1",
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

  it("never lets a picture reach the packet or the thing that is sent", async () => {
    const { pipeline, packets, bodies } = setup();
    await pipeline.runInterval();
    const everything = JSON.stringify([packets, bodies]);
    expect(everything).not.toContain("pixels");
    expect(everything).not.toContain("image");
    expect(Object.keys(packets[0]!.result).sort()).toEqual(["confidence", "modelVersion", "reasonCodes"]);
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

  it("fails loudly, and sends nothing, while the packet format is still the placeholder", async () => {
    const { pipeline, frames, bodies } = setup({ codec: unimplementedCodec });
    await expect(pipeline.runInterval()).rejects.toMatchObject({ code: "not_implemented" });
    expect(bodies).toEqual([]);
    expect(frames[0]?.close).toHaveBeenCalledTimes(1);
  });

  it("carries the observer role through to the packet (reserved for D-02)", async () => {
    const { pipeline, packets } = setup({ role: "observer", subjectParticipantRef: "p2" });
    await pipeline.runInterval();
    expect(packets[0]).toMatchObject({ role: "observer", subjectParticipantRef: "p2", participantRef: "p1" });
  });

  it("uses the role 'self' when none is given", async () => {
    const { pipeline, packets } = setup();
    await pipeline.runInterval();
    expect(packets[0]?.role).toBe("self");
  });
});
