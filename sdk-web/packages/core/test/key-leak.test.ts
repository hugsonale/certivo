/**
 * "The private key never appears in network traffic or logs (tested)." (P0-23)
 *
 * A key the browser keeps non-extractable cannot be read back, so to LOOK for it the test has to know it. So the test uses a
 * WebCrypto wrapper that makes an extractable copy of each key the SDK asks for, only so the test can learn the secret bytes.
 * It also records what the SDK asked for, and the tests check the SDK DID ask for a non-extractable key.
 * Then the whole SDK flow is run while every channel is recorded (network requests, console output, error text, the
 * registration request), and every recording is searched for the secret in every common written form.
 *
 * Limits, stated plainly: this finds the key written in the forms below. It cannot find a key that has been scrambled
 * on purpose. It covers the code paths exercised here. The static guards in test/architecture.test.ts keep the other
 * routes closed (no console, no private-key export), and P0-24 adds a real-browser network interception test.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  buildPacket,
  MemoryKeyStore,
  provisionDevice,
  type RegisterDevice,
  SdkError,
  SessionClient,
  scoreCodecV1,
} from "../src/index";

const real = globalThis.crypto.subtle;

// ------------------------------------------------------------------ the test-only WebCrypto wrapper

interface Spy {
  subtle: SubtleCrypto;
  generateCalls: Array<{ extractable: boolean; usages: readonly string[] }>;
  exportCalls: Array<{ format: string; keyType: string }>;
  secrets: Uint8Array[]; // every secret the test learned (private key, in PKCS#8 form, and the 32-byte seed inside it)
}

function spiedSubtle(): Spy {
  const spy: Spy = { subtle: real, generateCalls: [], exportCalls: [], secrets: [] };
  spy.subtle = new Proxy(real, {
    get(target, prop) {
      if (prop === "generateKey") {
        return async (algorithm: unknown, extractable: boolean, usages: readonly string[]) => {
          spy.generateCalls.push({ extractable, usages: [...usages] });
          // TEST ONLY: make it really extractable so that the test can learn the secret and hunt for it.
          const pair = (await target.generateKey(algorithm as never, true, usages as never)) as CryptoKeyPair;
          const pkcs8 = new Uint8Array(await target.exportKey("pkcs8", pair.privateKey));
          spy.secrets.push(pkcs8, pkcs8.slice(-32));
          return pair;
        };
      }
      if (prop === "exportKey") {
        return (format: string, key: CryptoKey) => {
          spy.exportCalls.push({ format, keyType: key.type });
          return target.exportKey(format as never, key);
        };
      }
      const value = Reflect.get(target, prop) as unknown;
      return typeof value === "function" ? value.bind(target) : value;
    },
  });
  return spy;
}

// ------------------------------------------------------------------ the detector

const toHex = (b: Uint8Array) => [...b].map((x) => x.toString(16).padStart(2, "0")).join("");
const toB64 = (b: Uint8Array) => btoa(String.fromCharCode(...b));

/** Every common way a byte string gets written down. */
function writtenForms(bytes: Uint8Array): Array<[string, string]> {
  const std = toB64(bytes);
  const url = std.replace(/\+/g, "-").replace(/\//g, "_");
  const array = Array.from(bytes);
  return [
    ["hex", toHex(bytes)],
    ["HEX", toHex(bytes).toUpperCase()],
    ["base64", std],
    ["base64 without padding", std.replace(/=+$/, "")],
    ["base64url", url],
    ["base64url without padding", url.replace(/=+$/, "")],
    ["JSON array", JSON.stringify(array)],
    ["comma list", array.join(",")],
    ["JSON object (a typed array stringified)", JSON.stringify({ ...array })],
    ["raw characters", String.fromCharCode(...bytes)],
  ];
}

/** Which forms of any secret appear in the text. Returns names only, never the secret. */
function leaks(text: string, secrets: Uint8Array[]): string[] {
  const found: string[] = [];
  secrets.forEach((secret, i) => {
    for (const [name, form] of writtenForms(secret))
      if (form.length >= 16 && text.includes(form)) found.push(`secret ${i}: ${name}`);
  });
  return found;
}

describe("the detector itself works (otherwise a clean result means nothing)", () => {
  const secret = Uint8Array.from({ length: 32 }, (_, i) => (i * 7 + 3) % 256);
  it("finds the secret in every form it can be written in", () => {
    for (const [name, form] of writtenForms(secret)) {
      expect(leaks(`prefix ${form} suffix`, [secret]), name).not.toEqual([]);
    }
  });
  it("finds the secret inside a request body and a log line", () => {
    expect(leaks(JSON.stringify({ body: { k: toB64(secret) } }), [secret])).not.toEqual([]);
    expect(leaks(`console.log: seed=${toHex(secret)}`, [secret])).not.toEqual([]);
  });
  it("does not flag text that does not contain it", () => {
    expect(leaks("nothing to see here, device dev_00000000000000000000000000000001", [secret])).toEqual([]);
  });
});

// ------------------------------------------------------------------ the whole flow, with every channel recorded

const consoleMethods = ["log", "info", "warn", "error", "debug", "trace"] as const;

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("the whole SDK flow, with every channel recorded", () => {
  async function runEverything() {
    const spy = spiedSubtle();
    const recorded: string[] = [];
    const note = (label: string, value: unknown) =>
      recorded.push(`${label}: ${typeof value === "string" ? value : JSON.stringify(value)}`);

    // Record the browser's OWN network doors too, so a leak that bypasses the SDK's client is still seen.
    vi.stubGlobal("fetch", (async (...args: unknown[]) => {
      note("global fetch", args);
      return new Response(null, { status: 204 });
    }) as unknown as typeof fetch);
    vi.stubGlobal(
      "XMLHttpRequest",
      class {
        open(...a: unknown[]) {
          note("xhr open", a);
        }
        setRequestHeader(...a: unknown[]) {
          note("xhr header", a);
        }
        send(...a: unknown[]) {
          note("xhr send", a);
        }
      },
    );
    vi.stubGlobal(
      "WebSocket",
      class {
        constructor(...a: unknown[]) {
          note("websocket open", a);
        }
        send(...a: unknown[]) {
          note("websocket send", a);
        }
      },
    );

    for (const method of consoleMethods) {
      vi.spyOn(console, method).mockImplementation(
        (...args: unknown[]) => void note(`console.${method}`, args.map(String).join(" ")),
      );
    }

    const requests: Array<{ url: string; headers: unknown; body: unknown }> = [];
    const fakeFetch = (async (url: string, init: RequestInit) => {
      requests.push({ url, headers: init.headers, body: init.body });
      note("network", { url, headers: init.headers, body: init.body });
      if (String(url).endsWith("/pause") || String(url).endsWith("/resume")) return new Response(null, { status: 204 });
      if (String(url).includes("/fail")) throw new TypeError("connection refused");
      return new Response(
        JSON.stringify({ accepted: true, seq: 0, current_policy_outcome: "accept", duplicate: false }),
        { status: 200 },
      );
    }) as unknown as typeof fetch;

    // 1. provisioning: the request the page hands to the partner backend
    const registerRequests: unknown[] = [];
    const register: RegisterDevice = async (request) => {
      registerRequests.push(request);
      note("registration request", request);
      return { deviceId: "dev_00000000000000000000000000000001" };
    };
    const store = new MemoryKeyStore();
    const device = await provisionDevice({ register, store, subtle: spy.subtle });

    // 2. a real packet: built, signed, and sent through the real client
    const packet = buildPacket({
      sessionId: "cs_00000000000000000000000000000001",
      participantReference: "alice",
      deviceId: device.deviceId,
      seq: 0,
      intervalStartMs: 1000,
      intervalEndMs: 2000,
      result: {
        confidenceMilli: 900,
        reasonCodes: ["consistent_motion"],
        signalMilli: { temporal: 900 },
        modelVersion: "edge-0.1.0",
      },
    });
    const signature = await device.signer.sign(scoreCodecV1.encodeForSigning(packet));
    const body = scoreCodecV1.toWire(packet, signature);
    const client = new SessionClient({
      baseUrl: "https://api.example.test",
      sessionId: packet.sessionId,
      sdkToken: "skt_test",
      sdkVersion: "0.0.0",
      platform: "web",
      fetch: fakeFetch,
    });
    await client.sendScoreEvent(body);
    await client.sendBatch([body, body]);
    await client.pause("connectivity");
    await client.resume();

    // 3. the unhappy paths, whose error text could leak something
    const failing = new SessionClient({
      baseUrl: "https://api.example.test",
      sessionId: "cs_fail",
      sdkToken: "skt_test",
      sdkVersion: "0.0.0",
      platform: "web",
      fetch: fakeFetch,
    });
    const failures: unknown[] = [];
    await failing.sendScoreEvent(body).catch((e: unknown) => failures.push(e));
    const brokenBackend: RegisterDevice = async () => Promise.reject(new Error("backend down"));
    await provisionDevice({ register: brokenBackend, store: new MemoryKeyStore(), subtle: spy.subtle }).catch(
      (e: unknown) => failures.push(e),
    );
    for (const error of failures) {
      expect(error).toBeInstanceOf(SdkError);
      note("error", { text: String(error), all: JSON.stringify(error, Object.getOwnPropertyNames(error)) });
    }

    note(
      "the stored device record, as text",
      JSON.stringify({ alg: (await store.load())?.alg, deviceId: (await store.load())?.deviceId }),
    );
    return { spy, recorded: recorded.join("\n"), requests, registerRequests, device };
  }

  it("never writes the private key into a request, a log line, an error, or the registration request", async () => {
    const { spy, recorded } = await runEverything();
    expect(spy.secrets.length).toBeGreaterThan(0); // the test really did learn secrets to look for
    expect(leaks(recorded, spy.secrets)).toEqual([]);
  });

  it("does send the PUBLIC key and the signature (so we know the recording really captures traffic)", async () => {
    const { recorded, device, requests } = await runEverything();
    expect(recorded).toContain(device.publicKey);
    expect(requests.length).toBeGreaterThanOrEqual(4);
    expect(requests.some((r) => String(r.body).includes("device_signature"))).toBe(true);
  });

  it("asks WebCrypto for a NON-extractable key, only for signing and verifying", async () => {
    const { spy } = await runEverything();
    expect(spy.generateCalls.length).toBeGreaterThan(0);
    for (const call of spy.generateCalls) {
      expect(call.extractable).toBe(false);
      expect([...call.usages].sort()).toEqual(["sign", "verify"]);
    }
  });

  it("only ever exports a PUBLIC key, in raw form", async () => {
    const { spy } = await runEverything();
    expect(spy.exportCalls.length).toBeGreaterThan(0);
    for (const call of spy.exportCalls) expect(call).toEqual({ format: "raw", keyType: "public" });
  });

  it("the registration request holds one field, the public key", async () => {
    const { registerRequests, device } = await runEverything();
    expect(registerRequests[0]).toEqual({ public_key: device.publicKey });
  });
});
