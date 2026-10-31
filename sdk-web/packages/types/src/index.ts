/**
 * Types shared by every SDK package. This package has NO runtime code: it is erased when the SDK is
 * built, so it adds nothing to the bundle. It exists so that `capture`, `inference`, `core` and `ui` can
 * agree on a few words without importing each other (the dependency rules are in docs/adr/0021).
 */

/** Which signing algorithm a device key uses (ADR 0020). */
export type SigningAlg = "Ed25519" | "ECDSA-P256";

/**
 * Who produced a score. "self": the device scored its own camera (the default, and all Phase 0 builds).
 * "observer": a participant's device scored someone else's incoming video (decision D-02, built in P1-10).
 *
 * The role exists in the SDK's own types, but it CANNOT be sent yet: the platform's packet format
 * (BUILD_SPEC_0 section 4) has no role field and the server refuses unknown fields. Sending an observer
 * packet needs a Spec 0 amendment first (docs/adr/0022).
 */
export type PacketRole = "self" | "observer";

/**
 * What a model says about one interval. This is all that ever leaves the inference step: numbers and
 * code words, never pixels. Every result carries a confidence AND an explanation (Part 3 of the guide).
 * The names and ranges follow BUILD_SPEC_0 section 4 exactly:
 *   confidenceMilli  whole number 0..1000 (floats are not allowed in signed packets)
 *   reasonCodes      1 to 8 code words, each [a-z0-9_]{1,48}
 *   signalMilli      up to 16 named signals, each 0..1000 (may be empty)
 */
export interface ScoreResult {
  readonly confidenceMilli: number;
  readonly reasonCodes: readonly string[];
  readonly signalMilli: Readonly<Record<string, number>>;
  readonly modelVersion: string;
}

/** The four states of the in-call trust indicator (Doc 13). */
export type IndicatorState = "stable" | "borderline" | "flagged" | "paused";
