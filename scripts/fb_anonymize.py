#!/usr/bin/env python3
"""fb_anonymize.py — anonymize an Apify Facebook-posts scrape into safe records.

Turns raw Apify actor JSON (a post feed / group scrape) into one anonymized
record per post at data/fb_threads/<group>-<postid>.json:

    {id, source: "facebook", group, group_url, url, posted_at, text,
     comments: [{pseudonym, text, posted_at}], reactions_count?}

HARD PRIVACY RULE (user requirement): NO person names anywhere in stored or
derived data.
  * author -> stable pseudonym "member-<8hex>", an HMAC-SHA256 of the
    author's *stable id* keyed by a per-install salt (env FB_PSEUDONYM_SALT,
    else an auto-generated salt persisted at
    ~/.config/aaps-atlas/fb-pseudonym-salt — never committed). Same author
    id always maps to the same pseudonym across posts/runs.
  * ALL profile fields are dropped at map time: names, profile-pic URLs,
    user URLs, per-user reaction lists. Outputs are built fresh from a
    whitelist (see scripts/privacy_common.py FB_THREAD_KEYS), so a profile
    field cannot survive by accident.
  * only aggregates are kept: comment count (implied by the comments array)
    and an optional numeric reactions count.
  * post permalinks ARE kept for verification linkback.
  * built-in self-check: before writing anything the script verifies no raw
    author name/handle appears in any output text field and FAILS CLOSED
    (exit 1, nothing written) when one does. This is the first name-leak
    gate; scripts/validate_privacy.py is the second, runnable later over
    stored + distilled data with the same raw authors list.

Input shape follows the documented apify/facebook-posts-scraper output
schema (see tests/fixtures/README.md); the field mapping is tolerant to the
common key aliases so a slightly different actor version does not break the
run. Group identity comes from the scrape when present (groupName /
groupUrl / inputUrl), otherwise from the optional --group-* flags — run
per-group scrapes with explicit flags for clean slugs.

Usage:
    python3 scripts/fb_anonymize.py --input tests/fixtures/apify_sample.json \\
        --outdir data/fb_threads
    FB_PSEUDONYM_SALT=… python3 scripts/fb_anonymize.py --input run-123.json \\
        --outdir data/fb_threads --group-slug xdrip-users \\
        --group-name "xDrip+ users" --group-url https://www.facebook.com/groups/471773313486427

Exit 0 = all posts anonymized + written (zero leaks); 1 = leak found (nothing
written) or unreadable input / missing post id or url.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import importlib.util
import json
import os
import re
import secrets
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _load_sibling(name: str):
    """Import a sibling script module regardless of cwd (stdlib-only load,
    same pattern validate_distilled.py uses for distill.py)."""
    path = Path(__file__).resolve().parent / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


privacy = _load_sibling("privacy_common")
collapse = privacy.collapse
harvest_author_names = privacy.harvest_author_names
name_leak_matches = privacy.name_leak_matches
FB_REACTION_COUNT_KEYS = privacy.FB_REACTION_COUNT_KEYS

SALT_ENV = "FB_PSEUDONYM_SALT"
SALT_FILE = Path.home() / ".config" / "aaps-atlas" / "fb-pseudonym-salt"
SLUG_SAFE = re.compile(r"[^a-z0-9]+")

GROUP_NAME_KEYS = ("groupName", "group_name", "pageName", "groupsName", "group")
GROUP_URL_KEYS = ("groupUrl", "group_url", "groupsUrl", "inputUrl")
POST_ID_KEYS = ("id", "postId", "post_id")
POST_URL_KEYS = ("url", "postUrl", "post_url", "permalink")
POST_TEXT_KEYS = ("postText", "post_text", "text", "message", "body")
POST_DATE_KEYS = ("date", "posted_at", "createdAt", "created_at", "timestamp", "time")
COMMENTS_KEYS = ("postComments", "comments", "commentList", "commentsData")
COMMENT_TEXT_KEYS = ("commentText", "text", "message", "body", "comment")
COMMENT_AUTHOR_NAME_KEYS = (
    "commentAuthor", "authorName", "author", "commentAuthorName", "name", "userName", "username", "user",
)
COMMENT_AUTHOR_ID_KEYS = (
    "commentAuthorId", "authorId", "userId", "user_id", "actorId", "author", "user",
)
COMMENT_DATE_KEYS = ("commentTimestamp", "date", "posted_at", "createdAt", "created_at", "timestamp", "time")


def _first_str(mapping: dict, keys: tuple[str, ...]) -> str:
    for key in keys:
        if not isinstance(key, str):
            continue
        value = mapping.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, (int, float)) and key not in ("timestamp", "time"):
            return str(value)
    return ""


def _first_int(mapping: dict, keys: tuple[str, ...]) -> int | None:
    """First numeric-looking value under any of `keys`, else None."""
    for key in keys:
        if not isinstance(key, str):
            continue
        value = mapping.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            try:
                return int(value)
            except (OverflowError, ValueError):
                continue
        if isinstance(value, str) and value.strip().lstrip("-").isdigit():
            try:
                return int(value)
            except ValueError:
                continue
    return None


def _nested(mapping: dict, key: str) -> dict:
    value = mapping.get(key)
    return value if isinstance(value, dict) else {}


def _iso_ts(value: str | int | float) -> str:
    """Normalise a post/comment timestamp to an ISO-8601 UTC string."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            dt = datetime.fromtimestamp(value, tz=timezone.utc)
            return dt.isoformat(timespec="seconds").replace("+00:00", "Z")
        except (OverflowError, OSError, ValueError):
            pass
    s = str(value or "").strip()
    if not s:
        return ""
    if s.isdigit() and len(s) >= 10:
        try:
            dt = datetime.fromtimestamp(int(s[:10]), tz=timezone.utc)
            return dt.isoformat(timespec="seconds").replace("+00:00", "Z")
        except (OverflowError, OSError, ValueError):
            return s
    try:
        # tolerate a trailing Z-less offset or space-separated T
        dt = datetime.fromisoformat(s.replace("Z", "+00:00").replace(" ", "T"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    except ValueError:
        return s[:32]


def load_salt() -> str:
    """Per-install pseudonym salt: env FB_PSEUDONYM_SALT wins, else a salt
    generated once and persisted (mode 0600) under ~/.config/aaps-atlas.
    Refuses to run with a global constant or empty salt."""
    env = os.environ.get(SALT_ENV, "").strip()
    if env:
        return env
    if SALT_FILE.exists():
        value = SALT_FILE.read_text(encoding="utf-8").strip()
        if value:
            return value
    try:
        SALT_FILE.parent.mkdir(parents=True, exist_ok=True)
        value = secrets.token_hex(32)
        SALT_FILE.write_text(value + "\n", encoding="utf-8")
        SALT_FILE.chmod(0o600)
        print(f"note: generated per-install pseudonym salt -> {SALT_FILE} "
              f"(set {SALT_ENV} to rotate; authors map to new pseudonyms)", file=sys.stderr)
        return value
    except OSError as exc:
        raise SystemExit(
            f"ERROR: no pseudonym salt — set {SALT_ENV} or make {SALT_FILE} writable ({exc})"
        ) from exc


def pseudonym_for(salt: str, identity: str) -> str:
    """member-<8hex>: HMAC-SHA256(identity, key=salt), first 8 hex chars."""
    digest = hmac.new(salt.encode("utf-8"), identity.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"member-{digest[:8]}"


def _group_slug(name: str, group_url: str, flag_slug: str) -> str:
    if flag_slug:
        return flag_slug
    if name:
        return SLUG_SAFE.sub("-", collapse(name)).strip("-") or "group"
    m = re.match(r"^https?://[^/]+/groups/([^/?#]+)", group_url or "")
    if m:
        seg = SLUG_SAFE.sub("-", m.group(1).lower()).strip("-")
        if seg:
            return seg
    return "group"


def _comment_identity(comment: dict, index: int, post_id: str) -> tuple[str, str]:
    """Return (stable identity for HMAC, display name for the roster).

    Stable identity preference: author id keys, then nested user/author id,
    then the author name itself, then a per-comment fallback token."""
    name = _first_str(comment, COMMENT_AUTHOR_NAME_KEYS)
    nested = comment
    for probe in ("user", "author", "actor", "from"):
        if isinstance(comment.get(probe), dict):
            nested = comment[probe]
            break
    ident = _first_str(comment, COMMENT_AUTHOR_ID_KEYS)
    if not ident:
        ident = _first_str(nested, ("id", "userId", "user_id", "actorId"))
    if not ident and name:
        ident = name
    if not ident:
        ident = f"anon:{post_id}:{index}"
    return ident, name


def _detect_group(item: dict, flags: dict) -> tuple[str, str, str]:
    """Return (group display name, group_url, slug)."""
    name = flags.get("group_name") or _first_str(item, GROUP_NAME_KEYS)
    url = flags.get("group_url") or _first_str(item, GROUP_URL_KEYS)
    post_url = _first_str(item, POST_URL_KEYS)
    if not url and post_url:
        m = re.match(r"^(https?://[^/]+/groups/[^/?#]+)", post_url)
        if m:
            url = m.group(1)
    slug = flags.get("group_slug") or _group_slug(name, url, "")
    display = name or slug
    return display, url, slug


def build_record(salt: str, item: dict, flags: dict,
                 post_index: int) -> tuple[dict, list[str]]:
    """Map one raw post item -> anonymized record. Returns (record, roster)."""
    post_id = _first_str(item, POST_ID_KEYS)
    post_url = _first_str(item, POST_URL_KEYS)
    if not post_id or not post_url:
        raise ValueError("missing post id or permalink url")
    post_id = re.sub(r"[^A-Za-z0-9_-]", "", post_id)[:120]
    if not post_id:
        raise ValueError("post id collapses to empty after sanitising")

    group_display, group_url, slug = _detect_group(item, flags)
    authors = harvest_author_names(item)  # names/handles seen in the raw item

    comments_out: list[dict[str, str]] = []
    raw_comments = item.get("postComments") or item.get("comments") or item.get("commentList") or []
    for idx, comment in enumerate(raw_comments):
        if not isinstance(comment, dict):
            continue
        ident, name = _comment_identity(comment, idx, post_id)
        pseudonym = pseudonym_for(salt, ident)
        text = _first_str(comment, COMMENT_TEXT_KEYS)
        posted = _iso_ts(_first_str(comment, COMMENT_DATE_KEYS) or comment.get("commentTimestamp", ""))
        comments_out.append({"pseudonym": pseudonym, "text": text, "posted_at": posted})

    record: dict[str, Any] = {
        "id": post_id,
        "source": "facebook",
        "group": group_display,
        "group_url": group_url,
        "url": post_url,
        "posted_at": _iso_ts(_first_str(item, POST_DATE_KEYS)),
        "text": _first_str(item, POST_TEXT_KEYS),
        "comments": comments_out,
    }
    reactions = _first_int(item, FB_REACTION_COUNT_KEYS)
    if reactions is not None:
        record["reactions_count"] = reactions
    return record, authors


def main() -> int:
    ap = argparse.ArgumentParser(description="Anonymize Apify Facebook scrape -> data/fb_threads records")
    ap.add_argument("--input", required=True, help="Apify actor output JSON (array or single post object)")
    ap.add_argument("--outdir", required=True, help="output directory for <group>-<postid>.json records")
    ap.add_argument("--group-slug", default="", help="override group slug for all posts (recommended per-group runs)")
    ap.add_argument("--group-name", default="", help="override group display name")
    ap.add_argument("--group-url", default="", help="override group url")
    ap.add_argument("--roster-out", default="",
                    help="optional path to write the raw author-name roster (JSON array) — point it at a "
                         "GITIGNORED location (e.g. data/fb_threads/raw/authors.json); never commit real names")
    args = ap.parse_args()

    src = Path(args.input)
    try:
        payload = json.loads(src.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"ERROR: cannot read {src}: {exc}", file=sys.stderr)
        return 1
    items = payload if isinstance(payload, list) else [payload]
    items = [i for i in items if isinstance(i, dict)]

    salt = load_salt()
    flags = {"group_slug": args.group_slug, "group_name": args.group_name, "group_url": args.group_url}

    records: list[dict] = []
    roster: list[str] = []
    seen_roster: set[str] = set()
    errors: list[str] = []
    for index, item in enumerate(items):
        try:
            record, authors = build_record(salt, item, flags, index)
        except ValueError as exc:
            errors.append(f"item {index}: {exc}")
            continue
        # ---- name-leak self check over THIS record's text fields ----
        texts = [record["text"]] + [c["text"] for c in record["comments"]]
        leaks = sorted({a for a in authors if any(name_leak_matches([a], t) for t in texts)})
        if leaks:
            errors.append(
                f"post {record['id']} would store real author name(s): {', '.join(leaks)} — "
                "refusing to write (privacy gate); exclude/redact that post and re-run")
        records.append(record)
        for author in authors:
            if author not in seen_roster:
                seen_roster.add(author)
                roster.append(author)

    if errors:
        print("PRIVACY/INPUT ERRORS — nothing written:", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1

    out = Path(args.outdir)
    out.mkdir(parents=True, exist_ok=True)
    for record in records:
        slug = args.group_slug or _group_slug(record["group"], record["group_url"], "")
        path = out / f"{slug}-{record['id']}.json"
        path.write_text(json.dumps(record, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"ok  {path.name} ({len(record['comments'])} comments)")

    if args.roster_out:
        roster_path = Path(args.roster_out)
        roster_path.parent.mkdir(parents=True, exist_ok=True)
        roster_path.write_text(json.dumps(roster, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"roster ({len(roster)} author names) -> {roster_path}  [do not commit]")
    print(f"wrote {len(records)} anonymized record(s) to {out} — zero author-name leaks")
    return 0


if __name__ == "__main__":
    sys.exit(main())
