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


STATE_FIELDS = ('role', 'value', 'checked', 'expanded', 'in_view', 'options')


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
        if len(out) >= limit:
            break
    return out


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
