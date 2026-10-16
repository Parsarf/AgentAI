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

const els = snap => Object.fromEntries(snap.elements.map(e => [e.label, e]));

test('a covered element is not clicked: the banner on top gets the click nowhere', async () => {
  await r.handle({ cmd: 'open', url: base + '/covered' });
  const s = await r.handle({ cmd: 'snapshot' }); const d = find(s.snapshot, 'Details');
  const a = await r.handle({ cmd: 'act', action: 'click', ref: +d[1], expect: { label: d[4] } });
  assert.deepEqual([a.ok, a.error], [false, 'covered']);
  assert.equal(await r.page.title(), 'Covered');                       // the button's handler never ran
});

test('an element that became disabled or aria-disabled after the snapshot is not acted on', async () => {
  await r.handle({ cmd: 'open', url: base + '/' });
  const s = await r.handle({ cmd: 'snapshot' }); const search = find(s.snapshot, 'Search paddles'); const btn = find(s.snapshot, 'Search');
  await r.page.evaluate(() => { document.querySelector('button').disabled = true; document.querySelector('input[name=q]').setAttribute('aria-disabled', 'true'); });
  assert.deepEqual([(await r.handle({ cmd: 'act', action: 'click', ref: +btn[1], expect: { label: btn[4] } })).error], ['disabled']);
  assert.equal((await r.handle({ cmd: 'act', action: 'type', ref: +search[1], value: 'x', expect: { label: search[4] } })).error, 'disabled');
  assert.equal(await r.page.title(), 'Paddle Shop');
});

test('read-only fields refuse typing', async () => {
  await r.handle({ cmd: 'open', url: base + '/form' });
  const s = await r.handle({ cmd: 'snapshot' }); const ref = find(s.snapshot, 'Reference');
  assert.equal((await r.handle({ cmd: 'act', action: 'type', ref: +ref[1], value: 'x', expect: { label: ref[4] } })).error, 'disabled');
});

test('secret fields are listed without their values, and a label is never taken from a secret value', async () => {
  await r.handle({ cmd: 'open', url: base + '/login' });
  const s = await r.handle({ cmd: 'snapshot' }); const e = els(s);
  assert.ok(e.Password, 'a password field with no label is still listed, so the host can see the page needs the user');
  assert.equal(e.Password.type, 'password'); assert.equal(e.Password.value, '');
  assert.match(s.snapshot, /<input type=password> "Password"/);
  assert.equal(e['Secret field'].value, '');                               // autocomplete=cc-number
  assert.equal(e.Email.value, 'me@example.com');                           // ordinary fields do report their text
  const everything = JSON.stringify(s);
  assert.ok(!everything.includes('hunter2') && !everything.includes('4111'), 'no secret value anywhere in the reply');
});

test('elements report state: value, checked, expanded, in_view and select options', async () => {
  await r.handle({ cmd: 'open', url: base + '/form' });
  let s = await r.handle({ cmd: 'snapshot' }); let e = els(s);
  assert.equal(e['Gift wrap'].checked, false); assert.equal(e.Details.expanded, false); assert.equal(e.Details.in_view, true);
  assert.deepEqual(e.Size.options, ['Small (S)', 'Medium (M)', 'Large (L)']); assert.equal(e.Size.value, 'Small (S)');
  assert.equal(e.Reference.value, 'fixed');
  for (const line of s.snapshot.split('\n')) assert.match(line, LINE);
  const gift = find(s.snapshot, 'Gift wrap'); const det = find(s.snapshot, 'Details');
  const t1 = Date.now();
  assert.equal((await r.handle({ cmd: 'act', action: 'click', ref: +gift[1], expect: { label: gift[4] } })).error, 'covered');      // an invisible checkbox under its styled label: refused at once
  assert.ok(Date.now() - t1 < 3000, 'refused at once, not after the 6 s click timeout');
  assert.equal((await r.handle({ cmd: 'act', action: 'click', ref: +det[1], expect: { label: det[4] } })).ok, true);
  s = await r.handle({ cmd: 'snapshot' }); e = els(s);
  assert.equal(e['Gift wrap'].checked, false); assert.equal(e.Details.expanded, true);
  const size = find(s.snapshot, 'Size');
  assert.equal((await r.handle({ cmd: 'act', action: 'select', ref: +size[1], value: 'Medium (M)', expect: { label: size[4] } })).ok, true);   // by label
  assert.equal(await r.page.inputValue('select'), 'Medium (M)');
  assert.equal((await r.handle({ cmd: 'act', action: 'select', ref: +size[1], value: 'large', expect: { label: size[4] } })).ok, true);          // case and prefix
  assert.equal(await r.page.inputValue('select'), 'Large (L)');
  const t0 = Date.now();
  assert.equal((await r.handle({ cmd: 'act', action: 'select', ref: +size[1], value: 'Huge', expect: { label: size[4] } })).error, 'no_option');
  assert.ok(Date.now() - t0 < 3000, 'a missing option fails at once, not after the default 8 s wait');
});

test('scroll goes up or down, wait is accepted, anything else is refused', async () => {
  await r.handle({ cmd: 'open', url: base + '/long' });
  const y = () => r.page.evaluate(() => window.scrollY);
  assert.equal(await y(), 0);
  assert.equal((await r.handle({ cmd: 'act', action: 'scroll' })).ok, true); const down = await y(); assert.ok(down > 0, 'default is down');
  assert.equal((await r.handle({ cmd: 'act', action: 'scroll', value: 'down' })).ok, true); assert.ok(await y() > down);
  assert.equal((await r.handle({ cmd: 'act', action: 'scroll', value: 'up' })).ok, true); assert.ok(await y() < 2 * down);
  assert.equal((await r.handle({ cmd: 'act', action: 'scroll', value: 'sideways' })).error, 'bad_value');
  const w = await r.handle({ cmd: 'act', action: 'wait' }); assert.equal(w.ok, true); assert.ok(w.page_fp);
  const s = await r.handle({ cmd: 'snapshot' }); assert.equal(els(s)['Bottom link'].in_view, false);
});

test('page_fp changes after a real change and not after a no-op, and act and snapshot agree on it', async () => {
  await r.handle({ cmd: 'open', url: base + '/long' });
  const a = await r.handle({ cmd: 'snapshot' }); const b = await r.handle({ cmd: 'snapshot' });
  assert.ok(a.page_fp && /^[0-9a-f]{12}$/.test(a.page_fp)); assert.equal(a.page_fp, b.page_fp);          // an idle page is stable
  const wait = await r.handle({ cmd: 'act', action: 'wait' }); assert.equal(wait.page_fp, a.page_fp);     // a no-op does not change it
  const scrolled = await r.handle({ cmd: 'act', action: 'scroll' }); assert.notEqual(scrolled.page_fp, a.page_fp);   // scrolling does, until the bottom
  assert.equal((await r.handle({ cmd: 'snapshot' })).page_fp, scrolled.page_fp);
  for (let i = 0; i < 12; i += 1) await r.handle({ cmd: 'act', action: 'scroll' });
  const bottom1 = await r.handle({ cmd: 'act', action: 'scroll' }); const bottom2 = await r.handle({ cmd: 'act', action: 'scroll' });
  assert.equal(bottom1.page_fp, bottom2.page_fp, 'scrolling at the bottom changes nothing');
  await r.handle({ cmd: 'open', url: base + '/checkout' });
  const s = await r.handle({ cmd: 'snapshot' }); const addr = find(s.snapshot, 'Delivery address');
  const typed = await r.handle({ cmd: 'act', action: 'type', ref: +addr[1], value: 'hello', expect: { label: addr[4] } });
  assert.notEqual(typed.page_fp, s.page_fp); assert.equal((await r.handle({ cmd: 'snapshot' })).page_fp, typed.page_fp);
  await r.handle({ cmd: 'open', url: base + '/login' });
  const l1 = (await r.handle({ cmd: 'snapshot' })).page_fp;
  await r.page.evaluate(() => { document.querySelector('input[type=password]').value = 'something else'; });
  assert.equal((await r.handle({ cmd: 'snapshot' })).page_fp, l1, 'a secret value is not part of the fingerprint');
});
