import type { ReactNode } from 'react';
import { EMOJI_BASE, splitEmoji } from '../lib/emojify';

/** One OpenMoji picture. The alt text is the emoji itself, so copying, searching and screen readers still get the character. */
export function EmojiImg({ emoji, file }: { emoji: string; file: string }) {
  return <img className="emoji" src={EMOJI_BASE + file} alt={emoji} draggable={false} loading="lazy" decoding="async" />;
}

/** Text with its emoji shown as pictures. Plain text (the usual case) comes back untouched. */
export function Emojified({ text }: { text: string }): ReactNode {
  const parts = splitEmoji(text);
  if (parts.length === 1 && typeof parts[0] === 'string') return parts[0];
  return parts.map((p, i) => (typeof p === 'string' ? p : <EmojiImg key={i} emoji={p.emoji} file={p.file} />));
}
