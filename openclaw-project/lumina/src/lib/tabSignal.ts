/** What the browser tab says while the app is not being looked at (reliability plan, Part 5): that something needs the person, or that what they were waiting for is done.
 *  Both come from the shared task state; nothing is counted or guessed here beyond it. */
export type TabSignal = 'none' | 'needs_you' | 'done';

export const TAB_NAME = 'Lumina';
export function tabTitle(signal: TabSignal, waiting = 0): string {
  if (signal === 'needs_you') return `${waiting > 1 ? `(${waiting}) ` : ''}Needs you · ${TAB_NAME}`;
  return signal === 'done' ? `Done · ${TAB_NAME}` : TAB_NAME;
}

const MARK = { none: '', needs_you: '<circle cx="24" cy="8" r="7" fill="#d97706" stroke="#fff" stroke-width="2"/>', done: '<circle cx="24" cy="8" r="7" fill="#16a34a" stroke="#fff" stroke-width="2"/>' };
/** The tab's icon: the same mark, with a dot whose colour AND presence carry the signal (amber: needs you; green: done). */
export function tabIcon(signal: TabSignal): string {
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"><circle cx="16" cy="16" r="13" fill="#1f2937"/><circle cx="16" cy="16" r="6" fill="#f9fafb"/>${MARK[signal]}</svg>`;
  return `data:image/svg+xml,${encodeURIComponent(svg)}`;
}

/** Which signal to show. `needs` is how many tasks wait for the person; `finishedUnseen` is true from the moment a task they had going ended while the tab was hidden
 *  until they look at the tab again. Needing them comes first: it is the one they can act on. */
export const tabSignal = (needs: number, finishedUnseen: boolean): TabSignal => (needs > 0 ? 'needs_you' : finishedUnseen ? 'done' : 'none');
