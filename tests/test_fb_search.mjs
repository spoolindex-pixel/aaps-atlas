#!/usr/bin/env node
// tests/test_fb_search.mjs — Facebook-source records flow through the same
// search engine + filters as GitHub records (fixture-based, no network).
//
// Uses the exact page algorithm: public/search.js is require()d (byte-identical
// to site/search.js — the Astro build copies public/* into site/). Feeds it a
// hand-built index payload shaped like scripts/build_index.py output for two
// anonymized FB records (one raw thread, one distilled) plus a GitHub thread,
// then asserts:
//   1. a text query hits the FB raw thread as kind "thread",
//   2. device / Android-version chips still tag FB text (scan paths),
//   3. the FB distilled record is searchable and device-tagged via its
//      structured arrays,
//   4. GitHub records are unaffected.
//   node tests/test_fb_search.mjs   (exit 0 = pass)
import { createRequire } from "node:module";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const require = createRequire(import.meta.url);
const { run, build } = require(join(root, "public", "search.js"));

const fbThread = {
  id: "thread:xdrip-users-pfbid0SampleA1xY",
  type: "thread",
  source: "facebook",
  title: "My Dexcom G6 keeps asking for calibration twice a day",
  url: "https://www.facebook.com/groups/584126708394913/posts/pfbid0SampleA1xY/",
  html_url: "https://www.facebook.com/groups/584126708394913/posts/pfbid0SampleA1xY/",
  group: "xDrip+ users",
  group_url: "https://www.facebook.com/groups/584126708394913",
  posted_at: "2025-11-02T09:14:00Z",
  comment_count: 3,
  comments: [
    { pseudonym: "member-d1f084e5", text: "Disable native mode on the transmitter in xDrip+ settings.", posted_at: "2025-11-02T10:40:00Z" },
  ],
  text: "My Dexcom G6 keeps asking for calibration twice a day even though the sensor was pre-calibrated. xDrip+ shows 'calibration needed'. Disable native mode on the transmitter in xDrip+ settings.",
};

const fbDistilled = {
  id: "distilled:androidaps-users-pfbid0SampleB1wT",
  type: "distilled",
  source: "facebook",
  group: "androidaps-users",
  group_url: "https://www.facebook.com/groups/854230771139407",
  title: "G7 companion readings not reaching AndroidAPS",
  url: "https://www.facebook.com/groups/854230771139407/posts/pfbid0SampleB1wT/",
  html_url: "https://www.facebook.com/groups/854230771139407/posts/pfbid0SampleB1wT/",
  confidence: "medium",
  symptom: "Fresh G7 transmitter and AndroidAPS shows no glucose values while the G7 app reads fine.",
  cause: "Companion mode stopped pushing after the G7 app was restarted.",
  fix: "Open the G7 app once, wait for readings, then check the G7 tab in AndroidAPS.",
  settings_changed: [],
  devices: ["G7"],
  android_versions: [],
  driver_tags: ["companion app", "broadcast"],
  evidence_quote: "Open the G7 app once, wait for readings, then check the G7 tab in AndroidAPS.",
  text: "G7 companion readings not reaching AndroidAPS Fresh G7 transmitter and AndroidAPS shows no glucose values G7 companion app broadcast Open the G7 app once, wait for readings, then check the G7 tab in AndroidAPS.",
};

const ghThread = {
  id: "thread:xdrip-628",
  type: "thread",
  title: "Android 9 - xDrip+ - Miaomiao - BT disconnecting",
  html_url: "https://github.com/NightscoutFoundation/xDrip/issues/628",
  repo: "NightscoutFoundation/xDrip",
  number: 628,
  labels: [],
  comment_count: 52,
  text: "Android 9 xDrip+ Miaomiao bluetooth disconnecting on OnePlus6.",
};

const data = {
  meta: { counts: { docs: 0, threads: 2, distilled: 1 } },
  docs: [],
  threads: [ghThread, fbThread],
  distilled: [fbDistilled],
};

let failed = 0;
const fail = (msg) => { console.error("FAIL: " + msg); failed++; };

// 1. text query hits the FB raw thread as kind "thread"
const hits = run(data, "calibration needed", { limit: 25 });
const fbHit = hits.find((h) => h.rec.id === fbThread.id);
if (!fbHit || fbHit.kind !== "thread") fail("FB raw thread not returned as kind=thread for 'calibration needed'");
else if (fbHit.url !== fbThread.url) fail("FB hit url != post permalink");

// 2. device / android chips still tag FB text (scan-based paths)
const idx = build(data);
const fbIdx = idx.recs.find((r) => r.id === fbThread.id);
if (fbIdx) {
  if (!(fbIdx.tags || []).includes("G6")) fail("FB text not tagged with G6 chip");
  if (!(fbIdx.tags || []).includes("Dexcom")) fail("FB text not tagged with Dexcom chip");
} else fail("FB thread missing from index");
const ghIdx = idx.recs.find((r) => r.id === ghThread.id);
if (!ghIdx || !ghIdx.title) fail("GitHub thread dropped by the extra source type");

// 3. FB distilled record searchable + device-tagged via structured arrays
const dHits = run(data, "companion broadcast AndroidAPS", { limit: 25 });
const dHit = dHits.find((h) => h.rec.id === fbDistilled.id);
if (!dHit || dHit.kind !== "distilled") fail("FB distilled record not returned for 'companion broadcast AndroidAPS'");
const dIdx = idx.recs.find((r) => r.id === fbDistilled.id);
if (!dIdx || !(dIdx.tags || []).includes("G7")) fail("FB distilled structured device G7 not tagged");

// 4. every index record keeps its attribution url
for (const r of idx.recs) {
  if (!r.url && r.kind !== "docs") fail(`record ${r.id} missing attribution url`);
}

console.log(failed ? `${failed} check(s) failed` : "FB SEARCH CHECKS PASSED");
process.exit(failed ? 1 : 0);
