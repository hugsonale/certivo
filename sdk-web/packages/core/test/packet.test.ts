import { describe, expect, it } from "vitest";
import { buildPacket, type PacketInput, SdkError, unimplementedCodec } from "../src/index";

const valid: PacketInput = {
  sessionId: "cs_1",
  participantRef: "p1",
  deviceId: "dev_1",
  seq: 0,
  intervalStartMs: 1000,
  intervalEndMs: 6000,
  result: { confidence: 0.9, reasonCodes: ["consistent_face"], modelVersion: "test-0" },
  alg: "Ed25519",
};

const rejects = (change: Partial<PacketInput>, code = "invalid_packet") => {
  try {
    buildPacket({ ...valid, ...change });
  } catch (error) {
    expect(error).toBeInstanceOf(SdkError);
    expect((error as SdkError).code).toBe(code);
    return;
  }
  throw new Error("expected buildPacket to refuse this packet");
};

describe("buildPacket", () => {
  it("builds a normal packet, with the role 'self' by default", () => {
    const packet = buildPacket(valid);
    expect(packet.role).toBe("self");
    expect(packet.subjectParticipantRef).toBeUndefined();
    expect("subjectParticipantRef" in packet).toBe(false);
  });

  it("refuses a score with no explanation (guide Part 3)", () => {
    rejects({ result: { ...valid.result, reasonCodes: [] } });
  });

  it("refuses a score with no confidence, or a nonsense one", () => {
    for (const confidence of [Number.NaN, Number.POSITIVE_INFINITY, -0.1, 1.1]) {
      rejects({ result: { ...valid.result, confidence } });
    }
  });

  it("refuses a score that does not say which model made it", () => {
    rejects({ result: { ...valid.result, modelVersion: "" } });
  });

  it("refuses bad reason codes, sequence numbers and intervals", () => {
    rejects({ result: { ...valid.result, reasonCodes: [""] } });
    rejects({ result: { ...valid.result, reasonCodes: ["x".repeat(65)] } });
    rejects({ seq: -1 });
    rejects({ seq: 1.5 });
    rejects({ intervalEndMs: 1000 });
    rejects({ intervalEndMs: 900 });
  });

  describe("the observer role, reserved for receiver-side scoring (D-02, ADR 0021)", () => {
    it("accepts an observer packet that names who was observed", () => {
      const packet = buildPacket({ ...valid, role: "observer", subjectParticipantRef: "p2" });
      expect(packet.role).toBe("observer");
      expect(packet.subjectParticipantRef).toBe("p2");
    });

    it("refuses an observer packet that does not say who was observed", () => {
      rejects({ role: "observer" });
    });

    it("refuses someone observing themselves", () => {
      rejects({ role: "observer", subjectParticipantRef: "p1" });
    });

    it("refuses a 'self' packet that names a subject", () => {
      rejects({ role: "self", subjectParticipantRef: "p2" });
      rejects({ subjectParticipantRef: "p2" });
    });
  });
});

describe("the placeholder codec", () => {
  it("fails loudly instead of sending a guessed format", () => {
    const packet = buildPacket(valid);
    expect(() => unimplementedCodec.encodeForSigning(packet)).toThrow(/P0-22/);
    expect(() => unimplementedCodec.toWire(packet, new Uint8Array())).toThrow(/P0-22/);
  });
});
