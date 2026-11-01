// The side chat in the extension: the pure model, the link that holds the ticket, the popup's choice of tab, and the service worker's wiring (fake `chrome`, fake socket, fake fetch).
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { parsePush, buildCall, view, stepLine, mergeEvents, pollDelay, newKey, errorText, KEY, TICKET, MAX_MESSAGE } from '../extension/src/panel-model.js';
import { createPanelLink } from '../extension/src/panel-link.js';
import { chatTab, describe } from '../extension/src/popup-model.js';
import { panelApiAllowed, PROD_PANEL_API } from '../extension/src/config.js';

const TICKET_OK = 'p1.eyJhIjoiYSJ9.c2lnbmF0dXJl', RID = 'a'.repeat(32);
const push = (over = {}) => ({ ticket: TICKET_OK, conversation_id: 'conv_1', device_id: 'a1b2c3d4e5f60718', expires_in: 90, ...over });

// ------------------------------------------------------------------------------------------------------------ model
test('only a well-formed ticket push is accepted, with its expiry worked out from now', () => {
  assert.deepEqual(parsePush(push(), 1000), { type: 'ticket', ticket: TICKET_OK, conversation: 'conv_1', expiresAt: 91000 });
  for (const bad of [null, 'x', {}, push({ ticket: 'v1.a.b' }), push({ ticket: 'p1.a b.c' }), push({ ticket: 5 }), push({ expires_in: 0 }), push({ expires_in: 601 }), push({ expires_in: '90' }), push({ expires_in: 1.5 }),
    push({ conversation_id: '../x' }), push({ conversation_id: 7 }), { clear: true, conversation_id: 'conv_1' }]) assert.equal(parsePush(bad), null, JSON.stringify(bad));
  assert.ok(TICKET.test(TICKET_OK));
});

test('keys are fresh, well-formed and different each time', () => {
  const a = newKey(), b = newKey();
  assert.match(a, KEY); assert.notEqual(a, b);
});

test('the panel may reach four endpoints and send one thing to each', () => {
  assert.deepEqual(buildCall('state'), { method: 'GET', path: 'state', query: '', body: undefined });
  assert.deepEqual(buildCall('stop'), { method: 'POST', path: 'stop', query: '', body: undefined });
  assert.deepEqual(buildCall('events', { request: RID, after: 4, limit: 50 }), { method: 'GET', path: 'events', query: `?request=${RID}&after=4&limit=50`, body: undefined });
  assert.deepEqual(buildCall('send', { message: ' hi ', key: 'abcdefgh1234' }), { method: 'POST', path: 'send', query: '', body: JSON.stringify({ message: ' hi ', key: 'abcdefgh1234' }) });
  for (const [endpoint, input] of [['events', {}], ['events', { request: 'nope' }], ['events', { request: RID, after: -1 }], ['events', { request: RID, limit: 101 }], ['events', { request: RID + '&x=1' }],
    ['send', { message: '', key: 'abcdefgh1234' }], ['send', { message: '  ', key: 'abcdefgh1234' }], ['send', { message: 'x'.repeat(MAX_MESSAGE + 1), key: 'abcdefgh1234' }], ['send', { message: 'a\0b', key: 'abcdefgh1234' }],
    ['send', { message: 'hi', key: 'bad key' }], ['send', { message: 5, key: 'abcdefgh1234' }], ['delete', {}], ['../state', {}], ['send']]) assert.equal(buildCall(endpoint, input), null, `${endpoint} ${JSON.stringify(input)}`);
});

test('the status follows what the worker, the server and the run say', () => {
  const link = { enabled: true, connected: true, hasTicket: true };
  const live = { live: true, request: { id: RID, state: 'running', paused: false }, messages: [] };
  assert.deepEqual([view({ link: { ...link, enabled: false } }).tone, view({ link: { ...link, enabled: false } }).canSend], ['off', false]);
  assert.equal(view({ link: { ...link, connected: false } }).tone, 'wait');
  assert.equal(view({ link, error: 'browser_off' }).tone, 'off');
  assert.equal(view({ link: { ...link, hasTicket: false } }).headline, 'Waiting for a task');
  assert.equal(view({ link }).headline, 'Loading…');
  assert.deepEqual(view({ link, state: live }), { tone: 'on', headline: 'Working', detail: '', canSend: true, canStop: true });
  assert.equal(view({ link, state: { ...live, request: { ...live.request, paused: true } } }).headline, 'Paused');
  assert.equal(view({ link, state: live, sending: true }).canSend, false);
  const done = view({ link, state: { live: false, request: { state: 'completed' }, messages: [] } });
  assert.deepEqual([done.tone, done.headline, done.canSend, done.canStop], ['idle', 'Done', false, false]);
  const lapsed = view({ link: { ...link, hasTicket: false }, state: live });
  assert.deepEqual([lapsed.tone, lapsed.canSend, lapsed.canStop], ['idle', false, false]);        // the ticket lapsed after the run: the last view stays, and nothing can be sent
  assert.equal(view({ link, state: { live: false, request: null, messages: [] } }).headline, 'Nothing is running');
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
  assert.match(errorText('budget_denied'), /allowance/); assert.match(errorText('no_active_run'), /Nothing is running/); assert.match(errorText('<img src=x>'), /Something went wrong/);
});

// ------------------------------------------------------------------------------------------------------------ link
function harness({ on = true, status = 200, body = { ok: true }, fail = false } = {}) {
  const state = { on, now: 1_000_000, calls: [], changes: 0 };
  const link = createPanelLink({
    base: 'https://backend.example/v1/panel', isOn: () => state.on, now: () => state.now, onChange: () => { state.changes += 1; },
    fetchFn: async (url, init) => { state.calls.push([url, init]); if (fail) throw new Error('offline'); return { status, json: async () => body }; },
  });
  return { state, link };
}

test('a pushed ticket is used as the only credential, with no cookies and no referrer', async () => {
  const { state, link } = harness();
  assert.equal(link.push({ panel: push() }), true); assert.equal(link.has(), true); assert.equal(state.changes, 1);
  const out = await link.call('send', { message: 'hello', key: 'abcdefgh1234' });
  assert.deepEqual(out, { status: 200, data: { ok: true } });
  const [url, init] = state.calls[0];
  assert.equal(url, 'https://backend.example/v1/panel/send');
  assert.deepEqual([init.method, init.credentials, init.referrerPolicy, init.cache], ['POST', 'omit', 'no-referrer', 'no-store']);
  assert.equal(init.headers.Authorization, `Panel ${TICKET_OK}`); assert.equal(init.headers['Content-Type'], 'application/json');
  assert.equal(JSON.parse(init.body).message, 'hello');
  await link.call('state'); assert.equal(state.calls[1][1].headers['Content-Type'], undefined); assert.equal(state.calls[1][1].body, undefined);
});

test('nothing is sent without a fresh ticket, when switched off, or for a call the panel may not make', async () => {
  const { state, link } = harness();
  assert.deepEqual(await link.call('state'), { status: 0, data: { error: 'no_ticket' } });
  link.push({ panel: push() });
  state.now += 91_000;
  assert.equal(link.has(), false); assert.deepEqual(await link.call('state'), { status: 0, data: { error: 'no_ticket' } });
  link.push({ panel: push() });
  assert.deepEqual(await link.call('wipe-everything'), { status: 400, data: { error: 'invalid_request' } });
  assert.deepEqual(await link.call('send', { message: 'x', key: 'k' }), { status: 400, data: { error: 'invalid_request' } });
  state.on = false;
  assert.deepEqual(await link.call('state'), { status: 0, data: { error: 'browser_off' } });
  assert.equal(state.calls.length, 0);
});

test('messages that are not panel tickets are left alone, and bad ones are swallowed without replacing a good ticket', async () => {
  const { link } = harness();
  for (const msg of [null, 'x', { id: 1, cmd: 'open' }, { welcome: 1 }]) assert.equal(link.push(msg), false);
  link.push({ panel: push() });
  assert.equal(link.push({ panel: push({ ticket: 'forged' }) }), true); assert.equal(link.has(), true);
  assert.equal(link.push({ panel: { clear: true, conversation_id: 'conv_1' } }), true);
});

test('the server saying the ticket is no good drops it; an unreachable server does not', async () => {
  const bad = harness({ status: 401, body: { error: 'ticket' } });
  bad.link.push({ panel: push() });
  assert.deepEqual(await bad.link.call('state'), { status: 401, data: { error: 'ticket' } }); assert.equal(bad.link.has(), false);
  const down = harness({ fail: true });
  down.link.push({ panel: push() });
  assert.deepEqual(await down.link.call('state'), { status: 0, data: { error: 'unavailable_now' } }); assert.equal(down.link.has(), true);
  const odd = harness({ body: 'not an object' });
  odd.link.push({ panel: push() });
  assert.deepEqual((await odd.link.call('state')).data, {});
  down.link.clear(); assert.equal(down.link.has(), false);
});

// ------------------------------------------------------------------------------------------------------------ popup and config
test('the popup offers the side chat only when it is on, connected and there is a Lumina tab; it opens beside the front tab when that is ours', () => {
  const on = { enabled: true, connected: true, paired: true, tabs: [11, 12] };
  assert.equal(describe(on).chat, true);
  assert.equal(describe({ ...on, tabs: [] }).chat, false); assert.equal(describe({ ...on, connected: false }).chat, undefined); assert.equal(describe({ ...on, enabled: false }).chat, undefined);
  assert.equal(chatTab(on, 11), 11); assert.equal(chatTab(on, 99), 12); assert.equal(chatTab({ tabs: [] }, 11), null); assert.equal(chatTab(undefined, 1), null);
});

test('the side panel API address is production, or this computer over plain http, and nothing else', () => {
  assert.equal(panelApiAllowed(PROD_PANEL_API), true); assert.equal(PROD_PANEL_API, 'https://backend.getlumina.pro/v1/panel');
  for (const ok of ['http://127.0.0.1:8000/v1/panel', 'http://localhost/v1/panel']) assert.equal(panelApiAllowed(ok), true, ok);
  for (const bad of ['https://evil.example/v1/panel', 'http://evil.example/v1/panel', 'https://backend.getlumina.pro/v1/panel/', 'http://127.0.0.1.evil.example/v1/panel', 'http://127.0.0.1:80/other', 'ftp://localhost/v1/panel', '', null, 5]) assert.equal(panelApiAllowed(bad), false, String(bad));
});

// ------------------------------------------------------------------------------------------------------------ the service worker
const listeners = () => { const l = []; return { addListener: f => l.push(f), fire: (...a) => l.forEach(f => f(...a)) }; };
const store = {}, calls = [], sockets = [], fetches = [];
let tabSeq = 200;
const chrome = {
  storage: { local: { get: async keys => Object.fromEntries([].concat(keys).filter(k => k in store).map(k => [k, store[k]])), set: async o => { Object.assign(store, o); }, remove: async k => { delete store[k]; } } },
  runtime: { id: 'ext-id', getManifest: () => ({ version: '0.1.0' }), getPlatformInfo: async () => ({ os: 'mac' }), onMessage: listeners(), onMessageExternal: listeners(), sendMessage: m => { calls.push(['notify', m.type]); return Promise.resolve(); } },
  action: { setBadgeText() {}, setBadgeBackgroundColor() {}, setTitle() {} },
  sidePanel: { setOptions: async o => { calls.push(['sidePanel', o.tabId, o.enabled, o.path]); } },
  tabs: { onRemoved: listeners(), onCreated: listeners(), create: async () => ({ id: ++tabSeq }), remove: async id => { calls.push(['tabs.remove', id]); }, group: async () => 7 },
  tabGroups: { update: async () => {} },
  debugger: { onEvent: listeners(), onDetach: listeners(), attach: async () => {}, detach: async () => {}, sendCommand: async (t, method) => { calls.push(['cdp', method]); return method === 'Runtime.evaluate' ? { result: { value: 'complete' } } : {}; } },
};
class FakeSocket { constructor(url) { this.url = url; this.sent = []; this.readyState = 0; sockets.push(this); } send(t) { this.sent.push(JSON.parse(t)); } close() { this.readyState = 3; this.onclose?.({ code: 1000 }); } drop(code = 1006) { this.readyState = 3; this.onclose?.({ code }); } }
globalThis.chrome = chrome; globalThis.WebSocket = FakeSocket;
globalThis.fetch = async (url, init) => { fetches.push([url, init]); return { status: 200, json: async () => ({ messages: [], live: true }) }; };
await import('../extension/src/background.js');
const ask = (set, msg, sender, wait = 3000) => new Promise(res => { set.fire(msg, sender, res); setTimeout(() => res(undefined), wait); });
const popup = msg => ask(chrome.runtime.onMessage, msg, { id: 'ext-id' });
const tick = (ms = 30) => new Promise(r => setTimeout(r, ms));
const deliver = async (sock, msg, wait = 40) => { sock.onmessage({ data: typeof msg === 'string' ? msg : JSON.stringify(msg) }); await tick(wait); };
const connect = async () => { store.token = 'device-token'; await popup({ type: 'toggle' }); await tick(); const s = sockets[sockets.length - 1]; s.readyState = 1; await s.onopen(); return s; };

test('the side chat exists only on tabs Lumina works in, and ends with them', async () => {
  const s = await connect();
  await deliver(s, { id: 1, cmd: 'open', url: 'https://example.com/' }, 900);
  assert.ok(calls.some(c => c[0] === 'sidePanel' && c[1] === 201 && c[2] === true && c[3] === 'panel.html'), JSON.stringify(calls.filter(c => c[0] === 'sidePanel')));
  chrome.tabs.onRemoved.fire(201); await tick();
  assert.ok(calls.some(c => c[0] === 'sidePanel' && c[1] === 201 && c[2] === false));
});

test('a ticket is taken at once, not queued behind a browser command, and the panel page can then call through the worker', async () => {
  const s = sockets[sockets.length - 1];
  await deliver(s, { id: 2, cmd: 'open', url: 'https://example.com/' }, 5);       // a command is in flight...
  await deliver(s, { panel: { ticket: TICKET_OK, conversation_id: 'conv_1', device_id: 'a1b2c3d4e5f60718', expires_in: 90 } }, 5);      // ...and a ticket arrives meanwhile
  assert.deepEqual(await popup({ type: 'panel:state' }), { enabled: true, connected: true, hasTicket: true });
  assert.equal((await popup({ type: 'status' })).panel, true);
  assert.ok(calls.some(c => c[0] === 'notify' && c[1] === 'panel:changed'));
  const out = await popup({ type: 'panel:call', endpoint: 'state' });
  assert.deepEqual(out, { status: 200, data: { messages: [], live: true } });
  const [url, init] = fetches.at(-1);
  assert.equal(url, 'https://backend.getlumina.pro/v1/panel/state'); assert.equal(init.headers.Authorization, `Panel ${TICKET_OK}`); assert.equal(init.credentials, 'omit');
  assert.deepEqual(await popup({ type: 'panel:call', endpoint: 'format-disk' }), { status: 400, data: { error: 'invalid_request' } });
  await tick(900);
});

test('a dev address for the panel API is used only when it is this computer', async () => {
  const before = fetches.length;
  store.panelApi = 'https://evil.example/v1/panel'; await popup({ type: 'panel:call', endpoint: 'state' });
  assert.equal(fetches[before][0], 'https://backend.getlumina.pro/v1/panel/state');
  store.panelApi = 'http://127.0.0.1:8000/v1/panel'; await popup({ type: 'panel:call', endpoint: 'state' });
  assert.equal(fetches[before + 1][0], 'http://127.0.0.1:8000/v1/panel/state');
  delete store.panelApi;
});

test('the panel page cannot get at the worker from anywhere but the extension itself', async () => {
  const before = fetches.length;
  assert.equal(await ask(chrome.runtime.onMessage, { type: 'panel:call', endpoint: 'state' }, { id: 'someone-else' }, 100), undefined);
  assert.equal(fetches.length, before);
});

test('the link going away drops the ticket; so does switching off, and a switched-off worker makes no panel call', async () => {
  const s = sockets[sockets.length - 1];
  s.drop(1006); await tick(50);
  assert.deepEqual(await popup({ type: 'panel:state' }), { enabled: true, connected: false, hasTicket: false });
  await tick(1300);
  const again = sockets[sockets.length - 1]; again.readyState = 1; await again.onopen();
  await deliver(again, { panel: { ticket: TICKET_OK, conversation_id: 'conv_1', device_id: 'a1b2c3d4e5f60718', expires_in: 90 } });
  assert.equal((await popup({ type: 'panel:state' })).hasTicket, true);
  await popup({ type: 'toggle' }); await tick(100);
  assert.deepEqual(await popup({ type: 'panel:state' }), { enabled: false, connected: false, hasTicket: false });
  const before = fetches.length;
  assert.deepEqual(await popup({ type: 'panel:call', endpoint: 'state' }), { status: 0, data: { error: 'browser_off' } });
  assert.equal(fetches.length, before);
});
