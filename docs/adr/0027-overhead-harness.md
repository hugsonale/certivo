# 0027. The overhead harness (P0-27)

**Date:** 4 November 2026
**Status:** Proposed

## Context

NFR-C.2 asks for the SDK's cost to a video call (CPU, memory, network, time per interval) to be measured on defined machines and reported per device tier. The pass budget is agreed with the first partner later (P0-71), and there is no real model yet (P0-37).
So the harness has to be repeatable, honest about what it leaves out, and ready for the model to be dropped in.

## Decision (proposed)

1. **Measure the difference, not the total.** The same fake video call (a canvas stream sent through a loopback WebRTC call in the page, encoded and decoded as in a real call) runs twice: alone, and with the SDK running on the same video. Repetitions alternate which goes first, each in a fresh browser, and the overhead is the paired difference, with the lowest and highest repetition shown.
2. **CPU from the browser itself.** The cumulative CPU time of every browser process (including the worker thread) is read through Chromium's debugging channel before and after a measured window, and reported as percent of one core and as milliseconds per interval. If that is unavailable, only the main thread's task time is used and the report says so.
3. **Memory:** the page's whole-page reading (page and worker) when the browser offers it; otherwise the main thread's JavaScript heap right after a garbage collection, labelled as understating the SDK's memory.
4. **Network:** exact bytes on the wire including headers, for the requests between the page and the platform, per interval and in kbit/s, next to the fake call's own video bitrate for scale. The test server is plain HTTP, so TLS overhead is not included (the report says so).
5. **Time per interval:** the whole interval and each stage (capture, model round trip, model inside the worker, signing, sending), as median, 95th percentile and longest over every interval, plus main-thread tasks over 50 ms. The stages are timed by wrapping the objects the pipeline already takes, so the SDK is not changed.
6. **The model is a slot.** `overhead/harness/model-worker.ts` is a stand-in (no real work). It can burn a known CPU time per picture for the self-check. When the real model exists it replaces this file.
7. **The harness checks itself.** A worker told to burn a known amount of CPU per interval must show up as about that much (within the larger of half of it or 8 ms), or the run fails. It also detects a nearly-saturated machine (above 85 percent of all cores): then extra work cannot show up as CPU, and the report carries a warning at the top that the CPU overhead reads too low.
8. **No budget is applied.** Every budget cell reads "not set" (tested), and no row says pass or fail.
9. **Tiers.** A report is tied to a named machine and tier (`docs/spec/reference-machines.md`). The tier definitions are placeholders until NFR-C.2 is checked. A slowdown setting is offered as an approximation, and the report says it slows only the main thread, not the worker.
10. **Run by hand, not in CI.** It needs a quiet machine and takes about 7 minutes per slowdown setting. The arithmetic and the report builder are unit-tested and run in `npm test`.

## Verification

- 30 unit tests: the statistics (percentiles, paired differences, CPU deltas between process readings, unit conversions, the self-check tolerance) and the report builder (pairing, wording, the saturation warning, "not set" in every budget cell, odd input).
- Run here in a real Chromium: the full harness with two paired repetitions. The self-check burned 50 ms per interval and measured 50.5 ms. With the default fake call the one-core test machine was already full (98 percent), the self-check failed, and the saturation warning now covers that case.

## Not verified, and known limits

- **No reference-machine report exists yet.** The run made here was on a one-core cloud machine with a tiny fake call (160x120 at 8 frames a second). It is kept only as evidence that the harness works, in `docs/reports/overhead/validation/`, and its numbers must not be quoted.
- Not run in a headed Chrome with the whole-page memory reading, on Windows, or on any real phone.
- The real model's cost is not measured. Battery use is not measured.
- A slowed-down tier does not slow the worker, so it cannot stand in for a slower device for model timing.
- Capture time includes waiting for the camera's next frame, so it is a delay and not CPU.

## Related

P0-26 (the demo, whose pipeline wiring this reuses), P0-37 (the real model), P0-71 (the pilot budget), P1-07 and P1-08 (native SDKs and real devices), NFR-C.2.
