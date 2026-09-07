# data/fb_threads — anonymized Facebook group threads

Populated by the pilot FB scrape task (blocked on ☀️ manual group-access
setup upstream) and **never hand-edited**. Each file is one anonymized
Facebook post from a closed diabetes-technology support group, produced by
`scripts/fb_anonymize.py` from a raw Apify `facebook-posts-scraper` run.

## Record schema (`<group>-<postid>.json`)

```jsonc
{
  "id": "<post id>",
  "source": "facebook",
  "group": "<group display name / slug>",
  "group_url": "https://www.facebook.com/groups/<gid>",
  "url": "https://www.facebook.com/groups/<gid>/posts/<postid>/",   // permalink kept for linkback
  "posted_at": "2025-11-02T09:14:00Z",
  "text": "<post body>",
  "comments": [
    { "pseudonym": "member-<8 hex>", "text": "<comment body>", "posted_at": "…" }
  ],
  "reactions_count": 12        // optional — aggregate only
}
```

## Privacy invariants (user requirement — enforced, not aspirational)

- **No person names anywhere.** Comment authors are stable pseudonyms
  `member-<8hex>` (HMAC-SHA256 of the author id keyed by the per-install
  salt from `FB_PSEUDONYM_SALT` / `~/.config/aaps-atlas/fb-pseudonym-salt`).
- Profile fields (name, profile-pic URL, user URL, per-user reactions) are
  **dropped at map time** — outputs are built from a whitelist, so they
  cannot survive by accident. Only aggregates (reactions/comment counts)
  are kept.
- Post permalinks **are** kept for verification linkback.
- Two hard gates: `scripts/fb_anonymize.py` fails closed on any author-name
  leak before writing; `scripts/validate_privacy.py` (CI) re-checks stored +
  distilled records against the raw author list and fails the build on any
  leak.

## Raw archives

Full-fidelity raw Apify output and author-name rosters must never be
committed — keep them under `data/fb_threads/raw/` (gitignored) or outside
the repo. `raw/` exists for the pilot's transient inputs only.
