// The native engine's page scripts (platform/agentai_platform/browse/native_scripts.py) run inside the cell's browser through the bridge, as source text.
// Nothing else ran them in a real browser before this file. These checks load the very strings the bridge sends and run them in Chrome, and hold them to the
// runner's own answers on the same page, so the two engines cannot drift apart unnoticed.
import { test, before, after } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { chromium } from 'playwright-core';

process.env.BROWSE_CHROME ||= '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const py = readFileSync(new URL('../../platform/agentai_platform/browse/native_scripts.py', import.meta.url), 'utf8');
const script = name => { const m = py.match(new RegExp(`\\n${name} = r"""([\\s\\S]*?)"""`)); assert.ok(m, `${name} not found`); return m[1]; };
const SELECTOR = py.match(/\nSELECTOR = '([^']+)'/)[1];
const runnerSource = readFileSync(new URL('../runner.mjs', import.meta.url), 'utf8');
const runnerFn = name => { const m = runnerSource.match(new RegExp(`\\nfunction ${name}\\([^)]*\\) \\{[\\s\\S]*?\\n\\}\\n`)); assert.ok(m, `${name} not found`); return m[0]; };

let browser, page;
before(async () => { browser = await chromium.launch({ executablePath: process.env.BROWSE_CHROME, headless: true }); page = await browser.newPage({ viewport: { width: 1280, height: 800 } }); });
after(async () => { await browser.close(); });
const run = (name, args) => page.evaluate(`(${script(name)})(${JSON.stringify(args || {})})`);          // exactly how native_scripts.expression() applies a script
const html = body => page.setContent(`<!doctype html><body style="margin:0">${body}</body>`);
const at = (left, top, width, height) => `position:absolute;left:${left}px;top:${top}px;width:${width}px;height:${height}px;box-sizing:border-box`;

test('the native selector is the runner\'s', () => {
  assert.match(runnerSource, new RegExp(`const SELECTOR = '${SELECTOR.replace(/[[\]().*+?^$|\\]/g, '\\$&')}'`));
});

test('describe gives the runner\'s answer for the same page: the same controls, numbers, state, places and focus', async () => {
  const menu = Array.from({ length: 100 }, (_, i) => `<a href="#m${i}" style="${at(10, 1500 + i * 30, 200, 20)}">Menu ${i}</a>`).join('');
  await html(`<div style="height:5000px"></div>${menu}<button style="${at(300, 200, 160, 40)}">Add to cart</button><input aria-label="Search" value="shoes" style="${at(300, 300, 200, 30)}">
    <select aria-label="Size" style="${at(300, 400, 120, 30)}"><option>S</option><option selected>M</option></select><input type="password" style="${at(300, 500, 200, 30)}">
    <button style="${at(700, 200, 120, 40)}">Under</button><div style="position:fixed;left:650px;top:150px;width:300px;height:200px;background:#ccc"></div>`);
  await page.evaluate(() => document.querySelector('input[aria-label=Search]').focus());
  const native = await run('DESCRIBE', { sel: SELECTOR, max: 80 });
  await page.evaluate(() => { for (const el of document.querySelectorAll('[data-lumina-ref]')) { el.removeAttribute('data-lumina-ref'); el.removeAttribute('data-lumina-label'); } });
  const runner = await page.evaluate(`(${runnerFn('describe').trim()})(${JSON.stringify({ sel: SELECTOR, max: 80 })})`.replace('(function describe', '(function'));
  assert.deepEqual(native.elements, runner.elements);
  assert.deepEqual(native.focus, runner.focus);
  for (const key of ['title', 'text', 'scroll', 'height', 'window']) assert.deepEqual(native[key], runner[key], key);
  const by = Object.fromEntries(native.elements.map(e => [e.label, e]));
  assert.ok(by['Add to cart'] && by['Search'] && by['Size'] && by['Password']);                 // all past 100 menu links in the page's code
  assert.equal(by['Under'].covered, true); assert.equal(by['Add to cart'].covered, false);
  assert.equal(native.focus.ref, by['Search'].ref); assert.equal(native.focus.value, 'shoes');
});

test('scroll moves the panel under the pointer before the page, says whether anything moved, and when the end is reached', async () => {
  await html(`<div style="height:4000px"></div><div id="panel" style="position:fixed;left:340px;top:100px;width:600px;height:600px;overflow-y:auto;background:#eee"><div style="height:1500px">long list</div></div>`);
  const first = await run('SCROLL', { dy: 700, x: 640, y: 400 });
  assert.deepEqual([first.moved, first.inner, first.at_end, first.y], [true, true, false, 0]);                // the panel moved; the page behind it did not
  assert.equal(await page.evaluate(() => document.getElementById('panel').scrollTop), 700);
  const second = await run('SCROLL', { dy: 700, x: 640, y: 400 });
  assert.deepEqual([second.moved, second.at_end], [true, true]);
  const third = await run('SCROLL', { dy: 700, x: 640, y: 400 });
  assert.deepEqual([third.moved, third.inner, third.at_end], [false, true, true]);                             // already at its end: nothing moved, and the host is told
  const page1 = await run('SCROLL', { dy: 700, x: 100, y: 400 });                                              // beside the panel: the page itself
  assert.deepEqual([page1.moved, page1.inner, page1.y], [true, false, 700]);
  const takeover = await run('SCROLL', { dy: -500 });                                                          // no point given (a takeover wheel): the page, as before
  assert.deepEqual([takeover.inner, takeover.y], [false, 200]);
});

test('typing into a numbered field replaces what was there, and the focused-field check refuses secrets', async () => {
  await html(`<input aria-label="Search" value="old" style="${at(100, 100, 200, 30)}"><input type="password" aria-label="Password" style="${at(100, 200, 200, 30)}">`);
  const d = await run('DESCRIBE', { sel: SELECTOR, max: 80 });
  const search = d.elements.find(e => e.label === 'Search');
  assert.deepEqual(await run('LOCATE', { ref: search.ref, label: 'Search', action: 'type' }).then(r => r.state), 'ok');
  assert.deepEqual(await run('TYPE_INTO', { ref: search.ref, value: 'blue shoes' }), { ok: true });
  assert.equal(await page.evaluate(() => document.querySelector('input').value), 'blue shoes');
  assert.equal((await run('DESCRIBE', { sel: SELECTOR, max: 80 })).focus.value, 'blue shoes');
  await page.evaluate(() => document.querySelector('input[type=password]').focus());
  assert.equal(await run('FOCUS_ACTIVE'), false);
});
