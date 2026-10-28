import { CaptureError, type Frame, type FrameSource } from "./types";

export interface VideoElementFrameSourceOptions {
  /** Shrink frames so their longest side is at most this many pixels (smaller frames cost less memory and time). */
  maxSide?: number;
  /** Give up waiting for a new frame after this long. Default 3000 ms. */
  frameTimeoutMs?: number;
  document?: Document;
}

/**
 * Reads frames from a MediaStream (the local camera, or the received video of a call) by playing it in a
 * hidden video element, drawing it on a canvas and taking an ImageBitmap. This is the one frame-reading
 * path that worked in every browser tested in P0-20 (Chrome, Edge, Firefox); the raw-frame API
 * (MediaStreamTrackProcessor) is absent in Firefox, so nothing here depends on it (ADR 0020).
 *
 * The SDK does not own the stream: stop() never stops the camera.
 */
export class VideoElementFrameSource implements FrameSource {
  private video: HTMLVideoElement | undefined;
  private canvas: HTMLCanvasElement | undefined;
  private context: CanvasRenderingContext2D | null = null;

  constructor(
    private readonly stream: MediaStream,
    private readonly options: VideoElementFrameSourceOptions = {},
  ) {
    const side = options.maxSide;
    if (side !== undefined && (!Number.isInteger(side) || side < 16)) {
      throw new RangeError("maxSide must be a whole number of at least 16");
    }
  }

  async start(): Promise<void> {
    if (this.video) return;
    const doc = this.options.document ?? document;
    const video = doc.createElement("video");
    video.muted = true;
    video.playsInline = true;
    video.setAttribute("aria-hidden", "true");
    // Off-screen, not display:none: some browsers stop delivering frames to a hidden video.
    video.style.cssText = "position:fixed;left:-9999px;top:0;width:2px;height:2px;opacity:0;pointer-events:none";
    video.srcObject = this.stream;
    doc.body.appendChild(video);
    try {
      await video.play();
    } catch (error) {
      video.remove();
      throw new CaptureError(`The video could not start playing (${(error as Error).name}).`);
    }
    this.video = video;
    this.canvas = doc.createElement("canvas");
    this.context = this.canvas.getContext("2d", { willReadFrequently: false });
    if (!this.context) {
      this.stop();
      throw new CaptureError("A 2D canvas is not available in this browser.");
    }
  }

  async grab(): Promise<Frame> {
    const { video, canvas, context } = this;
    if (!video || !canvas || !context) throw new CaptureError("grab() was called before start().");
    await this.nextFrame(video);
    if (!video.videoWidth) throw new CaptureError("The video has no picture yet.");

    const scale = this.options.maxSide
      ? Math.min(1, this.options.maxSide / Math.max(video.videoWidth, video.videoHeight))
      : 1;
    const width = Math.max(1, Math.round(video.videoWidth * scale));
    const height = Math.max(1, Math.round(video.videoHeight * scale));
    canvas.width = width;
    canvas.height = height;
    context.drawImage(video, 0, 0, width, height);
    const image = await createImageBitmap(canvas);

    let closed = false;
    return {
      width,
      height,
      timestampMs: performance.now(),
      image,
      close() {
        if (closed) return;
        closed = true;
        image.close();
      },
    };
  }

  stop(): void {
    if (this.video) {
      this.video.pause();
      this.video.srcObject = null; // lets go of the stream without stopping the camera
      this.video.remove();
    }
    this.video = undefined;
    this.canvas = undefined;
    this.context = null;
  }

  private nextFrame(video: HTMLVideoElement): Promise<void> {
    const timeoutMs = this.options.frameTimeoutMs ?? 3000;
    return new Promise((resolve, reject) => {
      const timer = setTimeout(
        () => reject(new CaptureError(`No new video frame arrived within ${timeoutMs} ms.`)),
        timeoutMs,
      );
      const done = () => {
        clearTimeout(timer);
        resolve();
      };
      if ("requestVideoFrameCallback" in video) video.requestVideoFrameCallback(done);
      else setTimeout(done, 100); // older browsers: poll at about 10 frames a second
    });
  }
}
