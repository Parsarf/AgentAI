// The extension's "hands": the same command protocol as ../../runner.mjs (open, snapshot, act, xy, view, probe, screenshot, close), done in a tab of the
// customer's own Chrome over the DevTools protocol. Deterministic, no model, no decisions: the host (the platform) judges what to do; this performs one
// already-validated step at a time and answers with the same fields the runner does.
//
// It talks to the browser only through `host`, so the same code runs in the extension (chrome.debugger / chrome.tabs) and in the tests (Playwright):
//   host.tabs()                  -> [tabId]  the tabs this session owns, oldest first (popups the agent opened are added by the host, capped at MAX_PAGES)
//   host.newTab()                -> tabId    a blank tab the session owns, already attached for DevTools commands
//   host.closeTab(tabId)
//   host.send(tabId, method, params) -> result   one DevTools command
//   host.onEvent(fn)             fn(tabId, method, params) for DevTools events
//   host.activate(tabId)         bring the tab to the front (a background tab may not paint, so a picture of it can stall)
import { WIDTH, HEIGHT, MAX_ELEMENTS, MAX_VALUE, MAX_URL, KEYS, TAKEOVER_KEYS, SELECTOR, urlAllowed, pointOk } from './rules.js';
import { describe, hitAt, focusActive, fingerprint, ready, locate, chooseOption, focusForFill } from './page.js';

const KEY_INFO = {
  Enter: { code: 'Enter', vk: 13, text: '\r' }, Tab: { code: 'Tab', vk: 9 }, Escape: { code: 'Escape', vk: 27 },
  Backspace: { code: 'Backspace', vk: 8 }, Delete: { code: 'Delete', vk: 46 }, Home: { code: 'Home', vk: 36 }, End: { code: 'End', vk: 35 },
  PageUp: { code: 'PageUp', vk: 33 }, PageDown: { code: 'PageDown', vk: 34 }, ArrowLeft: { code: 'ArrowLeft', vk: 37 }, ArrowUp: { code: 'ArrowUp', vk: 38 },
  ArrowRight: { code: 'ArrowRight', vk: 39 }, ArrowDown: { code: 'ArrowDown', vk: 40 },
};
const err = (error, detail) => (detail ? { ok: false, error, detail: String(detail).slice(0, 160) } : { ok: false, error });
const withTimeout = (p, ms) => Promise.race([p, new Promise((_, no) => setTimeout(() => no(new Error('timeout')), ms))]);

export class Executor {
  constructor(host, { allowLoopback = false, sleep = ms => new Promise(r => setTimeout(r, ms)) } = {}) {
    this.host = host; this.allowLoopback = allowLoopback; this.sleep = sleep;
    this.current = null; this.prepared = new Map(); this.blocked = [];
    host.onEvent((tab, method, params) => this.event(tab, method, params));
  }

  /** Called for every tab the session owns before it loads anything: the window every picture and point is judged against, and the address rules on every request the tab makes. */
  prepare(tab) {
    if (!this.prepared.has(tab)) {
      const send = (m, p) => this.host.send(tab, m, p);
      this.prepared.set(tab, (async () => {
        await send('Page.enable');
        await send('Emulation.setDeviceMetricsOverride', { width: WIDTH, height: HEIGHT, deviceScaleFactor: 1, mobile: false });
        await send('Fetch.enable', { patterns: [{ urlPattern: '*' }] });
      })());
    }
    return this.prepared.get(tab);      // callers on the same tab wait for the same setup
  }

  /** The host calls this the moment a tab joins the session (a popup the page opened, say): set it up and make it the tab commands go to, as the runner follows new pages. */
  adopt(tab) { this.current = tab; return this.prepare(tab); }

  event(tab, method, p) {
    if (method === 'Fetch.requestPaused') {
      const ok = urlAllowed(p.request.url, this.allowLoopback);
      if (!ok) this.blocked = [...this.blocked.slice(-49), p.request.url.slice(0, 120)];
      this.host.send(tab, ok ? 'Fetch.continueRequest' : 'Fetch.failRequest', ok ? { requestId: p.requestId } : { requestId: p.requestId, errorReason: 'BlockedByClient' }).catch(() => {});
    } else if (method === 'Page.javascriptDialogOpening') {
      this.host.send(tab, 'Page.handleJavaScriptDialog', { accept: false }).catch(() => {});      // alert / confirm / prompt would freeze the page: dismiss, as the runner does
    }
  }

  /** The tab commands go to: the one in use, or the newest still open, or a fresh blank one (the last tab closed). */
  async page() {
    const open = this.host.tabs();
    if (!this.current || !open.includes(this.current)) this.current = open.length ? open[open.length - 1] : await this.host.newTab();
    await this.prepare(this.current);
    return this.current;
  }

  async cdp(method, params) { return this.host.send(await this.page(), method, params); }

  async ev(fn, arg, helpers = []) {
    const expression = `(() => {\n${helpers.map(String).join('\n')}\nreturn (${fn})(${JSON.stringify(arg ?? null)});\n})()`;
    const r = await this.cdp('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true });
    if (r.exceptionDetails) throw new Error(r.exceptionDetails.exception?.description || r.exceptionDetails.text || 'evaluate failed');
    return r.result.value;
  }

  async url() { try { return await this.ev(() => location.href); } catch { return ''; } }
  async title() { try { return String(await this.ev(() => document.title)).slice(0, 120); } catch { return ''; } }
  async fp() {      // null = could not tell (page changing under us); the same 12 hex characters of SHA-1 the runner gives
    try {
      const d = await crypto.subtle.digest('SHA-1', new TextEncoder().encode(await this.ev(fingerprint, SELECTOR)));
      return [...new Uint8Array(d)].map(b => b.toString(16).padStart(2, '0')).join('').slice(0, 12);
    } catch { return null; }
  }

  /** DOM ready, then the page quiet: no new resources for two looks in a row (about half a second), at most 2.5 s. Slow pages are fine. */
  async settle() {
    try {
      for (let i = 0; i < 20 && (await this.ev(() => document.readyState)) === 'loading'; i++) await this.sleep(250);
      let last = -1, still = 0;
      for (let i = 0; i < 10; i++) {
        const n = await this.ev(() => performance.getEntriesByType('resource').length + (document.readyState === 'complete' ? 0 : 1000));
        if (n === last) { if (++still >= 2) break; } else { still = 0; last = n; }
        await this.sleep(250);
      }
    } catch { /* the page changed under us: the next step looks again */ }
  }

  async handle(msg) {
    try {
      if (!msg || typeof msg.cmd !== 'string') return err('unknown_command');
      if (msg.cmd === 'close') return await this.close();
      const fn = { open: this.open, snapshot: this.snapshot, act: this.act, xy: this.xy, view: this.view, probe: this.probe, screenshot: this.screenshot }[msg.cmd];
      return fn ? await fn.call(this, msg) : err('unknown_command');
    } catch (e) { return err('runner_error', e && e.message); }
  }

  // ---------------------------------------------------------------------------------------------------------------- commands
  async open(msg) {
    if (typeof msg.url !== 'string' || msg.url.length > MAX_URL || !urlAllowed(msg.url, this.allowLoopback)) return err('url_blocked');
    const nav = await this.cdp('Page.navigate', { url: msg.url });
    if (nav.errorText) return err('navigation_failed', nav.errorText);
    await this.settle();
    return { ok: true, url: await this.url(), title: await this.title() };
  }

  async snapshot() {
    await this.settle();
    const d = await this.ev(describe, { sel: SELECTOR, max: MAX_ELEMENTS });
    const lines = d.elements.map(e => `[${e.ref}] <${e.tag}${e.type ? ' type=' + e.type : ''}> "${e.label}"`).join('\n');
    return { ok: true, url: await this.url(), title: d.title, snapshot: lines, text: d.text, pages: this.host.tabs().length || 1, elements: d.elements, page_fp: await this.fp(), scroll: d.scroll, height: d.height, window: d.window };
  }

  async act(msg) {
    const { ref, action, value, expect } = msg;
    const done = async extra => ({ ok: true, url: await this.url(), page_fp: await this.fp(), ...extra });
    if (action === 'back') { await this.history(-1); await this.settle(); return done(); }
    if (action === 'press') { if (!KEYS.has(value)) return err('key_not_allowed'); await this.key(value); await this.settle(); return done(); }
    if (action === 'scroll') {
      if (value !== undefined && value !== null && !['down', 'up'].includes(value)) return err('bad_value');
      await this.wheel(value === 'up' ? -700 : 700); await this.sleep(150); return done();
    }
    if (action === 'wait') { await this.sleep(1000); await this.settle(); return done(); }
    const before = await this.url(), pagesBefore = this.host.tabs().length;
    const after = async () => { await this.page(); await this.sleep(400); await this.settle(); return done({ navigated: (await this.url()) !== before, new_tab: this.host.tabs().length > pagesBefore }); };

    if (action === 'clickat' || action === 'typeat') {      // a point chosen from a picture: the host has already named what is there (probe) and run its rules on it
      const { x, y } = msg;
      if (!pointOk(x, y)) return err('bad_coordinates');
      if (action === 'typeat' && (typeof value !== 'string' || !value || value.length > MAX_VALUE)) return err('bad_value');
      try {
        await this.click(x, y);
        if (action === 'typeat') {
          await this.sleep(200);
          if (!(await this.ev(focusActive))) return err('not_a_field');
          await this.cdp('Input.insertText', { text: value });
        }
      } catch { return err('action_failed'); }
      return after();
    }

    if (!['click', 'type', 'select'].includes(action) || !Number.isInteger(ref)) return err('bad_action');
    if ((action === 'type' || action === 'select') && (typeof value !== 'string' || value.length > MAX_VALUE)) return err('bad_value');
    const at = await this.ev(locate, { ref, expect, action }, [ready]);
    if (at.state !== 'ok') return err(at.state);
    try {
      if (action === 'click') await this.click(at.x, at.y);
      else if (action === 'type') {
        await this.click(at.x, at.y);
        if (!(await this.ev(focusForFill, { ref }))) return err('action_failed');
        await this.cdp('Input.insertText', { text: value });
      } else {
        const idx = await this.ev(chooseOption, { ref, value });
        if (idx === -1) return err('no_option');
        if (idx < 0) return err('stale');
      }
    } catch { return err('action_failed'); }
    return after();
  }

  async xy(msg) {   // takeover: coordinates come from the customer's own click on the picture; the host has already range-checked them
    const { x, y, action, text } = msg;
    if (action === 'click' && !pointOk(x, y)) return err('bad_coordinates');
    try {
      if (action === 'click') await this.click(x, y, 4);
      else if (action === 'type') { if (typeof text !== 'string' || text.length > MAX_VALUE) return err('bad_value'); await this.cdp('Input.insertText', { text }); }
      else if (action === 'key') { if (!KEYS.has(text) && !TAKEOVER_KEYS.has(text)) return err('key_not_allowed'); await this.key(text); }
      else if (action === 'scroll') await this.wheel(Number(text) > 0 ? 500 : -500);
      else if (action === 'goto') {
        if (typeof text !== 'string' || text.length > MAX_URL || !urlAllowed(text, this.allowLoopback)) return err('url_blocked');
        await this.cdp('Page.navigate', { url: text });
      } else if (action === 'back') await this.history(-1);
      else if (action === 'forward') await this.history(1);
      else if (action === 'reload') await this.cdp('Page.reload');
      else return err('bad_action');
    } catch { return err('action_failed'); }
    return { ok: true, url: await this.url() };       // no waiting for the page to settle: the next input must not queue behind a slow load
  }

  async view() {
    const tab = await this.page();
    const shoot = () => this.host.send(tab, 'Page.captureScreenshot', { format: 'jpeg', quality: 75, fromSurface: true });
    let shot;
    try { shot = await withTimeout(shoot(), 4000); } catch { await this.host.activate(tab); shot = await withTimeout(shoot(), 6000); }      // a background tab may not paint: bring it forward, once
    return { ok: true, data: shot.data, width: WIDTH, height: HEIGHT, view: { w: WIDTH, h: HEIGHT } };
  }

  /** The runner keeps the file itself; here the picture comes back as `data` and whoever owns the job's folder writes shot-NNN.jpg (see dev/drive.mjs). */
  async screenshot() {
    const v = await this.view();
    return { ok: true, data: v.data };
  }

  async probe({ x, y }) {
    if (!pointOk(x, y)) return err('bad_coordinates');
    return { ok: true, hit: await this.ev(hitAt, { x, y }) };
  }

  async close() {
    for (const t of this.host.tabs()) await this.host.closeTab(t).catch(() => {});
    this.current = null; this.prepared.clear();
    return { ok: true };
  }

  // ---------------------------------------------------------------------------------------------------------------- input
  async click(x, y, steps = 3) {
    for (let i = 1; i <= steps; i++) await this.cdp('Input.dispatchMouseEvent', { type: 'mouseMoved', x: x * i / steps, y: y * i / steps });
    await this.cdp('Input.dispatchMouseEvent', { type: 'mousePressed', x, y, button: 'left', clickCount: 1 });
    await this.sleep(40);
    await this.cdp('Input.dispatchMouseEvent', { type: 'mouseReleased', x, y, button: 'left', clickCount: 1 });
  }

  async wheel(deltaY) { await this.cdp('Input.dispatchMouseEvent', { type: 'mouseWheel', x: WIDTH / 2, y: HEIGHT / 2, deltaX: 0, deltaY }); }

  async key(name) {
    const k = KEY_INFO[name];
    const base = { key: name, code: k.code, windowsVirtualKeyCode: k.vk, nativeVirtualKeyCode: k.vk };
    await this.cdp('Input.dispatchKeyEvent', { type: k.text ? 'keyDown' : 'rawKeyDown', ...base, ...(k.text ? { text: k.text } : {}) });
    await this.cdp('Input.dispatchKeyEvent', { type: 'keyUp', ...base });
  }

  async history(delta) {
    const h = await this.cdp('Page.getNavigationHistory');
    const entry = h.entries[h.currentIndex + delta];
    if (entry) await this.cdp('Page.navigateToHistoryEntry', { entryId: entry.id });
  }
}
