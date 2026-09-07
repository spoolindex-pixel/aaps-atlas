#!/usr/bin/env python3
"""validate_distilled.py — CI gate over the distilled corpus.

Re-validates every data/distilled/*.json record against the same schema and
anti-hallucination checks the distiller enforces (scripts/distill.py), by
re-reading the source thread from data/corpus/ (github records) or
data/fb_threads/ (source: facebook records distilled by
`distill.py --source-type facebook`).

Fails (exit 1) when ANY record:
  * violates its record schema (github or facebook flavor), or
  * lacks its `url` field / the url is not the real source link (github
    issue or facebook post permalink), or
  * fails the evidence/devices containment checks against its source thread
    (meaning it could not have been produced from the thread text alone).

The separate name-leak gate (real author names never stored) lives in
scripts/validate_privacy.py — it needs the raw authors list and is run at
ingest time against the raw scrape + this validator covers structure only.

Run: python3 scripts/validate_distilled.py
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CORPUS = ROOT / "data" / "corpus"
DISTILLED = ROOT / "data" / "distilled"
FB_THREADS = ROOT / "data" / "fb_threads"


def _load_distill_module():
    """Import scripts/distill.py regardless of cwd (stdlib-only sibling load)."""
    import importlib.util
    path = Path(__file__).resolve().parent / "distill.py"
    spec = importlib.util.spec_from_file_location("distill", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


distill = _load_distill_module()
REPOS = distill.REPOS
searchable_text = distill.searchable_text
t_stem = distill.t_stem
validate_record = distill.validate_record
validate_record_fb = distill.validate_record_fb
FB_URL_RE = re.compile(r"^https://(?:www\.|m\.|web\.|mobile\.|business\.)?facebook\.com/")


def _fb_full_text(rec: dict) -> str:
    """Full anonymized post text used for FB containment checks."""
    parts = [rec.get("text", "")]
    parts += [c.get("text", "") for c in (rec.get("comments") or [])]
    return "\n".join(parts)


def main() -> int:
    if not DISTILLED.exists():
        print("FAIL: data/distilled/ missing — run scripts/distill.py first")
        return 1
    corpus = {}
    for path in CORPUS.glob("*-*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            corpus[t_stem(data)] = data
        except (json.JSONDecodeError, KeyError):
            continue
    fb_sources = {}
    if FB_THREADS.exists():
        for path in FB_THREADS.glob("*.json"):
            try:
                fb_sources[path.stem] = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, KeyError):
                continue
    records = sorted(p for p in DISTILLED.glob("*.json") if p.name != "state.json")
    failed = 0
    checked = 0
    for path in records:
        try:
            rec = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            print(f"FAIL {path.name}: corrupt JSON — {exc}")
            failed += 1
            continue
        stem = path.stem
        checked += 1
        if rec.get("source") == "facebook":
            src = fb_sources.get(stem)
            if src is None:
                print(f"FAIL {path.name}: no matching anonymized fb post in data/fb_threads/")
                failed += 1
                continue
            errs = validate_record_fb(rec, _fb_full_text(src))
            if not isinstance(rec.get("url"), str) or not FB_URL_RE.match(rec.get("url", "")):
                errs.append("url must be an https://facebook.com post permalink")
            for key in ("group", "group_url"):
                if not isinstance(rec.get(key), str):
                    errs.append(f"missing {key}")
        else:
            src = corpus.get(stem)
            if src is None:
                print(f"FAIL {path.name}: no matching corpus thread in data/corpus/")
                failed += 1
                continue
            # every record must carry its GitHub url (attribution + linkback)
            errs = validate_record(rec, searchable_text(src))
            if not rec.get("url"):
                errs.append("missing url field")
            if rec.get("issue_id") != src.get("number"):
                errs.append(f"issue_id {rec.get('issue_id')} != corpus number {src.get('number')}")
            if rec.get("repo") not in REPOS:
                errs.append(f"repo {rec.get('repo')!r} not in {REPOS}")
        if errs:
            failed += 1
            print(f"FAIL {path.name}: " + "; ".join(errs))
    print(f"validated {checked} distilled record(s) — {failed} failed")
    if failed:
        print(f"{failed} distilled record(s) invalid — see above")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
