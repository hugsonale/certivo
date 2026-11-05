import { defineConfig } from "@playwright/test";

// The overhead harness (guide P0-27). Run with: npm run overhead
// It is a long, quiet measurement (about 7 minutes for each slowdown setting with the defaults), so it has its own config and is not part of CI.
export default defineConfig({
  testDir: "overhead",
  testMatch: "**/*.spec.ts",
  timeout: 60 * 60_000,
  retries: 0,
  workers: 1,
  reporter: [["list"]],
});
