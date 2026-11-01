// The side panel page in a real Chrome, with a scripted stand-in for the service worker. What matters here: it renders text as text, only offers Send while a task runs,
// sends once per press with a stable key, shows the server's refusals in the customer's words, and holds no credential.
import { test, before, after } from 'node:test';
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { readFileSync } from 'node:fs';
import { extname, join, normalize } from 'node:path';
import { chromium } from 'playwright-core';

const CHROME = process.env.BROWSE_CHROME || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const ROOT = new URL('../extension/', import.meta.url).pathname;
const TYPES = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css' };
let server, base, browser;

before(async () => {
  server = createServer((req, res) => {
    const path = normalize(join(ROOT, new URL(req.url, 'http://x').pathname));
    if (!path.startsWith(ROOT)) { res.writeHead(403).end(); return; }
    let body; try { body = readFileSync(path); } catch { res.writeHead(404).end(); return; }
    res.writeHead(200, { 'Content-Type': TYPES[extname(path)] || 'application/octet-stream' }).end(body);
  }).listen(0, '127.0.0.1');
  await new Promise(r => server.once('listening', r)); base = `http://127.0.0.1:${server.address().port}`;
  browser = await chromium.launch({ executablePath: CHROME, headless: true, args: ['--no-first-run'] });
});
after(async () => { await browser.close(); server.close(); });

const RID = 'a'.repeat(32);
const LIVE = { live: true, request: { id: RID, state: 'running', paused: false, outcome: null }, messages: [
  { id: 1, role: 'customer', text: 'Find me the cheapest paddle', surface: null, at: 't' },
  { id: 2, role: 'agent', text: '<img src=x onerror="window.__pwned=1"> Looking now', surface: null, at: 't' },
  { id: 3, role: 'customer', text: 'only red ones', surface: 'panel', at: 't' }] };

/** Opens the panel with a fake `chrome`: `script` answers the worker's messages; every call the page makes is recorded on window.__calls. */
async function open(script) {
  const context = await browser.newContext(); const page = await context.newPage();
  await page.addInitScript(source => {
    window.__calls = []; const listeners = [];
    const handler = new Function('message', 'calls', `return (${source})(message, calls)`);
    window.chrome = { runtime: { sendMessage: async message => { window.__calls.push(message); return handler(message, window.__calls); }, onMessage: { addListener: f => listeners.push(f) } } };
    window.__fire = m => listeners.forEach(f => f(m));
  }, script.toString());
  await page.goto(base + '/panel.html');
  return { page, context };
}
const settle = page => page.waitForTimeout(250);

test('a running task: the trail and chat show as text, markup is inert, and Send and Stop are offered', async () => {
  const { page, context } = await open((m, calls) => {
    if (m.type === 'panel:state') return { enabled: true, connected: true, hasTicket: true };
    if (m.endpoint === 'state') return { status: 200, data: { messages: [
      { id: 1, role: 'customer', text: 'Find me the cheapest paddle', surface: null, at: 't' },
      { id: 2, role: 'agent', text: '<img src=x onerror="window.__pwned=1"> Looking now', surface: null, at: 't' },
      { id: 3, role: 'customer', text: 'only red ones', surface: 'panel', at: 't' }], live: true, request: { id: 'a'.repeat(32), state: 'running', paused: false, outcome: null } } };
    if (m.endpoint === 'events') return { status: 200, data: { task_state: 'running', events: [
      { sequence: 1, kind: 'tool', payload: { summary: 'Opened <b>the shop</b>' } }, { sequence: 2, kind: 'screenshot', payload: {} }, { sequence: 3, kind: 'page_loaded', payload: {} }] } };
    return { status: 0, data: {} };
  });
  await settle(page);
  assert.equal(await page.textContent('#status'), 'Working');
  assert.equal(await page.getAttribute('#status', 'data-tone'), 'on');
  assert.deepEqual(await page.$$eval('#trail li', l => l.map(x => x.textContent)), ['Opened <b>the shop</b>', 'page loaded']);      // the picture event has no line; markup is just letters
  const messages = await page.$$eval('#messages li', l => l.map(x => ({ role: x.dataset.role, text: x.firstChild.textContent, tag: x.querySelector('small')?.textContent ?? null })));
  assert.deepEqual(messages, [{ role: 'customer', text: 'Find me the cheapest paddle', tag: null }, { role: 'agent', text: '<img src=x onerror="window.__pwned=1"> Looking now', tag: null }, { role: 'customer', text: 'only red ones', tag: 'sent from this panel' }]);
  assert.equal(await page.$('#messages img'), null); assert.equal(await page.evaluate(() => window.__pwned), undefined);
  assert.equal(await page.isDisabled('#text'), false); assert.equal(await page.isHidden('#stop'), false);
  assert.equal(await page.evaluate(() => JSON.stringify(window.__calls).includes('p1.')), false, 'the page never sees a ticket');
  await context.close();
});

test('Enter sends once with one key; the same text pressed again reuses the key; Shift+Enter only adds a line', async () => {
  const { page, context } = await open((m, calls) => {
    if (m.type === 'panel:state') return { enabled: true, connected: true, hasTicket: true };
    if (m.endpoint === 'state') return { status: 200, data: { messages: [], live: true, request: { id: 'a'.repeat(32), state: 'running', paused: false } } };
    if (m.endpoint === 'events') return { status: 200, data: { events: [] } };
    if (m.endpoint === 'send') return calls.filter(c => c.endpoint === 'send').length === 1 ? { status: 409, data: { error: 'request_conflict' } } : { status: 202, data: { ok: true } };
    return { status: 0, data: {} };
  });
  await settle(page);
  await page.fill('#text', 'also check shipping'); await page.press('#text', 'Shift+Enter'); await page.keyboard.type('and returns');
  assert.equal(await page.inputValue('#text'), 'also check shipping\nand returns');
  await page.fill('#text', 'also check shipping'); await page.press('#text', 'Enter'); await settle(page);
  assert.match(await page.textContent('#error'), /could not be added/); assert.equal(await page.inputValue('#text'), 'also check shipping');      // kept so it can be sent again
  await page.waitForTimeout(1700); assert.equal(await page.isHidden('#error'), false, 'a refresh does not wipe the answer to the last send');
  await page.press('#text', 'Enter'); await settle(page);
  const sends = await page.evaluate(() => window.__calls.filter(c => c.endpoint === 'send'));
  assert.equal(sends.length, 2); assert.equal(sends[0].input.key, sends[1].input.key); assert.equal(sends[0].input.message, 'also check shipping');
  assert.equal(await page.inputValue('#text'), ''); assert.equal(await page.isHidden('#error'), true);
  await page.fill('#text', 'something else'); await page.press('#text', 'Enter'); await settle(page);
  const third = (await page.evaluate(() => window.__calls.filter(c => c.endpoint === 'send')))[2];
  assert.notEqual(third.input.key, sends[0].input.key);
  await context.close();
});

test('Stop asks the worker to stop and reports a refusal in words', async () => {
  const { page, context } = await open((m) => {
    if (m.type === 'panel:state') return { enabled: true, connected: true, hasTicket: true };
    if (m.endpoint === 'state') return { status: 200, data: { messages: [], live: true, request: { id: 'a'.repeat(32), state: 'running', paused: false } } };
    if (m.endpoint === 'events') return { status: 200, data: { events: [] } };
    if (m.endpoint === 'stop') return { status: 409, data: { error: 'no_active_run' } };
    return { status: 0, data: {} };
  });
  await settle(page); await page.click('#stop'); await settle(page);
  assert.equal(await page.evaluate(() => window.__calls.filter(c => c.endpoint === 'stop').length), 1);
  assert.match(await page.textContent('#error'), /Nothing is running/);
  await context.close();
});

test('with no task running, or no ticket, or switched off, nothing can be sent', async () => {
  for (const [link, state, headline, tone] of [
    [{ enabled: true, connected: true, hasTicket: true }, { messages: [{ id: 1, role: 'agent', text: 'All done.', surface: null, at: 't' }], live: false, request: { id: 'a'.repeat(32), state: 'completed', paused: false } }, 'Done', 'idle'],
    [{ enabled: true, connected: true, hasTicket: false }, null, 'Waiting for a task', 'wait'],
    [{ enabled: false, connected: false, hasTicket: false }, null, 'Lumina is off in this browser', 'off']]) {
    const { page, context } = await open(new Function('m', `
      if (m.type === 'panel:state') return ${JSON.stringify(link)};
      if (m.endpoint === 'state') return { status: 200, data: ${JSON.stringify(state)} };
      if (m.endpoint === 'events') return { status: 200, data: { events: [] } };
      return { status: 0, data: {} };`));
    await settle(page);
    assert.equal(await page.textContent('#status'), headline); assert.equal(await page.getAttribute('#status', 'data-tone'), tone);
    assert.equal(await page.isDisabled('#text'), true); assert.equal(await page.isDisabled('#send'), true); assert.equal(await page.isHidden('#stop'), true);
    if (state) assert.equal(await page.textContent('#messages li'), 'All done.');
    await context.close();
  }
});

test('a "changed" notice from the worker refreshes at once', async () => {
  const { page, context } = await open((m, calls) => {
    if (m.type === 'panel:state') return { enabled: true, connected: true, hasTicket: calls.filter(c => c.type === 'panel:state').length > 1 };
    if (m.endpoint === 'state') return { status: 200, data: { messages: [], live: true, request: { id: 'a'.repeat(32), state: 'running', paused: false } } };
    if (m.endpoint === 'events') return { status: 200, data: { events: [] } };
    return { status: 0, data: {} };
  });
  await settle(page); assert.equal(await page.textContent('#status'), 'Waiting for a task');
  await page.evaluate(() => window.__fire({ type: 'panel:changed' })); await settle(page);
  assert.equal(await page.textContent('#status'), 'Working');
  await context.close();
});
