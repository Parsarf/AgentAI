"""Watch tickets: HMAC-signed, expire in minutes, bound to one account and one task. View only: controlling the page still goes
through the normal authenticated API, so a leaked ticket can look at one task's frames for a few minutes and do nothing else."""
from __future__ import annotations
import base64
import hashlib
import hmac
import json
import re
import time

REQUEST_ID = re.compile(r'^[a-f0-9]{32}$')
TTL_SECONDS = 120
PREFIX = 'v1'


class TicketError(Exception):
    pass


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b'=').decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + '=' * (-len(text) % 4))


def mint(secret: bytes, account_id: str, request_id: str, *, now=time.time, ttl=TTL_SECONDS) -> str:
    if not secret or not REQUEST_ID.fullmatch(request_id or ''):
        raise TicketError('cannot mint')
    body = _b64(json.dumps({'a': account_id, 'r': request_id, 'e': int(now()) + ttl}, separators=(',', ':')).encode())
    sig = _b64(hmac.new(secret, f'{PREFIX}.{body}'.encode(), hashlib.sha256).digest())
    return f'{PREFIX}.{body}.{sig}'


def verify(secret: bytes, ticket: str, request_id: str, *, now=time.time) -> str:
    """-> account_id. Raises TicketError for anything wrong; the reason is deliberately not returned to callers."""
    try:
        prefix, body, sig = ticket.split('.')
        if prefix != PREFIX or not secret:
            raise ValueError
        want = _b64(hmac.new(secret, f'{prefix}.{body}'.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(sig, want):
            raise ValueError
        data = json.loads(_unb64(body))
        if data['r'] != request_id or not REQUEST_ID.fullmatch(request_id) or int(data['e']) < now() or not isinstance(data['a'], str):
            raise ValueError
        return data['a']
    except (ValueError, KeyError, TypeError, json.JSONDecodeError):
        raise TicketError('invalid ticket') from None
