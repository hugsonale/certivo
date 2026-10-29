import { describe, expect, it } from "vitest";
import { buildPacket, SCORE_DOMAIN, SdkError, scoreCodecV1, signedPayload } from "../src/index";

const packet = buildPacket({
  sessionId: "cs_00000000000000000000000000000001",
  participantReference: "alice",
  deviceId: "dev_00000000000000000000000000000001",
  seq: 0,
  intervalStartMs: 1000,
  intervalEndMs: 2000,
  result: { confidenceMilli: 0, reasonCodes: ["consistent_motion"], signalMilli: {}, modelVersion: "edge-0.1.0" },
});

// Exactly the fields of the platform's request schema (platform/app/schemas.py, ScoreEventIn). It forbids any other.
const SERVER_FIELDS = [
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
];

describe("the version 1 packet codec", () => {
  it("starts every signed message with the domain", () => {
    expect(SCORE_DOMAIN).toBe("certivo.score.v1\n");
    expect(new TextDecoder().decode(scoreCodecV1.encodeForSigning(packet).slice(0, SCORE_DOMAIN.length))).toBe(
      SCORE_DOMAIN,
    );
  });

  it("signs the packet WITH its session ID and WITHOUT a signature", () => {
    const payload = signedPayload(packet);
    expect(payload.session_id).toBe("cs_00000000000000000000000000000001");
    expect("device_signature" in payload).toBe(false);
    expect("role" in payload || "alg" in payload).toBe(false);
  });

  it("sends exactly the fields the server accepts, and no session ID", () => {
    const wire = scoreCodecV1.toWire(packet, new Uint8Array(64));
    expect(Object.keys(wire).sort()).toEqual(SERVER_FIELDS);
    expect(wire.device_signature.length).toBe(86);
    expect(JSON.stringify(wire)).not.toContain("cs_00000000000000000000000000000001");
  });

  it("copies the explanation, so changing the body cannot change the packet", () => {
    const wire = scoreCodecV1.toWire(packet, new Uint8Array(64));
    (wire.explanation.reason_codes as string[]).push("tampered");
    expect(packet.result.reasonCodes).toEqual(["consistent_motion"]);
  });

  it("refuses a signature that is not 64 bytes", () => {
    for (const length of [0, 63, 65]) {
      expect(() => scoreCodecV1.toWire(packet, new Uint8Array(length))).toThrow(SdkError);
    }
  });

  it("refuses an observer packet in both directions: the platform has no role field yet", () => {
    const observer = buildPacket({
      ...{ sessionId: packet.sessionId, participantReference: "alice", deviceId: packet.deviceId },
      seq: 0,
      intervalStartMs: 1000,
      intervalEndMs: 2000,
      result: packet.result,
      role: "observer",
      subjectParticipantReference: "bob",
    });
    for (const attempt of [
      () => scoreCodecV1.encodeForSigning(observer),
      () => scoreCodecV1.toWire(observer, new Uint8Array(64)),
    ]) {
      try {
        attempt();
        throw new Error("expected a refusal");
      } catch (error) {
        expect((error as SdkError).code).toBe("not_implemented");
      }
    }
  });
});
