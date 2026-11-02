# 0023. Browser key provisioning (P0-23)

**Date:** 30 October 2026
**Status:** Proposed

## Context

Step P0-23: a device-specific key pair created in the browser, the private key non-extractable, the public key registered through the partner's backend, tier 3 (software only) at first, and a test that the private key never appears in network traffic or logs.
What the SDK knows about the platform's side comes from `platform/app/schemas.py` (`DeviceIn` is exactly `{public_key}`, a 43-character Ed25519 key, extra fields refused; `DeviceOut` is `id`, `trust_tier`, `status`, `created_at_ms`) and the platform's tests (`POST /v1/devices` with a partner API key returns 201 and an `id`).
**`platform/app/routers/devices.py` has not been reviewed.** What it does with a duplicate key, which scope it needs, and which tier it records are unconfirmed (see "Still open").

## Decision (proposed)

1. **The SDK never calls the platform's device endpoint.** That endpoint needs the partner's secret API key, and the SDK ships to end users (D-05). The partner's page supplies a `register` function that talks to the partner's own backend. The SDK hands it exactly the platform's request body, `{ public_key }`, so the backend can forward it unchanged. The backend answers with the `id` the platform returned, and the SDK checks it looks like `dev_` plus 32 hex characters before trusting it.
2. **The key and its device ID are kept together** in the browser's IndexedDB. Each call to `provisionDevice` does the right thing:
   first visit: make the key, register, remember the ID. Later visits: load both, ask nobody. The browser cleared the data: a new key and a new registration. A registration failed: **the key is kept**, so the retry registers the same public key and not a new one. A key saved by the P0-21 build (no ID yet) is simply registered.
3. **One provisioning at a time.** Two calls in one page, or two tabs (where the browser has Web Locks), register once and not twice.
4. **The private key is created non-extractable in exactly one place** (`loadOrCreateKey`), is never exported, and its only use is signing. Failure messages say what kind of failure it was and never repeat text from the partner's code, which could hold anything.
5. **Tier 3 ("software") means:** the key lives in the browser and the page's scripts cannot read it out, so it cannot be copied to another machine. It does **not** mean: that nothing on this page can ask it to sign (any script running on the same page can), that the SDK is unmodified, or that a real person or a real camera is behind it.
   Nothing here is attested by hardware. A score from this device is only as honest as the device (guide Part 10.2). The SDK states the protection level (`"software"`); the platform decides the tier it records.
6. **How "the private key never appears in traffic or logs" is tested** (`packages/core/test/key-leak.test.ts`, `test/architecture.test.ts`):
   - A key that cannot be read cannot be searched for, so the test uses a WebCrypto wrapper that makes an extractable copy of each key, only so the test learns the secret. It also records what the SDK asked for, and checks the SDK asked for a non-extractable key, usable only to sign and verify.
   - The whole SDK flow then runs (provisioning, building, signing and sending packets, batches, pause, resume, and the failure paths) while every channel is recorded: the SDK's client, the browser's own `fetch`, `XMLHttpRequest` and `WebSocket`, every console method, error text, and the registration request. Every recording is searched for the secret in ten written forms (hex, base64 in four variants, a JSON array, a comma list, and others), for both the 32-byte secret and the full PKCS#8 key.
   - A detector self-test proves each form is found, so a clean result is meaningful.
   - Static guards fail the build if any SDK code writes to the console, exports anything but a public key in raw form, creates a key that is not non-extractable, names the private-key export formats, or touches IndexedDB outside the key store.
   - Checked in real Chromium 153: first visit, reload, and a simulated deletion of the browser's data. Every request the page made was captured; the only long values were public keys and one signature, no forbidden words appeared, nothing went anywhere but the partner backend and the platform, and the page wrote nothing to the console.

## Privacy: when a device key may be created

A key that persists in the browser is a persistent identifier for that device on the partner's site (it is not shared between sites). The guide forbids covert tracking and requires consent before the camera starts (P0-51). So **`provisionDevice` must be called only after the person has consented.** Nothing enforces this yet, because the consent flow does not exist yet (P0-51). Until it does, this is a rule for whoever integrates the SDK, and the device key must go in the data inventory (P0-52).
The Trusted Device Layer will need its own, separate consent (P1-05).

## Consequences

- A device the browser forgets is registered again, so the platform may accumulate registrations for one person's browser (private browsing, or Safari after about 7 days without a visit). `persisted: false` tells the page when this will happen. Server-side limits, and re-linking a returning user, belong to the Trusted Device Layer (P1-02).
- The partner needs a small backend endpoint that forwards `{ public_key }` to `POST /v1/devices` with their API key and returns the `id`. The demo app (P0-26) will include one.

## Still open (not decided here)

- **`devices.py` is unreviewed.** To check: what happens when the same public key is registered twice (for example when the first reply was lost and the SDK retries), which API-key scope the call needs, which tier is recorded for these devices, and any rate limit.
- **Limits of the leak test:** it finds the key written in the common forms; it cannot find a key scrambled on purpose; it covers the code paths exercised. The real-browser network-interception test for the whole SDK is P0-24.
- **Browsers:** the provisioning flow was run in Node and in headless Chromium 153. Storing a non-extractable key and reloading it was verified in Chrome, Edge and Firefox in P0-20. Safari is untested.

## Related

P0-23; D-01, D-05; ADR 0020, ADR 0022; guide Part 3 and Part 10.2; P0-24, P0-26, P0-51, P0-52, P1-02, P1-05.
