#!/usr/bin/env python3
"""validate_privacy.py — hard name-leak gate + FB-record hygiene checks.

The second layer of the FB-corpus privacy gate (the first is the built-in
self-check in scripts/fb_anonymize.py). Given the raw author list for a
scrape, this FAILS (exit 1) if ANY scanned record's text fields contain an
exact author name/handle string:

    python3 scripts/validate_privacy.py \\
        --raw    <raw Apify JSON>            # authors auto-extracted
        --authors <authors.json>             # or: explicit name list
        [paths...]                            # records to scan

Scan targets (default: data/fb_threads + data/distilled) are JSON files
holding records; every string under any key of every record is checked —
post text, comment text, distilled symptom/cause/fix/evidence_quote/… —
against every raw author name. Matching is exact-name (whole, collapsed,
case-insensitive with word boundaries — see scripts/privacy_common.py), so
the gate only fires on a real name, never on an overlapping common word.

Also runs FB-record hygiene checks over data/fb_threads/*.json even without
an author list: required keys present, `source` facebook, url is an https
facebook permalink, every comment author is a member-<8hex> pseudonym, and
no key outside the stored-record whitelist survived (a stray profile field
like `name`/`profileUrl` fails). Any file containing a non-pseudonym author
key fails closed.

Usage:
    python3 scripts/validate_privacy.py --authors /tmp/authors.json
    python3 scripts/validate_privacy.py --raw tests/fixtures/apify_sample.json \\
        /tmp/fb-out data/distilled
    python3 scripts/validate_privacy.py            # hygiene only
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SCAN_DIRS = (ROOT / "data" / "fb_threads", ROOT / "data" / "distilled")


def _load_sibling(name: str):
    """Import a sibling script module regardless of cwd (same pattern as
    validate_distilled.py -> distill.py)."""
    path = Path(__file__).resolve().parent / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


privacy = _load_sibling("privacy_common")
PSEUDONYM_RE = privacy.PSEUDONYM_RE
FB_THREAD_KEYS = privacy.FB_THREAD_KEYS
FB_COMMENT_KEYS = privacy.FB_COMMENT_KEYS
FB_URL_RE = privacy.FB_URL_RE
collapse = privacy.collapse
harvest_author_names = privacy.harvest_author_names
name_leak_matches = privacy.name_leak_matches


def iter_text_fields(record: Any, path: str = "record") -> list[tuple[str, str]]:
    """Yield (field-path, string) for every string reachable in a record."""
    out: list[tuple[str, str]] = []

    def walk(node: Any, here: str) -> None:
        if isinstance(node, str):
            out.append((here, node))
        elif isinstance(node, list):
            for i, child in enumerate(node):
                walk(child, f"{here}[{i}]")
        elif isinstance(node, dict):
            for key, child in node.items():
                walk(child, f"{here}.{key}")

    walk(record, path)
    return out


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path.name}: corrupt JSON — {exc}") from exc


def classify_record(rec: Any) -> str:
    """"fb_thread" | "fb_distilled" | "distilled" by structure, not path."""
    if isinstance(rec, dict) and rec.get("source") == "facebook":
        comments = rec.get("comments")
        has_pseudonym = isinstance(comments, list) and any(
            isinstance(c, dict) and "pseudonym" in c for c in comments)
        looks_distilled = any(k in rec for k in ("symptom", "cause", "fix", "evidence_quote"))
        if has_pseudonym or not looks_distilled:
            return "fb_thread"
        return "fb_distilled"
    return "distilled"


def check_fb_thread_file(path: Path, authors: list[str]) -> list[str]:
    """Hygiene + name-leak checks for one anonymized FB thread record."""
    errs: list[str] = []
    rec = _load_json(path)
    if not isinstance(rec, dict):
        return [f"{path.name}: record is not a JSON object"]
    extra = set(rec) - FB_THREAD_KEYS
    if extra:
        errs.append(f"{path.name}: stored keys outside the anonymous whitelist: "
                    f"{sorted(extra)} (raw profile fields must never be stored)")
    if rec.get("source") != "facebook":
        errs.append(f"{path.name}: source != facebook")
    url = rec.get("url")
    if not isinstance(url, str) or not FB_URL_RE.match(url):
        errs.append(f"{path.name}: url is not an https facebook permalink")
    comments = rec.get("comments")
    if not isinstance(comments, list):
        errs.append(f"{path.name}: comments must be an array")
        return errs
    for i, comment in enumerate(comments):
        if not isinstance(comment, dict):
            errs.append(f"{path.name}: comment[{i}] is not an object")
            continue
        extra_c = set(comment) - FB_COMMENT_KEYS
        if extra_c:
            errs.append(f"{path.name}: comment[{i}] keys outside whitelist: {sorted(extra_c)}")
        pseudonym = comment.get("pseudonym", "")
        if not (isinstance(pseudonym, str) and PSEUDONYM_RE.match(pseudonym)):
            errs.append(f"{path.name}: comment[{i}] author {pseudonym!r} is not a "
                        "member-<8hex> pseudonym")
        for field in ("text", "posted_at"):
            if not isinstance(comment.get(field), str):
                errs.append(f"{path.name}: comment[{i}].{field} must be a string")
    # name-leak scan over every text field, whatever directory the file
    # lives in (fixtures included)
    for here, text in iter_text_fields(rec):
        hits = name_leak_matches(authors, text)
        if hits:
            errs.append(f"{path.name}:{here} contains author name(s): {', '.join(hits)}")
    return errs


def check_distilled_file(path: Path, authors: list[str]) -> list[str]:
    """FB distilled records must be source-flagged; all distilled text (FB or
    GitHub) must be free of the raw FB author names."""
    errs: list[str] = []
    rec = _load_json(path)
    if not isinstance(rec, dict):
        return [f"{path.name}: record is not a JSON object"]
    if rec.get("source") == "facebook":
        url = rec.get("url")
        if not isinstance(url, str) or not FB_URL_RE.match(url):
            errs.append(f"{path.name}: FB distilled url is not an https facebook permalink")
        for field in ("group", "title"):
            if not isinstance(rec.get(field), str):
                errs.append(f"{path.name}: FB distilled {field} missing")
        for field in ("symptom", "cause", "fix"):
            v = rec.get(field)
            if not (v is None or isinstance(v, str)):
                errs.append(f"{path.name}: FB distilled {field} must be null or a string")
    for here, text in iter_text_fields(rec):
        hits = name_leak_matches(authors, text)
        if hits:
            errs.append(f"{path.name}:{here} contains author name(s): {', '.join(hits)}")
    return errs


def main() -> int:
    ap = argparse.ArgumentParser(description="Name-leak + FB hygiene gate over stored/distilled records")
    ap.add_argument("--authors", default="", help="JSON array of raw author names/handles to scan for")
    ap.add_argument("--raw", default="", help="raw Apify JSON whose author names are auto-harvested")
    ap.add_argument("paths", nargs="*", help="files or dirs to scan (default: data/fb_threads + data/distilled)")
    args = ap.parse_args()

    if args.raw:
        payload = _load_json(Path(args.raw))
        authors = harvest_author_names(payload)
        print(f"authors from {args.raw}: {len(authors)}")
    elif args.authors:
        authors = _load_json(Path(args.authors))
        if not isinstance(authors, list) or not all(isinstance(a, str) for a in authors):
            print("ERROR: --authors must be a JSON array of strings", file=sys.stderr)
            return 1
    else:
        authors = []
        print("no author list given (--authors/--raw) — hygiene checks only")

    targets: list[Path] = []
    if args.paths:
        targets = [Path(p) for p in args.paths]
    else:
        for d in DEFAULT_SCAN_DIRS:
            if d.exists():
                targets.append(d)
    if not targets:
        print("nothing to scan (no target dirs/files exist)")
        return 0

    files: list[Path] = []
    for target in targets:
        if target.is_dir():
            files.extend(sorted(p for p in target.glob("*.json")
                                if p.name != "state.json" and "state.facebook" not in p.name))
        elif target.is_file():
            files.append(target)
        else:
            print(f"WARN: skip missing target {target}", file=sys.stderr)

    failed = 0
    fb_thread_files = 0
    for path in files:
        try:
            rec = _load_json(path)
            kind = classify_record(rec)
            if kind == "fb_thread":
                fb_thread_files += 1
                errs = check_fb_thread_file(path, authors)
            else:
                errs = check_distilled_file(path, authors)
        except ValueError as exc:
            errs = [str(exc)]
        if errs:
            failed += 1
            print(f"FAIL {path}:")
            for err in errs:
                print(f"     - {err}")
    if failed:
        print(f"privacy gate: {failed} file(s) failed — {len(files) - failed} clean")
        return 1
    print(f"privacy gate: {len(files)} file(s) checked ({fb_thread_files} FB threads, "
          f"{len(files) - fb_thread_files} distilled/other) — {len(authors)} author names — 0 leaks")
    return 0


if __name__ == "__main__":
    sys.exit(main())
