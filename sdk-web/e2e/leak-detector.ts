/**
 * The rules that decide whether something sent from the page could be a picture (guide P0-24).
 * Pure functions with no browser and no Node-only code, so they can be unit-tested on their own
 * (test/leak-detector.test.ts) and then used on every request the real browser makes (e2e/no-media-egress.spec.ts).
 *
 * What this can and cannot prove: a request is flagged if it is not plain small JSON, carries a picture or video
 * file signature, carries a data: or blob: address, carries a long string or a long list of numbers, or contains the
 * actual pixel bytes the model saw (raw, hex, base64 or as a number list). A picture that has been compressed AND
 * disguised as small JSON would not be caught by the pixel-copy rule; the size, shape and type rules are what stand
 * in the way of that, together with the static guards in test/architecture.test.ts.
 */

export interface RecordedRequest {
  method: string;
  url: string;
  /** The request body exactly as the browser sent it, or null when there was none. */
  body: Uint8Array | null;
  contentType: string | undefined;
}

export interface Leak {
  rule: string;
  detail: string;
}

/** A packet is a few hundred bytes. Anything near the size of a frame is wrong. */
export const MAX_BODY_BYTES = 4096;
export const MAX_URL_LENGTH = 300;
const MAX_STRING_LENGTH = 256;
const MAX_NUMBER_LIST = 64;

/**
 * The first bytes of picture and video files. Short or all-letter markers are only checked where real files carry them
 * (at the start, or at a fixed offset): a marker like "BM" would otherwise turn up by chance inside ordinary text.
 */
const SIGNATURES: ReadonlyArray<{ name: string; bytes: readonly number[]; at?: number }> = [
  { name: "PNG", bytes: [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a] },
  { name: "JPEG", bytes: [0xff, 0xd8, 0xff] },
  { name: "GIF", bytes: [0x47, 0x49, 0x46, 0x38, 0x37, 0x61] }, // GIF87a
  { name: "GIF", bytes: [0x47, 0x49, 0x46, 0x38, 0x39, 0x61] }, // GIF89a
  { name: "WebP", bytes: [0x52, 0x49, 0x46, 0x46], at: 0 }, // "RIFF" ...
  { name: "WebP", bytes: [0x57, 0x45, 0x42, 0x50], at: 8 }, // ... "WEBP"
  { name: "MP4 or MOV", bytes: [0x66, 0x74, 0x79, 0x70], at: 4 }, // "ftyp"
  { name: "WebM or MKV", bytes: [0x1a, 0x45, 0xdf, 0xa3] },
  { name: "BMP", bytes: [0x42, 0x4d], at: 0 }, // "BM"
];

/** One byte becomes one character, so byte patterns can be searched as text. */
export function toLatin1(bytes: Uint8Array): string {
  let out = "";
  for (let i = 0; i < bytes.length; i += 8192) {
    out += String.fromCharCode(...bytes.subarray(i, i + 8192));
  }
  return out;
}

function containsBytes(haystack: Uint8Array, needle: readonly number[], at?: number): boolean {
  const first = at ?? 0;
  const last = at ?? haystack.length - needle.length;
  outer: for (let i = first; i <= last && i + needle.length <= haystack.length; i++) {
    for (let j = 0; j < needle.length; j++) if (haystack[i + j] !== needle[j]) continue outer;
    return true;
  }
  return false;
}

/** A sample is only useful as a canary if it is not flat or repetitive (a flat colour would match by chance). */
export function usableSample(sample: Uint8Array): boolean {
  return sample.length >= 12 && new Set(sample).size >= 8;
}

/** Every way a sample of pixel bytes could show up inside a request body, written out as text to search for. */
export function needlesFor(sample: Uint8Array): Array<{ form: string; needle: string }> {
  const raw = toLatin1(sample);
  const hex = [...sample].map((b) => b.toString(16).padStart(2, "0")).join("");
  const needles: Array<{ form: string; needle: string }> = [
    { form: "raw bytes", needle: raw },
    { form: "hex (lower case)", needle: hex },
    { form: "hex (upper case)", needle: hex.toUpperCase() },
    { form: "number list", needle: [...sample].join(",") },
    { form: "number list with spaces", needle: [...sample].join(", ") },
  ];
  // base64 depends on where the sample starts, so write it out for each of the three possible alignments.
  for (let k = 0; k < 3; k++) {
    const padded = new Uint8Array(k + sample.length);
    padded.set(sample, k);
    const lead = k === 0 ? 0 : k === 1 ? 2 : 3;
    const trail = padded.length % 3 === 0 ? 0 : 1;
    const text = btoa(toLatin1(padded)).replace(/=+$/, "");
    const core = text.slice(lead, text.length - trail);
    needles.push({ form: `base64 (alignment ${k})`, needle: core });
    needles.push({ form: `base64url (alignment ${k})`, needle: core.replace(/\+/g, "-").replace(/\//g, "_") });
  }
  return needles;
}

function jsonShapeProblems(value: unknown, path = "$"): string[] {
  if (typeof value === "string") {
    return value.length > MAX_STRING_LENGTH ? [`${path} is a string of ${value.length} characters`] : [];
  }
  if (Array.isArray(value)) {
    const problems: string[] = [];
    if (value.length > MAX_NUMBER_LIST && value.every((v) => typeof v === "number")) {
      problems.push(`${path} is a list of ${value.length} numbers`);
    }
    value.forEach((v, i) => {
      problems.push(...jsonShapeProblems(v, `${path}[${i}]`));
    });
    return problems;
  }
  if (value && typeof value === "object") {
    return Object.entries(value).flatMap(([k, v]) => jsonShapeProblems(v, `${path}.${k}`));
  }
  return [];
}

/** All the reasons to think this one request could carry a picture. An empty list means it looks clean. */
export function findLeaks(request: RecordedRequest, canary: readonly Uint8Array[]): Leak[] {
  const leaks: Leak[] = [];
  const add = (rule: string, detail: string) => leaks.push({ rule, detail });

  if (request.url.length > MAX_URL_LENGTH) add("long-url", `the address is ${request.url.length} characters long`);
  if (/^(data|blob):/i.test(request.url)) add("data-address", "the request goes to a data: or blob: address");

  const body = request.body;
  if (!body || body.length === 0) return leaks;

  if (body.length > MAX_BODY_BYTES) add("body-too-big", `${body.length} bytes (limit ${MAX_BODY_BYTES})`);
  if (!/^application\/json\b/i.test(request.contentType ?? "")) {
    add("not-json", `content type is "${request.contentType ?? "none"}"`);
  }

  const named = new Set<string>();
  for (const { name, bytes, at } of SIGNATURES) {
    if (containsBytes(body, bytes, at)) named.add(name);
  }
  // WebP needs both of its markers (RIFF at the start and WEBP at byte 8); every other file type needs only its own.
  const webpParts = SIGNATURES.filter((x) => x.name === "WebP").length;
  const webpHits = SIGNATURES.filter((x) => x.name === "WebP" && containsBytes(body, x.bytes, x.at)).length;
  if (webpHits < webpParts) named.delete("WebP");
  for (const name of named) add("file-signature", `contains the bytes of a ${name} file`);

  const text = toLatin1(body);
  if (/data:(image|video|audio)\//i.test(text) || /blob:https?:/i.test(text)) {
    add("data-address", "the body contains a data: or blob: address");
  }

  try {
    const parsed: unknown = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(body));
    for (const problem of jsonShapeProblems(parsed)) add("odd-json-shape", problem);
  } catch {
    add("not-json", "the body is not valid JSON text");
  }

  for (const sample of canary) {
    if (!usableSample(sample)) continue;
    for (const { form, needle } of needlesFor(sample)) {
      if (text.includes(needle)) add("pixel-copy", `the body contains pixel bytes the model saw (${form})`);
    }
  }
  return leaks;
}

/** The only addresses the page may talk to in the test: its own files and the score endpoint. */
export function unexpectedDestination(url: string, allowedOrigin: string): string | undefined {
  let parsed: URL;
  try {
    parsed = new URL(url);
  } catch {
    return `not a valid address: ${url.slice(0, 80)}`;
  }
  if (parsed.origin !== allowedOrigin) return `leaves the test server: ${parsed.origin}`;
  const allowed =
    /^\/(page\.js|worker\.js|favicon\.ico|internal\/v1\/sessions\/continuous\/[A-Za-z0-9_-]+\/score-events)?$/;
  if (!allowed.test(parsed.pathname)) return `unexpected path: ${parsed.pathname}`;
  if (parsed.search) return `has a query string: ${parsed.search.slice(0, 40)}`;
  return undefined;
}
