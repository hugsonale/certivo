import type { ScoreResult } from "@certivo/sdk-types";
import { describe, expect, it } from "vitest";
import { ScorerError, type WorkerRequest, type WorkerResponse } from "../src/protocol";
import { type WorkerLike, WorkerScorer } from "../src/worker-scorer";

const result: ScoreResult = { confidenceMilli: 900, reasonCodes: ["ok"], signalMilli: {}, modelVersion: "t-1" };
const picture = () => ({}) as ImageBitmap;

/** A worker that only answers when the test says so. */
function slowWorker() {
  const sent: WorkerRequest[] = [];
  let onMessage: ((event: MessageEvent<WorkerResponse>) => void) | undefined;
  const worker: WorkerLike = {
    postMessage: (message) => {
      sent.push(message);
    },
    addEventListener: ((type: string, listener: (event: never) => void) => {
      if (type === "message") onMessage = listener as typeof onMessage;
    }) as WorkerLike["addEventListener"],
    terminate: () => {},
  };
  const answer = (id: number) => onMessage?.({ data: { type: "result", id, result } } as MessageEvent<WorkerResponse>);
  return { worker, sent, answer };
}

describe("WorkerScorer back-pressure (guide P0-24: no frame retention)", () => {
  it("refuses with 'busy' and does NOT send the picture once too many are waiting at the worker", async () => {
    const { worker, sent } = slowWorker();
    const scorer = new WorkerScorer(worker, 5000, 2);
    void scorer.score(picture()).catch(() => {});
    void scorer.score(picture()).catch(() => {});
    const refused = scorer.score(picture());
    await expect(refused).rejects.toBeInstanceOf(ScorerError);
    await expect(refused).rejects.toMatchObject({ code: "busy" });
    expect(sent).toHaveLength(2); // the third picture never left the page's hands
    scorer.dispose();
  });

  it("keeps counting a picture whose wait timed out, until the worker answers it", async () => {
    const { worker, sent, answer } = slowWorker();
    const scorer = new WorkerScorer(worker, 10, 1); // gives up after 10 ms; allows 1 at the worker
    await expect(scorer.score(picture())).rejects.toMatchObject({ code: "timeout" });
    // The worker still holds that picture, so a second one must be refused.
    await expect(scorer.score(picture())).rejects.toMatchObject({ code: "busy" });
    expect(sent).toHaveLength(1);
    // The late answer frees the slot.
    answer(1);
    const next = scorer.score(picture());
    expect(sent).toHaveLength(2);
    answer(2);
    await expect(next).resolves.toEqual(result);
    scorer.dispose();
  });

  it("a normal one-at-a-time loop is never refused", async () => {
    const { worker, answer } = slowWorker();
    const scorer = new WorkerScorer(worker);
    for (let id = 1; id <= 20; id++) {
      const pending = scorer.score(picture());
      answer(id);
      await expect(pending).resolves.toEqual(result);
    }
    scorer.dispose();
  });
});
