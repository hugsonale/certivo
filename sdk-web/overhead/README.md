# The overhead harness (step P0-27)

Measures what the Web SDK costs a video call: **CPU, memory, network and time per interval**, and writes a report you can keep.

It runs the **same fake video call twice**, without the SDK and then with it, several times each and alternating, in a fresh browser every time.
The SDK's cost is the difference. It also **checks itself**: a worker that burns a known amount of CPU must show up as that much CPU, or the report says the numbers cannot be trusted.

> **Read this before quoting any number.** The model is a **stand-in** (the real one arrives in P0-37), so these numbers are the cost of everything *around* a model. The real model's cost is not here.
> The pass budget is agreed with the first partner (P0-71), so **no row says pass or fail**.

## Run it (Git Bash, from the repo root)

One time, if you have not already:

```
cd ~/desktop/exclusive/certivo/sdk-web
npm install --save-dev --save-exact @playwright/test@1.64.1
npm pkg set "scripts.overhead=playwright test -c playwright.overhead.config.ts"
```

(If `@playwright/test` is already there from P0-24, only the second line is new.)

The first real report, with your own Chrome and a visible window:

```
cd ~/desktop/exclusive/certivo/sdk-web
OVERHEAD_MACHINE=RM-1 OVERHEAD_TIER=dev-desktop OVERHEAD_CHANNEL=chrome OVERHEAD_HEADED=1 npm run overhead
```

It takes about 7 minutes and prints each step. **During those minutes do not use the computer**, plug in the power, and close other programs, or the numbers will be noisy.
The report is saved to `docs/reports/overhead/DATE-RM-1.md`, with the raw data beside it as `.json`.

To also try a slowed-down machine (the page's main thread slowed to a quarter speed, an approximation), add `OVERHEAD_THROTTLES=1,4`. That doubles the time.

## Settings (all optional, set before `npm run overhead`)

| Setting | Default | Meaning |
| :-- | :-- | :-- |
| `OVERHEAD_MACHINE` | `RM-unnamed` | The machine's name in `docs/spec/reference-machines.md`. Used in the report and its file name. |
| `OVERHEAD_TIER` | `unclassified` | The device tier this machine stands for. |
| `OVERHEAD_CHANNEL` | the browser Playwright installed | `chrome` or `msedge` to measure the browser really installed on the machine. |
| `OVERHEAD_HEADED` | off | `1` runs with a visible window (closer to real use). |
| `OVERHEAD_REPS` | 3 | Repetitions of each setup. |
| `OVERHEAD_WINDOW_S` / `OVERHEAD_WARMUP_S` | 45 / 6 | Seconds measured, and seconds of warm-up that are not. |
| `OVERHEAD_INTERVAL_MS` | 3000 | The SDK's interval. |
| `OVERHEAD_CALL` | `640x480@30` | The fake call video. A smaller one (for example `320x240@15`) is a fairer test of a weak machine. |
| `OVERHEAD_THROTTLES` | `1` | Slowdown settings to try, for example `1,4`. |
| `OVERHEAD_CALIBRATE` / `OVERHEAD_BURN_MS` | on / 5% of the interval | The harness self-check. |
| `OVERHEAD_OUT` | `docs/reports/overhead` | Where the report goes. |

## Reading the report

- **SDK overhead** is the run with the SDK minus the run without it, with the lowest and highest repetition in brackets. A negative number means noise; the harness does not hide it.
- **CPU percentages are of one core.** 100 is one core fully busy.
- **Capture time is mostly waiting** for the camera's next frame. The CPU rows are the cost.
- **A warning at the top** means the machine was nearly full during the run, so extra work could not show up as CPU and the CPU overhead **reads too low**. Use a smaller `OVERHEAD_CALL` or a quieter machine and run again.
- **The self-check line** must say the CPU numbers can be trusted. If it does not, the run fails.

## What it does not do yet

- Real phones and low-end devices. The slowed-down setting is only an approximation (it slows the main thread, not the worker). Real devices join when the native SDKs exist (P1-07, P1-08); until then record them in `docs/spec/reference-machines.md` as "not yet measured".
- Battery use.
- Firefox and Safari. Chromium browsers only, because the measurement uses Chromium's debugging channel.
- The real model. Replace `harness/model-worker.ts` when P0-37 delivers one; the rest stays.
