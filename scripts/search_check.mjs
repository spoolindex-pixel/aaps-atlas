#!/usr/bin/env node
// AAPS Atlas search acceptance check. Runs the SAME search.js the site uses
// (module.exports path) against the built site/search-index.json.
//   node scripts/search_check.mjs
// Fails (exit 1) when: corpus under target, a record lacks attribution, or
// any canonical demo query returns no docs AND no thread hits.
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
if (counts.docs < 6) { console.error(`FAIL docs ${counts.docs} < 6`); failed++; }
if (counts.threads < 45) { console.error(`FAIL threads ${counts.threads} < 45`); failed++; }
if (badDocs.length || badThreads.length) {
  console.error(`FAIL attribution missing: ${badDocs.length} docs, ${badThreads.length} threads`);
  failed++;
}

for (const q of queries) {
  const hits = run(data, q, { limit: 25 });
  const docs = hits.filter((h) => h.kind === "docs").length;
  const thr = hits.filter((h) => h.kind === "thread").length;
  const top = hits.slice(0, 5).map((h) => `  [${h.kind}] ${h.title} (score ${h.score.toFixed(1)})`).join("\n");
  console.log(`query "${q}" -> ${hits.length} hits (${thr} threads / ${docs} docs)\n${top}`);
  if (docs < 1 || thr < 1) { console.error(`FAIL "${q}": need hits across docs AND threads`); failed++; }
}

console.log(failed ? `\n${failed} check(s) failed` : "\nALL CHECKS PASSED");
process.exit(failed ? 1 : 0);
