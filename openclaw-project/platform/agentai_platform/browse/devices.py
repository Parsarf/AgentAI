"""Paired computers: the customers' own Chrome that may run their browser tasks (the `local` engine).

A customer asks for a pairing code (short, single-use, minutes); the extension in their Chrome trades it for a long random device token,
which only its hash is kept here. From then on the extension proves itself with the token each time it connects. A device can be
revoked at any time, which also drops its live connection.

  DeviceStore   what is remembered (a small 0600 JSON file, safe for several processes: the web app, this service and the command line)
  DeviceHub     who is connected right now: at most one live link per account, because a task needs exactly one browser
  DeviceLink    one connected extension: commands go out, replies come back, in order

Command line (run on the host, as the service user):  python -m agentai_platform.browse.devices pair --account <id> [--store <file>]
"""
from __future__ import annotations
import argparse
import contextlib
import fcntl
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import tempfile
import threading
import time
from collections import deque

from .session import RunnerError

ALPHABET = 'ABCDEFGHJKMNPQRSTUVWXYZ23456789'      # no 0 O 1 I L: read aloud or typed from a screen without mistakes
CODE_LENGTH = 8                                   # 31^8 is about 40 bits; with the short life and the gateway's attempt limit that is not guessable
PAIR_TTL = 600
MAX_OPEN_CODES = 5
MAX_DEVICES = 5
LABEL_MAX = 60
DEFAULT_STORE = '/var/lib/agentai-supervisor/devices.json'


class DeviceError(Exception):
    pass


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def normalise_code(code) -> str:
    return ''.join(c for c in str(code or '').upper() if c.isalnum())[:CODE_LENGTH + 4]


def clean_label(label) -> str:
    """What the customer sees in their device list: printable characters only, short."""
    text = ''.join(c for c in str(label or '') if c.isprintable()).strip()
    return text[:LABEL_MAX] or 'Chrome'


class DeviceStore:
    def __init__(self, path, *, clock=time.time):
        self.path, self.clock, self._lock = Path(path), clock, threading.RLock()

    @contextlib.contextmanager
    def _txn(self):
        """Read the file, let the caller change the dict, write it back atomically if it changed. One writer at a time across processes."""
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(str(self.path) + '.lock', os.O_CREAT | os.O_RDWR, 0o600)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX)
                try:
                    db = json.loads(self.path.read_text())
                except (OSError, ValueError):
                    db = {}
                if not isinstance(db, dict):
                    db = {}
                db.setdefault('pairings', {})
                db.setdefault('devices', {})
                db.setdefault('prefs', {})
                before = json.dumps(db, sort_keys=True)
                yield db
                if json.dumps(db, sort_keys=True) != before:
                    tmp = tempfile.NamedTemporaryFile('w', dir=self.path.parent, prefix='.devices-', delete=False)
                    try:
                        os.chmod(tmp.name, 0o600)
                        json.dump(db, tmp)
                        tmp.flush()
                        os.fsync(tmp.fileno())
                        tmp.close()
                        os.replace(tmp.name, self.path)
                    except BaseException:
                        with contextlib.suppress(OSError):
                            os.unlink(tmp.name)
                        raise
            finally:
                os.close(fd)

    def _expire(self, db):
        now = self.clock()
        db['pairings'] = {k: v for k, v in db['pairings'].items() if v.get('expires', 0) > now}

    # ------------------------------------------------------------------ pairing
    def pair(self, account: str) -> str:
        """A fresh code for this account (shown to the customer once). The oldest open code goes when there are too many."""
        if not isinstance(account, str) or not account:
            raise DeviceError('no account')
        with self._txn() as db:
            self._expire(db)
            mine = sorted((v.get('n', 0), k) for k, v in db['pairings'].items() if v['account'] == account)       # by order of issue: two codes can share a clock reading
            for _, key in mine[:max(0, len(mine) - MAX_OPEN_CODES + 1)]:
                del db['pairings'][key]
            code = ''.join(secrets.choice(ALPHABET) for _ in range(CODE_LENGTH))
            db['pair_seq'] = db.get('pair_seq', 0) + 1
            db['pairings'][_hash(code)] = {'account': account, 'expires': self.clock() + PAIR_TTL, 'n': db['pair_seq']}
            return code

    def redeem(self, code, label=''):
        """Trade a code for a device. -> {'account', 'device_id', 'token'} (the token exists only in this return value), or None for an unknown, used or expired code."""
        with self._txn() as db:
            self._expire(db)
            entry = db['pairings'].get(_hash(normalise_code(code)))
            if entry is None:
                return None
            account = entry['account']
            if sum(1 for d in db['devices'].values() if d['account'] == account) >= MAX_DEVICES:
                raise DeviceError('device limit')
            del db['pairings'][_hash(normalise_code(code))]          # single use
            token, device_id, now = secrets.token_urlsafe(32), secrets.token_hex(8), self.clock()
            db['devices'][device_id] = {'account': account, 'token': _hash(token), 'label': clean_label(label), 'created': now, 'last_seen': now}
            return {'account': account, 'device_id': device_id, 'token': token}

    # ------------------------------------------------------------------ the customer's choice
    def wants_local(self, account: str) -> bool:
        """Has this customer switched on "use my own browser" (the switch at the top of every chat)? Off until they say so."""
        with self._txn() as db:
            return bool(db['prefs'].get(account, {}).get('own_browser'))

    def set_wants_local(self, account: str, on: bool) -> bool:
        with self._txn() as db:
            db['prefs'].setdefault(account, {})['own_browser'] = bool(on)
            return bool(on)

    # ------------------------------------------------------------------ devices
    def authenticate(self, token):
        """-> (account, device_id) for a device token that is still valid, else None."""
        if not isinstance(token, str) or not 20 <= len(token) <= 200:
            return None
        digest, found = _hash(token), None
        with self._txn() as db:
            for device_id, d in db['devices'].items():
                if hmac.compare_digest(d['token'], digest):
                    found = (d['account'], device_id)
            if found:
                db['devices'][found[1]]['last_seen'] = int(self.clock() // 60 * 60)         # to the minute: a connection does not rewrite the file for nothing
        return found

    def devices(self, account: str):
        with self._txn() as db:
            return [{'device_id': k, 'label': v['label'], 'created': v['created'], 'last_seen': v['last_seen']} for k, v in db['devices'].items() if v['account'] == account]

    def exists(self, account: str, device_id: str) -> bool:
        with self._txn() as db:
            d = db['devices'].get(device_id)
            return bool(d) and d['account'] == account

    def revoke(self, account: str, device_id: str) -> bool:
        with self._txn() as db:
            d = db['devices'].get(device_id)
            if not d or d['account'] != account:
                return False
            del db['devices'][device_id]
            return True


class DeviceLink:
    """One connected extension. `conn` needs send_text(str) and close(code, reason). Replies arrive on the gateway's reader thread (push) and are taken in order (recv)."""

    def __init__(self, account, device_id, conn):
        self.account, self.device_id, self.conn = account, device_id, conn
        self._cv, self._inbox, self.alive, self.reason = threading.Condition(), deque(), True, ''
        self.stopped = ''                      # set when the customer pressed Cancel on Chrome's debugging bar (the extension says so before it hangs up)

    def begin(self):
        """A new task starts on this link: anything still in the inbox belongs to an earlier one."""
        with self._cv:
            self._inbox.clear()

    def push(self, msg):
        with self._cv:
            self._inbox.append(msg)
            self._cv.notify_all()

    def note_event(self, msg):
        if msg.get('event') == 'stopped':
            self.stopped = str(msg.get('reason', 'stopped'))[:40]

    def send(self, obj):
        if not self.alive:
            raise BrokenPipeError('device left')
        self.conn.send_text(json.dumps(obj, separators=(',', ':')))

    def recv(self, timeout):
        with self._cv:
            if not self._cv.wait_for(lambda: self._inbox or not self.alive, timeout=timeout):
                raise TimeoutError('runner did not answer in time')
            if self._inbox:
                return self._inbox.popleft()
        raise RunnerError('device left: ' + (self.stopped or self.reason or 'disconnected'))

    def close(self, reason='closed', code=1000):
        with self._cv:
            if not self.alive:
                return
            self.alive, self.reason = False, reason
            self._cv.notify_all()
        try:
            self.conn.close(code, reason)
        except Exception:
            pass


class DeviceHub:
    def __init__(self):
        self._links, self._lock = {}, threading.Lock()

    def attach(self, account, device_id, conn) -> DeviceLink:
        link = DeviceLink(account, device_id, conn)
        with self._lock:
            old = self._links.get(account)
            self._links[account] = link
        if old is not None:
            old.close('replaced by another computer', 4409)
        return link

    def link(self, account):
        with self._lock:
            link = self._links.get(account)
        return link if link is not None and link.alive else None

    def detach(self, link):
        with self._lock:
            if self._links.get(link.account) is link:
                del self._links[link.account]
        link.close('disconnected')

    def kick(self, account, device_id, reason='revoked'):
        link = self.link(account)
        if link is not None and link.device_id == device_id:
            link.close(reason, 4403)
            return True
        return False

    def connected(self):
        with self._lock:
            return [(a, l.device_id) for a, l in self._links.items() if l.alive]


class DeviceDesk:
    """What the customer's pages ask about their computers (through the service's private socket): a pairing code, the list, and revoking one.
    `allowed(account)` is the on/off for the whole feature (browse-engine.json: `"local": false` switches it off for everyone); when it is off nobody can pair, switch it on or use it."""

    def __init__(self, store: DeviceStore, hub: DeviceHub, *, allowed=lambda account: True):
        self.store, self.hub, self.allowed = store, hub, allowed

    def pair(self, account):
        if not self.allowed(account):
            return {'allowed': False}
        return {'allowed': True, 'code': self.store.pair(account), 'expires_in': PAIR_TTL}

    def listing(self, account):
        live = self.hub.link(account)
        return {'allowed': bool(self.allowed(account)), 'use': self.store.wants_local(account), 'connected': live is not None,
                'devices': [{**d, 'connected': bool(live and live.device_id == d['device_id'])} for d in sorted(self.store.devices(account), key=lambda d: d['created'])]}

    def use(self, account, on):
        if not self.allowed(account):
            return {'allowed': False}
        return {'allowed': True, 'use': self.store.set_wants_local(account, bool(on))}

    def revoke(self, account, device_id):
        done = self.store.revoke(account, device_id)
        if done:
            self.hub.kick(account, device_id, 'revoked')
        return {'ok': done}


def main(argv=None):
    parser = argparse.ArgumentParser(description='Manage paired computers')
    parser.add_argument('--store', default=DEFAULT_STORE)
    sub = parser.add_subparsers(dest='cmd', required=True)
    sub.add_parser('pair').add_argument('--account', required=True)
    sub.add_parser('list').add_argument('--account', required=True)
    revoke = sub.add_parser('revoke')
    revoke.add_argument('--account', required=True)
    revoke.add_argument('--device', required=True)
    args = parser.parse_args(argv)
    store = DeviceStore(args.store)
    if args.cmd == 'pair':
        print(f'pairing code (valid {PAIR_TTL // 60} minutes, one use): {store.pair(args.account)}')
    elif args.cmd == 'list':
        for d in store.devices(args.account):
            print(d['device_id'], d['label'], 'last seen', int(d['last_seen']))
    else:
        print('revoked' if store.revoke(args.account, args.device) else 'no such device')


if __name__ == '__main__':
    main()
