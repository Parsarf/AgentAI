import { test, before, after } from 'node:test';
import assert from 'node:assert/strict';
import { existsSync } from 'node:fs';
import { join } from 'node:path';
import { tmpdir } from 'node:os';
import { startSite } from '../fixtures/site.mjs';

process.env.BROWSE_CHROME ||= '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
process.env.BROWSE_ALLOW_LOOPBACK = '1';
process.env.BROWSE_OUT = join(tmpdir(), 'lumina-browse-test');
const { Runner, urlAllowed, privateIp } = await import('../runner.mjs');

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

test('when a popup tab closes the agent carries on in the page that is still open', async () => {
  await r.handle({ cmd: 'open', url: base + '/' });
  let s = await r.handle({ cmd: 'snapshot' }); const promo = find(s.snapshot, 'Open promo');
  assert.equal((await r.handle({ cmd: 'act', action: 'click', ref: +promo[1], expect: { label: promo[4] } })).new_tab, true);
  assert.match(r.page.url(), /\/popup$/);
  const close = find((await r.handle({ cmd: 'snapshot' })).snapshot, 'Close promo');
  const a = await r.handle({ cmd: 'act', action: 'click', ref: +close[1], expect: { label: close[4] } });        // the popup closes itself
  assert.equal(a.ok, true, 'the click that closed the tab still succeeded');
  s = await r.handle({ cmd: 'snapshot' });
  assert.equal(s.ok, true); assert.match(s.url, /\/$/); assert.ok(find(s.snapshot, 'Add to cart'));                   // back on the shop, not stuck on a dead tab
  assert.equal(r.page.isClosed(), false);
});

test('a tab closed from outside, or the last tab closing, does not leave the runner holding a dead page', async () => {
  await r.handle({ cmd: 'open', url: base + '/' });
  const s = await r.handle({ cmd: 'snapshot' }); const promo = find(s.snapshot, 'Open promo');
  await r.handle({ cmd: 'act', action: 'click', ref: +promo[1], expect: { label: promo[4] } });
  await r.page.close();                                                                                     // closed from outside, as a site's own script would
  assert.equal(r.page.isClosed(), false, 'switched to the remaining page at once, before any command');
  assert.equal((await r.handle({ cmd: 'snapshot' })).ok, true);
  for (const p of r.context.pages()) await p.close();                                                       // every tab gone
  const again = await r.handle({ cmd: 'open', url: base + '/' });
  assert.equal(again.ok, true); assert.ok(find((await r.handle({ cmd: 'snapshot' })).snapshot, 'Add to cart'));   // a fresh page was made
});

test('private address ranges are recognised in every written form', () => {
  for (const bad of ['10.1.2.3', '127.0.0.2', '0.0.0.0', '169.254.169.254', '172.16.0.1', '172.31.255.255', '192.168.1.1', '100.64.0.1', '::1', '::', 'fd00::1', 'fe80::1', 'fc00::1', '::ffff:10.0.0.1', '::ffff:7f00:1'])
    assert.equal(privateIp(bad), true, bad);
  for (const ok of ['93.184.216.34', '8.8.8.8', '172.32.0.1', '100.128.0.1', '2606:2800:220:1:248:1893:25c8:1946', 'example.com']) assert.equal(privateIp(ok), false, ok);
});

test('a name that looks public but resolves to an internal address is refused, a public one is not, and a name that does not resolve is left to the browser', async () => {
  const answers = { 'private.example': [{ address: '10.0.0.5', family: 4 }], 'mixed.example': [{ address: '93.184.216.34', family: 4 }, { address: '192.168.1.9', family: 4 }],
    'public.example': [{ address: '93.184.216.34', family: 4 }], 'v6.example': [{ address: 'fd12::1', family: 6 }] };
  const asked = [];
  const lookup = async (host) => { asked.push(host); if (host === 'broken.example') throw new Error('ENOTFOUND'); if (host === 'hang.example') return new Promise(() => {}); return answers[host]; };
  const r2 = new Runner({ lookup }); await r2.start();
  try {
    for (const host of ['private.example', 'mixed.example', 'v6.example']) {
      const o = await r2.handle({ cmd: 'open', url: `http://${host}:${site.port}/` });
      assert.equal(o.ok, false, host); assert.ok(r2.blocked.some(u => u.includes(host)), `${host} was refused by the resolution check`);
    }
    r2.blocked = [];
    for (const host of ['public.example', 'broken.example']) {
      await r2.handle({ cmd: 'open', url: `http://${host}:${site.port}/` });                      // the browser itself cannot resolve these test names
      assert.deepEqual(r2.blocked, [], `${host} is not refused by us`);
    }
    const t0 = Date.now(); await r2.handle({ cmd: 'open', url: `http://hang.example:${site.port}/` });
    assert.ok(Date.now() - t0 < 12000, 'a resolver that never answers does not hang the page'); assert.deepEqual(r2.blocked, []);
    const before = asked.filter(h => h === 'private.example').length;
    await r2.handle({ cmd: 'open', url: `http://private.example:${site.port}/again` });
    assert.equal(asked.filter(h => h === 'private.example').length, before, 'answers are cached, not asked for on every request');
    await new Promise(res => setTimeout(res, 800));                                                  // let Chrome's own error page settle before the next navigation
    assert.equal((await r2.handle({ cmd: 'open', url: base + '/' })).ok, true, 'literal loopback is still judged by the test switch only');
  } finally { await r2.stop(); }
});

// ---- what the picture mode needs from the runner: the window as a JPEG, what is under a point, and clicking or typing at a point
const html = body => r.page.setContent(`<!doctype html><body style="margin:0">${body}</body>`);
const at = (left, top, width, height) => `position:absolute;left:${left}px;top:${top}px;width:${width}px;height:${height}px;box-sizing:border-box`;

test('snapshot says how far down the page is and which controls in the window have something on top of them', async () => {
  await r.handle({ cmd: 'open', url: base + '/' });
  await html(`<div style="height:3000px"></div><button style="${at(100, 100, 120, 40)}">Under panel</button><button style="${at(700, 100, 120, 40)}">Free button</button>
    <div style="position:fixed;top:0;left:0;width:500px;height:800px;background:#ddd;z-index:5"></div><button style="${at(100, 3200, 120, 40)}">Far below</button>`);
  const s = await r.handle({ cmd: 'snapshot' });
  const by = Object.fromEntries(s.elements.map(e => [e.label, e]));
  assert.equal(by['Under panel'].covered, true); assert.equal(by['Free button'].covered, false); assert.equal(by['Far below'].covered, null);   // out of the window: unknown
  assert.equal(s.scroll, 0); assert.ok(s.height > 3000); assert.equal(s.window, 800);
  await r.page.evaluate(() => window.scrollTo(0, 500));
  assert.equal((await r.handle({ cmd: 'snapshot' })).scroll, 500);
});

test('view returns the window as a JPEG inside the size limits JEV accepts, and keeps a copy when asked', async () => {
  await r.handle({ cmd: 'open', url: base + '/' });
  const v = await r.handle({ cmd: 'view', save: true });
  assert.equal(v.ok, true); assert.deepEqual(v.view, { w: 1280, h: 800 });
  const bytes = Buffer.from(v.data, 'base64'); assert.deepEqual([...bytes.subarray(0, 2)], [0xff, 0xd8]);
  assert.ok(v.width >= 280 && v.width <= 1568 && v.height >= 280 && v.height <= 1568 && v.width * v.height <= 2_458_624);
  assert.match(v.file, /^shot-\d{3}\.jpg$/); assert.ok(existsSync(join(process.env.BROWSE_OUT, v.file)));
  assert.equal((await r.handle({ cmd: 'view' })).file, undefined);
});

test('probe names what is under a point, even inside a shadow root, and never reveals a secret field', async () => {
  await r.handle({ cmd: 'open', url: base + '/' });
  await html(`<div id=host></div><input type=search placeholder="Search products" style="${at(100, 300, 300, 40)}"><input type=password aria-label="Pin" style="${at(100, 400, 300, 40)}">
    <script>const root = document.getElementById('host').attachShadow({ mode: 'open' }); const b = document.createElement('button'); b.textContent = 'Accept'; b.style.cssText = '${at(600, 100, 200, 60)}'; root.appendChild(b);</script>`);
  assert.deepEqual(await r.handle({ cmd: 'probe', x: 700, y: 130 }), { ok: true, hit: { tag: 'button', type: '', label: 'Accept', secret: false, editable: false, disabled: false } });
  assert.deepEqual((await r.handle({ cmd: 'probe', x: 200, y: 320 })).hit, { tag: 'input', type: 'search', label: 'Search products', secret: false, editable: true, disabled: false });
  const secret = (await r.handle({ cmd: 'probe', x: 200, y: 420 })).hit; assert.equal(secret.secret, true); assert.equal(secret.label, 'Password');
  assert.equal((await r.handle({ cmd: 'probe', x: 5000, y: 5 })).error, 'bad_coordinates');
});

test('click and type at a point act exactly there, and typing needs a real text field', async () => {
  await r.handle({ cmd: 'open', url: base + '/' });
  await html(`<button style="${at(100, 100, 150, 50)}" onclick="document.title='CLICKED'">Go</button><input type=search style="${at(100, 300, 300, 40)}"><p style="${at(100, 500, 300, 40)}">Just words</p>
    <input type=password style="${at(100, 600, 300, 40)}">`);
  assert.equal((await r.handle({ cmd: 'act', action: 'clickat', x: 170, y: 120 })).ok, true); assert.equal(await r.page.title(), 'CLICKED');
  assert.equal((await r.handle({ cmd: 'act', action: 'typeat', x: 200, y: 320, value: 'boxer briefs' })).ok, true); assert.equal(await r.page.inputValue('input[type=search]'), 'boxer briefs');
  assert.equal((await r.handle({ cmd: 'act', action: 'typeat', x: 200, y: 320, value: 'replaced' })).ok, true); assert.equal(await r.page.inputValue('input[type=search]'), 'replaced');   // typing replaces what was there
  assert.equal((await r.handle({ cmd: 'act', action: 'typeat', x: 150, y: 520, value: 'x' })).error, 'not_a_field');
  assert.equal((await r.handle({ cmd: 'act', action: 'typeat', x: 150, y: 620, value: 'secret' })).error, 'not_a_field');                // a password field is never typed into from a picture
  assert.equal(await r.page.inputValue('input[type=password]'), '');
  assert.equal((await r.handle({ cmd: 'act', action: 'clickat', x: 5000, y: 5 })).error, 'bad_coordinates');
  assert.equal((await r.handle({ cmd: 'act', action: 'typeat', x: 200, y: 320, value: 'x'.repeat(501) })).error, 'bad_value');
});
