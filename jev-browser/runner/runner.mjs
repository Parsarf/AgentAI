// The hands and eyes. It talks straight to Chrome over the DevTools protocol, with no libraries and no packages (Node 22+ has WebSocket built in).
// One JSON line in, one JSON line out:
//   {cmd:'open', url}                      -> {ok, page}   open the page, then read it
//   {cmd:'look'}                           -> {ok, page}   read the page as it is right now (JEV always sees the page after an action, never an old copy)
//   {cmd:'shot'}                           -> {ok, data, width, height, view:{w,h}, file?}   a picture of what the window shows right now (base64 JPEG, sized for JEV)
//   {cmd:'probe', x, y}                    -> {ok, hit}    what is under that point (x, y in page pixels): {tag, type, label, editable, disabled} or null
//   {cmd:'act', action, ref?, x?, y?, value?} -> {ok, error?} do one thing; click | type | select (a numbered control from the last look), clickat | typeat (a point on the screen), scroll_down | press_enter
//   {cmd:'close'}
// `page` is {url, scroll, height, window, title, text, elements:[{ref, tag, type, label, value, checked, options, inView, covered}]}: what the page says it holds. JEV never sees it; it is only for the log.
import { spawn } from 'node:child_process';
import { createInterface } from 'node:readline';
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const CHROME = process.env.BROWSE_CHROME || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const SHOTS = process.env.BROWSE_SHOTS;                              // when set, every picture it takes for JEV is also saved here
const WINDOW = '1280,900';                                           // the window size; the page gets what is left under Chrome's own toolbar
const SELECTOR = 'a[href], button, input:not([type=hidden]), select, textarea, [role=button], [role=link], [role=checkbox], [role=tab], summary';
const MAX_CONTROLS = 150, MAX_TEXT = 3000;
const sleep = ms => new Promise(r => setTimeout(r, ms));
const event = (...a) => console.error('event', ...a);                // shows up in the run log as a tab event

// ------------------------------------------------------------------ in-page functions (sent to the page as text, so they must be self-contained)
// List the visible controls in page order and mark each with its number.
function describe({ sel, max, maxText }) {
  for (const el of document.querySelectorAll('[data-jev-ref]')) el.removeAttribute('data-jev-ref');
  const clean = s => (s || '').replace(/\s+/g, ' ').replace(/"/g, "'").trim().slice(0, 100);
  const out = [];
  for (const el of document.querySelectorAll(sel)) {
    if (out.length >= max) break;
    const r = el.getBoundingClientRect(), st = getComputedStyle(el);
    if (r.width < 2 || r.height < 2 || st.visibility === 'hidden' || st.display === 'none' || el.disabled || el.closest('[aria-hidden=true], [inert]')) continue;
    const tag = el.tagName.toLowerCase(), field = ['input', 'select', 'textarea'].includes(tag);
    const type = tag === 'input' ? (el.getAttribute('type') || 'text').toLowerCase() : '';
    const img = el.querySelector('img[alt]');
    const label = clean(el.getAttribute('aria-label') || (field ? (el.labels && el.labels[0] && el.labels[0].innerText) || el.placeholder || el.name || el.title : el.innerText || el.value || el.title || (img && img.alt)) || (type === 'password' ? 'Password' : ''));
    if (!label) continue;
    const ref = out.length + 1;
    el.setAttribute('data-jev-ref', String(ref));
    const vl = Math.max(r.left, 0), vr = Math.min(r.right, innerWidth), vt = Math.max(r.top, 0), vb = Math.min(r.bottom, innerHeight);      // the part of it that is in the window
    const inView = vr - vl > 1 && vb - vt > 1;
    let covered = null;                                                 // null when it is out of the window; otherwise: is something else on top of the middle of what shows?
    if (inView) {
      const top = document.elementFromPoint((vl + vr) / 2, (vt + vb) / 2);
      covered = !(top && (top === el || el.contains(top) || (el.labels && [...el.labels].some(l => l === top || l.contains(top)))));
    }
    out.push({ ref, inView, covered, tag: field ? tag : 'button', type, label,
      value: type === 'password' ? '' : clean(tag === 'select' ? (el.selectedOptions[0] || {}).label : field ? el.value : ''),
      checked: type === 'checkbox' || type === 'radio' ? !!el.checked : null,
      options: tag === 'select' ? [...el.options].filter(o => !o.disabled).slice(0, 30).map(o => clean(o.label)) : [] });
  }
  return { url: location.href, scroll: Math.round(scrollY), height: Math.round(Math.max(document.documentElement.scrollHeight, document.body ? document.body.scrollHeight : 0)), window: innerHeight, title: document.title.slice(0, 120), text: ((document.body && document.body.innerText) || '').replace(/[ \t]+/g, ' ').replace(/\s*\n\s*/g, '\n').slice(0, maxText), elements: out };
}

// Resolves when nothing in the page has changed for `quiet` ms, or after `cap` ms (pages with carousels or video never go quiet).
function quiet({ quiet, cap }) {
  return new Promise(resolve => {
    let timer; const done = () => { obs.disconnect(); clearTimeout(capTimer); resolve(true); };
    const obs = new MutationObserver(() => { clearTimeout(timer); timer = setTimeout(done, quiet); });
    const capTimer = setTimeout(done, cap);
    obs.observe(document, { subtree: true, childList: true, attributes: true, characterData: true });
    timer = setTimeout(done, quiet);
  });
}

// Bring a control into view and say where it is, and whether something else (a popup, a banner) is on top of it.
function locate({ ref }) {
  const el = document.querySelector(`[data-jev-ref="${ref}"]`);
  if (!el) return null;
  el.scrollIntoView({ block: 'center', inline: 'center' });
  const r = el.getBoundingClientRect(), x = r.left + r.width / 2, y = r.top + r.height / 2, top = document.elementFromPoint(x, y);
  const mine = top && (top === el || el.contains(top) || (el.labels && [...el.labels].some(l => l === top || l.contains(top))));
  return { x, y, covered: !mine, disabled: !!el.disabled || el.getAttribute('aria-disabled') === 'true', readonly: !!el.readOnly };
}

function focusField({ ref }) {
  const el = document.querySelector(`[data-jev-ref="${ref}"]`);
  if (!el) return false;
  el.focus(); if (el.select) el.select();                           // typing then replaces what was there
  return true;
}

function choose({ ref, label }) {
  const el = document.querySelector(`[data-jev-ref="${ref}"]`);
  if (!el || el.tagName !== 'SELECT') return 'that is not a dropdown';
  const lc = s => String(s).trim().toLowerCase(), o = [...el.options];
  let i = o.findIndex(x => x.label === label);
  if (i < 0) i = o.findIndex(x => lc(x.label) === lc(label));
  if (i < 0) i = o.findIndex(x => lc(x.label).startsWith(lc(label)));
  if (i < 0) return 'no such option';
  el.selectedIndex = i;
  el.dispatchEvent(new Event('input', { bubbles: true })); el.dispatchEvent(new Event('change', { bubbles: true }));
  return 'ok';
}

// What is at a point on the screen: the control under it (looking through open shadow roots), with the name a person would give it.
function hitAt({ x, y }) {
  let el = document.elementFromPoint(x, y);
  while (el && el.shadowRoot) { const inner = el.shadowRoot.elementFromPoint(x, y); if (!inner || inner === el) break; el = inner; }
  if (!el) return null;
  const clean = s => (s || '').replace(/\s+/g, ' ').replace(/"/g, "'").trim().slice(0, 100);
  const control = el.closest('a, button, input, select, textarea, summary, label, [role=button], [role=link], [role=checkbox], [role=tab]');
  const c = control || el, tag = c.tagName.toLowerCase(), field = ['input', 'select', 'textarea'].includes(tag);
  const type = tag === 'input' ? (c.getAttribute('type') || 'text').toLowerCase() : '';
  const img = c.querySelector && c.querySelector('img[alt]');
  const named = c.getAttribute('aria-label') || (field ? (c.labels && c.labels[0] && c.labels[0].innerText) || c.placeholder || c.name || c.title : c.innerText || c.value || c.title || (img && img.alt));
  const label = clean(control || (c.innerText || '').length <= 40 ? named : c.getAttribute('aria-label') || c.title || (img && img.alt)) || (type === 'password' ? 'Password' : '');
  const editable = tag === 'textarea' || (tag === 'input' && !['checkbox', 'radio', 'submit', 'button', 'reset', 'image', 'file', 'range', 'color', 'hidden'].includes(type)) || !!c.isContentEditable;
  return { tag, type, label, editable, disabled: !!c.disabled || c.getAttribute('aria-disabled') === 'true' };
}

// After a click on a text field: is the focus really in something that takes text? If so, select what is there so typing replaces it.
function focusActive() {
  const el = document.activeElement;
  if (!el) return false;
  const tag = el.tagName.toLowerCase(), type = tag === 'input' ? (el.getAttribute('type') || 'text').toLowerCase() : '';
  const ok = tag === 'textarea' || (tag === 'input' && !['checkbox', 'radio', 'submit', 'button', 'reset', 'image', 'file', 'range', 'color', 'hidden'].includes(type)) || el.isContentEditable;
  if (!ok || el.readOnly || el.disabled) return false;
  if (el.select) el.select(); else document.execCommand('selectAll');
  return true;
}

// ------------------------------------------------------------------ the DevTools connection
class Cdp {
  constructor(ws, onEvent) {
    this.ws = ws; this.nextId = 0; this.pending = new Map(); this.onEvent = onEvent;
    ws.onmessage = e => {
      const m = JSON.parse(e.data);
      if (m.id === undefined) return this.onEvent(m);
      const p = this.pending.get(m.id); this.pending.delete(m.id);
      if (p) m.error ? p.reject(new Error(m.error.message)) : p.resolve(m.result || {});
    };
    ws.onclose = () => { event('browser', 'DISCONNECTED (Chrome closed the connection)'); for (const p of this.pending.values()) p.reject(new Error('Chrome closed the connection')); this.pending.clear(); };
  }
  send(method, params = {}, sessionId, timeout = 30000) {
    const id = ++this.nextId, started = Date.now();
    this.ws.send(JSON.stringify({ id, method, params, ...(sessionId ? { sessionId } : {}) }));
    return new Promise((resolve, reject) => {
      const slow = outcome => { if (Date.now() - started > 3000) event('slow call', method, outcome, (Date.now() - started) + ' ms'); };   // so the log names whatever Chrome is slow at
      this.pending.set(id, { resolve: v => { slow('answered'); resolve(v); }, reject: e => { slow('failed'); reject(e); } });
      setTimeout(() => { if (this.pending.delete(id)) { event('slow call', method, 'NO ANSWER', timeout + ' ms'); reject(new Error(`Chrome did not answer ${method} in time`)); } }, timeout);
    });
  }
}

let chrome, cdp, profile, current = null, lastUrl = '', tabCount = 0, shotCount = 0;
const tabs = new Map(), attaching = new Map(), bySession = new Map();
if (SHOTS) mkdirSync(SHOTS, { recursive: true });

async function launch() {
  if (typeof WebSocket === 'undefined') throw new Error('Node 22 or newer is needed (it has WebSocket built in)');
  profile = mkdtempSync(join(tmpdir(), 'jevbrowse-'));                // a fresh profile every run: no saved logins, cookies or cards
  const args = ['--remote-debugging-port=0', `--user-data-dir=${profile}`, '--no-first-run', '--no-default-browser-check',
    `--window-size=${WINDOW}`,
    '--disable-backgrounding-occluded-windows', '--disable-renderer-backgrounding', '--disable-background-timer-throttling'];   // a window behind other apps must still answer clicks and scrolls
  if (process.env.BROWSE_HEADLESS === '1') args.push('--headless=new');
  chrome = spawn(CHROME, args, { stdio: 'ignore' });
  chrome.on('exit', code => event('browser', 'CHROME EXITED', code));
  let port, path;
  for (const until = Date.now() + 15000; Date.now() < until && !port;) {
    try { [port, path] = readFileSync(join(profile, 'DevToolsActivePort'), 'utf8').trim().split('\n'); } catch { await sleep(100); }
  }
  if (!port) throw new Error('Chrome did not start');
  const ws = new WebSocket(`ws://127.0.0.1:${port}${path}`);
  await new Promise((resolve, reject) => { ws.onopen = resolve; ws.onerror = () => reject(new Error('could not connect to Chrome')); });
  cdp = new Cdp(ws, onEvent);
  await cdp.send('Browser.setDownloadBehavior', { behavior: 'deny' }).catch(() => {});
  await cdp.send('Target.setDiscoverTargets', { discover: true });
  const { targetInfos } = await cdp.send('Target.getTargets');
  const first = targetInfos.find(t => t.type === 'page');
  const target = first ? first.targetId : (await cdp.send('Target.createTarget', { url: 'about:blank' })).targetId;
  current = await attachTab(target);
}

function attachTab(targetId) {
  if (!attaching.has(targetId)) attaching.set(targetId, (async () => {
    const tab = { id: 'tab' + (++tabCount), targetId, sessionId: null, url: '', closed: false };
    tabs.set(targetId, tab);
    const { sessionId } = await cdp.send('Target.attachToTarget', { targetId, flatten: true });
    tab.sessionId = sessionId; bySession.set(sessionId, tab);
    await cdp.send('Page.enable', {}, sessionId);
    await cdp.send('Emulation.setFocusEmulationEnabled', { enabled: true }, sessionId).catch(() => {});     // the page believes it is focused even when another app is in front
    cdp.send('Page.bringToFront', {}, sessionId).catch(() => {});      // so the person watching sees the window
    event(tab.id, 'opened');
    return tab;
  })());
  return attaching.get(targetId);
}

function onEvent(m) {
  const p = m.params || {}, tab = bySession.get(m.sessionId);
  if (m.method === 'Target.targetCreated' && p.targetInfo.type === 'page') {
    attachTab(p.targetInfo.targetId).then(t => { if (p.targetInfo.openerId) { current = t; event(t.id, 'is a popup or new tab; following it'); } }).catch(() => {});
  } else if (m.method === 'Target.targetInfoChanged' && tabs.has(p.targetInfo.targetId)) {
    tabs.get(p.targetInfo.targetId).url = p.targetInfo.url;
  } else if (m.method === 'Target.targetDestroyed' && tabs.has(p.targetId)) {
    const t = tabs.get(p.targetId); t.closed = true; event(t.id, 'CLOSED (last address ' + (t.url || '?').slice(0, 100) + ')');
  } else if (m.method === 'Inspector.targetCrashed' && tab) {
    event(tab.id, 'CRASHED');
  } else if (m.method === 'Page.javascriptDialogOpening' && tab) {      // a browser alert would freeze the page
    event(tab.id, 'dialog', p.type, JSON.stringify(String(p.message).slice(0, 80)));
    cdp.send('Page.handleJavaScriptDialog', { accept: false }, m.sessionId).catch(() => {});
  } else if (m.method === 'Page.frameNavigated' && tab && !p.frame.parentId) {
    tab.url = p.frame.url; event(tab.id, 'went to', p.frame.url.slice(0, 100));
  }
}

// The tab JEV is looking at. If it closed (a popup that closes itself, a site closing a tab), carry on in another one, or open a new one on the last page.
async function ensureTab() {
  if (current && !current.closed) return current;
  const open = [...tabs.values()].filter(t => !t.closed && t.sessionId);
  if (open.length) { current = open[open.length - 1]; event(current.id, 'now being used (the earlier tab closed)'); return current; }
  const { targetId } = await cdp.send('Target.createTarget', { url: 'about:blank' });
  current = await attachTab(targetId);
  event(current.id, 'new tab: none was left');
  if (lastUrl) await go(current, lastUrl).catch(() => {});
  return current;
}

async function evalIn(tab, expression) {
  const r = await cdp.send('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true }, tab.sessionId);
  if (r.exceptionDetails) throw new Error(((r.exceptionDetails.exception || {}).description || r.exceptionDetails.text || 'page error').split('\n')[0]);
  return r.result.value;
}
const run = (tab, fn, arg) => evalIn(tab, `(${fn.toString()})(${JSON.stringify(arg)})`);

async function go(tab, url) {
  const r = await cdp.send('Page.navigate', { url }, tab.sessionId);
  if (r.errorText) throw new Error(r.errorText);
  lastUrl = url;
}

// Wait until the page has loaded and then stopped changing (0.3 s still, 1.5 s at most): never "network idle", which busy sites never reach.
async function settle(tab) {
  await sleep(150);                                                    // let a click start its navigation first
  for (const until = Date.now() + 8000; Date.now() < until;) {
    const state = await evalIn(tab, 'document.readyState').catch(() => null);
    if (state === 'interactive' || state === 'complete') break;
    await sleep(100);
  }
  await run(tab, quiet, { quiet: 300, cap: 1500 }).catch(() => {});
}

async function look() {
  const tab = await ensureTab();
  await settle(tab);
  let page;
  try { page = await run(tab, describe, { sel: SELECTOR, max: MAX_CONTROLS, maxText: MAX_TEXT }); }
  catch { await sleep(400); page = await run(tab, describe, { sel: SELECTOR, max: MAX_CONTROLS, maxText: MAX_TEXT }); }   // the page was changing under us: once more
  if (/^https?:/.test(page.url)) lastUrl = page.url;
  return page;
}

// A picture of the window for JEV, inside what JEV accepts: each side 280-1568 px and at most ~2.4 million pixels (anything else is refused, never resized).
function jpegSize(buf) {
  for (let i = 2; i + 9 < buf.length;) {
    if (buf[i] !== 0xff) { i++; continue; }
    const m = buf[i + 1];
    if (m >= 0xc0 && m <= 0xcf && ![0xc4, 0xc8, 0xcc].includes(m)) return { height: buf.readUInt16BE(i + 5), width: buf.readUInt16BE(i + 7) };
    i += 2 + buf.readUInt16BE(i + 2);
  }
  throw new Error('not a JPEG');
}

async function screenshot() {
  const tab = await ensureTab();
  const [w, h, dpr] = await evalIn(tab, '[innerWidth, innerHeight, devicePixelRatio || 1]');
  const scale = Math.min(1 / dpr, 1500 / (Math.max(w, h) * dpr), Math.sqrt(2300000 / (w * h * dpr * dpr)));
  const shot = await cdp.send('Page.captureScreenshot', { format: 'jpeg', quality: 80, clip: { x: 0, y: 0, width: w, height: h, scale } }, tab.sessionId, 8000);
  const bytes = Buffer.from(shot.data, 'base64'), size = jpegSize(bytes);
  let file;
  if (SHOTS) { file = `step-${String(++shotCount).padStart(3, '0')}.jpg`; writeFileSync(join(SHOTS, file), bytes); }
  return { data: shot.data, ...size, view: { w, h }, file };
}

// ------------------------------------------------------------------ doing things
const mouse = (tab, params) => cdp.send('Input.dispatchMouseEvent', params, tab.sessionId);

async function act({ action, ref, x, y, value }) {
  const tab = await ensureTab();
  if (action === 'scroll_down') {
    const [x, y] = await evalIn(tab, '[innerWidth / 2, innerHeight / 2]');          // the middle of the page, wherever the window is
    await mouse(tab, { type: 'mouseWheel', x, y, deltaX: 0, deltaY: 650 }); await sleep(250); return;
  }
  if (action === 'press_enter') {
    const key = { key: 'Enter', code: 'Enter', windowsVirtualKeyCode: 13, nativeVirtualKeyCode: 13 };
    await cdp.send('Input.dispatchKeyEvent', { type: 'keyDown', text: '\r', ...key }, tab.sessionId);
    await cdp.send('Input.dispatchKeyEvent', { type: 'keyUp', ...key }, tab.sessionId);
    await sleep(300); return;
  }
  if (['clickat', 'typeat'].includes(action)) {                          // screenshot mode: a point on the screen
    if (!Number.isFinite(x) || !Number.isFinite(y)) throw new Error('no point to act on');
    for (const type of ['mouseMoved', 'mousePressed', 'mouseReleased']) await mouse(tab, { type, x, y, button: 'left', buttons: type === 'mousePressed' ? 1 : 0, clickCount: type === 'mouseMoved' ? 0 : 1 });
    if (action === 'typeat') {
      if (typeof value !== 'string' || !value || value.length > 500) throw new Error('nothing valid to type');
      await sleep(200);
      if (!(await run(tab, focusActive, {}))) throw new Error('no text field took the click');
      await cdp.send('Input.insertText', { text: value }, tab.sessionId);
    }
  } else {                                                             // controls mode: a numbered control from the last look
    if (!['click', 'type', 'select'].includes(action) || !Number.isInteger(ref)) throw new Error('unknown action');
    const spot = await run(tab, locate, { ref });
    if (!spot) throw new Error('that element is no longer on the page');
    if (spot.disabled) throw new Error('that element is disabled');
    if (action === 'click') {
      if (spot.covered) throw new Error('something else is on top of it (a popup or a banner?)');
      for (const type of ['mouseMoved', 'mousePressed', 'mouseReleased']) await mouse(tab, { type, x: spot.x, y: spot.y, button: 'left', buttons: type === 'mousePressed' ? 1 : 0, clickCount: type === 'mouseMoved' ? 0 : 1 });
    } else if (action === 'type') {
      if (spot.readonly) throw new Error('that field cannot be typed into');
      if (typeof value !== 'string' || !value || value.length > 500) throw new Error('nothing valid to type');
      if (!(await run(tab, focusField, { ref }))) throw new Error('that element is no longer on the page');
      await cdp.send('Input.insertText', { text: value }, tab.sessionId);
    } else {
      const result = await run(tab, choose, { ref, label: value });
      if (result !== 'ok') throw new Error(result);
    }
  }
  await sleep(300);                                                    // a link that opens a new tab reports it a moment later
}

async function handle(msg) {
  if (msg.cmd === 'open') {
    const tab = await ensureTab();
    try { await go(tab, msg.url); } catch (e) { return { ok: false, error: 'could not open: ' + e.message }; }
    return { ok: true, page: await look() };
  }
  if (msg.cmd === 'look') return { ok: true, page: await look() };
  if (msg.cmd === 'shot') { try { return { ok: true, ...(await screenshot()) }; } catch (e) { return { ok: false, error: 'no picture: ' + e.message.slice(0, 140) }; } }
  if (msg.cmd === 'probe') { const tab = await ensureTab(); return { ok: true, hit: await run(tab, hitAt, { x: msg.x, y: msg.y }) }; }
  if (msg.cmd === 'act') {
    try { await act(msg); } catch (e) { return { ok: false, error: e.message.slice(0, 160) }; }
    return { ok: true };
  }
  return { ok: false, error: 'unknown command' };
}

async function shutdown() {
  try { await cdp.send('Browser.close', {}, undefined, 3000); } catch { /* already gone */ }
  try { chrome.kill(); } catch { /* already gone */ }
  try { rmSync(profile, { recursive: true, force: true }); } catch { /* temp folder */ }
}

try { await launch(); } catch (e) { console.error('runner could not start:', e.message); await shutdown().catch(() => {}); process.exit(1); }
let queue = Promise.resolve();
createInterface({ input: process.stdin }).on('line', line => {
  queue = queue.then(async () => {
    const msg = JSON.parse(line);
    if (msg.cmd === 'close') { await shutdown(); console.log(JSON.stringify({ id: msg.id, ok: true })); process.exit(0); }
    let res; try { res = await handle(msg); } catch (e) { console.error('runner error', e.message); res = { ok: false, error: 'runner error: ' + String(e.message).slice(0, 160) }; }
    console.log(JSON.stringify({ id: msg.id, ...res }));
  });
}).on('close', async () => { await queue; await shutdown(); process.exit(0); });
