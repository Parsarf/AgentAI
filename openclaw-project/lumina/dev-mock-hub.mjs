// Local-only mock data for the mail, calendar, files and search screens (imported by dev-mock.mjs). Never deployed. Synthetic people and addresses only.
// MOCK_THREADS sets the size of the mailbox (default 100000, for the virtualized list measurement).
const now = () => Math.floor(Date.now() / 1000);
const TOTAL = Number(process.env.MOCK_THREADS || 100000);
const NAMES = ['Ada Park', 'Ben Ortiz', 'Chen Wei', 'Dana Ruiz', 'Eli Novak', 'Fay Osei', 'Gus Lind', 'Hana Sato', 'Ivo Marsh', 'Jo Keller'];
const SUBJECTS = ['Quarterly numbers for review', 'Lunch on Thursday?', 'Contract draft v3', 'Your invoice is ready', 'Team offsite plan', 'Re: design feedback', 'Flight confirmation', 'Weekly update', 'Question about the API', 'Welcome aboard'];
const START = now() - 3600;
const person = i => ({ name: NAMES[i % NAMES.length], address: NAMES[i % NAMES.length].toLowerCase().replace(' ', '.') + '@example.com' });
const thread = i => ({ connection_id: 'acc1', id: 't' + i, subject: SUBJECTS[i % SUBJECTS.length] + (i > 9 ? ` #${i}` : ''), snippet: 'A short preview of what this message says, so the list has a second line to show.',
  people: [person(i), person(i + 3)], last_epoch: START - i * 517, message_count: 1 + (i % 3), unread: i % 4 === 0, starred: i % 11 === 0, has_attachments: i % 7 === 0,
  labels: ['inbox'], provider_labels: [] });
const account = { id: 'acc1', provider: 'mock', provider_label: 'Mail service', identity: 'you@example.com', state: 'working', needs_reason: null,
  capabilities: { mail: true, calendar: true, mail_search: true, incremental: true, push: false, labels: 'labels', subjects: true, send: false, organize: false, mark_read: false, event_write: false, respond: false },
  granted: { mail: true, calendar: true }, mail: { synced_epoch: now() - 60, filled: true, items: TOTAL, error: null, paused: false }, calendar: { synced_epoch: now() - 60, filled: true, items: 40, error: null, paused: false } };
const calendars = [
  { connection_id: 'acc1', id: 'primary', name: 'You', colour: 'violet', timezone: null, access: 'owner', primary: true, selected: true, synced_epoch: now() - 60, filled: true, error: null, paused: false },
  { connection_id: 'acc1', id: 'team', name: 'Team', colour: 'teal', timezone: null, access: 'read', primary: false, selected: true, synced_epoch: now() - 60, filled: true, error: null, paused: false }];
const day0 = (() => { const d = new Date(); d.setHours(0, 0, 0, 0); return Math.floor(d.getTime() / 1000); })();
const events = [];
for (let d = -20; d < 40; d++) for (const [h, len, title, cal] of [[9, 1, 'Stand-up', 'team'], [13, 1.5, 'Design review', 'primary'], [16, 0.5, 'One to one', 'primary']]) {
  if ((d + h) % 3 === 0) continue;
  const s = day0 + d * 86400 + h * 3600;
  events.push({ connection_id: 'acc1', calendar_id: cal, id: `e${d}_${h}`, series_id: null, title, busy_only: false, start_epoch: s, end_epoch: s + len * 3600, all_day: false, start_date: null, end_date: null,
    timezone: null, place: d % 2 ? 'Room 2' : '', conference_url: null, my_response: 'accepted', exception: false, cancelled: false, visibility: 'default', colour: cal === 'team' ? 'teal' : 'violet' });
}
const folders = [{ id: 'f1', project_id: 'p1', parent_id: null, name: 'Reports', files: 2 }, { id: 'f2', project_id: 'p1', parent_id: 'f1', name: '2026', files: 1 }, { id: 'f3', project_id: 'p1', parent_id: null, name: 'Contracts', files: 1 }];
const catalogue = [
  ['u1', 'upload', 'Quarterly report.pdf', 'application/pdf', 'f1', 'document'], ['u2', 'upload', 'Budget 2026.xlsx', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', 'f2', 'spreadsheet'],
  ['a1', 'made', 'results.csv', 'text/csv', null, 'data'], ['a2', 'made', 'summary.md', 'text/markdown', 'f1', 'text'], ['u3', 'upload', 'Lease agreement.docx', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document', 'f3', 'document'],
  ['u4', 'upload', 'Team photo.png', 'image/png', null, 'picture']].map(([id, kind, name, type, folder, family], i) => ({ kind, id, name, original_name: name, media_type: type, size_bytes: 20000 + i * 91234,
  project_id: 'p1', folder_id: folder, source: kind === 'made' ? 'made' : 'uploaded', created_at: new Date(Date.now() - i * 86400000).toISOString(), family, copy_of: null, version: 1, versions: 1, conversation_id: kind === 'made' ? 'c1' : null }));

/** -> true when the request was answered here. */
export async function hubMock(p, url, req, res, json, body) {
  const q = k => url.searchParams.get(k);
  if (p === '/v1/hub') return json(res, 200, { accounts: [account], providers: [{ provider: 'mock', label: 'Mail service' }], settings: { timezone: null, image_senders: [] }, counts: { unread: Math.ceil(TOTAL / 4), by_account: { acc1: Math.ceil(TOTAL / 4) } },
    calendars, labels: ['inbox', 'starred', 'sent', 'drafts', 'archive', 'all', 'spam', 'trash'], colours: ['blue', 'green', 'amber', 'red', 'violet', 'teal', 'pink', 'grey'], read_only: true }), true;
  if (p === '/v1/hub/pulse') return json(res, 200, { mark: 'm1', loading: false, items: TOTAL }), true;
  if (p === '/v1/hub/mail/labels') return json(res, 200, { labels: [{ connection_id: 'acc1', labels: [{ id: 'L1', name: 'Receipts', threads: 12 }, { id: 'L2', name: 'Travel', threads: 4 }] }] }), true;
  if (p === '/v1/hub/mail/threads') {
    const limit = Math.min(Number(q('limit') || 50), 200); const from = Number(q('cursor') || 0); const term = (q('q') || '').toLowerCase(); const unread = q('unread') === 'true';
    const out = [];
    if (term || unread) { for (let i = 0; i < TOTAL && out.length < from + limit; i++) { const t = thread(i); if ((!term || t.subject.toLowerCase().includes(term)) && (!unread || t.unread)) out.push(t); } return json(res, 200, { threads: out.slice(from), next: null, complete: true }), true; }
    for (let i = from; i < Math.min(TOTAL, from + limit); i++) out.push(thread(i));
    return json(res, 200, { threads: out, next: from + limit < TOTAL ? String(from + limit) : null, complete: from + limit >= TOTAL }), true;
  }
  if (p === '/v1/hub/mail/thread') {
    const i = Number((q('id') || 't0').slice(1)); const t = thread(i);
    const messages = Array.from({ length: t.message_count }, (_, n) => ({ id: `m${i}_${n}`, thread_id: t.id, subject: t.subject, snippet: t.snippet, sender: person(i + n), to: [{ name: 'You', address: 'you@example.com' }], cc: [],
      sent_epoch: t.last_epoch - (t.message_count - n) * 3600, labels: ['inbox'], provider_labels: [], unread: false, starred: false, has_attachments: false,
      body: { html: '', text: `Hello,\n\nThis is message ${n + 1} of the thread "${t.subject}". It is synthetic text for a local check.\n\nBest,\n${person(i + n).name}`, blocked_images: 0, images_shown: false, attachments: [], fetched_epoch: now() } }));
    await new Promise(r => setTimeout(r, 120));          // the body takes a moment, as it does from the server
    return json(res, 200, { thread: t, messages, problem: null }), true;
  }
  if (p === '/v1/hub/events') { const s = Number(q('start')), e = Number(q('end')); return json(res, 200, { events: events.filter(x => x.end_epoch > s && x.start_epoch < e), complete: true }), true; }
  if (p === '/v1/hub/event') { const ev = events.find(x => x.id === q('id')); return json(res, ev ? 200 : 404, ev ? { event: { ...ev, description: 'Agenda: numbers, then next steps.', organizer: person(1), attendees: [{ ...person(2), response: 'accepted', self: false, optional: false }] } } : { error: 'not_found' }), true; }
  if (p === '/v1/hub/events/search') { const term = (q('q') || '').toLowerCase(); return json(res, 200, { events: events.filter(x => x.title.toLowerCase().includes(term)).slice(0, 50), complete: true }), true; }
  if (p === '/v1/hub/calendars') return json(res, 200, { calendars }), true;
  if (p === '/v1/hub/ask' || p === '/v1/assistant/ask') { await body(req); return json(res, 202, { request: { id: 'r4', conversation_id: 'c1' }, looking_at: null }), true; }
  if (p === '/v1/catalogue') return json(res, 200, { files: catalogue, folders, projects: [{ id: 'p1', name: 'General' }], total: catalogue.length, uploads: true }), true;
  if (p === '/v1/files') return json(res, 200, { files: catalogue.filter(f => f.kind === 'made').map(f => ({ id: f.id, version: 1, display_name: f.name, media_type: f.media_type, size_bytes: f.size_bytes, created_at: f.created_at, task_id: 'r3', project_id: 'p1', conversation_id: 'c1' })), used_bytes: 1200000, quota_bytes: 1073741824 }), true;
  if (p === '/v1/projects') return json(res, 200, { projects: [{ id: 'p1', name: 'General' }] }), true;
  if (p === '/v1/search') {
    const term = (q('q') || '').toLowerCase(); const t0 = Date.now();
    const mail = []; for (let i = 0; i < 2000 && mail.length < 5; i++) { const t = thread(i); if (t.subject.toLowerCase().includes(term)) mail.push({ kind: 'mail', id: t.id, title: t.subject, detail: personNameOf(t.people[0]), connection: t.connection_id, epoch: t.last_epoch }); }
    return json(res, 200, { query: term, results: [...mail, ...events.filter(e => e.title.toLowerCase().includes(term)).slice(0, 5).map(e => ({ kind: 'event', id: e.id, title: e.title, detail: '', connection: e.connection_id, calendar: e.calendar_id, epoch: e.start_epoch })),
      ...catalogue.filter(f => f.name.toLowerCase().includes(term)).map(f => ({ kind: 'file', id: f.id, file_kind: f.kind, title: f.name, detail: '', epoch: 0 }))], dropped: [], took_ms: Date.now() - t0 }), true;
  }
  return false;
}
const personNameOf = p => p.name || p.address;
