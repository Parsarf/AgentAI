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


# ---- work stream tickets -------------------------------------------------------------------------------------------------------------------------------
# The push gateway (push.py) is a separate small server that the signed-in session never reaches. The web app, which does hold the session, mints one of these for it:
# bound to one account and one member, short-lived, read only. A different prefix and field set from the frame ticket above, so neither can be used as the other.
WORK_PREFIX = 'w1'
WORK_TTL_SECONDS = 90
ACTOR_ID = re.compile(r'^[A-Za-z0-9_-]{1,64}$')


def mint_work(secret: bytes, account_id: str, actor_id: str, *, now=time.time, ttl=WORK_TTL_SECONDS) -> str:
    if not secret or not isinstance(account_id, str) or not account_id or not ACTOR_ID.fullmatch(str(actor_id or '')):
        raise TicketError('cannot mint')
    body = _b64(json.dumps({'a': account_id, 'u': str(actor_id), 'e': int(now()) + ttl}, separators=(',', ':')).encode())
    sig = _b64(hmac.new(secret, f'{WORK_PREFIX}.{body}'.encode(), hashlib.sha256).digest())
    return f'{WORK_PREFIX}.{body}.{sig}'


def verify_work(secret: bytes, ticket: str, *, now=time.time) -> tuple[str, str]:
    """-> (account_id, actor_id). Raises TicketError for anything wrong."""
    try:
        prefix, body, sig = ticket.split('.')
        if prefix != WORK_PREFIX or not secret:
            raise ValueError
        want = _b64(hmac.new(secret, f'{prefix}.{body}'.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(sig, want):
            raise ValueError
        data = json.loads(_unb64(body))
        if int(data['e']) < now() or not isinstance(data['a'], str) or not data['a'] or not ACTOR_ID.fullmatch(data['u']):
            raise ValueError
        return data['a'], data['u']
    except (ValueError, KeyError, TypeError, json.JSONDecodeError):
        raise TicketError('invalid ticket') from None
