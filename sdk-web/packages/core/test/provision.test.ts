import { describe, expect, it } from "vitest";
import {
  BROWSER_KEY_PROTECTION,
  type DeviceRegistrationRequest,
  type KeyStore,
  loadOrCreateKey,
  MemoryKeyStore,
  provisionDevice,
  type RegisterDevice,
  SdkError,
  type StoredKey,
} from "../src/index";

const real = globalThis.crypto.subtle;

/** A WebCrypto that refuses Ed25519, like an older browser. */
function withoutEd25519(): SubtleCrypto {
  return new Proxy(real, {
    get(target, prop) {
      if (prop === "generateKey") {
        return (algorithm: { name: string }, ...rest: unknown[]) =>
          algorithm.name === "Ed25519"
            ? Promise.reject(new DOMException("not supported", "NotSupportedError"))
            : (target.generateKey as (...a: unknown[]) => unknown)(algorithm, ...rest);
      }
      const value = Reflect.get(target, prop) as unknown;
      return typeof value === "function" ? value.bind(target) : value;
    },
  });
}

const deviceIdFor = (n: number) => `dev_${n.toString(16).padStart(32, "0")}`;

/** A stand-in for the partner's backend: records each request and hands out device IDs. */
function partnerBackend(failTimes = 0) {
  const requests: DeviceRegistrationRequest[] = [];
  let failures = failTimes;
  const register: RegisterDevice = async (request) => {
    requests.push(request);
    if (failures > 0) {
      failures--;
      throw new Error("backend said no: secret-partner-token-abc123");
    }
    return { deviceId: deviceIdFor(requests.length) };
  };
  return { register, requests };
}

describe("provisioning a device (P0-23)", () => {
  it("first visit: makes a key, asks the partner backend to register ONLY its public key, and remembers the ID", async () => {
    const store = new MemoryKeyStore();
    const { register, requests } = partnerBackend();
    const device = await provisionDevice({ register, store });
    expect(requests).toHaveLength(1);
    expect(Object.keys(requests[0] ?? {})).toEqual(["public_key"]); // exactly the platform's DeviceIn: it refuses extra fields
    expect(requests[0]?.public_key).toHaveLength(43);
    expect(device.deviceId).toBe(deviceIdFor(1));
    expect(device.publicKey).toBe(requests[0]?.public_key);
    expect(device.isNewDevice).toBe(true);
    expect(device.persisted).toBe(true);
    expect(device.protection).toBe(BROWSER_KEY_PROTECTION);
    expect((await store.load())?.deviceId).toBe(deviceIdFor(1));
  });

  it("the public key it registers is the one that verifies this device's signatures", async () => {
    const { register, requests } = partnerBackend();
    const device = await provisionDevice({ register, store: new MemoryKeyStore() });
    const message = new TextEncoder().encode("hello");
    const signature = await device.signer.sign(message);
    const publicKey = await real.importKey("raw", await device.signer.publicKeyRaw(), { name: "Ed25519" }, false, [
      "verify",
    ]);
    expect(await real.verify("Ed25519", publicKey, signature, message)).toBe(true);
    expect(requests[0]?.public_key).toBe(device.publicKey);
  });

  it("later visits: loads the key and the ID, and asks nobody", async () => {
    const store = new MemoryKeyStore();
    const { register, requests } = partnerBackend();
    const first = await provisionDevice({ register, store });
    const second = await provisionDevice({ register, store });
    expect(requests).toHaveLength(1);
    expect(second.isNewDevice).toBe(false);
    expect(second.deviceId).toBe(first.deviceId);
    expect(second.publicKey).toBe(first.publicKey);
  });

  it("the private key is always non-extractable", async () => {
    const store = new MemoryKeyStore();
    await provisionDevice({ register: partnerBackend().register, store });
    const stored = await store.load();
    expect(stored?.pair.privateKey.extractable).toBe(false);
    await expect(real.exportKey("pkcs8", stored?.pair.privateKey as CryptoKey)).rejects.toThrow();
  });

  it("a failed registration keeps the key, so the retry registers the SAME public key", async () => {
    const store = new MemoryKeyStore();
    const { register, requests } = partnerBackend(1);
    await expect(provisionDevice({ register, store })).rejects.toMatchObject({ code: "registration_failed" });
    const device = await provisionDevice({ register, store });
    expect(requests).toHaveLength(2);
    expect(requests[1]?.public_key).toBe(requests[0]?.public_key);
    expect(device.deviceId).toBe(deviceIdFor(2));
  });

  it("says what kind of failure it was, but never repeats what the partner's code wrote", async () => {
    const { register } = partnerBackend(1);
    const error = await provisionDevice({ register, store: new MemoryKeyStore() }).catch((e: unknown) => e);
    expect(error).toBeInstanceOf(SdkError);
    expect((error as SdkError).message).toContain("Error");
    expect((error as SdkError).message).not.toContain("secret-partner-token");
  });

  it("refuses a device ID that is not in the platform's form, and does not save it", async () => {
    const store = new MemoryKeyStore();
    for (const deviceId of [
      "",
      "dev_123",
      "DEV_00000000000000000000000000000001",
      "cs_00000000000000000000000000000001",
    ]) {
      const bad: RegisterDevice = async () => ({ deviceId });
      await expect(provisionDevice({ register: bad, store })).rejects.toMatchObject({ code: "registration_failed" });
    }
    expect((await store.load())?.deviceId).toBeUndefined();
    const silent: RegisterDevice = async () => ({}) as never;
    await expect(provisionDevice({ register: silent, store })).rejects.toMatchObject({ code: "registration_failed" });
  });

  it("if the browser cleared the key, this is a new device: new key, registered again", async () => {
    const store = new MemoryKeyStore();
    const { register, requests } = partnerBackend();
    const before = await provisionDevice({ register, store });
    await store.clear();
    const after = await provisionDevice({ register, store });
    expect(requests).toHaveLength(2);
    expect(after.publicKey).not.toBe(before.publicKey);
    expect(after.deviceId).not.toBe(before.deviceId);
    expect(after.isNewDevice).toBe(true);
  });

  it("two calls at once register once, not twice", async () => {
    const store = new MemoryKeyStore();
    const { register, requests } = partnerBackend();
    const [a, b] = await Promise.all([provisionDevice({ register, store }), provisionDevice({ register, store })]);
    expect(requests).toHaveLength(1);
    expect(a.deviceId).toBe(b.deviceId);
    expect(a.publicKey).toBe(b.publicKey);
  });

  it("if the key cannot be saved it still works this visit, and says it will not last", async () => {
    const broken: KeyStore = {
      load: async () => undefined,
      save: async () => Promise.reject(new Error("storage is full")),
      clear: async () => {},
    };
    const { register, requests } = partnerBackend();
    const first = await provisionDevice({ register, store: broken });
    expect(first.persisted).toBe(false);
    expect((await first.signer.sign(new Uint8Array(1))).length).toBe(64);
    await provisionDevice({ register, store: broken }); // nothing was remembered, so the next visit registers again
    expect(requests).toHaveLength(2);
  });

  it("a key saved by the P0-21 build (no device ID yet) is kept and registered", async () => {
    const store = new MemoryKeyStore();
    const pair = (await real.generateKey({ name: "Ed25519" }, false, ["sign", "verify"])) as CryptoKeyPair;
    const old: StoredKey = { alg: "Ed25519", pair };
    await store.save(old);
    const { register, requests } = partnerBackend();
    const device = await provisionDevice({ register, store });
    expect(device.isNewDevice).toBe(true);
    const expected = new Uint8Array(await real.exportKey("raw", pair.publicKey));
    expect(device.publicKey).toBe(
      btoa(String.fromCharCode(...expected))
        .replace(/\+/g, "-")
        .replace(/\//g, "_")
        .replace(/=+$/, ""),
    );
    expect(requests).toHaveLength(1);
  });

  it("registers nobody when the browser cannot make a key the platform accepts", async () => {
    const { register, requests } = partnerBackend();
    await expect(
      provisionDevice({ register, store: new MemoryKeyStore(), subtle: withoutEd25519() }),
    ).rejects.toMatchObject({
      code: "capability_missing",
    });
    expect(requests).toHaveLength(0);
  });

  it("loadOrCreateKey reports whether the key was new", async () => {
    const store = new MemoryKeyStore();
    expect((await loadOrCreateKey(store)).isNewKey).toBe(true);
    expect((await loadOrCreateKey(store)).isNewKey).toBe(false);
  });
});
