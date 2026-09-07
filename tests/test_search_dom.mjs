#!/usr/bin/env node
// tests/test_search_dom.mjs — end-to-end DOM smoke test for the populated
// landing + conclusions-only display (DA-201), driven through the REAL
// public/search.js init() wiring with a tiny DOM shim (no jsdom dependency,
// no network). Requires the built site/ (npm run build first).
//
// Asserts the no-query page shows the landing; a clickable example runs a
// search that hides the landing and renders result cards with a working
// "include incomplete (N)" toggle (incomplete distilled hidden by default,
// surfaced when toggled); browse-all renders capped pages and "load more"
// grows the list. exit 0 = pass.
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");

/* --- minimal DOM shim ---------------------------------------------------- */
function makeNode(tagName) {
  const n = {
    tagName, className: "", value: "", hidden: false, textContent: "",
    childNodes: [], parentNode: null, style: {}, dataset: {}, title: "",
    _cls: new Set(), _attrs: {}, _listeners: {},
    _syncCls() { n.className = [...n._cls].join(" "); },
    classList: {
      add(c) { n._cls.add(c); n._syncCls(); },
      remove(c) { n._cls.delete(c); n._syncCls(); },
      toggle(c, force) {
        const want = force === undefined ? !n._cls.has(c) : !!force;
        want ? n._cls.add(c) : n._cls.delete(c);
        n._syncCls();
      },
      contains(c) { return n._cls.has(c); },
    },
    setAttribute(k, v) {
      n._attrs[k] = String(v);
      if (k === "class") { n._cls = new Set(String(v).split(/\s+/).filter(Boolean)); n.className = String(v); }
      if (k.startsWith("data-")) n.dataset[k.slice(5)] = String(v);
    },
    getAttribute(k) { return n._attrs[k] ?? null; },
    hasAttribute(k) { return k in n._attrs; },
    appendChild(c) { n.childNodes.push(c); c.parentNode = n; return c; },
    replaceChildren(...cs) { n.childNodes.length = 0; cs.forEach((c) => n.appendChild(c)); },
    addEventListener(ev, fn) { (n._listeners[ev] = n._listeners[ev] || []).push(fn); },
    fire(ev, extra) {
      const e = Object.assign({ preventDefault() {}, target: n, key: "" }, extra || {});
      (n._listeners[ev] || []).forEach((fn) => fn(e));
    },
  };
  return n;
}

const registry = [];
const byId = {};
function register(el) { registry.push(el); if (el._attrs && el._attrs.id) byId[el._attrs.id] = el; }
function trackCreate(el) { register(el); return el; }

const documentShim = {
  allNodes: registry,
  createElement(tag) { return trackCreate(makeNode(tag)); },
  createTextNode(t) { return trackCreate(makeNode("#text")).textContent = t, { textContent: t, nodeType: 3 }; },
  getElementById(id) { return byId[id] || null; },
  querySelectorAll(sel) {
    const match = (el) => {
      if (sel === ".chip[data-type]") return el._cls.has("chip") && "data-type" in el._attrs;
      if (sel === "[data-example]") return "data-example" in el._attrs;
      return false;
    };
    const out = registry.filter(match);
    out.forEach = Array.prototype.forEach.bind(out);
    return out;
  },
  _listeners: {},
  addEventListener(ev, fn) { (documentShim._listeners[ev] = documentShim._listeners[ev] || []).push(fn); },
  fireReady() { (documentShim._listeners.DOMContentLoaded || []).forEach((fn) => fn()); },
};

/* --- build the page skeleton index.astro would have produced --------------- */
function el(id, cls, tag = "div") {
  const n = makeNode(tag);
  n.setAttribute("id", id);
  if (cls) n.setAttribute("class", cls);
  register(n);
  return n;
}
const q = el("q", "", "input");
const results = el("results", "results", "ol");
const status = el("status", "status");
const meta = el("meta", "meta");
const statline = el("statline");
const devRow = el("devfilters");
const andRow = el("andfilters");
const landing = el("landing", "landing");
const incwrap = el("incwrap", "incwrap");
const incbtn = el("incbtn", "chip", "button");
const incn = el("incn", "", "span");
incwrap.appendChild(incbtn); incbtn.appendChild(incn);
const morewrap = el("morewrap", "morewrap");
const browseall = el("browseall", "chip browseall", "button");
// result-type chips + example anchors (mirrors src/pages/index.astro)
for (const t of ["all", "docs", "thread", "distilled"]) {
  const b = makeNode("button");
  b.setAttribute("class", "chip" + (t === "all" ? " on" : ""));
  b.setAttribute("data-type", t);
  register(b);
}
const EXAMPLES = ["G7 broadcast", "pod activation", "Android 16 bluetooth", "sensor restart"];
const exampleEls = {};
for (const ex of EXAMPLES) {
  const a = makeNode("a");
  a.setAttribute("class", "chip ex");
  a.setAttribute("data-example", ex);
  a.setAttribute("href", "#q");
  register(a);
  exampleEls[ex] = a;
}

/* --- load search.js against the shim (fresh require sees `document`) ------- */
const data = JSON.parse(readFileSync(join(root, "site", "search-index.json"), "utf8"));
global.window = { __AAPS_INDEX__: data };
global.document = documentShim;

const require2 = (await import("node:module")).createRequire(import.meta.url);
const search = require2(join(root, "site", "search.js"));
if (typeof search.run !== "function") throw new Error("search.js did not load");

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let failures = 0;
const check = (cond, msg) => {
  if (cond) console.log("ok  " + msg); else { failures++; console.error("FAIL " + msg); }
};

try {
  documentShim.fireReady(); // init()
  await sleep(30);

  check(landing.hidden === false, "no query -> landing visible");
  check(results.childNodes.length === 0, "no query -> results empty");
  check(incwrap.hidden === true, "no query -> incomplete toggle hidden");

  // clickable example query runs a real search
  exampleEls["G7 broadcast"].fire("click");
  await sleep(10);
  check(landing.hidden === true, "example search -> landing hidden");
  check(results.childNodes.length > 0, "example search -> results rendered");
  const metaText = meta.textContent || "";
  check(/results for/.test(metaText), "example search -> result meta shown");

  // incomplete-distilled toggle: G7 broadcast windows include incomplete records
  const beforeToggle = results.childNodes.length;
  check(incwrap.hidden === false, "search view -> incomplete toggle surfaced when hidden records exist");
  check((incn.textContent || "") !== "0" && incn.textContent !== "", "search view -> toggle counts hidden records");
  incbtn.fire("click"); // include incomplete
  await sleep(10);
  const afterToggle = results.childNodes.length;
  check(afterToggle > beforeToggle, "toggle -> incomplete distilled included (cards grew)");
  check(incbtn.classList.contains("on"), "toggle -> button shows active state");

  // type directly in the box (input handler -> search mode)
  q.value = "pod activation";
  q.fire("input");
  await sleep(200);
  check(landing.hidden === true && results.childNodes.length > 0, "typing a query -> search results");
  check(/pod activation/.test(meta.textContent || ""), "typing a query -> meta mentions query");

  // clear -> landing again
  q.value = "";
  q.fire("input");
  await sleep(200);
  check(landing.hidden === false, "clearing the query -> landing returns");

  // browse-all entry (count-capped with load more)
  browseall.fire("click");
  await sleep(10);
  check(landing.hidden === true, "browse-all -> landing hidden");
  check(/browsing/.test(meta.textContent || ""), "browse-all -> browsing meta");
  check(results.childNodes.length <= 40, "browse-all -> first page capped at 40");
  const moreBtn = morewrap.childNodes.find((c) => c._listeners && c._listeners.click);
  check(!!moreBtn, "browse-all -> load-more button present");
  if (moreBtn) {
    const beforeMore = results.childNodes.length;
    moreBtn.fire("click");
    await sleep(10);
    check(results.childNodes.length > beforeMore, "browse-all -> load more grows the list");
  }

  // cards carry consistent kind+origin badges (docs/github) and distilled S/C/F
  const hasDistilledCard = results.childNodes.some((li) => {
    const h2 = li.childNodes[0] || {};
    const badges = (h2.childNodes || []).map((c) => c.textContent).join(",");
    return /distilled/.test(badges) && /GitHub/.test(badges);
  });
  check(hasDistilledCard, "cards -> distilled records carry kind + GitHub origin badges");
} catch (err) {
  failures++;
  console.error("FAIL DOM smoke crashed: " + (err && err.stack || err));
}

console.log(failures ? `\n${failures} DOM check(s) failed` : "\nDOM SMOKE PASSED");
process.exit(failures ? 1 : 0);
