// Copies the agent's latest answers and traces into the UI's offline fixtures so the mock layer shows every case.
//   npm run sync-fixtures
import { copyFileSync, existsSync, mkdirSync, readdirSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const web = join(dirname(fileURLToPath(import.meta.url)), "..");
const root = join(web, "..");
const pairs = [
  [join(root, "cases"), join(web, "src", "fixtures", "cases")],
  [join(root, "runs", "traces"), join(web, "src", "fixtures", "traces")],
];
let n = 0;
for (const [src, dst] of pairs) {
  if (!existsSync(src)) continue;
  mkdirSync(dst, { recursive: true });
  for (const f of readdirSync(src)) {
    if (!f.endsWith(".json")) continue;
    copyFileSync(join(src, f), join(dst, f));
    n++;
  }
}
const report = join(root, "eval", "report.json");
if (existsSync(report)) {
  copyFileSync(report, join(web, "src", "fixtures", "backtest_report.json"));
  n++;
}
console.log(`synced ${n} fixture file(s)`);
