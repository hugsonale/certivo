import { MemoryPacketBuffer } from "./buffer";
import type { ScoreWirePacket } from "./codec";
import { SdkError } from "./errors";
import { MemorySeqStore, type SeqStore } from "./seq-store";
import {
  MAX_BATCH_PACKETS,
  type PauseReason,
  type ScoreBatchResponse,
  type ScoreEventResponse,
} from "./session-client";

/** What the sender needs from the platform connection. `SessionClient` fits it; a test supplies a stand-in. */
export interface PacketTransport {
  sendScoreEvent(body: ScoreWirePacket): Promise<ScoreEventResponse>;
  sendBatch(packets: readonly ScoreWirePacket[]): Promise<ScoreBatchResponse>;
  pause(reason?: PauseReason): Promise<void>;
  resume(): Promise<void>;
}

export interface QueuedPacket {
  readonly seq: number;
  readonly body: ScoreWirePacket;
}

/** Why the sender gave up for good. The call carries on, but verification is no longer being reported. */
export type StopReason = "token_expired" | "token_invalid" | "session_ended" | "session_not_found" | "closed";

/** What happened to a packet the first time the sender dealt with it. */
export type SubmitOutcome =
  | { status: "sent"; duplicate: boolean }
  | { status: "buffered" }
  | { status: "dropped"; reason: string }
  | { status: "stopped"; reason: StopReason };

export type SenderEvent =
  | { type: "dropped"; seq: number; reason: string }
  | { type: "buffer_overflow"; dropped: number }
  | { type: "paused"; reason: PauseReason }
  | { type: "resumed" }
  | { type: "stopped"; reason: StopReason };

/**
 * Plain counters for the SDK's own health (TRD 2.6). They hold numbers and short code words only: never a score, a
 * participant, a token or anything about a picture. Nothing here is sent anywhere by this class (the platform has no
 * endpoint for it yet); the partner's app can read it or forward it.
 */
export interface SenderTelemetry {
  state: "idle" | "sending" | "backing_off" | "stopped";
  stoppedReason: StopReason | undefined;
  paused: boolean;
  /** Packets handed to the sender. */
  submitted: number;
  /** Packets the platform confirmed, counting a "duplicate" answer as confirmed. */
  confirmed: number;
  /** Confirmed straight away, on the first try, one packet at a time. */
  sentDirect: number;
  /** Confirmed after waiting in the buffer. */
  uploadedFromBuffer: number;
  /** Confirmed because the platform already had it (a safe retry, for example after a lost reply). */
  duplicatesAcknowledged: number;
  /** Attempts that failed for a reason worth trying again. */
  retries: number;
  rateLimited: number;
  batchesSent: number;
  batchSplits: number;
  bufferedNow: number;
  bufferHighWater: number;
  /** Thrown away because the buffer was full (the platform will disclose the hole as a gap). */
  droppedBufferFull: number;
  /** Refused by the platform for a reason that trying again cannot fix. */
  droppedRejected: number;
  rejectedByCode: Readonly<Record<string, number>>;
  /** Submitted again by the caller, or after the platform already had it, and ignored. */
  duplicateSubmits: number;
  pausesSent: number;
  resumesSent: number;
  implicitResumes: number;
  pauseFailures: number;
  consecutiveFailures: number;
  lastBackoffMs: number;
  lastSuccessAtMs: number | undefined;
}

export interface RetryPolicy {
  /** The first wait after a failure. Placeholder: not measured yet. */
  baseMs?: number;
  /** The longest wait between two tries. */
  maxMs?: number;
  /** The longest "Retry-After" from the platform that is obeyed. */
  maxRetryAfterMs?: number;
}

export interface PacketSenderOptions {
  transport: PacketTransport;
  sessionId: string;
  /** How many unsent packets to keep. When full the OLDEST is thrown away. Default 600 (about 30 minutes at 3 s). */
  capacity?: number;
  seqStore?: SeqStore;
  retry?: RetryPolicy;
  onEvent?(event: SenderEvent): void;
  /** For tests. */
  now?(): number;
  random?(): number;
  sleep?(ms: number, signal: AbortSignal): Promise<void>;
}

const DEFAULT_RETRY = { baseMs: 500, maxMs: 30_000, maxRetryAfterMs: 120_000 } as const;
const REMEMBERED_SETTLED = 2048;

const defaultSleep = (ms: number, signal: AbortSignal): Promise<void> =>
  new Promise((resolve) => {
    if (signal.aborted) return resolve();
    const timer = setTimeout(resolve, ms);
    signal.addEventListener(
      "abort",
      () => {
        clearTimeout(timer);
        resolve();
      },
      { once: true },
    );
  });

/** Server codes that mean "this packet can never be accepted, so stop trying". */
const PERMANENT_PACKET_CODES = new Set([
  "seq_conflict",
  "seq_out_of_order",
  "non_monotonic_interval",
  "invalid_interval",
  "timestamp_in_future",
  "non_canonical_payload",
  "validation_error",
  "invalid_device_signature",
]);

type Failure =
  | { kind: "retry"; retryAfterMs?: number; rateLimited?: boolean }
  | { kind: "split" }
  | { kind: "drop"; reason: string }
  | { kind: "stop"; reason: StopReason };

interface Meta {
  attempts: number;
  settled: boolean;
  settle(outcome: SubmitOutcome): void;
}

/**
 * Gets signed packets to the platform, in order, without ever sending a picture (a packet has none) and without ever
 * stalling the call. Everything it does follows Build Spec 0 section 4 and ADR 0014:
 *
 *  - ONE request at a time, oldest packet first, so the platform never sees a higher seq before a lower one.
 *  - A packet is tried straight away on the single-packet endpoint. If that fails for a reason worth retrying, it waits
 *    in a bounded buffer and every later packet queues behind it, so order is kept.
 *  - Waiting packets go up on the BATCH endpoint (at most 25, oldest first), because only the batch endpoint tells the
 *    platform the scores were late (so the attestation discloses the gap honestly).
 *  - Retries wait longer each time (with jitter), obey "Retry-After", and stop for good when the token is refused or the
 *    session has ended.
 *  - A reply of "duplicate" counts as success (the platform already had it). That is what makes a lost reply safe.
 *  - A packet the platform refuses for good (conflict, out of order, bad interval) is dropped and reported, never
 *    retried forever.
 */
export class PacketSender {
  private readonly buffer: MemoryPacketBuffer<QueuedPacket>;
  private readonly meta = new Map<number, Meta>();
  private readonly settledRecently = new Set<number>();
  private readonly seqStore: SeqStore;
  private readonly retry: Required<RetryPolicy>;
  private readonly now: () => number;
  private readonly random: () => number;
  private readonly sleep: (ms: number, signal: AbortSignal) => Promise<void>;
  private readonly wake = new AbortController();

  private pumping: Promise<void> | undefined;
  private stopped: StopReason | undefined;
  private backingOff = false;
  private nextAllowedAt = 0;
  private failures = 0;
  private batchLimit = MAX_BATCH_PACKETS;
  private paused = false;
  /** Goes up every time a packet gets through. */
  private successEpoch = 0;
  private seqNext: number;
  private lastDropCount = 0;
  private readonly rejected = new Map<string, number>();
  private t = {
    submitted: 0,
    confirmed: 0,
    sentDirect: 0,
    uploadedFromBuffer: 0,
    duplicatesAcknowledged: 0,
    retries: 0,
    rateLimited: 0,
    batchesSent: 0,
    batchSplits: 0,
    bufferHighWater: 0,
    droppedBufferFull: 0,
    droppedRejected: 0,
    duplicateSubmits: 0,
    pausesSent: 0,
    resumesSent: 0,
    implicitResumes: 0,
    pauseFailures: 0,
    lastBackoffMs: 0,
    lastSuccessAtMs: undefined as number | undefined,
  };

  constructor(private readonly options: PacketSenderOptions) {
    this.buffer = new MemoryPacketBuffer<QueuedPacket>(options.capacity ?? 600);
    this.seqStore = options.seqStore ?? new MemorySeqStore();
    this.retry = { ...DEFAULT_RETRY, ...options.retry };
    this.now = options.now ?? (() => Date.now());
    this.random = options.random ?? Math.random;
    this.sleep = options.sleep ?? defaultSleep;
    this.seqNext = this.seqStore.load(options.sessionId) ?? 0;
  }

  // ---------------------------------------------------------------- sequence numbers

  /** The seq for the next packet. Each call returns a new number and remembers it, so a reload carries on from here. */
  nextSeq(): number {
    const seq = this.seqNext++;
    this.seqStore.save(this.options.sessionId, this.seqNext);
    return seq;
  }

  // ---------------------------------------------------------------- sending

  /**
   * Hands over one signed packet. Resolves as soon as the packet has been dealt with once: "sent" (the platform has it),
   * "buffered" (it is waiting and will be retried), "dropped" (it can never be accepted) or "stopped". It never rejects.
   */
  submit(seq: number, body: ScoreWirePacket): Promise<SubmitOutcome> {
    if (this.stopped) return Promise.resolve({ status: "stopped", reason: this.stopped });
    if (this.meta.has(seq) || this.settledRecently.has(seq)) {
      this.t.duplicateSubmits++; // the same packet handed over twice: the first one is the one that counts
      return Promise.resolve({ status: "buffered" });
    }
    this.t.submitted++;
    return new Promise<SubmitOutcome>((resolve) => {
      this.meta.set(seq, {
        attempts: 0,
        settled: false,
        settle(outcome) {
          this.settled = true;
          resolve(outcome);
        },
      });
      this.buffer.push({ seq, body });
      this.t.bufferHighWater = Math.max(this.t.bufferHighWater, this.buffer.size);
      this.noticeOverflow();
      if (this.pumping)
        this.settle(seq, { status: "buffered" }); // earlier packets are still waiting: this one queues behind
      else this.startPump();
    });
  }

  /** Waits until nothing is left to send (true), or the time runs out or the sender stops (false). */
  async flush(timeoutMs = 10_000): Promise<boolean> {
    const deadline = this.now() + timeoutMs;
    while (this.buffer.size > 0 && !this.stopped && this.now() < deadline) {
      if (!this.pumping) this.startPump();
      await Promise.race([
        this.pumping,
        this.sleep(Math.min(100, Math.max(1, deadline - this.now())), this.wake.signal),
      ]);
    }
    return this.buffer.size === 0;
  }

  /** The call is over: stop for good and forget the seq. Packets still waiting are given up. */
  close(): void {
    this.seqStore.clear(this.options.sessionId);
    this.stop("closed");
  }

  // ---------------------------------------------------------------- pause and resume

  /**
   * Tells the platform that verification is unavailable right now, which opens a disclosed gap. Best effort: if the
   * platform cannot be reached it is NOT queued, because a pause that arrives late would put the gap in the wrong place.
   * (The platform finds a hole in the packets by itself, ADR 0014.) Returns true if the platform took it.
   */
  async pause(reason: PauseReason = "other"): Promise<boolean> {
    if (this.stopped || this.paused) return false;
    const epoch = this.successEpoch;
    try {
      await this.options.transport.pause(reason);
    } catch (error) {
      this.t.pauseFailures++;
      this.stopIfFatal(error);
      return false;
    }
    this.t.pausesSent++;
    // If a packet got through while the pause was on its way, that packet has already ended the pause (or is about to):
    // do not remember a pause that is over.
    if (this.successEpoch === epoch) {
      this.paused = true;
      this.emit({ type: "paused", reason });
    }
    return true;
  }

  /**
   * Closes the gap. A packet that goes through does this by itself (Build Spec 0 section 4), so calling it is only
   * needed when no packet is about to follow. Returns true if the platform took it.
   */
  async resume(): Promise<boolean> {
    if (this.stopped || !this.paused) return false;
    try {
      await this.options.transport.resume();
    } catch (error) {
      this.stopIfFatal(error);
      return false;
    }
    this.paused = false;
    this.t.resumesSent++;
    this.emit({ type: "resumed" });
    return true;
  }

  // ---------------------------------------------------------------- telemetry

  telemetry(): SenderTelemetry {
    return {
      state: this.stopped ? "stopped" : this.backingOff ? "backing_off" : this.pumping ? "sending" : "idle",
      stoppedReason: this.stopped,
      paused: this.paused,
      submitted: this.t.submitted,
      confirmed: this.t.confirmed,
      sentDirect: this.t.sentDirect,
      uploadedFromBuffer: this.t.uploadedFromBuffer,
      duplicatesAcknowledged: this.t.duplicatesAcknowledged,
      retries: this.t.retries,
      rateLimited: this.t.rateLimited,
      batchesSent: this.t.batchesSent,
      batchSplits: this.t.batchSplits,
      bufferedNow: this.buffer.size,
      bufferHighWater: this.t.bufferHighWater,
      droppedBufferFull: this.t.droppedBufferFull,
      droppedRejected: this.t.droppedRejected,
      rejectedByCode: Object.fromEntries(this.rejected),
      duplicateSubmits: this.t.duplicateSubmits,
      pausesSent: this.t.pausesSent,
      resumesSent: this.t.resumesSent,
      implicitResumes: this.t.implicitResumes,
      pauseFailures: this.t.pauseFailures,
      consecutiveFailures: this.failures,
      lastBackoffMs: this.t.lastBackoffMs,
      lastSuccessAtMs: this.t.lastSuccessAtMs,
    };
  }

  // ---------------------------------------------------------------- the sending loop

  private startPump(): void {
    this.pumping = this.pump().finally(() => {
      this.pumping = undefined;
      this.backingOff = false;
    });
  }

  private async pump(): Promise<void> {
    while (!this.stopped && this.buffer.size > 0) {
      const wait = this.nextAllowedAt - this.now();
      if (wait > 0) {
        this.backingOff = true;
        await this.sleep(wait, this.wake.signal);
        continue;
      }
      this.backingOff = false;
      await this.attempt();
    }
  }

  private async attempt(): Promise<void> {
    const batch = this.buffer.peek(Math.min(this.batchLimit, MAX_BATCH_PACKETS));
    const first = batch[0];
    if (!first) return;
    const fresh = batch.length === 1 && (this.meta.get(first.seq)?.attempts ?? 0) === 0;
    for (const packet of batch) {
      const meta = this.meta.get(packet.seq);
      if (meta) meta.attempts++;
    }
    try {
      if (fresh) {
        const reply = await this.options.transport.sendScoreEvent(first.body);
        this.confirm(first.seq, reply.duplicate, true);
        this.buffer.ackUpTo(first.seq);
        this.succeeded();
      } else {
        this.t.batchesSent++;
        const reply = await this.options.transport.sendBatch(batch.map((p) => p.body));
        this.handleBatchReply(batch, reply);
      }
    } catch (error) {
      this.handleFailure(error, batch);
    }
  }

  private handleBatchReply(batch: readonly QueuedPacket[], reply: ScoreBatchResponse): void {
    const byIndex = new Map(reply.results.map((r) => [r.index, r]));
    let handledPrefix = 0;
    for (const [index, packet] of batch.entries()) {
      const result = byIndex.get(index);
      if (!result) break; // the platform did not answer for this packet: it stays, and is tried again
      if (result.accepted || result.duplicate) {
        this.confirm(packet.seq, result.duplicate, false);
      } else {
        const code = result.error?.code ?? "not_accepted";
        if (code === "session_not_active") {
          this.stop("session_ended");
          return;
        }
        this.drop(packet.seq, code);
      }
      handledPrefix = index + 1;
    }
    const last = batch[handledPrefix - 1];
    if (last) this.buffer.ackUpTo(last.seq);
    if (handledPrefix < batch.length) {
      this.handleFailure(
        new SdkError("server_error", "The platform did not answer for every packet."),
        batch.slice(handledPrefix),
      );
      return;
    }
    this.succeeded();
  }

  private handleFailure(error: unknown, batch: readonly QueuedPacket[]): void {
    const failure = this.classify(error, batch.length);
    switch (failure.kind) {
      case "stop":
        this.stop(failure.reason);
        return;
      case "split":
        this.t.batchSplits++;
        this.batchLimit = Math.max(1, Math.floor(batch.length / 2));
        return; // try again at once, with a smaller batch
      case "drop": {
        const first = batch[0];
        if (first) {
          this.drop(first.seq, failure.reason);
          this.buffer.ackUpTo(first.seq);
        }
        this.batchLimit = 1;
        return;
      }
      case "retry": {
        for (const packet of batch) this.settle(packet.seq, { status: "buffered" });
        this.failures++;
        this.t.retries++;
        if (failure.rateLimited) this.t.rateLimited++;
        const ceiling = Math.min(this.retry.maxMs, this.retry.baseMs * 2 ** Math.min(this.failures - 1, 20));
        const jittered = ceiling / 2 + (this.random() * ceiling) / 2; // between half and all of the ceiling
        const asked = Math.min(failure.retryAfterMs ?? 0, this.retry.maxRetryAfterMs);
        this.t.lastBackoffMs = Math.round(Math.max(jittered, asked));
        this.nextAllowedAt = this.now() + this.t.lastBackoffMs;
        return;
      }
    }
  }

  private classify(error: unknown, batchSize: number): Failure {
    if (!(error instanceof SdkError)) return { kind: "retry" }; // unexpected: wait and try again rather than lose a packet
    switch (error.code) {
      case "network_error":
      case "server_error":
        return { kind: "retry" };
      case "rate_limited":
        return {
          kind: "retry",
          rateLimited: true,
          ...(error.retryAfterS !== undefined ? { retryAfterMs: error.retryAfterS * 1000 } : {}),
        };
      case "token_expired":
        return { kind: "stop", reason: "token_expired" };
      case "token_invalid":
        // A bad packet signature also arrives as a 401, but it condemns that packet, not the whole session.
        return error.serverCode === "invalid_device_signature"
          ? { kind: "drop", reason: "invalid_device_signature" }
          : { kind: "stop", reason: "token_invalid" };
      case "payload_too_large":
        return batchSize > 1 ? { kind: "split" } : { kind: "drop", reason: "payload_too_large" };
      case "rejected": {
        const code = error.serverCode ?? "rejected";
        if (code === "session_not_active") return { kind: "stop", reason: "session_ended" };
        if (code === "session_not_found") return { kind: "stop", reason: "session_not_found" };
        // One bad packet in a batch makes the platform refuse the whole request: halve it until the bad one is alone.
        if (batchSize > 1 && (code === "validation_error" || code === "non_canonical_payload"))
          return { kind: "split" };
        return { kind: "drop", reason: PERMANENT_PACKET_CODES.has(code) ? code : `rejected:${code}` };
      }
      default:
        return { kind: "retry" };
    }
  }

  // ---------------------------------------------------------------- bookkeeping

  private confirm(seq: number, duplicate: boolean, direct: boolean): void {
    const meta = this.meta.get(seq);
    const waited = !direct || (meta?.settled ?? false);
    this.t.confirmed++;
    if (duplicate) this.t.duplicatesAcknowledged++;
    if (waited) this.t.uploadedFromBuffer++;
    else this.t.sentDirect++;
    this.settle(seq, { status: "sent", duplicate });
    this.forget(seq);
  }

  private drop(seq: number, reason: string): void {
    this.t.droppedRejected++;
    this.rejected.set(reason, (this.rejected.get(reason) ?? 0) + 1);
    this.settle(seq, { status: "dropped", reason });
    this.forget(seq);
    this.emit({ type: "dropped", seq, reason });
  }

  private succeeded(): void {
    this.failures = 0;
    this.successEpoch++;
    this.nextAllowedAt = 0;
    this.t.lastSuccessAtMs = this.now();
    this.batchLimit = Math.min(MAX_BATCH_PACKETS, this.batchLimit * 2);
    if (this.paused) {
      this.paused = false; // a packet that gets through closes the gap on the platform's side too
      this.t.implicitResumes++;
      this.emit({ type: "resumed" });
    }
  }

  private settle(seq: number, outcome: SubmitOutcome): void {
    const meta = this.meta.get(seq);
    if (meta && !meta.settled) meta.settle(outcome);
  }

  private forget(seq: number): void {
    this.meta.delete(seq);
    this.settledRecently.add(seq);
    if (this.settledRecently.size > REMEMBERED_SETTLED) {
      const oldest = this.settledRecently.values().next().value;
      if (oldest !== undefined) this.settledRecently.delete(oldest);
    }
  }

  /** The buffer throws the oldest packet away when full. Tell whoever was waiting on those, and count them. */
  private noticeOverflow(): void {
    const total = this.buffer.droppedCount;
    if (total === this.lastDropCount) return;
    const newlyDropped = total - this.lastDropCount;
    this.lastDropCount = total;
    this.t.droppedBufferFull += newlyDropped;
    const oldestKept = this.buffer.peek(1)[0]?.seq ?? Number.POSITIVE_INFINITY;
    for (const seq of [...this.meta.keys()]) {
      if (seq < oldestKept) {
        this.settle(seq, { status: "dropped", reason: "buffer_full" });
        this.forget(seq);
      }
    }
    this.emit({ type: "buffer_overflow", dropped: newlyDropped });
  }

  private stopIfFatal(error: unknown): void {
    const failure = this.classify(error, 1);
    if (failure.kind === "stop") this.stop(failure.reason);
  }

  private stop(reason: StopReason): void {
    if (this.stopped) return;
    this.stopped = reason;
    this.wake.abort();
    for (const seq of [...this.meta.keys()]) this.settle(seq, { status: "stopped", reason });
    this.meta.clear();
    this.emit({ type: "stopped", reason });
  }

  private emit(event: SenderEvent): void {
    try {
      this.options.onEvent?.(event);
    } catch {
      // a listener's mistake must never stop packets
    }
  }
}
