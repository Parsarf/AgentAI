/** What the browser tab says while the app is not being looked at (reliability plan, Part 5): that something needs the person, or that what they were waiting for is done.
 *  Both come from the shared task state; nothing is counted or guessed here beyond it. */
export type TabSignal = 'none' | 'needs_you' | 'done';

export const TAB_NAME = 'Lumina';
export function tabTitle(signal: TabSignal, waiting = 0): string {
  if (signal === 'needs_you') return `${waiting > 1 ? `(${waiting}) ` : ''}Needs you · ${TAB_NAME}`;
  return signal === 'done' ? `Done · ${TAB_NAME}` : TAB_NAME;
}

/** A colour of the design system, read from the page's own tokens (src/styles/tokens.css) so the icon follows the theme; the plain colour name is only for a page that has
 *  no tokens (a test). */
const token = (name: string, plain: string) => (typeof document === 'undefined' ? '' : getComputedStyle(document.documentElement).getPropertyValue(name).trim()) || plain;
/** The tab's icon: the same mark, with a dot whose presence AND colour carry the signal (the warning colour: needs you; the success colour: done). */
export function tabIcon(signal: TabSignal): string {
  const ring = token('--surface-base', 'white');
  const dot = signal === 'none' ? '' : `<circle cx="24" cy="8" r="7" fill="${signal === 'needs_you' ? token('--warning', 'orange') : token('--success', 'green')}" stroke="${ring}" stroke-width="2"/>`;
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"><circle cx="16" cy="16" r="13" fill="${token('--accent', 'slateblue')}"/><circle cx="16" cy="16" r="5" fill="${token('--text-primary', 'white')}"/>${dot}</svg>`;
  return `data:image/svg+xml,${encodeURIComponent(svg)}`;
}

/** Which signal to show. `needs` is how many tasks wait for the person; `finishedUnseen` is true from the moment a task they had going ended while the tab was hidden
 *  until they look at the tab again. Needing them comes first: it is the one they can act on. */
export const tabSignal = (needs: number, finishedUnseen: boolean): TabSignal => (needs > 0 ? 'needs_you' : finishedUnseen ? 'done' : 'none');
