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

/** Sends pictures to an inference worker and waits for the score. */
export class WorkerScorer implements Scorer {
  private nextId = 1;
  private readonly pending = new Map<number, Pending>();

  constructor(
    private readonly worker: WorkerLike,
    private readonly timeoutMs = 2000,
  ) {
    worker.addEventListener("message", (event) => this.onMessage(event.data));
    worker.addEventListener("error", () =>
      this.failAll(new ScorerError("worker_failed", "The inference worker stopped.")),
    );
  }

  score(image: ImageBitmap): Promise<ScoreResult> {
    const id = this.nextId++;
    return new Promise<ScoreResult>((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        reject(new ScorerError("timeout", `No score arrived within ${this.timeoutMs} ms.`));
      }, this.timeoutMs);
      this.pending.set(id, { resolve, reject, timer });
      this.worker.postMessage({ type: "score", id, image }, [image]); // moved, not copied
    });
  }

  dispose(): void {
    this.failAll(new ScorerError("worker_failed", "The scorer was shut down."));
    this.worker.terminate();
  }

  private onMessage(message: WorkerResponse): void {
    const entry = this.pending.get(message.id);
    if (!entry) return; // a late answer to a request that already timed out
    this.pending.delete(message.id);
    clearTimeout(entry.timer);
    if (message.type === "result") entry.resolve(message.result);
    else entry.reject(new ScorerError(message.code, message.message));
  }

  private failAll(error: ScorerError): void {
    for (const [id, entry] of this.pending) {
      clearTimeout(entry.timer);
      entry.reject(error);
      this.pending.delete(id);
    }
  }
}
