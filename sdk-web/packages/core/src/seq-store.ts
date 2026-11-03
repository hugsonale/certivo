/**
 * Remembers the next sequence number of one session across a page reload, so a reload in the middle of a call carries on
 * where it left off instead of starting again at 0 (the platform refuses a packet whose seq is not higher than the last
 * one it took: `seq_out_of_order`, Build Spec 0 section 4).
 *
 * What is kept is ONE whole number per session, nothing about the person and nothing about the picture.
 */
export interface SeqStore {
  /** The next seq to use for this session, or undefined if none is remembered. */
  load(sessionId: string): number | undefined;
  save(sessionId: string, next: number): void;
  /** Forget it (the call is over). */
  clear(sessionId: string): void;
}

/** Remembers nothing across a reload. The default. */
export class MemorySeqStore implements SeqStore {
  private readonly values = new Map<string, number>();
  load(sessionId: string): number | undefined {
    return this.values.get(sessionId);
  }
  save(sessionId: string, next: number): void {
    this.values.set(sessionId, next);
  }
  clear(sessionId: string): void {
    this.values.delete(sessionId);
  }
}

/** The part of the browser's Storage that is used, so a test can supply a stand-in. */
export interface TabStorage {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
  removeItem(key: string): void;
}

const KEY_PREFIX = "certivo.next_seq.";

/**
 * Keeps the number in the browser's per-tab storage. It survives a reload of the tab and is gone when the tab closes,
 * which is as short as the life of a call. Every failure (storage full, blocked, private mode) is swallowed: the worst
 * case is the same as having no store. Pass `window.sessionStorage`.
 */
export class TabSeqStore implements SeqStore {
  constructor(private readonly storage: TabStorage) {}

  load(sessionId: string): number | undefined {
    try {
      const raw = this.storage.getItem(KEY_PREFIX + sessionId);
      if (raw === null || !/^\d{1,10}$/.test(raw)) return undefined;
      const value = Number(raw);
      return Number.isSafeInteger(value) && value <= 2 ** 31 - 1 ? value : undefined;
    } catch {
      return undefined;
    }
  }

  save(sessionId: string, next: number): void {
    try {
      this.storage.setItem(KEY_PREFIX + sessionId, String(next));
    } catch {
      // see the note above
    }
  }

  clear(sessionId: string): void {
    try {
      this.storage.removeItem(KEY_PREFIX + sessionId);
    } catch {
      // see the note above
    }
  }
}
