/* AAPS Atlas search — plain vanilla JS, no framework, no CDN.
 *
 * Runs identically in the browser and in Node (module.exports), so the
 * node harness (scripts/search_check.mjs) verifies the exact algorithm the
 * page uses. The corpus index is prebuilt by scripts/build_index.py:
 *   site/search-index.json (served over http) or
 *   site/search-data.js     (window.__AAPS_INDEX__, needed for file://).
 *
 * Three record kinds: docs (mirror pages), thread (raw GitHub issue, or an
 * anonymized Facebook group post when the record's `source` is "facebook")
 * and distilled (LLM symptom->cause->fix extraction of a thread, always
 * linked back to its source issue / post). Filters: result type + device
 * tags + Android versions. Device tags are canonicalised (G7 / G6 / DASH /
 * Omnipod 5 / Libre / Medtrum / Dexcom / Eversense); threads/docs match via
 * their text, distilled records via their validated structured arrays.
 * Facebook cards carry an "FB community" origin badge and link back to the
 * original post permalink (kept for verification); authors are pseudonyms.
 *
 * Display contract (UX pass DA-201):
 *  - Conclusions-only: distilled cards only ever show complete S->C->F
 *    records by default. A distilled record missing symptom, cause or fix
 *    is hidden unless the "include incomplete (N)" toggle is on. Raw
 *    thread/docs records are unaffected. isDistilledComplete /
 *    conclusionsOnly / countIncompleteDistilled implement this and are
 *    exported so the acceptance harness can unit-check it.
 *  - Populated landing: with no query the page shows clickable example
 *    queries + doc-guide links + a small set of top distilled records +
 *    a browse-all entry (see index.astro). search.js only toggles the
 *    landing element and runs browse mode here.
 *
 * Scoring (unchanged MiniSearch core): per-record term frequency weighted by
 * field (title 5x, labels 3x, body 1x) x corpus idf; full-query-overlap
 * records are floated to the top.
 */
((root, factory) => {
  var api = factory();
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  if (root) root.AAPS_SEARCH = api;
})(typeof window === "undefined" ? null : window, () => {

  var STOP = new Set(("the a an and or for to of in on is are was be with it this " +
    "that you your not no from at by i as had have has into how what when where who which " +
    "will would can could should do does did done if then than them they we us our also but " +
    "there here out via than much more most less some any all").split(" "));

  // Domain synonyms: in AAPS/xDrip usage "broadcast", "companion mode" and
  // "BYODA" all describe the same G7/G6-data delivery path to AAPS/xDrip.
  var EXPAND = {
    broadcast: ["broadcast", "companion", "byoda"],
    companion: ["companion", "broadcast", "byoda"],
    byoda: ["byoda", "broadcast"],
  };

  // Canonical device filter vocabulary. CGM/pump families only (phone models
  // stay visible on cards but are not filter chips).
  var DEVICE_ORDER = ["G7", "G6", "DASH", "Omnipod 5", "Libre", "Medtrum", "Dexcom", "Eversense"];

  // Text patterns used to tag docs/threads (distilled records use their
  // validated structured arrays instead).
  var DEVICE_PATTERNS = [
    { re: /\b(?:dexcom\s+)?g7\b/i, tag: "G7" },
    { re: /\b(?:dexcom\s+)?g6\b/i, tag: "G6" },
    { re: /\bomnipod\s*dash\b/i, tag: "DASH" },
    { re: /\bomnipod\s*5\b/i, tag: "Omnipod 5" },
    { re: /\blibre\b/i, tag: "Libre" },
    { re: /\bmedtrum\b/i, tag: "Medtrum" },
    { re: /\bdexcom\b/i, tag: "Dexcom" },
    { re: /\beversense\b/i, tag: "Eversense" },
  ];
  var ANDROID_RE = /\bandroid\s+(\d+(?:\.\d+)?)\b/gi;

  function canonDevice(entry) {
    // Canonicalise one structured device/driver string to a filter tag.
    var s = String(entry || "").toLowerCase().replace(/[^a-z0-9]+/g, " ");
    s = s.replace(/^\s+|\s+$/g, "");
    if (!s) return null;
    if (s === "g7" || s === "dexcom g7") return "G7";
    if (s === "g6" || s === "dexcom g6") return "G6";
    if (s.indexOf("omnipod") !== -1 && s.indexOf("dash") !== -1) return "DASH";
    if (s.indexOf("omnipod") !== -1 && (s === "omnipod 5" || /omnipod 5|omnipod5/.test(s))) return "Omnipod 5";
    if (s.indexOf("libre") !== -1) return "Libre";
    if (s.indexOf("medtrum") !== -1) return "Medtrum";
    if (s.indexOf("dexcom") !== -1) return "Dexcom";
    if (s.indexOf("eversense") !== -1) return "Eversense";
    return null; // phones / pumps outside the chip vocabulary
  }

  function hostOf(url) {
    var m = /^https?:\/\/([^/:?#]+)/.exec(String(url || ""));
    return m ? m[1].replace(/^www\./, "") : "";
  }

  function scanTags(text) {
    var tags = {};
    var lower = String(text || "").toLowerCase();
    DEVICE_PATTERNS.forEach((p) => { if (p.re.test(lower)) tags[p.tag] = 1; });
    return Object.keys(tags);
  }

  function scanAndroid(text) {
    var out = {};
    var m;
    var t = String(text || "");
    while ((m = ANDROID_RE.exec(t)) !== null) {
      if (m[1] && +m[1] >= 8) out["Android " + m[1]] = 1;
    }
    return Object.keys(out);
  }

  function fold(s) {
    return s.normalize ? s.normalize("NFKD").replace(/[\u0300-\u036f]/g, "") : s;
  }

  function terms(s) {
    return fold(String(s || "").toLowerCase()).split(/[^a-z0-9]+/).filter((t) => t.length > 1 && !STOP.has(t));
  }

  function count(tokens) {
    var m = {};
    tokens.forEach((t) => { m[t] = (m[t] || 0) + 1; });
    return m;
  }

  function build(data) {
    var recs = [];
    (data.docs || []).forEach((d) => {
      var hay = d.title + " " + d.text;
      recs.push({ kind: "docs", id: d.id, title: d.title || d.slug,
        url: "docs/" + d.slug + ".html", source: d.source_url || "", rec: d,
        titleTf: count(terms(d.title)), textTf: count(terms(d.text)),
        tags: scanTags(hay), android: scanAndroid(hay) });
    });
    (data.threads || []).forEach((t) => {
      var titleText = (t.title || "") + " " + (t.labels || []).join(" ");
      var hay = titleText + " " + t.text;
      recs.push({ kind: "thread", id: t.id, title: t.title || (t.repo + "#" + t.number),
        url: t.html_url || "", source: t.html_url || "", rec: t,
        titleTf: count(terms(titleText)), textTf: count(terms(t.text)),
        tags: scanTags(hay), android: scanAndroid(hay) });
    });
    (data.distilled || []).forEach((dt) => {
      var tags = {};
      (dt.devices || []).concat(dt.driver_tags || []).forEach((e) => {
        var tag = canonDevice(e);
        if (tag) tags[tag] = 1;
      });
      var androids = {};
      (dt.android_versions || []).forEach((v) => { androids[v] = 1; });
      recs.push({ kind: "distilled", id: dt.id, title: dt.title || "issue " + dt.issue_id,
        url: dt.url || "", source: dt.html_url || "", rec: dt,
        titleTf: count(terms(dt.title)), textTf: count(terms(dt.text)),
        tags: Object.keys(tags), android: Object.keys(androids) });
    });
    // document frequencies for idf
    var df = {};
    recs.forEach((r) => {
      var seen = {};
      Object.keys(r.titleTf).forEach((t) => { seen[t] = 1; });
      Object.keys(r.textTf).forEach((t) => { seen[t] = 1; });
      Object.keys(seen).forEach((t) => { df[t] = (df[t] || 0) + 1; });
    });
    return { recs: recs, df: df };
  }

  /* --- snippet: 2-line window around the first matched term ------------- */
  function snippet(rec, qtokens) {
    var text = rec.rec.text || "";
    var hay = fold(text.toLowerCase());
    var best = -1;
    for (var i = 0; i < qtokens.length; i++) {
      var at = hay.indexOf(qtokens[i]);
      if (at !== -1 && (best === -1 || at < best)) best = at;
    }
    if (best === -1 || !text) return text.slice(0, 240);
    var start = Math.max(0, best - 80);
    var end = Math.min(text.length, start + 300);
    if (start > 0) start = hay.indexOf(" ", start) + 1;
    var pre = start > 0 ? "…" : "";
    var post = end < text.length ? "…" : "";
    return pre + text.slice(start, end).replace(/\s+/g, " ") + post;
  }

  /* --- main entry -------------------------------------------------------- */
  function tfMax(aliases, tf) {
    var m = 0;
    aliases.forEach((a) => { if ((tf[a] || 0) > m) m = tf[a]; });
    return m;
  }

  function run(data, query, opts) {
    opts = opts || {};
    var limit = opts.limit || 25;
    var qterms = terms(query);
    if (!qterms.length) return [];
    var idx = build(data);
    var n = idx.recs.length;
    var scored = [];
    idx.recs.forEach((r) => {
      var matched = 0;
      var score = 0;
      qterms.forEach((t) => {
        var aliases = EXPAND[t] || [t];
        var tfTitle = tfMax(aliases, r.titleTf);
        var tfText = tfMax(aliases, r.textTf);
        if (!tfTitle && !tfText) return;
        matched += 1;
        var idf = Math.log((n + 1) / ((idx.df[t] || 0) + 0.5));
        score += idf * (tfTitle * 5 + tfText);
      });
      if (!matched) return;
      score *= 0.35 + (matched / qterms.length) * 0.65; // float full-overlap up
      scored.push({ kind: r.kind, rec: r.rec, title: r.title, url: r.url, source: r.source,
        score: score, matched: matched, snippet: snippet(r, qterms),
        tags: r.tags, android: r.android });
    });
    scored.sort((a, b) => b.score - a.score);
    return scored.slice(0, limit);
  }

  /* --- conclusions-only display contract (DA-201) ------------------------ */
  // A distilled record is "complete" only when all three parts (symptom AND
  // cause AND fix) are present. Incomplete distilled records are hidden by
  // default and surfaced via the "include incomplete (N)" toggle; raw
  // thread/docs records are never affected.
  function isDistilledComplete(rec) {
    return !!(rec && String(rec.symptom || "").trim() &&
      String(rec.cause || "").trim() && String(rec.fix || "").trim());
  }

  function countIncompleteDistilled(hits) {
    return hits.filter((h) => h.kind === "distilled" && !isDistilledComplete(h.rec)).length;
  }

  // Exported so the acceptance harness can unit-check the default-exclude /
  // toggle-include behaviour on a distilled record that is missing one part.
  function conclusionsOnly(hits, includeIncomplete) {
    if (includeIncomplete) return hits;
    return hits.filter((h) => h.kind !== "distilled" || isDistilledComplete(h.rec));
  }

  /* --- browser wiring ----------------------------------------------------- */
  function loadData() {
    if (typeof window === "undefined") return Promise.resolve(null);
    if (window.__AAPS_INDEX__) return Promise.resolve(window.__AAPS_INDEX__);
    if (window.location.protocol.indexOf("http") === 0) {
      return fetch("search-index.json").then((r) => {
        if (!r.ok) throw new Error("search-index.json: HTTP " + r.status);
        return r.json();
      });
    }
    // file:// — pull the window.__AAPS_INDEX__ blob via a script tag
    return new Promise((resolve, reject) => {
      var s = document.createElement("script");
      s.src = "search-data.js";
      s.onload = () => {
        if (window.__AAPS_INDEX__) resolve(window.__AAPS_INDEX__);
        else reject(new Error("search-data.js did not define window.__AAPS_INDEX__"));
      };
      s.onerror = () => { reject(new Error("failed to load search-data.js")); };
      document.head.appendChild(s);
    });
  }

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }

  function addChipRow(container, label, options, onClick) {
    // options: [{value, label, count}]. Radio-style: click again to clear.
    var active = null;
    if (label) container.appendChild(el("span", "lbl", label));
    options.forEach((o) => {
      var b = el("button", "chip", o.label + (o.count > 1 ? " · " + o.count : ""));
      b.setAttribute("data-filter", o.value);
      b.addEventListener("click", () => {
        if (active === b) { active.classList.remove("on"); active = null; }
        else {
          if (active) active.classList.remove("on");
          active = b; b.classList.add("on");
        }
        onClick(active ? b.dataset.filter : null);
      });
      container.appendChild(b);
    });
  }

  function init() {
    if (typeof document === "undefined") return;
    var input = document.getElementById("q");
    var resultsEl = document.getElementById("results");
    var statusEl = document.getElementById("status");
    var metaEl = document.getElementById("meta");
    var statlineEl = document.getElementById("statline");
    var devRowEl = document.getElementById("devfilters");
    var andRowEl = document.getElementById("andfilters");
    var landingEl = document.getElementById("landing");
    var incWrapEl = document.getElementById("incwrap");
    var incBtnEl = document.getElementById("incbtn");
    var incCountEl = document.getElementById("incn");
    var moreWrapEl = document.getElementById("morewrap");
    var browseBtnEl = document.getElementById("browseall");
    var activeType = "all";
    var activeDev = null;
    var activeAndroid = null;
    // View state: "home" (landing, no query) | "search" | "browse" (all).
    var mode = "home";
    var includeIncomplete = false;
    var browseCap = 40;
    var PAGE = 40;

    function enterBrowse() {
      mode = "browse";
      browseCap = PAGE;
    }
    // Any chip pressed on the empty landing becomes a filtered browse.
    function chipPressed() {
      if (!input.value.trim() && mode === "home") enterBrowse();
    }

    loadData().then((data) => {
      window.__AAPS_DATA__ = data;
      var counts = (data.meta || {}).counts || {};
      appendStat(statlineEl, [
        ["" + (counts.threads || 0), " raw solved threads · "],
        ["" + (counts.distilled || 0), " distilled records · "],
        ["" + (counts.docs || 0), " docs pages · "],
        ["" + ((counts.threads || 0) + (counts.docs || 0) + (counts.distilled || 0)), " records, searched in your browser"],
      ]);
      if ((counts.threads || 0) < 45) {
        metaEl.textContent = "Rate-limited pull: corpus is under the 45-thread target (see README).";
      }
      if (counts.distilled) buildDeviceFilters(data);
      render();
    }).catch((err) => {
      statusEl.textContent = "Could not load search index: " + err.message;
    });

    function buildDeviceFilters(data) {
      // tally canonical device tags + android versions across the whole index
      var idx = build(data);
      var devCounts = {}, andCounts = {};
      idx.recs.forEach((r) => {
        (r.tags || []).forEach((t) => { devCounts[t] = (devCounts[t] || 0) + 1; });
        (r.android || []).forEach((a) => { andCounts[a] = (andCounts[a] || 0) + 1; });
      });
      var devOpts = DEVICE_ORDER.filter((d) => devCounts[d])
        .map((d) => ({ value: "dev:" + d, label: d, count: devCounts[d] }));
      if (devOpts.length) {
        addChipRow(devRowEl, "Devices", devOpts, (v) => { chipPressed(); activeDev = v; render(); });
        devRowEl.style.display = "flex";
      }
      var andOpts = Object.keys(andCounts).sort((a, b) => +b.split(" ")[1] - +a.split(" ")[1])
        .slice(0, 8).map((a) => ({ value: "and:" + a, label: a, count: andCounts[a] }));
      if (andOpts.length) {
        addChipRow(andRowEl, "Android", andOpts, (v) => { chipPressed(); activeAndroid = v; render(); });
        andRowEl.style.display = "flex";
      }
    }

    function appendStat(root, parts) {
      parts.forEach((p) => {
        var b = document.createElement("b");
        b.textContent = p[0];
        root.appendChild(b);
        root.appendChild(document.createTextNode(p[1]));
      });
    }

    function show(msg) { statusEl.textContent = msg || ""; }
    function showLanding() {
      resultsEl.replaceChildren();
      hideEl(incWrapEl, true);
      hideEl(moreWrapEl, true);
      show("");
      metaEl.textContent = "";
      landingEl.hidden = false;
    }
    function hideEl(node, on) { if (node) node.hidden = on; }
    function activeFilterText() {
      var txt = [];
      if (activeType !== "all") txt.push(activeType);
      if (activeDev) txt.push(activeDev.slice(4));
      if (activeAndroid) txt.push(activeAndroid.slice(4));
      return txt;
    }
    function kindDevFilter(h) {
      if (activeType !== "all" && h.kind !== activeType) return false;
      if (activeDev && (h.tags || []).indexOf(activeDev.slice(4)) === -1) return false;
      if (activeAndroid && (h.android || []).indexOf(activeAndroid.slice(4)) === -1) return false;
      return true;
    }

    /* --- include-incomplete toggle -------------------------------------- */
    function renderIncToggle(hiddenN) {
      if (!incWrapEl) return;
      incWrapEl.hidden = !(hiddenN > 0 || includeIncomplete);
      if (incCountEl) incCountEl.textContent = "" + hiddenN;
      incBtnEl.classList.toggle("on", includeIncomplete);
      incBtnEl.setAttribute("aria-pressed", includeIncomplete ? "true" : "false");
      incBtnEl.title = includeIncomplete
        ? "Showing distilled records that miss a part; click to hide them."
        : "Also show distilled records missing symptom, cause or fix.";
    }

    /* --- card rendering ---------------------------------------------------- */
    function tagChips(h, cls) {
      var box = el("span", "tags" + (cls ? " " + cls : ""));
      (h.tags || []).forEach((t) => {
        var c = el("span", "tagchip", t);
        box.appendChild(c);
      });
      return box;
    }

    // Consistent source badge (DA-201): every card shows where its content
    // comes from — "docs" (official mirror), "github" (issue thread or its
    // distilled extract), or "FB community".
    function originBadge(h, isFb) {
      if (h.kind === "docs") return null;
      if (isFb) return el("span", "badge fb", "FB community");
      return el("span", "badge gh", "GitHub");
    }

    function cardHit(h) {
      var li = el("li", "card");
      var h2 = el("h2");
      var isFb = (h.rec || {}).source === "facebook";
      var badge = el("span", "badge " + h.kind);
      badge.textContent = h.kind;
      var link = document.createElement("a");
      link.href = h.url;
      link.textContent = h.title;
      if (h.kind !== "docs") { link.target = "_blank"; link.rel = "noopener"; }
      h2.appendChild(badge);
      var origin = originBadge(h, isFb);
      if (origin) h2.appendChild(origin);
      h2.appendChild(link);
      li.appendChild(h2);

      if (h.kind === "distilled") {
        li.appendChild(distilledBody(h));
      } else {
        var snip = el("p", "snip", h.snippet);
        li.appendChild(snip);
      }

      var foot = el("div", "footrow");
      var labels = h.rec.labels || [];
      labels.slice(0, 4).forEach((l) => foot.appendChild(el("span", "tagchip", l)));
      if (h.kind === "docs") {
        var srcA = document.createElement("a");
        srcA.className = "goto";
        srcA.href = h.rec.source_url;
        srcA.target = "_blank";
        srcA.rel = "noopener";
        srcA.textContent = (hostOf(h.rec.source_url) || "source") + " ↗";
        foot.appendChild(srcA);
      } else if (h.kind === "thread") {
        if (isFb) {
          foot.appendChild(el("b", null, h.rec.group || "Facebook community"));
          var posted = (h.rec.posted_at || "").slice(0, 10);
          if (posted) foot.appendChild(document.createTextNode(" · posted " + posted));
          foot.appendChild(document.createTextNode(" · " + (h.rec.comment_count || 0) + " comments"));
          var fbLink = document.createElement("a");
          fbLink.className = "goto";
          fbLink.href = h.rec.html_url || h.rec.url;
          fbLink.target = "_blank";
          fbLink.rel = "noopener";
          fbLink.textContent = "open original post ↗";
          foot.appendChild(fbLink);
        } else {
          foot.appendChild(el("b", null, h.rec.repo + "#" + h.rec.number));
          var closed = (h.rec.closed_at || "").slice(0, 10);
          if (closed) foot.appendChild(document.createTextNode(" · closed " + closed));
          foot.appendChild(document.createTextNode(" · " + (h.rec.comment_count || 0) + " comments"));
          var gh = document.createElement("a");
          gh.className = "goto";
          gh.href = h.rec.html_url;
          gh.target = "_blank";
          gh.rel = "noopener";
          gh.textContent = "open original issue ↗";
          foot.appendChild(gh);
        }
      } else { // distilled
        foot.appendChild(el("span", "conf conf-" + (h.rec.confidence || "low"),
          "confidence: " + (h.rec.confidence || "low")));
        foot.appendChild(tagChips(h));
        var gh2 = document.createElement("a");
        gh2.className = "goto";
        gh2.href = h.rec.url || h.rec.html_url;
        gh2.target = "_blank";
        gh2.rel = "noopener";
        gh2.textContent = isFb ? "view source post ↗" : "view source thread ↗";
        foot.appendChild(gh2);
      }
      li.appendChild(foot);
      resultsEl.appendChild(li);
    }

    function kv(label, value) {
      var row = el("p", "kv");
      row.appendChild(el("span", "k", label));
      row.appendChild(document.createTextNode(value));
      return row;
    }

    function distilledBody(h) {
      var r = h.rec;
      var box = el("div", "dbody");
      // Never a bare title: the three sections render distinctly (S -> C -> F).
      if (r.symptom) box.appendChild(kv("Symptom", r.symptom));
      if (r.cause) box.appendChild(kv("Cause", r.cause));
      if (r.fix) box.appendChild(kv("Fix", r.fix));
      if (r.settings_changed && r.settings_changed.length) {
        box.appendChild(kv("Settings changed", r.settings_changed.join("  ·  ")));
      }
      if (r.evidence_quote) {
        var q = el("p", "quote", "“" + r.evidence_quote + "”");
        box.appendChild(q);
      }
      var note = el("p", "kicker");
      if (r.source === "facebook") {
        note.textContent = "AI-extracted from a Facebook community post"
          + (r.group ? " (" + r.group + ")" : "") + " — not medical advice; verify against the original post.";
      } else {
        note.textContent = "AI-extracted from GitHub issue #" + r.issue_id + " — not medical advice; verify against the source thread.";
      }
      box.appendChild(note);
      return box;
    }

    function metaCounts(shown) {
      var docsN = shown.filter((h) => h.kind === "docs").length;
      var distilledN = shown.filter((h) => h.kind === "distilled").length;
      return { docsN: docsN, distilledN: distilledN, thrN: shown.length - docsN - distilledN };
    }

    /* --- browse-all (landing entry / filtered by chips) ------------------- */
    function browseCandidates() {
      var data = window.__AAPS_DATA__;
      var idx = build(data);
      var confW = { high: 3, medium: 2, low: 1 };
      var kindOrder = { docs: 0, distilled: 1, thread: 2 };
      var hits = idx.recs.map((r) => ({
        kind: r.kind, rec: r.rec, title: r.title, url: r.url, source: r.source,
        score: 0, matched: 0, snippet: snippet(r, []), tags: r.tags, android: r.android
      }));
      hits.sort((a, b) => {
        if (kindOrder[a.kind] !== kindOrder[b.kind]) return kindOrder[a.kind] - kindOrder[b.kind];
        if (a.kind === "distilled") {
          var d = (confW[b.rec.confidence] || 0) - (confW[a.rec.confidence] || 0);
          if (d) return d;
        }
        var cc = (b.rec.comment_count || 0) - (a.rec.comment_count || 0);
        if (cc) return cc;
        return a.title < b.title ? -1 : a.title > b.title ? 1 : 0;
      });
      return hits;
    }

    function renderBrowse() {
      landingEl.hidden = true;
      var all = conclusionsOnly(browseCandidates().filter(kindDevFilter), includeIncomplete);
      var total = all.length;
      var shown = all.slice(0, browseCap);
      resultsEl.replaceChildren();
      shown.forEach(cardHit);
      var hiddenN = countIncompleteDistilled(all);
      renderIncToggle(hiddenN);
      show("");
      var f = activeFilterText();
      metaEl.textContent = "browsing all " + total + " records" + (f.length ? " (filter: " + f.join(" + ") + ")" : "")
        + " — showing " + shown.length
        + (includeIncomplete ? " (incl. incomplete distilled)" : "")
        + " — type above to search";
      if (!shown.length) {
        show("Nothing to browse with the current filters — clear a chip or search above.");
      }
      if (!moreWrapEl) return;
      var remaining = total - shown.length;
      moreWrapEl.replaceChildren();
      if (remaining > 0) {
        var b = el("button", "chip more", "load more (" + remaining + " more)");
        b.addEventListener("click", () => { browseCap += PAGE; render(); });
        moreWrapEl.appendChild(b);
      } else if (total > PAGE) {
        moreWrapEl.appendChild(el("span", "endnote", "end of the index — refine with a search or a chip above"));
      }
      moreWrapEl.hidden = remaining <= 0;
    }

    /* --- query render ------------------------------------------------------ */
    function renderSearch(data, q) {
      var qterms = terms(q);
      if (!qterms.length) {
        hideEl(incWrapEl, true);
        metaEl.textContent = "";
        show("Search terms too generic — add a word like G7 or pod.");
        return;
      }
      var hits = run(data, q, { limit: 60 }).filter(kindDevFilter);
      var hiddenN = countIncompleteDistilled(hits);
      renderIncToggle(hiddenN);
      var shown = conclusionsOnly(hits, includeIncomplete);
      if (!hits.length) {
        show("No hits for “" + q + "” with the current filters. Try a shorter symptom phrase, a device name, or clear a chip.");
        return;
      }
      if (!shown.length) {
        show("Every distilled match for “" + q + "” is incomplete — enable “include incomplete (" + hiddenN + ")” above to surface it, or clear a filter.");
        return;
      }
      var counts = metaCounts(shown);
      var f = activeFilterText();
      var extra = "";
      if (hiddenN && !includeIncomplete) extra = " (+" + hiddenN + " incomplete distilled hidden)";
      metaEl.textContent = shown.length + " results for “" + q + "”"
        + (f.length ? " (filter: " + f.join(" + ") + ")" : "") +
        " — " + counts.distilledN + " distilled, " + counts.thrN + " threads, " + counts.docsN + " docs" + extra;
      show("");
      shown.forEach(cardHit);
    }

    function render() {
      resultsEl.replaceChildren();
      if (!window.__AAPS_DATA__) return;
      landingEl.hidden = mode === "home" ? false : true;
      var q = input.value.trim();
      if (mode === "browse") { renderBrowse(); return; }
      if (!q) { mode = "home"; showLanding(); return; }
      renderSearch(window.__AAPS_DATA__, q);
    }

    /* --- events ------------------------------------------------------------ */
    var t;
    input.addEventListener("input", () => {
      clearTimeout(t);
      t = setTimeout(() => {
        if (input.value.trim()) mode = "search";
        else if (mode === "search") mode = "home";
        render();
      }, 120);
    });
    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter") { mode = "search"; render(); }
    });
    if (incBtnEl) {
      incBtnEl.addEventListener("click", () => {
        includeIncomplete = !includeIncomplete;
        if (mode === "home") mode = "browse";
        render();
      });
    }
    if (browseBtnEl) {
      browseBtnEl.addEventListener("click", (ev) => {
        ev.preventDefault();
        if (input.value.trim()) input.value = "";
        enterBrowse();
        render();
      });
    }
    document.querySelectorAll(".chip[data-type]").forEach((b) => {
      b.addEventListener("click", () => {
        chipPressed();
        document.querySelectorAll(".chip[data-type]").forEach((x) => { x.classList.remove("on"); });
        b.classList.add("on");
        activeType = b.dataset.type;
        render();
      });
    });
    document.querySelectorAll("[data-example]").forEach((a) => {
      a.addEventListener("click", (ev) => {
        ev.preventDefault();
        input.value = a.dataset.example;
        mode = "search";
        render();
      });
    });
  }

  if (typeof document !== "undefined") {
    document.addEventListener("DOMContentLoaded", init);
  }

  return { run: run, terms: terms, build: build, STOP: STOP, EXPAND: EXPAND,
    canonDevice: canonDevice, isDistilledComplete: isDistilledComplete,
    countIncompleteDistilled: countIncompleteDistilled, conclusionsOnly: conclusionsOnly };
});
