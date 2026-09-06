#!/usr/bin/env python3
"""fetch_corpus.py — incremental, resumable full-corpus GitHub fetcher.

Pulls EVERY closed issue and all of its comments from
nightscout/AndroidAPS and NightscoutFoundation/xDrip into data/corpus/.

Auth: GITHUB_TOKEN env var (required). List endpoint only (no
/search/issues), so fine-grained and classic PATs both work.

Output (deterministic snapshot — commit data/corpus/*.json):
    data/corpus/<repo>-<number>.json   per-thread record (phase-1 schema)
    data/corpus/raw/<repo>.jsonl       raw API lines: issue dict + comments
                                       (gitignored: full-fidelity archive,
                                       regenerable by re-running this script)
    data/corpus/manifest.json          run summary + per-repo counts
    data/corpus/state.json             resume/incremental state (gitignored)

Resume/incremental semantics (state.json):
  * re-running skips issue numbers already saved (their comments are NOT
    re-fetched) — resumes cleanly after rate-limit interruptions;
  * --incremental additionally re-fetches issues whose updated_at is newer
    than the stored watermark (new issues + changed threads since last run).

Rate limiting: watches x-ratelimit-remaining, sleeps through 403/429 with
Retry-After, retries 5xx with backoff. ~3.4k issues ≈ one comment fetch each
≈ a few thousand API calls; run may take ~30-60 min. Safe to interrupt and
re-run.

Usage:
    GITHUB_TOKEN=... python3 scripts/fetch_corpus.py [--repo X] [--incremental]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "corpus"
RAW_DIR = OUT / "raw"
STATE_FILE = OUT / "state.json"
MANIFEST_FILE = OUT / "manifest.json"

REPOS = ["nightscout/AndroidAPS", "NightscoutFoundation/xDrip"]
PER_PAGE = 100
BODY_MAX = 8000        # issue body kept (chars)
COMMENT_MAX = 2000     # per-comment body kept (chars)
HEAD_COMMENTS = 15     # earliest chronological comments kept
TAIL_COMMENTS = 25     # latest chronological comments kept (resolution arc)
MIN_COMMENT_TOPUP = 10 # tiny-thread top-up from post-close comments
MAX_COMMENT_PAGES = 60 # safety cap on comment pagination per issue
UA = {"User-Agent": "aaps-atlas-corpus/2.0 (+https://github.com/spoolindex-pixel/aaps-atlas)"}

SLEEP_BETWEEN_CALLS = 0.12  # politeness pacing between API calls (sec)
HTTP_TIMEOUT = 30


class RateLimited(Exception):
    pass


def api_get(path: str, params: list[tuple[str, str]]) -> tuple[list | dict, dict]:
    """GET an api.github.com path with auth + pacing + rate-limit handling."""
    from urllib.parse import urlencode
    url = f"https://api.github.com{path}"
    if params:
        url += "?" + urlencode(params)
    if not url.startswith("https://"):
        raise ValueError(f"refusing non-https url: {url}")
    last_err: Exception | None = None
    for attempt in range(6):
        req = urllib.request.Request(url, headers={  # noqa: S310 (https only, allowlisted above)
            "Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}",
            "Accept": "application/vnd.github+json",
            **UA})
        try:
            with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:  # noqa: S310 (https only, allowlisted above)
                remaining = resp.headers.get("X-RateLimit-Remaining")
                if remaining is not None and int(remaining) == 0:
                    reset = int(resp.headers.get("X-RateLimit-Reset", "0"))
                    sleep = max(1, reset - time.time() + 2)
                    print(f"  rate limit exhausted — sleeping {sleep:.0f}s", flush=True)
                    time.sleep(sleep)
                    raise RateLimited()
                return json.load(resp), dict(resp.headers)
        except RateLimited:
            raise
        except urllib.error.HTTPError as err:
            body = err.read(400).decode("utf-8", "replace")
            retry_after = err.headers.get("Retry-After")
            if err.code in (403, 429):
                wait = float(retry_after) if retry_after else 60.0
                print(f"  HTTP {err.code} — sleeping {wait:.0f}s ({body[:120]})", flush=True)
                time.sleep(min(wait, 900))
                continue
            if err.code in (500, 502, 503, 504):
                time.sleep(5 * (attempt + 1))
                continue
            raise
        except (urllib.error.URLError, TimeoutError, OSError) as err:
            last_err = err
            time.sleep(4 * (attempt + 1))
    raise RuntimeError(f"GET {path} failed after retries: {last_err}")


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return {"repos": {}}


def save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=1), encoding="utf-8")


def clip(s: str | None, n: int) -> str:
    return (s or "")[:n]


def to_int(v: object, default: int = 0) -> int:
    """int() with a safe fallback for JSON values that may be null/missing."""
    try:
        return int(v)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def iso_le(a: str | None, b: str | None) -> bool:
    """True when a <= b; None bound means 'no close date' (unbounded)."""
    if a is None:
        return False
    if b is None:
        return True
    return a <= b  # GitHub ISO-8601 timestamps compare lexically


def keep_comments(raw_comments: list[dict], closed_at: str | None) -> list[dict]:
    """Phase-1-shaped comment selection: setup context + resolution arc.

    Chronological view; pre-close comments preferred (resolution happened
    before the issue closed). When a thread has many comments we keep the
    earliest HEAD_COMMENTS plus the latest TAIL_COMMENTS before close so the
    distiller sees both the problem context and how it was resolved.
    """
    ordered = sorted(raw_comments, key=lambda c: c.get("created_at", ""))
    pre = [c for c in ordered if iso_le(c.get("created_at"), closed_at)]
    if len(pre) > HEAD_COMMENTS + TAIL_COMMENTS:
        kept = pre[:HEAD_COMMENTS] + pre[-TAIL_COMMENTS:]
    else:
        kept = pre
    if len(kept) < MIN_COMMENT_TOPUP:
        post = [c for c in ordered if not iso_le(c.get("created_at"), closed_at)]
        kept = kept + post[: MIN_COMMENT_TOPUP - len(kept)]
    return kept


def fetch_issue_comments(repo: str, number: int) -> list[dict]:
    all_c: list[dict] = []
    for page in range(1, MAX_COMMENT_PAGES + 1):
        items, _ = api_get(
            f"/repos/{repo}/issues/{number}/comments",
            [("per_page", "100"), ("page", str(page))])
        if not isinstance(items, list) or not items:
            break
        all_c.extend(items)
        if len(items) < 100:
            break
    time.sleep(SLEEP_BETWEEN_CALLS)
    return all_c


def process_issue(item: dict, repo: str, state_repo: dict) -> None:
    """Fetch comments for one issue, write raw line + per-thread json."""
    number = to_int(item.get("number"))
    comments = fetch_issue_comments(repo, number)

    raw_path = RAW_DIR / f"{repo.split('/')[1].lower()}.jsonl"
    with raw_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"issue": item, "comments": comments},
                            ensure_ascii=False, separators=(",", ":")) + "\n")

    kept = keep_comments(comments, item.get("closed_at"))
    record = {
        "id": item["id"],
        "repo": repo,
        "number": number,
        "title": item["title"],
        "html_url": item["html_url"],
        "state": item["state"],
        "labels": [lab["name"] for lab in item.get("labels") or []],
        "created_at": item["created_at"],
        "closed_at": item.get("closed_at"),
        "comment_count": to_int(item.get("comments")),
        "body": clip(item.get("body"), BODY_MAX),
        "comments": [
            {"id": c["id"], "user": (c.get("user") or {}).get("login", "?"),
             "created_at": c.get("created_at", ""),
             "body": clip(c.get("body"), COMMENT_MAX)}
            for c in kept
        ],
    }
    dest = OUT / f"{repo.split('/')[1].lower()}-{number}.json"
    tmp = dest.with_suffix(".tmp")
    tmp.write_text(json.dumps(record, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    tmp.replace(dest)

    state_repo["saved"].append(number)
    state_repo["last_updated"] = max(
        state_repo.get("last_updated") or "", item.get("updated_at") or "") or None


def sync_repo(repo: str, incremental: bool) -> dict:
    state = load_state()
    st = state["repos"].setdefault(repo, {"saved": [], "last_updated": None,
                                          "closed_total": 0, "skipped_prs": 0})
    saved = {to_int(n) for n in st["saved"]}
    watermark = st.get("last_updated")
    closed_seen = 0
    pr_seen = 0
    fetched = 0
    skipped = 0
    print(f"== {repo} (saved {len(saved)}, incremental={incremental})", flush=True)

    for page in range(1, 1000):
        items, _ = api_get(f"/repos/{repo}/issues",
                           [("state", "closed"), ("per_page", str(PER_PAGE)),
                            ("page", str(page))])
        if not isinstance(items, list) or not items:
            break
        for item in items:
            number = to_int(item.get("number"))
            if not number or item.get("pull_request"):
                pr_seen += 1
                st["skipped_prs"] = pr_seen
                continue
            closed_seen += 1
            if (not incremental and number in saved) or \
               (incremental and number in saved and
                (item.get("updated_at") or "") <= (watermark or "")):
                skipped += 1
                continue
            process_issue(item, repo, st)
            fetched += 1
            if fetched % 25 == 0:
                save_state(state)
                print(f"  ... {len(st['saved'])} saved / {closed_seen} closed seen", flush=True)
        time.sleep(SLEEP_BETWEEN_CALLS)
        if len(items) < PER_PAGE:
            break

    st["closed_total"] = closed_seen
    # drop numbers no longer closed (should not happen; keeps saved honest)
    st["saved"] = sorted(set(st["saved"]))
    save_state(state)
    return {"closed_seen": closed_seen, "pr_skipped": pr_seen,
            "fetched": fetched, "skipped": skipped, "saved": len(st["saved"])}


def main() -> int:
    ap = argparse.ArgumentParser(description="Fetch full closed-issue corpus from GitHub into data/corpus/.")
    ap.add_argument("--repo", choices=REPOS, help="only this repo")
    ap.add_argument("--incremental", action="store_true",
                    help="re-fetch issues updated after the stored watermark")
    ap.add_argument("--force-refetch", action="store_true",
                    help="re-fetch comments for already-saved issues too")
    args = ap.parse_args()

    if not os.environ.get("GITHUB_TOKEN"):
        print("ERROR: GITHUB_TOKEN env var is required (GitHub API auth).", file=sys.stderr)
        return 1

    OUT.mkdir(parents=True, exist_ok=True)
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    repos = [args.repo] if args.repo else REPOS
    summary: dict[str, dict] = {}
    total_saved = 0
    for repo in repos:
        if args.force_refetch:
            state = load_state()
            state["repos"].setdefault(repo, {"saved": [], "last_updated": None,
                                             "closed_total": 0, "skipped_prs": 0})
            state["repos"][repo]["saved"] = []
            save_state(state)
        summary[repo] = sync_repo(repo, args.incremental)
        total_saved += summary[repo]["saved"]
    manifest = {
        "fetched_at": iso_now(),
        "mode": "incremental" if args.incremental else "full",
        "count": total_saved,
        "per_repo": summary,
        "note": ("full archive of closed issues + comments; per-thread files keep "
                 "phase-1 schema with widened caps (body<=8000, comment<=2000, head+tail "
                 "comment selection); data/corpus/raw/*.jsonl is the unbounded raw archive"),
    }
    MANIFEST_FILE.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"\nTOTAL: {total_saved} closed-issue threads in data/corpus/ "
          f"(AAPS={summary.get(REPOS[0], {}).get('saved')}, "
          f"xDrip={summary.get(REPOS[1], {}).get('saved')})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
