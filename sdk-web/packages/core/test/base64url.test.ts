import { describe, expect, it } from "vitest";
import { b64uDecode, b64uEncode } from "../src/index";

describe("base64url without padding", () => {
  it("uses - and _ instead of + and /, and no =", () => {
    expect(b64uEncode(Uint8Array.of(0xfb, 0xff))).toBe("-_8");
    expect(b64uEncode(Uint8Array.of(0x66, 0x6f, 0x6f, 0x62, 0x61))).toBe("Zm9vYmE");
  });

  it("makes 43 characters from a 32-byte public key and 86 from a 64-byte signature", () => {
    expect(b64uEncode(new Uint8Array(32)).length).toBe(43);
    expect(b64uEncode(new Uint8Array(64)).length).toBe(86);
  });

  it("round-trips every length from 0 to 130", () => {
    for (let n = 0; n <= 130; n++) {
      const bytes = Uint8Array.from({ length: n }, (_, i) => (i * 37 + n) % 256);
      expect(b64uDecode(b64uEncode(bytes))).toEqual(bytes);
    }
  });

  it("refuses text that is not base64url", () => {
    for (const bad of ["a+b", "a/b", "ab==", "ab cd", "a", "abcde", "\u00e9\u00e9"]) {
      expect(() => b64uDecode(bad), bad).toThrow(RangeError);
    }
  });
});
