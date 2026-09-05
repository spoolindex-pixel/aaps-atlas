# AAPS Atlas — AGENTS.md

AAPS Atlas = a static, client-side-searchable knowledge base of AAPS/xDrip
troubleshooting: an official docs mirror (data/docs/) + solved GitHub threads
(data/threads/) served as a zero-backend static site (site/) deployed to
**Cloudflare Pages**. GitHub-canonical repo, public, under spoolindex-pixel.

## Stack / shape

- **Python 3.10** (stdlib only) for everything: fetch scripts + `build_index.py`.
- **Static site**: hand-written `index.html` + vanilla JS search (no framework,
  no runtime CDN). Index prebuilt to `site/search-index.json` by the build script
  (+ `site/search-data.js` copy so `file://` works). Dark theme, spoolindex family.
- **Deploy**: Cloudflare Pages via `wrangler pages deploy site` — gated on the
  `CLOUDFLARE_API_TOKEN` secret (job skipped when absent). GitHub Actions CI.

## Key commands

| Command | What |
| --- | --- |
| `python3 scripts/fetch_docs.py` | Re-mirror docs pages → `data/docs/*.md` (first line = source URL) |
| `python3 scripts/fetch_threads.py` | Re-pull closed GitHub threads → `data/threads/*.json` (needs `gh` auth) |
| `python3 scripts/build_index.py` | Build `site/search-index.json` (+ `search-data.js`, `site/docs/*.html`); prints corpus stats |
| `python3 -m http.server 8000 -d site` | Local preview of the site |
| `ci` | GitHub Actions: `build` (index + site exists) then `deploy` (CF Pages, token-gated) |

## Conventions

- Git identity: `spoolindex` / `271381609+spoolindex-pixel@users.noreply.github.com`
  (GitHub-canonical — never change).
- Branches `feat/<task>-<slug>` → PR → merge to `main` (main auto-deploys).
  Conventional commits + `Refs <id>` footer + `Co-Authored-By: pi`.
- Never commit secrets; CF deploy token lives in repo secret `CLOUDFLARE_API_TOKEN`
  only (mirrored from vault item `aaps-atlas-cf-token`).
- Never start dev servers — verify with `python3 scripts/build_index.py` +
  the index assertions in `scripts/selftest.py`.

## Top gotchas

1. **Attribution mandatory**: every indexed record carries its origin URL — docs
   link to a local page (source URL shown), threads link back to the GitHub issue.
2. **Data files are deterministic snapshots.** Re-running a fetch script rewrites
   `data/`; keep fetched snapshots committed so the index is reproducible.
3. **GitHub REST search sort=comments requires auth** — `gh api` only (token in
   gh config, never in env vars/scripts). Rate budget ≈ 55 calls / ~1 min.
4. **No runtime CDN/network**: search-index.json + search.js must work from a
   plain static host and over `file://`.
5. Raw-thread data only (demo). Phase 2 = LLM symptom→cause→fix distillation;
   do NOT add LLM summaries to the index without a roadmap decision.

## Docs

- `README.md` — overview + rebuild + hosting options + roadmap
- `AGENTS-REFERENCE.md` — deep-dive: layout, data schema, scripts, env, CI/deploy
