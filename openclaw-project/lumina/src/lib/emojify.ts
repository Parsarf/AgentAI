// Shows emoji as OpenMoji pictures (src/lib/openmoji.ts has the 4,495 files and the lookup). Text stays text wherever there is no picture
// for an emoji, inside code, and for characters that are only emoji when followed by FE0F (such as (c) and (tm)).
import { emojiToFile } from './openmoji';

const BASE = String.raw`(?:\p{Emoji_Presentation}|\p{Extended_Pictographic}️)`;
const MOD = String.raw`(?:\p{Emoji_Modifier}|️)?`;
/** One emoji: an England-style tag flag, a flag (two regional indicators), a keycap, or a symbol with optional skin tone and ZWJ parts. */
const EMOJI = new RegExp(
  String.raw`\u{1F3F4}[\u{E0020}-\u{E007E}]+\u{E007F}` +
  String.raw`|\p{Regional_Indicator}{2}` +
  String.raw`|[0-9#*]️?⃣` +
  `|${BASE}${MOD}(?:\\u200D(?:${BASE}|\\p{Extended_Pictographic})${MOD})*`, 'gu');
const QUICK = /[\u{1F000}-\u{1FFFF}←-⯿⃣️‍]/u;       // most text has none of these: skip the scan

export type EmojiPart = string | { emoji: string; file: string };

/** Splits text into plain strings and emoji that have a picture. Returns [text] unchanged when there is nothing to show. */
export function splitEmoji(text: string): EmojiPart[] {
  if (!text || !QUICK.test(text)) return [text];
  const parts: EmojiPart[] = []; let last = 0; let any = false;
  for (const m of text.matchAll(EMOJI)) {
    const file = emojiToFile(m[0]);
    if (!file) continue;                                          // no picture: leave it as the text emoji
    if (m.index > last) parts.push(text.slice(last, m.index));
    parts.push({ emoji: m[0], file }); last = m.index + m[0].length; any = true;
  }
  if (!any) return [text];
  if (last < text.length) parts.push(text.slice(last));
  return parts;
}

export const EMOJI_BASE = `${import.meta.env.BASE_URL}openmoji/svg/`;
export const isEmojiUrl = (url?: string) => !!url && url.startsWith(EMOJI_BASE);

// --- Markdown: replace emoji in the message's text with image nodes (the renderer turns those into <img class="emoji">) ---
interface MdNode { type: string; value?: string; url?: string; alt?: string; children?: MdNode[] }
function walk(node: MdNode) {
  if (!node.children) return;
  const next: MdNode[] = [];
  for (const child of node.children) {
    if (child.type === 'text' && child.value) {
      const parts = splitEmoji(child.value);
      if (parts.length === 1 && typeof parts[0] === 'string') { next.push(child); continue; }
      for (const p of parts) next.push(typeof p === 'string' ? { type: 'text', value: p } : { type: 'image', url: EMOJI_BASE + p.file, alt: p.emoji });
    } else { walk(child); next.push(child); }                      // code and inlineCode have a value but no text children: they are left alone
  }
  node.children = next;
}
/** remark plugin. */
export function remarkEmoji() { return (tree: MdNode) => walk(tree); }
