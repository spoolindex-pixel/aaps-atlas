#!/usr/bin/env python3
"""Pull closed, most-discussed GitHub threads into data/threads/*.json.

Uses `gh api` (REST, auth from gh config — no tokens in env/scripts).
Selection per repo:
  1. pool = closed issues, list endpoint sorted by comment count desc
     (most-discussed = most likely to contain a worked-out solution).
     /search/issues returns 404 for fine-grained tokens, so we sort the
     plain issue list instead.
  2. skip long-tail wishlist/feature-request threads (denylist, xDrip only)
     that are not "solved problem" conversations.
  3. core = first 25 that survive.
  4. topic anchors = small explicit extras (native-G7 / broadcast threads)
     so the demo's canonical queries always hit threads, not just docs.

Each record: id, repo, number, title, html_url, state, labels, created_at,
closed_at, body (<=4000 chars) + up to 10 comments written before close
(each <=1000 chars). Re-runnable: python3 scripts/fetch_threads.py
"""
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "threads"
PER_REPO = 25
REPOS = ["nightscout/AndroidAPS", "NightscoutFoundation/xDrip"]
BODY_MAX = 4000
COMMENT_MAX = 1000
MAX_COMMENTS = 10

# Long-tail wishlist/feature-request threads (title regex) that are NOT
# "solved problem" conversations — dropped before picking the core 25.
WISHLIST_RE = re.compile(
    r"tizen|amazfit|fitbit|garmin|huawei.*watch|miband|\bmi band\b|pendiq|tidepool|"
    r"complications|always on display|testers wanted|watch face|smartwatch|ticwatch|"
    r"number wall|640g|basal input|watch collector|force collection on smartwatch",
    re.IGNORECASE,
)
# Explicit solved-thread anchors for demo queries the top slice may miss
# (native G7 / broadcast discussion). Numbers are only added when absent.
TOPIC_ANCHORS = {
    "NightscoutFoundation/xDrip": [4442, 3688, 1058],  # G7 backfill / new G7 sensor / broadcast
}


def gh(args: list[str]) -> Any:
    out = subprocess.run(["gh", "api", *args], check=True, capture_output=True, text=True)
    try:
        return json.loads(out.stdout)
    except ValueError as exc:
        raise RuntimeError(f"gh api {' '.join(args)} returned non-JSON") from exc


def iso_le(a: str, b: str | None) -> bool:
    """True when a <= b; b None means 'no close date' (keep)."""
    if b is None:
        return True
    return datetime.fromisoformat(a.replace("Z", "+00:00")) <= datetime.fromisoformat(b.replace("Z", "+00:00"))


def issue_pool(repo: str, pages: int = 12) -> list[dict]:
    """Closed issues sorted by comment count desc, pulled page by page."""
    pool: list[dict] = []
    for page in range(1, pages + 1):
        page_items = gh(["-X", "GET", f"repos/{repo}/issues",
                         "-f", "state=closed", "-f", "sort=comments",
                         "-f", "direction=desc", "-f", "per_page=100",
                         "-f", f"page={page}"])
        pool.extend(i for i in page_items if i.get("pull_request") is None)
        if not page_items or len(pool) >= 400:
            break
    return pool


def pick(repo: str, pool: list[dict]) -> list[dict]:
    kept: list[dict] = []
    seen: set[int] = set()
    for it in pool:
        if it["number"] in seen:
            continue
        seen.add(it["number"])
        if WISHLIST_RE.search(it["title"] or ""):
            continue
        kept.append(it)
        if len(kept) >= PER_REPO:
            break
    by_number = {it["number"]: it for it in pool}
    for number in TOPIC_ANCHORS.get(repo, []):
        if number not in {it["number"] for it in kept} and number in by_number:
            kept.append(by_number[number])
    return kept


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    for f in OUT.glob("*.json"):
        if f.name != "manifest.json":
            f.unlink()
    total = 0
    per_repo: dict[str, int] = {}
    for repo in REPOS:
        pool = issue_pool(repo)
        per_repo[repo] = len(pool)
        for it in pick(repo, pool):
            number = it["number"]
            comments = gh(["-X", "GET", f"repos/{repo}/issues/{number}/comments", "-f", "per_page=100"])
            # keep the resolution arc: earliest comments up to issue close
            comments = [c for c in comments if iso_le(c["created_at"], it.get("closed_at"))][:MAX_COMMENTS]
            record = {
                "id": it["id"],
                "repo": repo,
                "number": number,
                "title": it["title"],
                "html_url": it["html_url"],
                "state": it["state"],
                "labels": [lab["name"] for lab in it.get("labels") or []],
                "created_at": it["created_at"],
                "closed_at": it.get("closed_at"),
                "comment_count": it["comments"],
                "body": (it.get("body") or "")[:BODY_MAX],
                "comments": [
                    {"id": c["id"], "user": (c.get("user") or {}).get("login", "?"),
                     "created_at": c["created_at"], "body": (c.get("body") or "")[:COMMENT_MAX]}
                    for c in comments
                ],
            }
            fname = f"{repo.split('/')[1].lower()}-{number}.json"
            (OUT / fname).write_text(json.dumps(record, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
            total += 1
            print(f"ok   {fname:22s} #{number} cmts={it['comments']:<4d} kept={len(comments):<2d}  {it['title'][:70]}")
    manifest = {
        "fetched_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "count": total,
        "pool_size": per_repo,
        "selection": [
            "pool = closed issues sorted by GitHub comment count desc (via issue-list endpoint; /search/issues 404s on fine-grained tokens)",
            "skip long-tail wishlist/feature-request threads (title denylist, xDrip mostly)",
            "core = first 25 per repo; plus explicit native-G7/broadcast topic anchors from TOPIC_ANCHORS when the core missed them",
        ],
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"\n{total} thread records -> {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
