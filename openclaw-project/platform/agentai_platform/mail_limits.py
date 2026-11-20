"""How much mail an account may send (roadmap Phase 6, #66): protection against misuse of the customer's mailbox, not a quota. No bulk sending in Lumina.

The platform sets a ceiling; the customer's organization may set a lower one (policy `mail_limits`), and so may the customer (their mail settings). The lowest applies.
Counted by account: people a message goes to (to and copy), and messages sent in the last hour (every send that started, whatever became of it).
"""
from __future__ import annotations
import json
import time

PLATFORM = {'recipients': 50, 'per_hour': 30}
MAIL_DEFAULTS = {'undo_send_seconds': 10, 'mark_read_on_open': False}
# Addresses at these domains belong to no organization: "outside your organization" is only said for a sender at an organization's own domain (#66).
PUBLIC_MAIL_DOMAINS = frozenset({'gmail.com', 'googlemail.com', 'outlook.com', 'hotmail.com', 'live.com', 'msn.com', 'yahoo.com', 'icloud.com', 'me.com', 'mac.com', 'aol.com',
                                 'proton.me', 'protonmail.com', 'gmx.com', 'gmx.de', 'mail.com', 'yandex.com', 'zoho.com'})


def clean(value) -> dict:
    """A customer's or an organization's own limits: each at least 1 and at most the platform's. Raises ValueError."""
    if not isinstance(value, dict) or set(value) - set(PLATFORM):
        raise ValueError('invalid limits')
    out = {}
    for key, ceiling in PLATFORM.items():
        if value.get(key) is None:
            continue
        if type(value[key]) is not int or not 1 <= value[key] <= ceiling:
            raise ValueError(f'{key} is a whole number from 1 to {ceiling}')
        out[key] = value[key]
    return out


def mail_settings(con, account_id) -> dict:
    try:
        row = con.execute('SELECT mail_json FROM hub_settings WHERE account_id=?', (account_id,)).fetchone()
        own = json.loads(row[0]) if row and row[0] else {}
    except Exception:
        own = {}
    return {**MAIL_DEFAULTS, **{k: own[k] for k in MAIL_DEFAULTS if k in own}, 'limits': own.get('limits') or {}}


def limits(con, account_id) -> dict:
    from .organizations import policy
    out = dict(PLATFORM)
    for layer in (policy(con, account_id).get('mail_limits') or {}, mail_settings(con, account_id)['limits']):
        for key in out:
            if isinstance(layer.get(key), int):
                out[key] = min(out[key], layer[key])
    return out


def refusal(con, account_id, people: int, *, including_this: bool, clock=time.time) -> str | None:
    """Why this send is not allowed now, in a sentence the customer reads, or None. `including_this`: the send being checked already started (it is counted)."""
    allowed = limits(con, account_id)
    if people > allowed['recipients']:
        return f'This message goes to {people} people; the limit is {allowed["recipients"]} a message. Nothing was sent.'
    sent = con.execute("SELECT count(*) FROM connector_operations WHERE account_id=? AND kind='mail.send' AND created_epoch>? AND state IN ('running','completed','uncertain')",
                       (account_id, int(clock()) - 3600)).fetchone()[0]
    if sent - (1 if including_this else 0) >= allowed['per_hour']:
        return f'{allowed["per_hour"]} messages were sent from this account in the last hour, which is the limit. Nothing was sent; it can be sent later.'
    return None
