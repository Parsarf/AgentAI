"""The page-side scripts the native browser runs for us (act kind=evaluate). They are the same in-page functions the retired Playwright runner used (browse/runner.mjs),
so what the deciders see (element list, labels, fingerprints) and the fresh-target check before every action are unchanged; only who drives the browser changed.

The cell bridge accepts these by NAME only (see lifecycle/cell_bridge.py): a caller can never send its own script to a customer's browser.
"""
from __future__ import annotations
import json

SELECTOR = 'a[href], button, input:not([type=hidden]), select, textarea, [role=button], [role=link], [role=checkbox], [role=radio], [role=tab], [role=combobox], [role=option], [role=menuitem], [role=menuitemcheckbox], [role=menuitemradio], [role=switch], [onclick]'
MAX_ELEMENTS = 80

# Marks interactive elements with data-lumina-ref / data-lumina-label and describes them. A field holding a secret (password, card, one-time code) is always listed, never with its value.
DESCRIBE = r"""(args) => {
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
  return { elements: out, title: document.title.slice(0, 120), url: location.href, text: text.slice(0, 12000), full, full_at: above ? Math.min(above.length + 1, full.length) : 0,
    scroll: Math.round(window.scrollY), height: Math.round(Math.max(page.scrollHeight, document.body ? document.body.scrollHeight : 0)), window: vh, width: vw, focus };
}"""

# What is at a point on the screen, with the name a person would give it (looks through open shadow roots).
HIT_AT = r"""(args) => {
  const { x, y } = args;
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
}"""

# A text summary of what a person would see: two summaries are equal exactly when the page did not visibly change. Scroll position is part of it.
FINGERPRINT = r"""(args) => {
  const sel = args.sel;
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
}"""

# The element the host chose, right before acting: it must still carry the label it had ("stale" otherwise), be enabled, and have nothing on top of it.
# Returns { state: 'ok' | 'stale' | 'disabled' | 'covered' | 'bad_action', x, y } with the element's centre in window coordinates after bringing it into view.
LOCATE = r"""(args) => {
  const { ref, label, action } = args;
  const find = ref => { const q = '[data-lumina-ref="' + ref + '"]'; const roots = [document]; for (let i = 0; i < roots.length && i < 300; i++) { const hit = roots[i].querySelector(q); if (hit) return hit; for (const e of roots[i].querySelectorAll('*')) if (e.shadowRoot) roots.push(e.shadowRoot); } return null; };      // through open shadow roots, as describe lists them
  const el = find(ref);
  if (!el || !el.isConnected) return { state: 'stale' };
  if (label !== null && label !== undefined && el.getAttribute('data-lumina-label') !== label) return { state: 'stale' };
  if (el.disabled || el.getAttribute('aria-disabled') === 'true' || el.closest('[inert], [aria-disabled=true], fieldset:disabled')) return { state: 'disabled' };
  if (action === 'type' && (el.readOnly || el.getAttribute('aria-readonly') === 'true')) return { state: 'disabled' };
  el.scrollIntoView({ block: 'center', inline: 'center' });
  const r = el.getBoundingClientRect();
  if (r.width < 2 || r.height < 2) return { state: 'covered' };
  const cx = r.left + r.width / 2, cy = r.top + r.height / 2;
  if (cx < 0 || cy < 0 || cx > window.innerWidth || cy > window.innerHeight) return { state: 'covered' };
  let top = document.elementFromPoint(cx, cy);
  while (top && top.shadowRoot) { const inner = top.shadowRoot.elementFromPoint(cx, cy); if (!inner || inner === top) break; top = inner; }
  if (!top) return { state: 'covered' };
  let own = false; for (let n = top; n; n = n.parentNode || n.host) if (n === el) { own = true; break; }
  if (!(own || (el.labels && [...el.labels].some(l => l === top || l.contains(top))))) return { state: 'covered' };
  return { state: 'ok', x: cx, y: cy, tag: el.tagName.toLowerCase() };
}"""

# Puts text into the element the host chose (after LOCATE said ok): focus, select what is there so typing replaces it, then insert as typing would.
TYPE_INTO = r"""(args) => {
  const { ref, value } = args;
  const find = ref => { const q = '[data-lumina-ref="' + ref + '"]'; const roots = [document]; for (let i = 0; i < roots.length && i < 300; i++) { const hit = roots[i].querySelector(q); if (hit) return hit; for (const e of roots[i].querySelectorAll('*')) if (e.shadowRoot) roots.push(e.shadowRoot); } return null; };      // through open shadow roots, as describe lists them
  const el = find(ref);
  if (!el) return { ok: false, error: 'stale' };
  el.focus();
  const tag = el.tagName.toLowerCase();
  if (tag === 'select' || (tag === 'input' && ['checkbox', 'radio', 'submit', 'button', 'reset', 'image', 'file', 'range', 'color'].includes((el.getAttribute('type') || '').toLowerCase()))) return { ok: false, error: 'not_a_field' };
  if (el.select) el.select(); else document.execCommand('selectAll');
  let done = false;
  try { done = document.execCommand('insertText', false, value); } catch (e) { done = false; }
  if (!done || (el.value !== undefined && el.value !== value)) {
    const proto = tag === 'textarea' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
    const setter = Object.getOwnPropertyDescriptor(proto, 'value');
    if (el.value === undefined || !setter) return { ok: false, error: 'action_failed' };
    setter.set.call(el, value);
    el.dispatchEvent(new Event('input', { bubbles: true }));
    el.dispatchEvent(new Event('change', { bubbles: true }));
  }
  return { ok: true };
}"""

# Chooses an option of a <select> the way the runner did: exact label, exact value, case-insensitive label, then label prefix.
SELECT_OPTION = r"""(args) => {
  const { ref, value } = args;
  const find = ref => { const q = '[data-lumina-ref="' + ref + '"]'; const roots = [document]; for (let i = 0; i < roots.length && i < 300; i++) { const hit = roots[i].querySelector(q); if (hit) return hit; for (const e of roots[i].querySelectorAll('*')) if (e.shadowRoot) roots.push(e.shadowRoot); } return null; };      // through open shadow roots, as describe lists them
  const s = find(ref);
  if (!s || !s.options) return { ok: false, error: 'stale' };
  const o = [...s.options]; const lc = x => String(x).trim().toLowerCase();
  let i = o.findIndex(x => x.label === value);
  if (i < 0) i = o.findIndex(x => x.value === value);
  if (i < 0) i = o.findIndex(x => lc(x.label) === lc(value));
  if (i < 0) i = o.findIndex(x => lc(x.label).startsWith(lc(value)));
  if (i < 0) return { ok: false, error: 'no_option' };
  s.selectedIndex = i;
  s.dispatchEvent(new Event('input', { bubbles: true }));
  s.dispatchEvent(new Event('change', { bubbles: true }));
  return { ok: true };
}"""

# After a click on a text field (by point): is the focus in something that takes text? If so select what is there so typing replaces it.
FOCUS_ACTIVE = r"""(args) => {
  const el = document.activeElement;
  if (!el) return false;
  const tag = el.tagName.toLowerCase(), type = tag === 'input' ? (el.getAttribute('type') || 'text').toLowerCase() : '';
  const ok = tag === 'textarea' || (tag === 'input' && !['checkbox', 'radio', 'submit', 'button', 'reset', 'image', 'file', 'range', 'color', 'hidden'].includes(type)) || el.isContentEditable;
  if (!ok || el.readOnly || el.disabled || type === 'password') return false;
  if (el.select) el.select(); else document.execCommand('selectAll');
  return true;
}"""

# Where the page is, for the loop's "already at the bottom" notes and the window size the pictures are judged against.
VIEWPORT = r"""(args) => ({ w: window.innerWidth, h: window.innerHeight, url: location.href, title: document.title.slice(0, 120), ready: document.readyState })"""

# Back, forward and reload, for the loop's back step and the customer's takeover buttons.
HISTORY = r"""(args) => { if (args.delta === 0) location.reload(); else history.go(args.delta); return true; }"""

# The wheel, as the runner's mouse.wheel did: down or up by a fixed amount, from wherever the page is (the loop's scroll step and the customer's takeover scroll).
# Scrolls what a person's mouse wheel would: the nearest scrollable area under the point (a popup, a side panel, a results list), else the page. Says whether anything moved.
SCROLL = r"""(args) => {
  const { dy, x, y } = args;
  let box = null;
  const start = typeof x === 'number' && typeof y === 'number' ? document.elementFromPoint(x, y) : null;
  for (let n = start; n && n !== document.body && n !== document.documentElement; n = n.parentElement) {
    const oy = getComputedStyle(n).overflowY;
    if ((oy === 'auto' || oy === 'scroll') && n.scrollHeight > n.clientHeight + 4) { box = n; break; }
  }
  const sc = box || document.scrollingElement || document.documentElement;
  const before = sc.scrollTop;
  sc.scrollBy({ top: dy, left: 0, behavior: 'instant' });
  const view = box ? box.clientHeight : window.innerHeight;
  return { y: Math.round(window.scrollY), moved: Math.abs(sc.scrollTop - before) > 1, inner: !!box, at_end: dy > 0 && sc.scrollTop + view >= sc.scrollHeight - 4 };
}"""

# Text typed by the customer in a takeover goes to whatever has focus, as insertText (no shortcuts, no key chords).
INSERT_TEXT = r"""(args) => {
  const el = document.activeElement;
  if (!el) return { ok: false, error: 'action_failed' };
  let done = false;
  try { done = document.execCommand('insertText', false, args.text); } catch (e) { done = false; }
  return { ok: !!done, error: done ? undefined : 'action_failed' };
}"""

SCRIPTS = {'describe': DESCRIBE, 'hit_at': HIT_AT, 'fingerprint': FINGERPRINT, 'locate': LOCATE, 'type_into': TYPE_INTO, 'select_option': SELECT_OPTION,
           'focus_active': FOCUS_ACTIVE, 'viewport': VIEWPORT, 'scroll': SCROLL, 'insert_text': INSERT_TEXT, 'history': HISTORY}


def expression(name: str, args: dict | None = None) -> str:
    """The function source handed to the native browser's evaluate: the named script applied to JSON arguments."""
    return f'() => ({SCRIPTS[name]})({json.dumps(args or {})})'
