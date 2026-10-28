import type { SigningAlg } from "@certivo/sdk-types";
import { SdkError } from "./errors";
import { type KeyStore, MemoryKeyStore } from "./keystore";

/** Signs on behalf of this device. The private key is held by the browser and can never be read. */
export interface DeviceSigner {
  readonly alg: SigningAlg;
  /** The public half, as raw bytes (32 bytes for Ed25519, 65 for ECDSA P-256), to register the device. */
  publicKeyRaw(): Promise<Uint8Array<ArrayBuffer>>;
  /** Ed25519: 64 bytes. ECDSA P-256: 64 bytes in raw r||s form (the server must expect that, not DER). */
  sign(data: BufferSource): Promise<Uint8Array<ArrayBuffer>>;
}

const ED25519: AlgorithmIdentifier = { name: "Ed25519" };
const ECDSA_KEYGEN: EcKeyGenParams = { name: "ECDSA", namedCurve: "P-256" };
const ECDSA_SIGN: EcdsaParams = { name: "ECDSA", hash: "SHA-256" };

function subtleOf(subtle?: SubtleCrypto): SubtleCrypto {
  const s = subtle ?? globalThis.crypto?.subtle;
  if (!s) {
    throw new SdkError("capability_missing", "WebCrypto is not available. Use https or localhost.");
  }
  return s;
}

async function generate(subtle: SubtleCrypto, alg: SigningAlg): Promise<CryptoKeyPair> {
  // extractable = false: the private key can be used to sign but never read back (ADR 0020).
  const pair = (await (alg === "Ed25519"
    ? subtle.generateKey(ED25519, false, ["sign", "verify"])
    : subtle.generateKey(ECDSA_KEYGEN, false, ["sign", "verify"]))) as CryptoKeyPair;
  return pair;
}

/**
 * Decides which algorithm this browser can use: Ed25519 if it works, otherwise ECDSA P-256 (ADR 0020).
 * It tries for real rather than guessing from the browser version.
 */
export async function chooseSigningAlg(subtle?: SubtleCrypto): Promise<SigningAlg> {
  const s = subtleOf(subtle);
  for (const alg of ["Ed25519", "ECDSA-P256"] as const) {
    try {
      await generate(s, alg);
      return alg;
    } catch {
      // not supported here: try the next one
    }
  }
  throw new SdkError("capability_missing", "This browser can sign with neither Ed25519 nor ECDSA P-256.");
}

class WebCryptoSigner implements DeviceSigner {
  constructor(
    readonly alg: SigningAlg,
    private readonly pair: CryptoKeyPair,
    private readonly subtle: SubtleCrypto,
  ) {}

  async publicKeyRaw(): Promise<Uint8Array<ArrayBuffer>> {
    return new Uint8Array(await this.subtle.exportKey("raw", this.pair.publicKey));
  }

  async sign(data: BufferSource): Promise<Uint8Array<ArrayBuffer>> {
    const algorithm = this.alg === "Ed25519" ? ED25519 : ECDSA_SIGN;
    return new Uint8Array(await this.subtle.sign(algorithm, this.pair.privateKey, data));
  }
}

export interface CreatedSigner {
  readonly signer: DeviceSigner;
  /** True when a new key was just made: the device must be (re-)registered with the partner backend. */
  readonly isNewKey: boolean;
}

/**
 * Loads this device's key, or makes one if there is none. A missing key is normal (the browser may
 * have cleared it): it simply means a new device registration.
 */
export async function createDeviceSigner(
  store: KeyStore = new MemoryKeyStore(),
  subtle?: SubtleCrypto,
): Promise<CreatedSigner> {
  const s = subtleOf(subtle);
  let stored = null;
  try {
    stored = (await store.load()) ?? null;
  } catch {
    stored = null; // unreadable storage counts as "no key"
  }
  if (stored) {
    return { signer: new WebCryptoSigner(stored.alg, stored.pair, s), isNewKey: false };
  }
  const alg = await chooseSigningAlg(s);
  const pair = await generate(s, alg);
  try {
    await store.save({ alg, pair });
  } catch {
    // The key still works for this visit; it just will not survive a reload.
  }
  return { signer: new WebCryptoSigner(alg, pair, s), isNewKey: true };
}
