import { describe, expect, it } from 'vitest';
import { codepointKey, emojiToFile, emojiUrl, searchEmoji } from './openmoji';
import files from './openmoji/files.json';

// Vite lists the real files in public/openmoji/svg (the loaders read a file's text only when called).
const loaders = import.meta.glob<string>('/public/openmoji/svg/*.svg', { query: '?raw', import: 'default' });
const shipped = new Set(Object.keys(loaders).map(p => p.slice(p.lastIndexOf('/') + 1)));
const onDisk = (file: string | null) => file !== null && shipped.has(file);
const fromKey = (key: string) => String.fromCodePoint(...key.split('-').map(h => parseInt(h, 16)));

describe('emojiToFile', () => {
  it('finds a simple emoji, a skin-tone emoji, a ZWJ sequence and a flag, and each file exists', () => {
    for (const [emoji, file] of [['😀', '1F600.svg'], ['👍🏽', '1F44D-1F3FD.svg'], ['🧑🏽‍🍳', '1F9D1-1F3FD-200D-1F373.svg'], ['🇺🇸', '1F1FA-1F1F8.svg']] as const) {
      expect(emojiToFile(emoji)).toBe(file);
      expect(onDisk(emojiToFile(emoji))).toBe(true);
    }
  });

  it('builds uppercase hex codepoints joined with hyphens', () => {
    expect(codepointKey('😀')).toBe('1F600');
    expect(codepointKey('🧑🏽‍🍳')).toBe('1F9D1-1F3FD-200D-1F373');
    expect(codepointKey('')).toBe('');
  });

  it('copes with FE0F being present or absent, wherever the file keeps it', () => {
    expect(emojiToFile('❤️')).toBe('2764.svg');                          // the file has no FE0F, the text has one: removed
    expect(emojiToFile('❤')).toBe('2764.svg');
    expect(emojiToFile('☺')).toBe('263A.svg');
    expect(emojiToFile('🏋‍♀')).toBe('1F3CB-FE0F-200D-2640-FE0F.svg');    // the file has FE0F twice, the text has none: added back
    expect(emojiToFile('🏋️‍♀️')).toBe('1F3CB-FE0F-200D-2640-FE0F.svg');
    expect(onDisk(emojiToFile('🏋‍♀'))).toBe(true);
  });

  it('returns null when there is no picture, so the caller can show the plain text', () => {
    for (const text of ['', 'a', 'hello', '😀x', '\u{10FFFF}']) expect(emojiToFile(text)).toBeNull();
  });

  it('finds every one of the shipped files from its own emoji', () => {
    for (const key of files) expect(emojiToFile(fromKey(key))).toBe(`${key}.svg`);
  });
});

describe('the shipped files', () => {
  it('match the file list exactly, and every name is a valid codepoint sequence', () => {
    const names = [...shipped].map(f => f.slice(0, -4)).sort();
    expect(names).toEqual([...files].sort());
    expect(names.length).toBe(4495);
    for (const n of names) expect(n).toMatch(/^[0-9A-F]{4,6}(-[0-9A-F]{4,6})*$/);
  });

  it('are plain pictures: no scripts, event handlers, links or embedded objects', async () => {
    const bad = /<script|\son[a-z]+\s*=|javascript:|<foreignObject|<iframe|<embed|<object|href\s*=\s*["']https?:|@import|<!ENTITY|<!DOCTYPE/i;
    const offenders: string[] = [];
    for (const [path, load] of Object.entries(loaders)) if (bad.test(await load())) offenders.push(path);
    expect(offenders).toEqual([]);
  }, 60000);
});

describe('emojiUrl', () => {
  it('points at the served SVG, or is null without one', () => {
    expect(emojiUrl('😀')).toMatch(/\/openmoji\/svg\/1F600\.svg$/);
    expect(emojiUrl('🇺🇸')).toMatch(/\/openmoji\/svg\/1F1FA-1F1F8\.svg$/);
    expect(emojiUrl('nope')).toBeNull();
  });
});

describe('searchEmoji', () => {
  it('finds an emoji by its name, ranking the exact name first', async () => {
    const r = await searchEmoji('grinning face');
    expect(r[0].emoji).toBe('😀'); expect(r[0].file).toBe('1F600.svg'); expect(r[0].group).toBe('smileys-emotion');
  });
  it('finds by keyword and by several words together', async () => {
    expect((await searchEmoji('thumbs up')).some(m => m.emoji === '👍')).toBe(true);
    const cooking = await searchEmoji('cooking'); expect(cooking.length).toBeGreaterThan(0);
    expect((await searchEmoji('flag united states')).some(m => m.file === '1F1FA-1F1F8.svg')).toBe(true);
  });
  it('only returns pictures that exist, and respects the limit', async () => {
    const r = await searchEmoji('face', 5);
    expect(r.length).toBe(5);
    for (const m of r) { expect(onDisk(m.file)).toBe(true); expect(emojiToFile(m.emoji)).toBe(m.file); }
  });
  it('returns nothing for gibberish, an empty query or a zero limit', async () => {
    expect(await searchEmoji('qzxjvkw')).toEqual([]);
    expect(await searchEmoji('   ')).toEqual([]);
    expect(await searchEmoji('face', 0)).toEqual([]);
  });
  it('is not case sensitive', async () => { expect((await searchEmoji('GRINNING FACE'))[0].emoji).toBe('😀'); });
});
