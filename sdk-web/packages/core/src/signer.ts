import type { SigningAlg } from "@certivo/sdk-types";
import { SdkError } from "./errors";
import { type KeyStore, MemoryKeyStore, type StoredKey } from "./keystore";

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
 * The algorithms the SDK will use today. ONLY Ed25519: the platform's device registration accepts nothing else
 * (a 43-character Ed25519 public key, platform/app/schemas.py DeviceIn), and BUILD_SPEC_0 section 11 says the ECDSA
 * P-256 fallback needs an `alg` field on devices first. Add "ECDSA-P256" here, in one place, when the platform has it
 * (docs/adr/0022). Until then an ECDSA key would be created and then refused, which is worse than saying so up front.
 */
export const SUPPORTED_ALGS: readonly SigningAlg[] = ["Ed25519"];

/**
 * Decides which algorithm this browser can use: the first of `supported` that really works, in order of preference
 * (ADR 0020). It tries for real rather than guessing from the browser version.
 */
export async function chooseSigningAlg(
  subtle?: SubtleCrypto,
  supported: readonly SigningAlg[] = SUPPORTED_ALGS,
): Promise<SigningAlg> {
  const s = subtleOf(subtle);
  for (const alg of ["Ed25519", "ECDSA-P256"] as const) {
    if (!supported.includes(alg)) continue;
    try {
      await generate(s, alg);
      return alg;
    } catch {
      // not supported here: try the next one
    }
  }
  throw new SdkError(
    "capability_missing",
    `This browser cannot sign with any algorithm the platform accepts (${supported.join(", ")}).`,
  );
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

export interface LoadedKey {
  readonly stored: StoredKey;
  readonly isNewKey: boolean;
  /** False if the key could not be saved: it works for this visit but will not survive a reload. */
  readonly persisted: boolean;
}

/**
 * Loads this device's key, or makes one if there is none (or only one the platform no longer accepts). A missing key is
 * normal (the browser may have cleared it): it simply means a new device registration. The private key is created
 * non-extractable here and nowhere else.
 */
export async function loadOrCreateKey(
  store: KeyStore = new MemoryKeyStore(),
  subtle?: SubtleCrypto,
  supported: readonly SigningAlg[] = SUPPORTED_ALGS,
): Promise<LoadedKey> {
  const s = subtleOf(subtle);
  let existing: StoredKey | null = null;
  try {
    existing = (await store.load()) ?? null;
  } catch {
    existing = null; // unreadable storage counts as "no key"
  }
  if (existing && supported.includes(existing.alg)) {
    return { stored: existing, isNewKey: false, persisted: true };
  }
  const alg = await chooseSigningAlg(s, supported);
  const stored: StoredKey = { alg, pair: await generate(s, alg) };
  let persisted = true;
  try {
    await store.save(stored);
  } catch {
    persisted = false; // still works for this visit; it just will not survive a reload
  }
  return { stored, isNewKey: true, persisted };
}

/** A signer for a stored key. */
export function signerFor(stored: StoredKey, subtle?: SubtleCrypto): DeviceSigner {
  return new WebCryptoSigner(stored.alg, stored.pair, subtleOf(subtle));
}

export async function createDeviceSigner(
  store: KeyStore = new MemoryKeyStore(),
  subtle?: SubtleCrypto,
  supported: readonly SigningAlg[] = SUPPORTED_ALGS,
): Promise<CreatedSigner> {
  const { stored, isNewKey } = await loadOrCreateKey(store, subtle, supported);
  return { signer: signerFor(stored, subtle), isNewKey };
}
