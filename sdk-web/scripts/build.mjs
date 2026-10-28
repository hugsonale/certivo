// Builds the two files a partner loads: the SDK, and the inference worker (the model runs inside the worker).
import { mkdirSync, rmSync } from "node:fs";
import { build } from "esbuild";

rmSync("dist", { recursive: true, force: true });
mkdirSync("dist", { recursive: true });

const common = {
  bundle: true,
  minify: true,
  target: "es2022",
  platform: "browser",
  legalComments: "none",
  logLevel: "warning",
};

await build({ ...common, entryPoints: ["packages/sdk/src/index.ts"], format: "esm", outfile: "dist/certivo-sdk.js" });
// A classic (non-module) worker script, so it works in every browser.
await build({
  ...common,
  entryPoints: ["packages/inference/src/worker-entry.ts"],
  format: "iife",
  outfile: "dist/certivo-inference-worker.js",
});

console.log("built dist/certivo-sdk.js and dist/certivo-inference-worker.js");
