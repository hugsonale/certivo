import { describe, expect, it } from "vitest";
import { CanonicalizationError, canonicalBytes, canonicalJson } from "../src/index";

const refuses = (value: unknown) => expect(() => canonicalJson(value)).toThrow(CanonicalizationError);

describe("canonical JSON (BUILD_SPEC_0 section 4)", () => {
  it("sorts keys, at every depth, and writes no whitespace", () => {
    expect(canonicalJson({ b: 1, a: { d: [1, 2], c: "x" } })).toBe('{"a":{"c":"x","d":[1,2]},"b":1}');
  });

  it("sorts keys in byte order: digits, then underscore, then letters", () => {
    expect(canonicalJson({ ab: 1, a_b: 2, a1: 3, a: 4 })).toBe('{"a":4,"a1":3,"a_b":2,"ab":1}');
  });

  it("escapes only the quote and the backslash", () => {
    expect(canonicalJson({ a: 'say "hi" \\ a/b~' })).toBe('{"a":"say \\"hi\\" \\\\ a/b~"}');
  });

  it("keeps array order and accepts the largest whole numbers", () => {
    expect(canonicalJson([3, 1, 2, -9007199254740991, 9007199254740991])).toBe(
      "[3,1,2,-9007199254740991,9007199254740991]",
    );
  });

  it("writes negative zero as 0 (the platform has no negative zero)", () => {
    expect(canonicalJson({ a: -0 })).toBe('{"a":0}');
  });

  it("accepts an object with no prototype", () => {
    const bare = Object.create(null) as Record<string, number>;
    bare.a = 1;
    expect(canonicalJson(bare)).toBe('{"a":1}');
  });

  it("refuses everything outside the profile", () => {
    for (const bad of [
      { a: 1.5 },
      { a: Number.NaN },
      { a: Number.POSITIVE_INFINITY },
      { a: 2 ** 53 },
      { a: -(2 ** 53) },
      { a: true },
      { a: false },
      { a: null },
      { a: undefined },
      { a: 10n },
      { a: "caf\u00e9" },
      { a: "tab\t" },
      { a: "new\nline" },
      { a: "del\x7f" },
      { A: 1 },
      { "a-b": 1 },
      { "": 1 },
      { [`${"k".repeat(65)}`]: 1 },
      { a: new Date(0) },
      { a: new Map() },
      { a: () => 1 },
      { a: Symbol("x") },
      [{ b: [{ c: 1.5 }] }],
    ]) {
      refuses(bad);
    }
  });

  it("says where the problem is", () => {
    expect(() => canonicalJson({ a: [{ b: 1.5 }] })).toThrow(/\$\.a\[0\]\.b/);
  });

  it("returns the same text as bytes", () => {
    expect(new TextDecoder().decode(canonicalBytes({ b: 2, a: 1 }))).toBe('{"a":1,"b":2}');
  });
});
