import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { SdkError } from "../src/errors";
import { PacketSender, type PacketSenderOptions, type SenderEvent, type SubmitOutcome } from "../src/sender";
import { MemorySeqStore, TabSeqStore, type TabStorage } from "../src/seq-store";
import { FakePlatform, packet } from "./fake-platform";

/** Time is fake: `advance(ms)` runs every wait the sender is sitting in. */
beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(1_000_000);
});
afterEach(() => {
  vi.useRealTimers();
});
const advance = (ms: number) => vi.advanceTimersByTimeAsync(ms);

function setup(platform = new FakePlatform(), options: Partial<PacketSenderOptions> = {}) {
  const events: SenderEvent[] = [];
  // random() = 1 makes every wait exactly its ceiling: 500, 1000, 2000 ...
  const sender = new PacketSender({
    transport: platform,
    sessionId: "sess_1",
    random: () => 1,
    onEvent: (e) => events.push(e),
    ...options,
  });
  return { platform, sender, events };
}

/** Starts a submit and lets the first attempt finish. */
async function submit(sender: PacketSender, seq: number, extra: Record<string, unknown> = {}): Promise<SubmitOutcome> {
  const pending = sender.submit(seq, packet(seq, extra));
  await advance(0);
  return pending;
}

describe("sending", () => {
  it("sends a fresh packet straight away on the single-packet endpoint", async () => {
    const { platform, sender } = setup();
    expect(await submit(sender, 0)).toEqual({ status: "sent", duplicate: false });
    expect(platform.log.map((l) => l.kind)).toEqual(["single"]);
    expect(platform.accepted).toEqual([0]);
    expect(sender.telemetry()).toMatchObject({ submitted: 1, confirmed: 1, sentDirect: 1, retries: 0, state: "idle" });
  });

  it("keeps order: while one packet waits, newer ones queue behind it and nothing overtakes it", async () => {
    const platform = new FakePlatform({
      plan: ({ kind, n }) => (kind === "single" && n === 1 ? "lose_request" : undefined),
    });
    const { sender } = setup(platform);
    expect(await submit(sender, 0)).toEqual({ status: "buffered" });
    expect(await submit(sender, 1)).toEqual({ status: "buffered" });
    expect(await submit(sender, 2)).toEqual({ status: "buffered" });
    expect(platform.calls.single).toBe(1); // nothing was sent ahead of packet 0
    await advance(500);
    expect(platform.accepted).toEqual([0, 1, 2]);
    expect(platform.sawOutOfOrder).toBe(0);
  });

  it("sends waiting packets on the BATCH endpoint, oldest first, even when only one is waiting (that is how late scores are disclosed)", async () => {
    const platform = new FakePlatform({
      plan: ({ kind, n }) => (kind === "single" && n === 1 ? "lose_request" : undefined),
    });
    const { sender } = setup(platform);
    await submit(sender, 0);
    await advance(500);
    expect(platform.log.map((l) => [l.kind, l.seqs])).toEqual([
      ["single", [0]],
      ["batch", [0]],
    ]);
    expect(sender.telemetry()).toMatchObject({ confirmed: 1, uploadedFromBuffer: 1, sentDirect: 0 });
  });

  it("uploads a long backlog 25 at a time, in order", async () => {
    const platform = new FakePlatform();
    platform.down = true;
    const { sender } = setup(platform);
    for (let seq = 0; seq < 60; seq++) await submit(sender, seq);
    platform.down = false;
    await advance(60_000);
    expect(platform.accepted).toEqual(Array.from({ length: 60 }, (_, i) => i));
    const delivered = platform.log.filter((l) => l.kind === "batch" && l.seqs.length > 0).map((l) => l.seqs.length);
    expect(Math.max(...delivered)).toBe(25);
    expect(sender.telemetry().bufferedNow).toBe(0);
  });
});

describe("lost, duplicated and reordered packets (Build Spec 0 section 4)", () => {
  it("a LOST REQUEST is retried and accepted once", async () => {
    const platform = new FakePlatform({
      plan: ({ n, kind }) => (kind === "single" && n === 1 ? "lose_request" : undefined),
    });
    const { sender } = setup(platform);
    await submit(sender, 0);
    await advance(500);
    expect(platform.accepted).toEqual([0]);
    expect(sender.telemetry()).toMatchObject({ retries: 1, confirmed: 1, duplicatesAcknowledged: 0 });
  });

  it("a LOST REPLY is safe: the platform already has it, says duplicate, and that counts as success", async () => {
    const platform = new FakePlatform({
      plan: ({ n, kind }) => (kind === "single" && n === 1 ? "lose_response" : undefined),
    });
    const { sender } = setup(platform);
    await submit(sender, 0);
    await advance(500);
    expect(platform.accepted).toEqual([0]); // stored once, not twice
    expect(sender.telemetry()).toMatchObject({ confirmed: 1, duplicatesAcknowledged: 1, droppedRejected: 0 });
    expect(platform.sawConflict).toBe(0);
  });

  it("a DUPLICATE DELIVERY by the network changes nothing", async () => {
    const platform = new FakePlatform({ plan: () => "duplicate_delivery" });
    const { sender } = setup(platform);
    expect(await submit(sender, 0)).toEqual({ status: "sent", duplicate: false });
    expect(await submit(sender, 1)).toEqual({ status: "sent", duplicate: false });
    expect(platform.accepted).toEqual([0, 1]);
  });

  it("the same packet handed over twice is only sent once", async () => {
    const { platform, sender } = setup();
    await submit(sender, 0);
    expect(await submit(sender, 0)).toEqual({ status: "buffered" });
    expect(platform.calls.single).toBe(1);
    expect(sender.telemetry().duplicateSubmits).toBe(1);
  });

  it("packets handed over OUT OF ORDER while waiting are still uploaded in order", async () => {
    const platform = new FakePlatform();
    platform.down = true;
    const { sender } = setup(platform);
    for (const seq of [0, 1, 3, 2]) await submit(sender, seq);
    platform.down = false;
    await advance(60_000);
    expect(platform.accepted).toEqual([0, 1, 2, 3]);
    expect(platform.sawOutOfOrder).toBe(0);
  });

  it("a packet that arrives after a higher one was already accepted is refused for good, dropped and reported (never retried)", async () => {
    const { platform, sender, events } = setup();
    await submit(sender, 5);
    expect(await submit(sender, 4)).toEqual({ status: "dropped", reason: "seq_out_of_order" });
    await advance(60_000);
    expect(platform.calls.single).toBe(2); // no third try
    expect(sender.telemetry()).toMatchObject({ droppedRejected: 1, rejectedByCode: { seq_out_of_order: 1 } });
    expect(events).toContainEqual({ type: "dropped", seq: 4, reason: "seq_out_of_order" });
  });

  it("a conflicting packet inside a batch is dropped and its neighbours are kept (no whole-batch retry)", async () => {
    const platform = new FakePlatform();
    platform.down = true;
    const { sender } = setup(platform);
    for (const seq of [0, 1, 2]) await submit(sender, seq);
    platform.preload(1, "someone-elses-signature");
    platform.down = false;
    await advance(60_000);
    expect(platform.accepted).toEqual([0, 2]);
    expect(platform.sawConflict).toBe(1);
    expect(platform.calls.batch).toBeLessThanOrEqual(2);
    expect(sender.telemetry()).toMatchObject({
      confirmed: 2,
      droppedRejected: 1,
      rejectedByCode: { seq_conflict: 1 },
      bufferedNow: 0,
    });
  });

  it("a network drop in the MIDDLE of a backlog carries on from the right place", async () => {
    const platform = new FakePlatform({
      plan: ({ kind, n }) => (kind === "batch" && n === 2 ? "lose_request" : undefined),
    });
    platform.down = true;
    const { sender } = setup(platform);
    for (let seq = 0; seq < 60; seq++) await submit(sender, seq);
    platform.down = false;
    await advance(120_000);
    expect(platform.accepted).toEqual(Array.from({ length: 60 }, (_, i) => i));
    expect(sender.telemetry().duplicatesAcknowledged).toBe(0);
  });

  it("a lost reply to a whole BATCH is safe: the retry comes back all 'duplicate'", async () => {
    const platform = new FakePlatform({
      plan: ({ kind, n }) => (kind === "batch" && n === 1 ? "lose_response" : undefined),
    });
    platform.down = true;
    const { sender } = setup(platform);
    for (let seq = 0; seq < 10; seq++) await submit(sender, seq);
    platform.down = false;
    await advance(60_000);
    expect(platform.accepted).toEqual(Array.from({ length: 10 }, (_, i) => i));
    expect(sender.telemetry()).toMatchObject({ confirmed: 10, duplicatesAcknowledged: 10 });
  });
});

describe("a batch the platform refuses as a whole", () => {
  it("is split in half until it fits (413)", async () => {
    const platform = new FakePlatform({ maxBatch: 4 });
    platform.down = true;
    const { sender } = setup(platform);
    for (let seq = 0; seq < 10; seq++) await submit(sender, seq);
    platform.down = false;
    await advance(60_000);
    expect(platform.accepted).toEqual(Array.from({ length: 10 }, (_, i) => i));
    expect(sender.telemetry().batchSplits).toBeGreaterThanOrEqual(2);
  });

  it("is halved until the one malformed packet is alone, and only that packet is dropped (422)", async () => {
    const platform = new FakePlatform();
    platform.down = true;
    const { sender } = setup(platform);
    for (let seq = 0; seq < 6; seq++) await submit(sender, seq, seq === 3 ? { malformed: true } : {});
    platform.down = false;
    await advance(60_000);
    expect(platform.accepted).toEqual([0, 1, 2, 4, 5]);
    expect(sender.telemetry()).toMatchObject({
      droppedRejected: 1,
      rejectedByCode: { validation_error: 1 },
      bufferedNow: 0,
    });
  });
});

describe("retrying", () => {
  it("waits longer each time, up to a ceiling", async () => {
    const platform = new FakePlatform();
    platform.down = true;
    const { sender } = setup(platform);
    await submit(sender, 0);
    await advance(300_000);
    const gaps = platform.log.map((l, i, all) => (i === 0 ? 0 : l.at - (all[i - 1]?.at ?? 0))).slice(1, 9);
    expect(gaps).toEqual([500, 1000, 2000, 4000, 8000, 16000, 30000, 30000]);
    expect(sender.telemetry()).toMatchObject({ state: "backing_off", consecutiveFailures: expect.any(Number) });
  });

  it("jitters: a wait is between half the ceiling and all of it", async () => {
    const platform = new FakePlatform();
    platform.down = true;
    const { sender } = setup(platform, { random: () => 0 });
    await submit(sender, 0);
    await advance(100_000);
    const gaps = platform.log.map((l, i, all) => (i === 0 ? 0 : l.at - (all[i - 1]?.at ?? 0))).slice(1, 6);
    expect(gaps).toEqual([250, 500, 1000, 2000, 4000]);
  });

  it("obeys Retry-After when the platform asks for longer than its own wait", async () => {
    const platform = new FakePlatform({
      plan: ({ kind, n }) => (kind === "single" && n === 1 ? { rateLimit: 20 } : undefined),
    });
    const { sender } = setup(platform);
    await submit(sender, 0);
    await advance(19_999);
    expect(platform.calls.batch).toBe(0); // not before it was allowed
    await advance(1);
    expect(platform.accepted).toEqual([0]);
    expect(sender.telemetry().rateLimited).toBe(1);
  });

  it("does not let a huge Retry-After freeze it for ever", async () => {
    const platform = new FakePlatform({
      plan: ({ kind, n }) => (kind === "single" && n === 1 ? { rateLimit: 86_400 } : undefined),
    });
    const { sender } = setup(platform);
    await submit(sender, 0);
    await advance(120_000);
    expect(platform.accepted).toEqual([0]);
  });

  it("treats a server error like an outage and recovers", async () => {
    const platform = new FakePlatform({ plan: ({ n }) => (n <= 2 ? "server_error" : undefined) });
    const { sender } = setup(platform);
    await submit(sender, 0);
    await advance(10_000);
    expect(platform.accepted).toEqual([0]);
  });

  it("a success resets the wait to the start", async () => {
    const platform = new FakePlatform();
    platform.down = true;
    const { sender } = setup(platform);
    await submit(sender, 0);
    await advance(8_000); // several failures in
    platform.down = false;
    await advance(30_000);
    expect(sender.telemetry().consecutiveFailures).toBe(0);
  });

  it("a buffer that overflows throws away the OLDEST packets, counts them, and says so", async () => {
    const platform = new FakePlatform();
    platform.down = true;
    const { sender, events } = setup(platform, { capacity: 10 });
    for (let seq = 0; seq < 25; seq++) await submit(sender, seq);
    expect(sender.telemetry()).toMatchObject({ droppedBufferFull: 15, bufferedNow: 10, bufferHighWater: 10 });
    expect(events.filter((e) => e.type === "buffer_overflow").length).toBeGreaterThan(0);
    platform.down = false;
    await advance(120_000);
    expect(platform.accepted).toEqual(Array.from({ length: 10 }, (_, i) => i + 15));
  });
});

describe("giving up for good", () => {
  it("stops when the token has expired, and tells the caller", async () => {
    const platform = new FakePlatform({
      plan: () => ({ error: new SdkError("token_expired", "expired", { status: 401 }) }),
    });
    const { sender, events } = setup(platform);
    expect(await submit(sender, 0)).toEqual({ status: "stopped", reason: "token_expired" });
    expect(await submit(sender, 1)).toEqual({ status: "stopped", reason: "token_expired" });
    const calls = platform.log.length;
    await advance(120_000);
    expect(platform.log.length).toBe(calls); // not one more request
    expect(events).toContainEqual({ type: "stopped", reason: "token_expired" });
    expect(sender.telemetry()).toMatchObject({ state: "stopped", stoppedReason: "token_expired" });
  });

  it("stops when the session has ended", async () => {
    const { platform, sender } = setup();
    platform.status = "ended";
    expect(await submit(sender, 0)).toEqual({ status: "stopped", reason: "session_ended" });
  });

  it("stops while a backlog is being uploaded, and settles the waiting packets", async () => {
    const platform = new FakePlatform();
    platform.down = true;
    const { sender } = setup(platform);
    await submit(sender, 0);
    const second = sender.submit(1, packet(1));
    platform.down = false;
    platform.status = "ended";
    await advance(60_000);
    expect(await second).toEqual({ status: "buffered" });
    expect(sender.telemetry().state).toBe("stopped");
  });

  it("a bad packet SIGNATURE (also a 401) drops that packet but does not stop the session", async () => {
    const bad = new SdkError("token_invalid", "bad signature", { status: 401, serverCode: "invalid_device_signature" });
    const platform = new FakePlatform({
      plan: ({ n, kind }) => (kind === "single" && n === 1 ? { error: bad } : undefined),
    });
    const { sender } = setup(platform);
    expect(await submit(sender, 0)).toEqual({ status: "dropped", reason: "invalid_device_signature" });
    expect(await submit(sender, 1)).toEqual({ status: "sent", duplicate: false });
  });

  it("close() settles everything, wakes any wait, and sends nothing more", async () => {
    const platform = new FakePlatform();
    platform.down = true;
    const { sender } = setup(platform);
    await submit(sender, 0);
    const waiting = sender.submit(1, packet(1));
    sender.close();
    expect(await waiting).toEqual({ status: "buffered" });
    const calls = platform.log.length;
    await advance(120_000);
    expect(platform.log.length).toBe(calls);
    expect(vi.getTimerCount()).toBe(0);
    expect(await sender.submit(2, packet(2))).toEqual({ status: "stopped", reason: "closed" });
  });
});

describe("flush", () => {
  it("is true once everything has gone up", async () => {
    const platform = new FakePlatform({
      plan: ({ kind, n }) => (kind === "single" && n === 1 ? "lose_request" : undefined),
    });
    const { sender } = setup(platform);
    await submit(sender, 0);
    const done = sender.flush(10_000);
    await advance(2_000);
    expect(await done).toBe(true);
  });

  it("is false when the time runs out", async () => {
    const platform = new FakePlatform();
    platform.down = true;
    const { sender } = setup(platform);
    await submit(sender, 0);
    const done = sender.flush(3_000);
    await advance(5_000);
    expect(await done).toBe(false);
  });
});

describe("pause and resume", () => {
  it("pause tells the platform once, with the reason", async () => {
    const { platform, sender, events } = setup();
    expect(await sender.pause("model_unavailable")).toBe(true);
    expect(await sender.pause("model_unavailable")).toBe(false); // already paused: no second call
    expect(platform.calls.pause).toBe(1);
    expect(platform.pauseReasons).toEqual(["model_unavailable"]);
    expect(platform.status).toBe("paused");
    expect(events).toContainEqual({ type: "paused", reason: "model_unavailable" });
    expect(sender.telemetry()).toMatchObject({ paused: true, pausesSent: 1 });
  });

  it("a packet that gets through ends the pause (the platform does the same)", async () => {
    const { platform, sender, events } = setup();
    await sender.pause("sdk_error");
    await submit(sender, 0);
    expect(platform.status).toBe("active");
    expect(sender.telemetry()).toMatchObject({ paused: false, implicitResumes: 1, resumesSent: 0 });
    expect(events).toContainEqual({ type: "resumed" });
  });

  it("resume() closes the gap when no packet is about to follow, and only when paused", async () => {
    const { platform, sender } = setup();
    expect(await sender.resume()).toBe(false);
    expect(platform.calls.resume).toBe(0);
    await sender.pause("other");
    expect(await sender.resume()).toBe(true);
    expect(platform.status).toBe("active");
    expect(sender.telemetry()).toMatchObject({ paused: false, resumesSent: 1 });
  });

  it("if the platform cannot be reached the pause is NOT queued (a late pause would put the gap in the wrong place)", async () => {
    const platform = new FakePlatform();
    platform.down = true;
    const { sender } = setup(platform);
    expect(await sender.pause("connectivity")).toBe(false);
    expect(sender.telemetry()).toMatchObject({ paused: false, pauseFailures: 1 });
    platform.down = false;
    await advance(120_000);
    expect(platform.calls.pause).toBe(1); // never tried again on its own
  });

  it("a pause still on its way when a packet gets through is not remembered as current", async () => {
    const platform = new FakePlatform();
    let finishPause: () => void = () => {};
    const realPause = platform.pause.bind(platform);
    platform.pause = (reason) =>
      new Promise<void>((resolve) => {
        finishPause = () => void realPause(reason).then(resolve);
      });
    const { sender } = setup(platform);
    const pausing = sender.pause("sdk_error");
    await submit(sender, 0); // a packet gets through first
    finishPause();
    expect(await pausing).toBe(true);
    expect(sender.telemetry().paused).toBe(false);
    // so the NEXT pause is not refused as "already paused"
    platform.pause = FakePlatform.prototype.pause.bind(platform);
    expect(await sender.pause("sdk_error")).toBe(true);
  });

  it("a refused token during a pause stops the sender", async () => {
    const platform = new FakePlatform({
      plan: ({ kind }) => (kind === "pause" ? { error: new SdkError("token_expired", "x") } : undefined),
    });
    const { sender } = setup(platform);
    expect(await sender.pause("other")).toBe(false);
    expect(sender.telemetry().state).toBe("stopped");
  });
});

describe("sequence numbers", () => {
  it("count up from 0, one for each call", () => {
    const { sender } = setup();
    expect([sender.nextSeq(), sender.nextSeq(), sender.nextSeq()]).toEqual([0, 1, 2]);
  });

  it("carry on after a reload when a store remembers them, and are forgotten when the call is closed", () => {
    const store = new MemorySeqStore();
    const first = setup(undefined, { seqStore: store }).sender;
    first.nextSeq();
    first.nextSeq();
    const afterReload = setup(undefined, { seqStore: store }).sender;
    expect(afterReload.nextSeq()).toBe(2);
    afterReload.close();
    expect(setup(undefined, { seqStore: store }).sender.nextSeq()).toBe(0);
  });

  it("a different session starts at 0", () => {
    const store = new MemorySeqStore();
    setup(undefined, { seqStore: store, sessionId: "sess_a" }).sender.nextSeq();
    expect(setup(undefined, { seqStore: store, sessionId: "sess_b" }).sender.nextSeq()).toBe(0);
  });
});

describe("TabSeqStore", () => {
  const fakeStorage = (): TabStorage & { data: Map<string, string> } => {
    const data = new Map<string, string>();
    return {
      data,
      getItem: (k) => data.get(k) ?? null,
      setItem: (k, v) => void data.set(k, v),
      removeItem: (k) => void data.delete(k),
    };
  };

  it("keeps one whole number per session and nothing else", () => {
    const storage = fakeStorage();
    const store = new TabSeqStore(storage);
    store.save("sess_1", 7);
    expect([...storage.data.values()]).toEqual(["7"]);
    expect(store.load("sess_1")).toBe(7);
    store.clear("sess_1");
    expect(store.load("sess_1")).toBeUndefined();
  });

  it("ignores anything that is not a sensible number", () => {
    const storage = fakeStorage();
    const store = new TabSeqStore(storage);
    for (const junk of ["abc", "-1", "1.5", "99999999999", "", "1e3", " 4"]) {
      storage.data.set("certivo.next_seq.sess_1", junk);
      expect(store.load("sess_1"), junk).toBeUndefined();
    }
  });

  it("swallows a storage that throws (full, blocked, private mode)", () => {
    const broken: TabStorage = {
      getItem: () => {
        throw new Error("blocked");
      },
      setItem: () => {
        throw new Error("full");
      },
      removeItem: () => {
        throw new Error("blocked");
      },
    };
    const store = new TabSeqStore(broken);
    expect(() => store.save("s", 1)).not.toThrow();
    expect(store.load("s")).toBeUndefined();
    expect(() => store.clear("s")).not.toThrow();
  });
});

describe("telemetry", () => {
  it("is numbers, flags and short code words only: no packet, token or score can be in it", async () => {
    const platform = new FakePlatform();
    const { sender } = setup(platform);
    await submit(sender, 0);
    await sender.pause("other");
    const text = JSON.stringify(sender.telemetry());
    expect(text).not.toMatch(/sig\d|alice|participant|Bearer|skt_/);
    for (const value of Object.values(sender.telemetry())) {
      expect(["number", "string", "boolean", "undefined", "object"]).toContain(typeof value);
    }
  });

  it("adds up: every packet handed over is confirmed, dropped, or still waiting", async () => {
    const platform = new FakePlatform({
      plan: ({ n, kind }) => (kind === "single" && n % 3 === 0 ? "lose_request" : undefined),
    });
    const { sender } = setup(platform);
    for (let seq = 0; seq < 12; seq++) await submit(sender, seq);
    await advance(60_000);
    const t = sender.telemetry();
    expect(t.submitted).toBe(12);
    expect(t.confirmed + t.droppedRejected + t.droppedBufferFull + t.bufferedNow).toBe(12);
  });
});
