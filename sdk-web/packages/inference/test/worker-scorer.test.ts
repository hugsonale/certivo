import { describe, expect, it, vi } from "vitest";
import { ScorerError, type WorkerLike, type WorkerRequest, type WorkerResponse, WorkerScorer } from "../src/index";

class FakeWorker implements WorkerLike {
  sent: Array<{ message: WorkerRequest; transfer: Transferable[] }> = [];
  private onMessage: Array<(event: MessageEvent<WorkerResponse>) => void> = [];
  private onError: Array<(event: Event) => void> = [];
  terminated = false;

  postMessage(message: WorkerRequest, transfer: Transferable[]): void {
    this.sent.push({ message, transfer });
  }
  addEventListener(type: "message" | "error", listener: (event: never) => void): void {
    if (type === "message") this.onMessage.push(listener as (event: MessageEvent<WorkerResponse>) => void);
    else this.onError.push(listener as (event: Event) => void);
  }
  terminate(): void {
    this.terminated = true;
  }
  reply(data: WorkerResponse): void {
    for (const l of this.onMessage) l({ data } as MessageEvent<WorkerResponse>);
  }
  crash(): void {
    for (const l of this.onError) l(new Event("error"));
  }
}

const image = () => ({ close: vi.fn() }) as unknown as ImageBitmap;
const result = { confidenceMilli: 800, reasonCodes: ["consistent_motion"], signalMilli: {}, modelVersion: "t-0" };

describe("WorkerScorer", () => {
  it("moves (not copies) the picture to the worker and returns the score", async () => {
    const worker = new FakeWorker();
    const scorer = new WorkerScorer(worker);
    const bitmap = image();
    const pending = scorer.score(bitmap);
    const [sent] = worker.sent;
    expect(sent?.transfer).toEqual([bitmap]); // transferred: the page no longer holds it
    worker.reply({ type: "result", id: sent!.message.id, result });
    await expect(pending).resolves.toEqual(result);
  });

  it("keeps simultaneous requests apart", async () => {
    const worker = new FakeWorker();
    const scorer = new WorkerScorer(worker);
    const a = scorer.score(image());
    const b = scorer.score(image());
    worker.reply({ type: "result", id: worker.sent[1]!.message.id, result: { ...result, confidenceMilli: 200 } });
    worker.reply({ type: "result", id: worker.sent[0]!.message.id, result: { ...result, confidenceMilli: 900 } });
    expect((await a).confidenceMilli).toBe(900);
    expect((await b).confidenceMilli).toBe(200);
  });

  it("turns a worker error into a ScorerError with its code", async () => {
    const worker = new FakeWorker();
    const pending = new WorkerScorer(worker).score(image());
    worker.reply({ type: "error", id: worker.sent[0]!.message.id, code: "model_not_loaded", message: "no model" });
    const error = await pending.catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ScorerError);
    expect((error as ScorerError).code).toBe("model_not_loaded");
  });

  it("times out, and ignores the answer if it turns up later", async () => {
    const worker = new FakeWorker();
    const pending = new WorkerScorer(worker, 15).score(image());
    const error = await pending.catch((e: unknown) => e);
    expect((error as ScorerError).code).toBe("timeout");
    expect(() => worker.reply({ type: "result", id: worker.sent[0]!.message.id, result })).not.toThrow();
  });

  it("fails every waiting request if the worker crashes, and on dispose", async () => {
    const worker = new FakeWorker();
    const scorer = new WorkerScorer(worker);
    const first = scorer.score(image()).catch((e: unknown) => e);
    worker.crash();
    expect(((await first) as ScorerError).code).toBe("worker_failed");

    const second = scorer.score(image()).catch((e: unknown) => e);
    scorer.dispose();
    expect(((await second) as ScorerError).code).toBe("worker_failed");
    expect(worker.terminated).toBe(true);
  });
});
