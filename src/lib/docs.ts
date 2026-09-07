/**
 * Load the mirrored doc pages from data/docs/*.md for Astro routing.
 *
 * Same parsing contract as scripts/build_index.py (which builds the search
 * index): the first line is `# Source: <url>` (url may be wrapped in angle
 * brackets); the title is the first `# ` heading after it; the remainder is
 * mirrored markdown body rendered by src/lib/md.ts.
 */
import { readFileSync, readdirSync } from 'node:fs';

// Astro prerenders page modules into outDir (site/.prerender/...), so
// import.meta.url points inside the output tree during getStaticPaths —
// resolve data/docs against the build working directory (repo root) instead.
const DOCS_DIR = `${process.cwd()}/data/docs`;

const SRC_RE = /^#\s*Source:\s*(?:<)?(https?:\/\/[^\s>]+)(?:>)?/i;
const H1_RE = /^#\s+(.+)$/;

export interface DocRecord {
  slug: string;
  title: string;
  sourceUrl: string;
  /** Markdown body (source line + duplicated leading title stripped). */
  bodyMd: string;
}

/** Parse one data/docs/<slug>.md file. */
export function parseDoc(slug: string): DocRecord {
  const text = readFileSync(`${DOCS_DIR}/${slug}.md`, 'utf8');
  const lines = text.split('\n');
  let sourceUrl = '';
  const bodyLines: string[] = [];
  for (const line of lines) {
    if (sourceUrl === '') {
      const m = SRC_RE.exec(line.trim());
      if (m) {
        sourceUrl = m[1];
        continue; // drop the source line from the body
      }
    }
    bodyLines.push(line);
  }
  // Title: first `# ` heading (after the source line).
  let title = '';
  for (const ln of bodyLines) {
    const m = H1_RE.exec(ln.trim());
    if (m) {
      title = m[1].trim();
      break;
    }
  }
  title = title || slug.replace(/-/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
  // Drop a duplicated leading `# <title>` (the page header renders it as h1).
  const firstContent = bodyLines.find((l) => l.trim() !== '');
  if (firstContent) {
    const m = H1_RE.exec(firstContent.trim());
    if (m && m[1].trim() === title) {
      const idx = bodyLines.indexOf(firstContent);
      bodyLines.splice(idx, 1);
    }
  }
  const bodyMd = bodyLines.join('\n').replace(/^\s*\n/, '').trim();
  return { slug, title, sourceUrl, bodyMd };
}

/** All doc slugs found in data/docs (excluding hidden files). */
export function listDocSlugs(): string[] {
  return readdirSync(DOCS_DIR)
    .filter((f) => f.endsWith('.md') && !f.startsWith('.'))
    .map((f) => f.slice(0, -3))
    .sort();
}
