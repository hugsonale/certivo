import type { PacketRole, ScoreResult, SigningAlg } from "@certivo/sdk-types";
import { SdkError } from "./errors";

/**
 * One score for one interval of one participant.
 *
 * PROVISIONAL SHAPE. The field names and the exact bytes that get signed are fixed by Spec 0 and its
 * test vector, which step P0-22 reproduces in TypeScript. Until then the packet is built and checked here,
 * and turned into bytes by a PacketCodec that P0-22 supplies.
 */
export interface ScorePacket {
  readonly sessionId: string;
  readonly participantRef: string;
  readonly deviceId: string;
  readonly seq: number;
  readonly intervalStartMs: number;
  readonly intervalEndMs: number;
  /** "self" in every Phase 0 build. See docs/adr/0021. */
  readonly role: PacketRole;
  /** Who was scored. Present only when role is "observer". */
  readonly subjectParticipantRef?: string;
  readonly result: ScoreResult;
  readonly alg: SigningAlg;
}

export interface PacketInput {
  sessionId: string;
  participantRef: string;
  deviceId: string;
  seq: number;
  intervalStartMs: number;
  intervalEndMs: number;
  result: ScoreResult;
  alg: SigningAlg;
  role?: PacketRole;
  subjectParticipantRef?: string;
}

function invalid(message: string): never {
  throw new SdkError("invalid_packet", message);
}

/**
 * Builds a packet and refuses to build a wrong one. The rules come from the guide: no score without a
 * confidence and an explanation (Part 3), and the observer role must say who was observed.
 */
export function buildPacket(input: PacketInput): ScorePacket {
  const role = input.role ?? "self";
  if (!Number.isInteger(input.seq) || input.seq < 0) invalid("seq must be a whole number, 0 or more");
  if (!(input.intervalEndMs > input.intervalStartMs)) invalid("the interval must end after it starts");
  const { confidence, reasonCodes } = input.result;
  if (!Number.isFinite(confidence) || confidence < 0 || confidence > 1) {
    invalid("confidence must be a number from 0 to 1");
  }
  if (reasonCodes.length === 0) invalid("a score must come with at least one reason code");
  if (reasonCodes.some((c) => c.length === 0 || c.length > 64)) invalid("reason codes must be 1 to 64 characters");
  if (!input.result.modelVersion) invalid("the model version must be recorded with every score");
  if (role === "observer") {
    if (!input.subjectParticipantRef) invalid("an observer packet must say which participant was observed");
    if (input.subjectParticipantRef === input.participantRef) invalid("a participant cannot observe themselves");
  } else if (input.subjectParticipantRef !== undefined) {
    invalid("only an observer packet may name a subject participant");
  }
  const { subjectParticipantRef, ...rest } = input;
  return {
    ...rest,
    role,
    ...(subjectParticipantRef !== undefined ? { subjectParticipantRef } : {}),
  };
}

/** Turns a packet into the exact bytes to sign, and into the body to send. Supplied by P0-22. */
export interface PacketCodec {
  encodeForSigning(packet: ScorePacket): Uint8Array<ArrayBuffer>;
  toWire(packet: ScorePacket, signature: Uint8Array): unknown;
}

/** Stands in until P0-22: using it fails loudly instead of sending a guessed format. */
export const unimplementedCodec: PacketCodec = {
  encodeForSigning() {
    throw new SdkError("not_implemented", "The packet byte format arrives in P0-22 (Spec 0 and its test vector).");
  },
  toWire() {
    throw new SdkError("not_implemented", "The packet wire format arrives in P0-22 (Spec 0 and its test vector).");
  },
};
