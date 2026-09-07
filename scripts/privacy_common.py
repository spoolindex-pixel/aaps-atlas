"""Shared helpers for the FB-corpus privacy machinery (stdlib only).

Single source of truth for the two things every privacy gate must agree on:

1. *Pseudonym format* — a stored FB author is `member-<8 hex>` derived from
   an HMAC-SHA256 of the author's stable id keyed by the per-install salt.
2. *Name-leak matching* — how a raw author name is matched against record
   text. Matched as a whole, whitespace-collapsed, case-insensitive phrase
   with word boundaries, so "Sam" can never match inside "sample" but
   "Sofia Petrov" matches "…thanks Sofia Petrov…". Full names and handles
   are the units; never partial-name fragments.

Used by scripts/fb_anonymize.py (maps + fails closed at write time) and
scripts/validate_privacy.py (the CI/ingest gate over stored + distilled
records). Do not fork the logic here into another script.
"""
from __future__ import annotations

import re

# Stored FB comment authors are always pseudonyms of this exact shape.
PSEUDONYM_RE = re.compile(r"^member-[0-9a-f]{8}$")

# Top-level / per-comment keys allowed in a committed anonymized FB thread
# record (data/fb_threads/*.json). The anonymizer builds fresh dicts from
# this whitelist, so any raw profile key (name, user URL, profile-pic URL,
# per-user reactions) can never survive into stored data. If a stored file
# contains a key outside this set, the hygiene gate fails it.
FB_THREAD_KEYS = {
    "id", "source", "group", "group_url", "url", "posted_at", "text",
    "reactions_count", "comment_count", "comments",
}
FB_COMMENT_KEYS = {"pseudonym", "text", "posted_at"}
FB_COMMENT_COUNT_KEYS = (
    "comment_count", "comments_count", "postCommentsCount",
)
FB_REACTION_COUNT_KEYS = (
    "postReactionsCount", "reactionsCount", "reactionCount", "reactions_count",
)

# Key names under which Apify-style Facebook payloads carry a person's real
# name or handle. Only these are harvested into the raw-author roster; every
# other profile field is dropped on principle (see the anonymous output
# whitelist above).
AUTHOR_NAME_KEYS = {
    "name", "fullName", "displayName", "profileName", "userName", "username",
    "screenName", "handle", "author", "authorName", "postAuthor",
    "postAuthorName", "commentAuthor", "commentAuthorName", "from", "actor",
    "createdBy", "postedBy", "user", "owner", "commentAuthorUsername",
}

# Facebook post permalink (the verification linkback kept on every record).
FB_URL_RE = re.compile(r"^https://(?:www\.|m\.|web\.|mobile\.|business\.)?facebook\.com/")


def collapse(s: str) -> str:
    """Lowercased, whitespace-collapsed form used for name-leak matching."""
    return re.sub(r"\s+", " ", (s or "")).lower().strip()


def _is_name_like(value: str) -> bool:
    """Cheap plausibility filter for harvested author strings."""
    v = collapse(value)
    if not v or not any(c.isalpha() for c in v):
        return False
    if "://" in v or v.startswith("http"):
        return False
    # drop trivial tokens (single letter, "new", timestamps, urls-ish junk)
    words = [w for w in re.split(r"[^a-z0-9]+", v) if w]
    if not words:
        return False
    return not all(len(w) <= 2 for w in words)


def name_leak_matches(authors: list[str], text: str) -> list[str]:
    """Return the authors whose *whole* name/handle occurs in `text`.

    Exact-name gate: each author string is matched as one unit, so a stored
    record fails only when it contains the author's actual name/handle, not
    when a common word merely overlaps it. Matching is case-insensitive and
    whitespace-collapsed on both sides.
    """
    hay = collapse(text)
    if not hay:
        return []
    hits = []
    seen = set()
    for author in authors or []:
        name = collapse(author)
        if not _is_name_like(name) or name in seen:
            continue
        seen.add(name)
        # word boundaries so "sam" does not match "sample"; multi-word names
        # are collapsed to single spaces on both sides already.
        if re.search(r"(?<![a-z0-9])" + re.escape(name) + r"(?![a-z0-9])", hay):
            hits.append(author)
    return hits


def harvest_author_names(payload: object) -> list[str]:
    """Extract real author names/handles from an Apify-style payload tree.

    Walks the whole item (post, comments, per-user reaction lists, nested
    user objects) and collects every string found under a name-bearing key.
    Used to build the raw-author roster that the name-leak gate scans for.
    Never returns ids, urls or plain comment bodies.
    """
    found: list[str] = []

    def walk(node: object) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if isinstance(key, str) and key in AUTHOR_NAME_KEYS:
                    if isinstance(value, str) and _is_name_like(value):
                        found.append(value)
                    elif isinstance(value, dict):
                        # e.g. "author": {"name": "…", "id": "…"} — recurse,
                        # the inner "name" key is harvested on the next pass.
                        walk(value)
                else:
                    walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(payload)
    # de-dupe, preserve first-seen order
    return list(dict.fromkeys(found))
