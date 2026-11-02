# Browser support matrix (P0-20)

**Status: PARTIAL. Chrome, Edge and Firefox tested on a real Windows machine (27 October 2026). Safari NOT tested (waiting for access to a Mac).**
Step P0-20. Settles decision D-01 (signing algorithm for browsers), see ADR 0020. Feeds P0-21 to P0-25 and decision D-02.
Evidence: `docs/spec/browser-results/*.json`. Test page: `sdk-web/spikes/p0-20-browser-capability/`.

## 1. Tested on real machines

All ran on the same Windows computer (8 cores, 16 GB). Chrome and Edge used test page v1. Firefox was run twice: 153 with page v1, then 158 (the browser updated itself) with page v2, which can also look inside workers. "Pass" means every test behind that row passed.

| Question | Chrome 155 | Edge 156 | Firefox 153 and 158 | Safari |
| :---- | :---- | :---- | :---- | :---- |
| Ed25519: generate, private key cannot be exported, sign and verify, official RFC 8032 vectors, deterministic | Pass | Pass | Pass | Not tested |
| Ed25519 key stays non-extractable after being stored and reloaded | Pass | Pass | Pass | Not tested |
| ECDSA P-256 fallback, same checks (64-byte raw signature) | Pass | Pass | Pass | Not tested |
| Frames from a local video as pixels (video element, canvas, requestVideoFrameCallback) | Pass | Pass | Pass | Not tested |
| Raw frames on the page (MediaStreamTrackProcessor) | Pass | Pass | **Not present** (153 and 158) | Not tested |
| Raw frames inside a worker (MediaStreamTrackProcessor) | Not measured (page v1 could not tell; to re-run with v2) | Not measured (same) | **No** (158, page v2: absent on the page and inside workers) | Not tested |
| A frame sent to a worker as an image, or as a VideoFrame, and read there | Pass | Pass | Pass | Not tested |
| A whole video track handed to a worker | No (cannot be transferred) | No (same) | No (nothing to read it with) | Not tested |
| Received video of a call read as pixels (receiver-side scoring, D-02) | Pass | Pass | Pass | Not tested |
| Encoded frames of a call, standard API (RTCRtpScriptTransform) | Pass | Pass | Pass | Not tested |
| Older Chrome-style encoded frames (createEncodedStreams) | Present | Present | **Not present** | Not tested |
| ImageCapture.grabFrame() | Pass | Pass | **Not present** | Not tested |
| WebCodecs decoding of VP8, VP9, H.264, AV1 | All four | All four | All four | Not tested |
| WebAssembly SIMD, WebGPU, WebGL2 | All three | All three | All three | Not tested |
| Multi-threaded WebAssembly (needs a cross-origin-isolated page) | Not available on this test page | Same | Same | Not tested |

Observations that are not verdicts: Firefox delivered about half as many frames as Chrome and Edge from the same synthetic video
(32 against 60 encoded frames in 3 seconds; 1.3 s against 0.6 s for 10 local frames). A canvas-made video is not a camera, so this is not a
finding about Firefox. Real speed is step P0-27.

## 2. What the results mean for the SDK (proposed, see ADR 0020)

1. **Signing:** Ed25519 works everywhere tested, including the official test vectors. ECDSA P-256 also works everywhere and is the fallback.
2. **Reading frames:** the one path that worked in all three browsers is video element, canvas and requestVideoFrameCallback. The raw-frame API is a
   Chromium-only shortcut for now. The SDK must not depend on it.
3. **Workers:** frames can be sent to a worker as an image or a VideoFrame in all three. The SDK reads frames on the page and sends them on. It
   cannot send the whole track to a worker (Chrome and Edge), so that design is out.
4. **Encoded frames:** only the standard RTCRtpScriptTransform works in all three. The older createEncodedStreams is not used.
5. **Receiver-side scoring (D-02):** technically possible in all three tested browsers, by reading the received video as pixels.

## 3. Claims from public sources: checked against the tests

Gathered 27 October 2026. Nothing here may be quoted to a partner.

| Claim | Source | Result of our tests |
| :---- | :---- | :---- |
| Ed25519 in WebCrypto from Chrome 137, Firefox 129 (one source says 130), Safari 17; Edge follows Chrome | IPFS blog, Igalia blog, web-platform-dx | Consistent with Chrome 155, Edge 156, Firefox 153 passing. The version numbers themselves are NOT verified: we only tested the newest versions |
| MediaStreamTrackProcessor in Firefox 141 on Windows | A vendor blog (June 2026), a weak source | **Contradicted.** Firefox 153 and 158 on Windows have no MediaStreamTrackProcessor, neither on the page nor inside a worker. The blog's claim is not usable |
| MediaStreamTrackProcessor in Safari 26 | Same blog | Not tested |
| RTCRtpScriptTransform in Firefox 117 | Firefox source code | Consistent (works in 153) |
| createEncodedStreams is Chrome-only; Firefox adds a shim | Vendor documentation, Firefox source | Consistent: absent in Firefox 153 |

## 4. Minimum browser versions

Rule: we publish a minimum version only if we tested it. We tested one version of each browser, the newest.

| Browser | Verified (tested and passing) | Documented but NOT verified |
| :---- | :---- | :---- |
| Chrome | 155 | Ed25519 from 137 |
| Edge | 156 | Probably 137 (Chromium) |
| Firefox | 153 and 158 | Ed25519 from 129 or 130 |
| Safari | none | Ed25519 from 17 |

Until older versions are tested (for example with a cloud browser service, or an older installer), the only honest statement is "tested on
the versions above". The SDK will also test for the capabilities it needs when it starts (ADR 0020), so an older browser that lacks one is
detected at run time and not by guessing from a version number.

## 5. Known limits of this spike

- **Safari is untested.** It needs a Mac or iPhone. Safari is also the likeliest to differ: it has its own rules for stored data and for frame access.
- **Eviction is not tested.** Some browsers, notably Safari, delete a site's stored data after about 7 days without a visit. The SDK must treat a missing key as normal and register a new one. This is a design rule, not a test result.
- **One version of each browser, on one machine.** Nothing here is evidence about older versions, other computers, or phones.
- **A loopback call in one page is not a real call.** It shows the browser lets us read frames. It says nothing about speed under real network conditions (P0-27).
- **A canvas-made video is not a camera.** The optional camera test was not run.
- **The page reads frames but runs no model.** How fast frames can be processed is P0-27.
- **Page v1 had a gap.** It could not tell whether a browser offers the raw-frame API only inside workers. Page v2 fixes this and was used for Firefox 158. Chrome and Edge were measured with v1 only; re-running them on v2 takes about a minute each and is still to do (my own headless Chromium 153 run on v2 found no such API inside workers, but that is not a real-machine result).

## 6. Dry run (does NOT count as evidence)

Before you ran it, the page was tried in an automated, headless Chromium 153 on Linux, and in six deliberately broken browsers (no Ed25519; exportable
private key; non-standard signatures; storage refusing keys; no frame APIs; and a browser offering the raw-frame API only inside workers). It gave the right verdict every time.
