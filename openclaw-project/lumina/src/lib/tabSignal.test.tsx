import { afterEach, describe, expect, it } from 'vitest';
import { act, cleanup, render } from '@testing-library/react';
import { tabIcon, tabSignal, tabTitle } from './tabSignal';
import { useTabSignal } from './useTabSignal';
import { summary } from '../test/workMock';
import type { TaskSummary } from './work';

const Probe = ({ tasks }: { tasks: TaskSummary[] }) => { useTabSignal(tasks); return null; };
const hide = (hidden: boolean) => act(() => { Object.defineProperty(document, 'hidden', { configurable: true, value: hidden }); document.dispatchEvent(new Event('visibilitychange')); });
afterEach(() => { cleanup(); hide(false); document.querySelector('link[rel="icon"]')?.remove(); });

describe('what the tab says', () => {
  it('names what needs the person first, then what finished, in words and in the icon', () => {
    expect([tabSignal(0, false), tabSignal(2, false), tabSignal(1, true), tabSignal(0, true)]).toEqual(['none', 'needs_you', 'needs_you', 'done']);
    expect([tabTitle('none'), tabTitle('needs_you', 1), tabTitle('needs_you', 3), tabTitle('done')]).toEqual(['Lumina', 'Needs you · Lumina', '(3) Needs you · Lumina', 'Done · Lumina']);
    expect(new Set([tabIcon('none'), tabIcon('needs_you'), tabIcon('done')]).size).toBe(3);
    expect(decodeURIComponent(tabIcon('none'))).not.toContain('cx="24"');                      // no dot when there is nothing to say
  });
  it('says "needs you" while a task waits for the person and goes back when it no longer does', () => {
    const { rerender } = render(<Probe tasks={[summary({ id: 'a', phase: 'needs_you', attention: 'approval' })]} />);
    expect(document.title).toBe('Needs you · Lumina');
    expect(document.querySelector<HTMLLinkElement>('link[rel="icon"]')!.href).toBe(tabIcon('needs_you'));
    rerender(<Probe tasks={[summary({ id: 'a', phase: 'working' })]} />);
    expect(document.title).toBe('Lumina');
  });
  it('says "done" when a task that was going ended while the tab was hidden, until the tab is looked at', () => {
    const { rerender } = render(<Probe tasks={[summary({ id: 'a', phase: 'working' })]} />);
    hide(true);
    rerender(<Probe tasks={[summary({ id: 'a', phase: 'ended', outcome: 'completed' })]} />);
    expect(document.title).toBe('Done · Lumina');
    hide(false);
    expect(document.title).toBe('Lumina');
  });
  it('says nothing for a task that ended while the person was looking, or one that was already over', () => {
    const { rerender } = render(<Probe tasks={[summary({ id: 'a', phase: 'working' }), summary({ id: 'old', phase: 'ended', outcome: 'completed' })]} />);
    rerender(<Probe tasks={[summary({ id: 'a', phase: 'ended', outcome: 'completed' }), summary({ id: 'old', phase: 'ended', outcome: 'completed' })]} />);
    expect(document.title).toBe('Lumina');
    hide(true);
    rerender(<Probe tasks={[summary({ id: 'a', phase: 'ended', outcome: 'completed' }), summary({ id: 'old', phase: 'ended', outcome: 'completed' })]} />);
    expect(document.title).toBe('Lumina');
  });
});
