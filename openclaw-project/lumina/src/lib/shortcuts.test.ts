import { describe, expect, it } from 'vitest';
import { clashes, forPlace, keyWords, placeOf, presses, SHORTCUTS, type Shortcut } from './shortcuts';

describe('the shortcut registry', () => {
  it('has no two shortcuts with the same keys in the same place', () => {
    expect(clashes()).toEqual([]);
  });

  it('catches a clash when one is added', () => {
    const extra: Shortcut = { id: 'oops', keys: 'j', name: 'Oops', group: 'Mail', where: ['inbox'] };
    expect(clashes([...SHORTCUTS, extra])).toEqual(['mail-next and oops both use j']);
    expect(clashes([...SHORTCUTS, { ...extra, where: ['calendar'] }])).toEqual([]);           // the same key in another place is fine
  });

  it('gives every shortcut a name and a place, and every place the frame\'s own', () => {
    for (const s of SHORTCUTS) { expect(s.name.length).toBeGreaterThan(2); expect(s.where.length).toBeGreaterThan(0); }
    for (const p of ['home', 'chat', 'inbox', 'calendar', 'files', 'activity', 'settings'] as const) expect(forPlace(p).some(s => s.id === 'command')).toBe(true);
    expect(forPlace('chat').some(s => s.id === 'assistant')).toBe(false);                   // Chat is the assistant
    expect(forPlace('inbox').find(s => s.keys === '/')?.id).toBe('mail-search');            // "/" searches mail there, opens the bar elsewhere
  });

  it('words keys the way they are pressed', () => {
    expect(keyWords('g i')).toBe('G then I');
    expect(keyWords('shift+d')).toBe('Shift D');
    expect(['Ctrl K', '⌘ K']).toContain(keyWords('mod+k'));
  });

  it('matches key events', () => {
    const e = (key: string, o: Partial<KeyboardEvent> = {}) => ({ key, metaKey: false, ctrlKey: false, shiftKey: false, altKey: false, ...o });
    expect(presses(e('k', { ctrlKey: true }), 'mod+k')).toBe(true);
    expect(presses(e('k'), 'mod+k')).toBe(false);
    expect(presses(e('?', { shiftKey: true }), '?')).toBe(true);
    expect(presses(e('D', { shiftKey: true }), 'shift+d')).toBe(true);
    expect(presses(e('d'), 'shift+d')).toBe(false);
  });

  it('knows which place an address belongs to', () => {
    expect(['/inbox', '/calendar', '/files', '/tasks/1', '/activity', '/settings/usage', '/integrations', '/chat/x', '/'].map(placeOf))
      .toEqual(['inbox', 'calendar', 'files', 'activity', 'activity', 'settings', 'settings', 'chat', 'chat']);
  });
});
