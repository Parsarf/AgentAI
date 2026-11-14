"""Candidates the deciders may choose from, built by code from the runner's snapshot (never by a model).

Mirrors browser-opt/jev_adapter.py (same line format, same sensitive-control rule) so both stay interchangeable.
"""
from __future__ import annotations
import hashlib
import re

SNAPSHOT_RE = re.compile(r'^\[(\d{1,4})\]\s+<([a-z]+)(?:\s+type=([a-z]+))?>\s+"(.{0,120})"\s*$')
# Consequential controls always need the user: model confidence can never grant permission to pay, send, delete or sign in.
SENSITIVE = re.compile(r'\b(submit|pay|payment|purchase|buy( now)?|order|place order|confirm|delete|remove|send|transfer|sign\s*out|log\s*out|'
                       r'unsubscribe|publish|donate|checkout|complete (order|purchase)|subscribe|book now)\b', re.I)
CHECKOUT_PATH = re.compile(r'/(checkout|payment|pay|billing|order/confirm|purchase)\b', re.I)
CARD_FIELD = re.compile(r'(card number|cvv|cvc|security code|expiry|expiration|credit card|debit card)', re.I)
ACTIONS = {'a': 'click', 'button': 'click', 'input': 'type', 'textarea': 'type', 'select': 'select'}


def action_type(tag: str, input_type: str | None) -> str | None:
    if tag == 'input':
        if input_type in ('checkbox', 'radio', 'button', 'submit'):
            return 'click'
        if input_type in (None, '', 'text', 'email', 'search', 'tel', 'url', 'number', 'password'):
            return 'type'
        return None
    return ACTIONS.get(tag)


STATE_FIELDS = ('role', 'value', 'checked', 'expanded', 'in_view', 'covered', 'options', 'x', 'y')
JEV_LIMIT = 80                 # controls the fast decider is offered at once: what is in the window, not what comes first in the page's code
SNAP_RADIUS = 0.06             # how far (as a share of the window) a point chosen from the picture may be moved to reach a listed control


def build(snapshot_text: str, limit: int = 20, elements: list | None = None) -> list[dict]:
    """Candidates come from the snapshot LINES (the format has not changed). `elements`, when the runner sends it, adds each element's state;
    an older runner sends none, and then candidates simply carry no state."""
    by_ref = {e.get('ref'): e for e in elements or [] if isinstance(e, dict)}
    out = []
    for line in snapshot_text.splitlines():
        m = SNAPSHOT_RE.match(line.strip())
        if not m:
            continue
        ref, tag, input_type, label = m.groups()
        kind = action_type(tag, input_type)
        if kind is None:
            continue
        c = {'id': f'c{ref}', 'ref': int(ref), 'action': kind, 'label': label, 'tag': tag, 'input_type': input_type or '',
             'fingerprint': hashlib.sha256(f'{ref}|{tag}|{input_type or ""}|{label}'.encode()).hexdigest()[:16],
             'sensitive': bool(SENSITIVE.search(label)) or input_type == 'password'}
        state = by_ref.get(int(ref))
        if state and state.get('label') == label:                      # the same element the line describes
            c.update({k: state[k] for k in STATE_FIELDS if k in state})
            if input_type == 'password':
                c['value'] = ''                                       # belt and braces: the runner already sends none
        out.append(c)
    return _within(out, limit)


def _within(cands: list[dict], limit: int) -> list[dict]:
    """Prefer usable controls in the current viewport over offscreen navigation.

    Keep page order in the final list, and preserve the legacy order when the
    runner supplies no visibility information. This exposes product swatches
    and drawer controls even when a long header precedes them in the DOM.
    """
    head, rest = cands[:limit], cands[limit:]
    free = [c for c in rest if c.get('in_view') and c.get('covered') is False]
    replace = [i for i, c in enumerate(head) if c.get('covered') or c.get('in_view') is False]
    for i, c in zip(reversed(replace), free):
        head[i] = c
    return sorted(head, key=lambda c: c['ref'])


def reachable(cands: list[dict], limit: int = JEV_LIMIT) -> list[dict] | None:
    """What the fast decider is offered: the controls a person could click right now (in the window, nothing on top), in page order. It is shown the same window as a
    picture, so the list and the picture describe the same thing. None when the engine does not say what is visible (an older one): the caller keeps its own list."""
    if not any(c.get('in_view') is not None for c in cands):
        return None
    return [c for c in cands if c.get('in_view') and c.get('covered') is False][:limit]


def for_assistant(listed: list[dict], in_window: list[dict] | None, limit: int = JEV_LIMIT) -> list[dict]:
    """What the assistant is offered when a page is handed to it: everything it was offered before (`listed`, the first controls of the page with those in the window preferred),
    and with it the controls a person could click right now (`in_window`, what the fast decider is offered). It used to get `listed` alone, at most 20: on a results page the
    fast decider could see a product's button that the assistant, asked to take over, could not. In page order; never more than `limit`, and the controls in the window are the
    ones kept when there are too many. An engine that does not say what is visible (`in_window` is None) keeps the old list."""
    if not in_window:
        return listed
    keep = {c['ref']: c for c in in_window[:limit]}
    for c in listed:
        if len(keep) >= limit:
            break
        keep.setdefault(c['ref'], c)
    return sorted(keep.values(), key=lambda c: c['ref'])


def nearest(cands: list[dict], x: float, y: float, width: float, height: float, radius: float = SNAP_RADIUS) -> dict | None:
    """The listed clickable control closest to a point, if one is within `radius` of it (a share of the window). Never a secret field: a click is not steered onto one."""
    best, best_d = None, radius
    for c in cands:
        if c.get('action') != 'click' or c.get('sensitive') or not isinstance(c.get('x'), (int, float)) or not isinstance(c.get('y'), (int, float)) or not width or not height:
            continue
        d = (((c['x'] - x) / width) ** 2 + ((c['y'] - y) / height) ** 2) ** 0.5
        if d < best_d:
            best, best_d = c, d
    return best


def with_focus(cands: list[dict], focus) -> list[dict]:
    """Mark the control that has the keyboard (the engine names it by its number), so a decider can be told that typing would land there."""
    ref = focus.get('ref') if isinstance(focus, dict) and focus.get('editable') else None
    return [{**c, 'focused': True} if ref is not None and c['ref'] == ref else c for c in cands]


def page_is_payment(url: str, snapshot_text: str, page_text: str) -> bool:
    """A page that is, or is about to be, a payment step: the read-only release stops here and hands the screen to the user."""
    return bool(CHECKOUT_PATH.search(url or '')) or bool(CARD_FIELD.search(snapshot_text or '')) or sum(1 for _ in CARD_FIELD.finditer(page_text or '')) >= 2


PASSWORD_FIELD = re.compile(r'^\[\d+\]\s+<input\s+type=password>', re.M)


def page_is_login(snapshot_text: str) -> bool:
    """A page with a password field. It is read from the runner's snapshot lines (not the 20 listed candidates), so a field past the cap still counts.
    Such a page goes to the user before any model, JEV included, is shown it: sign-in pages are where a customer's private data sits."""
    return bool(PASSWORD_FIELD.search(snapshot_text or ''))


BOT_CHECK = re.compile(r'just a moment|verify (you are|you.re) (a )?human|checking (if|that) you are human|checking your browser|attention required|are you a robot|press (&|and) hold|captcha|unusual traffic|access denied', re.I)


def page_is_bot_check(title: str, page_text: str) -> bool:
    """A human-verification wall (Cloudflare and similar). Short pages only, so an article that merely mentions captchas does not match."""
    return len(page_text or '') < 1500 and bool(BOT_CHECK.search(f'{title or ""} {(page_text or "")[:1500]}'))
