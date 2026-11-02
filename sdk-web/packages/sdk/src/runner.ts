import type { IntervalOutcome } from "./pipeline";

export interface IntervalRunnerOptions {
  /** Time from the start of one turn to the start of the next. At least 100 ms, at most 60 000 ms. */
  intervalMs: number;
  /** One turn of the verification loop (normally `pipeline.runInterval()`). */
  run(): Promise<IntervalOutcome>;
  onOutcome?(outcome: IntervalOutcome): void;
  /** Called when a turn throws. The loop carries on with the next turn. */
  onError?(error: unknown): void;
  /** Supplied by tests. Must reject or resolve early when the signal is aborted. */
  sleep?(ms: number, signal: AbortSignal): Promise<void>;
  now?(): number;
}

const defaultSleep = (ms: number, signal: AbortSignal): Promise<void> =>
  new Promise((resolve) => {
    if (signal.aborted) return resolve();
    const timer = setTimeout(resolve, ms);
    signal.addEventListener(
      "abort",
      () => {
        clearTimeout(timer);
        resolve();
      },
      { once: true },
    );
  });

/**
 * Runs the verification loop at a fixed interval, and keeps two promises that protect people:
 *  - turns never overlap, so at most one frame is being taken at a time (a slow turn delays the next one; it never
 *    piles frames up);
 *  - after stop() resolves, no further frame is taken.
 */
export class IntervalRunner {
  private controller: AbortController | undefined;
  private loop: Promise<void> | undefined;

  constructor(private readonly options: IntervalRunnerOptions) {
    const { intervalMs } = options;
    if (!Number.isInteger(intervalMs) || intervalMs < 100 || intervalMs > 60_000) {
      throw new RangeError("intervalMs must be a whole number from 100 to 60000");
    }
  }

  get running(): boolean {
    return this.controller !== undefined;
  }

  start(): void {
    if (this.controller) return;
    const controller = new AbortController();
    this.controller = controller;
    this.loop = this.runLoop(controller.signal);
  }

  /** Stops the loop and waits for a turn that is already under way to finish (and discard its frame). */
  async stop(): Promise<void> {
    const { controller, loop } = this;
    this.controller = undefined;
    this.loop = undefined;
    controller?.abort();
    await loop;
  }

  private async runLoop(signal: AbortSignal): Promise<void> {
    const { intervalMs, run, onOutcome, onError } = this.options;
    const sleep = this.options.sleep ?? defaultSleep;
    const now = this.options.now ?? (() => Date.now());
    while (!signal.aborted) {
      const startedAt = now();
      try {
        const outcome = await run();
        onOutcome?.(outcome);
      } catch (error) {
        onError?.(error);
      }
      if (signal.aborted) break;
      await sleep(Math.max(0, intervalMs - (now() - startedAt)), signal);
    }
  }
}
