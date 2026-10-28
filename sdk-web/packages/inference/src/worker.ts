import type { ModelRunner, WorkerRequest, WorkerResponse } from "./protocol";

/** The small part of a worker's global scope that installWorker needs. */
export interface WorkerScope {
  onmessage: ((event: MessageEvent<WorkerRequest>) => void) | null;
  postMessage(message: WorkerResponse): void;
}

/**
 * Wires a model into a worker. With no model (null) every request is answered with "model_not_loaded":
 * the SDK never invents a score. The picture is ALWAYS closed after use, whatever happens.
 */
export function installWorker(scope: WorkerScope, runner: ModelRunner | null): void {
  let loading: Promise<void> | undefined;
  scope.onmessage = async (event) => {
    const { id, image } = event.data;
    try {
      if (!runner) {
        scope.postMessage({
          type: "error",
          id,
          code: "model_not_loaded",
          message: "No model is installed in this build (arrives in P0-37).",
        });
        return;
      }
      loading ??= runner.load();
      await loading;
      const result = await runner.score(image);
      scope.postMessage({ type: "result", id, result });
    } catch (error) {
      scope.postMessage({ type: "error", id, code: "scoring_failed", message: (error as Error).message });
    } finally {
      image.close();
    }
  };
}
