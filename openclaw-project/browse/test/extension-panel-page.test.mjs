// The side panel page in a real Chrome, with a scripted stand-in for the service worker. What matters here: it renders text as text, starts a new session on its own, sends once per press with
// a stable key and the right context (new tab, this tab, another tab), only acts in a tab that was allowed, shows the server's refusals in the customer's words, and holds no credential.
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
const TABS = [{ id: 11, title: 'Hotels in Paris', url: 'https://hotels.example/paris', active: true, grant: null, restricted: false },
  { id: 13, title: 'Docs', url: 'https://docs.example/a', active: false, grant: null, restricted: false }, { id: 12, title: 'Settings', url: 'chrome://settings', active: false, grant: null, restricted: true }];
const LINK = { enabled: true, connected: true, paired: true, hasTicket: true, conversation: 'conv_1', offered: null, hasSites: true };
const FRESH = { messages: [], live: false, request: null, cell: 'asleep' };
const LIVE = { messages: [], live: true, request: { id: RID, state: 'running', paused: false, outcome: null }, cell: 'ready' };

/** Opens the panel with a fake `chrome`. `world` is what the worker would say (link, state, tabs, what a tab reads as); `window.__calls` records everything the page asks the worker. */
async function open(world = {}) {
  const context = await browser.newContext(); const page = await context.newPage();
  await page.addInitScript(w => {
    window.__world = { link: {}, state: null, tabs: [], read: { read: true, text: 'Rooms from 120 euros', selection: 'two seats', title: 'Hotels in Paris', url: 'https://hotels.example/paris' }, events: [], sendStatus: 202, sendError: 'request_conflict', prompt: null, ...w };
    window.__calls = []; const listeners = [];
    window.chrome = {
      runtime: { sendMessage: async m => {
        window.__calls.push(m); const W = window.__world;
        if (m.type === 'panel:state') return W.link;
        if (m.type === 'panel:open' || m.type === 'panel:new') { W.link = { ...W.link, hasTicket: true }; return { ok: true }; }
        if (m.type === 'tabs:list') return { ok: true, tabs: W.tabs };
        if (m.type === 'tab:read') return { ok: true, ...W.read, grant: (W.tabs.find(t => t.id === m.tabId) || {}).grant ?? null };
        if (m.type === 'tab:grant') { const t = W.tabs.find(x => x.id === m.tabId); if (t) t.grant = 'g1'; return { ok: true, grant: 'g1' }; }
        if (m.type === 'tab:revoke') { for (const t of W.tabs) if (t.grant === m.grant) t.grant = null; return { ok: true }; }
        if (m.type === 'panel:take-prompt') { const p = W.prompt; W.prompt = null; return { ok: true, prompt: p }; }
        if (m.type === 'pair') return { ok: /^[A-Z0-9-]{8,}$/.test(m.code) };
        if (m.type === 'toggle') { W.link = { ...W.link, enabled: !W.link.enabled }; return {}; }
        if (m.type === 'panel:use-offered') { W.link = { ...W.link, offered: null }; return { ok: true }; }
        if (m.type === 'panel:call') {
          if (m.endpoint === 'state') return { status: 200, data: W.state };
          if (m.endpoint === 'events') return { status: 200, data: { task_state: 'running', events: W.events } };
          if (m.endpoint === 'send') return W.sendStatus === 202 ? { status: 202, data: { ok: true, started: true } } : { status: 409, data: { error: W.sendError } };
          if (m.endpoint === 'stop') return { status: 202, data: { ok: true } };
        }
        return { status: 0, data: {} };
      }, onMessage: { addListener: f => listeners.push(f) }, connect: () => ({ postMessage() {} }) },
      storage: { local: { get: async () => ({}), set: async () => {} } }, windows: { getCurrent: async () => ({ id: 1 }) }, permissions: { request: async () => true },
      tabs: { onActivated: { addListener() {} }, onUpdated: { addListener() {} } },
    };
    window.__fire = m => listeners.forEach(f => f(m));
  }, { link: LINK, ...world, tabs: structuredClone(world.tabs ?? TABS) });
  await page.goto(base + '/panel.html');
  return { page, context };
}
const settle = page => page.waitForTimeout(300);
const sends = page => page.evaluate(() => window.__calls.filter(c => c.endpoint === 'send').map(c => c.input));

test('a running task: the trail and chat show as text, markup is inert, and Send and Stop are offered', async () => {
  const { page, context } = await open({
    state: { ...LIVE, messages: [{ id: 1, role: 'customer', text: 'Find me the cheapest paddle', surface: null, at: 't' }, { id: 2, role: 'agent', text: '<img src=x onerror="window.__pwned=1"> Looking now', surface: null, at: 't' },
      { id: 3, role: 'customer', text: 'only red ones', surface: 'panel', at: 't' }] },
    events: [{ sequence: 1, kind: 'tool', payload: { summary: 'Opened <b>the shop</b>' } }, { sequence: 2, kind: 'screenshot', payload: {} }, { sequence: 3, kind: 'page_loaded', payload: {} }],
  });
  await settle(page);
  assert.equal(await page.textContent('#status'), 'Working'); assert.equal(await page.getAttribute('#status', 'data-tone'), 'on');
  assert.deepEqual(await page.$$eval('#trail li', l => l.map(x => x.textContent)), ['Opened <b>the shop</b>', 'page loaded']);
  const messages = await page.$$eval('#messages li', l => l.map(x => ({ role: x.dataset.role, text: x.firstChild.textContent, tag: x.querySelector('small')?.textContent ?? null })));
  assert.deepEqual(messages, [{ role: 'customer', text: 'Find me the cheapest paddle', tag: null }, { role: 'agent', text: '<img src=x onerror="window.__pwned=1"> Looking now', tag: null }, { role: 'customer', text: 'only red ones', tag: 'sent from this panel' }]);
  assert.equal(await page.$('#messages img'), null); assert.equal(await page.evaluate(() => window.__pwned), undefined);
  assert.equal(await page.isDisabled('#text'), false); assert.equal(await page.isHidden('#stop'), false);
  assert.equal(await page.evaluate(() => JSON.stringify(window.__calls).includes('p1.')), false, 'the page never sees a ticket');
  await context.close();
});

test('opening the panel starts a session by itself; a fresh session is ready to type and says the assistant is asleep', async () => {
  const { page, context } = await open({ link: { ...LINK, hasTicket: false }, state: FRESH });
  await settle(page);
  assert.ok(await page.evaluate(() => window.__calls.some(c => c.type === 'panel:open')), 'a session was asked for');
  assert.equal(await page.textContent('#status'), 'Ready'); assert.match(await page.textContent('#detail'), /asleep/);
  assert.equal(await page.isDisabled('#text'), false); assert.equal(await page.isVisible('#empty'), true);
  await page.click('#new'); await settle(page);
  assert.equal(await page.evaluate(() => window.__calls.filter(c => c.type === 'panel:new').length), 1);
  await context.close();
});

test('Enter sends once with one key, in a new tab by default; the same text pressed again reuses the key; Shift+Enter only adds a line', async () => {
  const { page, context } = await open({ state: FRESH });
  await page.evaluate(() => { window.__world.sendStatus = 409; });
  await settle(page);
  await page.fill('#text', 'find hotels in Paris'); await page.press('#text', 'Shift+Enter'); await page.keyboard.type('under 150');
  assert.equal(await page.inputValue('#text'), 'find hotels in Paris\nunder 150');
  await page.fill('#text', 'find hotels in Paris'); await page.press('#text', 'Enter'); await settle(page);
  assert.match(await page.textContent('#error'), /could not be added/); assert.equal(await page.inputValue('#text'), 'find hotels in Paris');      // kept so it can be sent again
  await page.evaluate(() => { window.__world.sendStatus = 202; });
  await page.press('#text', 'Enter'); await settle(page);
  const sent = await sends(page);
  assert.equal(sent.length, 2); assert.equal(sent[0].key, sent[1].key); assert.equal(sent[0].message, 'find hotels in Paris');
  assert.equal(sent[1].mode, 'browse'); assert.equal(sent[1].context.target, 'new_tab');
  assert.equal(sent[1].context.page, 'Rooms from 120 euros', 'what is on the page the customer is looking at goes along as context'); assert.equal(sent[1].context.selection, 'two seats');
  assert.equal(await page.inputValue('#text'), ''); assert.equal(await page.isHidden('#error'), true);
  await page.fill('#text', 'something else'); await page.press('#text', 'Enter'); await settle(page);
  assert.notEqual((await sends(page))[2].key, sent[0].key);
  await context.close();
});

test('Chat mode answers without the browser; the page text can be left out', async () => {
  const { page, context } = await open({ state: FRESH });
  await settle(page);
  await page.click('[data-mode="auto"]'); await page.uncheck('#withpage');
  await page.fill('#text', 'what is a good name for a cat'); await page.press('#text', 'Enter'); await settle(page);
  const [sent] = await sends(page);
  assert.equal(sent.mode, 'auto'); assert.equal(sent.context.page, undefined); assert.equal(sent.context.selection, 'two seats');
  await context.close();
});

test('"This tab" and "Another tab" need the customer to allow the tab first; then the message names it, carries its grant, and always browses', async () => {
  const { page, context } = await open({ state: FRESH });
  await settle(page);
  await page.click('[data-target="this_tab"]'); await settle(page);
  assert.equal(await page.isVisible('#tabline'), true); assert.equal(await page.textContent('#tabname'), 'Hotels in Paris');
  assert.equal(await page.isVisible('#allow'), true); assert.equal(await page.isHidden('#revoke'), true);
  await page.click('[data-mode="auto"]');
  await page.fill('#text', 'book the cheapest one'); await page.press('#text', 'Enter'); await settle(page);
  assert.equal((await sends(page)).length, 0, 'nothing is sent for a tab that was not allowed'); assert.match(await page.textContent('#error'), /cannot be used/);
  await page.click('#allow'); await settle(page);
  assert.ok(await page.evaluate(() => window.__calls.some(c => c.type === 'tab:grant' && c.tabId === 11)));
  assert.equal(await page.isHidden('#allow'), true); assert.equal(await page.isVisible('#revoke'), true);
  await page.press('#text', 'Enter'); await settle(page);
  const [sent] = await sends(page);
  assert.deepEqual([sent.mode, sent.context.target, sent.context.tabs], ['browse', 'this_tab', [{ title: 'Hotels in Paris', url: 'https://hotels.example/paris', grant: 'g1' }]]);
  await page.click('#revoke'); await settle(page);
  assert.ok(await page.evaluate(() => window.__calls.some(c => c.type === 'tab:revoke' && c.grant === 'g1')));
  // another tab: a picker of the window's usable tabs (never chrome:// pages)
  await page.click('[data-target="tab"]'); await settle(page);
  assert.deepEqual(await page.$$eval('#tabs option', o => o.map(x => x.textContent)), ['Hotels in Paris', 'Docs']);
  await page.selectOption('#tabs', '13'); await settle(page);
  assert.equal(await page.textContent('#tabname'), 'Docs'); assert.equal(await page.isVisible('#allow'), true);
  await context.close();
});

test('a page Lumina can never work in cannot be allowed', async () => {
  const { page, context } = await open({ state: FRESH, tabs: [{ id: 12, title: 'Settings', url: 'chrome://settings', active: true, grant: null, restricted: true }] });
  await settle(page);
  await page.click('[data-target="this_tab"]'); await settle(page);
  assert.equal(await page.isHidden('#allow'), true); assert.match(await page.textContent('#ctxnote'), /kind of page/);
  await context.close();
});

test('quick actions appear when there is something to ask about, and send their words in one press', async () => {
  const { page, context } = await open({ state: FRESH });
  await settle(page);
  assert.ok((await page.$$eval('#quick button', b => b.map(x => x.textContent))).includes('Summarize this page'));
  assert.ok((await page.$$eval('#quick button', b => b.map(x => x.textContent))).includes('Explain selection'));
  await page.click('text=Summarize this page'); await settle(page);
  const [sent] = await sends(page); assert.match(sent.message, /Summarize the page/); assert.equal(sent.mode, 'auto');
  await context.close();
  const none = await open({ state: FRESH, read: { read: false, text: '', selection: '' } });
  await settle(none.page); assert.deepEqual(await none.page.$$eval('#quick button', b => b.map(x => x.textContent)), []); await none.context.close();
});

test('Stop asks the worker to stop', async () => {
  const { page, context } = await open({ state: LIVE });
  await settle(page); await page.click('#stop'); await settle(page);
  assert.equal(await page.evaluate(() => window.__calls.filter(c => c.endpoint === 'stop').length), 1);
  await context.close();
});

test('not paired, switched off or still connecting: the right control is offered and nothing can be sent', async () => {
  const unpaired = await open({ link: { ...LINK, paired: false, enabled: false, connected: false, hasTicket: false } });
  await settle(unpaired.page);
  assert.equal(await unpaired.page.textContent('#status'), 'Connect this browser to Lumina'); assert.equal(await unpaired.page.isVisible('#pair'), true); assert.equal(await unpaired.page.isDisabled('#send'), true);
  await unpaired.page.fill('#code', 'ab'); await unpaired.page.press('#code', 'Enter'); await settle(unpaired.page);
  assert.equal(await unpaired.page.isVisible('#pair-error'), true);
  await unpaired.page.fill('#code', 'abcd-2345'); await unpaired.page.press('#code', 'Enter'); await settle(unpaired.page);
  assert.ok(await unpaired.page.evaluate(() => window.__calls.some(c => c.type === 'pair' && c.code === 'abcd-2345')));
  await unpaired.context.close();
  const off = await open({ link: { ...LINK, enabled: false, connected: false, hasTicket: false } });
  await settle(off.page);
  assert.equal(await off.page.textContent('#status'), 'Lumina is off in this browser'); assert.equal(await off.page.isDisabled('#text'), true);
  await off.page.click('#gear'); await off.page.click('#power'); await settle(off.page);
  assert.ok(await off.page.evaluate(() => window.__calls.some(c => c.type === 'toggle')));
  await off.context.close();
  const waiting = await open({ link: { ...LINK, connected: false, hasTicket: false } });
  await settle(waiting.page); assert.equal(await waiting.page.textContent('#status'), 'Connecting to Lumina…'); assert.equal(await waiting.page.isDisabled('#send'), true); await waiting.context.close();
});

test('a web-chat task running in this browser is offered, never forced', async () => {
  const { page, context } = await open({ state: FRESH, link: { ...LINK, offered: 'conv_9' } });
  await settle(page);
  assert.equal(await page.isVisible('#banner'), true); assert.match(await page.textContent('#banner-text'), /web chat/);
  await page.click('#banner-use'); await settle(page);
  assert.ok(await page.evaluate(() => window.__calls.some(c => c.type === 'panel:use-offered'))); assert.equal(await page.isHidden('#banner'), true);
  await context.close();
});

test('a right-click prompt is put in the box to finish, and is not sent by itself', async () => {
  const { page, context } = await open({ state: FRESH, prompt: { kind: 'selection', text: 'two seats left', url: 'https://hotels.example/paris' } });
  await settle(page);
  assert.equal(await page.inputValue('#text'), 'About this text: “two seats left”\n'); assert.equal((await sends(page)).length, 0);
  await context.close();
});

test('saved prompts are kept on this computer and put in the box; a changed notice from the worker refreshes at once', async () => {
  const { page, context } = await open({ state: FRESH, link: { ...LINK, hasTicket: false } });
  await settle(page);
  await page.click('#gear'); await page.fill('#saved-name', 'Weekly'); await page.fill('#saved-text', 'Check my bookings'); await page.click('#saved-form button'); await settle(page);
  assert.deepEqual(await page.$$eval('#saved li span', s => s.map(x => x.textContent)), ['Weekly']);
  await page.click('#gear'); await page.click('#quick >> text=Weekly'); assert.equal(await page.inputValue('#text'), 'Check my bookings');
  const before = await page.evaluate(() => window.__calls.filter(c => c.type === 'panel:state').length);
  await page.evaluate(() => window.__fire({ type: 'panel:changed' })); await settle(page);
  assert.ok(await page.evaluate(n => window.__calls.filter(c => c.type === 'panel:state').length > n, before));
  await context.close();
});
