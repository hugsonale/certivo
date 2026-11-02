# 0024. Capture pipeline and the no-media-leaves-the-page test (P0-24)

**Date:** 2 November 2026
**Status:** Proposed

## Context

Step P0-24 asks for frames that are read in memory at the configured interval, passed to the model, discarded at once, and never stored or sent (TRD 2.2),
with two proofs: an automated network-interception test showing that no media leaves the page, and a memory check showing that no frame is retained.
P0-21 already built the frame path (capture, then a worker, then a score) and a static scan of the source. The static scan stops a careless change; it cannot show
what a real browser does. ADR 0020 settled that frames are read through a hidden video element and a canvas, because the raw-frame API is missing in Firefox.

## Options considered

**How to prove "no media leaves the page".** (a) Trust the static scan. (b) Add a real-browser test that runs the real SDK code and records everything that leaves the page. (c) (b), plus a test of the detector itself.
Chosen: (c). A detector that has never been seen to fail proves nothing.

**What counts as a leak.** The detector flags a request if it is not small JSON, is larger than a packet should be (4,096 bytes), carries the first bytes of a picture or video file,
carries a `data:` or `blob:` address, carries a long string or a long list of numbers, or contains the actual pixel bytes the model saw (raw, hex, base64, base64url or as a number list).
The pixel bytes are taken from inside the worker, so the test searches for what really was on screen rather than for a guess.

**Which browser driver.** Playwright over Puppeteer or a Vitest browser mode: it drives real Chromium, Firefox and WebKit with one API, and can intercept every request including those from workers.

**How to count frames that are still open.** Every `createImageBitmap` result is recorded; a closed or transferred picture reports a width of 0, so "still open" is a count of pictures with a width above 0.
This is exact. The JavaScript heap is also measured, but only as a coarse backstop, because a picture's pixels do not live there.

## Decision (proposed)

1. **Where frames are read.** The guide says frames are read "on a worker". A video element needs the page's DOM, so the frame is taken on the page and moved (not copied) to the inference worker, which closes it. Nothing about the frame stays on the page after the move.
2. **One turn at a time.** `IntervalRunner` (packages/sdk/src/runner.ts) runs `pipeline.runInterval()` at a fixed interval (100 ms to 60 s). Turns never overlap, a slow turn delays the next one instead of piling frames up,
   and once `stop()` resolves no further frame is taken.
3. **Back-pressure at the worker.** `WorkerScorer` counts pictures that are still at the worker, including ones it stopped waiting for. At 2 (the default) it refuses the next with the error code `busy` and does not send the picture;
   the pipeline closes it. Before this, a slow worker could be handed a new picture every interval, so frames would pile up in the worker.
4. **No copy left behind in the capture canvas.** After each frame is taken the canvas is cleared, and `stop()` shrinks it to 0 by 0.
5. **The browser test** (`sdk-web/e2e/no-media-egress.spec.ts`, run with `npm run test:browser`) runs 180 intervals of the real capture, scorer, pipeline, signing and session client in Chromium, against a pretend platform on the local machine.
   The camera is a canvas of random noise, so every frame is new. Any address other than the pretend platform is refused and recorded. Every request body is checked by the detector.
   The page and the worker are also watched from the inside (`e2e/harness/instrument.ts`): network calls, picture encoding, pixel reads, storage writes and every message between page and worker.
6. **The detector is tested on its own** (`test/leak-detector.test.ts`, part of `npm test`) against each kind of leak above and against a normal packet, and the browser test ends by sending a picture out on purpose and checking it is caught.
7. **Dependencies.** `@playwright/test` 1.64.1, an exact version, released 14 October 2026 (more than 14 days before it was added).

## Consequences

- The claim "raw video never leaves the device" is now evidenced for the SDK's frame path, in Chromium, with a stand-in model. It is **not** yet evidenced for the real model (P0-37), for Firefox or Safari, or for audio (the SDK reads no audio, but there is no audio test).
  The claims register entry should say exactly that and no more.
- The stand-in model (`e2e/harness/test-worker.ts`) really reads the pixels, but it is not the real model. The test must be re-run when the real model arrives; if the model needs the network to load, the detector's allow-list of addresses has to be extended on purpose.
- The watcher in the page reports on the same page it watches, so it could be fooled by code written to fool it. The independent evidence is the server's own record of what arrived, and the browser's own list of requests.
  A picture compressed and then disguised as small JSON would pass the pixel-copy rule; the size, shape and type rules and the static scan are what stand in the way of that.
- `WorkerScorer` has a new error code, `busy`, and a third constructor argument. A caller that passes only two arguments keeps working.
- CI gets a new job (`browser-test`) that downloads Chromium. It is slower than the other jobs (about a minute).

## Not done here

- The offline buffer, retries and pause or resume signalling (P0-25).
- The overhead harness (P0-27) and the real model (P0-37).
- Firefox and Safari in the browser test. Firefox is next, once the model exists.

## Related

P0-21 (ADR 0021), P0-22 (ADR 0022), P0-23 (ADR 0023), ADR 0020, TRD 2.2, guide Part 3 and Part 11.2 (claims register).
