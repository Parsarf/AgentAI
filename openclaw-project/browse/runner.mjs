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
// Opening a page: how long the site has to answer at all, and how long the page then has to load before the task goes on with what is drawn. (The host waits a little
// longer than both together: platform/agentai_platform/browse/session.py DEADLINES.) The variables are for tests.
const OPEN_ANSWER_MS = Number(process.env.BROWSE_OPEN_ANSWER_MS) || 30000;
const OPEN_LOAD_MS = Number(process.env.BROWSE_OPEN_LOAD_MS) || 25000;
const MAX_ELEMENTS = 80, MAX_TEXT = 6000, MAX_PAGES = 3, MAX_VALUE = 500;
const KEYS = new Set(['Enter', 'Tab', 'Escape']);
const TAKEOVER_KEYS = new Set(['Backspace', 'Delete', 'ArrowDown', 'ArrowUp', 'ArrowLeft', 'ArrowRight', 'Home', 'End', 'PageDown', 'PageUp']);   // what the customer's own keyboard may send; no shortcuts
const MAX_URL = 2048;
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

const SELECTOR = 'a[href], button, input:not([type=hidden]), select, textarea, [role=button], [role=link], [role=checkbox], [role=radio], [role=tab], [role=combobox], [role=option], [role=menuitem], [role=menuitemcheckbox], [role=menuitemradio], [role=switch], [onclick]';

// Runs in the page. Describes interactive elements in the format the host parses: [ref] <tag type=x> "label", plus their state.
// A field that holds a secret (password, card, one-time code) is always listed, never with its value, so the host can see that the page needs the user.
// Controls inside open shadow roots (web components: a search box, a cookie banner, a cart drawer) are listed like any other.
function describe(args) {
  const { sel, max } = args;
  const roots = [document];                             // the document and every open shadow root under it, in page order
  for (let i = 0; i < roots.length && roots.length < 300; i++) for (const el of roots[i].querySelectorAll('*')) if (el.shadowRoot && roots.length < 300) roots.push(el.shadowRoot);
  for (const root of roots) for (const el of root.querySelectorAll('[data-lumina-ref]')) { el.removeAttribute('data-lumina-ref'); el.removeAttribute('data-lumina-label'); }
  const clean = s => (s || '').replace(/\s+/g, ' ').replace(/"/g, "'").trim().slice(0, 100);
  const vw = window.innerWidth, vh = window.innerHeight;
  const up = n => n.parentNode || n.host || null;       // one step up, through a shadow root to its host
  const within = (el, hit) => { for (let n = hit; n; n = up(n)) if (n === el) return true; return false; };
  const hidden = el => { for (let n = el; n && n.closest; n = n.getRootNode().host) if (n.closest('[aria-hidden=true]')) return true; return false; };
  const deepHit = (x, y) => { let el = document.elementFromPoint(x, y); while (el && el.shadowRoot) { const inner = el.shadowRoot.elementFromPoint(x, y); if (!inner || inner === el) break; el = inner; } return el; };
  const named = el => { const ids = (el.getAttribute('aria-labelledby') || '').split(/\s+/).filter(Boolean); const root = el.getRootNode();
    return ids.map(id => { const t = root.getElementById ? root.getElementById(id) : null; return t ? t.innerText || t.textContent : ''; }).join(' '); };
  const all = [];
  for (const root of roots) for (const el of root.querySelectorAll(sel)) all.push(el);
  // Page order across shadow roots: two controls in different trees are compared where their trees meet (a host comes before what is inside it).
  const chain = el => { const c = [el]; for (let root = el.getRootNode(); root && root.host; root = root.host.getRootNode()) c.unshift(root.host); return c; };
  if (roots.length > 1) {
    const chains = new Map(all.map(el => [el, chain(el)]));
    all.sort((a, b) => { const ca = chains.get(a), cb = chains.get(b);
      for (let i = 0; i < Math.max(ca.length, cb.length); i++) { if (ca[i] === cb[i]) continue; if (!ca[i]) return -1; if (!cb[i]) return 1; return (ca[i].compareDocumentPosition(cb[i]) & 4) ? -1 : 1; }
      return 0; });
  }
  const found = [];
  for (const el of all) {
    if (found.length >= 600) break;
    const tag = el.tagName.toLowerCase(); const role = el.getAttribute('role');
    let kind = tag === 'a' || role === 'link' ? 'a' : tag === 'input' || tag === 'select' || tag === 'textarea' ? tag : 'button';
    const type = kind === 'input' ? (el.getAttribute('type') || 'text').toLowerCase().replace(/[^a-z]/g, '') : '';
    let r = el.getBoundingClientRect(); let st = getComputedStyle(el);
    // A size or colour picker is usually a radio button the page hides and a label drawn as the button. The hidden input was skipped and the label is not a control, so the
    // choices were in the page's words and nowhere in the list: the task could read "Small Medium Large" and not choose one. Such a box is listed where its label is, and a step on it goes to the label.
    let face = el;
    if ((type === 'checkbox' || type === 'radio') && !el.disabled && el.labels && el.labels.length && (r.width < 4 || r.height < 4 || st.visibility === 'hidden' || st.display === 'none' || st.opacity === '0')) {
      const lab = [...el.labels].find(l => { const q = l.getBoundingClientRect(); const ls = getComputedStyle(l); return q.width >= 4 && q.height >= 4 && ls.visibility !== 'hidden' && ls.display !== 'none'; });
      if (lab) { face = lab; r = lab.getBoundingClientRect(); st = getComputedStyle(lab); }
    }
    if (r.width < 2 || r.height < 2 || st.visibility === 'hidden' || st.display === 'none' || el.disabled || hidden(el)) continue;
    const secret = type === 'password' || /^(cc-|one-time-code|current-password|new-password)/.test((el.getAttribute('autocomplete') || '').toLowerCase());
    const field = kind === 'input' || kind === 'select' || kind === 'textarea';
    const img = el.querySelector && el.querySelector('img[alt], svg title');
    const box = kind === 'input' && (type === 'checkbox' || type === 'radio');
    const beside = box && el.nextSibling && el.nextSibling.nodeType === 3 ? el.nextSibling.nodeValue : '';      // a box with its words written straight after it and no label element
    let label = clean(el.getAttribute('aria-label') || named(el) || (field ? ((el.labels && el.labels[0] && (el.labels[0].innerText || el.labels[0].getAttribute('title') || el.labels[0].getAttribute('aria-label'))) || el.placeholder || beside || (secret || kind === 'select' || (box && el.value === 'on') ? '' : el.value) || el.getAttribute('title'))
      : (el.innerText || el.value || el.getAttribute('title') || (img && (img.getAttribute('alt') || img.textContent)))));
    const full = clean(el.getAttribute('title'));       // a name the page cut short ("The Road to Little ...") is given whole when the page says what it is
    if (!field && full && /(\.\.\.|…)$/.test(label) && full.toLowerCase().startsWith(label.replace(/(\.\.\.|…)$/, '').trim().toLowerCase().slice(0, 12))) label = full;
    if (!label && secret) label = type === 'password' ? 'Password' : 'Secret field';
    // A control the page gave no name is still a control: an unnamed dropdown is called by its first option, an unnamed field or button by what the page calls it in its code.
    if (!label && kind === 'select') label = clean('Dropdown: ' + ((el.options[0] && el.options[0].label) || el.name || el.id || 'choose'));
    if (!label && (field || tag === 'button' || tag === 'a')) { const hint = clean((el.name || el.id || '').replace(/[-_]+/g, ' ')); if (hint && hint.length <= 40) label = field ? hint : hint + ' (unnamed button)'; }
    if (!label && kind === 'input' && ['checkbox', 'radio'].includes(type)) label = type === 'checkbox' ? 'Checkbox' : 'Radio button';
    if (!label) continue;
    let value = '';
    if (!secret) {
      if (tag === 'select') value = el.selectedOptions && el.selectedOptions[0] ? el.selectedOptions[0].label : '';
      else if ((tag === 'input' && !['checkbox', 'radio', 'button', 'submit', 'reset', 'image', 'file'].includes(type)) || tag === 'textarea') value = el.value;
    }
    const ariaChecked = el.getAttribute('aria-checked'); const ariaExpanded = el.getAttribute('aria-expanded');
    const picked = el.getAttribute('aria-selected') === 'true' || el.getAttribute('aria-pressed') === 'true' || ['page', 'true', 'step', 'location'].includes(el.getAttribute('aria-current'));
    const checked = type === 'checkbox' || type === 'radio' ? !!el.checked : ariaChecked === 'true' ? true : ariaChecked === 'false' ? false : picked ? true : null;
    const cx = r.left + r.width / 2, cy = r.top + r.height / 2;
    const options = tag === 'select' ? [...el.options].slice(0, 15).map(o => (o.label || '').replace(/\s+/g, ' ').trim().slice(0, 80)) : [];
    // Is something else on top of the middle of the part of it that shows? null when none of it is in the window. The host uses the share of covered controls to tell that a panel or popup is in the way.
    const vl = Math.max(r.left, 0), vr = Math.min(r.right, vw), vt = Math.max(r.top, 0), vb = Math.min(r.bottom, vh);
    let covered = null;
    if (vr - vl > 1 && vb - vt > 1) {
      const hit = deepHit((vl + vr) / 2, (vt + vb) / 2);
      covered = !(hit && (within(face, hit) || within(el, hit) || (el.labels && [...el.labels].some(l => within(l, hit)))));
    }
    const seen = vr - vl > 1 && vb - vt > 1;
    found.push({ el: face, label, secret, item: { ref: 0, tag: kind, type, label, role: role || '', value: clean(value), checked, expanded: ariaExpanded === 'true' ? true : ariaExpanded === 'false' ? false : null,
      in_view: cx >= 0 && cy >= 0 && cx <= vw && cy <= vh, covered, options, x: Math.round(seen ? (vl + vr) / 2 : cx), y: Math.round(seen ? (vt + vb) / 2 : cy) } });
  }
  // A secret field is always listed (the host must see that the page needs the user); then what a person can see and reach, so a long header or a closed menu cannot crowd it out. Numbers still follow page order.
  const reach = f => !f.secret && f.item.in_view && f.item.covered === false;
  const shown = f => !reach(f) && f.item.in_view;      // in the window but under something: still listed next, because how much is covered tells the host a popup is in the way
  const keep = new Set([...found.filter(f => f.secret), ...found.filter(reach), ...found.filter(f => !f.secret && shown(f)), ...found.filter(f => !f.secret && !reach(f) && !shown(f))].slice(0, max));
  const out = []; let n = 0;
  for (const f of found) {
    if (!keep.has(f)) continue;
    n += 1; f.item.ref = n; f.el.setAttribute('data-lumina-ref', String(n)); f.el.setAttribute('data-lumina-label', f.label); out.push(f.item);
  }
  // What has the keyboard right now: the host tells the decider whether typing would land in a text field, and what that field holds (never a secret).
  let focus = null;
  let act = document.activeElement;
  while (act && act.shadowRoot && act.shadowRoot.activeElement) act = act.shadowRoot.activeElement;
  if (act && act !== document.body && act !== document.documentElement) {
    const atag = act.tagName.toLowerCase(), atype = atag === 'input' ? (act.getAttribute('type') || 'text').toLowerCase().replace(/[^a-z]/g, '') : '';
    const asecret = atype === 'password' || /^(cc-|one-time-code|current-password|new-password)/.test((act.getAttribute('autocomplete') || '').toLowerCase());
    const editable = (atag === 'textarea' || (atag === 'input' && !['checkbox', 'radio', 'submit', 'button', 'reset', 'image', 'file', 'range', 'color', 'hidden'].includes(atype)) || !!act.isContentEditable) && !act.readOnly && !act.disabled;
    focus = { tag: atag, type: atype, editable, secret: asecret, ref: Number(act.getAttribute('data-lumina-ref')) || null,
      label: asecret ? '' : clean(act.getAttribute('data-lumina-label') || act.getAttribute('aria-label') || act.placeholder || act.name), value: asecret || !editable ? '' : clean(act.value !== undefined ? act.value : act.innerText) };
  }
  // The page's words, starting with what is in the window right now and going on down the page. It used to be the first 6,000 characters of the whole document whatever the scroll
  // position, so nothing a decider scrolled to was ever read. What is above the window comes last, and only if there is room.
  const SKIP = new Set(['SCRIPT', 'STYLE', 'NOSCRIPT', 'TEMPLATE', 'SVG', 'IFRAME', 'OPTION', 'TITLE', 'HEAD']);
  const LINE = 'tr, li, p, h1, h2, h3, h4, h5, h6, dt, dd, figcaption, blockquote, pre, label, button, a, summary, caption';
  const bands = [[], [], []];                           // in the window, below it, above it
  let nodes = 0;
  const walk = root => {
    const tw = document.createTreeWalker(root, 5 /* elements and text */, { acceptNode: n => n.nodeType === 1 && (SKIP.has(n.tagName.toUpperCase()) || n.getAttribute('aria-hidden') === 'true') ? 2 /* reject the subtree */ : 1 });
    let last = null, box = null, line = null;
    for (let n = tw.nextNode(); n && nodes < 8000; n = tw.nextNode()) {
      if (n.nodeType === 1) { if (n.shadowRoot) walk(n.shadowRoot); continue; }
      let words = n.nodeValue.replace(/\s+/g, ' ');
      if (!words.trim()) continue;
      nodes += 1;
      const parent = n.parentElement; if (!parent) continue;
      if (/(\.\.\.|…)\s*$/.test(words)) {          // a name the page cut short: read whole when the page itself says what it is (a title on it or on its link)
        const named = parent.closest('[title]'); const whole = named ? (named.getAttribute('title') || '').replace(/\s+/g, ' ').trim() : '';
        const stem = words.replace(/(\.\.\.|…)\s*$/, '').trim().toLowerCase();
        if (whole && stem.length >= 4 && whole.toLowerCase().startsWith(stem.slice(0, 12))) words = whole;
      }
      if (parent !== last) {
        last = parent; box = parent.getBoundingClientRect();
        if (box.width < 1 || box.height < 1 || (parent.checkVisibility && !parent.checkVisibility({ checkVisibilityCSS: true }))) box = null;
        line = parent.closest(LINE) || parent;
      }
      if (!box) continue;
      const band = bands[box.bottom < 0 ? 2 : box.top > vh ? 1 : 0];
      const tail = band[band.length - 1];
      if (tail && tail.line === line) tail.text += words; else band.push({ line, text: words });
    }
  };
  if (document.body) walk(document.body);
  const say = band => band.map(b => b.text.trim()).filter(Boolean).join('\n');
  const windowText = say(bands[0]), below = say(bands[1]), above = say(bands[2]);
  let text = windowText.slice(0, 5000);
  if (below && text.length < 11500) text += '\n[below the window]\n' + below.slice(0, 11500 - text.length);
  if (above && text.length < 11000) text += '\n[above the window]\n' + above.slice(0, 11500 - text.length);
  // The same words in page order, for a reader that takes the whole page at once (the assistant, when it writes the answer): `full_at` is where the window starts in it.
  const full = [above, windowText, below].filter(Boolean).join('\n').slice(0, 40000);
  const page = document.documentElement;
  return { elements: out, title: document.title.slice(0, 120), text: text.slice(0, 12000), full, full_at: above ? Math.min(above.length + 1, full.length) : 0,
    scroll: Math.round(window.scrollY), height: Math.round(Math.max(page.scrollHeight, document.body ? document.body.scrollHeight : 0)), window: vh, focus };
}

// Runs in the page. What is at a point on the screen: the control under it (looking through open shadow roots) with the name a person would give it.
// Used when a picture, not the element list, chose the target, so the host can run its safety rules on the label before anything is clicked.
function hitAt({ x, y }) {
  let el = document.elementFromPoint(x, y);
  while (el && el.shadowRoot) { const inner = el.shadowRoot.elementFromPoint(x, y); if (!inner || inner === el) break; el = inner; }
  if (!el) return null;
  const clean = s => (s || '').replace(/\s+/g, ' ').replace(/"/g, "'").trim().slice(0, 100);
  const control = el.closest('a, button, input, select, textarea, summary, label, [role=button], [role=link], [role=checkbox], [role=radio], [role=tab], [role=combobox], [role=option], [role=menuitem], [role=menuitemcheckbox], [role=menuitemradio], [role=switch]');
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
  const roots = [document];
  for (let i = 0; i < roots.length && roots.length < 300; i++) for (const el of roots[i].querySelectorAll('*')) if (el.shadowRoot && roots.length < 300) roots.push(el.shadowRoot);
  const hidden = el => { for (let n = el; n && n.closest; n = n.getRootNode().host) if (n.closest('[aria-hidden=true]')) return true; return false; };
  const parts = [location.href, String(Math.round(window.scrollY / 50)), String(((document.body && document.body.innerText) || '').length), String(roots.length)];
  for (const root of roots) for (const el of root.querySelectorAll(sel)) {
    const r = el.getBoundingClientRect(); const st = getComputedStyle(el);
    const type = (el.getAttribute('type') || '').toLowerCase();
    const box = (type === 'checkbox' || type === 'radio') && el.labels && el.labels.length > 0;       // a box the page hides behind its label still shows its tick there
    if (!box && (r.width < 2 || r.height < 2 || st.visibility === 'hidden' || st.display === 'none' || hidden(el))) continue;
    const secret = type === 'password' || /^(cc-|one-time-code|current-password|new-password)/.test((el.getAttribute('autocomplete') || '').toLowerCase());
    const label = (el.getAttribute('aria-label') || el.innerText || el.placeholder || '').replace(/\s+/g, ' ').trim().slice(0, 60);
    const value = secret ? '' : (el.tagName === 'SELECT' ? (el.selectedOptions[0] && el.selectedOptions[0].label) : ['checkbox', 'radio'].includes(type) ? String(el.checked) : el.value) || '';
    parts.push(`${el.tagName}|${label}|${String(value).slice(0, 60)}|${el.getAttribute('aria-expanded') || ''}|${el.getAttribute('aria-checked') || ''}|${el.getAttribute('aria-selected') || ''}|${el.getAttribute('aria-pressed') || ''}|${el.disabled ? 1 : 0}`);
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
  let top = document.elementFromPoint(cx, cy);
  while (top && top.shadowRoot) { const inner = top.shadowRoot.elementFromPoint(cx, cy); if (!inner || inner === top) break; top = inner; }      // look through open shadow roots, as describe does
  if (!top) return 'covered';
  for (let n = top; n; n = n.parentNode || n.host) if (n === el) return 'ok';
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
    // What the site answered for the page itself (200, 403, 429 ...): the host tells a page that was refused from a page that is merely empty or slow.
    p.on('response', res => { try { if (res.request().isNavigationRequest() && res.frame() === p.mainFrame()) p._luminaStatus = res.status(); } catch { /* the frame is gone */ } });
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
  /** A JPEG of the window. The ordinary way waits for the page's web fonts, and on a shop whose fonts never finish loading it gave up after 8 s on every step
   *  (the decider then had no picture). After a short try, the browser is asked for the picture directly, which waits for nothing. */
  async shoot(quality) {
    try { return await this.page.screenshot({ type: 'jpeg', quality, scale: 'css', fullPage: false, timeout: 3000 }); }
    catch {
      const cdp = await this.context.newCDPSession(this.page);
      try { const { data } = await cdp.send('Page.captureScreenshot', { format: 'jpeg', quality, captureBeyondViewport: false }); return Buffer.from(data, 'base64'); }
      finally { await cdp.detach().catch(() => {}); }
    }
  }
  async fp() { try { return createHash('sha1').update(await this.page.evaluate(fingerprint, SELECTOR)).digest('hex').slice(0, 12); } catch { return null; } }   // null = could not tell (page changing under us)
  /** Wait until the page has stopped changing, not until its network is silent: most real sites never go silent (analytics, ads, long polls), so that wait ran its full 2.5 s
   *  on every page opened and after many steps. The page counts as still when it has loaded and two looks 150 ms apart see the same amount of it; never longer than `ms`. */
  async settle(ms = 2500, waitLoad = true) {
    const until = Date.now() + ms;
    if (waitLoad) { try { await this.page.waitForLoadState('domcontentloaded', { timeout: 5000 }); } catch { /* slow pages are fine */ } }    // not again for a page whose open already ran out of loading time
    let last = null;
    for (;;) {
      const now = await this.page.evaluate(() => document.readyState + '|' + document.getElementsByTagName('*').length + '|' + ((document.body && document.body.innerText) || '').length).catch(() => null);
      if (now !== null && now === last && now.startsWith('complete')) return;
      if (Date.now() >= until) return;
      last = now;
      await this.page.waitForTimeout(150).catch(() => {});
    }
  }
  /** A page caught between two pages (still loading, or nothing drawn yet) reads as an empty one, and a decider shown an empty page gives up or calls for the customer.
   *  Give it a little longer, and stop the moment it has something to show. Never more than `ms`. */
  async drawn(ms = 3000) {
    const until = Date.now() + ms;
    for (;;) {
      const state = await this.page.evaluate(() => ({ loading: document.readyState === 'loading', words: ((document.body && document.body.innerText) || '').trim().length, things: document.querySelectorAll('a[href], button, input, select, textarea').length })).catch(() => null);
      if (state && !state.loading && (state.words >= 20 || state.things >= 1)) return;
      if (Date.now() >= until) return;
      await this.page.waitForTimeout(200).catch(() => {});
    }
  }
  /** After a click or a key the page often changes a moment later than the browser calls it settled (a site that swaps its own content in, a menu that animates open).
   *  Reading it at once said "nothing changed" about a click that worked, and the decider clicked again. Wait for a change, up to `ms`; a click that really did nothing costs that wait once. */
  async changedSince(before, beforeUrl, ms = 900) {
    const until = Date.now() + ms;
    for (;;) {
      const now = await this.fp();
      if (now === null || now !== before || this.page.url() !== beforeUrl || Date.now() >= until) return now;
      await this.page.waitForTimeout(150).catch(() => {});
    }
  }

  async handle(msg) {
    await this.ensurePage();
    switch (msg.cmd) {
      case 'open': {
        if (!urlAllowed(msg.url, ALLOW_LOOPBACK)) return { ok: false, error: 'url_blocked' };
        // A page is open once the site has answered. How long its own scripts then take is the page's business, not a failure: one limit for both ("content loaded within
        // 20 s") failed a heavy shop whose answer came in under a second, in a stage with one processor (production 2026-11-22, "navigation_failed"). So: wait for the
        // answer; then give the page time to load, and go on with what it has drawn when that time is up. The snapshot waits for something to be drawn anyway.
        try { await this.page.goto(msg.url, { waitUntil: 'commit', timeout: OPEN_ANSWER_MS }); }
        catch (e) {
          // The tab is now on its way to the browser's own error page, and an open sent to it meanwhile is "interrupted by another navigation" and fails as well: the host's
          // second try, and every open after it, could never work (found 2026-11-22; it was so since the first release). The task carries on in a fresh tab of the same
          // browser (same cookies, same sign-ins), and the broken one is closed.
          const broken = this.page;
          try { this.page = this.prepare(await this.context.newPage()); await broken.close().catch(() => {}); } catch { this.page = broken; }
          return { ok: false, error: 'navigation_failed', detail: String(e.message || e).split('\n')[0].slice(0, 160) };
        }
        const loaded = await this.page.waitForLoadState('domcontentloaded', { timeout: OPEN_LOAD_MS }).then(() => true, () => false);
        await this.settle(2500, loaded); return { ok: true, url: this.page.url(), title: (await this.page.title().catch(() => '')).slice(0, 120), ...(loaded ? {} : { still_loading: true }) };
      }
      case 'snapshot': {
        await this.settle(); await this.drawn(); const d = await this.page.evaluate(describe, { sel: SELECTOR, max: MAX_ELEMENTS });
        const lines = d.elements.map(e => `[${e.ref}] <${e.tag}${e.type ? ' type=' + e.type : ''}> "${e.label}"`).join('\n');
        return { ok: true, url: this.page.url(), title: d.title, snapshot: lines, text: d.text, pages: this.context.pages().length, elements: d.elements, page_fp: await this.fp(), scroll: d.scroll, height: d.height, window: d.window, focus: d.focus, full: d.full, full_at: d.full_at, http_status: this.page._luminaStatus || null };
      }
      case 'act': {
        const { ref, action, value, expect } = msg;
        const fpBefore = ['click', 'clickat', 'press', 'select'].includes(action) ? await this.fp() : null; const urlBefore = this.page.url();
        const done = async extra => ({ ok: true, url: this.page.url(), page_fp: fpBefore ? await this.changedSince(fpBefore, urlBefore) : await this.fp(), ...extra });
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
          else if (action === 'key') { if (!KEYS.has(text) && !TAKEOVER_KEYS.has(text)) return { ok: false, error: 'key_not_allowed' }; await this.page.keyboard.press(text); }
          else if (action === 'scroll') await this.page.mouse.wheel(0, (text === 'down' || Number(text) > 0) ? 500 : -500);      // the app sends the words 'up' and 'down'
          else if (action === 'goto') {      // the address bar: the same address rules as every request this browser makes (public http/https only)
            if (typeof text !== 'string' || text.length > MAX_URL || !urlAllowed(text, ALLOW_LOOPBACK)) return { ok: false, error: 'url_blocked' };
            await this.page.goto(text, { waitUntil: 'commit', timeout: 15000 });
          }
          else if (action === 'back') await this.page.goBack({ waitUntil: 'commit', timeout: 15000 });
          else if (action === 'forward') await this.page.goForward({ waitUntil: 'commit', timeout: 15000 });
          else if (action === 'reload') await this.page.reload({ waitUntil: 'commit', timeout: 15000 });
          else return { ok: false, error: 'bad_action' };
        } catch (e) { return { ok: false, error: 'action_failed' }; }
        return { ok: true, url: this.page.url() };     // no waiting for the page to settle: the next input must not queue behind a slow load
      }
      case 'view': {   // the picture JEV is shown when the element list cannot be used: one JPEG of the window as it is (1280x800, inside JEV's size limits), optionally kept for the run's record
        const bytes = await this.shoot(75);
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
        writeFileSync(join(OUT, file), await this.shoot(60));
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
    // A page whose own script never yields makes a read of it hang for ever. Each command has a limit a little under the host's, so the host gets an answer it can act on
    // (look again, reload) instead of losing the whole task to a silence.
    const limit = { open: OPEN_ANSWER_MS + OPEN_LOAD_MS + 10000, snapshot: 16000, act: 27000, view: 12000, screenshot: 12000, probe: 6000, xy: 18000 }[msg.cmd] || 16000;
    let res; let timer;
    try { res = await Promise.race([runner.handle(msg), new Promise(resolve => { timer = setTimeout(() => resolve({ ok: false, error: 'timeout' }), limit); })]); }
    catch (e) { res = { ok: false, error: 'runner_error' }; }
    clearTimeout(timer);
    console.log(JSON.stringify({ id: msg.id, ...res }));
  }); });
  rl.on('close', async () => { await queue; await runner.stop(); process.exit(0); });   // finish queued work before shutting the browser
}
if (import.meta.url === `file://${process.argv[1]}`) void main();
