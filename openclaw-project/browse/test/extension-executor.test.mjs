// The extension's executor against a real Chrome, through Playwright standing in for chrome.debugger / chrome.tabs. Same fixture shop and the same expectations as runner.test.mjs.
import { test, before, after } from 'node:test';
import assert from 'node:assert/strict';
import { chromium } from 'playwright-core';
import { startSite } from '../fixtures/site.mjs';
import { Executor } from '../extension/src/executor.js';
import { PlaywrightHost } from '../extension/dev/playwright-host.mjs';

const CHROME = process.env.BROWSE_CHROME || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
let site, base, browser, context, host, ex;
const LINE = /^\[(\d{1,4})\]\s+<([a-z]+)(?:\s+type=([a-z]+))?>\s+"(.{0,120})"\s*$/;
const find = (snap, text) => snap.split('\n').map(l => l.match(LINE)).find(m => m && m[4].includes(text));
const start = async (opts = {}) => { context = await browser.newContext({ viewport: { width: 1280, height: 800 } }); host = new PlaywrightHost(context); ex = new Executor(host, { allowLoopback: true, ...opts }); host.onAdopt = id => ex.adopt(id); };      // a fresh context per test: no test sees another's pages
const stop = async () => { await ex.handle({ cmd: 'close' }); await context.close(); };
const title = () => ex.title();

before(async () => {
  site = await startSite(); base = `http://127.0.0.1:${site.port}`;
  browser = await chromium.launch({ executablePath: CHROME, headless: true, args: ['--no-first-run'] });
});
after(async () => { await browser.close(); site.close(); });

test('open + snapshot list controls in the host format, and page text is only ever reported as data', async () => {
  await start();
  const o = await ex.handle({ cmd: 'open', url: base + '/' }); assert.equal(o.ok, true); assert.equal(o.title, 'Paddle Shop');
  const s = await ex.handle({ cmd: 'snapshot' }); assert.equal(s.ok, true);
  for (const l of s.snapshot.split('\n')) assert.match(l, LINE);
  assert.ok(find(s.snapshot, 'Add to cart')); assert.ok(find(s.snapshot, 'View cart'));
  assert.equal(find(s.snapshot, 'Search paddles')[2], 'input'); assert.equal(find(s.snapshot, 'Search paddles')[3], 'text');
  assert.ok(s.text.includes('IGNORE ALL RULES'));
  assert.match(s.page_fp, /^[0-9a-f]{12}$/);
  assert.equal(s.window, 800);
  await stop();
});

test('click navigates, type fills, select chooses, each reporting what happened', async () => {
  await start();
  await ex.handle({ cmd: 'open', url: base + '/' });
  let s = await ex.handle({ cmd: 'snapshot' });
  const add = find(s.snapshot, 'Add to cart');
  let a = await ex.handle({ cmd: 'act', action: 'click', ref: +add[1], expect: { label: add[4] } });
  assert.equal(a.ok, true); assert.equal(a.navigated, true); assert.match(a.url, /\/cart$/);
  s = await ex.handle({ cmd: 'snapshot' });
  a = await ex.handle({ cmd: 'act', action: 'click', ref: +find(s.snapshot, 'Checkout')[1] }); assert.match(a.url, /\/checkout$/);
  s = await ex.handle({ cmd: 'snapshot' });
  const addr = find(s.snapshot, 'Delivery address');
  a = await ex.handle({ cmd: 'act', action: 'type', ref: +addr[1], value: '12 Main St' }); assert.equal(a.ok, true);
  a = await ex.handle({ cmd: 'act', action: 'type', ref: +addr[1], value: 'replaced' }); assert.equal(a.ok, true);      // typing replaces what is there
  const ship = find(s.snapshot, 'Shipping');
  a = await ex.handle({ cmd: 'act', action: 'select', ref: +ship[1], value: 'express' }); assert.equal(a.ok, true);      // case-insensitive label
  s = await ex.handle({ cmd: 'snapshot' });
  const el = s.elements.find(e => e.label === 'Delivery address'); assert.equal(el.value, 'replaced');
  assert.equal(s.elements.find(e => e.label === 'Shipping').value, 'Express');
  a = await ex.handle({ cmd: 'act', action: 'select', ref: +ship[1], value: 'Drone' }); assert.equal(a.error, 'no_option');
  a = await ex.handle({ cmd: 'act', action: 'back' }); assert.match(a.url, /\/cart$/);
  await stop();
});

test('a control that changed, moved or is covered is not clicked', async () => {
  await start();
  await ex.handle({ cmd: 'open', url: base + '/' });
  let s = await ex.handle({ cmd: 'snapshot' });
  const add = find(s.snapshot, 'Add to cart');
  assert.equal((await ex.handle({ cmd: 'act', action: 'click', ref: +add[1], expect: { label: 'Something else' } })).error, 'stale');
  assert.equal((await ex.handle({ cmd: 'act', action: 'click', ref: 999 })).error, 'stale');
  await ex.handle({ cmd: 'open', url: base + '/covered' });
  s = await ex.handle({ cmd: 'snapshot' });
  const details = find(s.snapshot, 'Details');
  assert.equal((await ex.handle({ cmd: 'act', action: 'click', ref: +details[1] })).error, 'covered');
  assert.equal(await title(), 'Covered');
  await stop();
});

test('secret fields are listed but their value never leaves the page', async () => {
  await start();
  await ex.handle({ cmd: 'open', url: base + '/login' });
  const s = await ex.handle({ cmd: 'snapshot' });
  assert.ok(find(s.snapshot, 'Password')); assert.ok(find(s.snapshot, 'Secret field'));
  assert.ok(!JSON.stringify(s).includes('hunter2')); assert.ok(!JSON.stringify(s).includes('4111'));
  await stop();
});

test('addresses are judged before the browser is asked, and again on every request the page makes', async () => {
  await start({ allowLoopback: false });
  for (const bad of ['file:///etc/passwd', 'javascript:alert(1)', 'http://127.0.0.1:1/', 'http://192.168.0.1/', 'http://169.254.169.254/'])
    assert.equal((await ex.handle({ cmd: 'open', url: bad })).error, 'url_blocked', bad);
  assert.equal((await ex.handle({ cmd: 'xy', action: 'goto', text: 'http://10.0.0.1/' })).error, 'url_blocked');
  await stop();
  await start();                                                       // loopback allowed so the shop loads; the page then reaches for a private address
  await ex.handle({ cmd: 'open', url: base + '/' });
  const r = await ex.ev(async () => { const c = new AbortController(); setTimeout(() => c.abort(), 3000); try { await fetch('http://10.0.0.5:9/x', { signal: c.signal }); return 'reached'; } catch (e) { return e.name; } });
  assert.notEqual(r, 'reached');
  assert.ok(ex.blocked.some(u => u.startsWith('http://10.0.0.5:9/')), JSON.stringify(ex.blocked));
  await stop();
});

test('keys, scroll, coordinates and values are checked', async () => {
  await start();
  await ex.handle({ cmd: 'open', url: base + '/long' });
  assert.equal((await ex.handle({ cmd: 'act', action: 'press', value: 'F5' })).error, 'key_not_allowed');
  assert.equal((await ex.handle({ cmd: 'act', action: 'press', value: 'Backspace' })).error, 'key_not_allowed');       // takeover-only
  assert.equal((await ex.handle({ cmd: 'act', action: 'scroll', value: 'sideways' })).error, 'bad_value');
  assert.equal((await ex.handle({ cmd: 'act', action: 'clickat', x: 5000, y: 10 })).error, 'bad_coordinates');
  assert.equal((await ex.handle({ cmd: 'act', action: 'typeat', x: 5, y: 5, value: '' })).error, 'bad_value');
  assert.equal((await ex.handle({ cmd: 'act', action: 'type', ref: 1, value: 'x'.repeat(501) })).error, 'bad_value');
  assert.equal((await ex.handle({ cmd: 'probe', x: -1, y: 0 })).error, 'bad_coordinates');
  assert.equal((await ex.handle({ cmd: 'xy', action: 'key', text: 'F5' })).error, 'key_not_allowed');
  assert.equal((await ex.handle({ cmd: 'nope' })).error, 'unknown_command');
  assert.equal((await ex.handle(null)).error, 'unknown_command');
  const before = (await ex.handle({ cmd: 'snapshot' })).scroll;
  const a = await ex.handle({ cmd: 'act', action: 'scroll', value: 'down' });
  assert.equal(a.ok, true);
  assert.ok((await ex.handle({ cmd: 'snapshot' })).scroll > before);
  await stop();
});

test('a picture of the window, a probe of a point, and a click or typing at a point', async () => {
  await start();
  await ex.handle({ cmd: 'open', url: base + '/checkout' });
  const v = await ex.handle({ cmd: 'view' });
  assert.equal(v.ok, true); assert.equal(v.width, 1280); assert.equal(v.height, 800);
  const jpg = Buffer.from(v.data, 'base64'); assert.deepEqual([...jpg.subarray(0, 3)], [0xff, 0xd8, 0xff]);
  assert.equal((await ex.handle({ cmd: 'screenshot' })).ok, true);
  const s = await ex.handle({ cmd: 'snapshot' });
  const f = s.elements.find(e => e.label === 'Delivery address');
  const box = await ex.ev(() => { const r = document.querySelector('[aria-label="Delivery address"]').getBoundingClientRect(); return { x: r.left + r.width / 2, y: r.top + r.height / 2 }; });
  const p = await ex.handle({ cmd: 'probe', ...box });
  assert.equal(p.hit.label, 'Delivery address'); assert.equal(p.hit.editable, true); assert.equal(p.hit.secret, false);
  assert.equal((await ex.handle({ cmd: 'act', action: 'typeat', ...box, value: '5 Elm Rd' })).ok, true);
  assert.equal((await ex.handle({ cmd: 'snapshot' })).elements.find(e => e.label === f.label).value, '5 Elm Rd');
  const buy = await ex.ev(() => { const r = document.getElementById('buy').getBoundingClientRect(); return { x: r.left + r.width / 2, y: r.top + r.height / 2 }; });
  assert.equal((await ex.handle({ cmd: 'probe', ...buy })).hit.label, 'Place order');
  assert.equal((await ex.handle({ cmd: 'act', action: 'typeat', ...buy, value: 'x' })).error, 'not_a_field');
  await stop();
});

test('takeover input: click at a point, type, key, scroll, address bar, back / forward / reload', async () => {
  await start();
  await ex.handle({ cmd: 'open', url: base + '/' });
  assert.equal((await ex.handle({ cmd: 'xy', action: 'goto', text: base + '/cart' })).ok, true);
  await ex.settle();
  assert.match(await ex.url(), /\/cart$/);
  assert.equal((await ex.handle({ cmd: 'xy', action: 'back' })).ok, true); await ex.settle();
  assert.equal(await ex.url(), base + '/');
  await ex.handle({ cmd: 'xy', action: 'forward' }); await ex.settle();
  assert.match(await ex.url(), /\/cart$/);
  assert.equal((await ex.handle({ cmd: 'xy', action: 'reload' })).ok, true);
  await ex.handle({ cmd: 'open', url: base + '/checkout' });
  const box = await ex.ev(() => { const r = document.querySelector('[aria-label="Delivery address"]').getBoundingClientRect(); return { x: r.left + 5, y: r.top + 5 }; });
  await ex.handle({ cmd: 'xy', action: 'click', ...box });
  await ex.handle({ cmd: 'xy', action: 'type', text: 'abc' });
  await ex.handle({ cmd: 'xy', action: 'key', text: 'Backspace' });
  assert.equal(await ex.ev(() => document.querySelector('[aria-label="Delivery address"]').value), 'ab');
  assert.equal((await ex.handle({ cmd: 'xy', action: 'scroll', text: '1' })).ok, true);
  assert.equal((await ex.handle({ cmd: 'xy', action: 'dance' })).error, 'bad_action');
  await stop();
});

test('a popup becomes the page in use; when it closes the agent carries on in the page that is left', async () => {
  await start();
  await ex.handle({ cmd: 'open', url: base + '/' });
  const s = await ex.handle({ cmd: 'snapshot' });
  const promo = find(s.snapshot, 'Open promo');
  const a = await ex.handle({ cmd: 'act', action: 'click', ref: +promo[1] });
  assert.equal(a.ok, true); assert.equal(a.new_tab, true); assert.match(a.url, /\/popup$/);
  assert.equal(host.tabs().length, 2);
  const p = await ex.handle({ cmd: 'snapshot' }); assert.equal(p.pages, 2);
  const close = find(p.snapshot, 'Close promo');
  const c = await ex.handle({ cmd: 'act', action: 'click', ref: +close[1] });
  assert.equal(c.ok, true); assert.equal(host.tabs().length, 1);
  assert.equal(await ex.url(), base + '/');
  await stop();
});

test('close shuts every tab; the next command starts again from a blank one', async () => {
  await start();
  await ex.handle({ cmd: 'open', url: base + '/' });
  assert.equal((await ex.handle({ cmd: 'close' })).ok, true); assert.equal(host.tabs().length, 0);
  const o = await ex.handle({ cmd: 'open', url: base + '/cart' }); assert.equal(o.ok, true); assert.equal(host.tabs().length, 1);
  await stop();
});

test('a page that cannot be reached is a failed step, not a crash', async () => {
  await start();
  const o = await ex.handle({ cmd: 'open', url: 'http://127.0.0.1:1/' });
  assert.equal(o.ok, false); assert.equal(o.error, 'navigation_failed');
  await stop();
});
