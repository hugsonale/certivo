# 0020. Browser signing algorithm and how the Web SDK reads frames (P0-20, D-01)

**Date:** 27 October 2026
**Status:** Proposed. Safari is untested; see "Still open".

## Context

The Web SDK must (a) sign every score packet with a per-device key that the page's own code cannot export (Part 10.2 of the guide: per-device
keys, never one shared key), and (b) read video frames of the local camera and of the received call, in memory, off the main thread, without ever
storing or sending them (Part 3: never retain raw captures). Decision D-01 asked: Ed25519 or ECDSA P-256 in the browser. Step P0-20 measured what
real browsers do. Evidence: `docs/spec/browser-results/` (Chrome 155, Edge 156, Firefox 153 and 158, Windows) and `docs/spec/browser-support-matrix.md`.

## Options considered

**Signing.**
1. Ed25519 only. Matches the platform (Ed25519 device keys, the cross-language test vector). Passed everything in all three browsers tested. Risk: older browsers lack it (documented from Chrome 137, Firefox 129 or 130, Safari 17; none of these versions verified).
2. ECDSA P-256 only. Widest support. But it gives up the Ed25519 the platform already uses, and the signature is a different shape (64-byte raw r||s) that the server must accept.
3. **Ed25519 preferred, ECDSA P-256 as fallback, chosen at run time by a capability probe, with an `alg` field recording which.** Both passed every test in all three browsers.
4. A JavaScript or WebAssembly Ed25519 library. Rejected: the private key would then live in script memory where any code on the page can read it. That breaks the "non-extractable" rule. It could be reconsidered only for a browser that has no WebCrypto signing at all, and would then be tier 3 and labelled as such.

**Reading frames.**
1. Raw frames with MediaStreamTrackProcessor. Fast and direct, but absent in Firefox 153 and 158, on the page and inside workers. In Chrome and Edge it works on the page; whether it exists inside workers there is still to be confirmed on a real machine (my headless Chromium run found it absent).
2. **Video element, canvas and requestVideoFrameCallback.** The one path that passed in all three browsers.
3. Send the whole video track to a worker. Rejected: Chrome and Edge cannot transfer a track.
4. Read encoded frames and decode them with WebCodecs. Possible (RTCRtpScriptTransform works in all three, and all four codecs decode), but heavier and not needed for scoring.

## Decision (proposed)

1. **Signing:** option 3. At start the SDK tries to create an Ed25519 key. If that works it uses it. If not it uses ECDSA P-256. The key is always created non-extractable and stored in the browser's IndexedDB. The packet and the device record carry `alg`. A missing key (the browser cleared it) is treated as normal: the SDK registers a new device key.
2. **Frames:** option 2 is the baseline for local and received video. The raw-frame API may be used as an optimisation where present, but nothing may depend on it. Frames are read on the page, sent to a worker as an ImageBitmap or VideoFrame (works in all three), read there, and closed straight away.
3. **Encoded frames, if ever needed:** only the standard RTCRtpScriptTransform. The older createEncodedStreams is not used.
4. **Receiver-side scoring (D-02)** is technically possible in all three tested browsers by reading the received video as pixels. This does not decide D-02; it removes "the browser cannot do it" as a reason against.
5. **Minimum versions:** published only when verified by a test. At the moment that is Chrome 155, Edge 156, Firefox 153. The SDK's own start-up capability probe covers older browsers.

## Consequences

- Platform work this creates (not done here): an `alg` field on the device record and in the packet and attestation formats; server-side verification of ECDSA P-256 signatures in raw r||s form; a second cross-language test vector for ECDSA; a migration; updates to docs/spec. I could not see `crypto.py` or the schemas, so whether an `alg` field already exists needs checking when this is built (P0-21 to P0-23).
- SDK work: a capability probe, key re-registration, and a frame pipeline built on the video-element path.
- Easier: one code path for frames works in three browsers. Harder: the video-element path costs more CPU than raw frames; that cost is measured in P0-27.
- The Trusted Device Layer (P1-03) will need to know which tier an ECDSA fallback device is. Both algorithms are software keys in the browser, so both are tier 3 for now.

## Still open

- **Safari is not tested.** It needs a Mac or iPhone. It is the browser most likely to differ.
- **Chrome and Edge inside workers.** Measured with page v1, which could not look inside a worker. Re-run on page v2. This does not change the decision: frames are read on the page and sent on as images.
- **Older versions are unverified.**
- **Real camera speed** is P0-27, not this step.
- **The eviction rule** (stored data deleted after inactivity) is a design rule, not a measurement.

## Related

P0-20; D-01 (settled by this ADR once accepted); D-02; P0-21 to P0-25; P0-27; `docs/spec/browser-support-matrix.md`.
