# tests/fixtures — fixture-based tests, no network

All fixtures are **synthetic**: every person name/handle is made up and the
group URLs/ids do not resolve. Tests never touch Facebook, GitHub, or the
LLM — they exercise the anonymizer, the privacy gates, the distiller's FB
record validation and the search index with these files only.

## apify_sample.json — raw scrape shape under test

Models the documented output of the `apify/facebook-posts-scraper` actor
(output schema reference: <https://apify.com/apify/facebook-posts-scraper>).
Two closed groups ("xDrip+ users", "AndroidAPS Users"); five posts with
comment/reaction data, per-user reaction lists, profile URLs and timestamps
in both ISO and epoch forms. Key fields the anonymizer maps (tolerating the
common aliases): `url`/`postUrl` (post permalink), `groupName`/`groupUrl`/
`inputUrl` (group identity), `date`/`timestamp`, `postText`, `postComments`
with `commentAuthorId`/`commentAuthor`, nested `user` objects, and
`postReactionsCount` (kept as aggregate) + `reactions` (per-user list —
dropped).

Author names appearing anywhere in this file (post authors, commenters,
reaction lists) are the **roster the privacy gate scans for**:

  Alicia Chen · Marco Ruiz · Priya Nair · Tom Becker · Jordan Lee · Sam Okafor

**Do not** edit these names into the fixture *text fields* — the anonymizer
is supposed to pass with zero leaks on this file (a leak here fails the
acceptance fixture run). Deliberately-poisoned variants live next door:

- `poisoned_fb_thread.json` — an anonymized-shaped FB thread whose comment
  text contains a real author name (gate must FAIL it).
- `poisoned_distilled.json` — an FB distilled record whose `fix` field
  contains a real author name (gate must FAIL it).

## Regenerating expectations

Expected filenames from the fixture (group slug + post id):

    xdrip-users-pfbid0SampleA1xY.json
    xdrip-users-pfbid0SampleA2zQ.json
    xdrip-users-pfbid0SampleA3pL.json
    584126708394913-pfbid0SampleA4mN.json     # no groupName on this item -> gid slug
    androidaps-users-pfbid0SampleB1wT.json
