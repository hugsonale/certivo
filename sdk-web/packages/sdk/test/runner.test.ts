import { describe, expect, it } from "vitest";
import type { IntervalOutcome } from "../src/pipeline";
import { IntervalRunner } from "../src/runner";

const sent = (seq: number): IntervalOutcome => ({ status: "sent", seq });

/** A sleep that waits until the test releases it, so the test decides when the next turn may start. */
function controlledSleep() {
  const waits: number[] = [];
  let release: (() => void) | undefined;
  const sleep = (ms: number, signal: AbortSignal) =>
    new Promise<void>((resolve) => {
      waits.push(ms);
      release = resolve;
      signal.addEventListener("abort", () => resolve(), { once: true });
    });
  return { sleep, waits, next: () => release?.() };
}

const tick = () => new Promise<void>((resolve) => setTimeout(resolve, 0));

describe("IntervalRunner", () => {
  it("refuses a nonsense interval", () => {
    const run = async () => sent(0);
    for (const intervalMs of [0, 99, 60_001, 1000.5]) {
      expect(() => new IntervalRunner({ intervalMs, run })).toThrow(RangeError);
    }
    expect(() => new IntervalRunner({ intervalMs: 100, run })).not.toThrow();
  });

  it("runs a turn, waits the rest of the interval, then runs the next", async () => {
    const { sleep, waits, next } = controlledSleep();
    let clock = 0;
    let turns = 0;
    const runner = new IntervalRunner({
      intervalMs: 1000,
      sleep,
      now: () => clock,
      run: async () => {
        clock += 300; // this turn takes 300 ms
        return sent(turns++);
      },
    });
    runner.start();
    await tick();
    expect(turns).toBe(1);
    expect(waits).toEqual([700]); // 1000 minus the 300 the turn took
    next();
    await tick();
    expect(turns).toBe(2);
    await runner.stop();
  });

  it("never overlaps turns: a slow turn delays the next one", async () => {
    let active = 0;
    let maxActive = 0;
    let release: (() => void) | undefined;
    const runner = new IntervalRunner({
      intervalMs: 100,
      sleep: async () => {},
      run: async () => {
        active++;
        maxActive = Math.max(maxActive, active);
        await new Promise<void>((resolve) => {
          release = resolve;
        });
        active--;
        return sent(0);
      },
    });
    runner.start();
    await tick();
    await tick();
    expect(active).toBe(1); // still the first turn; no second one has started
    release?.();
    await tick();
    release?.();
    await runner.stop();
    expect(maxActive).toBe(1);
  });

  it("stop() waits for the turn under way, and no turn starts after it", async () => {
    let turns = 0;
    let finishTurn: (() => void) | undefined;
    const runner = new IntervalRunner({
      intervalMs: 100,
      sleep: async () => {},
      run: async () => {
        turns++;
        await new Promise<void>((resolve) => {
          finishTurn = resolve;
        });
        return sent(0);
      },
    });
    runner.start();
    await tick();
    let stopped = false;
    const stopping = runner.stop().then(() => {
      stopped = true;
    });
    await tick();
    expect(stopped).toBe(false); // the turn is not finished yet
    finishTurn?.();
    await stopping;
    expect(stopped).toBe(true);
    await tick();
    expect(turns).toBe(1);
    expect(runner.running).toBe(false);
  });

  it("keeps going after a turn throws, and reports the error", async () => {
    const errors: unknown[] = [];
    const outcomes: IntervalOutcome[] = [];
    let turns = 0;
    const runner = new IntervalRunner({
      intervalMs: 100,
      sleep: async () => {},
      run: async () => {
        turns++;
        if (turns === 1) throw new Error("boom");
        if (turns === 3) await runner.stop();
        return sent(turns);
      },
      onError: (e) => errors.push(e),
      onOutcome: (o) => outcomes.push(o),
    });
    runner.start();
    await tick();
    await tick();
    expect(errors).toHaveLength(1);
    expect(outcomes.length).toBeGreaterThanOrEqual(1);
    await runner.stop();
  });

  it("start() twice does not start two loops", async () => {
    let active = 0;
    let maxActive = 0;
    const runner = new IntervalRunner({
      intervalMs: 100,
      sleep: (_ms, signal) => new Promise<void>((resolve) => signal.addEventListener("abort", () => resolve())),
      run: async () => {
        active++;
        maxActive = Math.max(maxActive, active);
        await tick();
        active--;
        return sent(0);
      },
    });
    runner.start();
    runner.start();
    await tick();
    await tick();
    await runner.stop();
    expect(maxActive).toBe(1);
  });
});
