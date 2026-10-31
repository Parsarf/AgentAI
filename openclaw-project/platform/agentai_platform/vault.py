"""Saved logins and cards: what the customer asked Lumina to keep so a task can fill them in.

Encryption: AES-256-GCM, a different key per account (HKDF from the master key), a fresh random nonce per record, and the record's owner, kind and id bound in
as authenticated data, so a copied or swapped row fails to open. The master key lives in a root-only file (`AGENTAI_VAULT_KEY_FILE`), never in the database or a
backup of it; without that file the vault is off and nothing can be saved or opened.

What is never stored: a card's security code (CVV/CVC). What never leaves this module in the clear except to open an item for one approved fill: the secret.
Models, JEV, logs, traces and screenshots never receive it."""
from __future__ import annotations
import base64
import json
import os
import re
import secrets
import time
from urllib.parse import urlsplit

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

MAX_ITEMS = 30
KINDS = ('login', 'card')
DISCLAIMER_VERSION = 1


class VaultOff(Exception):
    """No key file: the vault is not set up on this server."""


class VaultError(ValueError):
    pass


class Keyring:
    """`kid:base64-key` per line in a root-only file; the first line is used for new records, every line can open old ones (key rotation)."""
    def __init__(self, keys: dict[str, bytes], current: str):
        self.keys, self.current = keys, current

    @classmethod
    def from_file(cls, path):
        try:
            if not path:
                raise VaultOff('vault key file not set')
            mode = os.stat(path).st_mode
            if mode & 0o077:
                raise VaultOff('vault key file must be private (0600)')
            with open(path, encoding='ascii') as fh:
                lines = [l.strip() for l in fh.read().splitlines() if l.strip() and not l.startswith('#')]
        except (OSError, UnicodeDecodeError) as exc:
            raise VaultOff('vault key file unreadable') from exc
        keys = {}
        for line in lines:
            kid, _, b64 = line.partition(':')
            try:
                raw = base64.urlsafe_b64decode(b64 + '=' * (-len(b64) % 4)) if b64 else b''
            except ValueError:                 # binascii.Error is a ValueError
                raw = b''
            if not re.fullmatch(r'[a-z0-9]{1,12}', kid) or len(raw) != 32:
                raise VaultOff('vault key file is malformed')
            keys[kid] = raw
        if not keys:
            raise VaultOff('vault key file is empty')
        return cls(keys, next(iter(keys)))

    @staticmethod
    def generate():
        return 'k1:' + base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip('=')

    def _aead(self, kid, account_id):
        master = self.keys.get(kid)
        if master is None:
            raise VaultError('unknown key')
        return AESGCM(HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=b'lumina-vault|' + account_id.encode()).derive(master))


def _aad(account_id, kind, item_id):
    return f'{account_id}|{kind}|{item_id}'.encode()


# ---------------------------------------------------------------- validation
def luhn(number: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(number)):
        d = int(ch)
        if i % 2:
            d = d * 2 - 9 if d > 4 else d * 2
        total += d
    return total % 10 == 0


def brand(number: str) -> str:
    if number.startswith('4'):
        return 'Visa'
    if re.match(r'^(5[1-5]|2[2-7])', number):
        return 'Mastercard'
    if re.match(r'^3[47]', number):
        return 'Amex'
    if re.match(r'^(6011|65)', number):
        return 'Discover'
    return 'Card'


def host_of(site: str) -> str:
    """The site a login belongs to: the host only (no path, no query), lower-case, without www."""
    raw = str(site or '').strip()
    parsed = urlsplit(raw if '//' in raw else '//' + raw)
    host = (parsed.hostname or '').lower().rstrip('.')
    if not host or '.' not in host or len(host) > 120 or not re.fullmatch(r'[a-z0-9.-]+', host):
        raise VaultError('that is not a site address')
    return host[4:] if host.startswith('www.') else host


def _clean_card(secret: dict, now: float):
    forbidden = {k for k in secret if str(k).lower() in ('cvv', 'cvc', 'cvv2', 'csc', 'security_code', 'code')}
    if forbidden:
        raise VaultError('the security code is never saved')
    number = re.sub(r'[ -]', '', str(secret.get('number') or ''))
    if not number.isdigit() or not 12 <= len(number) <= 19 or not luhn(number):
        raise VaultError('that card number does not look right')
    try:
        month, year = int(secret.get('exp_month')), int(secret.get('exp_year'))
    except (TypeError, ValueError):
        raise VaultError('the expiry date does not look right')
    year += 2000 if year < 100 else 0
    t = time.gmtime(now)
    if not 1 <= month <= 12 or (year, month) < (t.tm_year, t.tm_mon) or year > t.tm_year + 25:
        raise VaultError('the expiry date does not look right')
    name = str(secret.get('name') or '').strip()[:80]
    return {'number': number, 'exp_month': month, 'exp_year': year, 'name': name}, f'{brand(number)} ending {number[-4:]}', ''


def _clean_login(secret: dict, site: str):
    username, password = str(secret.get('username') or '').strip(), str(secret.get('password') or '')
    if not username or not password or len(username) > 200 or len(password) > 200:
        raise VaultError('a login needs a username and a password')
    host = host_of(site)
    masked = username[:2] + '***' + (username[username.find('@'):] if '@' in username else '')
    return {'username': username, 'password': password}, f'Login for {host}', host, masked


# ---------------------------------------------------------------- storage (con: anything with .execute and ? placeholders)
def public(row) -> dict:
    return {'id': row['id'], 'kind': row['kind'], 'label': row['label'], 'site': row['site'], 'hint': row['hint'], 'last_used_epoch': row['last_used_epoch']}


def list_items(con, account_id) -> list[dict]:
    return [public(r) for r in con.execute('SELECT * FROM vault_items WHERE account_id=? ORDER BY created_epoch', (account_id,)).fetchall()]


def add(con, ring: Keyring, account_id, kind, secret, *, site='', accepted=False, now=None) -> dict:
    """Seal and store one item. `accepted` must be True: the customer ticked the disclaimer for this save."""
    if kind not in KINDS or not isinstance(secret, dict):
        raise VaultError('invalid item')
    if accepted is not True:
        raise VaultError('the notice must be accepted first')
    now = time.time() if now is None else now
    if kind == 'card':
        data, label, host = *_clean_card(secret, now)[:2], ''
        hint = label
    else:
        data, label, host, hint = _clean_login(secret, site)
    if con.execute('SELECT count(*) FROM vault_items WHERE account_id=?', (account_id,)).fetchone()[0] >= MAX_ITEMS:
        raise VaultError('the saved list is full')
    item_id = secrets.token_hex(8)
    nonce = secrets.token_bytes(12)
    sealed = ring._aead(ring.current, account_id).encrypt(nonce, json.dumps(data, separators=(',', ':')).encode(), _aad(account_id, kind, item_id))
    con.execute('''INSERT INTO vault_items(account_id,id,kind,label,site,hint,kid,nonce,ciphertext,accepted_epoch,created_epoch) VALUES (?,?,?,?,?,?,?,?,?,?,?)''',
                (account_id, item_id, kind, label, host, hint, ring.current, nonce, sealed, int(now), int(now)))
    return {'id': item_id, 'kind': kind, 'label': label, 'site': host, 'hint': hint, 'last_used_epoch': None}


def open_item(con, ring: Keyring, account_id, item_id, *, now=None) -> tuple[str, dict]:
    """Decrypt one item for one approved fill. -> (kind, secret). Fails closed on any mismatch."""
    row = con.execute('SELECT * FROM vault_items WHERE account_id=? AND id=?', (account_id, item_id)).fetchone()
    if row is None:
        raise VaultError('not found')
    try:
        data = ring._aead(row['kid'], account_id).decrypt(bytes(row['nonce']), bytes(row['ciphertext']), _aad(account_id, row['kind'], row['id']))
    except InvalidTag as exc:
        raise VaultError('could not open the item') from exc
    con.execute('UPDATE vault_items SET last_used_epoch=? WHERE account_id=? AND id=?', (int(time.time() if now is None else now), account_id, item_id))
    return row['kind'], json.loads(data)


def delete(con, account_id, item_id):
    con.execute('DELETE FROM vault_items WHERE account_id=? AND id=?', (account_id, str(item_id)[:40]))


def logins_for(con, account_id, host) -> list[dict]:
    """The saved logins for a site (the readable part only): offered when a run reaches that site's sign-in page."""
    host = host_of(host)
    return [public(r) for r in con.execute("SELECT * FROM vault_items WHERE account_id=? AND kind='login' AND site=?", (account_id, host)).fetchall()]
