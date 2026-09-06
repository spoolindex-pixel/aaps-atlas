# AAPS Atlas

**A searchable AAPS / xDrip knowledge base** — a mirror of official docs,
real solved GitHub issue threads, and **distilled symptom → cause → fix
records** extracted from those threads, searched 100% client-side with zero
backend.

> **Not medical advice.** This is a search demo over community documentation
> and resolved GitHub issue discussions (AAPS & xDrip). Docs mirror and raw
> thread text is reproduced verbatim; distilled records are
> **AI-generated extracts** — every one is labelled, carries a verbatim
> evidence quote and links back to its source thread. Always confirm any
> change with the official docs, your clinician and your regional
> regulations before acting on it.

**Live search ideas:** `G7 broadcast` · `pod activation` ·
`Android 16 bluetooth` · `sensor restart`

---

## What this is

Two corpora, one prebuilt client-side index:

| Corpus | Content | Source | Attribution |
| --- | --- | --- | --- |
| **Docs** (`data/docs/`) | 6 mirrored official pages (clean text) | [wiki.aaps.app](https://wiki.aaps.app) + [navid200.github.io/xDrip](https://navid200.github.io/xDrip/) | every doc page shows its source URL; cards link to a local mirror page |
| **Threads** (`data/threads/`) | 53 closed GitHub issue discussions (demo slice) | [nightscout/AndroidAPS](https://github.com/nightscout/AndroidAPS) + [NightscoutFoundation/xDrip](https://github.com/NightscoutFoundation/xDrip) | every card links back to the original GitHub issue |
| **Distilled** (`data/distilled/`) | AI-extracted symptom → cause → fix records (batched LLM runs over the full corpus) | same threads, distilled by script | every record: issue number + `url` + verbatim evidence quote + confidence |

The site (`site/`) is hand-written `index.html` + vanilla JS — no
framework, **no CDN/network at runtime**. The index is prebuilt by a script
into `site/search-index.json` (and `site/search-data.js` so opening
`index.html` straight from disk with `file://` works). Filter chips narrow
results by type (docs / raw thread / distilled) and by device (G7, DASH,
Omnipod 5, …) or Android version.

## Try it locally

```bash
# option A — open the built site from disk (file:// works)
open site/index.html

# option B — tiny static server
python3 -m http.server 8000 -d site
# -> http://localhost:8000
```

Type `pod activation` — you should get the Omnipod DASH docs page plus the
solved threads about pod activation problems, each labeled `docs` or
`thread`.

## Rebuild everything (data → index → site)

```bash
python3 scripts/fetch_docs.py     # re-mirror docs pages into data/docs/   (network)
python3 scripts/fetch_threads.py  # re-pull demo threads into data/threads/ (needs `gh` auth)
GITHUB_TOKEN=… python3 scripts/fetch_corpus.py   # full closed-issue corpus -> data/corpus/ (network)
python3 scripts/distill.py        # next ~200 undistilled threads -> data/distilled/ (LLM batch)
python3 scripts/validate_distilled.py  # schema + url + quote-containment gate
python3 scripts/build_index.py    # docs + threads + distilled -> site/search-index.json (+ search-data.js, site/docs/*.html)
node    scripts/search_check.mjs  # acceptance harness: corpus sizes, attribution, demo queries
```

- `build_index.py` prints corpus stats
  (`docs=N threads=M distilled=K index=…KiB`) and exits non-zero if the
  corpus is under target or a record lacks its source URL / `html_url`.
- `search_check.mjs` runs the **same** `site/search.js` algorithm used by the
  page against the built index and requires hits across docs, threads and
  distilled records for the demo queries.
- No secrets needed to build; `fetch_threads.py` uses the `gh` CLI's existing
  auth, `fetch_corpus.py` needs `GITHUB_TOKEN` in env, and `distill.py` takes
  `AAPS_LLM_API_KEY` in the environment (or a default-provider config file in
  the operator's home directory) — never a token in env files or scripts.

## Layout

```
data/docs/*.md          mirrored doc pages (first line = source URL)
data/threads/*.json     demo thread records (phase-1 schema) + manifest.json
data/corpus/*.json      full closed-issue archive (phase-1 schema, widened caps)
data/corpus/raw/*.jsonl full-fidelity API lines (gitignored; re-fetch to regenerate)
data/distilled/*.json   distilled S-C-F records + rejects/ + state.json
scripts/fetch_docs.py   mirror docs (stdlib urllib + html.parser)
scripts/fetch_threads.py  demo-slice threads via GitHub REST (gh api)
scripts/fetch_corpus.py   full corpus fetch, resumable (GITHUB_TOKEN env)
scripts/distill.py      LLM batch distiller (corpus -> distilled; ~200/run)
scripts/validate_distilled.py  schema/url/quote gate over data/distilled/
scripts/build_index.py  corpus -> client index + local doc pages
scripts/search_check.mjs  acceptance checks (node)
site/                   static site: index.html, style.css, search.js,
                        search-index.json (+ search-data.js), docs/*.html
.github/workflows/ci.yml  build+checks, then token-gated CF Pages deploy
```

## Distillation (phase 2)

Every solved GitHub thread in the full corpus becomes a **symptom → cause →
fix** record via `scripts/distill.py`. Anti-hallucination is the #1
requirement:

- one thread per prompt, strict extract-only system prompt; every field is
  taken **only** from the thread text and is `null` / `[]` when absent;
- the validator rejects records whose evidence quote is not a verbatim
  substring of the thread, or whose device/version/setting entries do not
  literally occur in it — failure is retried once, then parked under
  `data/distilled/rejects/` with the reason;
- **every record carries its GitHub issue number + `url`** and a confidence
  (high / medium / low); unresolved threads get `low` with `cause`/`fix`
  null rather than invented answers;
- distilled records are labelled on the site and always link back to the raw
  thread (raw thread records stay searchable as before).

**Cost / batching:** distillation runs are capped at **~200 threads per run**
(back-to-back batch tasks; one batch per task — do not chain). The corpus is
prioritised by comment count desc and already-distilled threads are skipped
via `data/distilled/state.json`. Each run prints token totals + estimated
cost — a 200-thread batch is roughly **$0.10–0.25** at the default model's
list price (deepseek-chat ≈ $0.14/$0.28 per M tokens).

**Corpus reality check:** the full *closed*-issue archive is **3387** threads
(AAPS 1846 + xDrip 1541). Earlier estimates (~2.1k/1.6k, “~3.7k archive”)
counted open issues too — 3387 *is* the complete closed set.

### Data notes

- **Docs**: text mirrors (no code), fetched with stdlib; heading structure
  kept; first line of each `.md` is the source URL.
- **Threads** (demo slice): closed issues chosen per repo by **comment count
  (desc)** = most-discussed = most likely to contain a worked-out solution
  (the GitHub list endpoint sorts this way; `/search/issues` 404s on
  fine-grained tokens, so the list endpoint is used instead). Long-tail
  wishlist/feature-request threads are skipped, plus a few explicit
  native-G7/broadcast anchors so demo queries always have thread hits. The
  selection rule is in `data/threads/manifest.json`.
- **Corpus** (phase 2): the full closed archive (`fetch_corpus.py`) —
  per-thread files keep the same schema with widened caps (body ≤ 8k, ≤ 40
  head/tail comments ≤ 2k each); the unbounded raw archive lives in
  `data/corpus/raw/` (gitignored, re-fetchable).
- **Distilled** (phase 2): LLM-extracted S-C-F records, one per corpus
  thread, distilled in ~200-thread batches.
- Current index: **6 docs, 53 raw threads, 251 distilled records** (first
  ~200-thread batch; grows with each later batch task), index ≈ 1.1 MiB raw
  (~220 KiB gzipped).

## Hosting options (all free tier)

| Host | Static file deploy | CI integration |
| --- | --- | --- |
| **Cloudflare Pages** ← chosen | `wrangler pages deploy site --project-name aaps-atlas` | `.github/workflows/ci.yml` has a `deploy` job that runs on every `main` push |
| GitHub Pages | Publish `site/` via Actions | Add `actions/deploy-pages` job (not configured) |
| Vercel | `vercel deploy --prod` with output dir `site` | Standard Vercel git integration (not configured) |

### Cloudflare Pages wiring (decided)

`ci.yml` uploads the built `site/` as an artifact from the `build` job, and a
`deploy` job deploys it on every push to `main`:

```yaml
env:
  CLOUDFLARE_API_TOKEN:  ${{ secrets.CLOUDFLARE_API_TOKEN }}   # Pages:Edit
  CLOUDFLARE_ACCOUNT_ID: ${{ secrets.CLOUDFLARE_ACCOUNT_ID }}  # optional
```

The deploy job is **fully gated on the token**: without
`CLOUDFLARE_API_TOKEN` in repo secrets it skips deployment and prints a
notice, so the repo is always ready-to-deploy.

**Single manual step (CF token needed):** create an API token with
`Cloudflare Pages:Edit` permission and add it as the repo secret
`CLOUDFLARE_API_TOKEN` (optionally `CLOUDFLARE_ACCOUNT_ID`). After that, every
push to `main` deploys `site/` automatically. First deploy auto-creates the
Pages project (`--production-branch=main`); no secrets are ever committed to
this repo.

## Roadmap

1. ~~**Demo** — docs mirror + solved-thread search~~ *(done, phase 1)*
2. **Full corpus + distillation** — full closed-issue archive fetched
   (`data/corpus/`, 3387 threads) and batch LLM distillation into
   symptom → cause → fix records with filters on the site. *(in progress,
   phase 2 — one ~200-thread batch per task; cost note above)*
3. **Issue-closed-by-commit links** — surface the commit(s) that closed an
   issue as an extra “fix” signal on distilled records.
4. **Discord knowledge** — if AAPS ever grants a proper bot integration,
   index curated Discord troubleshooting into the same pipeline.

## License / attribution

Code and demo scaffolding: MIT (see repo). Mirrored docs remain © their
original authors (AndroidAPS community, xDrip project); issue text remains ©
its authors, used here under GitHub's terms for linking/attribution. Every
record carries its origin URL; if you are the author of any included content
and want it removed, open an issue and it will be dropped on the next rebuild.
