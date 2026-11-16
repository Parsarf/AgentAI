// The mail and calendar dashboard's data and its small pure helpers (roadmap #D3, #D4). Nothing in here, or in the pages built on it, names a provider: what differs between
// providers arrives as `capabilities` and is read as data.
import { api, ApiError } from './api';

export interface Person { name: string; address: string }
export interface HubCaps { mail: boolean; calendar: boolean; mail_search: boolean; incremental: boolean; push: boolean; labels: 'labels' | 'folders' | 'none'; subjects: boolean;
  send: boolean; organize: boolean; mark_read: boolean; event_write: boolean; respond: boolean }
export interface SyncPart { synced_epoch: number | null; filled: boolean; items: number; error: string | null; paused: boolean }
export interface HubAccount { id: string; provider: string; provider_label: string; identity: string; state: 'working' | 'needs_you'; needs_reason: string | null;
  capabilities: HubCaps; granted: { mail: boolean; calendar: boolean }; mail: SyncPart | null; calendar: SyncPart | null }
export interface ProviderLabel { id: string; name: string }
export interface Thread { connection_id: string; id: string; subject: string; snippet: string; people: Person[]; last_epoch: number; message_count: number; unread: boolean;
  starred: boolean; has_attachments: boolean; labels: string[]; provider_labels: ProviderLabel[] }
export interface Attachment { id: string; name: string; type: string; size: number }
export interface Body { html: string; text: string; blocked_images: number; images_shown: boolean; attachments: Attachment[]; fetched_epoch: number }
export interface Message { id: string; thread_id: string; subject: string; snippet: string; sender: Person; to: Person[]; cc: Person[]; sent_epoch: number; labels: string[];
  provider_labels: ProviderLabel[]; unread: boolean; starred: boolean; has_attachments: boolean; body: Body | null }
export interface HubCalendar { connection_id: string; id: string; name: string; colour: string; timezone: string | null; access: 'busy' | 'read' | 'write' | 'owner'; primary: boolean;
  selected: boolean; synced_epoch: number | null; filled: boolean; error: string | null; paused: boolean }
export interface HubEvent { connection_id: string; calendar_id: string; id: string; series_id: string | null; title: string; busy_only: boolean; start_epoch: number; end_epoch: number;
  all_day: boolean; start_date: string | null; end_date: string | null; timezone: string | null; place: string; conference_url: string | null; my_response: string | null;
  exception: boolean; cancelled: boolean; visibility: string; colour: string;
  description?: string; organizer?: Person | null; attendees?: (Person & { response: string; self: boolean; optional: boolean })[]; provider_url?: string | null; synced_epoch?: number | null }
export interface Overview { accounts: HubAccount[]; settings: { timezone: string | null; image_senders: string[] }; counts: { unread: number; by_account: Record<string, number> };
  calendars: HubCalendar[]; labels: string[]; colours: string[]; read_only: boolean }
export interface ThreadFilters { label: string; accounts?: string[]; provider_label?: string; unread?: boolean; attachments?: boolean; q?: string; cursor?: string; limit?: number }
export interface Page { count: number; complete: boolean; total_estimate: number | null; continuation: string | null; stopped_by: string | null }

const query = (values: Record<string, string | number | boolean | undefined | null>) => {
  const out = new URLSearchParams();
  for (const [key, value] of Object.entries(values)) if (value !== undefined && value !== null && value !== '' && value !== false) out.set(key, value === true ? '1' : String(value));
  const text = out.toString();
  return text ? '?' + text : '';
};

export const hub = {
  overview: () => api<Overview>('GET', '/v1/hub'),
  threads: (f: ThreadFilters) => api<{ threads: Thread[]; next: string | null; complete: boolean }>('GET', '/v1/hub/mail/threads' + query({ label: f.label, accounts: f.accounts?.join(','),
    provider_label: f.provider_label, unread: f.unread, attachments: f.attachments, q: f.q, cursor: f.cursor, limit: f.limit })),
  labels: () => api<{ labels: { connection_id: string; labels: (ProviderLabel & { threads: number })[] }[] }>('GET', '/v1/hub/mail/labels'),
  thread: (connection: string, id: string, images = false) => api<{ thread: Thread; messages: Message[]; problem: string | null }>('GET', '/v1/hub/mail/thread' + query({ connection, id, images })),
  message: (connection: string, id: string, images = false) => api<{ message: Message; problem: string | null }>('GET', '/v1/hub/mail/message' + query({ connection, id, images })),
  searchOlder: (connection: string, q: string, continuation?: string | null) =>
    api<{ messages: (Omit<Message, 'body'> & { connection_id: string })[]; problem: string | null; page: Page | null }>('GET', '/v1/hub/mail/search-older' + query({ connection, q, continuation })),
  events: (start: number, end: number, accounts?: string[]) => api<{ events: HubEvent[]; complete: boolean }>('GET', '/v1/hub/events' + query({ start, end, accounts: accounts?.join(',') })),
  event: (connection: string, calendar: string, id: string) => api<{ event: HubEvent }>('GET', '/v1/hub/event' + query({ connection, calendar, id })),
  searchEvents: (q: string) => api<{ events: HubEvent[]; complete: boolean }>('GET', '/v1/hub/events/search' + query({ q })),
  setCalendar: (connection_id: string, calendar_id: string, change: { selected?: boolean; colour?: string }) => api<{ calendars: HubCalendar[] }>('POST', '/v1/hub/calendars', { connection_id, calendar_id, ...change }),
  setSettings: (change: { timezone?: string | null; allow_images_from?: string; block_images_from?: string }) => api<{ settings: Overview['settings'] }>('POST', '/v1/hub/settings', change),
  refresh: (connection_id?: string) => api<{ requested: number }>('POST', '/v1/hub/refresh', connection_id ? { connection_id } : {}),
};

/** A plain sentence for each of the connector layer's fault kinds, for a customer. Never a provider's own text. */
export const PROBLEM: Record<string, string> = {
  retry_later: 'The mail service is busy right now. Try again in a moment.',
  needs_customer: 'This account needs you: reconnect it to carry on.',
  refused: 'This account is not allowed to do that.',
  not_found: 'That is no longer there.',
  conflict: 'That changed in the meantime. Refresh and try again.',
  invalid: 'That could not be read.',
  unsupported: 'This account cannot search older mail.',
};
export const problemWords = (kind: string | null | undefined) => (kind ? PROBLEM[kind] ?? 'That did not work. Try again.' : '');
export const failed = (error: unknown) => (error instanceof ApiError && error.status === 503 && error.code === 'feature_off' ? 'Mail and Calendar are not switched on.' :
  error instanceof ApiError && error.code.startsWith('connector_') ? problemWords(error.code.slice(10)) : 'That did not work. Try again.');

export const LABEL_WORDS: Record<string, string> = { inbox: 'Inbox', starred: 'Starred', sent: 'Sent', drafts: 'Drafts', archive: 'Archive', all: 'All mail', spam: 'Spam', trash: 'Trash', unread: 'Unread' };
export const LIST_ORDER = ['inbox', 'starred', 'sent', 'drafts', 'archive', 'all', 'spam', 'trash'];

export const personName = (p: Person) => p.name || p.address;
/** Who a thread is with, as the list shows it: everyone but the account's own address, the first two by name and then a count. */
export function people(list: Person[], own?: string): string {
  const others = list.filter(p => !own || p.address !== own.toLowerCase());
  const shown = (others.length ? others : list).map(personName);
  return shown.length <= 2 ? shown.join(', ') : `${shown[0]}, ${shown[1]} +${shown.length - 2}`;
}
export const fileSize = (bytes: number) => (bytes >= 1048576 ? `${(bytes / 1048576).toFixed(1)} MB` : bytes >= 1024 ? `${Math.round(bytes / 1024)} KB` : `${bytes} B`);

/** "just now", "5 min ago", "3 h ago", "2 days ago": how old a sync is. */
export function ago(epoch: number | null | undefined, now: number): string {
  if (!epoch) return 'not yet';
  const s = Math.max(0, now - epoch);
  if (s < 90) return 'just now';
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400 * 2) return `${Math.round(s / 3600)} h ago`;
  return `${Math.round(s / 86400)} days ago`;
}

// -- time in a timezone, with the platform's own calendar data (no library) --------------------------------------------------------------------------------
export const browserZone = () => { try { return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC'; } catch { return 'UTC'; } };
export const validZone = (zone: string) => { try { new Intl.DateTimeFormat('en-US', { timeZone: zone }); return true; } catch { return false; } };

interface Parts { year: number; month: number; day: number; hour: number; minute: number }
const formatters = new Map<string, Intl.DateTimeFormat>();
function parts(epoch: number, zone: string): Parts {
  let f = formatters.get(zone);
  if (!f) { f = new Intl.DateTimeFormat('en-CA', { timeZone: zone, year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }); formatters.set(zone, f); }
  const out: Record<string, number> = {};
  for (const p of f.formatToParts(new Date(epoch * 1000))) if (p.type !== 'literal') out[p.type] = Number(p.value);
  return { year: out.year, month: out.month, day: out.day, hour: out.hour % 24, minute: out.minute };
}
const pad = (n: number) => String(n).padStart(2, '0');
const key = (p: { year: number; month: number; day: number }) => `${p.year}-${pad(p.month)}-${pad(p.day)}`;

/** The calendar day ('YYYY-MM-DD') an instant falls on in a timezone. */
export const dayKey = (epoch: number, zone: string) => key(parts(epoch, zone));
/** Minutes since that day's midnight, in the timezone. */
export const minuteOfDay = (epoch: number, zone: string) => { const p = parts(epoch, zone); return p.hour * 60 + p.minute; };
/** The instant a wall-clock time happens in a timezone (the first one, where a clock change makes it happen twice; the next valid one, where it does not exist). */
export function zonedEpoch(day: string, minutes: number, zone: string): number {
  const [y, m, d] = day.split('-').map(Number);
  const wall = Date.UTC(y, m - 1, d, 0, minutes) / 1000;
  let guess = wall;
  for (let i = 0; i < 3; i++) {
    const p = parts(guess, zone);
    const shown = Date.UTC(p.year, p.month - 1, p.day, p.hour, p.minute) / 1000;
    if (shown === wall) break;
    guess += wall - shown;
  }
  return guess;
}
export function addDays(day: string, n: number): string {
  const [y, m, d] = day.split('-').map(Number);
  const t = new Date(Date.UTC(y, m - 1, d + n));
  return key({ year: t.getUTCFullYear(), month: t.getUTCMonth() + 1, day: t.getUTCDate() });
}
export const weekday = (day: string) => { const [y, m, d] = day.split('-').map(Number); return new Date(Date.UTC(y, m - 1, d)).getUTCDay(); };     // 0 = Sunday
export const startOfWeek = (day: string, firstDay = 1) => addDays(day, -((weekday(day) - firstDay + 7) % 7));
export const startOfMonth = (day: string) => day.slice(0, 8) + '01';
export function addMonths(day: string, n: number): string {
  const [y, m] = day.split('-').map(Number);
  const t = new Date(Date.UTC(y, m - 1 + n, 1));
  return key({ year: t.getUTCFullYear(), month: t.getUTCMonth() + 1, day: 1 });
}
const dateOf = (day: string) => { const [y, m, d] = day.split('-').map(Number); return new Date(Date.UTC(y, m - 1, d, 12)); };
export const dayTitle = (day: string, style: 'long' | 'short' | 'weekday' | 'month' = 'long') => new Intl.DateTimeFormat('en-US', { timeZone: 'UTC',
  ...(style === 'long' ? { weekday: 'long', month: 'long', day: 'numeric', year: 'numeric' } : style === 'short' ? { weekday: 'short', day: 'numeric' }
    : style === 'weekday' ? { weekday: 'short' } : { month: 'long', year: 'numeric' }) }).format(dateOf(day));
export const clock = (epoch: number, zone: string) => new Intl.DateTimeFormat('en-US', { timeZone: zone, hour: 'numeric', minute: '2-digit' }).format(new Date(epoch * 1000));
/** When a message arrived, as a list shows it: the time today, the weekday this week, else the date. */
export function listTime(epoch: number, zone: string, now: number): string {
  const today = dayKey(now, zone), day = dayKey(epoch, zone);
  if (day === today) return clock(epoch, zone);
  if (day > addDays(today, -7)) return dayTitle(day, 'weekday');
  return new Intl.DateTimeFormat('en-US', { timeZone: 'UTC', month: 'short', day: 'numeric', ...(day.slice(0, 4) === today.slice(0, 4) ? {} : { year: 'numeric' }) }).format(dateOf(day));
}
export const fullTime = (epoch: number, zone: string) => new Intl.DateTimeFormat('en-US', { timeZone: zone, weekday: 'short', month: 'short', day: 'numeric', year: 'numeric', hour: 'numeric', minute: '2-digit' }).format(new Date(epoch * 1000));
/** When an event happens, in words, in the customer's timezone; its own timezone is added when it differs. */
export function eventTime(e: HubEvent, zone: string): string {
  if (e.all_day && e.start_date && e.end_date) {
    const last = addDays(e.end_date, -1);
    return last <= e.start_date ? `${dayTitle(e.start_date)}, all day` : `${dayTitle(e.start_date)} to ${dayTitle(last)}`;
  }
  const first = dayKey(e.start_epoch, zone), last = dayKey(e.end_epoch, zone);
  const base = first === last ? `${dayTitle(first)}, ${clock(e.start_epoch, zone)} to ${clock(e.end_epoch, zone)}` : `${fullTime(e.start_epoch, zone)} to ${fullTime(e.end_epoch, zone)}`;
  return e.timezone && e.timezone !== zone && validZone(e.timezone) && minuteOfDay(e.start_epoch, e.timezone) !== minuteOfDay(e.start_epoch, zone)
    ? `${base} (${clock(e.start_epoch, e.timezone)} in ${e.timezone.replace(/_/g, ' ')})` : base;
}

// -- placing events ----------------------------------------------------------------------------------------------------------------------------------------
/** The days ('YYYY-MM-DD') an event is drawn on, within [from, to]. An all-day event uses its own dates (a date has no timezone); a timed one the customer's timezone. */
export function eventDays(e: HubEvent, zone: string, from: string, to: string): string[] {
  let first: string, last: string;
  if (e.all_day && e.start_date && e.end_date) { first = e.start_date; last = addDays(e.end_date, -1); if (last < first) last = first; }
  else { first = dayKey(e.start_epoch, zone); last = dayKey(Math.max(e.start_epoch, e.end_epoch - 1), zone); }
  const out: string[] = [];
  for (let day = first < from ? from : first; day <= last && day <= to; day = addDays(day, 1)) out.push(day);
  return out;
}
export interface Placed { event: HubEvent; top: number; height: number; column: number; columns: number }
/** Timed events of one day, laid out so that overlapping ones sit side by side and none is hidden. `top` and `height` are minutes from that day's midnight. */
export function layoutDay(events: HubEvent[], day: string, zone: string): Placed[] {
  const start = zonedEpoch(day, 0, zone), end = zonedEpoch(addDays(day, 1), 0, zone);
  const items = events.filter(e => !e.all_day && e.start_epoch < end && e.end_epoch > start)
    .map(e => { const from = Math.max(e.start_epoch, start), to = Math.min(Math.max(e.end_epoch, e.start_epoch + 900), end);
      return { event: e, from, to, top: Math.round((from - start) / 60), height: Math.max(20, Math.round((to - from) / 60)), column: 0, columns: 1 }; })
    .sort((a, b) => a.from - b.from || b.to - a.to);
  let group: typeof items = [], groupEnd = 0;
  const close = () => { const width = Math.max(0, ...group.map(i => i.column)) + 1; group.forEach(i => { i.columns = width; }); group = []; };
  for (const item of items) {
    if (group.length && item.from >= groupEnd) close();
    const used = new Set(group.filter(g => g.to > item.from).map(g => g.column));
    let column = 0; while (used.has(column)) column++;
    item.column = column; group.push(item); groupEnd = Math.max(groupEnd, item.to);
  }
  if (group.length) close();
  return items.map(({ event, top, height, column, columns }) => ({ event, top, height, column, columns }));
}
export const eventKey = (e: { connection_id: string; calendar_id: string; id: string }) => `${e.connection_id}\u0000${e.calendar_id}\u0000${e.id}`;
export const threadKey = (t: { connection_id: string; id: string }) => `${t.connection_id}\u0000${t.id}`;
