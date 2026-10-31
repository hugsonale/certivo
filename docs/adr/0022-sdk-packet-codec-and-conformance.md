# 0022. The SDK's packet codec, and the conformance gate (P0-22)

**Date:** 29 October 2026
**Status:** Proposed

## Context

Step P0-22: reproduce the platform's canonical bytes and signature (docs/spec/test-vectors/) in TypeScript, and make that a CI gate for the SDK.
BUILD_SPEC_0 section 4 says every SDK "must reproduce canonical_bytes_hex and signature_b64u exactly before it is allowed to send traffic".
The P0-21 skeleton used a provisional packet shape, flagged as provisional. Reading the real spec and schema showed it was wrong in several places.

## What the spec showed (corrections to the P0-21 skeleton)

| P0-21 skeleton | The platform (BUILD_SPEC_0 section 4, platform/app/schemas.py) |
| :---- | :---- |
| `confidence` a number from 0 to 1 | `confidence_milli`, a whole number from 0 to 1000. Floats are not allowed in signed packets |
| reason codes only | `explanation` with `reason_codes` (1 to 8) and `signal_milli` (up to 16 named signals, 0 to 1000) |
| `alg`, `role` in the packet | Neither exists on the wire. The server schema forbids unknown fields (`extra="forbid"`) |
| `participantRef` | `participant_reference`, plus fixed patterns for every field |
| session ID in the body | The session ID is **signed but not sent**: the URL carries it |
| pause reason: any string | Exactly four words: connectivity, sdk_error, model_unavailable, other |

## Decision (proposed)

1. **The packet codec is Spec 0 section 4, exactly** (`packages/core/src/codec.ts`, `canonical.ts`, `base64url.ts`). A signed message is the domain `certivo.score.v1\n`, then the canonical JSON of the packet with `session_id` added and the signature left out.
2. **The contract is widened.** One test vector cannot catch a quote escaped differently, a different key order, or a mishandled largest integer. The platform now also publishes `docs/spec/test-vectors/canonical-json-v1.json`: 170 cases and 17 inputs that must be refused, generated from the real canonicalizer by `platform/scripts/gen_canonical_corpus.py`
   (deterministic, with its own tiny random generator so it does not change between Python versions). A platform test fails if the file ever differs from what the code produces.
3. **The conformance gate** (`packages/core/test/conformance.test.ts`, `packages/sdk/test/pipeline-conformance.test.ts`) reproduces the vector's canonical text, bytes and signature, then runs the whole SDK loop and checks the request body equals the vector's packet plus its signature, and replays the full corpus. It is part of `npm test`, so it is part of the `sdk-web` CI check.
   A missing vector file **fails** the test, never skips it. The workflow also runs when `docs/spec/test-vectors/**` changes, so a change to the contract cannot slip past the SDK.
4. **The SDK's types now follow the spec** (`ScoreResult` has `confidenceMilli`, `reasonCodes`, `signalMilli`, `modelVersion`), and `buildPacket` enforces the platform's rules locally, so a packet the server would refuse is refused on the device with a clear reason.
5. **The ECDSA P-256 fallback is switched off for now.** ADR 0020 left open whether the device record has an `alg` field. It does not: device registration takes only a 43-character Ed25519 public key (`DeviceIn`), and BUILD_SPEC_0 section 11 already lists the ECDSA fallback as needing an `alg` field on devices. An ECDSA key would be created and then refused, so the SDK's list of usable algorithms is `["Ed25519"]`, in one place (`SUPPORTED_ALGS`).
   The ECDSA code stays, tested, behind that list. A browser that cannot do Ed25519 now gets a clear "capability missing" error instead of a device the platform would reject.
6. **The observer role (D-02) exists in the SDK but cannot be sent.** The wire format has no role field and the server forbids unknown fields. The codec refuses observer packets in both directions with a pointer to this ADR.

## Platform work this creates (none of it done here; each needs your decision)

- **ECDSA fallback:** an `alg` field on devices (migration, `DeviceIn`, the device record), acceptance of an 87-character P-256 public key, ECDSA verification of 64-byte raw (r||s) signatures, and a second test vector. Then add "ECDSA-P256" to `SUPPORTED_ALGS` in the SDK.
- **Observer packets:** a Spec 0 amendment and a schema change. Proposal: optional `role` and `subject_participant_reference` fields, left out for ordinary packets so existing packets stay byte-for-byte identical. Decide first what `participant_reference` means in an observer packet (the observer or the person observed); D-02 asks for this decision before the SDK hardens.

## Consequences

- The SDK and the platform cannot drift apart on the signed bytes without a failing build on one side or the other.
- Anyone changing the canonical profile must regenerate the vectors, which triggers the SDK's CI. That is the point.
- Easier: P0-23 (registering the device key) and P0-25 (transport) now build on the real packet.

## Known gaps

- **Whole numbers:** JavaScript cannot tell `1` from `1.0`. Python refuses `1.0`; TypeScript reads it as `1`. The SDK builds its packets from whole numbers only and the builder checks them, so this cannot occur inside the SDK.
- **Server rules are copied by hand** into `buildPacket` (patterns and limits from `schemas.py`). Nothing yet tests the two against each other. A check that reads the server's schema is a candidate for a later step.
- **Browsers:** the vector, corpus and full loop were run in Node and in headless Chromium 153, plus a 20,000-input comparison against the real Python canonicalizer. They were not run in Firefox, Edge or Safari; the canonicalizer is plain JavaScript and Ed25519 signing was verified against the official RFC 8032 vectors in Chrome, Edge and Firefox (P0-20).
- **The webhook vector** (`webhook-signature-v1.json`) is for partner receivers, not for the SDK. A partner-side helper would use it, but it is not in this step.
- The real **model** (P0-37) and **device registration** (P0-23) are still to come; the loop's score still comes from a placeholder.

## Related

P0-22; D-01, D-02; ADR 0020, ADR 0021; BUILD_SPEC_0 sections 4 and 11; `docs/spec/test-vectors/`; guide Part 3.
