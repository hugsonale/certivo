# 0021. Web SDK architecture (P0-21)

**Date:** 28 October 2026
**Status:** Proposed

## Context

Step P0-21 asks for a TypeScript monorepo in `sdk-web/` with core (session client, packet builder, signing, buffer), capture (frame access),
inference (the model, in a worker) and ui (reference indicator), a reserved observer role in the packet (D-02), and a bundle-size budget checked in CI.
The SDK runs on a partner's page, so it must protect people even when the code around it changes: frames never leave the device or outlast one
inference interval (guide Part 3), and a decision is never sent without a score and an explanation. ADR 0020 already settled signing (Ed25519 with an
ECDSA P-256 fallback) and frame reading (video element, canvas, requestVideoFrameCallback; frames sent to a worker as images).

## Options considered

**Layout.** (a) One package. (b) Four packages as the guide lists them. (c) Those four, plus a type-only `types` package, plus a `sdk` package that wires them.
Chosen: (c). The extra packages cost nothing at run time (`types` is erased) and make the key rule enforceable: `capture` and `inference` (which handle pictures) and
`core` (which talks to the network) cannot import each other, and only `sdk` joins them.

**Tooling.** npm workspaces (no extra tool) over pnpm, Nx or Turborepo: nothing here needs them. esbuild for bundling: small, fast, one dependency. TypeScript for type checking only
(the bundler strips types). Biome for lint and formatting (one tool instead of ESLint plus Prettier and their plugins). Vitest for tests. No DOM-simulation library: the only
DOM-dependent test uses a six-method stand-in, because the available library had a high-severity advisory whose fix was too new to use under our own 14-day rule.

**Where frames are checked.** (a) Trust reviewers. (b) A static scan of the source for forbidden words. (c) Both, and add the runtime test in P0-24. Chosen: (c).

## Decision (proposed)

1. **Packages:** `types`, `core`, `capture`, `inference`, `ui`, `sdk`. The allowed imports are written once, in `sdk-web/test/architecture.test.ts`, and the test fails on any other import.
2. **A picture only travels capture to inference.** `Frame` holds an `ImageBitmap`; the scorer receives it moved (not copied) into the worker, which closes it. What comes out is a `ScoreResult`
   (`confidence`, `reasonCodes`, `modelVersion`), nothing else. `core`, `ui`, `types` and `sdk` may not mention a picture type at all (the test checks).
3. **Where frames can never go.** The architecture test fails if `capture`, `inference`, `ui` or `types` use the network, storage, or anything that turns a picture into bytes
   (`fetch`, `WebSocket`, `sendBeacon`, `indexedDB`, `toBlob`, `toDataURL`, `MediaRecorder`, and similar), and if anything outside `core/src/session-client.ts` uses `fetch`.
   This is a static check. The runtime proof that no media leaves the page is P0-24.
4. **The loop** (`VerificationPipeline.runInterval`): grab a frame, score it, close the frame (always, in `finally`), then build, sign and send the packet. No score means no packet and no used sequence number. A network failure keeps
   the signed packet in the buffer. Any other failure is raised, never swallowed.
5. **The observer role (D-02) is reserved now.** A packet has `role: "self" | "observer"`, and an observer packet must also name `subjectParticipantRef` (never the sender). `buildPacket` enforces this; the pipeline passes it through; Phase 0 always uses "self".
   **Proposal for Spec 0:** when the role is "self" the field is left out of the signed bytes, so a Phase 0 packet is byte-for-byte what it is today and only observer packets carry the new fields. This needs an amendment to Spec 0 and a matching change in the platform's packet schema;
   neither is done here.
6. **Signing follows ADR 0020:** try Ed25519, else ECDSA P-256, by trying for real, with a non-extractable key kept in IndexedDB. A missing key is normal and means a new registration (`isNewKey`).
7. **Bundle budget** (`size-budget.json`, checked by `npm run size` in CI): 30,000 bytes (gzip) for `certivo-sdk.js`, 10,000 for the worker, 36,000 total. The first build is 4.7 KB. **These numbers are placeholders** chosen before any real code exists: a ceiling we set ourselves,
   not a partner requirement. Set the real numbers with the first design partner (P0-27, P1-01). The model and the ONNX runtime will be loaded separately and later, with their own budgets (P0-37).
8. **Dependencies** are pinned exactly, each at least 14 days old (P0-61): TypeScript 7.0.2, esbuild 0.28.2, Biome 2.5.15, vitest 5.0.4, @types/node 22.20.5. `npm audit` reports 0 vulnerabilities. **Node 24 (npm 11) is required**: npm 10 crashes while installing any vitest that has the security fixes
   (an npm 10 bug, found while building this). CI uses Node 24, and `.npmrc` makes an old npm stop with a clear message.

## Consequences

- Easier: the privacy rules fail a build instead of relying on review; each package can be understood alone; a new model or transport replaces one package.
- Harder: a change that really needs a package to reach across a boundary needs an ADR first (guide: "ADR before any cross-boundary shortcut").
- The people who run the SDK need Node 24 or newer to build it. Partners using the built file do not.
- Spec 0 and the platform schema must change before the observer role can be sent (P1-10).

## Not done here (each has its own step)

Packet bytes and the shared test vector (P0-22). Registering the device key with the partner backend (P0-23). The automated browser test that no media leaves the page (P0-24). Real retries, persistence and pause and resume (P0-25).
The demo call app (P0-26). Overhead measurement (P0-27). The model and the ONNX runtime (P0-37). The approved indicator wording and the design tokens (P0-38, P0-50). Safari (P0-20 is still open for it).

## Related

P0-21; D-01, D-02; ADR 0020; guide Part 3 (gates), P0-24, P0-61; `docs/spec/sdk-web-architecture.md`; `sdk-web/README.md`.

## Update (P0-22, 29 October 2026)

Reading BUILD_SPEC_0 corrected the provisional packet shape used here: confidence is a whole number 0 to 1000, the explanation also carries named signals, and there is no `role` or `alg` field on the wire. Point 5 above (the observer role) is therefore
held back, not sendable, until the platform's schema has a role field. See docs/adr/0022 for the corrections and the platform work they imply.
