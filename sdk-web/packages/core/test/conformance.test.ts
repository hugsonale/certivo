/**
 * THE CONFORMANCE GATE (P0-22). The platform publishes test vectors in docs/spec/test-vectors/ (BUILD_SPEC_0 section 4:
 * "every SDK implementation must reproduce canonical_bytes_hex and signature_b64u exactly before it is allowed to send
 * traffic"). These tests read those files and check the SDK against them. If the SDK and the platform ever disagree about
 * a single byte, this fails, and so does the pull request. The workflow also runs when the vector files change.
 */
import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import {
  b64uDecode,
  b64uEncode,
  buildPacket,
  CanonicalizationError,
  canonicalBytes,
  canonicalJson,
  SCORE_DOMAIN,
  scoreCodecV1,
} from "../src/index";
import { hexToBytes, vectorSigner } from "./vector-signer";

const repoRoot = join(__dirname, "..", "..", "..", "..");
const vectorDir = join(repoRoot, "docs", "spec", "test-vectors");

function load<T>(name: string): T {
  const file = join(vectorDir, name);
  // A missing file must FAIL, never skip: a gate that quietly checks nothing is worse than no gate.
  expect(existsSync(file), `${file} is missing: the conformance gate cannot run`).toBe(true);
  return JSON.parse(readFileSync(file, "utf8")) as T;
}

interface ScoreVector {
  test_only_private_seed_hex: string;
  public_key_b64u: string;
  domain_utf8: string;
  packet: {
    v: 1;
    session_id: string;
    participant_reference: string;
    device_id: string;
    seq: number;
    interval_start_ms: number;
    interval_end_ms: number;
    confidence_milli: number;
    model_version: string;
    explanation: { reason_codes: string[]; signal_milli: Record<string, number> };
  };
  canonical_utf8: string;
  canonical_bytes_hex: string;
  signature_b64u: string;
  signature_b64u_len: number;
}

const vector = load<ScoreVector>("score-packet-v1.json");
const hex = (bytes: Uint8Array): string => [...bytes].map((b) => b.toString(16).padStart(2, "0")).join("");

describe("score-packet-v1.json: the packet the platform signs", () => {
  it("uses the domain the SDK uses", () => {
    expect(vector.domain_utf8).toBe(SCORE_DOMAIN);
  });

  it("canonical JSON: the SDK reproduces the platform's text and bytes exactly", () => {
    expect(canonicalJson(vector.packet)).toBe(vector.canonical_utf8);
    expect(hex(canonicalBytes(vector.packet))).toBe(vector.canonical_bytes_hex);
  });

  it("signature: signing domain + canonical bytes with the vector's key gives the platform's exact signature", async () => {
    const signer = await vectorSigner(vector.test_only_private_seed_hex, vector.public_key_b64u);
    const message = new Uint8Array([
      ...new TextEncoder().encode(vector.domain_utf8),
      ...hexToBytes(vector.canonical_bytes_hex),
    ]);
    const signature = await signer.sign(message);
    expect(b64uEncode(signature)).toBe(vector.signature_b64u);
    expect(vector.signature_b64u.length).toBe(vector.signature_b64u_len);
  });

  it("the platform's signature verifies under the platform's public key, and fails if one byte changes", async () => {
    const publicKey = await crypto.subtle.importKey(
      "raw",
      b64uDecode(vector.public_key_b64u),
      { name: "Ed25519" },
      false,
      ["verify"],
    );
    const message = new Uint8Array([
      ...new TextEncoder().encode(vector.domain_utf8),
      ...hexToBytes(vector.canonical_bytes_hex),
    ]);
    const signature = b64uDecode(vector.signature_b64u);
    expect(await crypto.subtle.verify("Ed25519", publicKey, signature, message)).toBe(true);
    const changed = message.slice();
    changed[changed.length - 1] = (changed[changed.length - 1] ?? 0) ^ 1;
    expect(await crypto.subtle.verify("Ed25519", publicKey, signature, changed)).toBe(false);
  });

  it("the SDK's own packet and codec produce the same signed bytes and the same request body", async () => {
    const p = vector.packet;
    const packet = buildPacket({
      sessionId: p.session_id,
      participantReference: p.participant_reference,
      deviceId: p.device_id,
      seq: p.seq,
      intervalStartMs: p.interval_start_ms,
      intervalEndMs: p.interval_end_ms,
      result: {
        confidenceMilli: p.confidence_milli,
        reasonCodes: p.explanation.reason_codes,
        signalMilli: p.explanation.signal_milli,
        modelVersion: p.model_version,
      },
    });
    const message = scoreCodecV1.encodeForSigning(packet);
    expect(hex(message)).toBe(
      hex(new Uint8Array([...new TextEncoder().encode(vector.domain_utf8), ...hexToBytes(vector.canonical_bytes_hex)])),
    );

    const signer = await vectorSigner(vector.test_only_private_seed_hex, vector.public_key_b64u);
    const body = scoreCodecV1.toWire(packet, await signer.sign(message));
    const { session_id: _sessionId, ...sentFields } = p; // the session ID is signed but travels in the URL, not the body
    expect(body).toEqual({ ...sentFields, device_signature: vector.signature_b64u });
  });
});

interface Corpus {
  cases: Array<{ name: string; value: unknown; canonical_utf8: string; canonical_bytes_hex: string }>;
  rejected: Array<{ name: string; value: unknown }>;
}
const corpus = load<Corpus>("canonical-json-v1.json");

describe("canonical-json-v1.json: many small cases, including inputs that must be refused", () => {
  it("is a real corpus (not an empty file that would pass trivially)", () => {
    expect(corpus.cases.length).toBeGreaterThanOrEqual(150);
    expect(corpus.rejected.length).toBeGreaterThanOrEqual(15);
  });

  it("the SDK produces exactly the platform's canonical text and bytes for every case", () => {
    const mismatches: string[] = [];
    for (const c of corpus.cases) {
      const text = canonicalJson(c.value);
      if (text !== c.canonical_utf8 || hex(canonicalBytes(c.value)) !== c.canonical_bytes_hex) mismatches.push(c.name);
    }
    expect(mismatches).toEqual([]);
  });

  it("the SDK refuses everything the platform refuses", () => {
    const accepted: string[] = [];
    for (const c of corpus.rejected) {
      try {
        canonicalJson(c.value);
        accepted.push(c.name);
      } catch (error) {
        if (!(error instanceof CanonicalizationError)) throw error;
      }
    }
    expect(accepted).toEqual([]);
  });
});
