// @ts-check
import { defineConfig } from 'astro/config';

// AAPS Atlas — static Astro build.
// - outDir 'site' keeps the Cloudflare Pages deploy path unchanged
//   (CI uploads site/ and runs `wrangler pages deploy site`).
// - build.format 'file' emits docs pages as docs/<slug>.html — URL parity
//   with the pre-Astro site (aaps-atlas.pages.dev/docs/<slug>.html).
// - site/search-index.json + site/search-data.js are produced before the
//   build by `python3 scripts/build_index.py` into public/ (copied by Astro),
//   so site/search.js (public/search.js) and the acceptance harness
//   scripts/search_check.mjs keep working untouched.
export default defineConfig({
  site: 'https://aaps-atlas.pages.dev',
  outDir: 'site',
  build: {
    format: 'file',
  },
  // Keep whitespace between inline elements (the hand-written pages relied
  // on it for the " · " separators between links in the examples row and
  // footer).
  compressHTML: false,
});
