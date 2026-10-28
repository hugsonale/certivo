import { describe, expect, it } from "vitest";
import { CaptureError, VideoElementFrameSource } from "../src/index";

// The real behaviour of this class needs a real browser (a video element and a camera or canvas stream).
// It was checked in Chromium when P0-21 was built; an automated browser test arrives with P0-24.
// These tests cover what can be checked without a browser.

const stream = {} as MediaStream;

describe("VideoElementFrameSource", () => {
  it("refuses grab() before start()", async () => {
    const source = new VideoElementFrameSource(stream);
    await expect(source.grab()).rejects.toBeInstanceOf(CaptureError);
  });

  it("refuses a nonsense maxSide", () => {
    expect(() => new VideoElementFrameSource(stream, { maxSide: 0 })).toThrow(RangeError);
    expect(() => new VideoElementFrameSource(stream, { maxSide: 15 })).toThrow(RangeError);
    expect(() => new VideoElementFrameSource(stream, { maxSide: 224.5 })).toThrow(RangeError);
    expect(() => new VideoElementFrameSource(stream, { maxSide: 224 })).not.toThrow();
  });

  it("can be stopped before it was ever started", () => {
    expect(() => new VideoElementFrameSource(stream).stop()).not.toThrow();
  });
});
