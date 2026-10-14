// Builds the two small data files the emoji helpers use, from the unmodified OpenMoji SVGs and OpenMoji's own openmoji.json (CC BY-SA 4.0).
//   node scripts/build-openmoji-index.mjs <path to openmoji.json>
// Writes src/lib/openmoji/files.json (every SVG that exists) and src/lib/openmoji/index.json (names/keywords/groups for search).
// The SVG files themselves are never read or changed; openmoji.json is parsed as data only.
import { readdirSync, readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const svgDir = join(here, '..', 'public', 'openmoji', 'svg');
const outDir = join(here, '..', 'src', 'lib', 'openmoji');
const source = process.argv[2];
if (!source) { console.error('usage: node scripts/build-openmoji-index.mjs <openmoji.json>'); process.exit(1); }

const files = readdirSync(svgDir).filter(f => /^[0-9A-F]{4,6}(-[0-9A-F]{4,6})*\.svg$/.test(f)).map(f => f.slice(0, -4)).sort();
const have = new Set(files);
const data = JSON.parse(readFileSync(source, 'utf8'));

// One search entry per emoji (skin-tone variants are reachable through emojiToFile, and would only repeat the same names).
const groups = []; const items = []; let missing = 0, variants = 0;
for (const e of data) {
  if (typeof e.hexcode !== 'string' || !have.has(e.hexcode)) { missing += 1; continue; }
  if (e.skintone) { variants += 1; continue; }
  let g = groups.indexOf(e.group); if (g < 0) { g = groups.length; groups.push(e.group); }
  const words = [...new Set(`${e.tags ?? ''},${e.openmoji_tags ?? ''}`.split(',').map(w => w.trim().toLowerCase()).filter(Boolean))];
  items.push([e.hexcode, String(e.annotation ?? '').toLowerCase(), words.join(','), g]);
}
mkdirSync(outDir, { recursive: true });
writeFileSync(join(outDir, 'files.json'), JSON.stringify(files));
writeFileSync(join(outDir, 'index.json'), JSON.stringify({ groups, items }));
console.log(JSON.stringify({ svgFiles: files.length, entriesInJson: data.length, searchable: items.length, skipped: { noFileForEntry: missing, skinToneVariants: variants }, filesWithoutAnEntry: files.length - data.filter(e => have.has(e.hexcode)).length }));
