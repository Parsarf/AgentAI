"""Backup encryption with age: the host holds only PUBLIC recipients.

The server can therefore write encrypted backups but cannot read them, so a
compromised or ransomware-hit host cannot decrypt history, and decryption keys
stay with the owner. Decryption here exists for drills and the owner's own
restore tooling; it needs an identity file that is never installed on the host.
"""
from pathlib import Path
import re
import subprocess

RECIPIENT = re.compile(r'age1[a-z0-9]{58}')
HEADER = b'age-encryption.org/v1\n'


class CryptoError(Exception): pass


def default_run(argv):
    done = subprocess.run(argv, stdin=subprocess.DEVNULL, capture_output=True, timeout=3600)
    return done.returncode, done.stderr.decode('utf-8', 'replace')[-300:]


class AgeCrypto:
    def __init__(self, recipients, run=default_run, binary='age'):
        recipients = list(recipients or [])
        if not recipients or not all(isinstance(r, str) and RECIPIENT.fullmatch(r) for r in recipients):
            raise CryptoError('at least one valid age public recipient is required')
        self.recipients, self.run, self.binary = recipients, run, binary

    def encrypt(self, src, dst):
        src, dst = Path(src), Path(dst)
        if dst.exists(): raise CryptoError('refusing to overwrite an existing file')
        argv = [self.binary]
        for recipient in self.recipients: argv += ['-r', recipient]
        code, err = self.run(argv + ['-o', str(dst), str(src)])
        if code != 0 or not self.looks_encrypted(dst):
            dst.unlink(missing_ok=True)
            raise CryptoError('encryption failed')
        dst.chmod(0o600)
        return dst

    @staticmethod
    def looks_encrypted(path):
        try:
            with open(path, 'rb') as handle:
                return handle.read(len(HEADER)) == HEADER and Path(path).stat().st_size > 200
        except OSError:
            return False

    def decrypt(self, src, dst, identity_file):
        """Owner/drill side only; the identity file must not live on the production host."""
        src, dst = Path(src), Path(dst)
        if dst.exists(): raise CryptoError('refusing to overwrite an existing file')
        code, err = self.run([self.binary, '-d', '-i', str(identity_file), '-o', str(dst), str(src)])
        if code != 0:
            dst.unlink(missing_ok=True)
            raise CryptoError('decryption failed (wrong key or damaged file)')
        return dst
