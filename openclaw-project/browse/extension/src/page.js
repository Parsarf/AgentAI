// Page-side helpers. Each runs INSIDE the page (sent as source through Runtime.evaluate), so each must be fully self-contained: no imports, no closure.
// describe, hitAt, focusActive, fingerprint and ready are copied verbatim from ../../runner.mjs by test/extension-parity.test.mjs's rule: if one changes there, change it here (the test fails on drift).

// Runs in the page. Describes interactive elements in the format the host parses: [ref] <tag type=x> "label", plus their state.
// A field that holds a secret (password, card, one-time code) is always listed, never with its value, so the host can see that the page needs the user.
export function describe(args) {
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
export function hitAt({ x, y }) {
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
export function focusActive() {
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
export function fingerprint(sel) {
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
export function ready(el, action) {
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


// Extension only. Runs in the page, on the element the host chose (marked by describe): find it, make sure the label is still the one the host saw,
// bring its middle into the window, and report whether it can be acted on, with the point to click. Needs `ready` in scope (the executor sends it along).
export function locate({ ref, expect, action }) {
  const el = document.querySelector(`[data-lumina-ref="${ref}"]`);
  if (!el) return { state: 'stale' };
  if (expect && el.getAttribute('data-lumina-label') !== expect.label) return { state: 'stale' };
  let r = el.getBoundingClientRect();
  if (r.top < 0 || r.left < 0 || r.bottom > window.innerHeight || r.right > window.innerWidth) el.scrollIntoView({ block: 'center', inline: 'center' });
  const state = ready(el, action);
  r = el.getBoundingClientRect();
  return { state, x: r.left + r.width / 2, y: r.top + r.height / 2 };
}

// Extension only. Runs in the page. Pick the option the way the runner does (exact label, exact value, case-insensitive label, then label prefix) and select it.
// Returns the index, or -1 when nothing matches (nothing is changed then).
export function chooseOption({ ref, value }) {
  const s = document.querySelector(`[data-lumina-ref="${ref}"]`);
  if (!s || !s.options) return -2;
  const o = [...s.options]; const lc = x => String(x).trim().toLowerCase();
  let i = o.findIndex(x => x.label === value);
  if (i < 0) i = o.findIndex(x => x.value === value);
  if (i < 0) i = o.findIndex(x => lc(x.label) === lc(value));
  if (i < 0) i = o.findIndex(x => lc(x.label).startsWith(lc(value)));
  if (i < 0) return -1;
  s.selectedIndex = i;
  s.dispatchEvent(new Event('input', { bubbles: true })); s.dispatchEvent(new Event('change', { bubbles: true }));
  return i;
}

// Extension only. Runs in the page, right before text is inserted into a field the host chose: focus it and select what is there so the typing replaces it.
export function focusForFill({ ref }) {
  const el = document.querySelector(`[data-lumina-ref="${ref}"]`);
  if (!el) return false;
  el.focus();
  if (el.select) el.select(); else document.execCommand('selectAll');
  return document.activeElement === el || el.contains(document.activeElement);
}
