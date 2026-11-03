import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { PacketSender } from "../src/sender";
import { FakePlatform, type Fault, packet } from "./fake-platform";

/**
 * P0-25: "Fault-injection tests: lost, duplicated and reordered packets handled per Spec 0."
 *
 * The cases in sender.test.ts each break one thing. This file breaks everything at once, at random, many times over, and
 * checks the promises that must hold whatever happens:
 *
 *   1. The platform NEVER sees a packet out of order or in conflict (so it never has to refuse the SDK).
 *   2. Every packet is accepted exactly once (a lost reply or a double delivery never makes it count twice).
 *   3. Packets are accepted in seq order.
 *   4. Once the network is healthy, nothing is left waiting.
 *   5. Every packet handed over is accounted for: confirmed, dropped, or (only when the buffer overflowed) lost and counted.
 *
 * The random numbers are seeded, so a failure names its seed and can be replayed exactly.
 */
beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(5_000_000);
});
afterEach(() => {
  vi.useRealTimers();
});

/** A small, fast, repeatable random number generator (mulberry32). */
function seeded(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function pickFault(random: () => number): Fault | undefined {
  const roll = random();
  if (roll < 0.5) return undefined;
  if (roll < 0.64) return "lose_request";
  if (roll < 0.76) return "lose_response";
  if (roll < 0.86) return "duplicate_delivery";
  if (roll < 0.94) return "server_error";
  return { rateLimit: 1 + Math.floor(random() * 3) };
}

interface Run {
  platform: FakePlatform;
  sender: PacketSender;
  submitted: number;
}

async function chaos(seed: number, packets: number, capacity: number, outageChance: number): Promise<Run> {
  const random = seeded(seed);
  const platform = new FakePlatform({ plan: () => pickFault(random) });
  const sender = new PacketSender({ transport: platform, sessionId: "sess_chaos", capacity, random: seeded(seed + 1) });
  let outageEndsAt = 0;
  for (let seq = 0; seq < packets; seq++) {
    if (Date.now() >= outageEndsAt && random() < outageChance) outageEndsAt = Date.now() + 5_000 + random() * 40_000;
    platform.down = Date.now() < outageEndsAt;
    void sender.submit(seq, packet(seq));
    await vi.advanceTimersByTimeAsync(1_000); // one packet a second
  }
  // the network comes back for good
  platform.down = false;
  platform.plan = undefined;
  await vi.advanceTimersByTimeAsync(10 * 60_000);
  return { platform, sender, submitted: packets };
}

const range = (n: number, from = 0) => Array.from({ length: n }, (_, i) => i + from);

describe("every promise holds under random faults (25 seeds)", () => {
  for (let seed = 1; seed <= 25; seed++) {
    it(`seed ${seed}: all packets arrive exactly once, in order, and nothing is left waiting`, async () => {
      const { platform, sender, submitted } = await chaos(seed, 150, 600, 0.04);
      const t = sender.telemetry();
      expect(platform.sawOutOfOrder, "platform saw a packet out of order").toBe(0);
      expect(platform.sawConflict, "platform saw a conflicting packet").toBe(0);
      expect(platform.accepted, "accepted exactly 0..n-1, once each, in order").toEqual(range(submitted));
      expect(t.bufferedNow).toBe(0);
      expect(t.droppedRejected).toBe(0);
      expect(t.droppedBufferFull).toBe(0);
      expect(t.confirmed).toBe(submitted);
      expect(t.state).toBe("idle");
      expect(vi.getTimerCount(), "no timer left running").toBe(0);
    });
  }
});

describe("the same, with a buffer too small for the outages (25 seeds)", () => {
  for (let seed = 101; seed <= 125; seed++) {
    it(`seed ${seed}: nothing arrives out of order or twice, and every packet is accounted for`, async () => {
      const { platform, sender, submitted } = await chaos(seed, 200, 12, 0.08);
      const t = sender.telemetry();
      expect(platform.sawOutOfOrder).toBe(0);
      expect(platform.sawConflict).toBe(0);
      const sorted = [...platform.accepted].sort((a, b) => a - b);
      expect(platform.accepted, "accepted in seq order").toEqual(sorted);
      expect(new Set(platform.accepted).size, "no packet accepted twice").toBe(platform.accepted.length);
      expect(t.bufferedNow).toBe(0);
      expect(t.confirmed + t.droppedBufferFull + t.droppedRejected, "every packet is accounted for").toBe(submitted);
      // A reply can be lost after the platform stored a packet, and the overflow can then throw the packet away before the
      // retry confirms it. So the platform may hold MORE than the sender confirmed, but only by packets the sender dropped.
      expect(platform.accepted.length).toBeGreaterThanOrEqual(t.confirmed);
      expect(platform.accepted.length - t.confirmed).toBeLessThanOrEqual(t.droppedBufferFull);
    });
  }
});

describe("it really does injure the sender (the faults above are not decoration)", () => {
  it("a typical run is full of retries, duplicates and backlogs", async () => {
    const { platform, sender } = await chaos(7, 150, 600, 0.04);
    const t = sender.telemetry();
    expect(t.retries).toBeGreaterThan(10);
    expect(t.duplicatesAcknowledged).toBeGreaterThan(0);
    expect(t.batchesSent).toBeGreaterThan(0);
    expect(t.bufferHighWater).toBeGreaterThan(5);
    expect(platform.log.length).toBeGreaterThan(50);
  });
});
