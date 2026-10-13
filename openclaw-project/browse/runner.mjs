// Lumina browse runner: the "hands". Runs INSIDE the sandboxed browser stage; deterministic, no model, no network of its own.
// Protocol: one JSON object per line on stdin -> one JSON object per line on stdout. The host decides everything; this file only
// opens pages, describes them, and performs one already-validated action at a time.
import { chromium } from 'playwright-core';
import { createInterface } from 'node:readline';
import { mkdirSync } from 'node:fs';
import { join } from 'node:path';

const CHROME = process.env.BROWSE_CHROME || '/usr/bin/chromium';
const OUT = process.env.BROWSE_OUT || '/tmp/out';
const ALLOW_LOOPBACK = process.env.BROWSE_ALLOW_LOOPBACK === '1';   // tests only; never set in the stage
const MAX_ELEMENTS = 80, MAX_TEXT = 6000, MAX_PAGES = 3, MAX_VALUE = 500;
const KEYS = new Set(['Enter', 'Tab', 'Escape']);

export function urlAllowed(raw, allowLoopback = false) {
  let u; try { u = new URL(raw); } catch { return false; }
  if (!['http:', 'https:'].includes(u.protocol)) return false;
  const h = u.hostname.toLowerCase().replace(/^\[|\]$/g, '');
  if (u.username || u.password) return false;
  const loop = h === 'localhost' || h === '127.0.0.1' || h === '::1';
  if (loop) return allowLoopback;
  if (h.endsWith('.local') || h.endsWith('.internal') || h.endsWith('.localhost')) return false;
  const m = h.match(/^(\d+)\.(\d+)\.(\d+)\.(\d+)$/);
  if (m) { const [a, b] = [+m[1], +m[2]]; if (a === 10 || a === 127 || a === 0 || (a === 169 && b === 254) || (a === 172 && b >= 16 && b <= 31) || (a === 192 && b === 168) || (a === 100 && b >= 64 && b <= 127)) return false; }
  if (h.includes(':')) { if (/^(fc|fd|fe80|::1|::)/.test(h)) return false; }
  return true;
}

// Runs in the page. Describes interactive elements in the format the host parses: [ref] <tag type=x> "label"
function describe(max) {
  const sel = 'a[href], button, input:not([type=hidden]), select, textarea, [role=button], [role=link], [role=checkbox], [role=radio], [role=tab], [onclick]';
  for (const el of document.querySelectorAll('[data-lumina-ref]')) { el.removeAttribute('data-lumina-ref'); el.removeAttribute('data-lumina-label'); }
  const clean = s => (s || '').replace(/\s+/g, ' ').replace(/"/g, "'").trim().slice(0, 100);
  const out = []; let n = 0;
  for (const el of document.querySelectorAll(sel)) {
    if (n >= max) break;
    const r = el.getBoundingClientRect(); const st = getComputedStyle(el);
    if (r.width < 2 || r.height < 2 || st.visibility === 'hidden' || st.display === 'none' || el.disabled || el.closest('[aria-hidden=true]')) continue;
    const tag = el.tagName.toLowerCase(); const role = el.getAttribute('role');
    let kind = tag === 'a' || role === 'link' ? 'a' : tag === 'input' || tag === 'select' || tag === 'textarea' ? tag : 'button';
    const type = kind === 'input' ? (el.getAttribute('type') || 'text').toLowerCase().replace(/[^a-z]/g, '') : kind === 'button' && tag === 'button' ? '' : '';
    let label = clean(el.getAttribute('aria-label') || (kind === 'input' || kind === 'select' || kind === 'textarea' ? ((el.labels && el.labels[0] && el.labels[0].innerText) || el.placeholder || el.value || el.name || el.getAttribute('title')) : (el.innerText || el.value || el.getAttribute('title'))));
    if (!label) continue;
    n += 1; el.setAttribute('data-lumina-ref', String(n)); el.setAttribute('data-lumina-label', label);
    out.push({ ref: n, tag: kind, type, label });
  }
  return { elements: out, title: document.title.slice(0, 120), text: (document.body && document.body.innerText || '').replace(/\s+\n/g, '\n').slice(0, 6000) };
}

export class Runner {
  constructor() { this.browser = null; this.context = null; this.page = null; this.shots = 0; }
  async start() {
    mkdirSync(OUT, { recursive: true });
    this.browser = await chromium.launch({ executablePath: CHROME, headless: true, args: ['--no-sandbox', '--disable-gpu', '--disable-dev-shm-usage', '--disable-crash-reporter', '--no-first-run'] });
    this.context = await this.browser.newContext({ acceptDownloads: false, permissions: [], viewport: { width: 1280, height: 800 }, serviceWorkers: 'block' });
    await this.context.route('**/*', route => { const u = route.request().url(); if (urlAllowed(u, ALLOW_LOOPBACK)) return route.continue(); console.error('blocked', u.slice(0, 120)); return route.abort('blockedbyclient'); });
    this.context.on('page', p => { if (this.context.pages().length > MAX_PAGES) { p.close().catch(() => {}); return; } this.page = p; });
    this.page = await this.context.newPage(); this.page.setDefaultTimeout(8000); this.page.setDefaultNavigationTimeout(20000);
  }
  async stop() { try { await this.browser?.close(); } catch { /* already gone */ } }
  info() { return { url: this.page.url(), title: '' }; }
  async settle() { try { await this.page.waitForLoadState('domcontentloaded', { timeout: 5000 }); await this.page.waitForLoadState('networkidle', { timeout: 2500 }); } catch { /* slow pages are fine */ } }

  async handle(msg) {
    switch (msg.cmd) {
      case 'open': {
        if (!urlAllowed(msg.url, ALLOW_LOOPBACK)) return { ok: false, error: 'url_blocked' };
        try { await this.page.goto(msg.url, { waitUntil: 'domcontentloaded' }); } catch (e) { return { ok: false, error: 'navigation_failed', detail: String(e.message || e).split('\n')[0].slice(0, 160) }; }
        await this.settle(); return { ok: true, url: this.page.url(), title: (await this.page.title()).slice(0, 120) };
      }
      case 'snapshot': {
        await this.settle(); const d = await this.page.evaluate(describe, MAX_ELEMENTS);
        const lines = d.elements.map(e => `[${e.ref}] <${e.tag}${e.type ? ' type=' + e.type : ''}> "${e.label}"`).join('\n');
        return { ok: true, url: this.page.url(), title: d.title, snapshot: lines, text: d.text, pages: this.context.pages().length };
      }
      case 'act': {
        const { ref, action, value, expect } = msg;
        if (action === 'back') { await this.page.goBack({ timeout: 8000 }).catch(() => {}); await this.settle(); return { ok: true, url: this.page.url() }; }
        if (action === 'press') { if (!KEYS.has(value)) return { ok: false, error: 'key_not_allowed' }; await this.page.keyboard.press(value); await this.settle(); return { ok: true, url: this.page.url() }; }
        if (action === 'scroll') { await this.page.mouse.wheel(0, 700); return { ok: true, url: this.page.url() }; }
        if (!['click', 'type', 'select'].includes(action) || !Number.isInteger(ref)) return { ok: false, error: 'bad_action' };
        const el = await this.page.$(`[data-lumina-ref="${ref}"]`);
        if (!el) return { ok: false, error: 'stale' };
        // Fresh-target check: the element must still carry the label it had when the host chose it. A re-render drops the marks, so
        // a moved, renamed or removed element is "stale" and nothing is clicked.
        if (expect && (await el.getAttribute('data-lumina-label')) !== expect.label) return { ok: false, error: 'stale' };
        const before = this.page.url(); const pagesBefore = this.context.pages().length;
        try {
          if (action === 'click') await el.click({ timeout: 6000 });
          else if (action === 'type') { if (typeof value !== 'string' || value.length > MAX_VALUE) return { ok: false, error: 'bad_value' }; await el.fill(value, { timeout: 6000 }); }
          else { if (typeof value !== 'string') return { ok: false, error: 'bad_value' }; await el.selectOption({ label: value }).catch(() => el.selectOption(value)); }
        } catch (e) { return { ok: false, error: 'action_failed' }; }
        await this.page.waitForTimeout(400);          // a link opening a new tab reports it asynchronously
        await this.settle();
        return { ok: true, url: this.page.url(), navigated: this.page.url() !== before, new_tab: this.context.pages().length > pagesBefore };
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
if (import.meta.url === `file://${process.argv[1]}`) main();
