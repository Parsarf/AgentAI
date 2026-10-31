"""The page-side scripts the native browser runs for us (act kind=evaluate). They are the same in-page functions the retired Playwright runner used (browse/runner.mjs),
so what the deciders see (element list, labels, fingerprints) and the fresh-target check before every action are unchanged; only who drives the browser changed.

The cell bridge accepts these by NAME only (see lifecycle/cell_bridge.py): a caller can never send its own script to a customer's browser.
"""
from __future__ import annotations
import json

SELECTOR = 'a[href], button, input:not([type=hidden]), select, textarea, [role=button], [role=link], [role=checkbox], [role=radio], [role=tab], [onclick]'
MAX_ELEMENTS = 80

# Marks interactive elements with data-lumina-ref / data-lumina-label and describes them. A field holding a secret (password, card, one-time code) is always listed, never with its value.
DESCRIBE = r"""(args) => {
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
  return { elements: out, title: document.title.slice(0, 120), url: location.href, text: (document.body && document.body.innerText || '').replace(/\s+\n/g, '\n').slice(0, 6000),
    scroll: Math.round(window.scrollY), height: Math.round(Math.max(page.scrollHeight, document.body ? document.body.scrollHeight : 0)), window: vh, width: vw };
}"""

# What is at a point on the screen, with the name a person would give it (looks through open shadow roots).
HIT_AT = r"""(args) => {
  const { x, y } = args;
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
}"""

# A text summary of what a person would see: two summaries are equal exactly when the page did not visibly change. Scroll position is part of it.
FINGERPRINT = r"""(args) => {
  const sel = args.sel;
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
}"""

# The element the host chose, right before acting: it must still carry the label it had ("stale" otherwise), be enabled, and have nothing on top of it.
# Returns { state: 'ok' | 'stale' | 'disabled' | 'covered' | 'bad_action', x, y } with the element's centre in window coordinates after bringing it into view.
LOCATE = r"""(args) => {
  const { ref, label, action } = args;
  const el = document.querySelector('[data-lumina-ref="' + ref + '"]');
  if (!el || !el.isConnected) return { state: 'stale' };
  if (label !== null && label !== undefined && el.getAttribute('data-lumina-label') !== label) return { state: 'stale' };
  if (el.disabled || el.getAttribute('aria-disabled') === 'true' || el.closest('[inert], [aria-disabled=true], fieldset:disabled')) return { state: 'disabled' };
  if (action === 'type' && (el.readOnly || el.getAttribute('aria-readonly') === 'true')) return { state: 'disabled' };
  el.scrollIntoView({ block: 'center', inline: 'center' });
  const r = el.getBoundingClientRect();
  if (r.width < 2 || r.height < 2) return { state: 'covered' };
  const cx = r.left + r.width / 2, cy = r.top + r.height / 2;
  if (cx < 0 || cy < 0 || cx > window.innerWidth || cy > window.innerHeight) return { state: 'covered' };
  const top = document.elementFromPoint(cx, cy);
  if (!top) return { state: 'covered' };
  if (!(top === el || el.contains(top) || (el.labels && [...el.labels].some(l => l === top || l.contains(top))))) return { state: 'covered' };
  return { state: 'ok', x: cx, y: cy, tag: el.tagName.toLowerCase() };
}"""

# Puts text into the element the host chose (after LOCATE said ok): focus, select what is there so typing replaces it, then insert as typing would.
TYPE_INTO = r"""(args) => {
  const { ref, value } = args;
  const el = document.querySelector('[data-lumina-ref="' + ref + '"]');
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
  const s = document.querySelector('[data-lumina-ref="' + ref + '"]');
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
SCROLL = r"""(args) => { window.scrollBy({ top: args.dy, left: 0, behavior: 'instant' }); return { y: Math.round(window.scrollY) }; }"""

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
