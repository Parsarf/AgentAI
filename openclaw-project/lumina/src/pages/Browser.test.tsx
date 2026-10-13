import { describe, expect, it } from 'vitest';
import { stepText, toBrowser } from './Browser';

describe('browser page helpers', () => {
  it('maps a click on the scaled screenshot into the 1280x800 browser window', () => {
    expect(toBrowser(150, 120, { left: 100, top: 100, width: 640, height: 400 })).toEqual({ x: 100, y: 40 });
    expect(toBrowser(740, 500, { left: 100, top: 100, width: 640, height: 400 })).toEqual({ x: 1280, y: 800 });
  });
  it('hides screenshot events from the step list and names unlabeled steps', () => {
    expect(stepText({ n: 1, kind: 'screenshot', file: 'shot-001.jpg' })).toBeNull();
    expect(stepText({ n: 2, kind: 'step', summary: 'Opened shop' })).toBe('Opened shop');
    expect(stepText({ n: 3, kind: 'step' })).toBe('Acted on the page');
  });
});
