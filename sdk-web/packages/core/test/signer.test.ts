import { describe, expect, it } from "vitest";
import {
  chooseSigningAlg,
  createDeviceSigner,
  type KeyStore,
  MemoryKeyStore,
  SdkError,
  SUPPORTED_ALGS,
} from "../src/index";

const real = globalThis.crypto.subtle;

/** A WebCrypto that refuses the named algorithms, like an older browser would. */
function subtleWithout(...refused: string[]): SubtleCrypto {
  return new Proxy(real, {
    get(target, prop) {
      if (prop === "generateKey") {
        return (algorithm: { name: string }, ...rest: unknown[]) =>
          refused.includes(algorithm.name)
            ? Promise.reject(new DOMException("not supported", "NotSupportedError"))
            : (target.generateKey as (...a: unknown[]) => unknown)(algorithm, ...rest);
      }
      const value = Reflect.get(target, prop) as unknown;
      return typeof value === "function" ? value.bind(target) : value;
    },
  });
}

const message = new TextEncoder().encode("certivo test message");

describe("choosing the signing algorithm (ADR 0020)", () => {
  it("prefers Ed25519 when the browser has it", async () => {
    expect(await chooseSigningAlg()).toBe("Ed25519");
  });

  it("today the platform accepts only Ed25519 devices, so that is the only algorithm the SDK will use", () => {
    expect(SUPPORTED_ALGS).toEqual(["Ed25519"]);
  });

  it("does NOT quietly fall back to ECDSA when Ed25519 is missing: the platform would refuse that device", async () => {
    const error = await chooseSigningAlg(subtleWithout("Ed25519")).catch((e: unknown) => e);
    expect((error as SdkError).code).toBe("capability_missing");
    const created = await createDeviceSigner(new MemoryKeyStore(), subtleWithout("Ed25519")).catch((e: unknown) => e);
    expect((created as SdkError).code).toBe("capability_missing");
  });

  it("falls back to ECDSA P-256 once the platform accepts it (ADR 0022: one list to change)", async () => {
    expect(await chooseSigningAlg(subtleWithout("Ed25519"), ["Ed25519", "ECDSA-P256"])).toBe("ECDSA-P256");
  });

  it("says so clearly when the browser can do neither", async () => {
    const error = await chooseSigningAlg(subtleWithout("Ed25519", "ECDSA"), ["Ed25519", "ECDSA-P256"]).catch(
      (e: unknown) => e,
    );
    expect(error).toBeInstanceOf(SdkError);
    expect((error as SdkError).code).toBe("capability_missing");
  });
});

describe("the device signer", () => {
  it("makes a key the first time and reuses it afterwards", async () => {
    const store = new MemoryKeyStore();
    const first = await createDeviceSigner(store);
    expect(first.isNewKey).toBe(true);
    const second = await createDeviceSigner(store);
    expect(second.isNewKey).toBe(false);
    expect(await second.signer.publicKeyRaw()).toEqual(await first.signer.publicKeyRaw());
  });

  it("always creates a private key that cannot be exported", async () => {
    const store = new MemoryKeyStore();
    await createDeviceSigner(store);
    const stored = await store.load();
    expect(stored?.pair.privateKey.extractable).toBe(false);
    await expect(real.exportKey("pkcs8", stored!.pair.privateKey)).rejects.toThrow();
  });

  it("signs with Ed25519 in a way that verifies, and is deterministic", async () => {
    const { signer } = await createDeviceSigner(new MemoryKeyStore());
    expect(signer.alg).toBe("Ed25519");
    const signature = await signer.sign(message);
    expect(signature.length).toBe(64);
    const publicKey = await real.importKey("raw", await signer.publicKeyRaw(), { name: "Ed25519" }, false, ["verify"]);
    expect(await real.verify("Ed25519", publicKey, signature, message)).toBe(true);
    expect(await real.verify("Ed25519", publicKey, signature, new TextEncoder().encode("changed"))).toBe(false);
    expect(await signer.sign(message)).toEqual(signature);
  });

  it("signs with the ECDSA fallback in raw 64-byte form, and the signature verifies", async () => {
    const { signer } = await createDeviceSigner(new MemoryKeyStore(), subtleWithout("Ed25519"), [
      "Ed25519",
      "ECDSA-P256",
    ]);
    expect(signer.alg).toBe("ECDSA-P256");
    const signature = await signer.sign(message);
    expect(signature.length).toBe(64);
    const publicKey = await real.importKey(
      "raw",
      await signer.publicKeyRaw(),
      { name: "ECDSA", namedCurve: "P-256" },
      false,
      ["verify"],
    );
    expect(await real.verify({ name: "ECDSA", hash: "SHA-256" }, publicKey, signature, message)).toBe(true);
  });

  it("makes a new key when the stored one uses an algorithm the platform no longer accepts", async () => {
    const store = new MemoryKeyStore();
    const old = await createDeviceSigner(store, subtleWithout("Ed25519"), ["Ed25519", "ECDSA-P256"]);
    expect(old.signer.alg).toBe("ECDSA-P256");
    const now = await createDeviceSigner(store); // default: Ed25519 only
    expect(now.isNewKey).toBe(true);
    expect(now.signer.alg).toBe("Ed25519");
  });

  it("treats unreadable storage as 'no key' and carries on", async () => {
    const broken: KeyStore = {
      load: () => Promise.reject(new Error("storage is unavailable")),
      save: () => Promise.reject(new Error("storage is full")),
      clear: () => Promise.resolve(),
    };
    const { signer, isNewKey } = await createDeviceSigner(broken);
    expect(isNewKey).toBe(true);
    expect((await signer.sign(message)).length).toBe(64); // works for this visit even though it cannot be saved
  });
});
