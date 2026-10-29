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
 * The role is reserved in the packet now so that adding receiver-side scoring later does not change the
 * packet format again (docs/adr/0021).
 */
export type PacketRole = "self" | "observer";

/**
 * What a model says about one interval. This is all that ever leaves the inference step: numbers and
 * code words, never pixels. Every result carries a confidence AND an explanation (Part 3 of the guide).
 *
 * PROVISIONAL: the exact range of `confidence` and the catalogue of reason codes are fixed in P0-22
 * (Spec 0) and P0-38 (explanation generator).
 */
export interface ScoreResult {
  readonly confidence: number;
  readonly reasonCodes: readonly string[];
  readonly modelVersion: string;
}

/** The four states of the in-call trust indicator (Doc 13). */
export type IndicatorState = "stable" | "borderline" | "flagged" | "paused";
