import { afterEach, describe, expect, it } from 'vitest';
import { applyTheme, storedTheme } from './settings';

afterEach(() => { localStorage.clear(); delete document.documentElement.dataset.theme; });

describe('theme choice', () => {
  it('is the dark world until the person picks parchment', () => {
    expect(storedTheme()).toBe('obsidian');
    localStorage.setItem('lumina.theme', 'parchment');
    expect(storedTheme()).toBe('parchment');
  });
  it('ignores a value it does not know', () => {
    localStorage.setItem('lumina.theme', 'neon');
    expect(storedTheme()).toBe('obsidian');
  });
  it('is applied on the root element', () => {
    applyTheme('parchment');
    expect(document.documentElement.dataset.theme).toBe('parchment');
  });
});
