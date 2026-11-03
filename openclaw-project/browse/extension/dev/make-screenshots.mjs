// Renders the Chrome Web Store screenshots (1280x800 JPEG) into store/screenshots/. Everything shown is the real code:
//   - the side panel is panel.html + panel.js as shipped, with only the chrome.* calls stubbed to report a state;
//   - the Lumina pages are the built app (lumina/dist) served by lumina/dev-mock.mjs, with /v1/devices answered in the browser.
// Needs Chrome, `npm run build` in lumina/, and port 5199 free.        node dev/make-screenshots.mjs
// Only the side panel pictures (no app build needed):                 ONLY=panel node dev/make-screenshots.mjs
import { spawn } from 'node:child_process';
import { createServer } from 'node:http';
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { extname, join } from 'node:path';
import { chromium } from 'playwright-core';

const EXT = new URL('../', import.meta.url).pathname;
const OUT = join(EXT, 'store', 'screenshots'); mkdirSync(OUT, { recursive: true });
const CHROME = process.env.BROWSE_CHROME || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const MIME = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.png': 'image/png' };

// a static server for the extension folder (a popup's module scripts will not load from file://)
const files = createServer((req, res) => { try { const p = new URL(req.url, 'http://x').pathname.replace(/^\/+/, '') || 'panel.html'; const data = readFileSync(join(EXT, p)); res.writeHead(200, { 'Content-Type': MIME[extname(p)] || 'application/octet-stream' }); res.end(data); } catch { res.writeHead(404); res.end(); } });
await new Promise(r => files.listen(0, '127.0.0.1', r)); const panelUrl = `http://127.0.0.1:${files.address().port}/panel.html`;
const ONLY_PANEL = process.env.ONLY === 'panel';
const mock = ONLY_PANEL ? null : spawn('node', [join(EXT, '..', '..', 'lumina', 'dev-mock.mjs')], { stdio: 'ignore' });
await new Promise(r => setTimeout(r, ONLY_PANEL ? 0 : 1200));

const browser = await chromium.launch({ executablePath: CHROME, headless: true });
const context = await browser.newContext({ viewport: { width: 1280, height: 720 }, deviceScaleFactor: 1, colorScheme: 'dark' });

// the finished picture: the shot above, a caption strip below, 1280x800, opaque
async function compose(name, shot, caption, { height = 720 } = {}) {
  const page = await browser.newPage({ viewport: { width: 1280, height: 800 }, deviceScaleFactor: 1 });
  await page.setContent(`<!doctype html><style>html,body{margin:0;background:#07070a;width:1280px;height:800px;overflow:hidden;font-family:-apple-system,BlinkMacSystemFont,'SF Pro Text',Inter,system-ui,sans-serif}
    .stage{height:720px;display:grid;place-items:center}.stage img{max-height:${height}px;max-width:1280px;display:block;border-radius:14px;box-shadow:0 18px 48px rgba(0,0,0,.55)}
    .cap{height:80px;display:grid;place-items:center;background:#0e0f13;border-top:1px solid rgba(255,255,255,.1);color:#f2f2f5;font-size:28px;font-weight:600;letter-spacing:-.01em}</style>
    <div class="stage"><img src="data:image/png;base64,${shot.toString('base64')}"></div><div class="cap">${caption}</div>`);
  await page.waitForFunction(() => [...document.images].every(i => i.complete));
  writeFileSync(join(OUT, name), await page.screenshot({ type: 'jpeg', quality: 95 })); await page.close(); console.log('wrote', name);
}

// ---- the side panel, in two states: pairing a browser, and a chat about the page you are on
async function panelShot(world, { code, typed } = {}) {       // drawn at 2x so the text stays sharp when it is shown large
  const ctx = await browser.newContext({ viewport: { width: 400, height: 720 }, deviceScaleFactor: 2, colorScheme: 'dark' });
  const page = await ctx.newPage();
  await page.addInitScript(w => {
    const link = { enabled: true, connected: true, paired: true, hasTicket: true, offered: null, hasSites: true, ...w.link };
    const tabs = [{ id: 11, title: 'Hotels in Paris', url: 'https://hotels.example/paris', active: true, grant: w.granted ? 'g1' : null, restricted: false }, { id: 13, title: 'Train times', url: 'https://trains.example/', active: false, grant: null, restricted: false }];
    window.chrome = { runtime: { sendMessage: async m => {
      if (m.type === 'panel:state') return link; if (m.type === 'tabs:list') return { ok: true, tabs };
      if (m.type === 'tab:read') return { ok: true, title: 'Hotels in Paris', url: 'https://hotels.example/paris', text: 'Rooms from 120 euros', selection: '', read: true, grant: w.granted ? 'g1' : null };
      if (m.type === 'panel:call') return m.endpoint === 'state' ? { status: 200, data: w.state } : m.endpoint === 'events' ? { status: 200, data: { events: w.events || [] } } : { status: 0, data: {} };
      return { ok: true };
    }, onMessage: { addListener() {} }, connect: () => ({ postMessage() {} }) }, storage: { local: { get: async () => ({ ui: w.ui || {} }), set: async () => {} } }, windows: { getCurrent: async () => ({ id: 1 }) }, permissions: { request: async () => true }, tabs: { onActivated: { addListener() {} }, onUpdated: { addListener() {} } } };
  }, world);
  await page.goto(panelUrl); await page.waitForTimeout(900);
  if (code) await page.fill('#code', code);
  if (typed) await page.fill('#text', typed);
  const buffer = await page.screenshot(); await ctx.close(); return buffer;
}

await compose('01-connect-with-a-code.jpg', await panelShot({ link: { paired: false, enabled: false, connected: false, hasTicket: false }, state: null }, { code: 'ABCD-2345' }), 'Connect Chrome to Lumina with a one-time code', { height: 640 });
await compose('02-on-only-when-you-want.jpg', await panelShot({ granted: true, ui: { target: 'this_tab', mode: 'browse' }, state: { live: true, cell: 'ready', request: { id: 'a'.repeat(32), state: 'running', paused: false },
  messages: [{ id: 1, role: 'customer', text: 'Find the cheapest room for two nights and tell me about cancellation', surface: 'panel', at: 't' }, { id: 2, role: 'agent', text: 'On it. I am reading the prices on this page.', surface: null, at: 't' }],
  }, events: [{ sequence: 1, kind: 'tool', payload: { summary: 'Opened the hotel page you allowed' } }, { sequence: 2, kind: 'tool', payload: { summary: 'Reading room prices' } }] }), 'Chat with Lumina beside any tab. It works in a tab only when you allow it', { height: 640 });

if (!ONLY_PANEL) {
// ---- the Lumina app
const device = { device_id: 'a1b2c3d4e5f60718', label: 'Chrome (mac)', created: 1_790_000_000, last_seen: 1_790_000_000, connected: true };
async function app(path, { devices, wait, act }) {
  const page = await context.newPage();
  await page.route('**/v1/devices', r => r.request().method() === 'GET' ? r.fulfill({ json: devices }) : r.fallback());
  await page.route('**/v1/devices/pair', r => r.fulfill({ json: { code: 'ABCD2345', display: 'ABCD-2345', expires_in: 600 } }));
  await page.goto('http://127.0.0.1:5199/app' + path); await page.waitForSelector(wait, { timeout: 15000 });
  if (act) await act(page);
  await page.waitForTimeout(600);
  const buffer = await page.screenshot({ type: 'png' }); await page.close(); return buffer;
}
const chat = await app('/chat/c1', { devices: { available: true, use: true, connected: true, devices: [device] }, wait: '.own-browser[data-state="live"]', act: async page => {
  await page.addStyleTag({ content: '.own-browser{outline:2px solid #7455ff;outline-offset:5px;border-radius:50%}' });       // a ring so the eye finds the icon
  await page.waitForTimeout(1800);                                                               // the app scrolls itself to the newest message once the chat has loaded: let it finish,
  await page.evaluate(() => window.scrollTo({ top: 0, behavior: 'instant' }));                    // then show the top of the chat, where the switch is
  await page.waitForTimeout(1500);                                                               // and let any scroll animation come to rest before the picture is taken
} });
await compose('03-one-switch-in-every-chat.jpg', chat, 'One switch at the top of every chat: use my own browser');
const pairing = await app('/settings', { devices: { available: true, use: false, connected: false, devices: [] }, wait: '#your-browser', act: async page => {
  await page.getByRole('button', { name: 'Connect a browser' }).click(); await page.waitForSelector('.pair-code'); await page.locator('#your-browser').scrollIntoViewIfNeeded();
} });
await compose('04-pair-in-settings.jpg', pairing, 'Pair your browser from Settings with a one-time code');
const listed = await app('/settings', { devices: { available: true, use: true, connected: true, devices: [device, { ...device, device_id: '0f0f0f0f0f0f0f0f', label: 'Chrome (windows)', connected: false }] }, wait: '.device-list', act: async page => { await page.locator('#your-browser').scrollIntoViewIfNeeded(); } });
await compose('05-see-and-remove-your-browsers.jpg', listed, 'See your connected browsers and remove one any time');

}

await browser.close(); files.close(); mock?.kill();
