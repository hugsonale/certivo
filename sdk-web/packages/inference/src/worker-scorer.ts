import type { ScoreResult } from "@certivo/sdk-types";
import { type Scorer, ScorerError, type WorkerRequest, type WorkerResponse } from "./protocol";

/** The small part of a Worker that WorkerScorer needs (so tests can supply a fake). */
export interface WorkerLike {
  postMessage(message: WorkerRequest, transfer: Transferable[]): void;
  addEventListener(type: "message", listener: (event: MessageEvent<WorkerResponse>) => void): void;
  addEventListener(type: "error", listener: (event: Event) => void): void;
  terminate(): void;
}

interface Pending {
  resolve(result: ScoreResult): void;
  reject(error: ScorerError): void;
  timer: ReturnType<typeof setTimeout>;
}

/**
 * Sends pictures to an inference worker and waits for the score.
 *
 * A picture that was sent but not answered yet is still in the worker's memory, even if we stopped waiting for it
 * (timeout). So a slow worker must not be handed more pictures: once `maxInFlight` are waiting at the worker,
 * score() refuses with "busy" and the picture is NOT sent (the caller closes it). This keeps the number of live
 * frames small and fixed, which is what guide P0-24 ("no frame retention") needs.
 */
export class WorkerScorer implements Scorer {
  private nextId = 1;
  private readonly pending = new Map<number, Pending>();
  /** Ids sent to the worker and not yet answered, including ones we gave up waiting for. */
  private readonly atWorker = new Set<number>();

  constructor(
    private readonly worker: WorkerLike,
    private readonly timeoutMs = 2000,
    private readonly maxInFlight = 2,
  ) {
    worker.addEventListener("message", (event) => this.onMessage(event.data));
    worker.addEventListener("error", () =>
      this.failAll(new ScorerError("worker_failed", "The inference worker stopped.")),
    );
  }

  score(image: ImageBitmap): Promise<ScoreResult> {
    if (this.atWorker.size >= this.maxInFlight) {
      return Promise.reject(new ScorerError("busy", "The inference worker is still working on earlier pictures."));
    }
    const id = this.nextId++;
    return new Promise<ScoreResult>((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        reject(new ScorerError("timeout", `No score arrived within ${this.timeoutMs} ms.`));
      }, this.timeoutMs);
      this.pending.set(id, { resolve, reject, timer });
      this.atWorker.add(id);
      this.worker.postMessage({ type: "score", id, image }, [image]); // moved, not copied
    });
  }

  dispose(): void {
    this.failAll(new ScorerError("worker_failed", "The scorer was shut down."));
    this.worker.terminate();
  }

  private onMessage(message: WorkerResponse): void {
    this.atWorker.delete(message.id); // answered, even if the answer is late
    const entry = this.pending.get(message.id);
    if (!entry) return; // a late answer to a request that already timed out
    this.pending.delete(message.id);
    clearTimeout(entry.timer);
    if (message.type === "result") entry.resolve(message.result);
    else entry.reject(new ScorerError(message.code, message.message));
  }

  private failAll(error: ScorerError): void {
    this.atWorker.clear(); // the worker is gone, and its memory with it
    for (const [id, entry] of this.pending) {
      clearTimeout(entry.timer);
      entry.reject(error);
      this.pending.delete(id);
    }
  }
}
