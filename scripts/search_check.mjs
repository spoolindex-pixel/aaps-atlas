#!/usr/bin/env node
// AAPS Atlas search acceptance check. Runs the SAME search.js the site uses
// (module.exports path) against the built site/search-index.json.
//   node scripts/search_check.mjs
//
// Fails (exit 1) when:
//   - corpus under target, or a record lacks attribution, or
//   - any canonical demo query returns no docs AND no thread hits, or the
//     "G7 broadcast" demo query returns no complete distilled record
//     (complete = symptom AND cause AND fix — the default conclusions-only
//     view would hide anything less), or
//   - the completeness contract regresses: a distilled record missing one
//     part is excluded by default and included only with the toggle, or
//   - the built landing page (site/index.html) does not render the
//     populated no-query state: example queries + doc-guide links + top
//     distilled records + browse-all + the include-incomplete toggle.
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { spawnSync } from "node:child_process";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const require = createRequire(import.meta.url);
const search = require(join(root, "site", "search.js"));
const { run, isDistilledComplete, conclusionsOnly, countIncompleteDistilled } = search;
let data;
try {
  data = JSON.parse(readFileSync(join(root, "site", "search-index.json"), "utf8"));
} catch (err) {
  console.error("FAIL: cannot read site/search-index.json — run scripts/build_index.py first:", err.message);
  process.exit(1);
}

const counts = data.meta.counts;
// Demo queries surfaced as clickable examples on the landing page — each must
// return hits (docs AND threads) or it must not be listed there.
const queries = ["G7 broadcast", "pod activation", "Android 16 bluetooth", "sensor restart"];
const GUIDE_HREFS = [
  "/docs/dexcom-g7.html", "/docs/omnipod-dash.html", "/docs/xdrip-app.html",
  "/docs/building-aaps.html", "/docs/browser-build.html", "/docs/xdrip-g7.html",
];
let failed = 0;
const fail = (msg) => { console.error(`FAIL ${msg}`); failed++; };

const badDocs = (data.docs || []).filter((d) => !d.source_url);
const badThreads = (data.threads || []).filter((t) => !t.html_url);
const badDistilled = (data.distilled || []).filter((d) => !d.url || !d.html_url);
if (counts.docs < 6) { fail(`docs ${counts.docs} < 6`); }
if (counts.threads < 45) { fail(`threads ${counts.threads} < 45`); }
if ((counts.distilled || 0) < 45) { fail(`distilled ${counts.distilled || 0} < 45 (run scripts/distill.py batches)`); }
if (badDocs.length || badThreads.length || badDistilled.length) {
  fail(`attribution missing: ${badDocs.length} docs, ${badThreads.length} threads, ${badDistilled.length} distilled`);
}
console.log(`corpus: ${counts.docs} docs, ${counts.threads} threads, ${counts.distilled} distilled`);

/* --- demo queries (default conclusions-only view matches the real UX) ---- */
for (const q of queries) {
  const hits = run(data, q, { limit: 25 });
  const docs = hits.filter((h) => h.kind === "docs").length;
  const thr = hits.filter((h) => h.kind === "thread").length;
  const dis = hits.filter((h) => h.kind === "distilled").length;
  const disComplete = hits.filter((h) => h.kind === "distilled" && isDistilledComplete(h.rec)).length;
  const top = hits.slice(0, 5).map((h) => `  [${h.kind}] ${h.title} (score ${h.score.toFixed(1)})`).join("\n");
  console.log(`query "${q}" -> ${hits.length} hits (${disComplete} complete-distilled / ${dis} distilled / ${thr} threads / ${docs} docs)\n${top}`);
  if (docs < 1 || thr < 1) { fail(`"${q}": need hits across docs AND threads`); }
  if (q === "G7 broadcast" && disComplete < 1) {
    fail('"G7 broadcast": need >= 1 COMPLETE distilled hit (the default conclusions-only view shows only S+C+F records)');
  }
}

/* --- completeness contract unit check (DA-201) --------------------------- */
// A distilled record missing ANY of symptom/cause/fix is hidden by default
// and surfaced only by the include-incomplete toggle; raw records unaffected.
function dist(id, title, parts) {
  return { id, type: "distilled", title, issue_id: 1, repo: "nightscout/AndroidAPS",
    url: "https://github.com/nightscout/AndroidAPS/issues/1",
    html_url: "https://github.com/nightscout/AndroidAPS/issues/1",
    confidence: "high", settings_changed: [], devices: [], android_versions: [],
    driver_tags: [], evidence_quote: "",
    symptom: parts.symptom, cause: parts.cause, fix: parts.fix,
    text: `unitmark ${title} ${parts.symptom || ""} ${parts.cause || ""} ${parts.fix || ""}` };
}
const completeRec = dist("distilled:unit-complete", "Complete unit record",
  { symptom: "symptom a", cause: "cause a", fix: "fix a" });
const missingFix = dist("distilled:unit-missing-fix", "Missing fix record",
  { symptom: "symptom b", cause: "cause b" }); // no fix
const missingCause = dist("distilled:unit-missing-cause", "Missing cause record",
  { symptom: "symptom c", fix: "fix c" }); // no cause
const unitData = { meta: { counts: { docs: 0, threads: 0, distilled: 3 } },
  docs: [], threads: [], distilled: [completeRec, missingFix, missingCause] };
const unitHits = run(unitData, "unitmark", { limit: 10 });
const unitHidden = countIncompleteDistilled(unitHits);
const unitDefault = conclusionsOnly(unitHits, false);
const unitToggled = conclusionsOnly(unitHits, true);
if (unitHits.length !== 3) { fail(`completeness unit: synthetic query should match 3 distilled records, got ${unitHits.length}`); }
if (unitHidden !== 2) { fail(`completeness unit: expect 2 incomplete distilled (missing fix + missing cause), counted ${unitHidden}`); }
if (unitDefault.length !== 1 || unitDefault[0].rec.id !== "distilled:unit-complete") {
  fail("completeness unit: default view must exclude incomplete distilled (show only the complete record)");
}
if (unitToggled.length !== 3) {
  fail("completeness unit: include-incomplete toggle must surface the hidden records");
}
if (!isDistilledComplete(completeRec) || isDistilledComplete(missingFix) || isDistilledComplete(missingCause)) {
  fail("completeness unit: isDistilledComplete must require symptom AND cause AND fix");
}
console.log(`completeness unit: missing-fix + missing-cause distilled excluded by default (${unitDefault.length} of ${unitHits.length}), included with toggle (${unitToggled.length} of ${unitHits.length})`);

/* --- populated landing state in the built page (DA-201) ------------------- */
let html = "";
try {
  html = readFileSync(join(root, "site", "index.html"), "utf8");
} catch (err) {
  fail(`cannot read site/index.html — run npm run astro first: ${err.message}`);
}
if (html) {
  if (!html.includes('id="landing"')) { fail("landing: site/index.html must contain the populated landing section (#landing)"); }
  for (const q of queries) {
    if (!html.includes(`data-example="${q}"`)) { fail(`landing: example query "${q}" missing from site/index.html`); }
  }
  for (const href of GUIDE_HREFS) {
    if (!html.includes(href)) { fail(`landing: doc-guide link ${href} missing from site/index.html`); }
  }
  const topCards = (html.match(/class="card toprec"/g) || []).length;
  if (topCards < 1) { fail("landing: no top distilled record cards (class \"card toprec\") in site/index.html"); }
  const symptomRows = (html.match(/<span class="k">Symptom<\/span>/g) || []).length;
  if (symptomRows < 1) { fail("landing: top records must render the Symptom -> Cause -> Fix sections, found none"); }
  const causeRows = (html.match(/<span class="k">Cause<\/span>/g) || []).length;
  const fixRows = (html.match(/<span class="k">Fix<\/span>/g) || []).length;
  if (causeRows !== symptomRows || fixRows !== symptomRows) {
    fail(`landing: top record cards must render all three sections distinctly (S/C/F rows: ${symptomRows}/${causeRows}/${fixRows})`);
  }
  if (!html.includes('id="browseall"')) { fail("landing: browse-all entry (#browseall) missing from site/index.html"); }
  if (!html.includes('id="incbtn"')) { fail("landing: include-incomplete toggle (#incbtn) missing from site/index.html"); }
  console.log(`landing: ${queries.length} examples, ${GUIDE_HREFS.length} guide links, ${topCards} top record cards (${symptomRows} S/C/F rows), browse-all + toggle present`);

/* --- interactive wiring smoke test (real search.js + DOM shim) ----------- */
// Drives the landing/browse/toggle behaviour through init() with a tiny DOM
// shim; any exception or failed assertion fails the build.
const dom = spawnSync(process.execPath, [join(root, "tests", "test_search_dom.mjs")],
  { cwd: root, stdio: "inherit" });
if (dom.status !== 0) {
  fail("DOM smoke test (tests/test_search_dom.mjs) did not pass");
}
}

console.log(failed ? `\n${failed} check(s) failed` : "\nALL CHECKS PASSED");
process.exit(failed ? 1 : 0);
