import type { FrameSource } from "@certivo/sdk-capture";
import {
  buildPacket,
  type DeviceSigner,
  MAX_INTERVAL_MS,
  type MemoryPacketBuffer,
  type PacketCodec,
  type PacketSender,
  type PauseReason,
  type ScorePacket,
  type ScoreWirePacket,
  SdkError,
} from "@certivo/sdk-core";
import type { Scorer } from "@certivo/sdk-inference";
import type { PacketRole, ScoreResult } from "@certivo/sdk-types";

export interface WaitingPacket {
  readonly seq: number;
  readonly body: ScoreWirePacket;
}

export interface PipelineDeps {
  source: FrameSource;
  scorer: Scorer;
  signer: DeviceSigner;
  codec: PacketCodec;
  /**
   * The way packets leave (P0-25): numbering, retries, the buffer, batch upload and pause and resume. Use this.
   * Only a packet body ever reaches it; a frame never does.
   */
  sender?: PacketSender;
  /** The older, simpler way (P0-21): send one body, keep failures in a buffer. Used only when there is no `sender`. */
  send?(body: ScoreWirePacket): Promise<unknown>;
  buffer?: MemoryPacketBuffer<WaitingPacket>;
  /**
   * After this many intervals in a row with no score, tell the platform verification is unavailable (a disclosed gap).
   * 0 turns it off. Needs a `sender`. Placeholder: not measured yet.
   */
  pauseAfterMissedIntervals?: number;
  clock(): number;
  sessionId: string;
  participantReference: string;
  deviceId: string;
  intervalMs: number;
  /**
   * "self" (default). "observer" (receiver-side scoring, D-02) is held back: the codec refuses it until the platform's
   * packet format has a role field (docs/adr/0022).
   */
  role?: PacketRole;
  subjectParticipantReference?: string;
}

export type IntervalOutcome =
  | { status: "sent"; seq: number }
  | { status: "buffered"; seq: number; reason: string }
  | { status: "no_score"; reason: string }
  /** The platform refused this packet for good (it can never be accepted). It was not retried. */
  | { status: "dropped"; seq: number; reason: string }
  /** The sender has given up for good (token refused, session ended). Scoring carries on; nothing is reported. */
  | { status: "stopped"; seq: number; reason: string };

const DEFAULT_PAUSE_AFTER_MISSED = 3;

/**
 * One turn of the verification loop: take a frame, score it, discard the frame, then build, sign and send
 * a packet. The shape of this function is the architecture in miniature (docs/adr/0021):
 *
 *   capture -> inference ... (the frame stops here, and is closed) ... -> core
 *
 * Only a ScoreResult (numbers and code words) passes from inference to core.
 */
export class VerificationPipeline {
  private seq = 0;
  private lastEndMs: number | undefined;
  private missedInARow = 0;
  private pausedByPipeline = false;

  constructor(private readonly deps: PipelineDeps) {
    if (!deps.sender && !(deps.send && deps.buffer)) {
      throw new TypeError("a pipeline needs a sender (or, the older way, both send and buffer)");
    }
  }

  async runInterval(): Promise<IntervalOutcome> {
    const { source, scorer, signer, codec, clock, sender } = this.deps;
    const endMs = clock();
    // A packet covers the time since the last one. If scoring failed for a while, that time is NOT stretched over the
    // failure (it would claim a score for minutes that had none, and an interval may not exceed 60 s): the new interval
    // starts a fresh interval back, and the hole is left for the platform to disclose as a gap.
    const startMs =
      this.lastEndMs !== undefined && endMs - this.lastEndMs <= this.deps.intervalMs * 1.5
        ? this.lastEndMs
        : endMs - Math.min(this.deps.intervalMs, MAX_INTERVAL_MS);

    const frame = await source.grab();
    let result: ScoreResult;
    try {
      result = await scorer.score(frame.image);
    } catch (error) {
      // No score means no packet: the SDK never sends a decision without a score and an explanation.
      this.noteMissedInterval(error);
      return { status: "no_score", reason: (error as Error).message };
    } finally {
      frame.close(); // the frame is gone before anything else happens
    }

    this.missedInARow = 0;
    this.pausedByPipeline = false; // the packet below ends any pause on the platform's side as well
    this.lastEndMs = endMs;
    const seq = sender ? sender.nextSeq() : this.seq++;
    const packet: ScorePacket = buildPacket({
      sessionId: this.deps.sessionId,
      participantReference: this.deps.participantReference,
      deviceId: this.deps.deviceId,
      seq,
      intervalStartMs: startMs,
      intervalEndMs: endMs,
      result,
      ...(this.deps.role !== undefined ? { role: this.deps.role } : {}),
      ...(this.deps.subjectParticipantReference !== undefined
        ? { subjectParticipantReference: this.deps.subjectParticipantReference }
        : {}),
    });
    const signature = await signer.sign(codec.encodeForSigning(packet));
    const body = codec.toWire(packet, signature);

    if (sender) {
      const outcome = await sender.submit(seq, body);
      switch (outcome.status) {
        case "sent":
          return { status: "sent", seq };
        case "buffered":
          return { status: "buffered", seq, reason: "waiting to upload" };
        case "dropped":
          return { status: "dropped", seq, reason: outcome.reason };
        case "stopped":
          return { status: "stopped", seq, reason: outcome.reason };
      }
    }

    const { send, buffer } = this.deps;
    if (!send || !buffer) throw new TypeError("a pipeline needs a sender (or, the older way, both send and buffer)");
    try {
      await send(body);
      return { status: "sent", seq };
    } catch (error) {
      if (error instanceof SdkError && error.code === "network_error") {
        buffer.push({ seq, body });
        return { status: "buffered", seq, reason: error.message };
      }
      throw error;
    }
  }

  /** Counts intervals with no score and, after enough in a row, declares verification unavailable (once per streak). */
  private noteMissedInterval(error: unknown): void {
    const { sender } = this.deps;
    this.missedInARow++;
    const limit = this.deps.pauseAfterMissedIntervals ?? DEFAULT_PAUSE_AFTER_MISSED;
    if (!sender || limit < 1 || this.pausedByPipeline || this.missedInARow < limit) return;
    this.pausedByPipeline = true;
    const code = (error as { code?: unknown } | null)?.code;
    const reason: PauseReason = code === "model_not_loaded" ? "model_unavailable" : "sdk_error";
    void sender.pause(reason); // not awaited: a slow network must not delay the next interval. It never throws.
  }
}
