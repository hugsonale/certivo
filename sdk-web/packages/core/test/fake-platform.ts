import type { ScoreWirePacket } from "../src/codec";
import { SdkError } from "../src/errors";
import type { PacketTransport } from "../src/sender";
import {
  MAX_BATCH_PACKETS,
  type PauseReason,
  type ScoreBatchResponse,
  type ScoreEventResponse,
} from "../src/session-client";

/**
 * A stand-in for the platform that follows the replay and ordering rules of Build Spec 0 section 4 and ADR 0014, and
 * can break in the ways a network and a server break. The tests use it to check what the sender does, not what it
 * says it does.
 */
export type Fault =
  | "lose_request" //       the request never arrives (offline, dropped)
  | "lose_response" //      the platform takes the packet, but the reply is lost
  | "duplicate_delivery" // the network delivers the same request twice
  | "server_error" //       a 5xx before anything is stored
  | { rateLimit: number } //   429 with Retry-After (seconds)
  | { error: SdkError }; //    any other answer, before anything is stored

export type CallKind = "single" | "batch" | "pause" | "resume";
export interface PlatformOptions {
  /** Decides what goes wrong with call number `n` (counted per kind, from 1). */
  plan?(call: { n: number; kind: CallKind }): Fault | undefined;
  /** A batch with more packets than this is refused with 413. */
  maxBatch?: number;
}

interface Wire {
  seq: number;
  device_signature: string;
  interval_start_ms: number;
  interval_end_ms: number;
  malformed?: boolean;
}

const wire = (body: ScoreWirePacket) => body as unknown as Wire;

const refusal = (code: string, status = 409) => new SdkError("rejected", code, { status, serverCode: code });

export class FakePlatform implements PacketTransport {
  /** The seq of every packet the platform took, in the order it took them. */
  readonly accepted: number[] = [];
  readonly stored = new Map<number, string>();
  /** Every call the sender made, lost ones included: its kind, the seqs it carried and when (fake clock). */
  readonly log: Array<{ kind: CallKind; seqs: number[]; at: number }> = [];
  readonly calls = { single: 0, batch: 0, pause: 0, resume: 0 };
  readonly pauseReasons: PauseReason[] = [];
  /** How many times the platform refused something the SDK must never send. */
  sawOutOfOrder = 0;
  sawConflict = 0;
  status: "active" | "paused" | "ended" = "active";
  /** While true every request is lost. */
  down = false;
  plan: PlatformOptions["plan"];
  maxBatch: number;
  private lastSeq = -1;
  private lastEnd = -1;

  constructor(options: PlatformOptions = {}) {
    this.plan = options.plan;
    this.maxBatch = options.maxBatch ?? MAX_BATCH_PACKETS;
  }

  async sendScoreEvent(body: ScoreWirePacket): Promise<ScoreEventResponse> {
    const n = ++this.calls.single;
    const fault = this.fault(n, "single");
    this.record("single", [wire(body).seq]);
    this.beforeProcessing(fault);
    const result = this.process(body);
    if (fault === "duplicate_delivery") this.safely(() => this.process(body));
    if (fault === "lose_response") throw new SdkError("network_error", "reply lost");
    return result;
  }

  async sendBatch(packets: readonly ScoreWirePacket[]): Promise<ScoreBatchResponse> {
    const n = ++this.calls.batch;
    const fault = this.fault(n, "batch");
    this.record(
      "batch",
      packets.map((p) => wire(p).seq),
    );
    if (packets.length < 1 || packets.length > MAX_BATCH_PACKETS) throw new RangeError("a batch holds 1 to 25 packets");
    this.beforeProcessing(fault);
    if (packets.length > this.maxBatch) throw new SdkError("payload_too_large", "too big", { status: 413 });
    if (packets.some((p) => wire(p).malformed)) throw refusal("validation_error", 422);

    const run = () =>
      packets.map((packet, index) => {
        try {
          const ok = this.process(packet);
          return { index, ...ok, error: null };
        } catch (error) {
          const code = (error as SdkError).serverCode ?? "rejected";
          return {
            index,
            accepted: false,
            seq: wire(packet).seq,
            current_policy_outcome: null,
            duplicate: false,
            error: { code, message: code },
          };
        }
      });
    const results = run();
    if (fault === "duplicate_delivery") run();
    if (fault === "lose_response") throw new SdkError("network_error", "reply lost");
    return {
      results,
      accepted_count: results.filter((r) => r.accepted && !r.duplicate).length,
      duplicate_count: results.filter((r) => r.duplicate).length,
      rejected_count: results.filter((r) => r.error).length,
      gaps_recorded: 0,
    };
  }

  async pause(reason: PauseReason = "other"): Promise<void> {
    const n = ++this.calls.pause;
    this.beforeProcessing(this.fault(n, "pause"));
    this.record("pause", []);
    this.pauseReasons.push(reason);
    if (this.status === "active") this.status = "paused";
  }

  async resume(): Promise<void> {
    const n = ++this.calls.resume;
    this.beforeProcessing(this.fault(n, "resume"));
    this.record("resume", []);
    if (this.status === "paused") this.status = "active";
  }

  /** Pretend this seq was already stored with a different signature (to provoke `seq_conflict`). */
  preload(seq: number, signature: string): void {
    this.stored.set(seq, signature);
  }

  private fault(n: number, kind: CallKind): Fault | undefined {
    return this.down ? "lose_request" : this.plan?.({ n, kind });
  }

  private record(kind: CallKind, seqs: number[]): void {
    this.log.push({ kind, seqs, at: Date.now() });
  }

  /** Faults that happen before the platform stores anything. */
  private beforeProcessing(fault: Fault | undefined): void {
    if (fault === "lose_request") throw new SdkError("network_error", "request lost");
    if (fault === "server_error") throw new SdkError("server_error", "boom", { status: 500 });
    if (fault && typeof fault === "object") {
      if ("rateLimit" in fault)
        throw new SdkError("rate_limited", "slow down", { status: 429, retryAfterS: fault.rateLimit });
      throw fault.error;
    }
  }

  private safely(work: () => void): void {
    try {
      work();
    } catch {
      // the second delivery's answer is thrown away
    }
  }

  /** Build Spec 0 section 4, "Replay and ordering rules". */
  private process(body: ScoreWirePacket): {
    accepted: boolean;
    seq: number;
    current_policy_outcome: string;
    duplicate: boolean;
  } {
    const packet = wire(body);
    if (this.status === "ended") throw refusal("session_not_active");
    const known = this.stored.get(packet.seq);
    if (known !== undefined) {
      if (known === packet.device_signature) {
        return { accepted: true, seq: packet.seq, current_policy_outcome: "accept", duplicate: true };
      }
      this.sawConflict++;
      throw refusal("seq_conflict");
    }
    if (packet.seq < this.lastSeq) {
      this.sawOutOfOrder++;
      throw refusal("seq_out_of_order");
    }
    if (packet.interval_end_ms < this.lastEnd) throw refusal("non_monotonic_interval");
    this.stored.set(packet.seq, packet.device_signature);
    this.accepted.push(packet.seq);
    this.lastSeq = packet.seq;
    this.lastEnd = packet.interval_end_ms;
    if (this.status === "paused") this.status = "active"; // a valid packet while paused resumes the session
    return { accepted: true, seq: packet.seq, current_policy_outcome: "accept", duplicate: false };
  }
}

/** A packet body shaped like Build Spec 0 section 4. */
export function packet(seq: number, extra: Record<string, unknown> = {}): ScoreWirePacket {
  return {
    v: 1,
    participant_reference: "alice",
    seq,
    interval_start_ms: seq * 1000,
    interval_end_ms: seq * 1000 + 1000,
    device_signature: `sig${seq}`,
    ...extra,
  } as unknown as ScoreWirePacket;
}
