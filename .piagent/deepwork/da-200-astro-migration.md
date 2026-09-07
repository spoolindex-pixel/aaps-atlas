# DA-200 — Migrate site to Astro (static), keep Cloudflare Pages + full parity

Deepwork progress file. Branch: `feat/task-200-da-migrate-site-to-astro` (from origin/main).

## Goal (reconciled)

Migrate the hand-rolled static site (`site/index.html` + vanilla `site/search.js` +
python-generated `site/docs/*.html`) to an Astro static build whose output is still
consumed by the existing Cloudflare Pages deploy (same project `aaps-atlas`,
same pinned `wrangler@4.129.0` CI step, same secrets). Full feature parity:
6 docs pages, distilled S-C-F cards, raw threads reachable, filters, MiniSearch
client search with build-time index JSON, dark spoolindex-family theme,
"not medical advice" banner + attribution linkbacks on every record.

Data pipeline (fetch_corpus/distill/validate_distilled) stays UNTOUCHED.

## Confirmed context (research reconciled)

- Repo: github.com/spoolindex-pixel/aaps-atlas (canonical remote = GitHub; Forgejo pull-mirror, never push there). Commit identity already configured (`spoolindex` / noreply).
- Existing build = `python3 scripts/build_index.py` (stdlib) which writes
  `site/search-index.json` + `site/search-data.js` + `site/docs/<slug>.html`.
  `site/search.js` + `site/style.css` + `site/index.html` are hand-written and committed.
  Nightly distill rollup commits `data/` + `site/` to main; CI rebuilds from `data/` and
  deploys `site/` artifact to CF Pages. Acceptance harness `scripts/search_check.mjs`
  does `require(site/search.js)` + reads `site/search-index.json` — those two paths MUST
  keep resolving after the migration (script itself unchanged).
- Docs data files: line 1 `# Source: <url>`, blank, then `# Title` + mirror body
  (nav/links stripped by fetch_docs.py, headings + plain text remain). Source line must be
  parsed out; attribution linkback needed on each rendered doc page.
- Distilled record schema + search payload shape defined by scripts/build_index.py /
  scripts/validate_distilled.py (record: issue_id, repo, url, title, symptom, cause, fix,
  settings_changed[], devices[], android_versions[], driver_tags[], confidence, evidence_quote).
- Index payload: `{meta:{generated,counts:{docs,threads,distilled}}, docs[], threads[], distilled[]}`
  with doc entries `{id:"doc:<slug>",type,slug,title,source_url,text}`; thread entries
  `{id,type,title,html_url,repo,number,labels,state,created_at,closed_at,comment_count,comments[],text}`;
  distilled entries `{id:"distilled:<stem>",type,issue_id,repo,number,title,html_url,url,confidence,
  symptom,cause,fix,settings_changed,devices,android_versions,driver_tags,evidence_quote,text}`.
  `search.js` `build()` expects exactly these keys (docs→docs/`<slug>`.html URL; thread/distilled
  external GitHub URLs). Search text for threads = title + labels + body + comment bodies (concatenated);
  for docs = title + body; for distilled = composed string built in python.
- Current corpus (committed): 6 docs, 53 threads (manifest excluded), 1025 distilled. Min gates:
  docs ≥ 6, threads ≥ 45 (build_index.py exit 1 below min; search_check also gates distilled ≥ 45).
- Toolchain: python3 (3.10+), node v22.23.2, npm 10.9.8, registry reachable.
  Astro latest = 7.3.1 (engines node >=22.12, npm >=9.6.5). Astro static default output.
  CI runners run `node` + `npx -y wrangler@4.129.0` without setup-node today → default node on
  ubuntu-latest satisfies ≥18; for astro 7 we need node ≥22.12 ⇒ add pinned actions/setup-node
  (node 22) to the build job.
- Lock discipline: before touching `data/` or `site/` take
  `exec 9>/tmp/aaps-atlas-distill.lock; flock -w 5400 9 || true` (nightly rollup holds it during
  batches). Rebase on origin/main frequently (rollup lands data+site nightly ~05:30–06:30).
  Data/ files are untouched by this task → main's data commits apply cleanly; only `site/`
  (generated, committed) overlaps → resolve site/ conflicts with our build output.
- Untracked stray file present: `scripts/mirror_docs.py` — NOT ours, never stage (gotcha 8).

## Architecture decision (recorded for reviewers)

Repo-root Astro project; build output to `site/` (kept committed, as today, so rollup push +
file:// + "repo is the static site" semantics are unchanged).

- `package.json` (astro devDep pinned exact via package-lock) + `astro.config.mjs`
  (outDir `site`, `build.format: 'file'` so docs emit as `docs/<slug>.html` — URL parity with today).
- `public/` (committed static): `style.css` (verbatim move), `search.js` (verbatim move —
  search_check.mjs requires site/search.js after astro copies it out). Generated-at-build:
  `public/search-index.json` + `public/search-data.js` are written by the retooled
  `scripts/build_index.py` BEFORE astro build; both are gitignored intermediates
  (single committed copy of the payload lives in `site/` output as today).
- `src/`:
  - `src/pages/index.astro` — home/search page replicating index.html structure + IDs
    (`#q #meta #results #status #statline #devfilters #andfilters`, `.chip[data-type]`,
    `[data-example]`, banner + footer + attribution) so the UNCHANGED search.js DOM wiring works.
  - `src/pages/docs/[slug].astro` — getStaticPaths reads `data/docs/*.md`; renders crumb + title +
    source attribution + mirrored body via a small TS md→html renderer mirroring the old python
    rules (no `<h2>Source…` quirk; clean heading levels; content identical).
  - `src/layouts/Base.astro` (head + stylesheet + favicon + title prop), optional shared
    components for brand/banner/footer used by index.
- `scripts/build_index.py` retooled: same parsing/payload/stats/min-thresholds/attribution
  asserts as today, but writes `public/search-index.json` + `public/search-data.js` only
  (docs HTML emission moves to Astro). Prints stats incl. `docs=N threads=M distilled=K`.
- npm scripts: `build:index` (python), `build` (`build:index && astro build`), `check` optional.
  §site-build exact commands (cutover deliverable):
  `npm ci` (first time / dep change), `npm run build`, `python3 scripts/validate_distilled.py`,
  `node scripts/search_check.mjs`.
- CI (ci.yml build job): add pinned setup-node(node 22) → npm ci → build_index.py →
  astro build → validate_distilled → search_check → same artifact upload (`site/`). Deploy job
  unchanged (wrangler pin kept). Search-index min gates enforced via search_check (unchanged).
- Why not pure-Astro endpoints for search-index: python already owns corpus parsing + record
  schema + stats (validate_distilled imports distill.py; record schema documented in AGENTS-REFERENCE
  in python terms); reusing build_index.py keeps one parser of record shape, keeps `scripts/`
  consistent, and search_check/validate contracts untouched. Docs pages still go through Astro
  (the actual migration point + growth structure).

## Open questions / decisions pending

- Astro v7 `build.format:'file'` + dynamic `[slug]` route → verify emitted `docs/<slug>.html`
  file names with a real `astro build` in P1; if unsupported, fallback: static named pages or a
  `public/_redirects`? — decided only after empirical check.
- Exact pinned actions/setup-node SHA for CI (resolve at P3 via GitHub API; repo pins actions by SHA).

## Phases & gates

- P1 scaffold: Astro project + outDir site + home page (index.html parity) + dynamic docs pages
  from data/docs; verify emitted tree (docs/<slug>.html, index.html) + old checks still pass
  against main baseline. GATE 1 (oracle/reviewer): scaffold + docs parity.
- P2 search integration: retool build_index.py → public/; parity-diff generated payload vs old
  committed search-index.json (only meta.generated differs); search_check.mjs + validate pass
  on new pipeline; filters/data-driven rows verified in built markup; live-URL parity confirmed.
  GATE 2 (oracle/reviewer): integration + evidence.
- P3 cutover: ci.yml new flow; remove old hand-rolled doc-emit path remnants; AGENTS-REFERENCE
  update incl. NEW §site-build; README update; .gitignore public generated files; verify
  end-to-end: fresh-clone simulation (npm ci + build) + validate + search_check + static artifact
  asserts; CF deploy runs on main after merge (cannot be green-checked pre-merge — evidence =
  identical deploy step + wrangler pin + local artifact checks; note explicitly for PR).
  GATE 3 (oracle/reviewer): cutover evidence + docs.
- Final: rebase on origin/main, full verify, commit(s) per phase (conventional, `Refs DA-200`,
  `Co-Authored-By: pi`), push, open PR per write-pr prompt.

## Phase log

### GATE 1 outcome — READY for P2 (oracle review of a1ae9cc)
Preconditions recorded by reviewer:
1. Restore dirty site/ tree in shared worktree before P2 commit/rebase (state from P1
   builds). RESOLVED: `git restore site/` at P2 start; site/ output regenerated + committed
   together with each phase's source commit so the repo stays coherent.
2. P2 first commit must retool build_index.py → public/ so `npm run build` + search_check
   + artifact asserts pass end-to-end (P1's npm run build was ordering-broken: old
   build_index wrote site/ JSON, astro emptied outDir).
Product decision (recorded): **file:// self-browsing is DROPPED — http(s) parity is the
contract.** Astro emits root-absolute URLs (/style.css, /search.js, /) with no relative-base
option; local preview stays `python3 -m http.server 8000 -d site`. search-data.js + the
unchanged search.js file:// branch remain generated/present (CI asserts site/search-data.js;
search.js byte-identical), documented as vestigial-for-file:// but kept for the http data-load
contract. Re-document in README/AGENTS-REFERENCE at P3 (old "open site/index.html from disk"
option A becomes `npm run build` + http.server).
Also flagged LOW (deliberate, documented): doc heading levels now map naturally (## → h2 etc.)
vs the old accidental +1 shift, restyling .mirror h2/h3 slightly; footer "Rebuild: npm run
build" command was premature until P2 retool.

### P0 baseline (done)
Origin/main (05ac845) scratch worktree .tmp/v-main: build_index OK (docs=6 threads=53
distilled=1025 index=2546KiB), validate `0 failed`, search_check ALL CHECKS PASSED.

### P1 scaffold (done — build verified, awaiting GATE 1)
- package.json (astro 7.3.1 devDep, engines node>=22.12), package-lock.json.
- astro.config.mjs: outDir `site`, build.format 'file', compressHTML false (keeps " · "
  inline whitespace separators of the hand-written pages), site https://aaps-atlas.pages.dev.
- public/style.css + public/search.js = byte-identical copies of site/{style,search}.js
  (search.js MUST stay unchanged — search_check.mjs requires site/search.js after copy).
- src/layouts/Base.astro (head + favicon + css link + body class), src/pages/index.astro
  (search shell replicating index.html structure + ALL ids/chips/data-example contract for
  unchanged search.js), src/pages/docs/[slug].astro + src/lib/docs.ts + src/lib/md.ts
  (docs parse + md→html faithful port of old python rules, minus the accidental `<h2>Source…`
  + duplicated-title artifacts).
- Empirical findings (recorded for reviewers):
  * Astro prerenders page modules into outDir → import.meta.url is WRONG for data paths in
    getStaticPaths (resolved data/docs under site/.prerender → ENOENT). Fix: resolve
    `process.cwd()/data/docs`. astro build runs from repo root.
  * build.format 'file' + dynamic [slug] route emits docs/<slug>.html — URL parity confirmed
    (`/docs/browser-build.html` … `/docs/xdrip-g7.html` + `/index.html`).
  * compressHTML default ("jsx") drops whitespace-only text nodes → glued " · " separators;
    compressHTML false fixes (output now matches old page formatting).
  * .astro/ cache dir at repo root (generated) → gitignored.
  * Failed/interrupted astro build leaves site/.prerender/ junk; successful build cleans it.
- Build verification: 7 pages built; astro copies public/* (style.css, search.js) into site/.
- Doc page content parity vs old committed pages: old tokens are a strict subset of new
  (only the accidental duplicate Source/title headers were removed). All search DOM contract
  ids present on home page.

## Lock + git discipline

Held lock for any op touching data/ or site/. Never commit to main; work only on
feat/task-200-da-migrate-site-to-astro. Rebase often on origin/main. Never `git add -A`
(stray mirror_docs.py must not be staged); stage explicit paths.
