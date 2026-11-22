/** Every keyboard shortcut of the app, in one place (UI remodel, decision 8). The help sheet (`?`), the command bar and tooltips all read from here, and
 *  `shortcuts.test.ts` fails when two shortcuts share a key in the same place. Keys are written as the person presses them: "g i" is G then I, "mod+k" is Ctrl+K
 *  (Cmd+K on a Mac). Everything here can also be done with the pointer. */

export type Place = 'home' | 'chat' | 'inbox' | 'calendar' | 'files' | 'activity' | 'settings';
export const PLACES: Place[] = ['home', 'chat', 'inbox', 'calendar', 'files', 'activity', 'settings'];
export interface Shortcut { id: string; keys: string; name: string; group: 'Go to' | 'Frame' | 'Mail' | 'Calendar' | 'Help'; where: Place[] }
const ALL = PLACES;
const except = (...out: Place[]) => PLACES.filter(p => !out.includes(p));

export const SHORTCUTS: Shortcut[] = [
  { id: 'command', keys: 'mod+k', name: 'Search and commands', group: 'Frame', where: ALL },
  { id: 'command-slash', keys: '/', name: 'Search and commands', group: 'Frame', where: except('inbox') },
  { id: 'help', keys: '?', name: 'Keyboard shortcuts', group: 'Help', where: ALL },
  { id: 'context', keys: 'mod+b', name: 'Show or hide the side column', group: 'Frame', where: ALL },
  { id: 'assistant', keys: 'mod+j', name: 'Open or close the assistant', group: 'Frame', where: except('chat') },
  { id: 'zone-next', keys: 'f6', name: 'Move to the next zone', group: 'Frame', where: ALL },
  { id: 'zone-prev', keys: 'shift+f6', name: 'Move to the previous zone', group: 'Frame', where: ALL },
  { id: 'density', keys: 'shift+d', name: 'Switch between comfortable and compact', group: 'Frame', where: ALL },
  { id: 'go-home', keys: 'g h', name: 'Home', group: 'Go to', where: ALL },
  { id: 'go-chat', keys: 'g c', name: 'Chat', group: 'Go to', where: ALL },
  { id: 'go-inbox', keys: 'g i', name: 'Inbox', group: 'Go to', where: ALL },
  { id: 'go-calendar', keys: 'g l', name: 'Calendar', group: 'Go to', where: ALL },
  { id: 'go-files', keys: 'g f', name: 'Files', group: 'Go to', where: ALL },
  { id: 'go-activity', keys: 'g a', name: 'Activity', group: 'Go to', where: ALL },
  { id: 'go-settings', keys: 'g s', name: 'Settings', group: 'Go to', where: ALL },
  { id: 'mail-next', keys: 'j', name: 'Next thread', group: 'Mail', where: ['inbox'] },
  { id: 'mail-prev', keys: 'k', name: 'Previous thread', group: 'Mail', where: ['inbox'] },
  { id: 'mail-pick', keys: 'x', name: 'Select the open thread', group: 'Mail', where: ['inbox'] },
  { id: 'mail-search', keys: '/', name: 'Search mail', group: 'Mail', where: ['inbox'] },
  { id: 'mail-close', keys: 'escape', name: 'Close the thread', group: 'Mail', where: ['inbox'] },
  { id: 'mail-compose', keys: 'c', name: 'Write a new message', group: 'Mail', where: ['inbox'] },
  { id: 'mail-reply', keys: 'r', name: 'Reply', group: 'Mail', where: ['inbox'] },
  { id: 'mail-reply-all', keys: 'a', name: 'Reply to everyone', group: 'Mail', where: ['inbox'] },
  { id: 'mail-forward', keys: 'f', name: 'Forward', group: 'Mail', where: ['inbox'] },
  { id: 'mail-archive', keys: 'e', name: 'Archive, or move back to the inbox', group: 'Mail', where: ['inbox'] },
  { id: 'mail-bin', keys: '#', name: 'Move to the bin', group: 'Mail', where: ['inbox'] },
  { id: 'mail-star', keys: 's', name: 'Star, or remove the star', group: 'Mail', where: ['inbox'] },
  { id: 'mail-unread', keys: 'u', name: 'Mark as unread', group: 'Mail', where: ['inbox'] },
  { id: 'cal-today', keys: 't', name: 'Today', group: 'Calendar', where: ['calendar'] },
  { id: 'cal-earlier', keys: 'arrowleft', name: 'Earlier', group: 'Calendar', where: ['calendar'] },
  { id: 'cal-later', keys: 'arrowright', name: 'Later', group: 'Calendar', where: ['calendar'] },
  { id: 'cal-extend', keys: 'shift+arrowright', name: 'On a day heading: choose a range of days', group: 'Calendar', where: ['calendar'] },
  { id: 'cal-close', keys: 'escape', name: 'Close the event, or clear the chosen days', group: 'Calendar', where: ['calendar'] },
];

const isMac = () => typeof navigator !== 'undefined' && /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent);
const WORDS: Record<string, string> = { mod: '', shift: 'Shift', escape: 'Esc', arrowleft: '←', arrowright: '→', f6: 'F6', '?': '?', '/': '/', '#': '#' };
/** How a shortcut is shown: "Ctrl K" (or "⌘ K"), "G then I". */
export function keyWords(keys: string): string {
  return keys.split(' ').map(step => step.split('+').map(k => (k === 'mod' ? (isMac() ? '⌘' : 'Ctrl') : WORDS[k] ?? k.toUpperCase())).join(' ')).join(' then ');
}
export const shortcut = (id: string) => SHORTCUTS.find(s => s.id === id);
/** A tooltip with the shortcut: "Inbox (G then I)". */
export const hint = (label: string, id: string) => { const s = shortcut(id); return s ? `${label} (${keyWords(s.keys)})` : label; };
export const forPlace = (place: Place) => SHORTCUTS.filter(s => s.where.includes(place));

/** Does this key event press this one-step shortcut? ("mod+k", "shift+d", "f6", "?"). */
export function presses(e: Pick<KeyboardEvent, 'key' | 'metaKey' | 'ctrlKey' | 'shiftKey' | 'altKey'>, keys: string): boolean {
  const parts = keys.split('+'); const key = parts[parts.length - 1]; const mod = parts.includes('mod'); const shift = parts.includes('shift');
  if (mod !== (e.metaKey || e.ctrlKey) || e.altKey) return false;
  if (key === '?' || key === '/') return e.key === key;           // the character itself, whatever Shift took to type it
  return e.key.toLowerCase() === key && shift === e.shiftKey;
}
/** Two shortcuts in the same place with the same keys. Empty when the registry is sound. */
export function clashes(list: Shortcut[] = SHORTCUTS): string[] {
  const out: string[] = [];
  for (let i = 0; i < list.length; i++) for (let j = i + 1; j < list.length; j++)
    if (list[i].keys === list[j].keys && list[i].where.some(p => list[j].where.includes(p))) out.push(`${list[i].id} and ${list[j].id} both use ${list[i].keys}`);
  return out;
}
export function placeOf(path: string): Place {
  if (path.startsWith('/home')) return 'home';
  if (path.startsWith('/inbox')) return 'inbox';
  if (path.startsWith('/calendar')) return 'calendar';
  if (path.startsWith('/files')) return 'files';
  if (path.startsWith('/activity') || path.startsWith('/tasks') || path.startsWith('/live') || path.startsWith('/automations')) return 'activity';
  if (path.startsWith('/settings') || path.startsWith('/integrations')) return 'settings';
  return 'chat';
}
