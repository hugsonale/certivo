/**
 * The arithmetic of the overhead harness (guide P0-27). Pure functions with no browser and no Node-only code, so
 * they are unit-tested (test/overhead-stats.test.ts) and the numbers in a report can be trusted to be added up right.
 */

export interface Summary {
  n: number;
  min: number;
  p50: number;
  p95: number;
  max: number;
  mean: number;
}

/** The value below which `p` percent of the (sorted) values fall, by linear steps between neighbours. */
export function percentile(sorted: readonly number[], p: number): number {
  if (sorted.length === 0) return Number.NaN;
  if (sorted.length === 1) return sorted[0] as number;
  const rank = (p / 100) * (sorted.length - 1);
  const low = Math.floor(rank);
  const high = Math.ceil(rank);
  const a = sorted[low] as number;
  const b = sorted[high] as number;
  return a + (b - a) * (rank - low);
}

export function summarize(values: readonly number[]): Summary {
  const sorted = [...values].filter(Number.isFinite).sort((a, b) => a - b);
  if (sorted.length === 0)
    return { n: 0, min: Number.NaN, p50: Number.NaN, p95: Number.NaN, max: Number.NaN, mean: Number.NaN };
  return {
    n: sorted.length,
    min: sorted[0] as number,
    p50: percentile(sorted, 50),
    p95: percentile(sorted, 95),
    max: sorted[sorted.length - 1] as number,
    mean: sorted.reduce((a, b) => a + b, 0) / sorted.length,
  };
}

export const median = (values: readonly number[]): number => summarize(values).p50;

export interface ProcessCpu {
  id: number;
  type: string;
  /** Cumulative CPU seconds, over all threads of the process, since it started. */
  cpuTime: number;
}

export interface CpuDelta {
  totalS: number;
  byType: Record<string, number>;
}

/**
 * CPU seconds used between two readings of every browser process. A process in both readings counts the difference;
 * one that appeared in between counts all it has used; one that ended in between is lost (its last stretch is unknown).
 */
export function processCpuDelta(before: readonly ProcessCpu[], after: readonly ProcessCpu[]): CpuDelta {
  const earlier = new Map(before.map((p) => [p.id, p.cpuTime]));
  const byType: Record<string, number> = {};
  let totalS = 0;
  for (const p of after) {
    const used = Math.max(0, p.cpuTime - (earlier.get(p.id) ?? 0));
    totalS += used;
    byType[p.type] = (byType[p.type] ?? 0) + used;
  }
  return { totalS, byType };
}

/** CPU use as a percentage of ONE core (so 100 means one core fully busy, 250 means two and a half). */
export const cpuPercent = (cpuSeconds: number, wallSeconds: number): number =>
  wallSeconds > 0 ? (cpuSeconds / wallSeconds) * 100 : Number.NaN;

/** CPU milliseconds used per interval. */
export const cpuMsPerInterval = (cpuSeconds: number, intervals: number): number =>
  intervals > 0 ? (cpuSeconds * 1000) / intervals : Number.NaN;

/**
 * The cost the SDK adds: for repeat number i, the run WITH the SDK minus the run WITHOUT it (they alternate, so slow
 * drift on the machine hits both). Summarised over the repeats.
 */
export function pairedOverhead(without: readonly number[], withSdk: readonly number[]): Summary {
  const pairs = Math.min(without.length, withSdk.length);
  const diffs: number[] = [];
  for (let i = 0; i < pairs; i++) diffs.push((withSdk[i] as number) - (without[i] as number));
  return summarize(diffs);
}

/** Bits per second from bytes over a time. */
export const kbps = (bytes: number, seconds: number): number =>
  seconds > 0 ? (bytes * 8) / 1000 / seconds : Number.NaN;

export const mb = (bytes: number): number => bytes / 1024 / 1024;

/**
 * The harness checks itself: a worker that burns a KNOWN amount of CPU per interval must show up as about that much
 * extra CPU. If it does not, the CPU numbers cannot be trusted.
 */
export function calibrationCheck(
  expectedMsPerInterval: number,
  measuredMsPerInterval: number,
): { ok: boolean; toleranceMs: number } {
  const toleranceMs = Math.max(expectedMsPerInterval * 0.5, 8);
  return { ok: Math.abs(measuredMsPerInterval - expectedMsPerInterval) <= toleranceMs, toleranceMs };
}
