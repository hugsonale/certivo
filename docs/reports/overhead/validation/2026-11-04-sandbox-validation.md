# SDK overhead report: sandbox-validation (unclassified)

Generated 2026-11-04T22:04:47.954Z by the overhead harness (guide step P0-27, requirement NFR-C.2) at commit `unknown`.

## Read this first

- **The model is a stand-in.** There is no real model yet (P0-37). The "model" time below is a worker that does no real work, so these numbers are the cost of everything AROUND a model: capture, moving the picture to the worker, packet building and signing, and sending. **The real model's cost is not in this report.**
- **No pass budget is applied.** The budget is agreed with the first partner (P0-71). This report states measurements only, so no row says pass or fail.
- **Overhead means the difference.** Every run is done twice on the same machine: a loopback video call alone, and the same call with the SDK running on the same video. The SDK's cost is the second minus the first.
- **Capture time is mostly waiting.** The capture stage includes waiting for the camera's next frame (up to one frame time, about 33 ms at 30 frames a second), so it is a delay, not CPU work. The CPU rows are the cost.
- **Memory.** When the browser can measure the whole page and its worker, that is used. Otherwise only the main thread's JavaScript heap is measured (shown in brackets in the table), which leaves out the worker and the browser's own buffers, so it understates the SDK's memory.
- **Percentages of one core.** 100 means one whole core busy; 250 means two and a half. On a machine with several cores the same work looks smaller as a share of the whole machine.
- **Slowed-down tiers are approximations.** A tier above 1x slows only the page's main thread. The worker (where the model will run) is NOT slowed, so worker timings under a slowed tier do not represent a slower device. Real devices are needed for that.
- **Bandwidth here has no TLS.** The test server is plain HTTP on this machine, so encryption adds a little more on a real network.

## Machine

| | |
| :-- | :-- |
| Machine | sandbox-validation (vm) |
| Device tier | unclassified |
| Operating system | Linux 6.18.44-fc-v236 (x64) |
| Processor | Intel(R) Xeon(R) Processor @ 2.10GHz, 1 logical cores |
| Memory | 3.9 GB |
| Browser | 153.0.8010.0 (headless) |
| Page sees | 1 cores, cross-origin isolated: yes |

## How it was run

2 repetition(s) of each of the two setups, alternating. Each run: 4 s warm-up (not measured), then 16 s measured, one interval every 1000 ms, the fake call video is 160x120 at 8 frames a second, pictures for the SDK are scaled to 224 px on the long side, in a fresh browser each time. Slowdown settings tried: 1x.

## Results at 1x (no slowdown)

2 paired repetition(s); 32 intervals measured with the SDK. Typical value, with the lowest and highest repetition in brackets.

| Measure | Call alone | Call with the SDK | **SDK overhead** | Budget |
| :-- | --: | --: | --: | :-- |
| CPU, percent of one core (all browser processes) | 7.9 (7.8 to 7.9) | 8.5 (8.2 to 8.8) | **0.62 (0.37 to 0.87)** | not set |
| CPU, milliseconds per interval | | | **6.2 (3.7 to 8.7)** | not set |
| Memory at the end, MB (main-thread JavaScript heap only) | 1.3 (1.3 to 1.3) | 1.4 (1.4 to 1.4) | **0.2 (0.2 to 0.2)** | not set |
| Memory growth during the window, MB (SDK run) | | 0.08 (0.08 to 0.08) | | not set |
| Network sent by the SDK, kbit/s | | 9.53 (9.52 to 9.53) | **9.53 (9.52 to 9.53)** | not set |
| Network received by the SDK, kbit/s | | 3.03 (3.03 to 3.03) | **3.03 (3.03 to 3.03)** | not set |
| Network sent per interval, bytes | | 1192 (1192 to 1192) | **1192 (1192 to 1192)** | not set |

The loopback call itself sent about 32 (32 to 32) kbit/s of video, for scale.

### Time per interval (milliseconds, every interval of every repetition)

| Stage | Median | 95th percentile | Longest | Intervals |
| :-- | --: | --: | --: | --: |
| Whole interval | 120.2 | 128.0 | 133.7 | 32 |
| Capture (wait for a new camera frame, then copy it) | 111.7 | 118.9 | 126.6 | 32 |
| Model, round trip to the worker (STAND-IN) | 0.7 | 0.9 | 1.5 | 32 |
| Model, inside the worker only (STAND-IN) | 0.00 | 0.01 | 0.01 | 32 |
| Sign the packet | 0.13 | 0.16 | 0.18 | 32 |
| Send and get the reply | 6.3 | 8.9 | 12.5 | 32 |

Main-thread tasks over 50 ms: **0** with the SDK (longest 0 ms) against 0 without it. Outcomes of the intervals: sent 32.

## Harness self-check

A worker was told to burn **50 ms** of CPU per interval. The harness measured **50.5 ms** extra per interval (allowed difference 25.0 ms): **the CPU numbers can be trusted**.

## What this report does not say

- Nothing about the real model's speed, memory or battery use.
- Nothing about phones or other real devices unless they are listed as reference machines and were run with this harness.
- Nothing about whether the cost is acceptable: that needs the budget agreed with a partner.
