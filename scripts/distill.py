#!/usr/bin/env python3
"""distill.py — batch LLM distillation of corpus threads into S-C-F records.

Reads every thread in data/corpus/*.json, calls the LLM (ONE thread per
prompt) with a strict extract-only system prompt, JSON-validates the result
and writes data/distilled/<repo>-<number>.json.

Anti-hallucination contract (the #1 requirement):
  * every field must be extractable from the thread text — null / [] when
    the thread does not state it; never invented versions or settings;
  * evidence_quote must be a VERBATIM substring of the thread text (the
    validator normalises whitespace/case only);
  * devices / android_versions / settings_changed entries must each literally
    occur in the thread text (normalised containment check);
  * on validation failure the record is retried once with the exact error,
    then parked in data/distilled/rejects/ with the reason.

Record schema (validated per record):
    {issue_id, repo, url, title, symptom, cause, fix,
     settings_changed[], devices[], android_versions[], driver_tags[],
     confidence, evidence_quote}

Cost guard: default batch cap is 200 threads per run (see --limit). The run
prints prompt/completion token totals and an estimated $ at the model's list
price. Runs are back-to-back batch tasks: state.json records which issue
numbers are already distilled (or parked), so each run picks the next ~200 by
comment count desc.

LLM config (env, all optional):
    AAPS_LLM_API_KEY   key for the OpenAI-compatible endpoint below
    AAPS_LLM_KEY_FILE  optional JSON key file fallback: {"deepseek": {"key": ...}}
    AAPS_LLM_BASE_URL  default: https://api.deepseek.com
    AAPS_LLM_MODEL     default: deepseek-chat

Model gotcha: the deepseek-v4-flash reasoning variant is a heavy
reasoning model — on a meaningful fraction of threads it burns its whole
completion budget on reasoning_content (finish_reason=length) and returns
EMPTY content, which fails parse and gets parked as a reject. deepseek-chat
is the plain chat model on the same key: it emits the strict JSON reliably
(observed 100% pass over many threads) at ~1/20th the tokens. Always use
deepseek-chat here.

Usage:
    python3 scripts/distill.py [--limit 200] [--dry-run]
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
CORPUS = ROOT / "data" / "corpus"
DISTILLED = ROOT / "data" / "distilled"
REJECTS = DISTILLED / "rejects"
STATE_FILE = DISTILLED / "state.json"
STATE_FILE_FB = DISTILLED / "state.facebook.json"
DEFAULT_LIMIT = 200
PROMPT_TEXT_BUDGET = 14000   # chars of thread text sent per prompt
BODY_HEAD = 6000             # chars of the issue body always kept
MAX_TOKENS = 8000   # generous cap — deepseek-chat answers run ~300-800 tokens
HTTP_TIMEOUT = 120

# Token price (per 1M) for the default model — used only for the printed
# cost estimate. Override via AAPS_LLM_INPUT_PRICE / AAPS_LLM_OUTPUT_PRICE.
MODEL_PRICES = {"input": 0.14, "output": 0.28}  # USD / 1M tokens

# Explicit solved-thread anchors for demo queries: distilled records whose
# searchable text carries G7 + broadcast-family terms must exist so the
# canonical "G7 broadcast" demo query returns distilled hits. Titles carry
# both terms (androidaps-3266: "...companion app mode and dexcom g7
# original"). Kept tiny and counted against the batch cap.
ANCHOR_STEMS: list[str] = ["androidaps-3266", "xdrip-3250", "xdrip-3787"]

REPOS = ("nightscout/AndroidAPS", "NightscoutFoundation/xDrip")

SYSTEM_PROMPT = """You extract troubleshooting knowledge records from ONE GitHub issue thread. Extract ONLY from the provided text. Never use outside knowledge, never guess, never invent versions, device names, settings or fixes. When the thread does not state something, that field must be null (for strings) or an empty array [].

Return STRICT JSON only (no markdown fences, no prose) matching exactly this schema:
{
  "issue_id": <int, the issue number given below>,
  "repo": <string, the repo path given below>,
  "url": <string, the html_url given below>,
  "title": <string, the issue title, verbatim>,
  "symptom": <string or null — 1-3 sentence statement of the reported problem as the thread describes it; null only if no body and no comments>,
  "cause": <string or null — the root cause the THREAD identifies; null when the thread never establishes one>,
  "fix": <string or null — the resolution/workaround the THREAD states (action + exact config/setting/value if given); null when the thread states no resolution>,
  "settings_changed": [<string> — entries like "Setting name → new value" ONLY when a participant states a specific setting they changed and to what; empty [] otherwise],
  "devices": [<string> — the CGM/sensor/pump/phone device(s) the issue is ABOUT, exactly as the thread names them (e.g. "Dexcom G7", "Omnipod DASH", "Omnipod 5", "xDrip", "Libre 2"); empty [] when none>,
  "android_versions": [<string> — Android OS versions participants state they run, e.g. "Android 16", "Android 14"; empty [] when none; never infer from wording],
  "driver_tags": [<string> — delivery-path / integration terms the thread literally discusses, e.g. "native G7", "BYODA", "companion app", "broadcast", "xDrip collector", "Medtronic"; lowercase; empty [] when none>,
  "confidence": <"high" | "medium" | "low" — high: the thread clearly states cause AND fix and the quote below backs them; medium: cause or fix is stated but partial/secondhand; low: the thread does not resolve (cause/fix null) or resolution is speculative>,
  "evidence_quote": <string — a SHORT (<=400 chars) VERBATIM quote from the thread text that backs the most important extracted claim (the fix if present, else the cause). Copy exactly: same words, same order, ONE CONTIGUOUS span. NEVER use "..." or "…" and never skip/compress words inside the quote — if the source span is long, quote the shortest contiguous substring that still contains the claim. Only surrounding whitespace/newlines may collapse; the URL half of a markdown link like [text](url) may be dropped, but its visible [text] stays.>
}

Field-writing rules:
- symptom/cause/fix must be plain summaries of what the thread says — never paraphrase into claims the thread does not make.
- settings_changed entries: name exactly the setting as the thread does, with the value the thread states ("ON" / "off" / version / value). If a value is not given, put the setting alone.
- devices and android_versions entries must be strings that literally appear in the thread (use the thread's own casing/spacing, e.g. "Omnipod 5" if written that way).
- devices must list ONLY the device(s) the issue is about — do NOT add devices that merely appear in a comparison or in passing (e.g. a Libre 2 thread that briefly mentions Dexcom G7 should list Libre 2, not Dexcom G7).
- If the thread is a support question with an authoritative maintainer answer, prefer that answer for cause/fix over user speculation.
- If there is no resolution anywhere in the thread, fix = null, cause = null (or only what is established), confidence = "low".
- A thread that never mentions any device still gets [] arrays — do NOT add "AAPS" or "xDrip" merely because the repo is AAPS/xDrip.
- NEVER copy any participant's real name, username or @handle into title, symptom, cause, fix, settings_changed, devices, android_versions or driver_tags. For evidence_quote, keep the quote verbatim but prefer a contiguous span that does not name a person."""

USER_TEMPLATE = """Issue number: {number}
Repo: {repo}
URL: {url}
Title: {title}

======= THREAD TEXT =======
{thread_text}
======= END THREAD TEXT =======

Now return the strict JSON record for this thread (schema above)."""

# ----------------------------------------------------------------- facebook
# The same S->C->F distiller runs over anonymized Facebook group threads
# (data/fb_threads/*.json, produced by scripts/fb_anonymize.py). The
# extraction contract is identical (anti-hallucination containment vs the
# post text) but: posts have no title (the model synthesises a short one),
# authors are already pseudonymised member-<8hex> handles, and the privacy
# rule is absolute — real person names/handles must never reach an output
# field, INCLUDING evidence quotes.

SYSTEM_PROMPT_FB = """You extract troubleshooting knowledge records from ONE Facebook group post + its comments. The post is from a closed diabetes-technology support group (xDrip / AndroidAPS users) and has been anonymized: every participant is only a pseudonym like "member-a1b2c3d4". Extract ONLY from the provided text. Never use outside knowledge, never guess, never invent versions, device names, settings or fixes. When the post does not state something, that field must be null (for strings) or an empty array [].

HARD PRIVACY RULE: never copy any real person's name, username, handle or nickname into ANY output field — not into title, symptom, cause, fix, settings_changed, devices, android_versions, driver_tags and NOT even into evidence_quote. Never reproduce "member-..." pseudonyms either. Refer to people only generically ("the poster", "a commenter", "someone"). If the only quotable span contains a name or pseudonym, choose a shorter contiguous span around the technical claim that omits it, or paraphrase in the field and leave the quote to the closest clean span.

Return STRICT JSON only (no markdown fences, no prose) matching exactly this schema:
{
  "title": <string — synthesize a SHORT searchable topic title for the post (<= 90 chars, e.g. "G6 keeps asking for calibration"), from the technical content only, no names>,
  "symptom": <string or null — 1-3 sentence statement of the reported problem as the post describes it; null only if no text and no comments>,
  "cause": <string or null — the root cause the POST identifies; null when the post never establishes one>,
  "fix": <string or null — the resolution/workaround the POST states (action + exact config/setting/value if given); null when the post states no resolution>,
  "settings_changed": [<string> — entries like "Setting name → new value" ONLY when a participant states a specific setting they changed and to what; empty [] otherwise>],
  "devices": [<string> — the CGM/sensor/pump/phone device(s) the issue is ABOUT, exactly as the post names them (e.g. "Dexcom G6", "Omnipod DASH", "xDrip+"); empty [] when none>],
  "android_versions": [<string> — Android OS versions participants state they run, e.g. "Android 16", "Android 14"; empty [] when none; never infer from wording>],
  "driver_tags": [<string> — delivery-path / integration terms the post literally discusses, e.g. "companion app", "broadcast", "native G6", "patched collector"; lowercase; empty [] when none>],
  "confidence": <"high" | "medium" | "low" — high: the post clearly states cause AND fix and the quote below backs them; medium: cause or fix is stated but partial/secondhand; low: the post does not resolve>,
  "evidence_quote": <string — a SHORT (<=400 chars) VERBATIM quote from the post text that backs the most important extracted claim (the fix if present, else the cause). Copy exactly: same words, same order, ONE CONTIGUOUS span, and NO person names or member-... pseudonyms inside. Never use "..." or "…" and never skip/compress words inside the quote — choose the shortest contiguous clean span that still contains the claim.>
}

Field-writing rules:
- symptom/cause/fix must be plain summaries of what the post says — never paraphrase into claims the post does not make.
- settings_changed entries: name exactly the setting as the post does, with the value the post states ("ON" / "off" / version / value). If a value is not given, put the setting alone.
- devices and android_versions entries must be strings that literally appear in the post text (use the post's own casing/spacing).
- devices must list ONLY the device(s) the issue is about — not devices that merely appear in passing.
- If there is no resolution anywhere in the post, fix = null, cause = null (or only what is established), confidence = "low"."""

USER_TEMPLATE_FB = """Facebook group post
Group: {group}
Group URL: {group_url}
Post URL: {url}
Posted at: {posted_at}

======= POST TEXT =======
{thread_text}
======= END POST TEXT =======

Now return the strict JSON record for this post (schema above)."""

FB_LLM_KEYS = ("title", "symptom", "cause", "fix", "settings_changed",
               "devices", "android_versions", "driver_tags", "confidence",
               "evidence_quote")


def validate_record_fb(rec: Any, post_text: str) -> list[str]:
    """Structural + anti-hallucination checks for a distilled FB record.
    Same containment core as validate_record; url/group metadata is attached
    programmatically (never model-written), so it is not part of the schema
    the model must satisfy."""
    errs: list[str] = []
    if not isinstance(rec, dict):
        return ["record is not a JSON object"]
    for key in FB_LLM_KEYS:
        if key not in rec:
            errs.append(f"missing required field {key!r}")
    if errs:
        return errs
    if not (isinstance(rec["title"], str) and 1 <= len(rec["title"].strip()) <= 300):
        errs.append("title must be a non-empty string (<=300 chars)")
    for field in ("symptom", "cause", "fix"):
        v = rec[field]
        if not (v is None or (isinstance(v, str) and len(v.strip()) >= 3)):
            errs.append(f"{field} must be null or a non-trivial string")
    for field in ("settings_changed", "devices", "android_versions", "driver_tags"):
        v = rec[field]
        if not isinstance(v, list) or any(not isinstance(x, str) for x in v):
            errs.append(f"{field} must be an array of strings")
    if rec["confidence"] not in ("high", "medium", "low"):
        errs.append("confidence must be high|medium|low")
    if not (isinstance(rec["evidence_quote"], str) and len(rec["evidence_quote"].strip()) >= 5):
        errs.append("evidence_quote must be a non-empty string")
    if errs:
        return errs
    hay = norm(post_text)
    hay_compact = re.sub(r"\s+", "", hay)
    quote = norm(rec["evidence_quote"])
    if not quote or (quote not in hay and norm_quote(rec["evidence_quote"]) not in norm_quote(post_text)):
        errs.append("evidence_quote is not a verbatim substring of the post text")
    for field, entries in (("devices", rec["devices"]),
                           ("android_versions", rec["android_versions"])):
        for entry in entries:
            if entry and not in_thread(entry, hay, hay_compact):
                errs.append(f"{field} entry {entry!r} does not literally occur in the post text")
    for entry in rec["settings_changed"]:
        name = entry.split("→", 1)[0].split("->", 1)[0].strip()
        if name and not in_thread(name, hay, hay_compact):
            errs.append(f"settings_changed entry {entry!r}: setting name not in post text")
    return errs


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def norm(s: str) -> str:
    """Whitespace-collapsed, lowercased form used for verbatim checks."""
    return re.sub(r"\s+", " ", (s or "")).strip().lower()


MD_LINK_RE = re.compile(r"\]\([^)\n]+?\)")  # markdown link "(url)" sugar


def norm_quote(s: str) -> str:
    """norm() plus symmetric removal of markdown-link URL sugar.

    Formatting-only tolerance: GitHub thread prose is full of
    [text](https://…) links, and models routinely drop the URL half when
    quoting. The quote must still be word-for-word verbatim — only the
    (url) destination, which carries no claim content, may differ between
    the quote and its source. Applied to BOTH sides of the containment
    check, so it can never admit invented words (inserted "...", skipped
    spans, renamed devices all still fail).
    """
    return MD_LINK_RE.sub("]", norm(s))


def in_thread(entry: str, hay: str, hay_compact: str) -> bool:
    """Token-level literal check: every significant token of `entry` must
    occur in the thread text. Tolerates wording variants ("Samsung S23" vs
    "galaxy S23") while still rejecting invented tokens (a made-up model
    name or version number will not be present anywhere in the thread)."""
    tokens = re.findall(r"[a-z0-9]{2,}", norm(entry))
    if not tokens:
        return False
    return all((t in hay) or (t in hay_compact) for t in tokens)


def to_int(v: object, default: int = 0) -> int:
    """int() with a safe fallback for JSON values that may be null/missing."""
    try:
        return int(v)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------- schema

SCHEMA: dict[str, Any] = {
    "issue_id": {"type": "integer", "minimum": 1},
    "repo": {"type": "string", "enum": list(REPOS)},
    "url": {"type": "string", "pattern": r"^https://github\.com/.+/issues/\d+$"},
    "title": {"type": "string", "minLength": 1, "maxLength": 300},
    "symptom": {"type": ["string", "null"], "minLength": 3, "maxLength": 1500},
    "cause": {"type": ["string", "null"], "minLength": 3, "maxLength": 2000},
    "fix": {"type": ["string", "null"], "minLength": 3, "maxLength": 2000},
    "settings_changed": {"type": "array", "items": {"type": "string", "maxLength": 200}},
    "devices": {"type": "array", "items": {"type": "string", "maxLength": 120}},
    "android_versions": {"type": "array", "items": {"type": "string", "maxLength": 60}},
    "driver_tags": {"type": "array", "items": {"type": "string", "maxLength": 120}},
    "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
    "evidence_quote": {"type": "string", "minLength": 5, "maxLength": 500},
}
REQUIRED = ["issue_id", "repo", "url", "title", "symptom", "cause", "fix",
            "settings_changed", "devices", "android_versions", "driver_tags",
            "confidence", "evidence_quote"]


def validate_record(rec: Any, thread_text: str) -> list[str]:
    """Structural + anti-hallucination checks. Returns list of errors ([] = ok)."""
    errs: list[str] = []
    if not isinstance(rec, dict):
        return ["record is not a JSON object"]
    for key in REQUIRED:
        if key not in rec:
            errs.append(f"missing required field {key!r}")
    if errs:
        return errs
    # types / enums / patterns (mirrors the SCHEMA above)
    if not isinstance(rec["issue_id"], int) or isinstance(rec["issue_id"], bool) or rec["issue_id"] < 1:
        errs.append("issue_id must be a positive integer")
    if rec["repo"] not in REPOS:
        errs.append(f"repo not in {REPOS}")
    if not re.match(r"^https://github\.com/.+/issues/\d+$", rec["url"]):
        errs.append("url must be an https://github.com/.../issues/N link")
    if not (isinstance(rec["title"], str) and rec["title"].strip()):
        errs.append("title must be a non-empty string")
    for field in ("symptom", "cause", "fix"):
        v = rec[field]
        if not (v is None or (isinstance(v, str) and len(v.strip()) >= 3)):
            errs.append(f"{field} must be null or a non-trivial string")
    for field in ("settings_changed", "devices", "android_versions", "driver_tags"):
        v = rec[field]
        if not isinstance(v, list) or any(not isinstance(x, str) for x in v):
            errs.append(f"{field} must be an array of strings")
    if rec["confidence"] not in ("high", "medium", "low"):
        errs.append("confidence must be high|medium|low")
    if not (isinstance(rec["evidence_quote"], str) and len(rec["evidence_quote"].strip()) >= 5):
        errs.append("evidence_quote must be a non-empty string")
    if errs:
        return errs
    # ---- anti-hallucination: every value must literally appear in thread text
    hay = norm(thread_text)
    hay_compact = re.sub(r"\s+", "", hay)
    quote = norm(rec["evidence_quote"])
    # markdown-link URL destinations may differ between quote and source
    # (both sides stripped — see norm_quote); everything else stays verbatim
    if not quote or (quote not in hay and norm_quote(rec["evidence_quote"]) not in norm_quote(thread_text)):
        errs.append("evidence_quote is not a verbatim substring of the thread text")
    for field, entries in (("devices", rec["devices"]),
                           ("android_versions", rec["android_versions"])):
        for entry in entries:
            if entry and not in_thread(entry, hay, hay_compact):
                errs.append(f"{field} entry {entry!r} does not literally occur in the thread text")
    for entry in rec["settings_changed"]:
        name = entry.split("→", 1)[0].split("->", 1)[0].strip()
        if name and not in_thread(name, hay, hay_compact):
            errs.append(f"settings_changed entry {entry!r}: setting name not in thread text")
    return errs


# ---------------------------------------------------------------- corpus IO

def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return {"distilled": [], "parked": [], "runs": 0}


def save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=1), encoding="utf-8")


def load_corpus_threads() -> list[dict]:
    threads = []
    for path in sorted(CORPUS.glob("*-*.json")):
        if path.name == "state.json" or path.name == "manifest.json":
            continue
        try:
            threads.append(json.loads(path.read_text(encoding="utf-8")))
        except json.JSONDecodeError as exc:
            print(f"WARN corrupt corpus record {path.name}: {exc}", file=sys.stderr)
    return threads


def thread_text(thread: dict, budget: int = PROMPT_TEXT_BUDGET) -> str:
    """Assemble bounded thread text: body + head/tail comment arc, middle-out."""
    body = (thread.get("body") or "")[:BODY_HEAD]
    blocks: list[str] = []
    if body.strip():
        blocks.append(f"[issue body]\n{body}")
    comments = thread.get("comments") or []
    for c in comments:
        author = c.get("user", "?")
        date = (c.get("created_at") or "")[:10]
        blocks.append(f"[comment by {author} {date}]\n{(c.get('body') or '')}")
    total = sum(len(b) for b in blocks)
    while total > budget and len(blocks) > 1:
        # drop the block nearest the middle to preserve both arc ends
        mid = len(blocks) // 2
        total -= len(blocks.pop(mid))
    if total > budget and blocks:
        # pathological single long block: trim from the tail
        blocks[0] = blocks[0][:budget]
    return "\n\n".join(blocks)


def searchable_text(thread: dict) -> str:
    """Full thread text used by the evidence/device containment checks."""
    parts = [thread.get("title", ""), thread.get("body", "")]
    parts += [c.get("body", "") for c in (thread.get("comments") or [])]
    return "\n".join(parts)


# ---------------------------------------------------------------- LLM call

def llm_config() -> dict:
    base = os.environ.get("AAPS_LLM_BASE_URL", "https://api.deepseek.com").rstrip("/")
    model = os.environ.get("AAPS_LLM_MODEL", "deepseek-chat")
    key = os.environ.get("AAPS_LLM_API_KEY", "")
    if not key:
        key_file = os.environ.get(
            "AAPS_LLM_KEY_FILE",
            str(Path.home() / ".config" / "aaps-atlas" / "llm-key.json"),
        )
        auth = Path(key_file).expanduser()
        if auth.exists():
            try:
                data = json.loads(auth.read_text(encoding="utf-8"))
                key = (data.get("deepseek") or {}).get("key", "")
            except json.JSONDecodeError:
                key = ""
    if not key:
        raise SystemExit(
            "ERROR: no LLM API key — set AAPS_LLM_API_KEY (or AAPS_LLM_KEY_FILE "
            'pointing at a JSON file shaped {"deepseek": {"key": ...}}).'
        )
    return {"base": base, "model": model, "key": key}


def llm_chat(cfg: dict, system: str, user: str) -> tuple[str, dict]:
    """One chat completion. Returns (content, usage). Raises on HTTP errors."""
    url = f"{cfg['base']}/chat/completions"
    if not url.startswith("https://"):
        raise ValueError(f"refusing non-https LLM url: {url}")
    payload = {
        "model": cfg["model"],
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": user}],
        "temperature": 0.1,
        "max_tokens": MAX_TOKENS,
        "response_format": {"type": "json_object"},
        "stream": False,
    }
    req = urllib.request.Request(  # noqa: S310 (https checked above)
        url, data=json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {cfg['key']}",
                 "Content-Type": "application/json",
                 "User-Agent": "aaps-atlas-distill/2.0"})
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:  # noqa: S310 (https checked above)
        raw = resp.read()
    try:
        data = json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"non-JSON LLM response: {exc}") from exc
    return data["choices"][0]["message"]["content"], data.get("usage", {})


def parse_json_object(content: str) -> Any:
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("no JSON object in model response")
    try:
        return json.loads(text[start:end + 1])
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON in model response: {exc}") from exc


# ---------------------------------------------------------------- distiller

def distill_one(cfg: dict, system_prompt: str, base_user: str,
                validator, retry_feedback: str = "") \
        -> tuple[dict | None, str | None, dict]:
    """One completion loop. `validator(rec)` returns a list of errors ([] = ok).
    Returns (record, error, usage). record None + error str on failure."""
    last_error = ""
    attempts = 0
    while attempts < 2:
        attempts += 1
        try:
            user = base_user
            if retry_feedback:
                user = base_user + f"\n\nYour previous answer failed validation:\n{retry_feedback}"
            content, usage = llm_chat(cfg, system_prompt, user)
            rec = parse_json_object(content)
            errs = validator(rec)
            if not errs:
                return rec, None, usage
            last_error = "validation: " + "; ".join(errs)
            retry_feedback = last_error
        except json.JSONDecodeError as exc:
            last_error = f"parse: {exc}"
        except ValueError as exc:
            last_error = f"parse: {exc}"
        except urllib.error.HTTPError as exc:
            msg = exc.read(200).decode("utf-8", "replace")
            last_error = f"llm http {exc.code}: {msg}"
            if exc.code in (429, 500, 502, 503, 504):
                time.sleep(5 * attempts)
                continue
            if exc.code in (400, 401, 402, 403, 404):
                break  # not transient — do not retry
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_error = f"llm network: {exc}"
            time.sleep(5 * attempts)
    return None, last_error, {}


def pick_batch(threads: list[dict], state: dict, limit: int) -> list[dict]:
    """Next undistilled batch: comment count desc + demo anchors first."""
    done = set(state["distilled"]) | set(state["parked"])
    anchors = [t for t in threads if t_stem(t) in ANCHOR_STEMS and t_stem(t) not in done]
    anchors.sort(key=lambda t: t["comment_count"], reverse=True)
    rest = [t for t in threads if t_stem(t) not in done and t_stem(t) not in {t_stem(a) for a in anchors}]
    rest.sort(key=lambda t: (t["comment_count"], t["number"]), reverse=True)
    batch = anchors + rest
    return batch[:limit]


def t_stem(thread: dict) -> str:
    return f"{thread['repo'].split('/')[1].lower()}-{thread['number']}"


def _run_pool(work, batch: list[dict], workers: int, token_counts: dict) -> None:
    with cf.ThreadPoolExecutor(max_workers=workers) as ex:
        futures = []
        for item in batch:
            futures.append(ex.submit(work, item))
        for fut in cf.as_completed(futures):
            try:
                fut.result()
            except Exception as exc:  # noqa: BLE001 — worker should not die silently
                print(f"WORKER ERROR: {exc}", file=sys.stderr)


def main_github(args) -> int:
    """Original GitHub-corpus distillation (data/corpus -> data/distilled)."""
    threads = load_corpus_threads()
    state = load_state()
    batch = pick_batch(threads, state, args.limit)
    print(f"corpus threads: {len(threads)} | already distilled: {len(state['distilled'])} "
          f"| parked: {len(state['parked'])} | this batch: {len(batch)}")
    if args.dry_run or not batch:
        for t in batch[:10]:
            print(f"  would distill {t_stem(t)} #{t['number']} "
                  f"cc={t['comment_count']} {t['title'][:70]}")
        if batch:
            print(f"  ... ({len(batch)} total; remaining undistilled: "
                  f"{len(threads) - len(state['distilled']) - len(state['parked'])} before this batch)")
        return 0
    if len(batch) > args.limit:
        print(f"note: batch capped at {args.limit}")

    cfg = llm_config()
    print(f"llm: {cfg['model']} @ {cfg['base']} | workers={args.workers}")
    DISTILLED.mkdir(parents=True, exist_ok=True)
    REJECTS.mkdir(parents=True, exist_ok=True)
    state["runs"] = to_int(state.get("runs")) + 1
    lock = threading.Lock()
    token_counts = {"prompt": 0, "completion": 0}
    started = time.time()

    def work(thread: dict):
        thread_txt = thread_text(thread)
        full_txt = searchable_text(thread)
        user = USER_TEMPLATE.format(number=thread["number"], repo=thread["repo"],
                                    url=thread["html_url"], title=thread["title"],
                                    thread_text=thread_txt)

        def validator(rec):
            return validate_record(rec, full_txt)

        rec, err, usage = distill_one(cfg, SYSTEM_PROMPT, user, validator)
        stem = t_stem(thread)
        with lock:
            token_counts["prompt"] += to_int(usage.get("prompt_tokens"))
            token_counts["completion"] += to_int(usage.get("completion_tokens"))
            if rec is not None:
                rec.setdefault("issue_id", thread["number"])
                (DISTILLED / f"{stem}.json").write_text(
                    json.dumps(rec, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
                state["distilled"].append(stem)
                save_state(state)
                print(f"ok   {stem} #{thread['number']} cc={thread['comment_count']:<4d} "
                      f"{thread['title'][:60]}", flush=True)
            else:
                parked = {"thread": stem, "number": thread["number"], "repo": thread["repo"],
                          "url": thread["html_url"], "title": thread["title"],
                          "error": err, "parked_at": iso_now()}
                (REJECTS / f"{stem}.json").write_text(
                    json.dumps(parked, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
                state["parked"].append(stem)
                save_state(state)
                print(f"REJECT {stem} #{thread['number']} — {err}", flush=True)

    _run_pool(work, batch, args.workers, token_counts)

    in_toks = token_counts["prompt"]
    out_toks = token_counts["completion"]
    cost = (in_toks / 1e6 * MODEL_PRICES["input"]) + (out_toks / 1e6 * MODEL_PRICES["output"])
    save_state(state)
    mins = (time.time() - started) / 60
    print(f"\nbatch done in {mins:.1f} min | prompt_tokens={in_toks} completion_tokens={out_toks} "
          f"| est cost ${cost:.3f} | distilled total={len(state['distilled'])} "
          f"parked={len(state['parked'])}")
    remaining = len(threads) - len(state["distilled"]) - len(state["parked"])
    print(f"REMAINING undistilled threads: {remaining} (of {len(threads)})")
    return 0


# ------------------------------------------------------- facebook source

def load_fb_posts(source_dir: Path) -> list[dict]:
    """Read anonymized fb_threads records -> prompt-shaped pseudo threads.

    Comment authors are already pseudonyms (member-<8hex>); nothing here
    sees a real name. Each pseudo thread keeps the keys thread_text() and
    searchable_text() expect, plus facebook metadata for the prompt/record.
    """
    posts: list[dict] = []
    for path in sorted(source_dir.glob("*.json")):
        try:
            rec = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            print(f"WARN corrupt fb record {path.name}: {exc}", file=sys.stderr)
            continue
        if not isinstance(rec, dict) or rec.get("source") != "facebook":
            continue
        comments = rec.get("comments") or []
        posts.append({
            "stem": path.stem,
            "post_id": rec.get("id"),
            "url": rec.get("url", ""),
            "group": rec.get("group", ""),
            "group_url": rec.get("group_url", ""),
            "posted_at": rec.get("posted_at", ""),
            "title": rec.get("title", "") or "",
            "body": rec.get("text", ""),
            "comments": [{"user": c.get("pseudonym", ""), "body": c.get("text", ""),
                           "created_at": c.get("posted_at", "")}
                          for c in comments if isinstance(c, dict)],
            "comment_count": len(comments),
        })
    return posts


def load_fb_state() -> dict:
    if STATE_FILE_FB.exists():
        try:
            return json.loads(STATE_FILE_FB.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return {"distilled": [], "parked": [], "runs": 0}


def save_fb_state(state: dict) -> None:
    STATE_FILE_FB.write_text(json.dumps(state, indent=1), encoding="utf-8")


def pick_fb_batch(posts: list[dict], state: dict, limit: int) -> list[dict]:
    done = set(state["distilled"]) | set(state["parked"])
    rest = [p for p in posts if p["stem"] not in done]
    rest.sort(key=lambda p: (p["comment_count"], p["stem"]), reverse=True)
    return rest[:limit]


def main_facebook(args) -> int:
    """Distill anonymized FB group posts (--source-dir data/fb_threads).

    Same S->C->F contract as the GitHub corpus, with the FB record schema
    (validate_record_fb), the FB no-names system prompt and a separate state
    file (data/distilled/state.facebook.json) so FB stems never pollute the
    GitHub batch bookkeeping. Metadata (source/group/group_url/url) is
    attached programmatically after the model passes validation — never
    model-written."""
    posts = load_fb_posts(args.source_dir)
    state = load_fb_state()
    batch = pick_fb_batch(posts, state, args.limit)
    print(f"fb posts: {len(posts)} | already distilled: {len(state['distilled'])} "
          f"| parked: {len(state['parked'])} | this batch: {len(batch)}")
    if args.dry_run or not batch:
        for p in batch[:10]:
            print(f"  would distill {p['stem']} cc={p['comment_count']} {p['url']}")
        if batch:
            print(f"  ... ({len(batch)} total; remaining undistilled: "
                  f"{len(posts) - len(state['distilled']) - len(state['parked'])} before this batch)")
        return 0
    if len(batch) > args.limit:
        print(f"note: batch capped at {args.limit}")

    cfg = llm_config()
    print(f"llm: {cfg['model']} @ {cfg['base']} | workers={args.workers} | source_type=facebook")
    DISTILLED.mkdir(parents=True, exist_ok=True)
    REJECTS.mkdir(parents=True, exist_ok=True)
    state["runs"] = to_int(state.get("runs")) + 1
    lock = threading.Lock()
    token_counts = {"prompt": 0, "completion": 0}
    started = time.time()

    def work(post: dict):
        thread_txt = thread_text(post)
        full_txt = searchable_text(post)
        user = USER_TEMPLATE_FB.format(group=post["group"], group_url=post["group_url"],
                                       url=post["url"], posted_at=post["posted_at"],
                                       thread_text=thread_txt)

        def validator(rec):
            return validate_record_fb(rec, full_txt)

        rec, err, usage = distill_one(cfg, SYSTEM_PROMPT_FB, user, validator)
        stem = post["stem"]
        with lock:
            token_counts["prompt"] += to_int(usage.get("prompt_tokens"))
            token_counts["completion"] += to_int(usage.get("completion_tokens"))
            if rec is not None:
                # metadata is attached here (trusted), never by the model
                rec.update({"source": "facebook", "group": post["group"],
                            "group_url": post["group_url"], "url": post["url"]})
                (DISTILLED / f"{stem}.json").write_text(
                    json.dumps(rec, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
                state["distilled"].append(stem)
                save_fb_state(state)
                print(f"ok   {stem} cc={post['comment_count']:<4d} {rec['title'][:60]}", flush=True)
            else:
                parked = {"thread": stem, "group": post["group"], "url": post["url"],
                          "error": err, "parked_at": iso_now()}
                (REJECTS / f"{stem}.json").write_text(
                    json.dumps(parked, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
                state["parked"].append(stem)
                save_fb_state(state)
                print(f"REJECT {stem} — {err}", flush=True)

    _run_pool(work, batch, args.workers, token_counts)

    in_toks = token_counts["prompt"]
    out_toks = token_counts["completion"]
    cost = (in_toks / 1e6 * MODEL_PRICES["input"]) + (out_toks / 1e6 * MODEL_PRICES["output"])
    save_fb_state(state)
    mins = (time.time() - started) / 60
    print(f"\nbatch done in {mins:.1f} min | prompt_tokens={in_toks} completion_tokens={out_toks} "
          f"| est cost ${cost:.3f} | fb distilled total={len(state['distilled'])} "
          f"parked={len(state['parked'])}")
    remaining = len(posts) - len(state["distilled"]) - len(state["parked"])
    print(f"REMAINING undistilled fb posts: {remaining} (of {len(posts)})")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Distill threads into symptom->cause->fix records "
                                             "(github corpus or facebook group posts).")
    ap.add_argument("--limit", type=int, default=DEFAULT_LIMIT,
                    help=f"max threads per run (default {DEFAULT_LIMIT})")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the next batch without calling the LLM")
    ap.add_argument("--workers", type=int, default=4, help="parallel LLM workers")
    ap.add_argument("--source-dir", type=Path, default=CORPUS,
                    help="thread source dir (default: data/corpus; facebook: data/fb_threads)")
    ap.add_argument("--source-type", choices=("github", "facebook"), default="github",
                    help="record/schema flavor of the source dir")
    args = ap.parse_args()

    if args.source_type == "facebook":
        return main_facebook(args)
    return main_github(args)


if __name__ == "__main__":
    sys.exit(main())
