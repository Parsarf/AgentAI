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


def build(snapshot_text: str, limit: int = 20) -> list[dict]:
    out = []
    for line in snapshot_text.splitlines():
        m = SNAPSHOT_RE.match(line.strip())
        if not m:
            continue
        ref, tag, input_type, label = m.groups()
        kind = action_type(tag, input_type)
        if kind is None:
            continue
        out.append({'id': f'c{ref}', 'ref': int(ref), 'action': kind, 'label': label, 'tag': tag, 'input_type': input_type or '',
                    'fingerprint': hashlib.sha256(f'{ref}|{tag}|{input_type or ""}|{label}'.encode()).hexdigest()[:16],
                    'sensitive': bool(SENSITIVE.search(label)) or input_type == 'password'})
        if len(out) >= limit:
            break
    return out


def page_is_payment(url: str, snapshot_text: str, page_text: str) -> bool:
    """A page that is, or is about to be, a payment step: the read-only release stops here and hands the screen to the user."""
    return bool(CHECKOUT_PATH.search(url or '')) or bool(CARD_FIELD.search(snapshot_text or '')) or sum(1 for _ in CARD_FIELD.finditer(page_text or '')) >= 2
