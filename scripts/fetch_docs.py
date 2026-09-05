#!/usr/bin/env python3
"""Mirror AAPS/xDrip doc pages into data/docs/*.md as clean markdown.

Plain stdlib (urllib + html.parser), no framework. First line of each .md is the
source URL. Skips nav/script/style chrome, keeps headings + body text.
Re-runnable: python3 scripts/fetch_docs.py
"""
import io
import re
import sys
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "docs"

# (filename, url).  Each file gets an id (stem) used by the site/index.
SOURCES = [
    ("omnipod-dash.md", "https://wiki.aaps.app/en/latest/CompatiblePumps/OmnipodDASH.html"),
    ("dexcom-g7.md", "https://wiki.aaps.app/en/latest/Hardware/DexcomG7.html"),
    ("xdrip-app.md", "https://wiki.aaps.app/en/latest/CompatibleCgms/xDrip.html"),
    ("browser-build.md", "https://wiki.aaps.app/en/latest/SettingUpAaps/BrowserBuild.html"),
    ("building-aaps.md", "https://wiki.aaps.app/en/latest/SettingUpAaps/BuildingAaps.html"),
    ("xdrip-g7.md", "https://navid200.github.io/xDrip/docs/Dexcom/G7.html"),
]

HEADING_LEVELS = {"h1": 1, "h2": 2, "h3": 3, "h4": 4, "h5": 5, "h6": 6}

SKIP_TAGS = {"script", "style", "noscript", "nav", "footer", "aside", "head", "form"}


def slice_article(raw: str) -> str:
    """Cut the raw HTML down to the article body region for the two hosts."""
    if "wiki.aaps.app" in raw[:2000] or raw.find("itemprop=\"articleBody\"") != -1:
        start = raw.find('<div itemprop="articleBody">')
        end = raw.find("<footer", start)
        if start == -1:  # fall back to role="main"
            start = raw.find('role="main"')
            end = raw.find("</section>", start)
        if end == -1:
            end = raw.find("</body>", start)
        return raw[start:end] if start != -1 else raw
    # navid200.github.io Jekyll pages: article = region from the <h1> to end.
    start = raw.rfind("<h1")
    end = raw.find("<script", start)
    if end == -1:
        end = raw.find("</body>", start)
    return raw[start:end] if start != -1 else raw


class Textify(HTMLParser):
    """Dumb-but-safe HTML -> loose markdown converter (block structure only)."""

    BLOCK = {"p", "div", "section", "article", "hr", "ul", "ol", "table",
             "tr", "blockquote", "pre", "br", "li", "h1", "h2", "h3", "h4", "h5", "h6"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out = io.StringIO()
        self.skip_depth = 0
        self.at_line_start = True

    def handle_starttag(self, tag, attrs):
        if tag in SKIP_TAGS:
            self.skip_depth += 1
            return
        if self.skip_depth:
            return
        if tag in HEADING_LEVELS:
            self._nl()
            self.out.write("#" * HEADING_LEVELS[tag] + " ")
        elif tag == "li":
            self._nl()
            self.out.write("- ")
        elif tag == "br":
            self._nl()
        elif tag == "hr":
            self._nl()
            self.out.write("---")
            self._nl()
        elif tag in self.BLOCK:
            self._nl()

    def handle_endtag(self, tag):
        if tag in SKIP_TAGS:
            self.skip_depth = max(0, self.skip_depth - 1)
        elif not self.skip_depth and tag in self.BLOCK:
            self._nl()

    def handle_data(self, data):
        if self.skip_depth:
            return
        text = re.sub(r"\s+", " ", data)
        if text.strip():
            self.out.write(" " if not self.at_line_start and not text.startswith(" ") else "")
            self.out.write(text)
            self.at_line_start = False

    def _nl(self):
        if not self.at_line_start:
            self.out.write("\n")
            self.at_line_start = True


def fetch(url: str) -> str:
    if urllib.parse.urlparse(url).scheme not in ("http", "https"):
        raise ValueError(f"refusing non-http(s) URL: {url!r}")
    # pi-lens-ignore: S310 - audited: scheme allowlisted above, URLs are module constants
    req = urllib.request.Request(url, headers={"User-Agent": "aaps-atlas-mirror/0.1 (+https://github.com/spoolindex-pixel/aaps-atlas)"})
    with urllib.request.urlopen(req, timeout=60) as r:  # noqa: S310
        return r.read().decode("utf-8", errors="replace")


def clean(region: str) -> str:
    # drop the in-article "Edit on GitHub" / breadcrumb chrome if it leaked in
    region = re.sub(r'<a class="headerlink"[^>]*>.*?</a>', "", region)
    t = Textify()
    t.feed(region)
    text = t.out.getvalue()
    lines = [ln.rstrip() for ln in text.splitlines()]
    lines = [re.sub(r"^(\s*[-#]+)\s*$", "", ln) for ln in lines]  # drop empty heading/list markers
    text = "\n".join(lines)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, url in SOURCES:
        try:
            raw = fetch(url)
        except Exception as exc:  # noqa: BLE001
            print(f"FAIL {name}: {exc}")
            continue
        body = clean(slice_article(raw))
        (OUT / name).write_text(f"# Source: {url}\n\n{body}\n", encoding="utf-8")
        print(f"ok   {name:18s} {len(body):6d} chars <- {url}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
