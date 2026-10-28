/**
 * Structural guards (P0-21, docs/adr/0021). They read the source code itself, and fail when a rule that
 * protects people is broken. They are a STATIC check: they catch a careless change early and cheaply.
 * They are not proof that no media can leave the page. That proof is the runtime network-interception
 * test in P0-24.
 */
import { existsSync, readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const PACKAGES = ["types", "core", "capture", "inference", "ui", "sdk"] as const;
type Pkg = (typeof PACKAGES)[number];

/** Which @certivo packages each package may import. Everything else is a mistake. */
const ALLOWED_IMPORTS: Record<Pkg, readonly string[]> = {
  types: [],
  core: ["@certivo/sdk-types"],
  capture: ["@certivo/sdk-types"],
  inference: ["@certivo/sdk-types"],
  ui: ["@certivo/sdk-types"],
  sdk: ["@certivo/sdk-types", "@certivo/sdk-core", "@certivo/sdk-capture", "@certivo/sdk-inference", "@certivo/sdk-ui"],
};

/** Ways a frame could leave the page, be kept, or be turned into bytes. Never allowed where frames live. */
const FRAME_EGRESS = [
  /\bfetch\s*\(/,
  /\bXMLHttpRequest\b/,
  /\bWebSocket\b/,
  /\bsendBeacon\b/,
  /\bEventSource\b/,
  /\bRTCPeerConnection\b/,
  /\bRTCDataChannel\b/,
  /\bimportScripts\b/,
  /\bindexedDB\b/,
  /\blocalStorage\b/,
  /\bsessionStorage\b/,
  /\bcaches\b/,
  /\bnavigator\.storage\b/,
  /\bshowSaveFilePicker\b/,
  /\bFileReader\b/,
  /\btoDataURL\b/,
  /\btoBlob\b/,
  /\bconvertToBlob\b/,
  /\bMediaRecorder\b/,
  /\bcaptureStream\b/,
  /\bcreateObjectURL\b/,
];

/** Pixel types. The packages that talk to the platform and draw the indicator must never see pictures. */
const PIXEL_TYPES = [
  /\bImageBitmap\b/,
  /\bImageData\b/,
  /\bVideoFrame\b/,
  /\bgetImageData\b/,
  /\bHTMLCanvasElement\b/,
  /\bHTMLVideoElement\b/,
  /\bOffscreenCanvas\b/,
];

const root = join(__dirname, "..", "packages");

function sourceFiles(pkg: Pkg): string[] {
  const dir = join(root, pkg, "src");
  return existsSync(dir)
    ? readdirSync(dir)
        .filter((f) => f.endsWith(".ts"))
        .map((f) => join(dir, f))
    : [];
}

/** Removes comments so a sentence that merely MENTIONS fetch() does not trip the check. */
function stripComments(source: string): string {
  return source.replace(/\/\*[\s\S]*?\*\//g, "").replace(/(^|[^:"'`])\/\/.*$/gm, "$1");
}

function findViolations(source: string, patterns: RegExp[]): string[] {
  const code = stripComments(source);
  return patterns.filter((p) => p.test(code)).map((p) => p.source);
}

const importsOf = (source: string): string[] =>
  [...stripComments(source).matchAll(/\b(?:from|import)\s*\(?\s*["']([^"']+)["']/g)].map((m) => m[1] as string);

describe("the guard itself works", () => {
  it("finds a forbidden call in real code, but not in a comment", () => {
    expect(findViolations("const r = await fetch(url);", FRAME_EGRESS)).not.toEqual([]);
    expect(findViolations("canvas.toBlob(cb)", FRAME_EGRESS)).not.toEqual([]);
    expect(findViolations("// we never call fetch( here\n/* localStorage */ const a = 1;", FRAME_EGRESS)).toEqual([]);
  });
  it("finds imports", () => {
    expect(importsOf(`import { a } from "@certivo/sdk-core";\nexport * from "./x";`)).toEqual([
      "@certivo/sdk-core",
      "./x",
    ]);
  });
});

describe("package boundaries", () => {
  for (const pkg of PACKAGES) {
    it(`${pkg} imports only what it is allowed to`, () => {
      for (const file of sourceFiles(pkg)) {
        for (const spec of importsOf(readFileSync(file, "utf8"))) {
          if (spec.startsWith(".")) continue;
          expect(ALLOWED_IMPORTS[pkg], `${file} imports ${spec}`).toContain(spec);
        }
      }
    });

    it(`${pkg}'s package.json declares exactly the packages it imports`, () => {
      const manifest = JSON.parse(readFileSync(join(root, pkg, "package.json"), "utf8")) as {
        dependencies?: Record<string, string>;
      };
      const used = new Set<string>();
      for (const file of sourceFiles(pkg)) {
        for (const spec of importsOf(readFileSync(file, "utf8"))) if (spec.startsWith("@certivo/")) used.add(spec);
      }
      const declared = Object.keys(manifest.dependencies ?? {}).filter((d) => d.startsWith("@certivo/"));
      for (const spec of used) expect(declared, `${pkg} imports ${spec} without declaring it`).toContain(spec);
      expect(declared.sort(), `${pkg} declares a package it does not import`).toEqual([...used].sort());
    });
  }

  it("capture and inference do not know about each other or about core", () => {
    for (const pkg of ["capture", "inference"] as const) {
      for (const file of sourceFiles(pkg)) {
        for (const spec of importsOf(readFileSync(file, "utf8"))) {
          expect(spec, `${file}`).not.toMatch(/sdk-(core|capture|inference|ui)$/);
        }
      }
    }
  });
});

describe("a frame can never leave the page or be kept (guide Part 3; full proof is P0-24)", () => {
  for (const pkg of ["capture", "inference", "ui", "types"] as const) {
    it(`${pkg} has no network, storage or picture-encoding code`, () => {
      for (const file of sourceFiles(pkg)) {
        expect(findViolations(readFileSync(file, "utf8"), FRAME_EGRESS), file).toEqual([]);
      }
    });
  }

  it("capture and ui send no messages anywhere", () => {
    for (const pkg of ["capture", "ui"] as const) {
      for (const file of sourceFiles(pkg)) {
        expect(findViolations(readFileSync(file, "utf8"), [/\bpostMessage\b/]), file).toEqual([]);
      }
    }
  });

  it("only core's session client may use the network, and nothing there touches pictures", () => {
    const users: string[] = [];
    for (const pkg of PACKAGES) {
      for (const file of sourceFiles(pkg)) {
        if (findViolations(readFileSync(file, "utf8"), [/\bfetch\b/]).length) users.push(file.slice(root.length + 1));
      }
    }
    expect(users).toEqual([join("core", "src", "session-client.ts")]);
  });

  it("the packages that talk to the platform or draw the indicator never see a picture", () => {
    for (const pkg of ["core", "ui", "types", "sdk"] as const) {
      for (const file of sourceFiles(pkg)) {
        expect(findViolations(readFileSync(file, "utf8"), PIXEL_TYPES), file).toEqual([]);
      }
    }
  });

  it("only the inference package defines the picture-carrying messages", () => {
    const code = stripComments(readFileSync(join(root, "inference", "src", "protocol.ts"), "utf8"));
    expect(code).toMatch(/image: ImageBitmap/);
    // ...and what comes OUT of inference is numbers and code words only:
    const result = readFileSync(join(root, "types", "src", "index.ts"), "utf8");
    const body = /interface ScoreResult \{([\s\S]*?)\}/.exec(result)?.[1] ?? "";
    expect([...body.matchAll(/^\s*readonly (\w+):/gm)].map((m) => m[1]).sort()).toEqual([
      "confidence",
      "modelVersion",
      "reasonCodes",
    ]);
  });
});
