import type { SigningAlg } from "@certivo/sdk-types";
import { b64uEncode } from "./base64url";
import { SdkError } from "./errors";
import { type KeyStore, MemoryKeyStore } from "./keystore";
import { type DeviceSigner, loadOrCreateKey, SUPPORTED_ALGS, signerFor } from "./signer";

/**
 * What the SDK hands to the partner's backend to register a device. It is EXACTLY the JSON body of the platform's
 * `POST /v1/devices` (platform/app/schemas.py, DeviceIn): the partner's backend forwards it as it is, because the
 * platform refuses any extra field. It holds only the PUBLIC key.
 */
export interface DeviceRegistrationRequest {
  /** The device's Ed25519 public key, 43 characters of base64url. */
  readonly public_key: string;
}

/** What the partner's backend sends back: the `id` the platform gave the device (it looks like dev_ and 32 hex characters). */
export interface DeviceRegistrationReply {
  readonly deviceId: string;
}

/**
 * Supplied by the partner's page. It sends the request to the partner's OWN backend, which calls the platform with the
 * partner's secret API key. The SDK never holds that key (decision D-05): it ships to end users.
 */
export type RegisterDevice = (request: DeviceRegistrationRequest) => Promise<DeviceRegistrationReply>;

/** Runs a function so that only one provisioning happens at a time. */
export type LockRunner = <T>(work: () => Promise<T>) => Promise<T>;

/**
 * "software": the key lives in the browser, cannot be read out of it, but has no hardware behind it and nothing proves
 * what is running the code. That is tier 3 in the Trusted Device Layer (docs/adr/0023). The platform decides the tier it records.
 */
export const BROWSER_KEY_PROTECTION = "software" as const;

export interface ProvisionOptions {
  register: RegisterDevice;
  store?: KeyStore;
  subtle?: SubtleCrypto;
  supportedAlgs?: readonly SigningAlg[];
  /** For tests. By default: one at a time in this page, and across tabs where the browser supports Web Locks. */
  lock?: LockRunner;
}

export interface ProvisionedDevice {
  readonly signer: DeviceSigner;
  /** The platform's ID for this device (dev_ and 32 hex characters). Goes in every score packet. */
  readonly deviceId: string;
  /** The public key, 43 characters of base64url. */
  readonly publicKey: string;
  /** True if this call registered the device; false if it was already registered by an earlier visit. */
  readonly isNewDevice: boolean;
  /** False if the key could not be saved: the device will be registered AGAIN on the next visit. */
  readonly persisted: boolean;
  readonly protection: typeof BROWSER_KEY_PROTECTION;
}

const DEVICE_ID = /^dev_[0-9a-f]{32}$/;
let tabQueue: Promise<unknown> = Promise.resolve();

/** One at a time in this page, and (where the browser has Web Locks) one at a time across all tabs of the site. */
export const defaultLock: LockRunner = (work) => {
  const run = (): Promise<never> =>
    (globalThis.navigator?.locks
      ? globalThis.navigator.locks.request("certivo-device-provisioning", work)
      : work()) as Promise<never>;
  const next = tabQueue.then(run, run);
  tabQueue = next.catch(() => undefined);
  return next as Promise<never>;
};

const errorName = (error: unknown): string => (error instanceof Error ? error.name : "Error");

/**
 * Makes sure this device has a key and is registered. Safe to call on every page load:
 *   - first visit: creates a non-extractable key, asks the partner backend to register its public key, remembers the device ID
 *   - later visits: loads both; asks nobody
 *   - key gone (the browser cleared it): treated as a new device, so it registers again
 *   - registration failed: the key is KEPT, so trying again registers the same public key, not a new one
 * Two tabs or two calls at once register once, not twice.
 */
export function provisionDevice(options: ProvisionOptions): Promise<ProvisionedDevice> {
  const store = options.store ?? new MemoryKeyStore();
  const lock = options.lock ?? defaultLock;
  return lock(async () => {
    const loaded = await loadOrCreateKey(store, options.subtle, options.supportedAlgs ?? SUPPORTED_ALGS);
    const signer = signerFor(loaded.stored, options.subtle);
    const publicKey = b64uEncode(await signer.publicKeyRaw());
    if (publicKey.length !== 43) {
      throw new SdkError(
        "capability_missing",
        "The device key is not an Ed25519 key, which is all the platform accepts.",
      );
    }
    let persisted = loaded.persisted;

    if (loaded.stored.deviceId) {
      return {
        signer,
        deviceId: loaded.stored.deviceId,
        publicKey,
        isNewDevice: false,
        persisted,
        protection: BROWSER_KEY_PROTECTION,
      };
    }

    let reply: DeviceRegistrationReply;
    try {
      reply = await options.register({ public_key: publicKey });
    } catch (error) {
      // Say what kind of failure, never what the partner's code put in its message: it could hold anything.
      throw new SdkError(
        "registration_failed",
        `The partner backend could not register this device (${errorName(error)}).`,
      );
    }
    if (typeof reply?.deviceId !== "string" || !DEVICE_ID.test(reply.deviceId)) {
      throw new SdkError("registration_failed", "The partner backend returned a device ID in an unexpected form.");
    }
    try {
      await store.save({ ...loaded.stored, deviceId: reply.deviceId });
    } catch {
      persisted = false;
    }
    return {
      signer,
      deviceId: reply.deviceId,
      publicKey,
      isNewDevice: true,
      persisted,
      protection: BROWSER_KEY_PROTECTION,
    };
  });
}
