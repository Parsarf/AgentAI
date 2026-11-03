// The side chat in the extension: the pure model, the link that holds the ticket, and the service worker's wiring (fake `chrome`, fake socket, fake fetch).
import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  parsePush, parseSession, buildCall, buildContext, view, stepLine, mergeEvents, pollDelay, newKey, errorText, cellLine, availableActions, cleanPrompts, restrictedUrl, QUICK_ACTIONS, KEY, TICKET, MAX_MESSAGE,
} from '../extension/src/panel-model.js';
import { createPanelLink } from '../extension/src/panel-link.js';
import { panelApiAllowed, PROD_PANEL_API } from '../extension/src/config.js';

const TICKET_OK = 'p1.eyJhIjoiYSJ9.c2lnbmF0dXJl', RID = 'a'.repeat(32);
const push = (over = {}) => ({ ticket: TICKET_OK, conversation_id: 'conv_1', device_id: 'a1b2c3d4e5f60718', expires_in: 90, ...over });
const session = (over = {}) => ({ ticket: TICKET_OK, conversation: 'conv_new', expires_in: 90, cell: 'asleep', ...over });

// ------------------------------------------------------------------------------------------------------------ model
test('only a well-formed ticket push is accepted, with its expiry worked out from now', () => {
  assert.deepEqual(parsePush(push(), 1000), { type: 'ticket', ticket: TICKET_OK, conversation: 'conv_1', expiresAt: 91000 });
  for (const bad of [null, 'x', {}, push({ ticket: 'v1.a.b' }), push({ ticket: 'p1.a b.c' }), push({ ticket: 5 }), push({ expires_in: 0 }), push({ expires_in: 601 }), push({ expires_in: '90' }), push({ expires_in: 1.5 }),
    push({ conversation_id: '../x' }), push({ conversation_id: 7 }), { clear: true, conversation_id: 'conv_1' }]) assert.equal(parsePush(bad), null, JSON.stringify(bad));
  assert.ok(TICKET.test(TICKET_OK));
});

test('a session answer is accepted only when it is shaped like one; an unknown cell state becomes "unknown"', () => {
  assert.deepEqual(parseSession(session(), 1000), { ticket: TICKET_OK, conversation: 'conv_new', expiresAt: 91000, cell: 'asleep' });
  assert.equal(parseSession(session({ cell: 'on fire' }), 0).cell, 'unknown');
  for (const bad of [null, 'x', {}, session({ ticket: 'v1.a.b' }), session({ conversation: '../x' }), session({ expires_in: 0 }), session({ expires_in: 9999 }), session({ expires_in: '90' })]) assert.equal(parseSession(bad), null, JSON.stringify(bad));
});

test('keys are fresh, well-formed and different each time', () => {
  const a = newKey(), b = newKey();
  assert.match(a, KEY); assert.notEqual(a, b);
});

test('what goes with a message is cut to size and limited to a target, a few tabs, a selection and the page text', () => {
  assert.deepEqual(buildContext(), {});
  const c = buildContext({ target: 'this_tab', tabs: [{ title: 'T'.repeat(300), url: 'https://a.example/', grant: 'g1', extra: 'x' }, { title: 'Mail', url: 'https://m.example/', grant: 'Bad Grant' }], selection: 's'.repeat(9000), page: 'p'.repeat(40_000) });
  assert.equal(c.target, 'this_tab'); assert.equal(c.tabs[0].title.length, 200); assert.equal(c.tabs[0].grant, 'g1'); assert.equal(c.tabs[0].extra, undefined);
  assert.equal(c.tabs[1].grant, undefined); assert.equal(c.selection.length, 4000); assert.equal(c.page.length, 20_000);
  assert.deepEqual(buildContext({ target: 'elsewhere', tabs: 'x', selection: '  ', page: '' }), {});
  assert.equal(buildContext({ tabs: Array(20).fill({ title: 't', url: 'u' }) }).tabs.length, 8);
});

test('extra tabs carry their own text, cut per tab and in total, so several tabs can be compared', () => {
  const c = buildContext({ tabs: [{ title: 'A', url: 'https://a.example/', text: 'a'.repeat(9000) }, { title: 'B', url: 'https://b.example/', text: 'b'.repeat(6000) }, { title: 'C', url: 'https://c.example/', text: 'c'.repeat(6000) },
    { title: 'D', url: 'https://d.example/', text: 'd'.repeat(6000) }, { title: 'E', url: 'https://e.example/', text: 'e'.repeat(6000) }, { title: 'F', url: 'https://f.example/', text: ' ' }] });
  assert.deepEqual(c.tabs.map(t => (t.text ?? '').length), [6000, 6000, 6000, 6000, 0, 0]);      // 24,000 in all; an empty text is left out
  assert.equal(c.tabs[5].text, undefined);
  assert.deepEqual(buildCall('history'), { method: 'GET', path: 'history', query: '', body: undefined });
});

test('the panel may reach four endpoints and send one thing to each', () => {
  assert.deepEqual(buildCall('state'), { method: 'GET', path: 'state', query: '', body: undefined });
  assert.deepEqual(buildCall('stop'), { method: 'POST', path: 'stop', query: '', body: undefined });
  assert.deepEqual(buildCall('events', { request: RID, after: 4, limit: 50 }), { method: 'GET', path: 'events', query: `?request=${RID}&after=4&limit=50`, body: undefined });
  assert.deepEqual(buildCall('send', { message: ' hi ', key: 'abcdefgh1234' }), { method: 'POST', path: 'send', query: '', body: JSON.stringify({ message: ' hi ', key: 'abcdefgh1234' }) });
  const withContext = buildCall('send', { message: 'do it', key: 'abcdefgh1234', mode: 'browse', context: { target: 'tab', tabs: [{ title: 'Shop', url: 'https://s.example/', grant: 'g2' }] } });
  assert.deepEqual(JSON.parse(withContext.body), { message: 'do it', key: 'abcdefgh1234', mode: 'browse', context: { target: 'tab', tabs: [{ title: 'Shop', url: 'https://s.example/', grant: 'g2' }] } });
  assert.deepEqual(JSON.parse(buildCall('send', { message: 'hi', key: 'abcdefgh1234', context: {} }).body), { message: 'hi', key: 'abcdefgh1234' });      // nothing to add: nothing sent
  for (const [endpoint, input] of [['events', {}], ['events', { request: 'nope' }], ['events', { request: RID, after: -1 }], ['events', { request: RID, limit: 101 }], ['events', { request: RID + '&x=1' }],
    ['send', { message: '', key: 'abcdefgh1234' }], ['send', { message: '  ', key: 'abcdefgh1234' }], ['send', { message: 'x'.repeat(MAX_MESSAGE + 1), key: 'abcdefgh1234' }], ['send', { message: 'a\0b', key: 'abcdefgh1234' }],
    ['send', { message: 'hi', key: 'bad key' }], ['send', { message: 5, key: 'abcdefgh1234' }], ['send', { message: 'hi', key: 'abcdefgh1234', mode: 'plan' }], ['delete', {}], ['../state', {}], ['send']]) assert.equal(buildCall(endpoint, input), null, `${endpoint} ${JSON.stringify(input)}`);
});

test('the status follows the pairing, the link, the session, the assistant and the run', () => {
  const link = { paired: true, enabled: true, connected: true, hasTicket: true };
  const live = { live: true, request: { id: RID, state: 'running', paused: false }, messages: [], cell: 'ready' };
  assert.deepEqual([view({ link: { ...link, paired: false } }).needsPair, view({ link: { ...link, paired: false } }).canSend], [true, false]);
  assert.deepEqual([view({ link: { ...link, enabled: false } }).tone, view({ link: { ...link, enabled: false } }).canTurnOn], ['off', true]);
  assert.equal(view({ link: { ...link, connected: false } }).headline, 'Connecting to Lumina…');
  assert.equal(view({ link, error: 'browser_off' }).tone, 'off'); assert.equal(view({ link, error: 'device' }).needsPair, true);
  assert.equal(view({ link: { ...link, hasTicket: false } }).headline, 'Starting a new session…');
  assert.deepEqual([view({ link }).headline, view({ link }).canSend], ['Loading…', true]);
  assert.deepEqual(view({ link, state: live }), { tone: 'on', headline: 'Working', detail: '', canSend: true, canStop: true });
  assert.equal(view({ link, state: { ...live, request: { ...live.request, paused: true } } }).headline, 'Paused');
  assert.equal(view({ link, state: live, sending: true }).canSend, false);
  // a fresh session with nothing sent: ready to type, and it says whether the assistant is asleep
  const fresh = view({ link, state: { live: false, request: null, messages: [], cell: 'asleep' } });
  assert.deepEqual([fresh.tone, fresh.headline, fresh.canSend, fresh.canStop], ['on', 'Ready', true, false]); assert.match(fresh.detail, /asleep/);
  // a message sent while the assistant sleeps: it is being woken, and can still be stopped
  const waking = view({ link, state: { live: false, request: { state: 'waiting' }, messages: [], cell: 'waking' } });
  assert.deepEqual([waking.headline, waking.canStop, waking.canSend], ['Waking your assistant…', true, true]);
  const done = view({ link, state: { live: false, request: { state: 'completed' }, messages: [], cell: 'ready' } });
  assert.deepEqual([done.tone, done.headline, done.canSend, done.canStop], ['idle', 'Done', true, false]);      // after a run the same session takes the next message
});

test('the assistant\'s readiness is said in plain words, and not while a task runs', () => {
  assert.match(cellLine('waking'), /Waking/); assert.match(cellLine('asleep'), /asleep/); assert.match(cellLine('ready'), /awake/); assert.equal(cellLine('unknown'), ''); assert.equal(cellLine('ready', true), '');
});

test('trail lines are plain text; pictures and the person\'s own clicks are skipped; merging orders and de-duplicates', () => {
  assert.equal(stepLine({ kind: 'screenshot' }), null); assert.equal(stepLine({ kind: 'control' }), null); assert.equal(stepLine(null), null);
  assert.equal(stepLine({ kind: 'tool', payload: { summary: '  Opened the shop <b>now</b> ' } }), 'Opened the shop <b>now</b>');      // shown with textContent, so markup is just letters
  assert.equal(stepLine({ kind: 'page_loaded', payload: {} }), 'page loaded');
  assert.equal(stepLine({ kind: 'x', payload: { summary: 'y'.repeat(900) } }).length, 300);
  const merged = mergeEvents([{ sequence: 2 }, { sequence: 3 }], [{ sequence: 3 }, { sequence: 1 }, { sequence: 'x' }, null, { sequence: 4 }], 3);
  assert.deepEqual(merged.map(e => e.sequence), [2, 3, 4]);
});

test('polling is brisk while a task runs, calm otherwise, backs off on trouble and slows when hidden', () => {
  assert.equal(pollDelay({ live: true }), 1500); assert.equal(pollDelay({}), 4000); assert.equal(pollDelay({ hidden: true, live: true }), 10000);
  assert.deepEqual([1, 2, 3, 4, 5, 9].map(f => pollDelay({ failures: f })), [2000, 4000, 8000, 15000, 15000, 15000]);
});

test('error codes become the customer\'s words, and an unknown one gets the generic line', () => {
  assert.match(errorText('budget_denied'), /allowance/); assert.match(errorText('device'), /paired/); assert.match(errorText('<img src=x>'), /Something went wrong/);
});

test('quick actions run only when what they need is on the page; saved prompts are short, named and few; some pages are never usable', () => {
  assert.deepEqual(availableActions({}).map(a => a.id), ['research'].filter(() => false));      // nothing on the page: nothing to ask about
  const withPage = availableActions({ hasPage: true }).map(a => a.id); assert.ok(withPage.includes('summarize') && !withPage.includes('explain'));
  const withSelection = availableActions({ hasSelection: true }).map(a => a.id); assert.ok(withSelection.includes('explain') && withSelection.includes('translate'));
  for (const a of QUICK_ACTIONS) assert.ok(a.prompt.length > 10 && ['auto', 'browse'].includes(a.mode), a.id);
  const prompts = cleanPrompts([{ name: ' Weekly ', text: ' do it ' }, { name: '', text: 'x' }, { name: 'n', text: '' }, null, 'x', ...Array.from({ length: 20 }, (_, i) => ({ name: 'p' + i, text: 't' }))]);
  assert.equal(prompts.length, 12); assert.deepEqual(prompts[0], { name: 'Weekly', text: 'do it' }); assert.deepEqual(cleanPrompts('x'), []);
  for (const ok of ['https://shop.example/a', 'http://example.com']) assert.equal(restrictedUrl(ok), false, ok);
  for (const bad of ['chrome://settings', 'chrome-extension://x/panel.html', 'about:blank', 'file:///etc/passwd', 'https://chromewebstore.google.com/detail/x', '', null, 'not a url']) assert.equal(restrictedUrl(bad), true, String(bad));
});

// ------------------------------------------------------------------------------------------------------------ link
function harness({ on = true, status = 200, body = { ok: true }, fail = false, token = 'device-token', sessions = [] } = {}) {
  const state = { on, now: 1_000_000, calls: [], changes: 0, token };
  const link = createPanelLink({
    base: 'https://backend.example/v1/panel', isOn: () => state.on, now: () => state.now, token: async () => state.token, onChange: () => { state.changes += 1; },
    fetchFn: async (url, init) => {
      state.calls.push([url, init]); if (fail) throw new Error('offline');
      if (url.endsWith('/session')) { const next = sessions.shift(); return { status: next?.status ?? 200, json: async () => next?.body ?? session() }; }
      return { status, json: async () => body };
    },
  });
  return { state, link };
}

test('opening the panel signs in with the device token alone and starts a NEW session, with no cookies and no referrer', async () => {
  const { state, link } = harness();
  const out = await link.open();
  assert.equal(out.status, 200); assert.equal(link.has(), true); assert.equal(link.conversation(), 'conv_new'); assert.equal(state.changes, 1);
  const [url, init] = state.calls[0];
  assert.equal(url, 'https://backend.example/v1/panel/session'); assert.equal(init.method, 'POST'); assert.equal(init.body, '{}');
  assert.deepEqual([init.credentials, init.referrerPolicy, init.cache], ['omit', 'no-referrer', 'no-store']);
  assert.equal(init.headers.Authorization, 'Device device-token');
  const sent = await link.call('send', { message: 'hello', key: 'abcdefgh1234', mode: 'browse' });
  assert.equal(sent.status, 200); assert.equal(state.calls[1][1].headers.Authorization, `Panel ${TICKET_OK}`);       // after that, only the ticket is shown, never the device token
  assert.ok(!JSON.stringify(state.calls.slice(1)).includes('device-token'));
});

test('a past chat is reopened with a ticket for that conversation, without disturbing a new-session open', async () => {
  const { state, link } = harness({ sessions: [{ body: session({ conversation: 'conv_old' }) }] });
  const out = await link.open('conv_old');
  assert.equal(out.status, 200); assert.equal(link.conversation(), 'conv_old');
  assert.deepEqual(JSON.parse(state.calls[0][1].body), { conversation: 'conv_old' });
});

test('concurrent opens share one request; with no device token or when switched off nothing is asked', async () => {
  const { state, link } = harness();
  await Promise.all([link.open(), link.open(), link.open()]); assert.equal(state.calls.length, 1);
  const none = harness({ token: '' }); assert.deepEqual(await none.link.open(), { status: 0, data: { error: 'device' } }); assert.equal(none.state.calls.length, 0);
  const off = harness({ on: false }); assert.deepEqual(await off.link.open(), { status: 0, data: { error: 'browser_off' } }); assert.equal(off.state.calls.length, 0);
});

test('a malformed session answer gives no ticket; a refusal is passed on and an unknown device drops what was held', async () => {
  const odd = harness({ sessions: [{ body: { ticket: 'forged', conversation: 'x', expires_in: 90 } }] });
  assert.deepEqual(await odd.link.open(), { status: 0, data: { error: 'unavailable_now' } }); assert.equal(odd.link.has(), false);
  const refused = harness({ sessions: [{ status: 409, body: { error: 'browser_off' } }] });
  assert.deepEqual(await refused.link.open(), { status: 409, data: { error: 'browser_off' } });
  const gone = harness({ sessions: [{}, { status: 401, body: { error: 'device' } }] });
  await gone.link.open(); gone.state.now += 70_000;
  const call = await gone.link.call('state'); assert.equal(call.status, 0); assert.equal(gone.link.has(), false);
});

test('the ticket is renewed shortly before it lapses, for the same conversation, so a long chat never loses its session', async () => {
  const { state, link } = harness({ sessions: [{}, { body: session({ ticket: 'p1.bmV3.c2ln', conversation: 'conv_new' }) }] });
  await link.open();
  state.now += 70_000;      // 20 s left of 90
  await link.call('state');
  const renewal = state.calls[1]; assert.equal(renewal[0].endsWith('/session'), true); assert.deepEqual(JSON.parse(renewal[1].body), { conversation: 'conv_new' });
  assert.equal(state.calls[2][1].headers.Authorization, 'Panel p1.bmV3.c2ln');
});

test('nothing is sent without a fresh ticket, when switched off, or for a call the panel may not make', async () => {
  const { state, link } = harness();
  assert.deepEqual(await link.call('state'), { status: 0, data: { error: 'no_ticket' } });
  await link.open(); state.calls.length = 0;
  assert.deepEqual(await link.call('wipe-everything'), { status: 400, data: { error: 'invalid_request' } });
  assert.deepEqual(await link.call('send', { message: 'x', key: 'k' }), { status: 400, data: { error: 'invalid_request' } });
  state.on = false;
  assert.deepEqual(await link.call('state'), { status: 0, data: { error: 'browser_off' } });
  assert.equal(state.calls.length, 0);
});

test('a ticket pushed for a web-chat task is only offered; the panel keeps its own session unless the customer switches', async () => {
  const { state, link } = harness();
  assert.equal(link.push({ panel: push() }), true); assert.equal(link.offered(), 'conv_1'); assert.equal(link.has(), false);
  await link.open(); assert.equal(link.conversation(), 'conv_new'); assert.equal(link.offered(), 'conv_1');
  assert.equal(link.useOffered(), true); assert.equal(link.conversation(), 'conv_1'); assert.equal(link.offered(), null);
  assert.equal(link.useOffered(), false);
  state.now += 91_000; assert.equal(link.has(), false);
});

test('messages that are not panel tickets are left alone, and bad ones are swallowed without replacing a good ticket', async () => {
  const { link } = harness();
  for (const msg of [null, 'x', { id: 1, cmd: 'open' }, { welcome: 1 }]) assert.equal(link.push(msg), false);
  link.push({ panel: push() });
  assert.equal(link.push({ panel: push({ ticket: 'forged' }) }), true); assert.equal(link.offered(), 'conv_1');
});

test('the server saying the ticket is no good drops it; an unreachable server does not', async () => {
  const bad = harness({ status: 401, body: { error: 'ticket' } });
  await bad.link.open();
  assert.deepEqual(await bad.link.call('state'), { status: 401, data: { error: 'ticket' } }); assert.equal(bad.link.has(), false);
  const down = harness({ fail: false });
  await down.link.open();
  const failing = createPanelLink({ base: 'https://b.example/v1/panel', isOn: () => true, now: () => 1_000_000, token: async () => 't', fetchFn: async () => { throw new Error('offline'); } });
  assert.deepEqual(await failing.open(), { status: 0, data: { error: 'unavailable_now' } });
  const odd = harness({ body: 'not an object' }); await odd.link.open();
  assert.deepEqual((await odd.link.call('state')).data, {});
  down.link.clear(); assert.equal(down.link.has(), false);
});

test('the side panel API address is production, or this computer over plain http, and nothing else', () => {
  assert.equal(panelApiAllowed(PROD_PANEL_API), true); assert.equal(PROD_PANEL_API, 'https://backend.getlumina.pro/v1/panel');
  for (const ok of ['http://127.0.0.1:8000/v1/panel', 'http://localhost/v1/panel']) assert.equal(panelApiAllowed(ok), true, ok);
  for (const bad of ['https://evil.example/v1/panel', 'http://evil.example/v1/panel', 'https://backend.getlumina.pro/v1/panel/', 'http://127.0.0.1.evil.example/v1/panel', 'http://127.0.0.1:80/other', 'ftp://localhost/v1/panel', '']) assert.equal(panelApiAllowed(bad), false, bad);
});

// ------------------------------------------------------------------------------------------------------------ the service worker
const listeners = () => { const l = []; return { addListener: f => l.push(f), fire: (...a) => l.forEach(f => f(...a)) }; };
const store = {}, calls = [], sockets = [], fetches = [];
let tabSeq = 200, sessionSeq = 0, allSites = false;
const TABS = [{ id: 11, windowId: 1, active: true, title: 'Hotels', url: 'https://hotels.example/paris', favIconUrl: 'https://hotels.example/f.png' }, { id: 12, windowId: 1, active: false, title: 'Settings', url: 'chrome://settings' },
  { id: 13, windowId: 1, active: false, title: 'Docs', url: 'https://docs.example/a' }, { id: 14, windowId: 1, active: false, title: 'Panel', url: 'chrome-extension://ext-id/panel.html' }];
const evaluate = expression => (expression.includes('location.href') ? 'https://hotels.example/paris' : expression.includes('document.title') ? 'Hotels' : expression.includes('getEntriesByType') ? 3 : 'complete');
const chrome = {
  storage: { local: { get: async keys => Object.fromEntries([].concat(keys).filter(k => k in store).map(k => [k, store[k]])), set: async o => { Object.assign(store, o); }, remove: async k => { delete store[k]; } } },
  runtime: { id: 'ext-id', getManifest: () => ({ version: '0.3.0' }), getPlatformInfo: async () => ({ os: 'mac' }), onMessage: listeners(), onMessageExternal: listeners(), onConnect: listeners(), onInstalled: listeners(),
    sendMessage: m => { calls.push(['notify', m.type]); return Promise.resolve(); } },
  action: { setBadgeText() {}, setBadgeBackgroundColor() {}, setTitle() {} },
  sidePanel: { setOptions: async o => { calls.push(['sidePanel.options', o.path, o.enabled]); }, setPanelBehavior: async o => { calls.push(['sidePanel.behavior', o.openPanelOnActionClick]); },
    open: async o => { calls.push(['sidePanel.open', o.windowId]); }, close: async o => { calls.push(['sidePanel.close', o.windowId]); } },
  commands: { onCommand: listeners() },
  contextMenus: { onClicked: listeners(), removeAll: cb => { calls.push(['menus.removeAll']); cb?.(); }, create: o => { calls.push(['menus.create', o.id]); } },
  permissions: { contains: async () => allSites },
  scripting: { executeScript: async ({ target }) => { calls.push(['scripting', target.tabId]); return [{ result: { selection: 'two seats', text: 'Rooms from 120 euros' } }]; } },
  tabs: { onRemoved: listeners(), onCreated: listeners(), create: async () => ({ id: ++tabSeq }), remove: async id => { calls.push(['tabs.remove', id]); }, group: async () => 7, update: async () => ({}),
    query: async () => TABS, get: async id => TABS.find(t => t.id === id) ?? null },
  tabGroups: { update: async () => {} },
  debugger: { onEvent: listeners(), onDetach: listeners(), attach: async t => { calls.push(['attach', t.tabId]); }, detach: async t => { calls.push(['detach', t.tabId]); },
    sendCommand: async (t, method, params) => { calls.push(['cdp', t.tabId, method]); return method === 'Runtime.evaluate' ? { result: { value: evaluate(params.expression) } } : method === 'Page.captureScreenshot' ? { data: 'AAAA' } : method === 'Page.getLayoutMetrics' ? { cssVisualViewport: { clientWidth: 900, clientHeight: 600 } } : method === 'Page.navigate' ? {} : {}; } },
};
class FakeSocket { constructor(url) { this.url = url; this.sent = []; this.readyState = 0; sockets.push(this); } send(t) { this.sent.push(JSON.parse(t)); } close() { this.readyState = 3; this.onclose?.({ code: 1000 }); } drop(code) { this.readyState = 3; this.onclose?.({ code }); } }
globalThis.chrome = chrome; globalThis.WebSocket = FakeSocket;
globalThis.fetch = async (url, init) => {
  fetches.push([url, init]);
  if (url.endsWith('/session')) return { status: 200, json: async () => ({ ticket: TICKET_OK, conversation: 'conv_' + (++sessionSeq), expires_in: 90, cell: 'asleep' }) };
  return { status: 200, json: async () => ({ messages: [], live: false, cell: 'asleep' }) };
};
await import('../extension/src/background.js');
const ask = (set, msg, sender, wait = 3000) => new Promise(res => { set.fire(msg, sender, res); setTimeout(() => res(undefined), wait); });
const popup = msg => ask(chrome.runtime.onMessage, msg, { id: 'ext-id' });
const tick = (ms = 30) => new Promise(r => setTimeout(r, ms));
const deliver = async (sock, msg, wait = 40) => { sock.onmessage({ data: typeof msg === 'string' ? msg : JSON.stringify(msg) }); await tick(wait); };
const link = async () => { const s = sockets[sockets.length - 1]; s.readyState = 1; await s.onopen(); return s; };
const port = () => { const p = { name: 'panel', sender: { id: 'ext-id' }, onMessage: listeners(), onDisconnect: listeners() }; chrome.runtime.onConnect.fire(p); return p; };

test('the toolbar button opens the panel on any tab; the shortcut toggles it; the menu entries exist', async () => {
  assert.ok(calls.some(c => c[0] === 'sidePanel.behavior' && c[1] === true)); assert.ok(calls.some(c => c[0] === 'sidePanel.options' && c[1] === 'panel.html' && c[2] === true));
  chrome.runtime.onInstalled.fire(); await tick();
  assert.deepEqual(calls.filter(c => c[0] === 'menus.create').map(c => c[1]), ['ask-selection', 'ask-page', 'ask-link']);
  chrome.commands.onCommand.fire('toggle-panel', { windowId: 1 }); await tick();
  assert.ok(calls.some(c => c[0] === 'sidePanel.open' && c[1] === 1));
  const p = port(); p.onMessage.fire({ windowId: 1 });
  chrome.commands.onCommand.fire('toggle-panel', { windowId: 1 }); await tick();
  assert.ok(calls.some(c => c[0] === 'sidePanel.close' && c[1] === 1), 'open -> closes');
  chrome.commands.onCommand.fire('some-other-command', { windowId: 1 }); chrome.commands.onCommand.fire('toggle-panel', null); await tick();
  p.onDisconnect.fire();
});

test('an unpaired browser cannot start a session; opening the panel after pairing switches Lumina on and starts a NEW conversation each time', async () => {
  assert.deepEqual(await popup({ type: 'panel:open', windowId: 1 }), { ok: false, error: 'unpaired' });
  assert.equal(sockets.length, 0);
  store.token = 'device-token';
  const opened = popup({ type: 'panel:open', windowId: 1 }); await tick(120); await link();
  const out = await opened;
  assert.deepEqual(out, { ok: true, status: 200, error: null, conversation: 'conv_1', cell: 'asleep' }); assert.equal(store.enabled, true);
  const [url, init] = fetches.find(f => f[0].endsWith('/session'));
  assert.equal(url, 'https://backend.getlumina.pro/v1/panel/session'); assert.equal(init.headers.Authorization, 'Device device-token'); assert.equal(init.credentials, 'omit');
  assert.deepEqual(await popup({ type: 'panel:open', windowId: 1 }), { ok: true, status: 200, conversation: 'conv_1', error: null, cell: 'unknown' });        // the same panel keeps its session
  const fresh = await popup({ type: 'panel:new', windowId: 1 }); assert.equal(fresh.conversation, 'conv_2');
  const state = await popup({ type: 'panel:state', windowId: 1 });
  assert.deepEqual([state.enabled, state.connected, state.paired, state.hasTicket, state.conversation, state.hasSites], [true, true, true, true, 'conv_2', false]);
  assert.equal((await popup({ type: 'panel:state', windowId: 2 })).hasTicket, false, 'another window has no session of its own yet');
});

test('the panel page calls through the worker with the ticket; closing the panel ends its session', async () => {
  const p = port(); p.onMessage.fire({ windowId: 1 });
  const out = await popup({ type: 'panel:call', windowId: 1, endpoint: 'send', input: { message: 'find hotels', key: 'abcdefgh1234', mode: 'browse', context: { target: 'new_tab' } } });
  assert.equal(out.status, 200);
  const [url, init] = fetches.at(-1);
  assert.equal(url, 'https://backend.getlumina.pro/v1/panel/send'); assert.equal(init.headers.Authorization, `Panel ${TICKET_OK}`);
  assert.deepEqual(JSON.parse(init.body), { message: 'find hotels', key: 'abcdefgh1234', mode: 'browse', context: { target: 'new_tab' } });
  assert.deepEqual(await popup({ type: 'panel:call', windowId: 1, endpoint: 'format-disk' }), { status: 400, data: { error: 'invalid_request' } });
  p.onDisconnect.fire(); await tick();
  assert.equal((await popup({ type: 'panel:state', windowId: 1 })).hasTicket, false);
  assert.deepEqual(await popup({ type: 'panel:call', windowId: 1, endpoint: 'state' }), { status: 0, data: { error: 'no_ticket' } });
});

test('the panel page cannot get at the worker from anywhere but the extension itself', async () => {
  const before = fetches.length;
  assert.equal(await ask(chrome.runtime.onMessage, { type: 'panel:call', endpoint: 'state' }, { id: 'someone-else' }, 100), undefined);
  assert.equal(await ask(chrome.runtime.onMessage, { type: 'tab:grant', tabId: 11 }, { id: 'someone-else' }, 100), undefined);
  chrome.runtime.onConnect.fire({ name: 'panel', sender: { id: 'someone-else' }, onMessage: listeners(), onDisconnect: listeners() });
  assert.equal(fetches.length, before);
});

test('the tab picker lists the window\'s tabs without the extension\'s own page, marking pages that can never be used', async () => {
  const out = await popup({ type: 'tabs:list', windowId: 1 });
  assert.deepEqual(out.tabs.map(t => [t.id, t.active, t.restricted, t.grant]), [[11, true, false, null], [12, false, true, null], [13, false, false, null]]);
  assert.equal(out.tabs[0].favicon, 'https://hotels.example/f.png');
});

test('reading a page needs the customer\'s permission for all sites; without it only the name and address are given', async () => {
  const before = calls.length;
  const without = await popup({ type: 'tab:read', tabId: 11 });
  assert.deepEqual([without.ok, without.title, without.read, without.text], [true, 'Hotels', false, '']);
  assert.ok(!calls.slice(before).some(c => c[0] === 'scripting'));
  allSites = true;
  const withIt = await popup({ type: 'tab:read', tabId: 11 });
  assert.deepEqual([withIt.read, withIt.selection, withIt.text], [true, 'two seats', 'Rooms from 120 euros']);
  assert.equal((await popup({ type: 'panel:state', windowId: 1 })).hasSites, true);
  assert.equal((await popup({ type: 'tab:read', tabId: 12 })).read, false, 'chrome:// pages are never read');
  assert.equal((await popup({ type: 'tab:read', tabId: 9999 })).ok, false);
  allSites = false;
});

test('a tab is used only after the customer allows it; the job attaches to it in place, never closes it, and lets go when done', async () => {
  const s = sockets[sockets.length - 1];
  assert.deepEqual(await popup({ type: 'tab:grant', tabId: 12 }), { ok: false, error: 'tab_blocked' });
  assert.deepEqual(await popup({ type: 'tab:grant', tabId: 9999 }), { ok: false, error: 'tab_blocked' });
  assert.deepEqual(await popup({ type: 'tab:grant', tabId: 'x' }), { ok: false, error: 'bad_tab' });
  assert.deepEqual(await popup({ type: 'tab:grant', tabId: 11 }), { ok: true, grant: 'g1' });
  assert.deepEqual(await popup({ type: 'tab:grant', tabId: 11 }), { ok: true, grant: 'g1' }, 'allowing twice is the same grant');
  assert.equal((await popup({ type: 'tabs:list', windowId: 1 })).tabs[0].grant, 'g1');
  assert.ok(!calls.some(c => c[0] === 'attach' && c[1] === 11), 'allowing alone attaches nothing: the bar only appears while Lumina is working in it');
  const mark = calls.length;
  await deliver(s, { id: 70, cmd: 'attach', tab: 'g1' }, 900);
  const reply = s.sent.find(m => m.id === 70); assert.deepEqual([reply.ok, reply.url, reply.title], [true, 'https://hotels.example/paris', 'Hotels']);
  const after = calls.slice(mark);
  assert.ok(after.some(c => c[0] === 'attach' && c[1] === 11));
  const methods = after.filter(c => c[0] === 'cdp' && c[1] === 11).map(c => c[2]);
  assert.ok(methods.includes('Page.enable') && methods.includes('Fetch.enable')); assert.ok(!methods.includes('Emulation.setDeviceMetricsOverride'), 'the customer\'s own tab keeps its size');
  assert.ok(!after.some(c => c[0] === 'tabs.create'), 'no new tab is opened');
  await deliver(s, { id: 71, cmd: 'view' }, 300);
  assert.deepEqual([s.sent.find(m => m.id === 71).width, s.sent.find(m => m.id === 71).height], [900, 600], 'pictures are the tab\'s real viewport');
  await deliver(s, { id: 72, cmd: 'attach', tab: 'g99' }); assert.equal(s.sent.find(m => m.id === 72).error, 'no_such_tab');
  await deliver(s, { id: 73, cmd: 'attach', tab: '../x' }); assert.equal(s.sent.find(m => m.id === 73).error, 'bad_tab');
  const end = calls.length;
  await deliver(s, { id: 74, cmd: 'close' }, 300);
  assert.ok(calls.slice(end).some(c => c[0] === 'detach' && c[1] === 11), 'let go of');
  assert.ok(!calls.slice(end).some(c => c[0] === 'tabs.remove' && c[1] === 11), 'never closed');
  assert.deepEqual(await popup({ type: 'tab:revoke', grant: 'g1' }), { ok: true });
  await deliver(s, { id: 75, cmd: 'attach', tab: 'g1' }); assert.equal(s.sent.find(m => m.id === 75).error, 'no_such_tab');
});

test('a normal browse job still opens its own tab in the Lumina group, as before', async () => {
  const s = sockets[sockets.length - 1]; const mark = calls.length;
  await deliver(s, { id: 80, cmd: 'open', url: 'https://example.com/' }, 900);
  assert.equal(s.sent.find(m => m.id === 80).ok, true);
  const after = calls.slice(mark);
  assert.ok(after.some(c => c[0] === 'attach' && c[1] > 200)); const own = after.find(c => c[0] === 'attach')[1];
  assert.ok(after.filter(c => c[0] === 'cdp' && c[1] === own).map(c => c[2]).includes('Emulation.setDeviceMetricsOverride'));
});

test('a past chat is reopened through the worker, and only a plain conversation id is accepted', async () => {
  const before = fetches.length;
  assert.deepEqual(await popup({ type: 'panel:resume', windowId: 1, conversation: '../x' }), { ok: false, error: 'invalid_request' });
  assert.equal(fetches.length, before);
});

test('the right-click menu leaves a prompt for the window\'s panel, opens it, and it is handed over once', async () => {
  chrome.contextMenus.onClicked.fire({ menuItemId: 'ask-selection', selectionText: 'two seats left' }, { windowId: 1, url: 'https://hotels.example/paris' }); await tick();
  assert.ok(calls.some(c => c[0] === 'sidePanel.open' && c[1] === 1)); assert.ok(calls.some(c => c[0] === 'notify' && c[1] === 'panel:prompt'));
  assert.deepEqual(await popup({ type: 'panel:take-prompt', windowId: 1 }), { ok: true, prompt: { kind: 'selection', text: 'two seats left', url: 'https://hotels.example/paris' } });
  assert.deepEqual(await popup({ type: 'panel:take-prompt', windowId: 1 }), { ok: true, prompt: null });
});

test('the link going away drops every session; so does switching off, which also lets go of allowed tabs', async () => {
  const s = sockets[sockets.length - 1];
  await popup({ type: 'panel:new', windowId: 1 }); assert.equal((await popup({ type: 'panel:state', windowId: 1 })).hasTicket, true);
  s.drop(1006); await tick(50);
  assert.deepEqual([(await popup({ type: 'panel:state', windowId: 1 })).connected, (await popup({ type: 'panel:state', windowId: 1 })).hasTicket], [false, false]);
  await tick(1300); await link();
  assert.deepEqual(await popup({ type: 'tab:grant', tabId: 13 }), { ok: true, grant: 'g2' });
  await popup({ type: 'toggle' }); await tick(100);
  const state = await popup({ type: 'panel:state', windowId: 1 }); assert.deepEqual([state.enabled, state.connected, state.hasTicket], [false, false, false]);
  assert.deepEqual(await popup({ type: 'tab:grant', tabId: 13 }), { ok: false, error: 'browser_off' });
  const before = fetches.length;
  assert.deepEqual(await popup({ type: 'panel:call', windowId: 1, endpoint: 'state' }), { status: 0, data: { error: 'browser_off' } });
  assert.equal(fetches.length, before);
});
