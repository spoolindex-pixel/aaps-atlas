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
| `python3 scripts/validate_distilled.py` | CI gate: re-validates every distilled record (schema + url + verbatim-quote/devices containment vs corpus) |
| `python3 scripts/build_index.py` | `data/*` → `site/search-index.json` + `site/search-data.js` + `site/docs/*.html`; prints `docs=N threads=M distilled=K index=…KiB`; exits 1 under target |
| `node scripts/search_check.mjs` | Acceptance harness — corpus sizes, attribution, demo queries across docs+threads+distilled |
| `python3 -m http.server 8000 -d site` | Local preview (also works via `file://` on `index.html`) |

All build/check steps are stdlib Python 3.10+ or Node ≥ 18 — no `npm install`, no runtime CDN.

## Data pipeline

```
wiki.aaps.app / navid200.github.io/xDrip   -> scripts/fetch_docs.py    -> data/docs/*.md
nightscout/AndroidAPS + NightscoutFoundation/xDrip
                                          -> scripts/fetch_threads.py  -> data/threads/*.json   (demo slice)
                                          -> scripts/fetch_corpus.py   -> data/corpus/*.json     (full archive)
data/corpus/*.json (priority: comment count desc) -> scripts/distill.py -> data/distilled/*.json
data/docs + data/threads + data/distilled -> scripts/build_index.py   -> site/
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
  `deepseek` key in `~/.pi/agent/auth.json` — the robit/pi default
  provider), `AAPS_LLM_BASE_URL` (default `https://api.deepseek.com`),
  `AAPS_LLM_MODEL` (default `deepseek-chat`). Prints prompt/completion token
  totals + est. cost (list price ~$0.14/$0.28 per M → a 200-thread batch
  ≈ $0.10-0.25; observed $0.10).

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
  Current standing (after task 155's first batch): **251 records**, 52
  parked, 3084 undistilled.

### Batch-run recovery (ad hoc)

If a run's prompt/validator is improved, previously-parked rejects can be
re-attempted by un-parking their stems from `data/distilled/state.json` and
re-running them through `distill.distill_one` (retry-once contract still
applies; successes land as records, failures re-park). Task 155 used this to
recover 9/17 first-pass rejects after the prompt/norm_quote hardening.

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
  (`window.__AAPS_INDEX__`).
- `site/search-index.json`, `search-data.js`, `site/docs/*.html` are
  generated — edit `scripts/build_index.py`, not the outputs.

## Env vars / secrets

| Var | Where | Needed for |
| --- | --- | --- |
| — | `gh` CLI config | `fetch_threads.py` (never a token in env/scripts) |
| `GITHUB_TOKEN` | env only (never committed) | `fetch_corpus.py` full-corpus fetch |
| `AAPS_LLM_API_KEY` / `AAPS_LLM_BASE_URL` / `AAPS_LLM_MODEL` | env (optional; default = deepseek key in `~/.pi/agent/auth.json`) | `distill.py` |
| `CLOUDFLARE_API_TOKEN` | GitHub repo secret (mirror of vault item `aaps-atlas-cf-token`) | CF Pages deploy job |
| `CLOUDFLARE_ACCOUNT_ID` | GitHub repo secret (optional) | CF Pages deploy job |

Deploy is fully token-gated in CI — no token ⇒ deploy steps are skipped and a
notice prints the one manual setup step. No `.env` required locally.

## CI / deploy

`.github/workflows/ci.yml`:

1. `build` — build_index.py, **validate_distilled.py** (schema + url + quote
   containment gate), search_check.mjs, static-artifact assertions, upload
   `site/` artifact. Runs on every PR + push to main.
2. `deploy` — needs build, main-only, gated on `secrets.CLOUDFLARE_API_TOKEN`.
   Creates the Pages project (continue-on-error), then
   `wrangler pages deploy site --project-name aaps-atlas`.

## Gotchas

1. `gh api` with `-f` params POSTs by default — always pass `-X GET` for
   reads (issues list + comments).
2. GitHub fine-grained tokens cannot use `/search/issues` (404) — both
   fetchers use the plain issues list endpoint (fetch_threads sorts by
   `sort=comments`; fetch_corpus pages the whole closed set).
3. Repo text is community content: markdownlint/typo advisories on `data/`
   (proprietary terms, heading structure, real typos in issue text) are
   expected and safe to ignore — the build/CI checks are the gate.
4. Generated outputs live in `site/` — edit `scripts/build_index.py`, never
   the generated files.
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
