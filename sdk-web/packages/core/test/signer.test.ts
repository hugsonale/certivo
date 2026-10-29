import { describe, expect, it } from "vitest";
import { chooseSigningAlg, createDeviceSigner, type KeyStore, MemoryKeyStore, SdkError } from "../src/index";

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

  it("falls back to ECDSA P-256 when Ed25519 is missing", async () => {
    expect(await chooseSigningAlg(subtleWithout("Ed25519"))).toBe("ECDSA-P256");
  });

  it("says so clearly when the browser can do neither", async () => {
    const error = await chooseSigningAlg(subtleWithout("Ed25519", "ECDSA")).catch((e: unknown) => e);
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
    const { signer } = await createDeviceSigner(new MemoryKeyStore(), subtleWithout("Ed25519"));
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
