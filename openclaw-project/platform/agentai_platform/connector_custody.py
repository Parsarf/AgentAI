"""Custody for provider tokens (roadmap #22): sealed at rest, behind account-bound opaque references.

The same sealing the vault uses for saved logins: AES-256-GCM, a different key per account (derived from a master key), a fresh nonce per record, and the owner and the
reference bound in as authenticated data, so a row copied to another account or another reference does not open. The master key lives in a root-only file
(`AGENTAI_CONNECTOR_KEY_FILE`); without it custody is off and every link fails closed (`DisabledCustody` in connectors.py), exactly as before this existed.

Nothing here returns a secret to anything but the host-side connector client. References are random and say nothing. Tokens are never logged, never in events and never in
a response: the tables views read hold only the reference.
"""
from __future__ import annotations
import secrets
import time

from cryptography.exceptions import InvalidTag

from .connectors import ConnectorNotConfigured
from .security import NotFound
from .vault import Keyring, VaultOff

MAX_SECRET_BYTES = 32768


def keyring_from_file(path):
    """The custody keyring, or None when the key file is not set, not private or malformed (custody is then off)."""
    try:
        return Keyring.from_file(path)
    except VaultOff:
        return None


class SealedCustody:
    def __init__(self, store, keyring: Keyring, *, clock=time.time):
        if keyring is None:
            raise ConnectorNotConfigured('custody unavailable')
        self.store, self.ring, self.clock = store, keyring, clock

    @staticmethod
    def _aad(account_id, ref):
        return f'connector|{account_id}|{ref}'.encode()

    def _aead(self, kid, account_id):
        return self.ring._aead(kid, 'connector:' + account_id)        # its own key space: a vault record and a custody record of one account never share a key

    def put(self, account_id: str, label: str, secret: bytes) -> str:
        with self.store.connect() as con:
            return self.put_in(con, account_id, label, secret)

    def put_in(self, con, account_id: str, label: str, secret: bytes) -> str:
        """`put` on the caller's own connection: for a caller that is inside a write transaction (a second connection would wait on the first's lock), and so that the
        secret and the row that refers to it are committed or rolled back together."""
        if not isinstance(secret, (bytes, bytearray)) or not 0 < len(secret) <= MAX_SECRET_BYTES:
            raise ValueError('invalid secret')
        ref, nonce = 'cs-' + secrets.token_hex(16), secrets.token_bytes(12)
        sealed = self._aead(self.ring.current, account_id).encrypt(nonce, bytes(secret), self._aad(account_id, ref))
        con.execute('INSERT INTO connector_secrets(account_id,ref,label,kid,nonce,ciphertext,created_epoch) VALUES (?,?,?,?,?,?,?)',
                    (account_id, ref, str(label)[:40], self.ring.current, nonce, sealed, int(self.clock())))
        return ref

    def get(self, account_id: str, ref: str) -> bytes:
        with self.store.connect() as con:
            row = con.execute('SELECT kid,nonce,ciphertext FROM connector_secrets WHERE account_id=? AND ref=?', (account_id, ref)).fetchone()
        if row is None:
            raise NotFound('unavailable')
        try:
            return self._aead(row['kid'], account_id).decrypt(bytes(row['nonce']), bytes(row['ciphertext']), self._aad(account_id, ref))
        except (InvalidTag, ValueError):
            raise NotFound('unavailable') from None                   # a row that does not open is, for every caller, a row that is not there

    def delete(self, account_id: str, ref: str) -> None:
        with self.store.connect() as con:
            self.delete_in(con, account_id, ref)

    @staticmethod
    def delete_in(con, account_id: str, ref: str) -> None:
        con.execute('DELETE FROM connector_secrets WHERE account_id=? AND ref=?', (account_id, ref))

    def delete_all(self, account_id: str) -> int:
        """Every secret of one account (account deletion). -> how many were removed."""
        with self.store.connect() as con:
            return con.execute('DELETE FROM connector_secrets WHERE account_id=?', (account_id,)).rowcount

    def count(self, account_id: str) -> int:
        with self.store.connect() as con:
            return con.execute('SELECT count(*) FROM connector_secrets WHERE account_id=?', (account_id,)).fetchone()[0]
