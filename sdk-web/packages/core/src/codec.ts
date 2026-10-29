import { b64uEncode } from "./base64url";
import { canonicalBytes } from "./canonical";
import { SdkError } from "./errors";
import type { ScorePacket } from "./packet";

/**
 * The domain that starts every signed score message (BUILD_SPEC_0 section 4). It keeps a signature made for
 * one purpose from being replayed as another.
 */
export const SCORE_DOMAIN = "certivo.score.v1\n";

/** The request body for a score packet: exactly the fields the platform accepts (ScoreEventIn), no more. */
export interface ScoreWirePacket {
  readonly v: 1;
  readonly participant_reference: string;
  readonly device_id: string;
  readonly seq: number;
  readonly interval_start_ms: number;
  readonly interval_end_ms: number;
  readonly confidence_milli: number;
  readonly model_version: string;
  readonly explanation: {
    readonly reason_codes: readonly string[];
    readonly signal_milli: Readonly<Record<string, number>>;
  };
  /** 86 characters of base64url: an Ed25519 signature, 64 bytes. */
  readonly device_signature: string;
}

/** Turns a packet into the exact bytes to sign, and into the body to send. */
export interface PacketCodec {
  encodeForSigning(packet: ScorePacket): Uint8Array<ArrayBuffer>;
  toWire(packet: ScorePacket, signature: Uint8Array): ScoreWirePacket;
}

type Unsigned = Omit<ScoreWirePacket, "device_signature">;

function wireFields(packet: ScorePacket): Unsigned {
  return {
    v: packet.v,
    participant_reference: packet.participantReference,
    device_id: packet.deviceId,
    seq: packet.seq,
    interval_start_ms: packet.intervalStartMs,
    interval_end_ms: packet.intervalEndMs,
    confidence_milli: packet.result.confidenceMilli,
    model_version: packet.result.modelVersion,
    explanation: {
      reason_codes: [...packet.result.reasonCodes],
      signal_milli: { ...packet.result.signalMilli },
    },
  };
}

function requireSelf(packet: ScorePacket): void {
  if (packet.role !== "self") {
    throw new SdkError(
      "not_implemented",
      "Observer packets cannot be sent yet: the platform's packet format (BUILD_SPEC_0 section 4) has no role field. See decision D-02 and docs/adr/0022.",
    );
  }
}

/** The object the device signs: the packet without its signature, plus the session ID (which the URL carries). */
export function signedPayload(packet: ScorePacket): Record<string, unknown> {
  requireSelf(packet);
  return { ...wireFields(packet), session_id: packet.sessionId };
}

/** Packet format version 1, exactly as BUILD_SPEC_0 section 4 defines it. */
export class ScoreCodecV1 implements PacketCodec {
  encodeForSigning(packet: ScorePacket): Uint8Array<ArrayBuffer> {
    const domain = new TextEncoder().encode(SCORE_DOMAIN);
    const body = canonicalBytes(signedPayload(packet));
    const message = new Uint8Array(domain.length + body.length);
    message.set(domain, 0);
    message.set(body, domain.length);
    return message;
  }

  toWire(packet: ScorePacket, signature: Uint8Array): ScoreWirePacket {
    requireSelf(packet);
    if (signature.length !== 64) {
      throw new SdkError("invalid_packet", `a signature must be 64 bytes, not ${signature.length}`);
    }
    return { ...wireFields(packet), device_signature: b64uEncode(signature) };
  }
}

export const scoreCodecV1: PacketCodec = new ScoreCodecV1();
