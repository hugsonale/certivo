import type { ScoreResult } from "@certivo/sdk-types";
import { describe, expect, it } from "vitest";
import { buildPacket, MAX_INTERVAL_MS, type PacketInput, SdkError } from "../src/index";

const result: ScoreResult = {
  confidenceMilli: 912,
  reasonCodes: ["consistent_motion", "stable_texture"],
  signalMilli: { temporal: 940, texture: 880 },
  modelVersion: "edge-0.1.0",
};

const valid: PacketInput = {
  sessionId: "cs_00000000000000000000000000000001",
  participantReference: "alice",
  deviceId: "dev_00000000000000000000000000000001",
  seq: 3,
  intervalStartMs: 1760000003000,
  intervalEndMs: 1760000004000,
  result,
};

const refuses = (change: Partial<PacketInput>) => {
  try {
    buildPacket({ ...valid, ...change });
  } catch (error) {
    expect(error).toBeInstanceOf(SdkError);
    expect((error as SdkError).code).toBe("invalid_packet");
    return;
  }
  throw new Error(`expected buildPacket to refuse ${JSON.stringify(change)}`);
};
const withResult = (change: Partial<ScoreResult>): Partial<PacketInput> => ({ result: { ...result, ...change } });

describe("buildPacket", () => {
  it("builds a normal packet: version 1, role 'self', no subject", () => {
    const packet = buildPacket(valid);
    expect(packet.v).toBe(1);
    expect(packet.role).toBe("self");
    expect("subjectParticipantReference" in packet).toBe(false);
  });

  it("accepts the limits themselves", () => {
    buildPacket({ ...valid, seq: 0, intervalStartMs: 0, intervalEndMs: MAX_INTERVAL_MS });
    buildPacket({ ...valid, seq: 2 ** 31 - 1 });
    buildPacket({ ...valid, ...withResult({ confidenceMilli: 0 }) });
    buildPacket({ ...valid, ...withResult({ confidenceMilli: 1000 }) });
    buildPacket({ ...valid, ...withResult({ signalMilli: {} }) });
    buildPacket({ ...valid, ...withResult({ reasonCodes: Array.from({ length: 8 }, (_, i) => `code_${i}`) }) });
  });

  it("refuses a score with no explanation (guide Part 3)", () => {
    refuses(withResult({ reasonCodes: [] }));
  });

  it("refuses more than 8 reason codes, and badly written ones", () => {
    refuses(withResult({ reasonCodes: Array.from({ length: 9 }, (_, i) => `code_${i}`) }));
    for (const bad of ["", "Upper", "has space", "dash-ed", "x".repeat(49)])
      refuses(withResult({ reasonCodes: [bad] }));
  });

  it("refuses a confidence that is not a whole number from 0 to 1000", () => {
    for (const confidenceMilli of [Number.NaN, 0.5, 912.5, -1, 1001, Number.POSITIVE_INFINITY]) {
      refuses(withResult({ confidenceMilli }));
    }
  });

  it("refuses bad signals: too many, badly named, out of range, not whole", () => {
    refuses(withResult({ signalMilli: Object.fromEntries(Array.from({ length: 17 }, (_, i) => [`s_${i}`, 1])) }));
    refuses(withResult({ signalMilli: { Bad: 1 } }));
    refuses(withResult({ signalMilli: { ok: 1001 } }));
    refuses(withResult({ signalMilli: { ok: -1 } }));
    refuses(withResult({ signalMilli: { ok: 0.5 } }));
  });

  it("refuses a missing or badly written model version", () => {
    for (const modelVersion of ["", "has space", "x".repeat(65)]) refuses(withResult({ modelVersion }));
  });

  it("refuses badly written references and IDs", () => {
    refuses({ participantReference: "" });
    refuses({ participantReference: "has space" });
    refuses({ participantReference: "x".repeat(65) });
    refuses({ deviceId: "dev_123" });
    refuses({ deviceId: "DEV_00000000000000000000000000000001" });
    refuses({ sessionId: "" });
    refuses({ sessionId: "has/slash" });
  });

  it("refuses bad sequence numbers and intervals", () => {
    refuses({ seq: -1 });
    refuses({ seq: 1.5 });
    refuses({ seq: 2 ** 31 });
    refuses({ intervalStartMs: -1 });
    refuses({ intervalEndMs: valid.intervalStartMs });
    refuses({ intervalEndMs: valid.intervalStartMs - 1 });
    refuses({ intervalEndMs: valid.intervalStartMs + MAX_INTERVAL_MS + 1 });
    refuses({ intervalStartMs: 1.5 });
  });

  describe("the observer role (D-02): built in the SDK, but not yet sendable (docs/adr/0022)", () => {
    it("accepts an observer packet that names who was observed", () => {
      const packet = buildPacket({ ...valid, role: "observer", subjectParticipantReference: "bob" });
      expect(packet.role).toBe("observer");
      expect(packet.subjectParticipantReference).toBe("bob");
    });
    it("refuses an observer packet that does not say who was observed", () => refuses({ role: "observer" }));
    it("refuses someone observing themselves", () => {
      refuses({ role: "observer", subjectParticipantReference: "alice" });
    });
    it("refuses a 'self' packet that names a subject", () => {
      refuses({ role: "self", subjectParticipantReference: "bob" });
      refuses({ subjectParticipantReference: "bob" });
    });
  });
});
