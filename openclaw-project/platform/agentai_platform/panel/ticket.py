"""Panel tickets: HMAC-signed, expire in about a minute, bound to one account, the person it runs for, one conversation and one connected computer.

A ticket is the side panel's whole credential: it carries no cookie and no device token. Only the web app's side holds the key (never the browse service, which only
relays the finished string to the extension), and the app re-checks on every request that the run is live and that exact computer is connected. A different prefix from the
live-view tickets (live/ticket.py) means one kind can never be accepted as the other, even if both were signed with the same key."""
from __future__ import annotations
import base64
import hashlib
import hmac
import json
import re
import time

PREFIX = 'p1'
TTL_SECONDS = 90
IDENT = re.compile(r'^[A-Za-z0-9_-]{1,64}$')
DEVICE = re.compile(r'^[a-f0-9]{16}$')
MAX_TICKET = 600


class TicketError(Exception):
    pass


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b'=').decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + '=' * (-len(text) % 4))


def _sign(secret: bytes, body: str) -> str:
    return _b64(hmac.new(secret, f'{PREFIX}.{body}'.encode(), hashlib.sha256).digest())


def mint(secret: bytes, account: str, actor: str, conversation: str, device: str, *, now=time.time, ttl=TTL_SECONDS) -> str:
    if len(secret or b'') < 32 or not all(IDENT.fullmatch(x or '') for x in (account, actor, conversation)) or not DEVICE.fullmatch(device or ''):
        raise TicketError('cannot mint')
    body = _b64(json.dumps({'a': account, 'u': actor, 'c': conversation, 'd': device, 'e': int(now()) + int(ttl)}, separators=(',', ':')).encode())
    return f'{PREFIX}.{body}.{_sign(secret, body)}'


def verify(secret: bytes, ticket, *, now=time.time) -> dict:
    """-> {'account', 'actor', 'conversation', 'device'}. Raises TicketError for anything wrong; the reason is deliberately not returned to callers."""
    try:
        if not isinstance(ticket, str) or len(ticket) > MAX_TICKET or len(secret or b'') < 32:
            raise ValueError
        prefix, body, sig = ticket.split('.')
        if prefix != PREFIX or not hmac.compare_digest(sig, _sign(secret, body)):
            raise ValueError
        data = json.loads(_unb64(body))
        claims = {'account': data['a'], 'actor': data['u'], 'conversation': data['c'], 'device': data['d']}
        if int(data['e']) < now() or not all(isinstance(v, str) for v in claims.values()):
            raise ValueError
        if not all(IDENT.fullmatch(claims[k]) for k in ('account', 'actor', 'conversation')) or not DEVICE.fullmatch(claims['device']):
            raise ValueError
        return claims
    except (ValueError, KeyError, TypeError, json.JSONDecodeError):
        raise TicketError('invalid ticket') from None
