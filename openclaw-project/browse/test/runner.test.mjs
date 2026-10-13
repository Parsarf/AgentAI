import { test, before, after } from 'node:test';
import assert from 'node:assert/strict';
import { existsSync } from 'node:fs';
import { join } from 'node:path';
import { tmpdir } from 'node:os';
import { startSite } from '../fixtures/site.mjs';

process.env.BROWSE_CHROME ||= '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
process.env.BROWSE_ALLOW_LOOPBACK = '1';
process.env.BROWSE_OUT = join(tmpdir(), 'lumina-browse-test');
const { Runner, urlAllowed } = await import('../runner.mjs');

let site, r, base;
before(async () => { site = await startSite(); base = `http://127.0.0.1:${site.port}`; r = new Runner(); await r.start(); });
after(async () => { await r.stop(); site.close(); });
const LINE = /^\[(\d{1,4})\]\s+<([a-z]+)(?:\s+type=([a-z]+))?>\s+"(.{0,120})"\s*$/;
const find = (snap, text) => snap.split('\n').map(l => l.match(LINE)).find(m => m && m[4].includes(text));

test('url policy allows public web only', () => {
  for (const bad of ['file:///etc/passwd', 'javascript:alert(1)', 'data:text/html,hi', 'chrome://settings', 'http://localhost/', 'http://127.0.0.1/', 'http://10.1.2.3/', 'http://192.168.1.1/', 'http://169.254.169.254/latest', 'http://172.20.0.1/', 'http://[::1]/', 'http://user:pw@example.com/', 'http://printer.local/', 'ftp://example.com'])
    assert.equal(urlAllowed(bad), false, bad);
  for (const ok of ['https://example.com/', 'http://93.184.216.34/']) assert.equal(urlAllowed(ok), true, ok);
  assert.equal(urlAllowed('http://127.0.0.1:1/', true), true);   // test-only switch
});

test('open + snapshot lists interactive elements in the host format and never trusts page text', async () => {
  const o = await r.handle({ cmd: 'open', url: base + '/' }); assert.equal(o.ok, true);
  const s = await r.handle({ cmd: 'snapshot' }); assert.equal(s.ok, true);
  for (const l of s.snapshot.split('\n')) assert.match(l, LINE);
  assert.ok(find(s.snapshot, 'Add to cart')); assert.ok(find(s.snapshot, 'View cart')); assert.ok(find(s.snapshot, 'Search paddles'));
  assert.equal(find(s.snapshot, 'Search paddles')[2], 'input'); assert.equal(find(s.snapshot, 'Search paddles')[3], 'text');
  assert.ok(s.text.includes('IGNORE ALL RULES'));                       // reported as DATA to the host; the runner never acts on it
});

test('click navigates, type fills, select chooses, and each action reports what happened', async () => {
  await r.handle({ cmd: 'open', url: base + '/' });
  let s = await r.handle({ cmd: 'snapshot' });
  const add = find(s.snapshot, 'Add to cart');
  let a = await r.handle({ cmd: 'act', action: 'click', ref: +add[1], expect: { label: add[4] } });
  assert.equal(a.ok, true); assert.equal(a.navigated, true); assert.match(a.url, /\/cart$/);
  assert.equal(site.cart.length, 1);
  s = await r.handle({ cmd: 'snapshot' }); const co = find(s.snapshot, 'Checkout');
  await r.handle({ cmd: 'act', action: 'click', ref: +co[1], expect: { label: co[4] } });
  s = await r.handle({ cmd: 'snapshot' });
  const addr = find(s.snapshot, 'Delivery address'); const ship = find(s.snapshot, 'Shipping');
  assert.equal((await r.handle({ cmd: 'act', action: 'type', ref: +addr[1], value: '1 Main St', expect: { label: addr[4] } })).ok, true);
  assert.equal((await r.handle({ cmd: 'act', action: 'select', ref: +ship[1], value: 'Express', expect: { label: ship[4] } })).ok, true);
  assert.equal(await r.page.inputValue('input[name=addr]'), '1 Main St'); assert.equal(await r.page.inputValue('select'), 'Express');
});

test('a moved or renamed element is stale and nothing happens', async () => {
  await r.handle({ cmd: 'open', url: base + '/' });
  const s = await r.handle({ cmd: 'snapshot' }); const add = find(s.snapshot, 'Add to cart');
  const before = site.cart.length;
  const wrong = await r.handle({ cmd: 'act', action: 'click', ref: +add[1], expect: { label: 'Something else' } });
  assert.deepEqual([wrong.ok, wrong.error], [false, 'stale']);
  await r.page.evaluate(() => { document.body.innerHTML = '<p>re-rendered</p>'; });
  const gone = await r.handle({ cmd: 'act', action: 'click', ref: +add[1], expect: { label: add[4] } });
  assert.deepEqual([gone.ok, gone.error], [false, 'stale']); assert.equal(site.cart.length, before);
});

test('unsafe requests are refused: bad urls, long values, odd keys, unknown actions, private subresources', async () => {
  assert.equal((await r.handle({ cmd: 'open', url: 'file:///etc/passwd' })).error, 'url_blocked');
  assert.equal((await r.handle({ cmd: 'act', action: 'press', value: 'Control+Shift+I' })).error, 'key_not_allowed');
  assert.equal((await r.handle({ cmd: 'act', action: 'hover', ref: 1 })).error, 'bad_action');
  assert.equal((await r.handle({ cmd: 'nope' })).error, 'unknown_command');
  await r.handle({ cmd: 'open', url: base + '/checkout' });
  const s = await r.handle({ cmd: 'snapshot' }); const addr = find(s.snapshot, 'Delivery address');
  assert.equal((await r.handle({ cmd: 'act', action: 'type', ref: +addr[1], value: 'x'.repeat(501) })).error, 'bad_value');
});

test('new tabs are tracked, screenshots are written, back works', async () => {
  await r.handle({ cmd: 'open', url: base + '/' });
  const s = await r.handle({ cmd: 'snapshot' }); const promo = find(s.snapshot, 'Open promo');
  const a = await r.handle({ cmd: 'act', action: 'click', ref: +promo[1], expect: { label: promo[4] } });
  assert.equal(a.ok, true); assert.equal(a.new_tab, true);
  const shot = await r.handle({ cmd: 'screenshot' }); assert.equal(shot.ok, true); assert.ok(existsSync(join(process.env.BROWSE_OUT, shot.file)));
});

test('takeover commands click, type and scroll by coordinates with strict bounds', async () => {
  await r.handle({ cmd: 'open', url: base + '/checkout' });
  const box = await r.page.locator('input[name=addr]').boundingBox();
  assert.equal((await r.handle({ cmd: 'xy', action: 'click', x: box.x + 5, y: box.y + 5 })).ok, true);
  assert.equal((await r.handle({ cmd: 'xy', action: 'type', text: 'Hello' })).ok, true);
  assert.equal(await r.page.inputValue('input[name=addr]'), 'Hello');
  assert.equal((await r.handle({ cmd: 'xy', action: 'key', text: 'Backspace' })).ok, true); assert.equal(await r.page.inputValue('input[name=addr]'), 'Hell');
  assert.equal((await r.handle({ cmd: 'xy', action: 'click', x: -1, y: 5 })).error, 'bad_coordinates');
  assert.equal((await r.handle({ cmd: 'xy', action: 'click', x: 5000, y: 5 })).error, 'bad_coordinates');
  assert.equal((await r.handle({ cmd: 'xy', action: 'key', text: 'Control+W' })).error, 'key_not_allowed');
  assert.equal((await r.handle({ cmd: 'xy', action: 'exec', x: 1, y: 1 })).error, 'bad_action');
  assert.equal((await r.handle({ cmd: 'xy', action: 'type', text: 'x'.repeat(501) })).error, 'bad_value');
});
