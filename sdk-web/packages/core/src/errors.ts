export type SdkErrorCode =
  | "network_error" //      could not reach the server (offline, timeout)
  | "token_expired" //      the session token has run out
  | "token_invalid" //      the session token is not accepted
  | "rate_limited" //       the server asked us to slow down (see retryAfterS)
  | "payload_too_large" //  the request body was refused as too big
  | "server_error" //       the server failed (5xx)
  | "rejected" //           the server refused the request (other 4xx); see serverCode
  | "invalid_packet" //     the packet could not be built (a rule in packet.ts was broken)
  | "capability_missing" // the browser cannot do something the SDK needs
  | "not_implemented"; //   a later step in the build guide supplies this

/** The one error type the SDK throws, so callers can switch on `code`. It never contains a secret. */
export class SdkError extends Error {
  override readonly name = "SdkError";
  readonly code: SdkErrorCode;
  readonly status: number | undefined;
  /** The server's own error code (for example "seq_conflict"), when there is one. */
  readonly serverCode: string | undefined;
  /** The server's request ID: quote it to support so the matching log lines can be found. */
  readonly requestId: string | undefined;
  readonly retryAfterS: number | undefined;

  constructor(
    code: SdkErrorCode,
    message: string,
    details: { status?: number; serverCode?: string; requestId?: string; retryAfterS?: number } = {},
  ) {
    super(message);
    this.code = code;
    this.status = details.status;
    this.serverCode = details.serverCode;
    this.requestId = details.requestId;
    this.retryAfterS = details.retryAfterS;
  }
}
