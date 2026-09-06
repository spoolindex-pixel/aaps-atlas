#!/usr/bin/env node
// AAPS Atlas search acceptance check. Runs the SAME search.js the site uses
// (module.exports path) against the built site/search-index.json.
//   node scripts/search_check.mjs
// Fails (exit 1) when: corpus under target, a record lacks attribution, any
// canonical demo query returns no docs AND no thread hits, or the "G7
// broadcast" demo query returns no distilled record.
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const require = createRequire(import.meta.url);
const { run } = require(join(root, "site", "search.js"));
let data;
try {
  data = JSON.parse(readFileSync(join(root, "site", "search-index.json"), "utf8"));
} catch (err) {
  console.error("FAIL: cannot read site/search-index.json — run scripts/build_index.py first:", err.message);
  process.exit(1);
}

const counts = data.meta.counts;
const queries = ["G7 broadcast", "pod activation", "Android 16 bluetooth"];
let failed = 0;

const badDocs = (data.docs || []).filter((d) => !d.source_url);
const badThreads = (data.threads || []).filter((t) => !t.html_url);
const badDistilled = (data.distilled || []).filter((d) => !d.url || !d.html_url);
if (counts.docs < 6) { console.error(`FAIL docs ${counts.docs} < 6`); failed++; }
if (counts.threads < 45) { console.error(`FAIL threads ${counts.threads} < 45`); failed++; }
if ((counts.distilled || 0) < 45) {
  console.error(`FAIL distilled ${counts.distilled || 0} < 45 (run scripts/distill.py batches)`);
  failed++;
}
if (badDocs.length || badThreads.length || badDistilled.length) {
  console.error(`FAIL attribution missing: ${badDocs.length} docs, ${badThreads.length} threads, ${badDistilled.length} distilled`);
  failed++;
}
console.log(`corpus: ${counts.docs} docs, ${counts.threads} threads, ${counts.distilled} distilled`);

for (const q of queries) {
  const hits = run(data, q, { limit: 25 });
  const docs = hits.filter((h) => h.kind === "docs").length;
  const thr = hits.filter((h) => h.kind === "thread").length;
  const dis = hits.filter((h) => h.kind === "distilled").length;
  const top = hits.slice(0, 6).map((h) => `  [${h.kind}] ${h.title} (score ${h.score.toFixed(1)})`).join("\n");
  console.log(`query "${q}" -> ${hits.length} hits (${dis} distilled / ${thr} threads / ${docs} docs)\n${top}`);
  if (docs < 1 || thr < 1) { console.error(`FAIL "${q}": need hits across docs AND threads`); failed++; }
  if (q === "G7 broadcast" && dis < 1) {
    console.error('FAIL "G7 broadcast": need >= 1 distilled hit (filter demo coverage)');
    failed++;
  }
}

console.log(failed ? `\n${failed} check(s) failed` : "\nALL CHECKS PASSED");
process.exit(failed ? 1 : 0);
