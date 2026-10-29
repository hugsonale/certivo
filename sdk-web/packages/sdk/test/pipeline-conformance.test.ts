/**
 * The whole loop, end to end, against the platform's published test vector: a frame goes in, and the request body that
 * comes out is the platform's own vector packet with its own signature. (P0-22: "reproduce the canonical bytes and
 * signature".) Uses the vector's PUBLIC test-only key; never real keys.
 */
import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { MemoryPacketBuffer, scoreCodecV1 } from "@certivo/sdk-core";
import { describe, expect, it, vi } from "vitest";
import { vectorSigner } from "../../core/test/vector-signer";
import { VerificationPipeline, type WaitingPacket } from "../src/index";

const file = join(__dirname, "..", "..", "..", "..", "docs", "spec", "test-vectors", "score-packet-v1.json");

describe("the pipeline reproduces the platform's score-packet vector", () => {
  it("produces the vector's exact request body and signature on its fourth interval", async () => {
    expect(existsSync(file), `${file} is missing: the conformance gate cannot run`).toBe(true);
    const vector = JSON.parse(readFileSync(file, "utf8")) as {
      test_only_private_seed_hex: string;
      public_key_b64u: string;
      signature_b64u: string;
      packet: Record<string, unknown> & {
        session_id: string;
        participant_reference: string;
        device_id: string;
        seq: number;
        interval_end_ms: number;
        confidence_milli: number;
        model_version: string;
        explanation: { reason_codes: string[]; signal_milli: Record<string, number> };
      };
    };
    const p = vector.packet;
    const sent: unknown[] = [];
    const ticks = [1760000001000, 1760000002000, 1760000003000, p.interval_end_ms]; // the 4th interval is 3000..4000
    const pipeline = new VerificationPipeline({
      source: {
        start: async () => {},
        stop: () => {},
        grab: async () => ({ width: 1, height: 1, timestampMs: 0, image: {} as ImageBitmap, close: vi.fn() }),
      },
      scorer: {
        score: async () => ({
          confidenceMilli: p.confidence_milli,
          reasonCodes: p.explanation.reason_codes,
          signalMilli: p.explanation.signal_milli,
          modelVersion: p.model_version,
        }),
      },
      signer: await vectorSigner(vector.test_only_private_seed_hex, vector.public_key_b64u),
      codec: scoreCodecV1,
      send: async (body) => {
        sent.push(body);
      },
      buffer: new MemoryPacketBuffer<WaitingPacket>(10),
      clock: () => ticks.shift() ?? 0,
      sessionId: p.session_id,
      participantReference: p.participant_reference,
      deviceId: p.device_id,
      intervalMs: 1000,
    });

    for (let i = 0; i < 4; i++) await pipeline.runInterval();

    const { session_id: _sessionId, ...expectedFields } = p;
    expect(sent[3]).toEqual({ ...expectedFields, device_signature: vector.signature_b64u });
    expect((sent[3] as { seq: number }).seq).toBe(3);
  });
});
