import type { FrameSource } from "@certivo/sdk-capture";
import {
  buildPacket,
  type DeviceSigner,
  type MemoryPacketBuffer,
  type PacketCodec,
  type ScorePacket,
  SdkError,
} from "@certivo/sdk-core";
import type { Scorer } from "@certivo/sdk-inference";
import type { PacketRole, ScoreResult } from "@certivo/sdk-types";

export interface WaitingPacket {
  readonly seq: number;
  readonly body: unknown;
}

export interface PipelineDeps {
  source: FrameSource;
  scorer: Scorer;
  signer: DeviceSigner;
  codec: PacketCodec;
  /** Sends one packet body. Only the body leaves; a frame never reaches this function. */
  send(body: unknown): Promise<unknown>;
  buffer: MemoryPacketBuffer<WaitingPacket>;
  clock(): number;
  sessionId: string;
  participantRef: string;
  deviceId: string;
  intervalMs: number;
  /** "self" (default) or "observer" (receiver-side scoring, D-02, built in P1-10). */
  role?: PacketRole;
  subjectParticipantRef?: string;
}

export type IntervalOutcome =
  | { status: "sent"; seq: number }
  | { status: "buffered"; seq: number; reason: string }
  | { status: "no_score"; reason: string };

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

  constructor(private readonly deps: PipelineDeps) {}

  async runInterval(): Promise<IntervalOutcome> {
    const { source, scorer, signer, codec, buffer, clock } = this.deps;
    const endMs = clock();
    const startMs = this.lastEndMs ?? endMs - this.deps.intervalMs;

    const frame = await source.grab();
    let result: ScoreResult;
    try {
      result = await scorer.score(frame.image);
    } catch (error) {
      // No score means no packet: the SDK never sends a decision without a score and an explanation.
      return { status: "no_score", reason: (error as Error).message };
    } finally {
      frame.close(); // the frame is gone before anything else happens
    }

    this.lastEndMs = endMs;
    const seq = this.seq++;
    const packet: ScorePacket = buildPacket({
      sessionId: this.deps.sessionId,
      participantRef: this.deps.participantRef,
      deviceId: this.deps.deviceId,
      seq,
      intervalStartMs: startMs,
      intervalEndMs: endMs,
      result,
      alg: signer.alg,
      ...(this.deps.role !== undefined ? { role: this.deps.role } : {}),
      ...(this.deps.subjectParticipantRef !== undefined
        ? { subjectParticipantRef: this.deps.subjectParticipantRef }
        : {}),
    });
    const signature = await signer.sign(codec.encodeForSigning(packet));
    const body = codec.toWire(packet, signature);

    try {
      await this.deps.send(body);
      return { status: "sent", seq };
    } catch (error) {
      if (error instanceof SdkError && error.code === "network_error") {
        buffer.push({ seq, body });
        return { status: "buffered", seq, reason: error.message };
      }
      throw error;
    }
  }
}
