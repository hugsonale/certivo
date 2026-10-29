/**
 * The Certivo Web SDK: the one entry point partners import. It wires the packages together:
 *   capture (frames) -> inference (scores, in a worker) -> core (packets, signing, sending), with ui (the indicator).
 */
export * from "@certivo/sdk-capture";
export * from "@certivo/sdk-core";
export * from "@certivo/sdk-inference";
export type * from "@certivo/sdk-types";
export * from "@certivo/sdk-ui";
export { type IntervalOutcome, type PipelineDeps, VerificationPipeline, type WaitingPacket } from "./pipeline";

export const SDK_VERSION = "0.0.0";
