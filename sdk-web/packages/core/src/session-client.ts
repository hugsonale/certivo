import { SdkError } from "./errors";

export interface SessionClientOptions {
  /** For example "https://api.certivo.example" (no trailing slash needed). */
  baseUrl: string;
  sessionId: string;
  /** The per-session SDK token the partner backend received when it started the session. */
  sdkToken: string;
  sdkVersion: string;
  /** For example "web". */
  platform: string;
  fetch?: typeof fetch;
  timeoutMs?: number;
}

/**
 * Talks to the platform's SDK endpoints (platform/app/routers/sessions.py). It only handles the HTTP
 * side: the body is built and signed elsewhere (a PacketCodec, from P0-22). It never logs the token and
 * never puts it anywhere except the Authorization header.
 */
export class SessionClient {
  private readonly fetchImpl: typeof fetch;
  private readonly base: string;

  constructor(private readonly options: SessionClientOptions) {
    this.fetchImpl = options.fetch ?? globalThis.fetch.bind(globalThis);
    this.base = `${options.baseUrl.replace(/\/+$/, "")}/internal/v1/sessions/continuous/${encodeURIComponent(options.sessionId)}`;
  }

  sendScoreEvent(body: unknown, idempotencyKey?: string): Promise<unknown> {
    return this.post("/score-events", body, idempotencyKey);
  }

  sendBatch(packets: readonly unknown[]): Promise<unknown> {
    return this.post("/score-events/batch", { packets });
  }

  async pause(reason?: string): Promise<void> {
    await this.post("/pause", reason === undefined ? {} : { reason });
  }

  async resume(): Promise<void> {
    await this.post("/resume", undefined);
  }

  private async post(path: string, body: unknown, idempotencyKey?: string): Promise<unknown> {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), this.options.timeoutMs ?? 10_000);
    const headers: Record<string, string> = {
      Authorization: `Bearer ${this.options.sdkToken}`,
      "Certivo-SDK-Version": this.options.sdkVersion,
      "Certivo-SDK-Platform": this.options.platform,
    };
    if (body !== undefined) headers["Content-Type"] = "application/json";
    if (idempotencyKey) headers["Idempotency-Key"] = idempotencyKey;
    let response: Response;
    try {
      response = await this.fetchImpl(`${this.base}${path}`, {
        method: "POST",
        headers,
        body: body === undefined ? null : JSON.stringify(body),
        signal: controller.signal,
        credentials: "omit",
        cache: "no-store",
      });
    } catch {
      throw new SdkError("network_error", "Could not reach the Certivo platform.");
    } finally {
      clearTimeout(timer);
    }
    if (!response.ok) throw await toError(response);
    if (response.status === 204) return undefined;
    try {
      return await response.json();
    } catch {
      return undefined;
    }
  }
}

async function toError(response: Response): Promise<SdkError> {
  let serverCode: string | undefined;
  let requestId = response.headers.get("X-Request-ID") ?? undefined;
  let message = `The platform answered ${response.status}.`;
  try {
    const parsed = (await response.json()) as { error?: { code?: string; message?: string; request_id?: string } };
    serverCode = parsed.error?.code;
    message = parsed.error?.message ?? message;
    requestId = parsed.error?.request_id ?? requestId;
  } catch {
    // not JSON: keep the generic message
  }
  const retry = Number(response.headers.get("Retry-After"));
  const details = {
    status: response.status,
    ...(serverCode !== undefined ? { serverCode } : {}),
    ...(requestId !== undefined ? { requestId } : {}),
    ...(Number.isFinite(retry) && retry > 0 ? { retryAfterS: retry } : {}),
  };
  if (response.status === 401) {
    return new SdkError(serverCode === "session_token_expired" ? "token_expired" : "token_invalid", message, details);
  }
  if (response.status === 429) return new SdkError("rate_limited", message, details);
  if (response.status === 413) return new SdkError("payload_too_large", message, details);
  if (response.status >= 500) return new SdkError("server_error", message, details);
  return new SdkError("rejected", message, details);
}
