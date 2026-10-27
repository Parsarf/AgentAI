import { describe, expect, it } from 'vitest';
import { EMOJI_BASE, isEmojiUrl, remarkEmoji, splitEmoji } from './emojify';

const pic = (emoji: string, file: string) => ({ emoji, file });

describe('splitEmoji', () => {
  it('leaves ordinary text alone', () => {
    for (const t of ['', 'plain text', 'Price: $70 (c) 2026 #1 *star* 3x', 'café – naïve ✓ → ½']) expect(splitEmoji(t)).toEqual([t]);
  });

  it('turns emoji into pictures and keeps the words around them', () => {
    expect(splitEmoji('😀')).toEqual([pic('😀', '1F600.svg')]);
    expect(splitEmoji('hot 🌶️🔥 now')).toEqual(['hot ', pic('🌶️', '1F336.svg'), pic('🔥', '1F525.svg'), ' now']);
  });

  it('handles skin tones, ZWJ sequences, flags and keycaps as single pictures', () => {
    expect(splitEmoji('👍🏽')).toEqual([pic('👍🏽', '1F44D-1F3FD.svg')]);
    expect(splitEmoji('🧑🏽‍🍳')).toEqual([pic('🧑🏽‍🍳', '1F9D1-1F3FD-200D-1F373.svg')]);
    expect(splitEmoji('🇺🇸')).toEqual([pic('🇺🇸', '1F1FA-1F1F8.svg')]);
    expect(splitEmoji('🏋️‍♀️')).toEqual([pic('🏋️‍♀️', '1F3CB-FE0F-200D-2640-FE0F.svg')]);
    const keycap = splitEmoji('1️⃣'); expect(keycap.length).toBe(1); expect(typeof keycap[0]).toBe('object');
  });

  it('does not turn text symbols or digits into pictures', () => {
    expect(splitEmoji('© ® ™ 2026 #1')).toEqual(['© ® ™ 2026 #1']);
    expect(splitEmoji('🇺')).toEqual([pic('🇺', '1F1FA.svg')]);       // OpenMoji ships a picture for each lone regional-indicator letter
  });

  it('shows ❤️ (with the emoji selector) as a picture but leaves the bare text heart as text', () => {
    expect(splitEmoji('I ❤️ it')).toEqual(['I ', pic('❤️', '2764.svg'), ' it']);
    expect(splitEmoji('I ❤ it')).toEqual(['I ❤ it']);
  });
});

describe('remarkEmoji', () => {
  const tree = () => ({ type: 'root', children: [
    { type: 'paragraph', children: [{ type: 'text', value: 'hi 😀 there' }, { type: 'strong', children: [{ type: 'text', value: '🔥' }] }] },
    { type: 'code', value: 'print("😀")' },
    { type: 'paragraph', children: [{ type: 'inlineCode', value: '🔥' }] },
  ] });

  it('replaces emoji in text (including inside bold) with image nodes', () => {
    const t = tree(); remarkEmoji()(t);
    const p = t.children[0].children!;
    expect(p.map(n => n.type)).toEqual(['text', 'image', 'text', 'strong']);
    expect(p[1]).toEqual({ type: 'image', url: EMOJI_BASE + '1F600.svg', alt: '😀' });
    expect(p[3].children![0]).toEqual({ type: 'image', url: EMOJI_BASE + '1F525.svg', alt: '🔥' });
  });

  it('never touches code', () => {
    const t = tree(); remarkEmoji()(t);
    expect(t.children[1]).toEqual({ type: 'code', value: 'print("😀")' });
    expect(t.children[2].children![0]).toEqual({ type: 'inlineCode', value: '🔥' });
  });

  it('recognises its own picture urls', () => {
    expect(isEmojiUrl(EMOJI_BASE + '1F600.svg')).toBe(true);
    expect(isEmojiUrl('https://example.com/openmoji/svg/1F600.svg')).toBe(false);
    expect(isEmojiUrl(undefined)).toBe(false);
  });
});
