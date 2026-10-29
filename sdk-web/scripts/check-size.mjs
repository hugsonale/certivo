// Fails if a built file is larger than its budget in size-budget.json (the bundle-size gate, guide P0-21).
// Size = gzip level 9, which is close to what a browser downloads.
import { readdirSync, readFileSync } from "node:fs";
import { gzipSync } from "node:zlib";

const budget = JSON.parse(readFileSync("size-budget.json", "utf8"));
const files = readdirSync("dist").filter((f) => f.endsWith(".js"));
let failed = false;
let total = 0;

const row = (name, size, max) => {
  const pct = ((size / max) * 100).toFixed(0).padStart(3);
  const flag = size > max ? "OVER BUDGET" : "ok";
  console.log(
    `${name.padEnd(34)} ${String(size).padStart(7)} B gzip   budget ${String(max).padStart(7)} B  (${pct}%)  ${flag}`,
  );
};

for (const [name, { maxGzipBytes }] of Object.entries(budget.files)) {
  if (!files.includes(name)) {
    console.error(`MISSING: ${name} is in size-budget.json but was not built`);
    failed = true;
    continue;
  }
  const size = gzipSync(readFileSync(`dist/${name}`), { level: 9 }).length;
  total += size;
  row(name, size, maxGzipBytes);
  if (size > maxGzipBytes) failed = true;
}
for (const name of files) {
  if (!(name in budget.files)) {
    console.error(`NO BUDGET: dist/${name} was built but has no entry in size-budget.json. Add one on purpose.`);
    failed = true;
  }
}
row("TOTAL", total, budget.totalMaxGzipBytes);
if (total > budget.totalMaxGzipBytes) failed = true;

if (failed) {
  console.error(
    "\nSize check FAILED. Make the code smaller, or (with a written reason in the pull request) raise the budget in size-budget.json.",
  );
  process.exit(1);
}
console.log("\nSize check passed.");
