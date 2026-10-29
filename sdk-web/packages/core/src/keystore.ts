import type { SigningAlg } from "@certivo/sdk-types";

/** A device key pair and which algorithm it uses. The private key is ALWAYS non-extractable. */
export interface StoredKey {
  readonly alg: SigningAlg;
  readonly pair: CryptoKeyPair;
}

/** Where the device key lives between page loads. */
export interface KeyStore {
  load(): Promise<StoredKey | undefined>;
  save(key: StoredKey): Promise<void>;
  clear(): Promise<void>;
}

/** Keeps the key in memory only: it is gone when the page closes. Used in tests, and as the
 *  fallback when the browser offers no IndexedDB (the SDK then registers a new device key each visit). */
export class MemoryKeyStore implements KeyStore {
  private value: StoredKey | undefined;
  async load(): Promise<StoredKey | undefined> {
    return this.value;
  }
  async save(key: StoredKey): Promise<void> {
    this.value = key;
  }
  async clear(): Promise<void> {
    this.value = undefined;
  }
}

const DB_NAME = "certivo-sdk";
const STORE = "device-key";
const RECORD = "current";

function open(factory: IDBFactory): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = factory.open(DB_NAME, 1);
    request.onupgradeneeded = () => request.result.createObjectStore(STORE);
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
    request.onblocked = () => reject(new Error("opening the key database was blocked"));
  });
}

function run<T>(db: IDBDatabase, mode: IDBTransactionMode, work: (store: IDBObjectStore) => IDBRequest<T>): Promise<T> {
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE, mode);
    const request = work(tx.objectStore(STORE));
    tx.oncomplete = () => resolve(request.result);
    tx.onerror = () => reject(tx.error);
    tx.onabort = () => reject(tx.error);
  });
}

/**
 * Stores the key pair in the browser's IndexedDB. A non-extractable key can be stored this way and
 * keeps its protection (tested in P0-20 on Chrome, Edge and Firefox). The browser may delete it at any
 * time (for example Safari after about 7 days without a visit), so a missing key is normal, not an error.
 */
export class IndexedDbKeyStore implements KeyStore {
  constructor(private readonly factory: IDBFactory = globalThis.indexedDB) {}

  async load(): Promise<StoredKey | undefined> {
    const db = await open(this.factory);
    try {
      const value = await run<StoredKey | undefined>(db, "readonly", (s) => s.get(RECORD));
      return value?.pair?.privateKey && value.alg ? value : undefined;
    } finally {
      db.close();
    }
  }

  async save(key: StoredKey): Promise<void> {
    const db = await open(this.factory);
    try {
      await run(db, "readwrite", (s) => s.put(key, RECORD));
    } finally {
      db.close();
    }
  }

  async clear(): Promise<void> {
    const db = await open(this.factory);
    try {
      await run(db, "readwrite", (s) => s.delete(RECORD));
    } finally {
      db.close();
    }
  }
}
