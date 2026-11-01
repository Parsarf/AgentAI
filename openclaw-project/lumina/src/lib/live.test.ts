import { describe, expect, it } from 'vitest';
import type { ActivityItem } from './activity';
import { FALLBACK_AFTER, NOTE_TEXT, frameBackoff, followMode, keyAction, modesFor, nowLabel, parseNow, stepText, toBrowser } from './live';

const row = (category: string, key = category): ActivityItem => ({ key, category, label: category, detail: '', output: '', status: 'done', at: '' });

describe('live view helpers', () => {
  it('maps a click on the scaled picture into the 1280x800 browser window', () => {
    expect(toBrowser(150, 120, { left: 100, top: 100, width: 640, height: 400 })).toEqual({ x: 100, y: 40 });
    expect(toBrowser(740, 500, { left: 100, top: 100, width: 640, height: 400 })).toEqual({ x: 1280, y: 800 });
    expect(toBrowser(300, 300, { left: 0, top: 0, width: 960, height: 600 })).toEqual({ x: 400, y: 400 });   // the 960x600 live frame keeps the window's shape
  });

  it('hides screenshots and your own control events from the step list and names unlabeled steps', () => {
    expect(stepText({ n: 1, kind: 'screenshot', file: 'shot-001.jpg' })).toBeNull();
    expect(stepText({ n: 4, kind: 'control', action: 'type' })).toBeNull();
    expect(stepText({ n: 2, kind: 'step', summary: 'Opened shop' })).toBe('Opened shop');
    expect(stepText({ n: 3, kind: 'step' })).toBe('Acted on the page');
  });

  it('follows actual running commands, otherwise opens Activity', () => {
    const running = { ...row('command'), status: 'running' as const };
    expect(followMode([], true)).toBe('activity');
    expect(followMode([row('browse'), row('read')], true)).toBe('activity');
    expect(followMode([running, row('note')], true)).toBe('terminal');
    expect(followMode([running], false)).toBe('activity');
    expect(followMode([row('command')], true)).toBe('activity');
    expect(followMode([row('file')], true)).toBe('activity');
  });

  it('offers Terminal only while in use and Screen only for browser tasks', () => {
    expect(modesFor(true)).toEqual(['activity', 'screen', 'files']);
    expect(modesFor(false)).toEqual(['activity', 'files']);
    expect(modesFor(true, true)).toEqual(['activity', 'screen', 'terminal', 'files']);
    expect(modesFor(false, true)).toEqual(['activity', 'terminal', 'files']);
  });

  it('forwards typing and a few editing keys to the page, but never shortcuts or other keys', () => {
    expect(keyAction({ key: 'a' })).toEqual({ kind: 'text', text: 'a' });
    expect(keyAction({ key: ' ' })).toEqual({ kind: 'text', text: ' ' });
    expect(keyAction({ key: 'Enter' })).toEqual({ kind: 'key', text: 'Enter' });
    expect(keyAction({ key: 'ArrowLeft' })).toEqual({ kind: 'key', text: 'ArrowLeft' });
    expect(keyAction({ key: 'Backspace' })).toEqual({ kind: 'key', text: 'Backspace' });
    for (const k of ['F5', 'Shift', 'Meta', 'Delete', 'Dead']) expect(keyAction({ key: k })).toBeNull();
    expect(keyAction({ key: 'r', metaKey: true })).toBeNull();                                      // Cmd/Ctrl+R stays the browser's own
    expect(keyAction({ key: 'w', ctrlKey: true })).toBeNull();
    expect(keyAction({ key: 'x', altKey: true })).toBeNull();
  });

  it('backs off gently when frames fail and falls back to snapshots after a few misses', () => {
    expect([1, 2, 3, 4, 5, 9].map(frameBackoff)).toEqual([250, 500, 1000, 2000, 4000, 10000]);
    expect(frameBackoff(0)).toBe(250);
    expect(FALLBACK_AFTER).toBeGreaterThan(1);
  });
});

describe('who is deciding, read from a frame response', () => {
  const headers = (h: Record<string, string>) => (name: string) => h[name] ?? null;

  it('reads the four headers into a status and turns the codes into our own words', () => {
    const n = parseNow(headers({ 'X-Now-Seq': '7', 'X-By': 'claude', 'X-Mode': 'controls', 'X-Note': 'took' }));
    expect(n).toEqual({ seq: '7', by: 'claude', mode: 'controls', note: 'took' });
    expect(nowLabel(n!)).toBe('Claude'); expect(NOTE_TEXT.took).toBe('Claude took over this page');
    expect(nowLabel({ seq: '1', by: 'jev', mode: 'picture', note: '' })).toBe('JEV · picture');
    expect(nowLabel({ seq: '1', by: 'jev', mode: 'controls', note: '' })).toBe('JEV');
    expect(parseNow(headers({ 'X-Now-Seq': '2', 'X-By': 'jev', 'X-Mode': 'controls' }))?.note).toBe('');          // no note header: no notice
  });

  it('ignores anything that is not exactly what the gateway sends, so no page-controlled text can reach the screen', () => {
    const ok = { 'X-Now-Seq': '1', 'X-By': 'jev', 'X-Mode': 'controls', 'X-Note': '' };
    expect(parseNow(headers({}))).toBeNull();
    for (const bad of [{ 'X-Now-Seq': 'abc' }, { 'X-Now-Seq': '1'.repeat(20) }, { 'X-By': 'someone' }, { 'X-Mode': 'x' }, { 'X-Note': 'Order placed <b>' }]) expect(parseNow(headers({ ...ok, ...bad }))).toBeNull();
  });
});

