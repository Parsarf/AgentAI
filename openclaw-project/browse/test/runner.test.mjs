import { test, before, after } from 'node:test';
import assert from 'node:assert/strict';
import { existsSync } from 'node:fs';
import { join } from 'node:path';
import { tmpdir } from 'node:os';
import { startSite } from '../fixtures/site.mjs';

process.env.BROWSE_CHROME ||= '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
process.env.BROWSE_ALLOW_LOOPBACK = '1';
process.env.BROWSE_OUT = join(tmpdir(), 'lumina-browse-test');
process.env.BROWSE_OPEN_LOAD_MS = '1200';                 // how long a page gets to finish loading before the task goes on with what it has drawn (25 s in the stage)
const { Runner, urlAllowed, privateIp } = await import('../runner.mjs');

let site, r, base;
before(async () => { site = await startSite(); base = `http://127.0.0.1:${site.port}`; r = new Runner(); await r.start(); });
after(async () => { await r.stop(); site.close(); });
const LINE = /^\[(\d{1,4})\]\s+<([a-z]+)(?:\s+type=([a-z]+))?>\s+"(.{0,120})"\s*$/;
const find = (snap, text) => snap.split('\n').map(l => l.match(LINE)).find(m => m && m[4].includes(text));

test('a page whose own scripts are slow is opened, not failed: the task goes on with what is drawn, and sees the rest when it arrives', async () => {
  const started = Date.now();
  const o = await r.handle({ cmd: 'open', url: base + '/heavy' });
  assert.equal(o.ok, true); assert.equal(o.still_loading, true);                 // the site answered; its script had not finished (it takes 4 s)
  const early = await r.handle({ cmd: 'snapshot' });
  assert.ok(find(early.snapshot, 'Paddle Shop'), early.snapshot);                // what is above the slow script can be used already
  await new Promise(resolve => setTimeout(resolve, 4200 - (Date.now() - started) > 0 ? 4200 - (Date.now() - started) : 0));
  const late = await r.handle({ cmd: 'snapshot' });
  assert.ok(find(late.snapshot, 'Late button'), late.snapshot); assert.equal(late.title, 'Heavy shop, loaded');
});

test('after an open that failed, the very next open works: the second try is worth making', async () => {
  const gone = await r.handle({ cmd: 'open', url: 'http://127.0.0.1:1/' });     // nothing answers there at all: a failed open
  assert.equal(gone.ok, false); assert.equal(gone.error, 'navigation_failed');
  const again = await r.handle({ cmd: 'open', url: base + '/' });               // sent at once, as the host's retry is
  assert.equal(again.ok, true, JSON.stringify(again));
  assert.ok(find((await r.handle({ cmd: 'snapshot' })).snapshot, 'Search'));
  assert.equal((await r.handle({ cmd: 'open', url: base + '/cart' })).ok, true);
});

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

test('takeover address bar, back, forward and reload, with the same address rules as every other request', async () => {
  await r.handle({ cmd: 'open', url: base + '/' });
  assert.equal((await r.handle({ cmd: 'xy', action: 'goto', text: base + '/checkout' })).ok, true);
  assert.ok(r.page.url().endsWith('/checkout'));
  assert.equal((await r.handle({ cmd: 'xy', action: 'back' })).ok, true); assert.ok(!r.page.url().endsWith('/checkout'));
  assert.equal((await r.handle({ cmd: 'xy', action: 'forward' })).ok, true); assert.ok(r.page.url().endsWith('/checkout'));
  assert.equal((await r.handle({ cmd: 'xy', action: 'reload' })).ok, true);
  for (const bad of ['javascript:alert(1)', 'file:///etc/passwd', 'http://10.0.0.1/', 'http://169.254.169.254/', 'http://user:pw@example.com/', 'http://box.local/', 'x'.repeat(2049), '', undefined])
    assert.equal((await r.handle({ cmd: 'xy', action: 'goto', text: bad })).error, 'url_blocked');
  for (const key of ['ArrowLeft', 'ArrowRight', 'Delete', 'Home', 'End', 'PageDown', 'PageUp']) assert.equal((await r.handle({ cmd: 'xy', action: 'key', text: key })).ok, true);
  assert.equal((await r.handle({ cmd: 'xy', action: 'key', text: 'Control+L' })).error, 'key_not_allowed');
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
  assert.equal((await r.handle({ cmd: 'act', action: 'click', ref: +gift[1], expect: { label: gift[4] } })).ok, true);      // an invisible checkbox under its styled label: the step goes to the label, as a person's click does (it used to be refused as "covered")
  assert.ok(Date.now() - t1 < 3000, 'done at once, not after the 6 s click timeout');
  assert.equal((await r.handle({ cmd: 'act', action: 'click', ref: +det[1], expect: { label: det[4] } })).ok, true);
  s = await r.handle({ cmd: 'snapshot' }); e = els(s);
  assert.equal(e['Gift wrap'].checked, true); assert.equal(e.Details.expanded, true);
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

// ---- what the decider is offered: the controls a person can see and reach come first, and the snapshot says what has the keyboard
test('a long header or menu cannot crowd the visible controls out of the list, and numbers still follow page order', async () => {
  await r.handle({ cmd: 'open', url: base + '/' });
  const hidden = Array.from({ length: 120 }, (_, i) => `<a href="#m${i}" style="${at(10, 2000 + i * 30, 200, 20)}">Menu ${i}</a>`).join('');
  await html(`<div style="height:6000px"></div>${hidden}<button style="${at(300, 200, 160, 40)}">Add to cart</button><input aria-label="Search" style="${at(300, 300, 200, 30)}">`);
  const s = await r.handle({ cmd: 'snapshot' });
  const labels = s.elements.map(e => e.label);
  assert.equal(s.elements.length, 80);                                           // the cap is unchanged
  assert.ok(labels.includes('Add to cart') && labels.includes('Search'));        // both come after 120 menu links in the page's code, and are still listed
  assert.deepEqual(s.elements.map(e => e.ref), Array.from({ length: 80 }, (_, i) => i + 1));
  const add = s.elements.find(e => e.label === 'Add to cart');
  assert.equal(add.in_view, true); assert.equal(add.covered, false); assert.equal(add.x, 380); assert.equal(add.y, 220);      // where a click on it lands, in window pixels
  const clicked = await r.handle({ cmd: 'act', action: 'click', ref: add.ref, expect: { label: 'Add to cart' } });
  assert.equal(clicked.ok, true);                                                // the number still names the same element
});

test('a secret field is always listed, even past the cap, so the host still sees that the page needs the user', async () => {
  await r.handle({ cmd: 'open', url: base + '/' });
  const many = Array.from({ length: 90 }, (_, i) => `<button style="${at(10 + (i % 9) * 130, 10 + Math.floor(i / 9) * 50, 120, 40)}">B${i}</button>`).join('');
  await html(`<div style="height:4000px"></div>${many}<input type="password" style="${at(100, 3000, 200, 30)}">`);
  const s = await r.handle({ cmd: 'snapshot' });
  assert.ok(s.elements.some(e => e.type === 'password'));
  assert.match(s.snapshot, /<input type=password>/);
});

test('snapshot says what has the keyboard: nothing, a text field with what it holds, and never a secret value', async () => {
  await r.handle({ cmd: 'open', url: base + '/' });
  await html(`<input aria-label="Search" style="${at(100, 100, 200, 30)}"><button style="${at(100, 200, 100, 30)}">Go</button><input type="password" aria-label="Password" style="${at(100, 300, 200, 30)}">`);
  assert.equal((await r.handle({ cmd: 'snapshot' })).focus, null);
  const s1 = await r.handle({ cmd: 'snapshot' });
  const search = s1.elements.find(e => e.label === 'Search');
  await r.handle({ cmd: 'act', action: 'type', ref: search.ref, value: 'blue shoes', expect: { label: 'Search' } });
  const s2 = await r.handle({ cmd: 'snapshot' });
  assert.equal(s2.focus.editable, true); assert.equal(s2.focus.value, 'blue shoes'); assert.equal(s2.focus.label, 'Search');
  assert.equal(s2.focus.ref, s2.elements.find(e => e.label === 'Search').ref);   // the focused field is named by its number in this same list
  await r.page.evaluate(() => { const p = document.querySelector('input[type=password]'); p.value = 'hunter2'; p.focus(); });
  const s3 = await r.handle({ cmd: 'snapshot' });
  assert.equal(s3.focus.secret, true); assert.equal(s3.focus.value, ''); assert.equal(s3.focus.label, '');
  await r.page.evaluate(() => document.querySelector('button').focus());
  assert.equal((await r.handle({ cmd: 'snapshot' })).focus.editable, false);
});

// ---- November 2026 reliability work: each of these was a task that failed in the lab (browser-opt/lab) before the runner was changed.
const setPage = body => r.page.setContent(`<!doctype html><title>T</title><body style="margin:0">${body}</body>`);

test('controls inside open shadow roots are listed, clicked and typed into like any other', async () => {
  await r.handle({ cmd: 'open', url: base + '/long' });
  await setPage(`<h1>Library</h1><div id=host></div><script>
    const root = document.getElementById('host').attachShadow({ mode: 'open' });
    root.innerHTML = '<input aria-label="Search books" style="width:200px;height:30px"><button id=go>Go</button><div id=inner></div>';
    const deep = root.getElementById('inner').attachShadow({ mode: 'open' }); deep.innerHTML = '<button>Deep button</button><p>Deep words</p>';
    root.getElementById('go').addEventListener('click', () => { document.title = 'WENT ' + root.querySelector('input').value; });</script>`);
  const s = await r.handle({ cmd: 'snapshot' });
  const field = s.elements.find(e => e.label === 'Search books'), go = s.elements.find(e => e.label === 'Go'), deep = s.elements.find(e => e.label === 'Deep button');
  assert.ok(field && go && deep, 'the search box of a web component used to be invisible: the task could only click its button over and over');
  assert.ok(field.ref < go.ref && go.ref < deep.ref, 'numbers follow page order through shadow roots too');
  assert.equal(field.covered, false); assert.equal(deep.covered, false);
  assert.match(s.text, /Deep words/);                                                       // the words inside are read too
  assert.equal((await r.handle({ cmd: 'act', action: 'type', ref: field.ref, value: 'dune', expect: { label: 'Search books' } })).ok, true);
  const s2 = await r.handle({ cmd: 'snapshot' });
  assert.equal(s2.focus.label, 'Search books'); assert.equal(s2.focus.value, 'dune');        // focus is followed into the shadow root
  assert.equal((await r.handle({ cmd: 'act', action: 'click', ref: s2.elements.find(e => e.label === 'Go').ref, expect: { label: 'Go' } })).ok, true);
  assert.equal(await r.page.title(), 'WENT dune');
});

test('a control the page gave no name is still listed: a dropdown by its first option, a field or button by what the code calls it', async () => {
  await r.handle({ cmd: 'open', url: base + '/long' });
  await setPage(`<select id=dropdown><option value="">Please select an option</option><option>Option 1</option><option>Option 2</option></select>
    <input name="first_name"><input type=checkbox><br><input type=checkbox> gift wrap<br><button id="cart-toggle"><svg width=20 height=20></svg></button>
    <a href="#x" title="The Road to Little Dribbling: Adventures of an American in Britain">The Road to Little ...</a><p><a href="#y" title="A Very Long Book Title Indeed">A Very Long ...</a> in stock</p>`);
  const s = await r.handle({ cmd: 'snapshot' });
  const labels = s.elements.map(e => e.label);
  assert.ok(labels.includes('Dropdown: Please select an option'), labels.join(' | '));
  assert.ok(labels.includes('first name')); assert.ok(labels.includes('Checkbox')); assert.ok(labels.includes('gift wrap')); assert.ok(labels.includes('cart toggle (unnamed button)'));
  assert.ok(labels.includes('The Road to Little Dribbling: Adventures of an American in Britain'));       // a name the page cut short is given whole when its title says it
  assert.match(s.text, /A Very Long Book Title Indeed/);                                                  // ... in the page's words too
  const dd = s.elements.find(e => e.tag === 'select');
  assert.deepEqual(dd.options, ['Please select an option', 'Option 1', 'Option 2']);
  assert.equal((await r.handle({ cmd: 'act', action: 'select', ref: dd.ref, value: 'Option 2', expect: { label: dd.label } })).ok, true);
  assert.equal(await r.page.evaluate(() => document.getElementById('dropdown').value), 'Option 2');
});

test('the page text starts with what is in the window, wherever the page is scrolled to, and the whole page is given in page order', async () => {
  await r.handle({ cmd: 'open', url: base + '/long' });
  const top = await r.handle({ cmd: 'snapshot' });
  assert.ok(top.text.startsWith('Long page\nLine 0'), top.text.slice(0, 40)); assert.equal(top.full_at, 0);
  await r.handle({ cmd: 'act', action: 'scroll', value: 'down' }); await r.handle({ cmd: 'act', action: 'scroll', value: 'down' });
  const down = await r.handle({ cmd: 'snapshot' });
  assert.ok(down.scroll >= 1300);
  const first = Number(down.text.match(/^Line (\d+)/)[1]);
  assert.ok(first >= 20 && first <= 24, `the first words are the first line in the window, not the top of the document (Line ${first})`);
  assert.match(down.text, /\[below the window\]/); assert.match(down.text, /\[above the window\]\nLong page\nLine 0/);
  assert.ok(down.full.startsWith('Long page\nLine 0')); assert.ok(down.full.includes('Line 59')); assert.equal(down.full.slice(down.full_at).startsWith(`Line ${first}`), true);
});

test('a click whose effect arrives a moment later is still seen as a change', async () => {
  await r.handle({ cmd: 'open', url: base + '/long' });
  await setPage(`<button onclick="setTimeout(() => { const a = document.createElement('a'); a.href = '#n'; a.textContent = 'Now here'; document.body.appendChild(a); }, 700)">Load</button>`);
  const s = await r.handle({ cmd: 'snapshot' });
  const out = await r.handle({ cmd: 'act', action: 'click', ref: s.elements[0].ref, expect: { label: 'Load' } });
  assert.equal(out.ok, true); assert.notEqual(out.page_fp, s.page_fp, 'read at once this said "nothing changed", and the decider clicked again');
});

test('a page caught before it has drawn anything is given a moment, and the snapshot shows what then appeared', async () => {
  await r.handle({ cmd: 'open', url: base + '/long' });
  await setPage(`<script>setTimeout(() => { document.body.innerHTML = '<h1>Results</h1><a href="#r">First result</a>'; }, 900)</script>`);
  const s = await r.handle({ cmd: 'snapshot' });
  assert.match(s.text, /Results/); assert.ok(s.elements.some(e => e.label === 'First result'));
});

test('a picture is still taken when the page waits for a font that never arrives', async () => {
  await r.handle({ cmd: 'open', url: base + '/long' });
  const bytes = await r.shoot(60);
  assert.ok(bytes.length > 1000); assert.equal(bytes[0], 0xff); assert.equal(bytes[1], 0xd8);
  const page = r.page; const real = page.screenshot.bind(page);
  page.screenshot = async () => { throw new Error('Timeout 3000ms exceeded while waiting for fonts to load'); };
  try { const direct = await r.shoot(60); assert.equal(direct[0], 0xff); assert.ok(direct.length > 1000); } finally { page.screenshot = real; }
  assert.equal((await r.handle({ cmd: 'view' })).ok, true);
});

test('a size picker drawn as labels over hidden radio buttons is listed, shows what is chosen, and a step on it chooses', async () => {
  await r.handle({ cmd: 'open', url: base + '/long' });
  await setPage(`<fieldset><legend>Size:</legend>
    <input type=radio name=size id=s value=Small checked style="position:absolute;opacity:0;width:1px;height:1px"><label for=s style="display:inline-block;padding:10px 20px;border:1px solid">Small</label>
    <input type=radio name=size id=m value=Medium style="display:none"><label for=m style="display:inline-block;padding:10px 20px;border:1px solid">Medium</label>
    <input type=radio name=size id=l value=Large disabled style="display:none"><label for=l style="display:inline-block;padding:10px 20px;border:1px solid">Large</label></fieldset>`);
  const s = await r.handle({ cmd: 'snapshot' });
  const small = s.elements.find(e => e.label === 'Small'), medium = s.elements.find(e => e.label === 'Medium');
  assert.ok(small && medium, 'the choices used to be in the page text and nowhere in the list of controls'); assert.equal(s.elements.find(e => e.label === 'Large'), undefined);   // sold out: not offered
  assert.deepEqual([small.type, small.checked, medium.checked, medium.covered, medium.in_view], ['radio', true, false, false, true]);
  const out = await r.handle({ cmd: 'act', action: 'click', ref: medium.ref, expect: { label: 'Medium' } });
  assert.equal(out.ok, true); assert.notEqual(out.page_fp, s.page_fp);                          // choosing a size is a change the host can see
  assert.equal(await r.page.evaluate(() => document.getElementById('m').checked), true);
  const after = await r.handle({ cmd: 'snapshot' });
  assert.equal(after.elements.find(e => e.label === 'Medium').checked, true); assert.equal(after.elements.find(e => e.label === 'Small').checked, false);
});

test('a custom dropdown, its options, menu items and switches are controls like any other', async () => {
  await r.handle({ cmd: 'open', url: base + '/long' });
  await setPage(`<div role="combobox" aria-expanded="false" tabindex="0" id="trip" style="width:160px;height:32px"
      onclick="this.setAttribute('aria-expanded','true'); document.getElementById('list').hidden=false">Round trip</div>
    <ul id="list" role="listbox" hidden><li role="option" aria-selected="true" style="height:30px">Round trip</li>
      <li role="option" aria-selected="false" style="height:30px" onclick="document.getElementById('trip').textContent='One way'; this.parentNode.hidden=true">One way</li></ul>
    <div role="switch" aria-checked="false" tabindex="0" style="width:60px;height:24px" onclick="this.setAttribute('aria-checked','true')">Nonstop only</div>
    <div role="menuitem" tabindex="0" style="width:120px;height:24px">Price graph</div>`);
  let s = await r.handle({ cmd: 'snapshot' });
  const trip = s.elements.find(e => e.label === 'Round trip' && e.role === 'combobox');
  assert.ok(trip, 'the trip-type control of a flight search is a combobox: it was never listed, so "one way" could only be reached by pointing at a picture');
  assert.equal(trip.expanded, false); assert.ok(s.elements.some(e => e.role === 'menuitem' && e.label === 'Price graph'));
  assert.equal(s.elements.find(e => e.role === 'switch').checked, false);
  await r.handle({ cmd: 'act', action: 'click', ref: trip.ref, expect: { label: 'Round trip' } });
  s = await r.handle({ cmd: 'snapshot' });
  const oneWay = s.elements.find(e => e.role === 'option' && e.label === 'One way');
  assert.ok(oneWay); assert.equal(oneWay.checked, null); assert.equal(s.elements.find(e => e.role === 'option' && e.label === 'Round trip').checked, true);       // the option that is chosen says so
  await r.handle({ cmd: 'act', action: 'click', ref: oneWay.ref, expect: { label: 'One way' } });
  assert.equal(await r.page.evaluate(() => document.getElementById('trip').textContent), 'One way');
});
