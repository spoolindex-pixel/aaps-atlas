#!/usr/bin/env python3
"""Build the AAPS Atlas client search index (pure stdlib, re-runnable).

data/docs/*.md + data/threads/*.json  ->  site/search-index.json
                                      +  site/search-data.js  (file:// variant)
                                      +  site/docs/<slug>.html (local doc pages)

Prints corpus stats (N docs, N threads, index size). Exits non-zero when a
record is missing its mandatory attribution URL or corpus is below minimums.
Run: python3 scripts/build_index.py
"""
import html
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "data" / "docs"
THREADS = ROOT / "data" / "threads"
SITE = ROOT / "site"
MIN_DOCS = 6
MIN_THREADS = 45

SRC_LINE = re.compile(r"^#\s*Source:\s*(?:<)?(https?://[^\s>]+)(?:>)?", re.IGNORECASE)


def parse_doc(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    source_url = ""
    if lines:
        src_match = SRC_LINE.match(lines[0])
        if src_match is not None:
            source_url = src_match.group(1)
            lines = lines[1:]
    body = "\n".join(lines).strip()
    title = ""
    for ln in lines:
        if ln.startswith("# ") and not ln.startswith("# Source"):
            title = ln.lstrip("# ").strip()
            break
    title = title or path.stem.replace("-", " ").title()
    return {"id": f"doc:{path.stem}", "type": "docs", "slug": path.stem,
            "title": title, "source_url": source_url, "text": f"{title}\n{body}"}


def parse_thread(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"corrupt thread json {path.name}: {exc}") from exc
    comments = data.get("comments") or []
    text = " ".join([data.get("title", ""), " ".join(data.get("labels") or []),
                     data.get("body", ""),
                     " ".join(c.get("body", "") for c in comments)])
    return {"id": f"thread:{path.stem}", "type": "thread",
            "title": data.get("title", ""), "html_url": data.get("html_url", ""),
            "repo": data.get("repo", ""), "number": data.get("number"),
            "labels": data.get("labels") or [], "state": data.get("state", ""),
            "created_at": data.get("created_at", ""), "closed_at": data.get("closed_at", ""),
            "comment_count": data.get("comment_count", len(comments)),
            "comments": [{"user": c.get("user", ""), "created_at": c.get("created_at", ""),
                          "body": c.get("body", "")} for c in comments],
            "text": text}


# ---------------------------------------------------------------- md -> html

def md_inline(s: str) -> str:
    s = html.escape(s, quote=False)
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    s = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"\*([^*]+)\*", r"<em>\1</em>", s)
    return s


def md_to_html(md: str) -> str:
    out: list[str] = []
    for raw in md.splitlines():
        line = raw.rstrip()
        if not line.strip():
            continue
        m = re.match(r"^(#{1,6})\s+(.*)$", line)
        if m:
            level = min(len(m.group(1)) + 1, 6)
            out.append(f"<h{level}>{md_inline(m.group(2))}</h{level}>")
        elif line.startswith("- "):
            out.append(f"<li>{md_inline(line[2:])}</li>")
        elif re.match(r"^\s*\d+\.\s+", line):
            item_text = re.sub(r"^\s*\d+\.\s+", "", line)
            out.append(f"<li>{md_inline(item_text)}</li>")
        elif line == "---":
            out.append("<hr>")
        elif line.startswith("# Source:"):
            out.append(f"<p class='source'>{md_inline(line)}</p>")
        else:
            out.append(f"<p>{md_inline(line)}</p>")
    body = []
    buf: list[str] = []
    for el in out:
        if el.startswith("<li>"):
            buf.append(el)
        elif buf:
            body.append("<ul>" + "".join(buf) + "</ul>")
            buf = []
            body.append(el)
        else:
            body.append(el)
    if buf:
        body.append("<ul>" + "".join(buf) + "</ul>")
    return "\n".join(body)


DOC_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} · AAPS Atlas</title>
<link rel="stylesheet" href="../style.css">
</head>
<body class="docpage">
<main>
  <p class="crumb"><a href="../index.html">← AAPS Atlas search</a></p>
  <article class="mirror">
    <h1>{title}</h1>
    <p class="source">Mirrored from <a href="{source}">{source}</a> — community documentation, not medical advice.</p>
    <hr>
{body}
  </article>
</main>
</body>
</html>
"""


def emit_doc_page(rec: dict) -> None:
    md = (DOCS / f"{rec['slug']}.md").read_text(encoding="utf-8")
    body = md_to_html(md)
    page = DOC_TEMPLATE.format(title=html.escape(rec["title"]),
                               source=rec["source_url"], body=body)
    dest = SITE / "docs" / f"{rec['slug']}.html"
    dest.write_text(page, encoding="utf-8")


def main() -> int:
    doc_recs = sorted((parse_doc(p) for p in DOCS.glob("*.md")), key=lambda d: d["slug"])
    thread_recs = sorted(
        (parse_thread(p) for p in THREADS.glob("*.json") if p.name != "manifest.json"),
        key=lambda t: t["id"])
    for rec in doc_recs:
        assert rec["source_url"], f"doc {rec['id']} missing source URL (first line)"
    for rec in thread_recs:
        assert rec["html_url"], f"thread {rec['id']} missing html_url"
    missing = [t["id"] for t in thread_recs if not t["text"].strip()]
    if missing:
        print(f"WARN empty thread records: {missing}")

    payload = {"meta": {"generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                        "counts": {"docs": len(doc_recs), "threads": len(thread_recs)}},
               "docs": doc_recs, "threads": thread_recs}
    SITE.mkdir(exist_ok=True)
    (SITE / "search-index.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    js = f"window.__AAPS_INDEX__ = {json.dumps(payload, ensure_ascii=False)};\n"
    (SITE / "search-data.js").write_text(js, encoding="utf-8")
    (SITE / "docs").mkdir(exist_ok=True)
    for rec in doc_recs:
        emit_doc_page(rec)

    size = (SITE / "search-index.json").stat().st_size
    ok = len(doc_recs) >= MIN_DOCS and len(thread_recs) >= MIN_THREADS
    print(f"docs={len(doc_recs)} threads={len(thread_recs)} "
          f"index={size / 1024:.0f}KiB -> site/search-index.json {'OK' if ok else 'TOO SMALL'}")
    if not ok:
        print(f"need >= {MIN_DOCS} docs and >= {MIN_THREADS} threads")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
