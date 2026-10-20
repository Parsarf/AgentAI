// Lumina browse runner: the "hands". Runs INSIDE the sandboxed browser stage; deterministic, no model, no network of its own.
// Protocol: one JSON object per line on stdin -> one JSON object per line on stdout. The host decides everything; this file only
// opens pages, describes them, and performs one already-validated action at a time.
import { chromium } from 'playwright-core';
import { createInterface } from 'node:readline';
import { mkdirSync, statSync, writeFileSync, renameSync } from 'node:fs';
import { join } from 'node:path';
import { createHash } from 'node:crypto';
import { lookup as dnsLookup } from 'node:dns/promises';

const CHROME = process.env.BROWSE_CHROME || '/usr/bin/chromium';
const OUT = process.env.BROWSE_OUT || '/tmp/out';
const ALLOW_LOOPBACK = process.env.BROWSE_ALLOW_LOOPBACK === '1';   // tests only; never set in the stage
const MAX_ELEMENTS = 80, MAX_TEXT = 6000, MAX_PAGES = 3, MAX_VALUE = 500;
const KEYS = new Set(['Enter', 'Tab', 'Escape']);
// Live view: Chrome pushes JPEG frames only when the page changes; we keep ONLY the newest one (live.jpg, replaced atomically) and only
// while the host has recently touched OUT/watching. Nobody watching = no screencast, no CPU, no disk writes.
const LIVE = { fps: 15, quality: 60, width: 1280, height: 800, watchSeconds: 6, pollMs: 250 };

/** An address (not a name) in a private, loopback, link-local or otherwise internal range. */
export function privateIp(h) {
  const m = h.match(/^(\d+)\.(\d+)\.(\d+)\.(\d+)$/);
  if (m) { const [a, b] = [+m[1], +m[2]]; return a === 10 || a === 127 || a === 0 || (a === 169 && b === 254) || (a === 172 && b >= 16 && b <= 31) || (a === 192 && b === 168) || (a === 100 && b >= 64 && b <= 127); }
  if (h.includes(':')) {
    const v4 = h.toLowerCase().match(/^::ffff:(\d+\.\d+\.\d+\.\d+)$/);                       // an IPv4 address written as IPv6
    return v4 ? privateIp(v4[1]) : /^(fc|fd|fe80|::1|::)/i.test(h);
  }
  return false;
}

export function urlAllowed(raw, allowLoopback = false) {
  let u; try { u = new URL(raw); } catch { return false; }
  if (!['http:', 'https:'].includes(u.protocol)) return false;
  const h = u.hostname.toLowerCase().replace(/^\[|\]$/g, '');
  if (u.username || u.password) return false;
  const loop = h === 'localhost' || h === '127.0.0.1' || h === '::1';
  if (loop) return allowLoopback;
  if (h.endsWith('.local') || h.endsWith('.internal') || h.endsWith('.localhost')) return false;
  return !privateIp(h);
}

const SELECTOR = 'a[href], button, input:not([type=hidden]), select, textarea, [role=button], [role=link], [role=checkbox], [role=radio], [role=tab], [onclick]';

// Runs in the page. Describes interactive elements in the format the host parses: [ref] <tag type=x> "label", plus their state.
// A field that holds a secret (password, card, one-time code) is always listed, never with its value, so the host can see that the page needs the user.
function describe(args) {
  const { sel, max } = args;
  for (const el of document.querySelectorAll('[data-lumina-ref]')) { el.removeAttribute('data-lumina-ref'); el.removeAttribute('data-lumina-label'); }
  const clean = s => (s || '').replace(/\s+/g, ' ').replace(/"/g, "'").trim().slice(0, 100);
  const out = []; let n = 0;
  const vw = window.innerWidth, vh = window.innerHeight;
  for (const el of document.querySelectorAll(sel)) {
    if (n >= max) break;
    const r = el.getBoundingClientRect(); const st = getComputedStyle(el);
    if (r.width < 2 || r.height < 2 || st.visibility === 'hidden' || st.display === 'none' || el.disabled || el.closest('[aria-hidden=true]')) continue;
    const tag = el.tagName.toLowerCase(); const role = el.getAttribute('role');
    let kind = tag === 'a' || role === 'link' ? 'a' : tag === 'input' || tag === 'select' || tag === 'textarea' ? tag : 'button';
    const type = kind === 'input' ? (el.getAttribute('type') || 'text').toLowerCase().replace(/[^a-z]/g, '') : '';
    const secret = type === 'password' || /^(cc-|one-time-code|current-password|new-password)/.test((el.getAttribute('autocomplete') || '').toLowerCase());
    let label = clean(el.getAttribute('aria-label') || (kind === 'input' || kind === 'select' || kind === 'textarea' ? ((el.labels && el.labels[0] && el.labels[0].innerText) || el.placeholder || (secret ? '' : el.value) || el.name || el.getAttribute('title')) : (el.innerText || el.value || el.getAttribute('title'))));
    if (!label && secret) label = type === 'password' ? 'Password' : 'Secret field';
    if (!label) continue;
    n += 1; el.setAttribute('data-lumina-ref', String(n)); el.setAttribute('data-lumina-label', label);
    let value = '';
    if (!secret) {
      if (tag === 'select') value = el.selectedOptions && el.selectedOptions[0] ? el.selectedOptions[0].label : '';
      else if ((tag === 'input' && !['checkbox', 'radio', 'button', 'submit', 'reset', 'image', 'file'].includes(type)) || tag === 'textarea') value = el.value;
    }
    const ariaChecked = el.getAttribute('aria-checked'); const ariaExpanded = el.getAttribute('aria-expanded');
    const checked = type === 'checkbox' || type === 'radio' ? !!el.checked : ariaChecked === 'true' ? true : ariaChecked === 'false' ? false : null;
    const cx = r.left + r.width / 2, cy = r.top + r.height / 2;
    const options = tag === 'select' ? [...el.options].slice(0, 15).map(o => (o.label || '').replace(/\s+/g, ' ').trim().slice(0, 80)) : [];
    // Is something else on top of the middle of the part of it that shows? null when none of it is in the window. The host uses the share of covered controls to tell that a panel or popup is in the way.
    const vl = Math.max(r.left, 0), vr = Math.min(r.right, vw), vt = Math.max(r.top, 0), vb = Math.min(r.bottom, vh);
    let covered = null;
    if (vr - vl > 1 && vb - vt > 1) {
      const hit = document.elementFromPoint((vl + vr) / 2, (vt + vb) / 2);
      covered = !(hit && (hit === el || el.contains(hit) || (el.labels && [...el.labels].some(l => l === hit || l.contains(hit)))));
    }
    out.push({ ref: n, tag: kind, type, label, role: role || '', value: clean(value), checked, expanded: ariaExpanded === 'true' ? true : ariaExpanded === 'false' ? false : null,
      in_view: cx >= 0 && cy >= 0 && cx <= vw && cy <= vh, covered, options });
  }
  const page = document.documentElement;
  return { elements: out, title: document.title.slice(0, 120), text: (document.body && document.body.innerText || '').replace(/\s+\n/g, '\n').slice(0, 6000),
    scroll: Math.round(window.scrollY), height: Math.round(Math.max(page.scrollHeight, document.body ? document.body.scrollHeight : 0)), window: vh };
}

// Runs in the page. What is at a point on the screen: the control under it (looking through open shadow roots) with the name a person would give it.
// Used when a picture, not the element list, chose the target, so the host can run its safety rules on the label before anything is clicked.
function hitAt({ x, y }) {
  let el = document.elementFromPoint(x, y);
  while (el && el.shadowRoot) { const inner = el.shadowRoot.elementFromPoint(x, y); if (!inner || inner === el) break; el = inner; }
  if (!el) return null;
  const clean = s => (s || '').replace(/\s+/g, ' ').replace(/"/g, "'").trim().slice(0, 100);
  const control = el.closest('a, button, input, select, textarea, summary, label, [role=button], [role=link], [role=checkbox], [role=radio], [role=tab]');
  const c = control || el, tag = c.tagName.toLowerCase(), field = ['input', 'select', 'textarea'].includes(tag);
  const type = tag === 'input' ? (c.getAttribute('type') || 'text').toLowerCase().replace(/[^a-z]/g, '') : '';
  const secret = type === 'password' || /^(cc-|one-time-code|current-password|new-password)/.test((c.getAttribute('autocomplete') || '').toLowerCase());
  const img = c.querySelector && c.querySelector('img[alt]');
  const named = c.getAttribute('aria-label') || (field ? (c.labels && c.labels[0] && c.labels[0].innerText) || c.placeholder || c.name || c.title : c.innerText || c.value || c.title || (img && img.alt));
  const label = secret ? (type === 'password' ? 'Password' : 'Secret field') : clean(control || (c.innerText || '').length <= 40 ? named : c.getAttribute('aria-label') || c.title || (img && img.alt));
  const editable = tag === 'textarea' || (tag === 'input' && !['checkbox', 'radio', 'submit', 'button', 'reset', 'image', 'file', 'range', 'color', 'hidden'].includes(type)) || !!c.isContentEditable;
  return { tag, type, label, secret, editable, disabled: !!c.disabled || c.getAttribute('aria-disabled') === 'true' };
}

// Runs in the page, after a click on a text field: is the focus really in something that takes text? If so, select what is there so typing replaces it.
function focusActive() {
  const el = document.activeElement;
  if (!el) return false;
  const tag = el.tagName.toLowerCase(), type = tag === 'input' ? (el.getAttribute('type') || 'text').toLowerCase() : '';
  const ok = tag === 'textarea' || (tag === 'input' && !['checkbox', 'radio', 'submit', 'button', 'reset', 'image', 'file', 'range', 'color', 'hidden'].includes(type)) || el.isContentEditable;
  if (!ok || el.readOnly || el.disabled || type === 'password') return false;
  if (el.select) el.select(); else document.execCommand('selectAll');
  return true;
}

// Runs in the page. Read-only (marks nothing): a text summary of what a person would see, so two summaries are equal exactly when the page did not visibly change.
// Scroll position is part of it, so scrolling counts as a change until the bottom is reached.
function fingerprint(sel) {
  const parts = [location.href, String(Math.round(window.scrollY / 50)), String(((document.body && document.body.innerText) || '').length)];
  for (const el of document.querySelectorAll(sel)) {
    const r = el.getBoundingClientRect(); const st = getComputedStyle(el);
    if (r.width < 2 || r.height < 2 || st.visibility === 'hidden' || st.display === 'none' || el.closest('[aria-hidden=true]')) continue;
    const type = (el.getAttribute('type') || '').toLowerCase();
    const secret = type === 'password' || /^(cc-|one-time-code|current-password|new-password)/.test((el.getAttribute('autocomplete') || '').toLowerCase());
    const label = (el.getAttribute('aria-label') || el.innerText || el.placeholder || '').replace(/\s+/g, ' ').trim().slice(0, 60);
    const value = secret ? '' : (el.tagName === 'SELECT' ? (el.selectedOptions[0] && el.selectedOptions[0].label) : ['checkbox', 'radio'].includes(type) ? String(el.checked) : el.value) || '';
    parts.push(`${el.tagName}|${label}|${String(value).slice(0, 60)}|${el.getAttribute('aria-expanded') || ''}|${el.getAttribute('aria-checked') || ''}|${el.disabled ? 1 : 0}`);
  }
  return parts.join('\n');
}

// Runs in the page, on the element the host chose, right before acting. 'ok' | 'disabled' | 'covered' | 'stale'.
function ready(el, action) {
  if (!el.isConnected) return 'stale';
  if (el.disabled || el.getAttribute('aria-disabled') === 'true' || el.closest('[inert], [aria-disabled=true], fieldset:disabled')) return 'disabled';
  if (action === 'type' && (el.readOnly || el.getAttribute('aria-readonly') === 'true')) return 'disabled';
  const r = el.getBoundingClientRect();
  if (r.width < 2 || r.height < 2) return 'covered';
  const cx = r.left + r.width / 2, cy = r.top + r.height / 2;
  if (cx < 0 || cy < 0 || cx > window.innerWidth || cy > window.innerHeight) return 'covered';
  const top = document.elementFromPoint(cx, cy);
  if (!top) return 'covered';
  if (top === el || el.contains(top)) return 'ok';
  return 'covered';                                                                                // a banner, modal, or any other element is on top (the browser would refuse the click too, after a 6 s wait)
}

export class Runner {
  constructor({ lookup = dnsLookup } = {}) { this.lookup = lookup; this.dnsSeen = new Map(); this.blocked = []; this.browser = null; this.context = null; this.page = null; this.shots = 0; this.live = null; this.liveTimer = null; this.lastFrame = 0; }
  async start() {
    mkdirSync(OUT, { recursive: true });
    this.browser = await chromium.launch({ executablePath: CHROME, headless: true, args: ['--no-sandbox', '--disable-gpu', '--disable-dev-shm-usage', '--disable-crash-reporter', '--no-first-run'] });
    this.context = await this.browser.newContext({ acceptDownloads: false, permissions: [], viewport: { width: 1280, height: 800 }, serviceWorkers: 'block' });
    await this.context.route('**/*', async route => {
      const u = route.request().url();
      if (urlAllowed(u, ALLOW_LOOPBACK) && !(await this.resolvesPrivately(u))) return route.continue();
      this.blocked = [...this.blocked.slice(-49), u.slice(0, 120)]; console.error('blocked', u.slice(0, 120)); return route.abort('blockedbyclient');
    });
    this.context.on('page', p => { if (this.context.pages().length > MAX_PAGES) { p.close().catch(() => {}); return; } this.page = this.prepare(p); });
    this.page = this.prepare(await this.context.newPage());
    this.liveTimer = setInterval(() => this.liveSync().catch(() => {}), LIVE.pollMs); this.liveTimer.unref?.();
  }
  /** A name that looks public but resolves to an internal address (wildcard DNS such as 10.0.0.1.nip.io, or a misconfigured record). The host firewall is the real
   *  barrier; this catches the static cases early. A name that does not resolve is let through: the browser fails on it by itself. Answers are cached for 30 s. */
  resolvesPrivately(raw) {
    let host; try { host = new URL(raw).hostname.toLowerCase().replace(/^\[|\]$/g, ''); } catch { return Promise.resolve(false); }
    if (host === 'localhost' || /^[\d.]+$/.test(host) || host.includes(':')) return Promise.resolve(false);               // literal addresses were already judged by urlAllowed
    const seen = this.dnsSeen.get(host);
    if (seen && seen.until > Date.now()) return seen.answer;
    const answer = Promise.race([this.lookup(host, { all: true }), new Promise((_, no) => setTimeout(() => no(new Error('slow')), 3000))])
      .then(list => list.some(a => privateIp(a.address) && !(ALLOW_LOOPBACK && (a.address === '127.0.0.1' || a.address === '::1'))), () => false);
    this.dnsSeen.set(host, { until: Date.now() + 30_000, answer });
    return answer;
  }
  // Every page gets the same timeouts and a close handler: when the page the agent is on closes (a login, OAuth or payment popup that finishes and
  // closes itself, or a site closing a tab), the agent carries on in the page that is still open instead of being left holding a dead one.
  prepare(p) {
    p.setDefaultTimeout(8000); p.setDefaultNavigationTimeout(20000);
    p.on('close', () => { if (this.page === p) { const open = this.context.pages().filter(x => !x.isClosed()); if (open.length) this.page = open[open.length - 1]; } });
    return p;
  }
  async ensurePage() {
    if (!this.page.isClosed()) return;
    const open = this.context.pages().filter(x => !x.isClosed());
    this.page = open.length ? open[open.length - 1] : this.prepare(await this.context.newPage());    // the last tab closed: start again from a blank one
  }
  async stop() { clearInterval(this.liveTimer); await this.liveOff(); try { await this.browser?.close(); } catch { /* already gone */ } }

  watched() { try { return Date.now() - statSync(join(OUT, 'watching')).mtimeMs < LIVE.watchSeconds * 1000; } catch { return false; } }
  async liveSync() {
    if (this.liveBusy) return;                       // the timer fires every 250 ms; starting a capture can take longer, and a second start would leave a second one running
    this.liveBusy = true;
    try {
      const want = this.watched();
      if (want && (!this.live || this.live.page !== this.page)) await this.liveOn();
      else if (!want && this.live) await this.liveOff();
    } finally { this.liveBusy = false; }
  }
  async liveOn() {
    await this.liveOff();
    const page = this.page; const cdp = await this.context.newCDPSession(page); const tmp = join(OUT, 'live.tmp'); const dest = join(OUT, 'live.jpg');
    const write = data => { this.lastFrame = Date.now(); try { writeFileSync(tmp, Buffer.from(data, 'base64')); renameSync(tmp, dest); } catch { /* disk full or folder gone: skip this frame */ } };
    cdp.on('Page.screencastFrame', ev => {
      cdp.send('Page.screencastFrameAck', { sessionId: ev.sessionId }).catch(() => {});
      const wait = 1000 / LIVE.fps - (Date.now() - this.lastFrame);
      clearTimeout(this.pendingFrame);
      // Newest frame wins. One that arrives too soon is held and written when the rate allows, never dropped: the last frame of a change
      // (a spinner stopping, a checkbox ticking) must always reach the screen.
      if (wait <= 0) write(ev.data); else this.pendingFrame = setTimeout(() => write(ev.data), wait);
    });
    await cdp.send('Page.startScreencast', { format: 'jpeg', quality: LIVE.quality, maxWidth: LIVE.width, maxHeight: LIVE.height, everyNthFrame: 1 });
    this.live = { cdp, page };
  }
  async liveOff() {
    const l = this.live; this.live = null; clearTimeout(this.pendingFrame); if (!l) return;
    try { await l.cdp.send('Page.stopScreencast'); await l.cdp.detach(); } catch { /* page already closed */ }
  }
  info() { return { url: this.page.url(), title: '' }; }
  async fp() { try { return createHash('sha1').update(await this.page.evaluate(fingerprint, SELECTOR)).digest('hex').slice(0, 12); } catch { return null; } }   // null = could not tell (page changing under us)
  async settle() { try { await this.page.waitForLoadState('domcontentloaded', { timeout: 5000 }); await this.page.waitForLoadState('networkidle', { timeout: 2500 }); } catch { /* slow pages are fine */ } }

  async handle(msg) {
    await this.ensurePage();
    switch (msg.cmd) {
      case 'open': {
        if (!urlAllowed(msg.url, ALLOW_LOOPBACK)) return { ok: false, error: 'url_blocked' };
        try { await this.page.goto(msg.url, { waitUntil: 'domcontentloaded' }); } catch (e) { return { ok: false, error: 'navigation_failed', detail: String(e.message || e).split('\n')[0].slice(0, 160) }; }
        await this.settle(); return { ok: true, url: this.page.url(), title: (await this.page.title()).slice(0, 120) };
      }
      case 'snapshot': {
        await this.settle(); const d = await this.page.evaluate(describe, { sel: SELECTOR, max: MAX_ELEMENTS });
        const lines = d.elements.map(e => `[${e.ref}] <${e.tag}${e.type ? ' type=' + e.type : ''}> "${e.label}"`).join('\n');
        return { ok: true, url: this.page.url(), title: d.title, snapshot: lines, text: d.text, pages: this.context.pages().length, elements: d.elements, page_fp: await this.fp(), scroll: d.scroll, height: d.height, window: d.window };
      }
      case 'act': {
        const { ref, action, value, expect } = msg;
        const done = async extra => ({ ok: true, url: this.page.url(), page_fp: await this.fp(), ...extra });
        if (action === 'back') { await this.page.goBack({ timeout: 8000 }).catch(() => {}); await this.settle(); return done(); }
        if (action === 'press') { if (!KEYS.has(value)) return { ok: false, error: 'key_not_allowed' }; await this.page.keyboard.press(value); await this.settle(); return done(); }
        if (action === 'scroll') {
          if (value !== undefined && value !== null && !['down', 'up'].includes(value)) return { ok: false, error: 'bad_value' };
          await this.page.mouse.wheel(0, value === 'up' ? -700 : 700); await this.page.waitForTimeout(150).catch(() => {}); return done();
        }
        if (action === 'wait') { await this.page.waitForTimeout(1000).catch(() => {}); await this.settle(); return done(); }
        if (action === 'clickat' || action === 'typeat') {      // a point chosen from a picture: the host has already named what is there (probe) and run its rules on it
          const { x, y } = msg;
          if (!Number.isFinite(x) || !Number.isFinite(y) || x < 0 || y < 0 || x > 1280 || y > 800) return { ok: false, error: 'bad_coordinates' };
          if (action === 'typeat' && (typeof value !== 'string' || !value || value.length > MAX_VALUE)) return { ok: false, error: 'bad_value' };
          const page = this.page; const before = page.url(); const pagesBefore = this.context.pages().length;
          try {
            await page.mouse.move(x, y, { steps: 3 }); await page.mouse.click(x, y, { delay: 40 });
            if (action === 'typeat') {
              await page.waitForTimeout(200);
              if (!(await page.evaluate(focusActive))) return { ok: false, error: 'not_a_field' };
              await page.keyboard.insertText(value);
            }
          } catch (e) { if (!page.isClosed()) return { ok: false, error: 'action_failed' }; }
          await this.ensurePage();
          await this.page.waitForTimeout(400).catch(() => {});
          await this.settle();
          return done({ navigated: this.page.url() !== before, new_tab: this.context.pages().length > pagesBefore });
        }
        if (!['click', 'type', 'select'].includes(action) || !Number.isInteger(ref)) return { ok: false, error: 'bad_action' };
        const el = await this.page.$(`[data-lumina-ref="${ref}"]`);
        if (!el) return { ok: false, error: 'stale' };
        // Fresh-target check: the element must still carry the label it had when the host chose it. A re-render drops the marks, so
        // a moved, renamed or removed element is "stale" and nothing is clicked.
        if (expect && (await el.getAttribute('data-lumina-label')) !== expect.label) return { ok: false, error: 'stale' };
        if ((action === 'type' || action === 'select') && (typeof value !== 'string' || value.length > MAX_VALUE)) return { ok: false, error: 'bad_value' };
        // Ready check: bring it into view, then act only if it is enabled and nothing (a banner, a modal) sits on top of it. Nothing is clicked otherwise.
        await el.scrollIntoViewIfNeeded({ timeout: 3000 }).catch(() => {});
        const state = await el.evaluate(ready, action).catch(() => 'stale');
        if (state !== 'ok') return { ok: false, error: state };
        const page = this.page; const before = page.url(); const pagesBefore = this.context.pages().length;
        try {
          if (action === 'click') await el.click({ timeout: 6000 });
          else if (action === 'type') await el.fill(value, { timeout: 6000 });
          else {
            // Resolve the option in the page first (exact label, exact value, case-insensitive label, then label prefix) so a miss fails at once, not after the 8 s default wait.
            const idx = await el.evaluate((s, v) => { const o = [...s.options]; const lc = x => String(x).trim().toLowerCase(); let i = o.findIndex(x => x.label === v);
              if (i < 0) i = o.findIndex(x => x.value === v); if (i < 0) i = o.findIndex(x => lc(x.label) === lc(v)); if (i < 0) i = o.findIndex(x => lc(x.label).startsWith(lc(v))); return i; }, value);
            if (idx < 0) return { ok: false, error: 'no_option' };
            await el.selectOption({ index: idx }, { timeout: 4000 });
          }
        } catch (e) { if (!page.isClosed()) return { ok: false, error: 'action_failed' }; }      // the click closed its own tab (a popup finishing): that is what it was for
        await this.ensurePage();
        await this.page.waitForTimeout(400).catch(() => {});          // a link opening a new tab reports it asynchronously (and a click may close this one)
        await this.settle();
        return done({ navigated: this.page.url() !== before, new_tab: this.context.pages().length > pagesBefore });
      }
      case 'xy': {   // takeover: coordinates come from the user's own click on the screenshot; the host has already range-checked them
        const { x, y, action, text } = msg;
        if (action === 'click' && (!Number.isFinite(x) || !Number.isFinite(y) || x < 0 || y < 0 || x > 1280 || y > 800)) return { ok: false, error: 'bad_coordinates' };
        try {
          if (action === 'click') { await this.page.mouse.move(x, y, { steps: 4 }); await this.page.mouse.click(x, y, { delay: 40 }); }
          else if (action === 'type') { if (typeof text !== 'string' || text.length > MAX_VALUE) return { ok: false, error: 'bad_value' }; await this.page.keyboard.type(text, { delay: 5 }); }
          else if (action === 'key') { if (!KEYS.has(text) && !['Backspace', 'ArrowDown', 'ArrowUp'].includes(text)) return { ok: false, error: 'key_not_allowed' }; await this.page.keyboard.press(text); }
          else if (action === 'scroll') await this.page.mouse.wheel(0, Number(text) > 0 ? 500 : -500);
          else return { ok: false, error: 'bad_action' };
        } catch (e) { return { ok: false, error: 'action_failed' }; }
        return { ok: true, url: this.page.url() };     // no waiting for the page to settle: the next input must not queue behind a slow load
      }
      case 'view': {   // the picture JEV is shown when the element list cannot be used: one JPEG of the window as it is (1280x800, inside JEV's size limits), optionally kept for the run's record
        const bytes = await this.page.screenshot({ type: 'jpeg', quality: 75, scale: 'css', fullPage: false });
        const size = this.page.viewportSize() || { width: 1280, height: 800 };
        let file; if (msg.save) { file = `shot-${String(++this.shots).padStart(3, '0')}.jpg`; writeFileSync(join(OUT, file), bytes); }     // same names and folder as every other picture, so the host serves it the same way
        return { ok: true, data: bytes.toString('base64'), width: size.width, height: size.height, view: { w: size.width, h: size.height }, file };
      }
      case 'probe': {
        const { x, y } = msg;
        if (!Number.isFinite(x) || !Number.isFinite(y) || x < 0 || y < 0 || x > 1280 || y > 800) return { ok: false, error: 'bad_coordinates' };
        return { ok: true, hit: await this.page.evaluate(hitAt, { x, y }) };
      }
      case 'screenshot': {
        const file = `shot-${String(++this.shots).padStart(3, '0')}.jpg`;
        await this.page.screenshot({ path: join(OUT, file), type: 'jpeg', quality: 60, fullPage: false });
        return { ok: true, file };
      }
      default: return { ok: false, error: 'unknown_command' };
    }
  }
}

async function main() {
  const runner = new Runner(); await runner.start();
  const rl = createInterface({ input: process.stdin });
  let queue = Promise.resolve();
  rl.on('line', line => { queue = queue.then(async () => {
    let msg; try { msg = JSON.parse(line); } catch { return console.log(JSON.stringify({ ok: false, error: 'bad_json' })); }
    if (msg.cmd === 'close') { await runner.stop(); console.log(JSON.stringify({ id: msg.id, ok: true })); process.exit(0); }
    let res; try { res = await runner.handle(msg); } catch (e) { res = { ok: false, error: 'runner_error' }; }
    console.log(JSON.stringify({ id: msg.id, ...res }));
  }); });
  rl.on('close', async () => { await queue; await runner.stop(); process.exit(0); });   // finish queued work before shutting the browser
}
if (import.meta.url === `file://${process.argv[1]}`) void main();
