/* AAPS Atlas search — plain vanilla JS, no framework, no CDN.
 *
 * Runs identically in the browser and in Node (module.exports), so the
 * node harness (scripts/search_check.mjs) verifies the exact algorithm the
 * page uses. The corpus index is prebuilt by scripts/build_index.py:
 *   site/search-index.json (served over http) or
 *   site/search-data.js     (window.__AAPS_INDEX__, needed for file://).
 *
 * Three record kinds: docs (mirror pages), thread (raw GitHub issue) and
 * distilled (LLM symptom->cause->fix extraction of a thread, always linked
 * back to its source issue). Filters: result type + device tags + Android
 * versions. Device tags are canonicalised (G7 / G6 / DASH / Omnipod 5 /
 * Libre / Medtrum / Dexcom / Eversense); threads/docs match via their text,
 * distilled records via their validated structured arrays.
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
    var activeType = "all";
    var activeDev = null;
    var activeAndroid = null;

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
        addChipRow(devRowEl, "Devices", devOpts, (v) => { activeDev = v; render(); });
        devRowEl.style.display = "flex";
      }
      var andOpts = Object.keys(andCounts).sort((a, b) => +b.split(" ")[1] - +a.split(" ")[1])
        .slice(0, 8).map((a) => ({ value: "and:" + a, label: a, count: andCounts[a] }));
      if (andOpts.length) {
        addChipRow(andRowEl, "Android", andOpts, (v) => { activeAndroid = v; render(); });
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

    function tagChips(h, cls) {
      var box = el("span", "tags");
      (h.tags || []).forEach((t) => {
        var c = el("span", "tagchip", t);
        box.appendChild(c);
      });
      return box;
    }

    function cardHit(h) {
      var li = el("li", "card");
      var h2 = el("h2");
      var badge = el("span", "badge " + h.kind);
      badge.textContent = h.kind;
      var link = document.createElement("a");
      link.href = h.url;
      link.textContent = h.title;
      if (h.kind !== "docs") { link.target = "_blank"; link.rel = "noopener"; }
      h2.appendChild(badge);
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
        srcA.className = "src";
        srcA.href = h.rec.source_url;
        srcA.target = "_blank";
        srcA.rel = "noopener";
        srcA.textContent = "source: " + h.rec.source_url;
        foot.appendChild(srcA);
      } else if (h.kind === "thread") {
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
      } else { // distilled
        foot.appendChild(el("span", "conf conf-" + (h.rec.confidence || "low"),
          "confidence: " + (h.rec.confidence || "low")));
        foot.appendChild(tagChips(h));
        var gh2 = document.createElement("a");
        gh2.className = "goto";
        gh2.href = h.rec.url || h.rec.html_url;
        gh2.target = "_blank";
        gh2.rel = "noopener";
        gh2.textContent = "view source thread ↗";
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
      note.textContent = "AI-extracted from GitHub issue #" + r.issue_id + " — not medical advice; verify against the source thread.";
      box.appendChild(note);
      return box;
    }

    function render() {
      var q = input.value.trim();
      var data = window.__AAPS_DATA__;
      resultsEl.replaceChildren();
      if (!data) return;
      if (!q) { show("Type a symptom, device, or error — e.g. G7 broadcast."); return; }
      var qterms = terms(q);
      if (!qterms.length) { show("Search terms too generic — add a word like G7 or pod."); return; }
      var hits = run(data, q, { limit: 60 }).filter((h) => {
        if (activeType !== "all" && h.kind !== activeType) return false;
        if (activeDev && (h.tags || []).indexOf(activeDev.slice(4)) === -1) return false;
        if (activeAndroid && (h.android || []).indexOf(activeAndroid.slice(4)) === -1) return false;
        return true;
      });
      show("");
      if (!hits.length) {
        show("No hits for “" + q + "” with the current filters. Try a shorter symptom phrase, a device name, or clear a chip.");
        return;
      }
      var docsN = hits.filter((h) => h.kind === "docs").length;
      var distilledN = hits.filter((h) => h.kind === "distilled").length;
      var thrN = hits.length - docsN - distilledN;
      var filterTxt = [];
      if (activeType !== "all") filterTxt.push(activeType);
      if (activeDev) filterTxt.push(activeDev.slice(4));
      if (activeAndroid) filterTxt.push(activeAndroid.slice(4));
      metaEl.textContent = hits.length + " results for “" + q + "”"
        + (filterTxt.length ? " (filter: " + filterTxt.join(" + ") + ")" : "") +
        " — " + distilledN + " distilled, " + thrN + " threads, " + docsN + " docs";
      hits.forEach(cardHit);
    }

    var t;
    input.addEventListener("input", () => {
      clearTimeout(t);
      t = setTimeout(render, 120);
    });
    document.querySelectorAll(".chip[data-type]").forEach((b) => {
      b.addEventListener("click", () => {
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
        render();
      });
    });
    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter") render();
    });
  }

  if (typeof document !== "undefined") {
    document.addEventListener("DOMContentLoaded", init);
  }

  return { run: run, terms: terms, build: build, STOP: STOP, EXPAND: EXPAND,
    canonDevice: canonDevice };
});
