/* AAPS Atlas search — plain vanilla JS, no framework, no CDN.
 *
 * Runs identically in the browser and in Node (module.exports), so the
 * node harness (scripts/search_check.mjs) verifies the exact algorithm the
 * page uses. The corpus index is prebuilt by scripts/build_index.py:
 *   site/search-index.json (served over http) or
 *   site/search-data.js     (window.__AAPS_INDEX__, needed for file://).
 *
 * Scoring: per-record term frequency weighted by field (title 5x, labels 3x,
 * body 1x) x corpus idf; full-query-overlap records are floated to the top.
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

  function fold(s) {
    return s.normalize ? s.normalize("NFKD").replace(/[\u0300-\u036f]/g, "") : s;
  }

  function terms(s) {
    return fold(String(s || "").toLowerCase()).split(/[^a-z0-9]+/).filter((t) => t.length > 1 && !STOP.has(t));
  }

  function build(data) {
    var recs = [];
    (data.docs || []).forEach((d) => {
      recs.push({ kind: "docs", id: d.id, title: d.title || d.slug,
        url: "docs/" + d.slug + ".html", source: d.source_url || "", rec: d,
        titleTf: count(terms(d.title)), textTf: count(terms(d.text)) });
    });
    (data.threads || []).forEach((t) => {
      var titleText = (t.title || "") + " " + (t.labels || []).join(" ");
      recs.push({ kind: "thread", id: t.id, title: t.title || (t.repo + "#" + t.number),
        url: t.html_url || "", source: t.html_url || "", rec: t,
        titleTf: count(terms(titleText)), textTf: count(terms(t.text)) });
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

  function count(tokens) {
    var m = {};
    tokens.forEach((t) => { m[t] = (m[t] || 0) + 1; });
    return m;
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
        score: score, matched: matched, snippet: snippet(r, qterms) });
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

  function init() {
    if (typeof document === "undefined") return;
    var input = document.getElementById("q");
    var resultsEl = document.getElementById("results");
    var statusEl = document.getElementById("status");
    var metaEl = document.getElementById("meta");
    var statlineEl = document.getElementById("statline");
    var activeType = "all";

    loadData().then((data) => {
      window.__AAPS_DATA__ = data;
      var counts = (data.meta || {}).counts || {};
      // statline, built as text nodes (no user-controlled HTML)
      appendStat(statlineEl, [
        ["" + counts.threads, " solved GitHub threads · "],
        ["" + counts.docs, " docs pages · "],
        ["" + (counts.threads + counts.docs), " indexed records, searched 100% in your browser"],
      ]);
      if (counts.threads < 45) {
        metaEl.textContent = "Rate-limited pull: corpus is under the 45-thread target (see README).";
      }
    }).catch((err) => {
      statusEl.textContent = "Could not load search index: " + err.message;
    });

    function appendStat(root, parts) {
      parts.forEach((p) => {
        var b = document.createElement("b");
        b.textContent = p[0];
        root.appendChild(b);
        root.appendChild(document.createTextNode(p[1]));
      });
    }

    function show(msg) { statusEl.textContent = msg || ""; }

    function cardHit(h) {
      var li = document.createElement("li");
      li.className = "card";
      var h2 = document.createElement("h2");
      var badge = document.createElement("span");
      badge.className = "badge " + h.kind;
      badge.textContent = h.kind === "docs" ? "docs" : "thread";
      var link = document.createElement("a");
      link.href = h.url;
      link.textContent = h.title;
      if (h.kind === "thread") { link.target = "_blank"; link.rel = "noopener"; }
      h2.appendChild(badge);
      h2.appendChild(link);
      li.appendChild(h2);

      var snip = document.createElement("p");
      snip.className = "snip";
      snip.textContent = h.snippet;
      li.appendChild(snip);

      var foot = document.createElement("div");
      foot.className = "footrow";
      var labels = h.rec.labels || [];
      labels.slice(0, 4).forEach((l) => {
        var c = document.createElement("span");
        c.className = "tagchip";
        c.textContent = l;
        foot.appendChild(c);
      });
      if (h.kind === "docs") {
        var srcA = document.createElement("a");
        srcA.className = "src";
        srcA.href = h.rec.source_url;
        srcA.target = "_blank";
        srcA.rel = "noopener";
        srcA.textContent = "source: " + h.rec.source_url;
        foot.appendChild(srcA);
      } else {
        var bold = document.createElement("b");
        bold.textContent = h.rec.repo + "#" + h.rec.number;
        foot.appendChild(bold);
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
      li.appendChild(foot);
      resultsEl.appendChild(li);
    }

    function render() {
      var q = input.value.trim();
      var data = window.__AAPS_DATA__;
      resultsEl.replaceChildren();
      if (!data) return;
      if (!q) { show("Type a symptom, device, or error — e.g. pod activation."); return; }
      var qterms = terms(q);
      if (!qterms.length) { show("Search terms too generic — add a word like G7 or pod."); return; }
      var hits = run(data, q, { limit: 60 }).filter((h) => activeType === "all" || h.kind === activeType);
      show("");
      if (!hits.length) {
        show("No hits for “" + q + "”. Try a shorter symptom phrase or a device name.");
        return;
      }
      var docsN = hits.filter((h) => h.kind === "docs").length;
      var thrN = hits.length - docsN;
      metaEl.textContent = hits.length + " results for “" + q + "” — " + thrN + " threads, " + docsN + " docs";
      hits.forEach(cardHit);
    }

    var t;
    input.addEventListener("input", () => {
      clearTimeout(t);
      t = setTimeout(render, 120);
    });
    document.querySelectorAll(".chip").forEach((b) => {
      b.addEventListener("click", () => {
        document.querySelectorAll(".chip").forEach((x) => { x.classList.remove("on"); });
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

  return { run: run, terms: terms, build: build, STOP: STOP, EXPAND: EXPAND };
});
