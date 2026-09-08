# AAPS Atlas — AGENTS-REFERENCE.md

Deep-dive companion to `AGENTS.md`. Pipeline, data schema, search details,
env vars and CI/deploy notes.

## Commands (full)

| Command | What |
| --- | --- |
| `python3 scripts/fetch_docs.py` | Mirror 6 doc pages → `data/docs/*.md` (network; stdlib only) |
| `python3 scripts/fetch_threads.py` | Pull demo closed threads → `data/threads/*.json` (network; `gh` auth) |
| `GITHUB_TOKEN=… python3 scripts/fetch_corpus.py` | Full closed-issue corpus + comments → `data/corpus/*.json` + `data/corpus/raw/*.jsonl`; resumable + `--incremental` (network; token env only) |
| `python3 scripts/distill.py` | LLM batch distiller: corpus → `data/distilled/*.json` records (symptom/cause/fix); **~200/run cap** (`--limit`), state-skipping, rejects parked under `data/distilled/rejects/` |
| `python3 scripts/validate_distilled.py` | CI gate: re-validates every distilled record (schema + url + verbatim-quote/devices containment vs corpus) — GitHub records against `data/corpus/`, FB records against `data/fb_threads/` |
| `FB_PSEUDONYM_SALT=… python3 scripts/fb_anonymize.py --input <apify.json> --outdir data/fb_threads [--group-slug … --group-name … --group-url …]` | Anonymize a raw Apify FB scrape → `data/fb_threads/<group>-<postid>.json` (authors → `member-<8hex>`, profile fields dropped, fails closed on any author-name leak) |
| `python3 scripts/validate_privacy.py --raw <apify.json> [paths…]` (or `--authors <names.json>`) | Hard name-leak + FB-record hygiene gate: fails if any scanned record text contains an exact author name; run with the raw roster against stored/distilled data |
| `python3 scripts/distill.py --source-dir data/fb_threads --source-type facebook [--limit …]` | Distill FB records through the same S→C→F distiller (FB no-names prompt, `state.facebook.json`, records land in `data/distilled/`) |
| `npm test` | Fixture privacy suite: `validate_privacy.py` + `unittest discover -s tests` + `tests/test_fb_search.mjs` (no network) |
| `python3 scripts/build_index.py` | `data/*` → `public/search-index.json` + `public/search-data.js` (build-time search payload); prints `docs=N threads=M distilled=K index=…KiB`; exits 1 under target |
| `npm run astro` (aka `astro build`) | Astro static build: copies `public/*` + renders `src/` (docs pages from `data/docs/*.md`) → `site/`; **run `scripts/build_index.py` first** (Astro clears `site/` then copies `public/*`) |
| `npm run build` | The one-shot site build: `build_index.py` then `astro build` (exact sequence the nightly chain uses) |
| `npm ci` | Install pinned site build deps (Astro) — first time / after a dependency change; needs Node ≥ 22.12 |
| `npx astro check` | Type-checks the Astro pages/components (0 errors expected) |
| `node scripts/search_check.mjs` | Acceptance harness — corpus sizes, attribution, demo queries across docs+threads+distilled, the conclusions-only completeness unit check, built-page landing assertions (examples + guides + top records + browse-all/toggle controls), and a DOM smoke of the real search.js wiring via `tests/test_search_dom.mjs` |
| `python3 -m http.server 8000 -d site` | Local preview of the built site (http only — Astro output uses root-absolute paths, `file://` double-click no longer works) |

All data-pipeline steps are stdlib Python 3.10+. The **site build now needs Node ≥ 22.12 and `npm ci`** (Astro 7, pinned in package-lock.json) — this changed post-DA-200; previously the site was buildable with stdlib python alone. No runtime CDN either way.

## Data pipeline

```
wiki.aaps.app / navid200.github.io/xDrip   -> scripts/fetch_docs.py    -> data/docs/*.md
nightscout/AndroidAPS + NightscoutFoundation/xDrip
                                          -> scripts/fetch_threads.py  -> data/threads/*.json   (demo slice)
                                          -> scripts/fetch_corpus.py   -> data/corpus/*.json     (full archive)
Apify facebook-posts-scraper (raw, gated) -> scripts/fb_anonymize.py  -> data/fb_threads/*.json  (anonymized)
data/corpus/*.json (priority: comment count desc) -> scripts/distill.py -> data/distilled/*.json
data/fb_threads/*.json (priority: comment count desc)
                                          -> scripts/distill.py --source-type facebook -> data/distilled/*.json
data/docs + data/threads + data/fb_threads + data/distilled -> scripts/build_index.py   -> public/search-index.json + public/search-data.js
public/* + src/ (data/docs/*.md rendered by Astro)   -> npm run build (astro)  -> site/   (Cloudflare Pages deploy input)
```

### Doc mirror format

- First line of every `data/docs/*.md` is the source URL (`# Source: <url>`).
- Mirroring strips nav/script/style and keeps headings + body. Two host
  layouts are handled: AAPS wiki (Sphinx, `itemprop="articleBody"`) and
  navid200.github.io xDrip (Jekyll — content after the last `<h1>`).

### Demo thread slice (`data/threads/*.json`)

Closed issues sorted by **comment count desc**; long-tail
wishlist/feature-request threads skipped (`WISHLIST_RE`); `TOPIC_ANCHORS`
adds native-G7/broadcast threads. Rationale in
`data/threads/manifest.json`. **Snapshots are committed** — re-running a
fetch rewrites data/.

### Full corpus (`data/corpus/`)

Phase-2: the *complete* closed-issue archive of both repos — every closed
issue + all comments. Real totals (checked 2026-09):
`nightscout/AndroidAPS` **1846** + `NightscoutFoundation/xDrip` **1541** =
**3387** threads (the ~2.1k/1.6k numbers in older task text counted *all*
issues incl. open; closed-only is 3387 — that IS the full set, not a partial
fetch).

- `data/corpus/<repo>-<number>.json` — per-thread record, **same keys as the
  phase-1 schema** but with widened caps for the full archive: `body` ≤ 8000
  chars; kept comments ≤ 40/thread — earliest 15 + latest 25 before close
  (setup context + resolution arc) with a post-close top-up for tiny threads;
  each comment body ≤ 2000 chars. Committed (deterministic snapshot).
- `data/corpus/raw/<repo>.jsonl` — full-fidelity raw API archive (one line =
  issue dict + all raw comments, uncapped). **Gitignored**: too heavy to
  commit (~45 MB); regenerate with `scripts/fetch_corpus.py`.
- `data/corpus/manifest.json` — committed run summary + per-repo counts.
- `data/corpus/state.json` — **gitignored** resume cursor: saved issue
  numbers per repo + `last_updated` watermark. Re-running skips already-saved
  numbers (no comment re-fetch); `--incremental` re-fetches issues updated
  after the watermark. A fresh clone has no state → a fetch run refetches
  everything (raw archive is needed for full fidelity anyway).

`fetch_corpus.py` uses `GITHUB_TOKEN` from env (fine-grained and classic both
work — list endpoint only). Handles pagination, watches
`x-ratelimit-remaining`, sleeps through 403/429 with Retry-After, retries
5xx. ~3.4k issues ≈ one comments call each ≈ ~30-60 min, safe to interrupt.

## Distillation (`data/distilled/`, scripts/distill.py)

- **Anti-hallucination is the #1 contract.** One thread per prompt, strict
  extract-only system prompt: every field only from the thread text; null/[]
  when absent; never invented versions/settings/devices. The validator then
  enforces: JSON schema (types/enums/url pattern), `evidence_quote` is a
  verbatim (whitespace/case-normalised) substring of the thread text, and
  every `devices`/`android_versions`/`settings_changed` entry literally
  occurs in the thread (token-level containment — tolerates "Samsung S23" vs
  "galaxy S23", rejects invented tokens). Failure → one retry with the exact
  error → parked in `data/distilled/rejects/<stem>.json` with the reason.
- Record schema (validated every record):
  `{issue_id, repo, url, title, symptom, cause, fix, settings_changed[],
  devices[], android_versions[], driver_tags[], confidence, evidence_quote}`
  — `confidence` = high/medium/low (low when the thread does not resolve),
  `evidence_quote` ≤ 400 chars backing the fix (else cause).
- **Batch discipline**: default `--limit 200` per run (task-scoped batches,
  one batch per task — do NOT chain runs inside a task). Selection: comment
  count desc over undistilled corpus + a few G7/broadcast demo anchors
  (`ANCHOR_STEMS`) forced into every batch so "G7 broadcast" always hits
  distilled records. `data/distilled/state.json` records distilled + parked
  stems so each run picks the next ~200; printout ends with
  `REMAINING undistilled threads: N`.
- LLM config (env, all optional): `AAPS_LLM_API_KEY` (default: the
  `deepseek` key in `~/.config/aaps-atlas/llm-key.json`, JSON shape
  `{"deepseek": {"key": …}}`; `AAPS_LLM_KEY_FILE` overrides the path),
  `AAPS_LLM_BASE_URL` (default `https://api.deepseek.com`),
  `AAPS_LLM_MODEL` (default `deepseek-chat`). Prints prompt/completion token
  totals + est. cost (list price ~$0.14/$0.28 per M → a 200-thread batch
  ≈ $0.10-0.25; observed $0.07).

  **Model gotcha — use `deepseek-chat`, never the reasoning variant.**
  `deepseek-v4-flash` (the pi/robit *default* model) is a heavy reasoning
  model: on a meaningful fraction of threads it burns its whole completion
  budget on `reasoning_content` (`finish_reason=length`) and returns EMPTY
  content — observed ~30-50% parse rejects. `deepseek-chat` is the plain
  chat model on the same key: strict-JSON output at ~300-600 completion
  tokens/thread, ~20× cheaper. `scripts/distill.py` now defaults to
  `deepseek-chat`; keep it that way.

  **Verbatim-quote tolerance (`norm_quote`).** The evidence-quote check
  compares whitespace/case-normalised forms AND a symmetric variant that
  strips markdown-link URL destinations (`[text](url)` → `[text]`) from
  BOTH the quote and the source — the words must still be verbatim; only
  the `(url)` half (formatting sugar, no claim content) may differ. Inserted
  "..." / skipped spans / invented words always fail.

  **Observed outcome (first 200-thread batch, task 155).** 192/200 passed
  full validation (96%): 183 on the first pass, 9 more after hardening the
  prompt (explicitly banning "…"/ellipsis and non-contiguous quotes) +
  the `norm_quote` tolerance. 8 stayed parked — legitimately hard threads:
  resolution text is a log/backtrace dump or the model invented a setting
  name (e.g. "minimum bolus step") not in the thread. All older parked
  files with `parse: no JSON object in model response` are victims of the
  v4-flash reasoning bug above, not of the current pipeline.
- All data in `data/distilled/` is committed (records + rejects + state) so
  the site index is reproducible and later batches skip done threads.
  Batch standing:
  batch 1 (task 155, phase-2 merge) **251** records / 52 parked;
  batch 2 (task 157) **446** / 57;
  batch 3 (task 155 refire) **641** / 62;
  batch 4 (task 155 refire) **832** records / 71 parked;
  batch 5 (task 158) **1025** records / 78 parked;
  batch 6 (task 194 rollup) **1222** records / 81 parked;
  batch 7 (task 194 rollup, this run) **1412** records / 91 parked —
  **1884 undistilled** of 3387. Every batch reconciles exactly:
  new-distilled + new-parked = attempts, and
  `3387 − distilled − parked = REMAINING`.

### Batch-run recovery (ad hoc)

If a run's prompt/validator is improved, previously-parked rejects can be
re-attempted by un-parking their stems from `data/distilled/state.json` and
re-running them through `distill.distill_one` (retry-once contract still
applies; successes land as records, failures re-park). Task 155 used this to
recover 9/17 first-pass rejects after the prompt/norm_quote hardening.

## FB corpus ingest + privacy (task-196)

The two closed Facebook groups (xDrip+ users, AndroidAPS Users) get the same
S→C→F treatment as GitHub, through a deliberately *separate*, privacy-first
pipeline. **HARD PRIVACY RULE (user requirement): NO person names anywhere in
stored or derived data.** The pilot scrape task (blocked on ☀️ manual group
setup) consumes everything below; this repo builds and tests it with the
synthetic fixture `tests/fixtures/apify_sample.json` (no network).

### Anonymization (scripts/fb_anonymize.py)

Takes raw Apify `facebook-posts-scraper` output (field mapping tolerates the
documented aliases — see `tests/fixtures/README.md`) and writes one record
per post to `data/fb_threads/<group>-<postid>.json`:
`{id, source: "facebook", group, group_url, url (post permalink — kept for
linkback), posted_at, text, comments: [{pseudonym, text, posted_at}],
reactions_count?}`.

- Author → stable pseudonym `member-<8hex>`: HMAC-SHA256 of the author's
  **stable id**, keyed by a **per-install salt** — `FB_PSEUDONYM_SALT` env
  wins, otherwise a one-time salt is generated and persisted at
  `~/.config/aaps-atlas/fb-pseudonym-salt` (0600, never committed). Same
  author id ⇒ same pseudonym across posts/runs; rotating the salt remaps
  everything.
- **All profile fields are dropped at map time** (names, profile-pic URL,
  user URL, per-user `reactions` lists); outputs are built fresh from a
  whitelist (`scripts/privacy_common.py` `FB_THREAD_KEYS`), so a profile
  field cannot survive by accident. Only aggregates survive (comment count
  implied by the array, optional `reactions_count` int).
- Fails **closed** (exit 1, nothing written) if any output text field
  contains a raw author name — the first gate. Real runs should pass
  `--group-slug/--group-name/--group-url` (per-group scrape) for clean
  filenames; raw Apify archives + author rosters go under
  `data/fb_threads/raw/` (gitignored) and are **never committed**.

### Name-leak gates (validate_privacy.py + CI)

- `scripts/validate_privacy.py` — given the raw authors list
  (`--raw <apify.json>` auto-harvests names/handles; `--authors <list.json>`
  for an explicit roster) it **fails if any scanned record's text fields
  contain an exact author name** (whole-name, whitespace-collapsed,
  case-insensitive, word-bounded — `privacy_common.name_leak_matches`).
  Scans any JSON paths; defaults to `data/fb_threads` + `data/distilled`.
  Also enforces FB-record hygiene even without an author list: whitelisted
  keys only, `member-<8hex>` comment pseudonyms, https facebook permalink.
- Wired into CI (build job, before the site build) as two steps: the
  fixture suite (`unittest discover -s tests` + `tests/test_fb_search.mjs`)
  and a live anonymize→gate run (`fb_anonymize.py` on the fixture, then
  `validate_privacy.py --raw … data/fb_threads data/distilled`). The
  unittest suite also proves the gate FAILS on the poisoned fixtures
  (`tests/fixtures/poisoned_fb_thread.json`, `poisoned_distilled.json`).
- A real scrape re-runs the gate with ITS raw roster (kept out-of-repo) at
  ingest time — the raw authors are never persisted, so the committed data
  - CI stay clean while the pilot still gets a hard check.

### Distillation (same distiller, FB flavor)

`python3 scripts/distill.py --source-dir data/fb_threads --source-type
facebook` runs the same extract-only S→C→F engine on FB records:

- FB system prompt (never reached by GH runs) hard-bans copying any real
  name/handle/**pseudonym** into any output field incl. evidence quotes;
  the shared GH prompt also gained a no-names rule. Metadata (`source`,
  `group`, `group_url`, `url`) is attached **programmatically** after the
  model passes `validate_record_fb` — never model-written. Posts have no
  title: the model synthesises a short one.
- Bookkeeping is isolated: FB stems + rejects live in
  `data/distilled/state.facebook.json` (never in the GitHub `state.json`),
  so batch math for the 3387-thread GitHub corpus stays exact.
- `validate_distilled.py` routes records by content: `source: "facebook"`
  records are checked against `data/fb_threads/` with the FB schema;
  everything else against `data/corpus/` as before.

### Site

Facebook records are indexed as ordinary `thread` entries carrying
`source: "facebook"` (+ group/group_url/url/posted_at, auto-title from the
post text) and FB distilled records as `distilled` entries with
`source: "facebook"`. `search.js` cards show an **FB community** badge and
link back to the **original post permalink** ("open original post ↗"/
"view source post ↗", `badge.fbsrc` style); the type/device/Android
filters treat FB records exactly like GitHub ones. `site/` regenerated with
the usual §site-build sequence.

## Search engine (site/search.js)

- Prebuilt, normalised records + client-side scoring; **no runtime network**.
- Tokenizer: lowercase, NFKD-fold, split on non-alnum, drop 1-char + stopwords.
- Score per term = `idf × (titleTf×5 + textTf×1)`; multi-term overlap is
  floated up. Synonym map `EXPAND`: `broadcast ≈ companion ≈ byoda`
  (all mean the G7/G6→AAPS/xDrip delivery path). MiniSearch core unchanged.
- Three record kinds in one index: **docs**, **thread** (raw issue), and
  **distilled** (LLM S-C-F extraction, always linking back to its GitHub
  issue via `url`/`html_url`). Distilled searchable text = title + symptom +
  cause + fix + tags + versions + evidence quote.
- Filters (all client-side, combine with AND across rows):
  1. type chips All/Docs/Threads/Distilled;
  2. **device chips** from a canonical CGM/pump vocabulary (G7, G6, DASH,
     Omnipod 5, Libre, Medtrum, Dexcom, Eversense) — distilled records match
     via their structured `devices`/`driver_tags` arrays, docs/threads via
     text scanning; rows appear only when the index has matching records;
  3. **Android-version chips** from `android_versions`/text scan.
- Same file is `require()`d by `scripts/search_check.mjs` — the harness tests
  the exact page algorithm. Data loading: over `http(s)` fetch
  `search-index.json`; over `file://` inject `search-data.js`
  (`window.__AAPS_INDEX__`) — the latter path is vestigial post-Astro (the
  built site is http-served only) but is kept because search.js must stay
  byte-identical for the harness.
- Generated at build time: `public/search-index.json` + `public/search-data.js`
  (by `scripts/build_index.py`) are copied by Astro into `site/` next to
  `site/search.js` (source: `public/search.js`, byte-identical, never edited).
  Docs pages are Astro pages (`src/pages/docs/[slug].astro` rendering
  `data/docs/*.md` via `src/lib/md.ts`). Edit `scripts/build_index.py` or
  `src/`, never the generated files.

### Populated landing + conclusions-only display (DA-201 UX pass)

- **Populated landing**: with no query the home page is not a blank shell.
  `src/pages/index.astro` statically renders (at Astro build time) clickable
  example queries (each verified by search_check to return docs+threads hits
  before it may be listed), links to the six doc guides
  (docs/dexcom-g7, omnipod-dash, xdrip-app [xDrip settings], building-aaps,
  browser-build, xdrip-g7), a small "Top distilled records" list, and a
  browse-all button. Top records are computed in `src/lib/top.ts` from
  `data/distilled` joined to `data/corpus` comment counts — **complete
  records only** (symptom AND cause AND fix), ranked by confidence then
  comments. `search.js` only toggles that section's visibility and runs the
  views.
- **Conclusions-only search results**: distilled cards show records with all
  three parts populated. Records missing symptom, cause or fix (today ~567
  of 1412) are hidden by default and surfaced only by the client-side
  "include incomplete (N)" toggle. `isDistilledComplete` / `conclusionsOnly` /
  `countIncompleteDistilled` are exported from `public/search.js` for the
  search_check unit check. Raw docs/thread records are never affected. Every
  distilled card renders S → C → F as three distinct `.kv` rows
  (Symptom/Cause/Fix) — never a bare title.
- **Browse-all**: the landing button opens a paged view (40/page, "load
  more") over the whole index ordered docs → distilled → threads, honouring
  the type/device/Android chips and the incomplete toggle. The same view
  opens when a chip is pressed with an empty query (chip = filtered browse).
- **Source badges**: every card now carries a consistent origin badge after
  the kind badge — docs: `docs`; GitHub threads + distilled: `GitHub`;
  Facebook records: `FB community`. Docs cards' footrow shows a short
  `<host> ↗` link instead of the full source URL.
- `scripts/build_index.py` annotates each distilled index entry with
  `comment_count` (source-thread comments, read from `data/corpus` or
  `data/fb_threads`) so browse/top ordering is by most-discussed.
- Verification: `node scripts/search_check.mjs` additionally asserts the
  built `site/index.html` contains the landing (all example queries, the six
  guide hrefs, ≥ 1 top record card with all three S/C/F rows, browse-all +
  toggle controls), runs the completeness unit check (missing-fix/missing-
  cause distilled excluded by default, included with the toggle), and spawns
  `tests/test_search_dom.mjs` — a DOM-shim smoke of the real `search.js`
  init() wiring (landing ↔ search ↔ browse modes, toggle behaviour,
  load-more). `npx astro check` must stay 0 errors — note node API reads
  (`readFileSync`/`process.cwd()`) type-check clean in `src/lib/*.ts` but
  NOT inside `.astro` frontmatter; keep file I/O in lib modules like
  `src/lib/top.ts` / `docs.ts`.

## Site build (the nightly rollup chain reads this §site-build)

**Post-DA-200 this is the ONLY build path** (the old python docs-HTML emitter was removed).
Exact commands for the nightly rollup chain and any rebuild — run them inside the usual
lock (`exec 9>/tmp/aaps-atlas-distill.lock; flock -w 5400 9 || true`) before touching
`data/`/`site/`:

```bash
npm ci                                        # only first time / after a dependency change (Node >= 22.12)
python3 scripts/build_index.py                # data/ -> public/search-index.json + public/search-data.js
npm run astro                                 # public/ + src/ -> site/  (astro build)
# ...the two above are exactly `npm run build`
python3 scripts/validate_distilled.py         # must print `0 failed`
node scripts/search_check.mjs                 # must print ALL CHECKS PASSED
```

Then commit **only `data/` + `site/`** (generated outputs incl. `site/search-index.json`,
`site/search-data.js`, `site/docs/*.html`, `site/index.html`) — rejects/state/manifest churn
included. `public/search-index.json` + `public/search-data.js` are gitignored intermediates
(regenerated every build; the committed copy lives in `site/`). A batch that runs only
`build_index.py` and skips `npm run astro` leaves the committed `site/` **stale** — always
run the full sequence so committed `site/` stays in sync with `data/`.

## Env vars / secrets

| Var | Where | Needed for |
| --- | --- | --- |
| — | `gh` CLI config | `fetch_threads.py` (never a token in env/scripts) |
| `GITHUB_TOKEN` | env only (never committed) | `fetch_corpus.py` full-corpus fetch |
| `AAPS_LLM_API_KEY` / `AAPS_LLM_KEY_FILE` / `AAPS_LLM_BASE_URL` / `AAPS_LLM_MODEL` | env (optional; default = deepseek key in `~/.config/aaps-atlas/llm-key.json`) | `distill.py` |
| `FB_PSEUDONYM_SALT` | env (optional; else auto-generated per-install salt at `~/.config/aaps-atlas/fb-pseudonym-salt`) | `fb_anonymize.py` (pseudonym HMAC key — rotate to remap authors) |
| `CLOUDFLARE_API_TOKEN` | GitHub repo secret (mirror of vault item `aaps-atlas-cf-token`) | CF Pages deploy job |
| `CLOUDFLARE_ACCOUNT_ID` | GitHub repo secret (optional) | CF Pages deploy job |

Deploy is fully token-gated in CI — no token ⇒ deploy steps are skipped and a
notice prints the one manual setup step. No `.env` required locally.

## CI / deploy

`.github/workflows/ci.yml`:

1. `build` — pinned setup-python 3.12 + **pinned setup-node 22** (Astro 7 needs ≥ 22.12),
   `npm ci`, then the **FB privacy steps** (fixture-based, no network:
   `unittest discover -s tests` + `tests/test_fb_search.mjs`, plus an
   anonymize→`validate_privacy.py --raw … data/fb_threads data/distilled`
   gate over committed data with the fixture roster), then
   `python3 scripts/build_index.py` (→ `public/`), `npm run astro`
   (**after** build_index — Astro clears `site/` then copies `public/*`),
   **validate_distilled.py** (schema + url + quote containment gate; routes
   FB records to their fb_threads source), search_check.mjs, static-artifact
   assertions, upload `site/` artifact.
   Runs on every PR + push to main.
   `FB_PSEUDONYM_SALT` is set to a CI-only fixture salt in those steps.
2. `deploy` — needs build, main-only, gated on `secrets.CLOUDFLARE_API_TOKEN`.
   Downloads the `site/` artifact, then
   `wrangler@4.129.0 pages deploy site --project-name aaps-atlas` (pin unchanged).

## Gotchas

1. `gh api` with `-f` params POSTs by default — always pass `-X GET` for
   reads (issues list + comments).
2. GitHub fine-grained tokens cannot use `/search/issues` (404) — both
   fetchers use the plain issues list endpoint (fetch_threads sorts by
   `sort=comments`; fetch_corpus pages the whole closed set).
3. Repo text is community content: markdownlint/typo/generic-secret
   advisories on `data/` (proprietary terms, heading structure, real typos
   in issue text, verbatim-quoted api-secret hashes in evidence quotes) are
   expected and safe to ignore — the build/CI checks are the gate. Never
   edit a distilled record to dodge an advisory (breaks the verbatim
   contract).
4. Generated outputs live in `site/` (search-index.json, search-data.js,
   docs/*.html, index.html) — produced by `scripts/build_index.py`
   (→ gitignored `public/` intermediates) + the Astro build (`src/`).
   Edit `scripts/build_index.py` or `src/`, never the generated files.
   Astro renders the docs pages from `data/docs/*.md` (`src/lib/docs.ts` +
   `src/lib/md.ts` are the faithful port of the old python renderer).
5. Ruff S310 (urlopen) is suppressed per-line with `# noqa: S310` after the
   scheme allowlist; do not remove the guard. Apply the same pattern to new
   fetchers.
6. Corpus/distilled state files are gitignored only for `data/corpus/`
   (`state.json`, `raw/`, `.fetch.log`); `data/distilled/state.json` IS
   committed so CI/next batches see distilled + parked stems.
7. GitHub closed-issue totals are **3387** (AAPS 1846 + xDrip 1541) — do not
   chase a "3.5k+" target; that number counted open issues too.
8. A stray abandoned docs-mirror task may leave untracked `data/docs/*.md`
   (CamelCase) + `scripts/mirror_docs.py` in the worktree — not part of the
   pipeline; never stage them (they break the phase-1 doc header format).
9. **Nightly batches serialize on a lock**, not on git: before touching
   `data/`/`site/` a batch task must hold `/tmp/aaps-atlas-distill.lock`
   (`flock -w` up to 90 min — earlier batches and phase-2 acceptance runs
   are expected to be in flight). Never push a batch while not holding it.
10. **Distiller must be on `origin/main` before a batch runs** — poll
    `git fetch origin` + `git cat-file -e origin/main:scripts/distill.py`
    (~2 min, up to 90 min). Until phase-2 merges, the scripts + corpus may
    exist only as *uncommitted* leftovers in the shared worktree from the
    phase-2 task — do not commit or push those; wait for the merge, then
    `git fetch origin && git checkout -B feat/task-<n>-<slug> origin/main`
    (gitignored `data/corpus/state.json` + `raw/` survive the checkout, so
    `fetch_corpus.py` stays incremental).
11. Multiple queued task dispatches share ONE worktree checkout; the last
    task to `checkout`/`commit` wins the branch. Always re-check
    `git branch --show-current` + `git status` immediately before committing
    — never `git add -A` (would sweep another task's stray files).
12. A plain re-run of `fetch_corpus.py` rewrites `data/corpus/manifest.json`
    `fetched_at` (counts unchanged) — expected churn; commit it with the
    batch.
13. Semgrep/gitleaks-style "generic secret" advisories on `data/distilled/`
    are expected data-content false positives: `evidence_quote`/`fix` quote
    public GitHub issue text verbatim (e.g. an xDrip local web-service
    `api-secret` SHA1 from issue #830). The validator + CI are the gate; do
    not edit records to dodge an advisory (breaks the verbatim contract).
14. **`gh auth token` does not exist on this gh build** (unknown command) —
    do not rely on it. To feed `GITHUB_TOKEN` to `fetch_corpus.py`, pull the
    value from `~/.config/gh/hosts.yml` (`oauth_token:`) into the env var
    with awk/sed and never print it, e.g.
    `GITHUB_TOKEN=$(awk -F': ' '/oauth_token:/{print $2; exit}' ~/.config/gh/hosts.yml) python3 scripts/fetch_corpus.py`
    No GitHub token lives in the vault; env only.
15. **The shared feat/task-155 branch accumulates other tasks' content.**
    When the remote branch tip holds committed records/rejects that are NOT
    yet on `origin/main` (a merged PR fell behind later batch pushes),
    cherry-pick those content commits onto your main-based branch BEFORE
    distilling so threads already distilled are never re-distilled (each
    thread must exist exactly once in the merged history). The final push is
    then `git push --force-with-lease` — content-preserving supersession of
    the stale branch; nothing is lost.
16. **Site build needs Node ≥ 22.12 + `npm ci` (Astro 7).** The data-pipeline
    scripts stay stdlib python, but a machine rebuilding `site/` must have
    node ≥ 22.12 and run `npm ci` once (package-lock.json is committed). CI
    pins setup-node 22; do not bump Astro without re-running the whole
    §site-build pipeline.
17. **Astro output is http-only.** It uses root-absolute `/style.css` etc., so
    `file://` double-click on `site/index.html` no longer works — use
    `python3 -m http.server 8000 -d site`. `search-data.js` + search.js's
    file:// branch are kept only because search.js must stay byte-identical
    for `search_check.mjs`.
18. **Interrupted `astro build` can leave `site/.prerender/` junk** in the
    output dir — never commit it (successful builds clean it up). `.astro/`
    at the repo root and `public/search-index.json`/`search-data.js` are
    gitignored build intermediates.
19. **Rollup coherence:** since DA-200 the nightly batch MUST run the full
    §site-build sequence (`build_index.py` → `npm run astro`). Running only
    `build_index.py` commits `data/` with a stale committed `site/`
    (CI-on-push would still deploy correctly, but the committed tree would
    disagree with `data/`).
20. **FB data never contains real names.** `fb_anonymize.py` fails closed on
    author-name leaks and `validate_privacy.py` is the CI gate; raw Apify
    archives + author rosters go under `data/fb_threads/raw/` (gitignored)
    and must never be committed. `data/fb_threads/` is committed with only
    anonymized `<group>-<postid>.json` records (+ README.md — build_index
    skips it). Profile fields are dropped by whitelist at map time — never
    hand-edit a record to add `name`/`user` keys (hygiene gate fails).
21. **FB distilled metadata is programmatic, not model-written.**
    `distill.py --source-type facebook` attaches `source`/`group`/
    `group_url`/`url` after validation; FB stems use
    `data/distilled/state.facebook.json` so they never disturb the GitHub
    corpus batch math (`state.json`). A `.json` file in `data/distilled/`
    whose record has `"source": "facebook"` is validated by
    `validate_distilled.py` against `data/fb_threads/<stem>.json`.
22. **Privacy tests need the salt env:** fixture tests set
    `FB_PSEUDONYM_SALT` themselves (CI uses a fixture-only value). The
    per-install salt file is under `~/.config/`, never in the repo.
23. **Name matching is exact-name:** `privacy_common.name_leak_matches`
    matches whole names/handles only (word-bounded, collapsed), so a roster
    entry like "Sam Okafor" never trips on the word "sample". Short/single-
    token names and handles are matched with boundaries; don't add
    first-name-only fragments to a roster expecting them to catch full
    names.
24. **Distilled search results are conclusions-only (DA-201).** Any distilled
    record missing symptom/cause/fix is hidden by default behind the
    "include incomplete (N)" toggle — a *display* rule in `public/search.js`
    (the scoring `run()` is unchanged) that search_check unit-checks. Do not
    hand-edit a record to "complete" it (breaks the verbatim contract). The
    landing page's top-distilled list and the default browse view show only
    complete records by construction.

## Nightly batch runs (post-phase-2)

Task-scoped `~200/batch` distill runs (from task 194 a self-recreating
rollup — one next-200 batch per dispatch, then a same-title successor
task is created while `REMAINING > 0`; dupe-guarded so at most one open
successor):

1. Hold the flock (`/tmp/aaps-atlas-distill.lock`); confirm `distill.py` +
   `fetch_corpus.py` are on `origin/main`; sync the worktree to
   `origin/main` on `feat/task-<n>-da-distill-batch-<k>-next-200`.
2. `GITHUB_TOKEN=… python3 scripts/fetch_corpus.py` — incremental; with a
   populated gitignored `state.json` it lists each repo's closed set and
   skips saved numbers (~seconds, 0 new fetches).
3. `python3 scripts/distill.py --limit 200` — picks the next 200
   undistilled by comments desc (+ a few G7/broadcast anchors). Prints
   `ok`/`REJECT` per thread and a closing summary
   (`batch done … | distilled total=N parked=M`, `REMAINING undistilled`).
   Observed: ~200 threads ≈ 2 min at default 4 workers,
   prompt+completion tokens ≈ 425k, est. cost ≈ $0.07 (deepseek-chat).
4. Run the §site-build sequence — `python3 scripts/build_index.py` &&
   `npm run astro` (or `npm run build`) — then
   `python3 scripts/validate_distilled.py` (must print `0 failed`) and
   `node scripts/search_check.mjs` (must print ALL CHECKS PASSED); then
   commit ONLY `data/` + `site/` (rejects, state.json, manifest churn,
   regenerated site outputs included).
5. `git pull --rebase origin main && git push` (retry ≤3 on reject) — a
   branch push is enough; the queue harness opens/merges the PR, CI build
   runs on it, deploy fires on main. If the remote shared branch has
   diverged with content absent from main, cherry-pick that content first
   and push `--force-with-lease` (gotcha 15).
6. Batch bookkeeping reconciles exactly: new-distilled + new-parked =
   attempts, and `3387 − distilled − parked = REMAINING`.

The phase-2 acceptance batch (task 155) uses the same distiller without the
flock — it is the reason a batch's 90-min lock wait exists.

### Task 208 rollup observation

A completed nightly batch may produce fewer than 200 records when strict
schema/quote validation parks rejects; use the distiller's final
`REMAINING undistilled threads` line for successor decisions. The 2026-09-07
batch produced 194 records and 6 parked rejects, leaving 1684 undistilled.
