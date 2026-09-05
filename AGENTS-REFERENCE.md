# AAPS Atlas — AGENTS-REFERENCE.md

Deep-dive companion to `AGENTS.md`. Pipeline, data schema, search details,
env vars and CI/deploy notes.

## Commands (full)

| Command | What |
| --- | --- |
| `python3 scripts/fetch_docs.py` | Mirror 6 doc pages → `data/docs/*.md` (network; stdlib only) |
| `python3 scripts/fetch_threads.py` | Pull closed threads → `data/threads/*.json` (network; `gh` auth) |
| `python3 scripts/build_index.py` | `data/*` → `site/search-index.json` + `site/search-data.js` + `site/docs/*.html`; prints `docs=N threads=M index=…KiB`; exits 1 under target |
| `node scripts/search_check.mjs` | Acceptance harness — corpus sizes, attribution, demo queries across docs+threads |
| `python3 -m http.server 8000 -d site` | Local preview (also works via `file://` on `index.html`) |

All build/check steps are stdlib Python 3.10+ or Node ≥ 18 — no `npm install`, no runtime CDN.

## Data pipeline

```
wiki.aaps.app / navid200.github.io/xDrip   -> scripts/fetch_docs.py    -> data/docs/*.md
nightscout/AndroidAPS + NightscoutFoundation/xDrip
                                          -> scripts/fetch_threads.py  -> data/threads/*.json
data/docs + data/threads                  -> scripts/build_index.py   -> site/
```

### Doc mirror format

- First line of every `data/docs/*.md` is the source URL (`# Source: <url>`).
- Mirroring strips nav/script/style and keeps headings + body. Two host
  layouts are handled: AAPS wiki (Sphinx, `itemprop="articleBody"`) and
  navid200.github.io xDrip (Jekyll — content after the last `<h1>`).

### Thread record schema (`data/threads/*.json`)

```jsonc
{
  "id": 123, "repo": "nightscout/AndroidAPS", "number": 4027,
  "title": "...", "html_url": "https://github.com/.../issues/4027",
  "state": "closed",
  "labels": ["bug"], "created_at": "...", "closed_at": "...",
  "comment_count": 56,
  "body": "(<=4000 chars)",
  "comments": [ {"id":…, "user": "…", "created_at": "…", "body": "(<=1000 chars)"} ]  // <=10, written before close
}
```

Selection: closed issues sorted by **comment count desc** (list endpoint —
`/search/issues` returns 404 on fine-grained tokens). Long-tail
wishlist/feature-request threads are skipped via `WISHLIST_RE`;
`TOPIC_ANCHORS` adds native-G7/broadcast threads so demo queries hit threads.
Rationale lives in `data/threads/manifest.json`. **Snapshots are committed** —
re-running a fetch rewrites data/.

## Search engine (site/search.js)

- Prebuilt, normalised records + client-side scoring; **no runtime network**.
- Tokenizer: lowercase, NFKD-fold, split on non-alnum, drop 1-char + stopwords.
- Score per term = `idf × (titleTf×5 + textTf×1)`; multi-term overlap is
  floated up. Synonym map `EXPAND`: `broadcast ≈ companion ≈ byoda`
  (all mean the G7/G6→AAPS/xDrip delivery path).
- Same file is `require()`d by `scripts/search_check.mjs` — the harness tests
  the exact page algorithm.
- Data loading: over `http(s)` fetch `search-index.json`; over `file://`
  inject `search-data.js` (defines `window.__AAPS_INDEX__`).

## Env vars / secrets

| Var | Where | Needed for |
| --- | --- | --- |
| — | `gh` CLI config | `fetch_threads.py` (never a token in env/scripts) |
| `CLOUDFLARE_API_TOKEN` | GitHub repo secret (mirror of vault item `aaps-atlas-cf-token`) | CF Pages deploy job |
| `CLOUDFLARE_ACCOUNT_ID` | GitHub repo secret (optional) | CF Pages deploy job |

Deploy is fully token-gated in CI — no token ⇒ deploy steps are skipped and a
notice prints the one manual setup step. No `.env` required locally.

## CI / deploy

`.github/workflows/ci.yml`:

1. `build` — build_index.py, search_check.mjs, static-artifact assertions,
   upload `site/` artifact. Runs on every PR + push to main.
2. `deploy` — needs build, main-only, gated on `secrets.CLOUDFLARE_API_TOKEN`.
   Creates the Pages project (continue-on-error), then
   `wrangler pages deploy site --project-name aaps-atlas`.

## Gotchas

1. `gh api` with `-f` params POSTs by default — always pass `-X GET` for
   reads (issues list + comments).
2. GitHub fine-grained tokens cannot use `/search/issues` (404) — sort the
   plain issues list by `sort=comments&direction=desc` instead.
3. Repo mirror text is community content: markdownlint/typo advisories on
   `data/` (proprietary terms, heading structure) are expected and safe to
   ignore — the build/CI checks are the gate.
4. `site/search-index.json` and `search-data.js` are generated — edit
   `scripts/build_index.py`, not the outputs. `site/docs/*.html` likewise.
5. Ruff S310 (urlopen) is suppressed per-line with `# noqa: S310` after the
   scheme allowlist; do not remove the guard.
