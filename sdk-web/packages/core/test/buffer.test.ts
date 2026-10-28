import { describe, expect, it } from "vitest";
import { MemoryPacketBuffer } from "../src/index";

const item = (seq: number) => ({ seq });

describe("MemoryPacketBuffer", () => {
  it("returns packets oldest first, whatever order they arrived in", () => {
    const buffer = new MemoryPacketBuffer(10);
    for (const seq of [3, 1, 2]) buffer.push(item(seq));
    expect(buffer.peek(10).map((i) => i.seq)).toEqual([1, 2, 3]);
  });

  it("ignores a packet it already holds", () => {
    const buffer = new MemoryPacketBuffer(10);
    buffer.push(item(1));
    buffer.push(item(1));
    expect(buffer.size).toBe(1);
  });

  it("peek does not remove; ackUpTo removes what the server confirmed", () => {
    const buffer = new MemoryPacketBuffer(10);
    for (const seq of [1, 2, 3, 4]) buffer.push(item(seq));
    expect(buffer.peek(2).map((i) => i.seq)).toEqual([1, 2]);
    expect(buffer.size).toBe(4);
    buffer.ackUpTo(2);
    expect(buffer.peek(10).map((i) => i.seq)).toEqual([3, 4]);
  });

  it("when full, drops the OLDEST and counts them so the gap can be disclosed", () => {
    const buffer = new MemoryPacketBuffer(3);
    for (const seq of [1, 2, 3, 4, 5]) buffer.push(item(seq));
    expect(buffer.peek(10).map((i) => i.seq)).toEqual([3, 4, 5]);
    expect(buffer.droppedCount).toBe(2);
  });

  it("refuses a nonsense capacity", () => {
    expect(() => new MemoryPacketBuffer(0)).toThrow(RangeError);
    expect(() => new MemoryPacketBuffer(1.5)).toThrow(RangeError);
  });
});
