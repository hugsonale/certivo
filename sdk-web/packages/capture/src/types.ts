/**
 * One video frame, held in memory only. Whoever receives a Frame must call close() as soon as they are
 * done with it: frames are never stored, never sent anywhere, and never kept past one inference interval
 * (TRD 2.2, guide Part 3). close() can be called more than once.
 */
export interface Frame {
  readonly width: number;
  readonly height: number;
  /** performance.now() when the frame was taken. */
  readonly timestampMs: number;
  /** The pixels. Only the inference step may look at this. */
  readonly image: ImageBitmap;
  close(): void;
}

/** Something that can hand out the next frame of a video. */
export interface FrameSource {
  start(): Promise<void>;
  /** Waits for a NEW frame (never the same one twice) and returns it. */
  grab(): Promise<Frame>;
  stop(): void;
}

export class CaptureError extends Error {
  override readonly name = "CaptureError";
}
