// The mail and calendar dashboard's data and its small pure helpers (roadmap #D3, #D4). Nothing in here, or in the pages built on it, names a provider: what differs between
// providers arrives as `capabilities` and is read as data.
import { api, ApiError } from './api';

export interface Person { name: string; address: string }
export interface HubCaps { mail: boolean; calendar: boolean; mail_search: boolean; incremental: boolean; push: boolean; labels: 'labels' | 'folders' | 'none'; subjects: boolean;
  send: boolean; organize: boolean; mark_read: boolean; event_write: boolean; respond: boolean; attachments?: boolean; compose_link?: boolean; free_busy?: boolean;
  /** change an event (time, title, place, notes, people); change or cancel part of a repeating series (Phase 6, #62) */
  event_change?: boolean; event_series?: boolean;
  /** capability -> the permission to ask for (Phase 6): the provider can, this account has not allowed it yet */
  missing?: Record<string, string> }
/** A permission to change things, asked for on first use (Phase 6): the same names for every provider. */
export interface HubGrant { name: string; capabilities: string[]; words: string }
export interface SyncPart { synced_epoch: number | null; filled: boolean; items: number; error: string | null; paused: boolean }
export interface HubAccount { id: string; provider: string; provider_label: string; identity: string; state: 'working' | 'needs_you'; needs_reason: string | null;
  capabilities: HubCaps; grants?: HubGrant[]; granted: { mail: boolean; calendar: boolean }; mail: SyncPart | null; calendar: SyncPart | null }
export interface ProviderLabel { id: string; name: string }
export interface Thread { connection_id: string; id: string; subject: string; snippet: string; people: Person[]; last_epoch: number; message_count: number; unread: boolean;
  starred: boolean; has_attachments: boolean; labels: string[]; provider_labels: ProviderLabel[] }
export interface Attachment { id: string; name: string; type: string; size: number }
/** `designed`: the message sets a background of its own, so it is shown as sent on a light page; otherwise it is shown in the theme. `quoted`: earlier messages under it were folded. */
export interface Body { html: string; text: string; blocked_images: number; images_shown: boolean; designed?: boolean; quoted?: boolean; attachments: Attachment[]; fetched_epoch: number }
export interface Message { id: string; thread_id: string; subject: string; snippet: string; sender: Person; to: Person[]; cc: Person[]; sent_epoch: number; labels: string[];
  provider_labels: ProviderLabel[]; unread: boolean; starred: boolean; has_attachments: boolean; body: Body | null }
export interface HubCalendar { connection_id: string; id: string; name: string; colour: string; timezone: string | null; access: 'busy' | 'read' | 'write' | 'owner'; primary: boolean;
  selected: boolean; synced_epoch: number | null; filled: boolean; error: string | null; paused: boolean }
export interface HubEvent { connection_id: string; calendar_id: string; id: string; series_id: string | null; title: string; busy_only: boolean; start_epoch: number; end_epoch: number;
  all_day: boolean; start_date: string | null; end_date: string | null; timezone: string | null; place: string; conference_url: string | null; my_response: string | null;
  exception: boolean; cancelled: boolean; visibility: string; colour: string;
  description?: string; organizer?: Person | null; attendees?: (Person & { response: string; self: boolean; optional: boolean })[]; provider_url?: string | null; synced_epoch?: number | null }
/** The customer's own mail settings (#D6, #66): Undo send's wait, marking read at the provider on open, and their own sending limits (allowed: what applies now). */
export interface MailSettings { undo_send_seconds: number; mark_read_on_open: boolean; limits: { recipients?: number; per_hour?: number }; allowed: { recipients: number; per_hour: number };
  platform: { recipients: number; per_hour: number } }
export type OrganizeOp = 'archive' | 'inbox' | 'star' | 'unstar' | 'read' | 'unread' | 'label' | 'unlabel' | 'move' | 'trash' | 'untrash';
/** A mail and calendar service that can be connected. `kinds`: the kinds of account it signs in separately (a personal or a work account), chosen before going there. */
export interface Provider { provider: string; label: string; kinds?: { id: string; label: string }[] }
export interface Overview { accounts: HubAccount[]; providers?: Provider[]; settings: { timezone: string | null; image_senders: string[]; mail?: MailSettings }; counts: { unread: number; by_account: Record<string, number> };
  calendars: HubCalendar[]; labels: string[]; colours: string[]; read_only: boolean; feeds?: boolean }
/** A change in a connected account, as the action pipeline reports it (Phase 6). `direct` is the screen when the customer made it with their own hand. */
export interface HubAction { id: string; kind: string; state: string; preview: { title: string; summary: string; destination: string; changes: { field: string; before: unknown; after: unknown }[]; can_undo: boolean };
  verified: boolean | null; can_undo: boolean; undo_until_epoch: number | null; direct: string | null; ended_words: string }
/** How much of a repeating series a change touches (#62): always chosen by the customer, never guessed. */
export type Scope = 'this' | 'following' | 'all';
export interface EventChange { connection: string; calendar: string; event: string; series?: string | null; scope?: Scope; title?: string; start?: string; end?: string; all_day?: boolean;
  timezone?: string; place?: string; description?: string; attendees?: string[]; notify?: boolean }
/** Times the assistant found for a meeting (#65), drawn on the Calendar for the customer to pick. */
export interface MeetingProposal { id: string; connection_id: string; title: string; minutes: number; attendees: string[]; external: string[];
  options: { start: string; end: string; start_epoch: number; end_epoch: number }[]; waiting: boolean }
export interface NewEvent { connection: string; calendar: string; title: string; start: string; end: string; all_day?: boolean; attendees?: string[]; place?: string; description?: string; notify?: boolean }
/** A mail draft kept in Lumina (#57): never in the mailbox. The customer sends it themselves from their mail service. */
export interface Draft { id: string; account: string; thread: string | null; to: string[]; cc: string[]; subject: string; body: string; origin: 'customer' | 'assistant';
  created_epoch: number; updated_epoch: number }
export type DraftChange = { draft?: string; connection_id?: string; thread_id?: string | null; to?: string[]; cc?: string[]; subject?: string; body?: string };
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
  setSettings: (change: { timezone?: string | null; allow_images_from?: string; block_images_from?: string; mail?: Partial<Pick<MailSettings, 'undo_send_seconds' | 'mark_read_on_open'>> & { limits?: MailSettings['limits'] | null } }) =>
    api<{ settings: Overview['settings'] }>('POST', '/v1/hub/settings', change),
  sendDraft: (draft: string) => api<{ action: HubAction; undo_send_seconds: number }>('POST', '/v1/hub/mail/send', { draft }),
  checkDraft: (draft: string) => api<{ notes: string[]; limit?: string }>('GET', `/v1/hub/mail/check${query({ draft })}`),
  organize: (connection: string, threads: string[], op: OrganizeOp, label?: string) => api<{ action: HubAction }>('POST', '/v1/hub/mail/organize', { connection, threads, op, ...(label ? { label } : {}) }),
  stop: (action: string) => api<{ action: HubAction }>('POST', `/v1/hub/actions/${encodeURIComponent(action)}/stop`, {}),
  action: (action: string) => api<{ action: HubAction }>('GET', `/v1/actions/${encodeURIComponent(action)}`),
  refresh: (connection_id?: string) => api<{ requested: number }>('POST', '/v1/hub/refresh', connection_id ? { connection_id } : {}),
  drafts: (thread?: string) => api<{ drafts: Draft[] }>('GET', '/v1/hub/drafts' + query({ thread })),
  saveDraft: (change: DraftChange) => api<{ draft: Draft }>('POST', '/v1/hub/drafts', change),
  discardDraft: (id: string) => api<{ discarded: string }>('POST', `/v1/hub/drafts/${encodeURIComponent(id)}/discard`, {}),
  composeLink: (id: string) => api<{ draft: Draft; link: string | null }>('GET', `/v1/hub/drafts/${encodeURIComponent(id)}/compose`),
  // Phase 6: changing calendars. The customer's own press is the approval; each call goes through the action pipeline once.
  allow: (account: HubAccount, add: string[]) => api<{ authorize_url: string; expires_in: number }>('POST', '/v1/hub/link', { provider: account.provider, connection: account.id, add }),
  /** Begin signing in to a service (optionally one kind of account). Nothing is connected until the customer comes back. */
  connect: (provider: string, kind?: string) => api<{ authorize_url: string; expires_in: number }>('POST', '/v1/hub/link', { provider, ...(kind ? { kind } : {}) }),
  /** Sign in again to an account whose access ended: the same connection, its mail and what it was allowed are kept. */
  reconnect: (account: HubAccount) => api<{ authorize_url: string; expires_in: number }>('POST', '/v1/hub/link', { provider: account.provider, connection: account.id }),
  finishLink: (state: string, code: string) => api<{ connection_id: string }>('POST', '/v1/hub/link/finish', { state, code }),
  people: (q: string) => api<{ people: Person[] }>('GET', '/v1/hub/mail/people' + query({ q })),
  createEvent: (e: NewEvent) => api<{ action: HubAction }>('POST', '/v1/hub/events/create', e),
  cancelEvent: (connection: string, calendar: string, event: string, notify = true, scope?: Scope, series?: string | null) =>
    api<{ action: HubAction }>('POST', '/v1/hub/events/cancel', { connection, calendar, event, notify, ...(scope && series ? { scope, series } : {}) }),
  addFeed: (address: string, name?: string) => api<{ connection_id: string }>('POST', '/v1/hub/feeds', { address, ...(name ? { name } : {}) }),
  proposals: (start: number, end: number) => api<{ proposals: MeetingProposal[] }>('GET', `/v1/hub/proposals${query({ start, end })}`),
  closeProposal: (id: string, state: 'picked' | 'dismissed') => api<{ proposal: { id: string; state: string } }>('POST', `/v1/hub/proposals/${encodeURIComponent(id)}/close`, { state }),
  changeEvent: (change: EventChange) => api<{ action: HubAction }>('POST', '/v1/hub/events/change', { ...change, series: change.series || undefined, scope: change.series ? change.scope : undefined }),
  undo: (action: string, screen = 'calendar') => api<{ action: HubAction }>('POST', `/v1/hub/actions/${encodeURIComponent(action)}/undo`, { screen }),
  respondEvent: (connection: string, calendar: string, event: string, response: 'accepted' | 'tentative' | 'declined', scope?: 'this' | 'all', series?: string | null) =>
    api<{ action: HubAction }>('POST', '/v1/hub/events/respond', { connection, calendar, event, response, ...(scope && series ? { scope, series } : {}) }),
};

/** The page a message is shown in: served with its own content policy (the app's would refuse the message's styles and pictures), framed only by Lumina. */
export const frameUrl = (connection: string, id: string, images = false) => '/v1/hub/mail/frame' + query({ connection, id, images });
/** One attachment: a download, or (`inline`, pictures only) something to show. */
export const fileUrl = (connection: string, message: string, attachment: string, inline = false) => '/v1/hub/mail/file' + query({ connection, message, attachment, inline });
export const isPicture = (a: Attachment) => /^image\/(png|jpeg|gif|webp)$/i.test(a.type);

/** Why a sign-in connected nothing, in a sentence that says what to do. The keys are the server's reasons (connectors.LINK_REASONS and the return route's). */
export const LINK_WORDS: Record<string, string> = {
  declined: 'You did not give access, so nothing was connected.',
  expired: 'That sign-in was already used or took too long. Nothing was connected. Start again from "Add account".',
  admin_consent: 'Your organization lets only an administrator allow apps like Lumina. Ask your IT administrator to allow Lumina, then connect again.',
  provider_setup: 'The mail service refused Lumina itself, not your account. Nothing was connected, and trying again will not help until we fix it: please tell support.',
  provider_unreachable: 'The mail service did not answer. Nothing was connected. Try again in a minute.',
  provider_refused: 'The mail service refused this sign-in. Nothing was connected. Try again, or use a different account.',
  no_identity: 'The mail service did not say which account you signed in to. Nothing was connected. Try again.',
  unexpected_access: 'The mail service offered more access than Lumina asks for, so Lumina refused it. Nothing was connected.',
  no_access: 'The account was signed in, but without access to mail or calendars. Nothing was connected. Connect again and leave mail or calendars ticked.',
  different_account: 'You signed in as a different account than the one being changed. Nothing changed. Sign in with the same address.',
  interrupted: 'The sign-in was not finished at the mail service. Nothing was connected. Try again.',
  not_allowed: 'Your role in this organization does not allow connecting accounts.',
  failed: 'The account could not be connected. Nothing was connected. Try again.',
};
export const linkWords = (reason: string | null | undefined, reference?: string | null) => {
  const words = LINK_WORDS[reason ?? ''] ?? LINK_WORDS.failed;
  return reference && /^[A-Z]{3,10}\d{3,8}$/.test(reference) ? `${words} (Reference: ${reference}.)` : words;
};

/** Addresses typed in one box, split on commas, semicolons and spaces. */
export const addresses = (text: string) => text.split(/[\s,;]+/).map(a => a.trim()).filter(Boolean);
/** A reply's subject: "Re: " once, never twice. */
export const replySubject = (subject: string) => (/^re:/i.test(subject.trim()) ? subject.trim() : `Re: ${subject.trim()}`.trim());

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
  error instanceof ApiError && error.status === 429 ? 'Lumina was asked for too much in a short time. Wait a minute, then carry on.' :
  error instanceof ApiError && error.code.startsWith('connector_') ? problemWords(error.code.slice(10)) : 'That did not work. Try again.');

export const LABEL_WORDS: Record<string, string> = { inbox: 'Inbox', starred: 'Starred', sent: 'Sent', drafts: 'Drafts', archive: 'Archive', all: 'All mail', spam: 'Spam', trash: 'Bin', unread: 'Unread' };
export const LIST_ORDER = ['inbox', 'starred', 'sent', 'drafts', 'archive', 'all', 'spam', 'trash'];

export const personName = (p: Person) => p.name || p.address;
/** Who a thread is with, as the list shows it: everyone but the account's own address, the first two by name and then a count. */
export function people(list: Person[], own?: string): string {
  const others = list.filter(p => !own || p.address !== own.toLowerCase());
  const shown = (others.length ? others : list).map(personName);
  return shown.length <= 2 ? shown.join(', ') : `${shown[0]}, ${shown[1]} +${shown.length - 2}`;
}
/** Two letters for a person's mark: of their name, else of their address. */
export function initials(p: Person): string {
  const words = (p.name || p.address.split('@')[0] || '?').replace(/["'()<>]/g, '').split(/[\s._-]+/).filter(Boolean);
  const letters = words.length > 1 ? words[0][0] + words[words.length - 1][0] : (words[0] ?? '?').slice(0, 2);
  return letters.toUpperCase();
}
/** A steady number 0-5 from an address: which of the six quiet tints its mark gets (the same person always the same one). */
export function tint(address: string): number {
  let h = 0; for (let i = 0; i < address.length; i++) h = (h * 31 + address.charCodeAt(i)) >>> 0;
  return h % 6;
}
/** Who a message went to, as its header shows it: "me" for the account itself, first names for the rest, then a count. */
export function recipients(to: Person[], cc: Person[], own?: string): string {
  const mine = (own ?? '').toLowerCase();
  const names = [...to, ...cc].map(p => (mine && p.address.toLowerCase() === mine ? 'me' : (p.name || p.address).split(/[\s@]/)[0]));
  if (!names.length) return 'no one';
  return names.length <= 3 ? names.join(', ') : `${names.slice(0, 2).join(', ')} and ${names.length - 2} more`;
}
/** What a reply carries under the customer's own words: the message it answers, each line marked, as mail programs do. */
export function quoteOf(m: { sender: Person; sent_epoch: number; body: { text: string } | null; snippet: string }, zone: string, limit = 6000): string {
  const text = (m.body?.text || m.snippet || '').trim(); if (!text) return '';
  const cut = text.length > limit ? text.slice(0, limit) + '\n[...]' : text;
  return `\n\nOn ${fullTime(m.sent_epoch, zone)}, ${m.sender.name ? `${m.sender.name} <${m.sender.address}>` : m.sender.address} wrote:\n` + cut.split('\n').map(l => (l.startsWith('>') ? '>' + l : '> ' + l)).join('\n');
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
/** A moment as a time field holds it in this timezone: YYYY-MM-DDTHH:MM. */
export const localTime = (epoch: number, zone: string) => { const m = minuteOfDay(epoch, zone); return `${dayKey(epoch, zone)}T${String(Math.floor(m / 60)).padStart(2, '0')}:${String(m % 60).padStart(2, '0')}`; };
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
const wording = (day: string, options: Intl.DateTimeFormatOptions) => new Intl.DateTimeFormat('en-US', { timeZone: 'UTC', ...options }).format(dateOf(day));
/** A day in words. 'long': Wednesday, May 20, 2026. 'short': Wed 20. 'weekday': Wed. 'month': May 2026. */
export const dayTitle = (day: string, style: 'long' | 'short' | 'weekday' | 'month' = 'long') => (style === 'long' ? wording(day, { weekday: 'long', month: 'long', day: 'numeric', year: 'numeric' })
  : style === 'short' ? `${wording(day, { weekday: 'short' })} ${Number(day.slice(8))}` : style === 'weekday' ? wording(day, { weekday: 'short' }) : wording(day, { month: 'long', year: 'numeric' }));
/** A run of days in words: "May 18 to 24, 2026", "April 27 to May 3, 2026", "December 29, 2025 to January 4, 2026". */
export function rangeTitle(from: string, to: string): string {
  const month = (d: string) => wording(d, { month: 'long' }), year = (d: string) => d.slice(0, 4), date = (d: string) => Number(d.slice(8));
  if (year(from) !== year(to)) return `${month(from)} ${date(from)}, ${year(from)} to ${month(to)} ${date(to)}, ${year(to)}`;
  return from.slice(0, 7) === to.slice(0, 7) ? `${month(from)} ${date(from)} to ${date(to)}, ${year(to)}` : `${month(from)} ${date(from)} to ${month(to)} ${date(to)}, ${year(to)}`;
}
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
/** The list after the server's newest page was read again while the reader is further down it: the newest page as it is now, then what was already loaded below it.
 *  New mail joins at the top, what changed is shown as it is now, and nothing below is thrown away (the list keeps the reader's place when rows are added above).
 *  A conversation that was in the list within the newest page's span of time and is not in that page any more has left this mailbox (archived, moved or deleted
 *  somewhere else): it goes. `whole`: the newest page is the entire mailbox. */
export function mergeNewest(loaded: Thread[], newest: Thread[], whole: boolean): Thread[] {
  if (whole || !newest.length) return newest;
  const there = new Set(newest.map(threadKey)); const until = newest[newest.length - 1].last_epoch;
  return [...newest, ...loaded.filter(t => !there.has(threadKey(t)) && t.last_epoch <= until)];
}
export const eventKey = (e: { connection_id: string; calendar_id: string; id: string }) => `${e.connection_id}\u0000${e.calendar_id}\u0000${e.id}`;
export const threadKey = (t: { connection_id: string; id: string }) => `${t.connection_id}\u0000${t.id}`;
