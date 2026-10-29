import type { ScoreResult } from "@certivo/sdk-types";

/** Messages between the page and the inference worker. Only these ever cross: a picture goes in, numbers come out. */
export type WorkerRequest = { type: "score"; id: number; image: ImageBitmap };

export type WorkerResponse =
  | { type: "result"; id: number; result: ScoreResult }
  | { type: "error"; id: number; code: ScorerErrorCode; message: string };

export type ScorerErrorCode = "model_not_loaded" | "scoring_failed" | "timeout" | "worker_failed";

export class ScorerError extends Error {
  override readonly name = "ScorerError";
  constructor(
    readonly code: ScorerErrorCode,
    message: string,
  ) {
    super(message);
  }
}

/** Turns one picture into a score. The only thing that leaves is a ScoreResult. */
export interface Scorer {
  /**
   * After this call the image belongs to the scorer: it is moved to the worker and closed there. The caller
   * should still call close() on its own copy (a no-op once moved).
   */
  score(image: ImageBitmap): Promise<ScoreResult>;
}

/** The model itself, supplied in step P0-37 (ONNX Runtime Web). It runs inside the worker. */
export interface ModelRunner {
  load(): Promise<void>;
  score(image: ImageBitmap): Promise<ScoreResult>;
}
