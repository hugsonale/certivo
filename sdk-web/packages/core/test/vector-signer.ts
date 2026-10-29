// Test helper (not a test): a DeviceSigner that holds the PUBLIC test-only key from the platform's test vector,
// so tests can sign exactly as the platform's own test does. Never use this seed for anything real.
import type { DeviceSigner } from "../src/index";
import { b64uDecode } from "../src/index";

const hexToBytes = (hex: string): Uint8Array<ArrayBuffer> =>
  Uint8Array.from((hex.match(/../g) ?? []).map((byte) => Number.parseInt(byte, 16)));

// PKCS#8 wrapper for a 32-byte Ed25519 seed (RFC 8410).
const PKCS8_PREFIX = hexToBytes("302e020100300506032b657004220420");

export async function vectorSigner(seedHex: string, publicKeyB64u: string): Promise<DeviceSigner> {
  const pkcs8 = new Uint8Array([...PKCS8_PREFIX, ...hexToBytes(seedHex)]);
  const privateKey = await crypto.subtle.importKey("pkcs8", pkcs8, { name: "Ed25519" }, false, ["sign"]);
  return {
    alg: "Ed25519",
    publicKeyRaw: async () => b64uDecode(publicKeyB64u),
    sign: async (data) => new Uint8Array(await crypto.subtle.sign("Ed25519", privateKey, data)),
  };
}

export { hexToBytes };
