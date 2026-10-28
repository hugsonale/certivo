/** Something that can wait in the buffer. `seq` is the packet's sequence number. */
export interface Buffered {
  readonly seq: number;
}

/**
 * Holds signed packets that could not be sent yet (backend unreachable), in order, so they can be
 * uploaded later with the gap disclosed (SDD 7.1, built properly in P0-25). This in-memory version is
 * the skeleton: it keeps order, ignores duplicates, and drops the OLDEST packets when full (the newest
 * ones matter most to a call in progress) while counting what it dropped so the gap can be disclosed.
 */
export class MemoryPacketBuffer<T extends Buffered> {
  private items: T[] = [];
  private dropped = 0;

  constructor(private readonly capacity = 600) {
    if (!Number.isInteger(capacity) || capacity < 1)
      throw new RangeError("capacity must be a whole number of 1 or more");
  }

  push(item: T): void {
    if (this.items.some((i) => i.seq === item.seq)) return; // already waiting
    this.items.push(item);
    this.items.sort((a, b) => a.seq - b.seq);
    while (this.items.length > this.capacity) {
      this.items.shift();
      this.dropped++;
    }
  }

  /** The next `n` packets, oldest first, WITHOUT removing them. */
  peek(n: number): readonly T[] {
    return this.items.slice(0, n);
  }

  /** Remove everything up to and including `seq` (the server confirmed it). */
  ackUpTo(seq: number): void {
    this.items = this.items.filter((i) => i.seq > seq);
  }

  get size(): number {
    return this.items.length;
  }

  /** How many packets were thrown away because the buffer was full. */
  get droppedCount(): number {
    return this.dropped;
  }
}
