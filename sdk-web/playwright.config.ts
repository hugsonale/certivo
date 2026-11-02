import { defineConfig } from "@playwright/test";

// The real-browser tests (guide P0-24). Run with: npm run test:browser
// Chromium is the gate for now. Firefox and Safari are added when the SDK has a model to test (P0-37).
export default defineConfig({
  testDir: "e2e",
  testMatch: "**/*.spec.ts",
  timeout: 120_000,
  retries: 0,
  workers: 1,
  reporter: [["list"]],
  use: {
    browserName: "chromium",
    launchOptions: { args: ["--autoplay-policy=no-user-gesture-required"] },
  },
});
