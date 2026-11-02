import { describe, expect, it } from "vitest";
import {
  findLeaks,
  MAX_BODY_BYTES,
  needlesFor,
  type RecordedRequest,
  toLatin1,
  unexpectedDestination,
  usableSample,
} from "../e2e/leak-detector";

/**
 * P0-24: the runtime test is only worth something if the detector can actually catch a leak. These tests feed it
 * every kind of leak we know about, and a normal packet, and check each verdict.
 */

const encoder = new TextEncoder();
const noise = (length: number, seed = 7): Uint8Array => {
  const out = new Uint8Array(length);
  let x = seed;
  for (let i = 0; i < length; i++) {
    x = (x * 1103515245 + 12345) & 0x7fffffff;
    out[i] = (x >> 16) & 0xff;
  }
  return out;
};
const sample = noise(24);
const canary = [sample];

const post = (body: Uint8Array | string, contentType: string | undefined = "application/json"): RecordedRequest => ({
  method: "POST",
  url: "http://127.0.0.1:1234/internal/v1/sessions/continuous/sess_1/score-events",
  body: typeof body === "string" ? encoder.encode(body) : body,
  contentType,
});
const rulesOf = (request: RecordedRequest) => findLeaks(request, canary).map((l) => l.rule);

const packet = JSON.stringify({
  v: 1,
  device_id: `dev_${"a".repeat(32)}`,
  seq: 4,
  confidence_milli: 912,
  reason_codes: ["consistent_face"],
  signal_milli: { motion: 400 },
  model_version: "m-1",
  signature: "x".repeat(86),
});

describe("the leak detector accepts a normal packet", () => {
  it("passes a realistic packet", () => {
    expect(rulesOf(post(packet))).toEqual([]);
  });
  it("passes a request with no body", () => {
    expect(rulesOf({ method: "GET", url: "http://127.0.0.1:1/page.js", body: null, contentType: undefined })).toEqual(
      [],
    );
  });
});

describe("the leak detector catches every way a picture could go out", () => {
  it("a body that is not JSON (raw picture data)", () => {
    expect(rulesOf(post(noise(900, 3), "application/octet-stream"))).toContain("not-json");
  });
  it("a JSON content type on a binary body", () => {
    expect(rulesOf(post(noise(900, 3)))).toContain("not-json");
  });
  it("a body as big as a frame", () => {
    const big = JSON.stringify({ pixels: "a".repeat(MAX_BODY_BYTES + 10) });
    const rules = rulesOf(post(big));
    expect(rules).toContain("body-too-big");
    expect(rules).toContain("odd-json-shape");
  });
  it("picture and video file signatures", () => {
    const filled = (bytes: number[], at: number, extra: Array<[number[], number]> = []) => {
      const body = new Uint8Array(200).fill(0x20);
      body.set(bytes, at);
      for (const [more, where] of extra) body.set(more, where);
      return post(body, "image/x");
    };
    expect(rulesOf(filled([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a], 50))).toContain("file-signature");
    expect(rulesOf(filled([0xff, 0xd8, 0xff, 0xe0], 50))).toContain("file-signature");
    expect(rulesOf(filled([0x47, 0x49, 0x46, 0x38, 0x39, 0x61], 50))).toContain("file-signature");
    expect(rulesOf(filled([0x52, 0x49, 0x46, 0x46], 0, [[[0x57, 0x45, 0x42, 0x50], 8]]))).toContain("file-signature");
    expect(rulesOf(filled([0x66, 0x74, 0x79, 0x70], 4))).toContain("file-signature");
    expect(rulesOf(filled([0x1a, 0x45, 0xdf, 0xa3], 50))).toContain("file-signature");
    expect(rulesOf(filled([0x42, 0x4d], 0))).toContain("file-signature");
  });
  it("does not mistake ordinary text for a file signature", () => {
    // "BM", "RIFF", "ftyp" and "WEBP" are only meaningful at their fixed places in a file
    expect(rulesOf(post(JSON.stringify({ s: "xxBMxxRIFFxxftypxxWEBPxxGIF89xx" })))).toEqual([]);
    expect(rulesOf(post(JSON.stringify({ s: "RIFF" })))).toEqual([]); // RIFF alone is not WebP
  });
  it("a data: address inside JSON", () => {
    expect(rulesOf(post(JSON.stringify({ frame: "data:image/png;base64,AAAA" })))).toContain("data-address");
  });
  it("a long string and a long list of numbers", () => {
    expect(rulesOf(post(JSON.stringify({ s: "z".repeat(300) })))).toContain("odd-json-shape");
    expect(rulesOf(post(JSON.stringify({ n: Array.from({ length: 100 }, (_, i) => i % 255) })))).toContain(
      "odd-json-shape",
    );
  });
  it("a very long address", () => {
    expect(
      findLeaks(
        { method: "GET", url: `http://127.0.0.1:1/x?d=${"a".repeat(400)}`, body: null, contentType: undefined },
        [],
      ).map((l) => l.rule),
    ).toContain("long-url");
  });
});

describe("the leak detector finds the real pixel bytes in every disguise", () => {
  const forms = needlesFor(sample);
  it("knows many disguises", () => {
    expect(forms.length).toBeGreaterThanOrEqual(11);
  });
  for (const { form, needle } of forms) {
    it(`finds them as: ${form}`, () => {
      if (form === "raw bytes") {
        const raw = new Uint8Array(sample.length + 20);
        raw.set(sample, 10);
        expect(rulesOf(post(raw))).toContain("pixel-copy");
      } else {
        // the needle is plain text here, hidden inside an otherwise normal-looking JSON body
        expect(rulesOf(post(`{"note":"hi","x":"${needle}"}`))).toContain("pixel-copy");
      }
    });
  }

  it("finds base64 even when the sample sits at an odd offset inside a bigger buffer", () => {
    for (const prefix of [0, 1, 2]) {
      const buffer = new Uint8Array(prefix + 40 + sample.length + 5);
      buffer.set(noise(prefix + 40, 99));
      buffer.set(sample, prefix + 40);
      const text = btoa(toLatin1(buffer));
      expect(rulesOf(post(JSON.stringify({ d: text.slice(0, 200) })))).toContain("pixel-copy");
    }
  });

  it("does not use a flat or repetitive sample as a canary", () => {
    expect(usableSample(new Uint8Array(24).fill(255))).toBe(false);
    expect(usableSample(new Uint8Array(24))).toBe(false);
    expect(usableSample(sample)).toBe(true);
    expect(findLeaks(post(JSON.stringify({ a: 1 })), [new Uint8Array(24).fill(1)])).toEqual([]);
  });
});

describe("unexpectedDestination", () => {
  const origin = "http://127.0.0.1:4321";
  it("allows the test server's own files and the score endpoint", () => {
    for (const path of ["/", "/page.js", "/worker.js", "/internal/v1/sessions/continuous/sess_1/score-events"]) {
      expect(unexpectedDestination(`${origin}${path}`, origin)).toBeUndefined();
    }
  });
  it("refuses another host, another path and a query string", () => {
    expect(unexpectedDestination("https://example.com/x", origin)).toMatch(/leaves the test server/);
    expect(unexpectedDestination(`${origin}/upload`, origin)).toMatch(/unexpected path/);
    expect(unexpectedDestination(`${origin}/page.js?d=1`, origin)).toMatch(/query string/);
    expect(unexpectedDestination("not a url", origin)).toMatch(/not a valid address/);
  });
});
