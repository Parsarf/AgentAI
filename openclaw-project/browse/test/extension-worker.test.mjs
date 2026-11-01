// The service worker's wiring, against a fake `chrome` and a fake WebSocket (Chrome 156 will not load an unpacked extension from a flag, so the real thing is tried by hand: see extension/README.md).
import { test } from 'node:test';
import assert from 'node:assert/strict';

const listeners = () => { const l = []; return { addListener: f => l.push(f), fire: (...a) => l.forEach(f => f(...a)) }; };
const store = {}, calls = [], sockets = [];
let tabSeq = 100;
const chrome = {
  storage: { local: { get: async keys => Object.fromEntries([].concat(keys).filter(k => k in store).map(k => [k, store[k]])), set: async o => { Object.assign(store, o); }, remove: async k => { delete store[k]; } } },
  runtime: { id: 'ext-id', getManifest: () => ({ version: '0.1.0' }), getPlatformInfo: async () => ({ os: 'mac' }), onMessage: listeners(), onMessageExternal: listeners() },
  action: { setBadgeText: o => calls.push(['badge', o.text]), setBadgeBackgroundColor() {}, setTitle() {} },
  tabs: { onRemoved: listeners(), onCreated: listeners(), create: async o => { calls.push(['tabs.create', o.url]); return { id: ++tabSeq }; }, remove: async id => { calls.push(['tabs.remove', id]); }, update: async () => {}, group: async o => o.groupId ?? 7 },
  tabGroups: { update: async () => {} },
  debugger: { onEvent: listeners(), onDetach: listeners(), attach: async t => { calls.push(['attach', t.tabId]); }, detach: async t => { calls.push(['detach', t.tabId]); },
    sendCommand: async (t, method) => { calls.push(['cdp', t.tabId, method]); return method === 'Runtime.evaluate' ? { result: { value: 'complete' } } : method === 'Page.captureScreenshot' ? { data: 'AAAA' } : {}; } },
};
class FakeSocket { constructor(url) { this.url = url; this.sent = []; this.readyState = 0; sockets.push(this); } send(t) { this.sent.push(JSON.parse(t)); } close() { this.readyState = 3; this.onclose?.({}); } drop(code, reason = '') { this.readyState = 3; this.onclose?.({ code, reason }); } }
globalThis.chrome = chrome; globalThis.WebSocket = FakeSocket;
await import('../extension/src/background.js');
const ask = (set, msg, sender, wait = 3000) => new Promise(res => { set.fire(msg, sender, res); setTimeout(() => res(undefined), wait); });      // a listener that ignores a message never answers: the timeout stands for "no answer"
const popup = msg => ask(chrome.runtime.onMessage, msg, { id: 'ext-id' });
const toggle = () => popup({ type: 'toggle' });
const tick = (ms = 30) => new Promise(r => setTimeout(r, ms));
const deliver = async (sock, msg) => { sock.onmessage({ data: typeof msg === 'string' ? msg : JSON.stringify(msg) }); await tick(900); };

test('nothing connects until the customer switches it on; then it says hello with the token', async () => {
  assert.equal(sockets.length, 0); assert.equal(store.enabled, false);
  store.token = 'secret-token';
  await toggle(); await tick();
  assert.equal(sockets.length, 1); assert.equal(sockets[0].url, 'wss://backend.getlumina.pro/v1/device'); assert.equal(store.enabled, true);
  const s = sockets[0]; s.readyState = 1; await s.onopen();
  assert.deepEqual(s.sent[0], { hello: 1, token: 'secret-token', version: '0.1.0' });
});

test('a command opens a tab in a Lumina group, attaches DevTools to it alone, and the reply carries the command id', async () => {
  const s = sockets[0];
  await deliver(s, { id: 41, cmd: 'open', url: 'https://example.com/' });
  const reply = s.sent.find(m => m.id === 41);
  assert.ok(reply && reply.ok === true, JSON.stringify(s.sent));
  assert.ok(calls.some(c => c[0] === 'tabs.create' && c[1] === 'about:blank'));
  assert.ok(calls.some(c => c[0] === 'attach' && c[1] === 101));
  const methods = calls.filter(c => c[0] === 'cdp' && c[1] === 101).map(c => c[2]);
  assert.deepEqual(methods.slice(0, 4), ['Page.enable', 'Emulation.setDeviceMetricsOverride', 'Fetch.enable', 'Page.navigate']);
  assert.ok(!calls.some(c => c[0] === 'cdp' && c[1] !== 101), 'only the session\'s tab is ever touched');
});

test('bad input and a refused address are answered, never executed', async () => {
  const s = sockets[0]; const n = calls.length;
  await deliver(s, 'not json');
  await deliver(s, { id: 42, cmd: 'open', url: 'http://192.168.1.1/' });
  await deliver(s, { id: 43, cmd: 'format-disk' });
  assert.equal(s.sent.find(m => m.error === 'bad_json').ok, false);
  assert.equal(s.sent.find(m => m.id === 42).error, 'url_blocked');
  assert.equal(s.sent.find(m => m.id === 43).error, 'unknown_command');
  assert.ok(!calls.slice(n).some(c => c[0] === 'cdp' && c[2] === 'Page.navigate'));
});

test('popups opened by the agent\'s own tab join up to the cap; others are ignored or closed', async () => {
  chrome.tabs.onCreated.fire({ id: 500, openerTabId: 999 }); await tick();                 // opened by a tab that is not ours
  assert.ok(!calls.some(c => c[0] === 'attach' && c[1] === 500));
  chrome.tabs.onCreated.fire({ id: 501, openerTabId: 101 }); await tick();
  chrome.tabs.onCreated.fire({ id: 502, openerTabId: 101 }); await tick();
  chrome.tabs.onCreated.fire({ id: 503, openerTabId: 101 }); await tick();                 // a fourth tab: over MAX_PAGES (3)
  assert.ok(calls.some(c => c[0] === 'attach' && c[1] === 501)); assert.ok(calls.some(c => c[0] === 'attach' && c[1] === 502));
  assert.ok(!calls.some(c => c[0] === 'attach' && c[1] === 503)); assert.ok(calls.some(c => c[0] === 'tabs.remove' && c[1] === 503));
});

test('pressing Cancel on Chrome\'s debugging bar stops everything: tabs closed, platform told, switched off', async () => {
  const s = sockets[0];
  chrome.debugger.onDetach.fire({ tabId: 101 }, 'canceled_by_user'); await tick(100);
  assert.ok(s.sent.some(m => m.event === 'stopped' && m.reason === 'stopped_by_customer'));
  for (const t of [501, 502]) assert.ok(calls.some(c => c[0] === 'tabs.remove' && c[1] === t), `tab ${t} closed`);
  assert.equal(store.enabled, false); assert.equal(s.readyState, 3);
  const n = sockets.length; await tick(1200); assert.equal(sockets.length, n, 'does not reconnect after a stop');
});

test('switching on again starts a clean session', async () => {
  await toggle(); await tick();
  assert.equal(store.enabled, true); assert.equal(sockets.length, 2);
  await toggle(); await tick(100);
  assert.equal(store.enabled, false);
});

const opened = async () => { const s = sockets[sockets.length - 1]; s.readyState = 1; await s.onopen(); return s; };

test('a pairing code is sent instead of the token, and the token the platform returns is kept and the code forgotten', async () => {
  store.pairCode = 'ABCD2345'; delete store.token;
  await toggle(); await tick();
  const s = await opened();
  assert.deepEqual(s.sent[0], { hello: 1, pair: 'ABCD2345', label: 'Chrome (mac)', version: '0.1.0' });
  await deliver(s, { welcome: 1, device_id: 'd1', token: 'fresh-token-from-platform' });
  assert.equal(store.token, 'fresh-token-from-platform'); assert.equal('pairCode' in store, false);
  s.close(); await tick(50); await toggle(); await tick(100);
});

test('a later connection uses the stored token, and a welcome without a token changes nothing', async () => {
  await toggle(); await tick();
  const s = await opened();
  assert.deepEqual(s.sent[0], { hello: 1, token: 'fresh-token-from-platform', version: '0.1.0' });
  await deliver(s, { welcome: 1, device_id: 'd1' });
  assert.equal(store.token, 'fresh-token-from-platform');
});

test('refused, revoked or replaced means switched off with a visible reason, not an endless retry; a dropped link just retries', async () => {
  const s = sockets[sockets.length - 1], n = sockets.length;
  s.drop(1006); await tick(1200); assert.equal(sockets.length, n + 1, 'a dropped link reconnects'); assert.equal(store.enabled, true);
  for (const [code, reason] of [[4401, 'unauthorized'], [4403, 'revoked'], [4409, 'replaced by another computer']]) {
    if (!store.enabled) { await toggle(); await tick(); }
    const sock = sockets[sockets.length - 1]; sock.readyState = 1; const before = sockets.length;
    sock.drop(code, reason); await tick(1300);
    assert.equal(store.enabled, false, String(code)); assert.equal(sockets.length, before, `${code}: no reconnect`);
    assert.equal(calls.filter(c => c[0] === 'badge').at(-1)[1], '!');
  }
});

test('the popup reports the state, and a bad pairing code is refused without touching anything', async () => {
  const idle = await popup({ type: 'status' });
  assert.deepEqual(idle, { enabled: false, connected: false, paired: true, pairing: false, tabs: [], panel: false });
  const n = sockets.length;
  assert.deepEqual(await popup({ type: 'pair', code: 'nope' }), { ok: false, error: 'bad_code' });
  assert.deepEqual(await popup({ type: 'pair', code: 'ABCD-2340' }), { ok: false, error: 'bad_code' });      // 0 is never in a code
  assert.equal(sockets.length, n); assert.equal('pairCode' in store, false);
  assert.deepEqual(await popup({ type: 'who-knows' }), { ok: false, error: 'unknown_message' });
});

test('a code typed in the popup is cleaned up, switches the extension on, and goes out as the pairing hello', async () => {
  const n = sockets.length;
  assert.deepEqual(await popup({ type: 'pair', code: ' abcd - 2345 ' }), { ok: true }); await tick(60);
  assert.equal(store.pairCode, 'ABCD2345'); assert.equal(store.enabled, true); assert.equal(sockets.length, n + 1);
  const s = await opened(); assert.equal(s.sent[0].pair, 'ABCD2345'); assert.equal('token' in s.sent[0], false);
  const live = await popup({ type: 'status' }); assert.equal(live.enabled, true); assert.equal(live.connected, true); assert.equal(live.pairing, true);
  await toggle(); await tick(100);
});

test('only the popup and the Lumina page may talk to it, and the page may only hand over a code', async () => {
  delete store.pairCode;
  const stranger = { id: 'some-other-extension' };
  assert.equal(await ask(chrome.runtime.onMessage, { type: 'toggle' }, stranger, 150), undefined); assert.equal(store.enabled, false);
  const lumina = { origin: 'https://getlumina.pro' };
  for (const [msg, sender] of [[{ type: 'pair', code: 'WXYZ6789' }, { origin: 'https://evil.example' }], [{ type: 'pair', code: 'WXYZ6789' }, { origin: 'https://getlumina.pro.evil.example' }],
                               [{ type: 'pair', code: 'WXYZ6789' }, { origin: 'http://getlumina.pro' }], [{ type: 'toggle' }, lumina], [{ type: 'status' }, lumina], [{ type: 'bridge', url: 'wss://evil.example' }, lumina], [null, lumina]])
    assert.equal(await ask(chrome.runtime.onMessageExternal, msg, sender, 150), undefined, JSON.stringify([msg, sender]));
  assert.equal(store.enabled, false); assert.equal('pairCode' in store, false);
  assert.deepEqual(await ask(chrome.runtime.onMessageExternal, { type: 'pair', code: 'bad' }, lumina), { ok: false, error: 'bad_code' });
  const n = sockets.length;
  assert.deepEqual(await ask(chrome.runtime.onMessageExternal, { type: 'pair', code: 'wxyz-6789', bridge: 'wss://evil.example/x' }, lumina), { ok: true }); await tick(60);
  assert.equal(store.pairCode, 'WXYZ6789'); assert.equal(sockets.length, n + 1);
  assert.equal(sockets.at(-1).url, 'wss://backend.getlumina.pro/v1/device', 'an address in the page\'s message is ignored');
  await toggle(); await tick(100);
});

test('a stored address is used only for production or this computer', async () => {
  for (const [bridge, expect] of [['wss://evil.example/v1/device', 'wss://backend.getlumina.pro/v1/device'], ['ws://evil.example:8765/device', 'wss://backend.getlumina.pro/v1/device'],
                                  ['ws://127.0.0.1.evil.example/device', 'wss://backend.getlumina.pro/v1/device'], ['ws://127.0.0.1:8765/device', 'ws://127.0.0.1:8765/device'],
                                  ['ws://localhost:9000/v1/device', 'ws://localhost:9000/v1/device'], [undefined, 'wss://backend.getlumina.pro/v1/device']]) {
    if (bridge === undefined) delete store.bridge; else store.bridge = bridge;
    await toggle(); await tick(); assert.equal(sockets.at(-1).url, expect, String(bridge));
    await toggle(); await tick(60);
  }
  delete store.bridge;
});
