import type { PacketRole, ScoreResult } from "@certivo/sdk-types";
import { SdkError } from "./errors";

/**
 * One score for one interval of one participant, as the SDK holds it before it is signed and sent.
 * Field names here are the SDK's own; `codec.ts` turns them into the platform's names (BUILD_SPEC_0 section 4).
 */
export interface ScorePacket {
  /** Packet format version. Always 1. */
  readonly v: 1;
  /** Taken from the session the partner started. It is signed but not sent in the body (the URL carries it). */
  readonly sessionId: string;
  readonly participantReference: string;
  readonly deviceId: string;
  readonly seq: number;
  readonly intervalStartMs: number;
  readonly intervalEndMs: number;
  readonly result: ScoreResult;
  /** "self" in every Phase 0 build. An observer packet cannot be sent yet (docs/adr/0022). */
  readonly role: PacketRole;
  /** Who was scored. Present only when role is "observer". */
  readonly subjectParticipantReference?: string;
}

export interface PacketInput {
  sessionId: string;
  participantReference: string;
  deviceId: string;
  seq: number;
  intervalStartMs: number;
  intervalEndMs: number;
  result: ScoreResult;
  role?: PacketRole;
  subjectParticipantReference?: string;
}

/** The longest interval the platform accepts (BUILD_SPEC_0 section 4). */
export const MAX_INTERVAL_MS = 60_000;

// These rules are copied from the platform's request schema (platform/app/schemas.py, ScoreEventIn). The server
// refuses anything else, so checking here turns a rejected request into a clear error on the device.
const REFERENCE = /^[A-Za-z0-9_.:-]{1,64}$/;
const DEVICE_ID = /^dev_[0-9a-f]{32}$/;
const SESSION_ID = /^[A-Za-z0-9_-]{1,64}$/;
const MODEL_VERSION = /^[A-Za-z0-9_.-]{1,64}$/;
const CODE = /^[a-z0-9_]{1,48}$/;

function invalid(message: string): never {
  throw new SdkError("invalid_packet", message);
}

const isWhole = (n: unknown, min: number, max: number): boolean =>
  typeof n === "number" && Number.isInteger(n) && n >= min && n <= max;

/**
 * Builds a packet and refuses to build a wrong one. The rules come from the platform's schema and the guide:
 * no score without a confidence and an explanation (Part 3), whole numbers only, and the observer role must
 * say who was observed.
 */
export function buildPacket(input: PacketInput): ScorePacket {
  const role = input.role ?? "self";
  if (!SESSION_ID.test(input.sessionId)) invalid("the session ID is not in the expected form");
  if (!REFERENCE.test(input.participantReference))
    invalid("participantReference must be 1 to 64 of A-Z a-z 0-9 _ . : -");
  if (!DEVICE_ID.test(input.deviceId)) invalid("deviceId must look like dev_ followed by 32 hex characters");
  if (!isWhole(input.seq, 0, 2 ** 31 - 1)) invalid("seq must be a whole number from 0 to 2147483647");
  if (!isWhole(input.intervalStartMs, 0, Number.MAX_SAFE_INTEGER))
    invalid("intervalStartMs must be a whole number, 0 or more");
  if (!isWhole(input.intervalEndMs, 0, Number.MAX_SAFE_INTEGER))
    invalid("intervalEndMs must be a whole number, 0 or more");
  if (!(input.intervalEndMs > input.intervalStartMs)) invalid("the interval must end after it starts");
  if (input.intervalEndMs - input.intervalStartMs > MAX_INTERVAL_MS)
    invalid("an interval may be at most 60 seconds long");

  const { confidenceMilli, reasonCodes, signalMilli, modelVersion } = input.result;
  if (!isWhole(confidenceMilli, 0, 1000)) invalid("confidenceMilli must be a whole number from 0 to 1000");
  if (reasonCodes.length < 1) invalid("a score must come with at least one reason code");
  if (reasonCodes.length > 8) invalid("a score may have at most 8 reason codes");
  if (reasonCodes.some((c) => !CODE.test(c))) invalid("reason codes must be 1 to 48 of a-z 0-9 _");
  const signals = Object.entries(signalMilli);
  if (signals.length > 16) invalid("a score may have at most 16 signals");
  for (const [name, value] of signals) {
    if (!CODE.test(name)) invalid("signal names must be 1 to 48 of a-z 0-9 _");
    if (!isWhole(value, 0, 1000)) invalid("signal values must be whole numbers from 0 to 1000");
  }
  if (!MODEL_VERSION.test(modelVersion)) invalid("the model version must be recorded, 1 to 64 of A-Z a-z 0-9 _ . -");

  if (role === "observer") {
    if (!input.subjectParticipantReference) invalid("an observer packet must say which participant was observed");
    if (!REFERENCE.test(input.subjectParticipantReference))
      invalid("subjectParticipantReference is not in the expected form");
    if (input.subjectParticipantReference === input.participantReference)
      invalid("a participant cannot observe themselves");
  } else if (input.subjectParticipantReference !== undefined) {
    invalid("only an observer packet may name a subject participant");
  }

  return {
    v: 1,
    sessionId: input.sessionId,
    participantReference: input.participantReference,
    deviceId: input.deviceId,
    seq: input.seq,
    intervalStartMs: input.intervalStartMs,
    intervalEndMs: input.intervalEndMs,
    result: input.result,
    role,
    ...(input.subjectParticipantReference !== undefined
      ? { subjectParticipantReference: input.subjectParticipantReference }
      : {}),
  };
}
