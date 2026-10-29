import { describe, expect, it } from "vitest";
import { MAX_BATCH_PACKETS, type ScoreWirePacket, SdkError, SessionClient } from "../src/index";

const TOKEN = "skt_UnitTestToken0123456789abcdefABCDEF";

interface Call {
  url: string;
  init: RequestInit;
}

function clientWith(respond: (call: Call) => Response | Promise<Response>, extra: { timeoutMs?: number } = {}) {
  const calls: Call[] = [];
  const fakeFetch = (async (url: string, init: RequestInit) => {
    const call = { url, init };
    calls.push(call);
    return respond(call);
  }) as unknown as typeof fetch;
  const client = new SessionClient({
    baseUrl: "https://api.example.test/",
    sessionId: "cs_abc 123",
    sdkToken: TOKEN,
    sdkVersion: "0.0.0",
    platform: "web",
    fetch: fakeFetch,
    ...extra,
  });
  return { client, calls };
}

const wire = (seq: number): ScoreWirePacket => ({
  v: 1,
  participant_reference: "alice",
  device_id: "dev_00000000000000000000000000000001",
  seq,
  interval_start_ms: 1000,
  interval_end_ms: 2000,
  confidence_milli: 900,
  model_version: "edge-0.1.0",
  explanation: { reason_codes: ["consistent_motion"], signal_milli: {} },
  device_signature: "x".repeat(86),
});

const json = (status: number, body: unknown, headers: Record<string, string> = {}) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json", ...headers } });

const failureOf = async (promise: Promise<unknown>): Promise<SdkError> => {
  try {
    await promise;
  } catch (error) {
    expect(error).toBeInstanceOf(SdkError);
    return error as SdkError;
  }
  throw new Error("expected the request to fail");
};

describe("what the client sends", () => {
  it("posts to the session's score-events endpoint with the token ONLY in the Authorization header", async () => {
    const { client, calls } = clientWith(() => json(200, { accepted: true }));
    await client.sendScoreEvent(wire(0), "idem-1");
    const [call] = calls;
    expect(call?.url).toBe("https://api.example.test/internal/v1/sessions/continuous/cs_abc%20123/score-events");
    const headers = call?.init.headers as Record<string, string>;
    expect(headers.Authorization).toBe(`Bearer ${TOKEN}`);
    expect(headers["Certivo-SDK-Version"]).toBe("0.0.0");
    expect(headers["Certivo-SDK-Platform"]).toBe("web");
    expect(headers["Idempotency-Key"]).toBe("idem-1");
    expect(call?.url).not.toContain(TOKEN);
    expect(String(call?.init.body)).not.toContain(TOKEN);
    expect(call?.init.credentials).toBe("omit"); // never send the partner site's cookies
  });

  it("uses the batch, pause and resume endpoints", async () => {
    const { client, calls } = clientWith(() => new Response(null, { status: 204 }));
    await client.sendBatch([wire(1), wire(2)]);
    await client.pause("connectivity");
    await client.resume();
    expect(calls.map((c) => c.url.split("/continuous/cs_abc%20123")[1])).toEqual([
      "/score-events/batch",
      "/pause",
      "/resume",
    ]);
    expect(JSON.parse(String(calls[0]?.init.body))).toEqual({ packets: [wire(1), wire(2)] });
    expect(JSON.parse(String(calls[1]?.init.body))).toEqual({ reason: "connectivity" });
    expect(calls[2]?.init.body).toBeNull();
    // pause without a reason says "other", the platform's default
    await client.pause();
    expect(JSON.parse(String(calls[3]?.init.body))).toEqual({ reason: "other" });
  });

  it("returns nothing for a 204", async () => {
    const { client } = clientWith(() => new Response(null, { status: 204 }));
    await expect(client.pause()).resolves.toBeUndefined();
  });
});

describe("batches", () => {
  it(`hold 1 to ${MAX_BATCH_PACKETS} packets, as the platform requires`, () => {
    const { client } = clientWith(() => json(200, {}));
    expect(() => client.sendBatch([])).toThrow(RangeError);
    expect(() => client.sendBatch(Array.from({ length: MAX_BATCH_PACKETS + 1 }, (_, i) => wire(i)))).toThrow(
      RangeError,
    );
  });
});

describe("how the client explains a failure", () => {
  const cases: Array<[string, number, unknown, Record<string, string>, string]> = [
    [
      "an expired token",
      401,
      { error: { code: "session_token_expired", message: "expired", request_id: "req_1" } },
      {},
      "token_expired",
    ],
    ["a wrong token", 401, { error: { code: "invalid_session_token", message: "no" } }, {}, "token_invalid"],
    [
      "rate limiting",
      429,
      { error: { code: "rate_limited", message: "slow down" } },
      { "Retry-After": "7" },
      "rate_limited",
    ],
    ["a body that is too big", 413, { error: { code: "payload_too_large", message: "big" } }, {}, "payload_too_large"],
    [
      "a server error",
      500,
      { error: { code: "internal_error", message: "oops", request_id: "req_9" } },
      {},
      "server_error",
    ],
    ["a refused packet", 409, { error: { code: "seq_conflict", message: "dup" } }, {}, "rejected"],
  ];
  for (const [name, status, body, headers, code] of cases) {
    it(`maps ${name} to '${code}'`, async () => {
      const { client } = clientWith(() => json(status, body, headers));
      const error = await failureOf(client.sendScoreEvent(wire(0)));
      expect(error.code).toBe(code);
      expect(error.status).toBe(status);
      expect(error.message).not.toContain(TOKEN);
    });
  }

  it("keeps the server's code, request ID and retry delay for the caller", async () => {
    const { client } = clientWith(() =>
      json(429, { error: { code: "rate_limited", message: "slow", request_id: "req_77" } }, { "Retry-After": "7" }),
    );
    const error = await failureOf(client.sendScoreEvent(wire(0)));
    expect(error.serverCode).toBe("rate_limited");
    expect(error.requestId).toBe("req_77");
    expect(error.retryAfterS).toBe(7);
  });

  it("copes with an error that is not JSON", async () => {
    const { client } = clientWith(() => new Response("<html>bad gateway</html>", { status: 502 }));
    expect((await failureOf(client.sendScoreEvent(wire(0)))).code).toBe("server_error");
  });

  it("calls an unreachable server a network error, without leaking the token", async () => {
    const { client } = clientWith(() => {
      throw new TypeError(`failed to fetch with ${TOKEN}`);
    });
    const error = await failureOf(client.sendScoreEvent(wire(0)));
    expect(error.code).toBe("network_error");
    expect(error.message).not.toContain(TOKEN);
  });

  it("gives up on a server that never answers", async () => {
    const hang = ({ init }: Call) =>
      new Promise<Response>((_, reject) =>
        init.signal?.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError"))),
      );
    const { client } = clientWith(hang, { timeoutMs: 20 });
    expect((await failureOf(client.sendScoreEvent(wire(0)))).code).toBe("network_error");
  });
});
