#!/usr/bin/env python3
"""pick_anchors.py — find G7/broadcast demo-anchor candidates in the corpus.

Prints corpus threads whose text contains BOTH a G7 token and a
broadcast-family token (broadcast/companion/byoda), ranked by comment count
desc — the distilled records of these threads make the canonical "G7
broadcast" demo query return distilled hits. Read-only helper (used once to
set ANCHOR_STEMS in scripts/distill.py).
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CORPUS = ROOT / "data" / "corpus"

G7_RE = re.compile(r"\b(?:dexcom\s+)?g7\b", re.I)
BCAST_RE = re.compile(r"\b(?:broadcast|companion|byoda)\b", re.I)


def main() -> int:
    cands = []
    for path in sorted(CORPUS.glob("*-*.json")):
        if path.name in ("state.json", "manifest.json"):
            continue
        try:
            d = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        text = " ".join([d.get("title", ""), d.get("body", "")] +
                        [c.get("body", "") for c in d.get("comments") or []])
        if not G7_RE.search(text) or not BCAST_RE.search(text):
            continue
        cands.append((d.get("comment_count", 0), path.stem, d.get("title", "")))
    cands.sort(key=lambda x: x[0], reverse=True)
    print(f"{len(cands)} G7+broadcast threads in corpus (top 15 by comments):")
    for cc, stem, title in cands[:15]:
        print(f"  {stem:24s} cc={cc:<4d} {title[:80]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
