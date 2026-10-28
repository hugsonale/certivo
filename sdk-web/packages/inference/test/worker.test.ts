import { describe, expect, it, vi } from "vitest";
import {
  installWorker,
  type ModelRunner,
  type WorkerRequest,
  type WorkerResponse,
  type WorkerScope,
} from "../src/index";

function setup(runner: ModelRunner | null) {
  const out: WorkerResponse[] = [];
  const scope: WorkerScope = { onmessage: null, postMessage: (m) => void out.push(m) };
  installWorker(scope, runner);
  const send = async (id: number, image: ImageBitmap) => {
    await scope.onmessage?.({
      data: { type: "score", id, image } satisfies WorkerRequest,
    } as MessageEvent<WorkerRequest>);
  };
  return { out, send };
}
const image = () => ({ close: vi.fn() }) as unknown as ImageBitmap;
const result = { confidence: 0.7, reasonCodes: ["consistent_face"], modelVersion: "t-0" };

describe("installWorker", () => {
  it("with no model, never invents a score, and still closes the picture", async () => {
    const { out, send } = setup(null);
    const bitmap = image();
    await send(1, bitmap);
    expect(out).toEqual([{ type: "error", id: 1, code: "model_not_loaded", message: expect.any(String) }]);
    expect(bitmap.close).toHaveBeenCalledTimes(1);
  });

  it("returns the model's score and closes the picture", async () => {
    const runner: ModelRunner = { load: vi.fn(async () => {}), score: vi.fn(async () => result) };
    const { out, send } = setup(runner);
    const bitmap = image();
    await send(7, bitmap);
    expect(out).toEqual([{ type: "result", id: 7, result }]);
    expect(bitmap.close).toHaveBeenCalledTimes(1);
  });

  it("closes the picture even when the model fails, and reports it as an error", async () => {
    const runner: ModelRunner = {
      load: async () => {},
      score: async () => Promise.reject(new Error("model exploded")),
    };
    const { out, send } = setup(runner);
    const bitmap = image();
    await send(2, bitmap);
    expect(out).toEqual([{ type: "error", id: 2, code: "scoring_failed", message: "model exploded" }]);
    expect(bitmap.close).toHaveBeenCalledTimes(1);
  });

  it("loads the model once, however many pictures arrive", async () => {
    const runner: ModelRunner = { load: vi.fn(async () => {}), score: async () => result };
    const { send } = setup(runner);
    await send(1, image());
    await send(2, image());
    await send(3, image());
    expect(runner.load).toHaveBeenCalledTimes(1);
  });
});
