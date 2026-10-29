/**
 * Canonical JSON: the exact bytes that get signed (BUILD_SPEC_0 section 4). This is a deliberately
 * small profile of JSON, so that every language can produce identical bytes without a library:
 *
 *   1. UTF-8, no whitespace, object keys sorted ascending (byte order).
 *   2. Keys match ^[a-z0-9_]{1,64}$.
 *   3. Values are: whole numbers within +/-(2^53 - 1), printable-ASCII strings (0x20 to 0x7E), arrays, objects.
 *   4. NO floats, booleans, nulls or non-ASCII.
 *
 * Whatever this file produces must match the platform's `canonical_json` (platform/app/crypto.py) byte for byte.
 * The test vectors in docs/spec/test-vectors/ prove it, and CI fails if they ever disagree.
 *
 * One gap that no test can close: JavaScript cannot tell 1 from 1.0. Python's `canonical_json` refuses 1.0 (a
 * float) and this file accepts it as the whole number 1. The SDK builds its packets from whole numbers only
 * (the packet builder checks), so this cannot happen in the SDK itself.
 */

export class CanonicalizationError extends Error {
  override readonly name = "CanonicalizationError";
}

const KEY = /^[a-z0-9_]{1,64}$/;

function isPlainObject(value: object): boolean {
  const proto = Object.getPrototypeOf(value);
  return proto === Object.prototype || proto === null;
}

function encode(value: unknown, path: string): string {
  if (typeof value === "number") {
    if (!Number.isSafeInteger(value)) {
      throw new CanonicalizationError(`${path}: only whole numbers within +/-(2^53-1) are allowed`);
    }
    return JSON.stringify(Object.is(value, -0) ? 0 : value);
  }
  if (typeof value === "string") {
    for (let i = 0; i < value.length; i++) {
      const code = value.charCodeAt(i);
      if (code < 0x20 || code > 0x7e) {
        throw new CanonicalizationError(`${path}: only printable ASCII strings are allowed`);
      }
    }
    return JSON.stringify(value); // for printable ASCII this escapes exactly the quote and the backslash
  }
  if (Array.isArray(value)) {
    return `[${value.map((item, i) => encode(item, `${path}[${i}]`)).join(",")}]`;
  }
  if (typeof value === "object" && value !== null) {
    if (!isPlainObject(value)) throw new CanonicalizationError(`${path}: only plain objects are allowed`);
    const keys = Object.keys(value).sort(); // default sort is by UTF-16 code unit, which is byte order for ASCII keys
    const parts = keys.map((key) => {
      if (!KEY.test(key)) throw new CanonicalizationError(`${path}: invalid key ${JSON.stringify(key)}`);
      return `${JSON.stringify(key)}:${encode((value as Record<string, unknown>)[key], `${path}.${key}`)}`;
    });
    return `{${parts.join(",")}}`;
  }
  throw new CanonicalizationError(`${path}: null, boolean, undefined and other types are not allowed`);
}

/** The canonical text of a value. Throws CanonicalizationError for anything outside the profile. */
export function canonicalJson(value: unknown): string {
  return encode(value, "$");
}

/** The canonical bytes of a value (UTF-8, which for this profile is plain ASCII). */
export function canonicalBytes(value: unknown): Uint8Array<ArrayBuffer> {
  return new TextEncoder().encode(canonicalJson(value));
}
