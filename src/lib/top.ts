/**
 * Build-time "top distilled records" for the populated landing state.
 *
 * The home page must not be a blank shell when no query is typed (DA-201):
 * Astro statically renders a small set of top distilled records — complete
 * symptom -> cause -> fix records only (the conclusions-only contract),
 * ranked by (confidence, source-thread comment count). Runs in the Astro
 * prerender like docs.ts; reads data/distilled + data/corpus straight from
 * the repo root.
 */
import { readFileSync, readdirSync } from 'node:fs';

const DISTILLED_DIR = `${process.cwd()}/data/distilled`;
const CORPUS_DIR = `${process.cwd()}/data/corpus`;

const CONF_W: Record<string, number> = { high: 3, medium: 2, low: 1 };
const TOP_N = 4;

export interface TopRecord {
  title: string;
  url: string;
  issueRef: string;
  confidence: string;
  symptom: string;
  cause: string;
  fix: string;
  commentCount: number;
}

/** Complete distilled records ranked by (confidence, source-thread comments).
 *  Only records with ALL THREE parts (symptom/cause/fix) may appear — the
 *  conclusions-only contract is enforced statically for the landing list. */
export function loadTopDistilled(): TopRecord[] {
  const out: TopRecord[] = [];
  const files = readdirSync(DISTILLED_DIR)
    .filter((f) => f.endsWith('.json') && !f.startsWith('state'))
    .sort();
  for (const f of files) {
    let d: Record<string, unknown>;
    try {
      d = JSON.parse(readFileSync(`${DISTILLED_DIR}/${f}`, 'utf8'));
    } catch {
      continue;
    }
    const symptom = String(d.symptom ?? '').trim();
    const cause = String(d.cause ?? '').trim();
    const fix = String(d.fix ?? '').trim();
    if (!symptom || !cause || !fix) continue;
    if (d.source === 'facebook') continue; // none committed today; landing stays GitHub-sourced
    const repo = String(d.repo ?? '');
    const issueId = String(d.issue_id ?? '');
    if (!repo || !issueId) continue;
    const url = String(d.url ?? '');
    const confidence = String(d.confidence ?? 'low');
    let commentCount = 0;
    const stem = f.slice(0, -5);
    try {
      const src = JSON.parse(readFileSync(`${CORPUS_DIR}/${stem}.json`, 'utf8')) as {
        comment_count?: number;
      };
      commentCount = Number(src.comment_count) || 0;
    } catch {
      // distilled record whose corpus file is missing — rank by confidence only
    }
    out.push({
      title: String(d.title ?? ''),
      url,
      issueRef: `${repo.split('/')[1] ?? repo}#${issueId}`,
      confidence,
      symptom,
      cause,
      fix,
      commentCount,
    });
  }
  out.sort(
    (a, b) =>
      (CONF_W[b.confidence] ?? 0) - (CONF_W[a.confidence] ?? 0) ||
      b.commentCount - a.commentCount ||
      a.title.localeCompare(b.title)
  );
  return out.slice(0, TOP_N);
}
