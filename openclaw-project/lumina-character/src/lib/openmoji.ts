// OpenMoji colour emoji (https://openmoji.org, CC BY-SA 4.0; see public/openmoji/OPENMOJI-LICENSE.txt). The 4,495 SVGs in
// public/openmoji/svg are the original, unmodified files, named by Unicode codepoints in uppercase hex joined with "-".
// Nothing here loads the artwork: these helpers only turn an emoji into a file name or an image URL and search names.
import files from './openmoji/files.json';

const AVAILABLE = new Set<string>(files);
const FE0F = 'FE0F';                                             // the "show as emoji" selector: some files include it, some leave it out, at varying positions
const withoutFE0F = (key: string) => key.split('-').filter(p => p !== FE0F).join('-');
const BY_BARE = new Map<string, string>(files.map(k => [withoutFE0F(k), k]));   // all 4,495 files stay distinct once FE0F is ignored (checked), so this is unambiguous
const hex = (cp: number) => cp.toString(16).toUpperCase().padStart(4, '0');

/** "😀" -> "1F600", "👍🏽" -> "1F44D-1F3FD". */
export function codepointKey(emoji: string): string {
  return Array.from(emoji, ch => hex(ch.codePointAt(0)!)).join('-');
}

/**
 * The file name for an emoji character or sequence ("1F600.svg"), or null so the caller can show the plain text emoji instead.
 * Tries the codepoints as given; then without FE0F; then with FE0F added wherever the file has it (OpenMoji names "2764.svg" without
 * it but "1F3CB-FE0F-200D-2640-FE0F.svg" with it in two places, so a fixed position would miss some).
 */
export function emojiToFile(emoji: string): string | null {
  const key = codepointKey(emoji);
  if (!key) return null;
  if (AVAILABLE.has(key)) return `${key}.svg`;
  const found = BY_BARE.get(withoutFE0F(key));
  return found ? `${found}.svg` : null;
}

/** Where the browser can load an emoji's SVG (use it as an image source, never inline the markup), or null if there is none. */
export function emojiUrl(emoji: string): string | null {
  const file = emojiToFile(emoji);
  return file ? `${import.meta.env.BASE_URL}openmoji/svg/${file}` : null;
}

export interface EmojiMatch { emoji: string; file: string; name: string; group: string; keywords: string[] }
interface Index { groups: string[]; items: [string, string, string, number][] }
let loaded: Promise<Index> | null = null;
const loadIndex = () => (loaded ??= import('./openmoji/index.json').then(m => m.default as Index));   // fetched only when someone searches

const toEmoji = (hexcode: string) => String.fromCodePoint(...hexcode.split('-').map(h => parseInt(h, 16)));
const words = (s: string) => s.toLowerCase().split(/[^a-z0-9]+/).filter(Boolean);

/** Best matches for a name, keyword or group ("thumbs up", "cooking", "animals"). Every word of the query must match something. */
export async function searchEmoji(query: string, limit = 8): Promise<EmojiMatch[]> {
  const q = words(query);
  if (!q.length || limit < 1) return [];
  const { groups, items } = await loadIndex();
  const scored: { score: number; order: number; hexcode: string; name: string; kw: string; group: string }[] = [];
  items.forEach(([hexcode, name, kw, g], order) => {
    const nameWords = words(name); const kwList = kw ? kw.split(',') : []; const group = groups[g];
    let total = 0;
    for (const w of q) {
      let s = 0;
      if (name === w) s = 100;
      else if (nameWords.includes(w)) s = 60;
      else if (nameWords.some(n => n.startsWith(w))) s = 40;
      else if (kwList.includes(w)) s = 30;
      else if (kwList.some(k => k.split(' ').some(p => p.startsWith(w)))) s = 15;
      else if (group.includes(w)) s = 5;
      if (!s) return;                                             // this word matched nothing: not a result
      total += s;
    }
    if (name === q.join(' ')) total += 100;                       // the whole query is the name
    scored.push({ score: total, order, hexcode, name, kw, group });
  });
  scored.sort((a, b) => b.score - a.score || a.order - b.order);
  return scored.slice(0, limit).map(m => ({ emoji: toEmoji(m.hexcode), file: `${m.hexcode}.svg`, name: m.name, group: m.group, keywords: m.kw ? m.kw.split(',') : [] }));
}
