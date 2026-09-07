/**
 * Markdown -> HTML for the mirrored doc pages.
 *
 * Faithful port of the md_to_html()/md_inline() rules previously used by
 * scripts/build_index.py so doc-mirror pages keep rendering the same content:
 *   - inline: `code`, **strong**, *emphasis* (escaped &, <, > first)
 *   - block: ATX headings (#..######), "- " list items, "N. " numbered
 *     items, "---" thematic breaks, otherwise paragraphs
 *   - consecutive list items are wrapped in a single <ul>
 *
 * The mirrored text is nav/script-free plain text (fetch_docs.py strips
 * links), so this intentionally does NOT implement links/images/tables.
 */
export function escapeHtml(s: string): string {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

export function mdInline(s: string): string {
  let out = escapeHtml(s);
  out = out.replace(/`([^`]+)`/g, '<code>$1</code>');
  out = out.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
  out = out.replace(/\*([^*]+)\*/g, '<em>$1</em>');
  return out;
}

const HEADING_RE = /^(#{1,6})\s+(.*)$/;
const NUMBERED_RE = /^\s*\d+\.\s+/;

/** Convert mirrored doc markdown body to an HTML fragment string. */
export function mdToHtml(md: string): string {
  const out: string[] = [];
  for (const raw of md.split('\n')) {
    const line = raw.replace(/\s+$/, '');
    if (!line.trim()) continue;
    const h = HEADING_RE.exec(line);
    if (h) {
      const level = Math.min(h[1].length, 6);
      out.push(`<h${level}>${mdInline(h[2])}</h${level}>`);
    } else if (line.startsWith('- ')) {
      out.push(`<li>${mdInline(line.slice(2))}</li>`);
    } else if (NUMBERED_RE.test(line)) {
      out.push(`<li>${mdInline(line.replace(NUMBERED_RE, ''))}</li>`);
    } else if (line === '---') {
      out.push('<hr>');
    } else {
      out.push(`<p>${mdInline(line)}</p>`);
    }
  }
  // Wrap runs of consecutive <li> elements in one <ul>.
  const body: string[] = [];
  let buf: string[] = [];
  for (const el of out) {
    if (el.startsWith('<li>')) {
      buf.push(el);
    } else {
      if (buf.length) {
        body.push('<ul>' + buf.join('') + '</ul>');
        buf = [];
      }
      body.push(el);
    }
  }
  if (buf.length) body.push('<ul>' + buf.join('') + '</ul>');
  return body.join('\n');
}
