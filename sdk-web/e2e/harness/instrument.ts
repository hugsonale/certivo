/**
 * Watches the page (and the inference worker) for anything that could send a picture out, turn it into bytes, or keep it
 * (guide P0-24). It is loaded FIRST in both test bundles, so it is in place before any SDK code runs. It only records;
 * every call still goes through. The records are read by e2e/no-media-egress.spec.ts.
 *
 * This is test code. It is never part of the SDK bundle.
 */
export type Where = "page" | "worker";

export interface E2eEvent {
  where: Where;
  /** For example "network:fetch", "encode:toblob", "pixels:read", "storage:idb", "message:to-worker". */
  kind: string;
  detail: string;
  /** For storage writes: the text that was stored (capped), so the spec can look for pixel bytes in it. */
  text?: string;
}

export interface E2eState {
  where: Where;
  events: E2eEvent[];
  /** While above 0, the harness itself is calling (for example to build the fake camera): not recorded. */
  allow: number;
  /** Every picture created in this scope. A picture that was closed or moved away reports a width of 0. */
  bitmaps: ImageBitmap[];
}

type Fn = (this: unknown, ...args: unknown[]) => unknown;
type Holder = Record<string, Fn>;

const scope = globalThis as unknown as Record<string, unknown>;
const where: Where = typeof document === "undefined" ? "worker" : "page";
const state: E2eState = { where, events: [], allow: 0, bitmaps: [] };
scope.__e2e = state;

export function record(kind: string, detail: string, text?: string): void {
  if (state.allow > 0) return;
  state.events.push({
    where,
    kind,
    detail: detail.slice(0, 300),
    ...(text !== undefined ? { text: text.slice(0, 4000) } : {}),
  });
}

/** Run something the harness itself needs without it being recorded as the SDK's doing. */
export function allowed<T>(work: () => T): T {
  state.allow++;
  try {
    return work();
  } finally {
    state.allow--;
  }
}

/** A short description of a value: its kind, and its size when that is easy to know. Never the contents. */
export function kindOf(value: unknown): string {
  if (value === null) return "null";
  if (typeof value !== "object") return typeof value;
  const tag = Object.prototype.toString.call(value);
  if (value instanceof ArrayBuffer) return `${tag} ${value.byteLength} bytes`;
  if (ArrayBuffer.isView(value)) return `${tag} ${value.byteLength} bytes`;
  if (typeof Blob !== "undefined" && value instanceof Blob) return `${tag} ${value.size} bytes`;
  return tag;
}

/** Every leaf of a message as "path: kind", so the spec can check that only numbers and words travel. */
export function shapeOf(value: unknown, path = "$", depth = 0): string[] {
  if (depth > 6) return [`${path}: too deep`];
  if (value === null || typeof value !== "object") {
    return [`${path}: ${typeof value}${typeof value === "string" ? ` ${value.length}` : ""}`];
  }
  const tag = Object.prototype.toString.call(value);
  if (Array.isArray(value)) return value.flatMap((v, i) => shapeOf(v, `${path}[${i}]`, depth + 1));
  if (tag !== "[object Object]") return [`${path}: ${kindOf(value)}`];
  return Object.entries(value).flatMap(([k, v]) => shapeOf(v, `${path}.${k}`, depth + 1));
}

function wrap(
  target: object | undefined,
  name: string,
  kind: string,
  describe: (args: unknown[]) => [string, string?],
) {
  if (!target) return;
  const holder = target as Holder;
  const original = holder[name];
  if (typeof original !== "function") return;
  holder[name] = function (this: unknown, ...args: unknown[]) {
    const [detail, text] = describe(args);
    record(kind, detail, text);
    return original.apply(this, args);
  };
}

function wrapConstructor(name: string, kind: string) {
  const original = scope[name];
  if (typeof original !== "function") return;
  scope[name] = new Proxy(original as new (...args: unknown[]) => object, {
    construct(target, args, newTarget) {
      record(kind, `${name}(${String(args[0] ?? "").slice(0, 80)})`);
      return Reflect.construct(target, args, newTarget);
    },
  });
}

const proto = (name: string): object | undefined => (scope[name] as { prototype?: object } | undefined)?.prototype;

// --- anything that talks to a network ---
wrap(scope, "fetch", "network:fetch", (a) => {
  const input = a[0];
  const url =
    typeof input === "string"
      ? input
      : input instanceof URL
        ? input.href
        : ((input as Request | undefined)?.url ?? "?");
  const init = a[1] as { body?: unknown; method?: string } | undefined;
  return [`${init?.method ?? "GET"} ${url} body=${kindOf(init?.body)}`];
});
wrap(proto("XMLHttpRequest"), "send", "network:xhr", (a) => [`body=${kindOf(a[0])}`]);
wrap(proto("Navigator"), "sendBeacon", "network:beacon", (a) => [`${String(a[0])} body=${kindOf(a[1])}`]);
wrap(scope, "importScripts", "network:importscripts", (a) => [a.map(String).join(" ")]);
wrapConstructor("WebSocket", "network:websocket");
wrapConstructor("EventSource", "network:eventsource");
wrapConstructor("RTCPeerConnection", "network:webrtc");
wrapConstructor("WebTransport", "network:webtransport");

// --- anything that turns a picture into bytes, a file or a recording ---
wrap(proto("HTMLCanvasElement"), "toBlob", "encode:toblob", () => ["canvas.toBlob"]);
wrap(proto("HTMLCanvasElement"), "toDataURL", "encode:todataurl", () => ["canvas.toDataURL"]);
wrap(proto("HTMLCanvasElement"), "captureStream", "capture:capturestream", () => ["canvas.captureStream"]);
wrap(proto("OffscreenCanvas"), "convertToBlob", "encode:converttoblob", () => ["OffscreenCanvas.convertToBlob"]);
wrap(proto("FileReader"), "readAsDataURL", "encode:filereader", () => ["readAsDataURL"]);
wrap(proto("FileReader"), "readAsArrayBuffer", "encode:filereader", () => ["readAsArrayBuffer"]);
wrap(proto("FileReader"), "readAsBinaryString", "encode:filereader", () => ["readAsBinaryString"]);
wrap(scope.URL as object, "createObjectURL", "encode:objecturl", () => ["URL.createObjectURL"]);
wrapConstructor("MediaRecorder", "encode:mediarecorder");

// --- reading pixel values out of a picture ---
wrap(proto("CanvasRenderingContext2D"), "getImageData", "pixels:read", () => ["getImageData"]);
wrap(proto("OffscreenCanvasRenderingContext2D"), "getImageData", "pixels:read", () => ["getImageData"]);

// --- anything that keeps data after the page is closed ---
wrap(proto("Storage"), "setItem", "storage:web", (a) => [
  `${String(a[0])} (${String(a[1]).length} characters)`,
  String(a[1]),
]);
const describeStored = (a: unknown[]): [string, string] => {
  const value = a[0] as unknown;
  const parts = shapeOf(value).join("; ");
  let text = "";
  try {
    text = JSON.stringify(value) ?? "";
  } catch {
    // values holding keys or bytes cannot be turned into text: the shape list above still describes them
  }
  return [parts, text];
};
wrap(proto("IDBObjectStore"), "put", "storage:idb", describeStored);
wrap(proto("IDBObjectStore"), "add", "storage:idb", describeStored);
wrap(proto("Cache"), "put", "storage:cache", () => ["Cache.put"]);
wrap(proto("Cache"), "add", "storage:cache", () => ["Cache.add"]);
wrap(proto("Cache"), "addAll", "storage:cache", () => ["Cache.addAll"]);
wrap(proto("StorageManager"), "getDirectory", "storage:opfs", () => ["navigator.storage.getDirectory"]);

// --- what crosses between the page and the worker ---
if (where === "page") {
  wrap(proto("Worker"), "postMessage", "message:to-worker", (a) => {
    const transfer = Array.isArray(a[1]) ? (a[1] as unknown[]).map(kindOf).join(",") : "";
    return [`${shapeOf(a[0]).join("; ")} | transfer=${transfer}`];
  });
} else {
  wrap(scope, "postMessage", "message:from-worker", (a) => [shapeOf(a[0]).join("; ")]);
}

// --- every picture that is created, so the spec can count the ones still open ---
const originalCreate = scope.createImageBitmap as ((...args: unknown[]) => Promise<ImageBitmap>) | undefined;
if (originalCreate) {
  scope.createImageBitmap = async (...args: unknown[]) => {
    const bitmap = await originalCreate.apply(globalThis, args);
    state.bitmaps.push(bitmap);
    return bitmap;
  };
}

/** How many pictures created in this scope still hold pixels. A closed or transferred picture reports width 0. */
export function liveBitmaps(): number {
  return state.bitmaps.filter((b) => b.width > 0 || b.height > 0).length;
}

/** Forget closed pictures so the list does not grow during long runs. */
export function pruneBitmaps(): void {
  state.bitmaps = state.bitmaps.filter((b) => b.width > 0 || b.height > 0);
}
