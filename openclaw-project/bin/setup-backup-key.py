#!/usr/bin/env python3
"""Create the backup decryption key on YOUR computer (never on the server) and print only the public half.

The private file stays in ~/agentai-backup-key/identity.txt (mode 0600). Copy it into your password manager
and keep a second copy somewhere else (a USB stick, a printed copy in a safe). Without it every backup is
unreadable; with it anyone can read every backup, so never put it on the server, in Git, or in chat.
"""
import os
import stat
import subprocess
import sys
from pathlib import Path

directory = Path.home() / 'agentai-backup-key'
identity = directory / 'identity.txt'
directory.mkdir(mode=0o700, exist_ok=True)
if identity.exists():
    out = subprocess.run(['age-keygen', '-y', str(identity)], capture_output=True, text=True)
    print('A key already exists at', identity)
else:
    out = subprocess.run(['age-keygen', '-o', str(identity)], capture_output=True, text=True)
    os.chmod(identity, 0o600)
    print('Created', identity, '(mode', oct(stat.S_IMODE(identity.stat().st_mode)) + ')')
public = [w for w in (out.stdout + out.stderr).split() if w.startswith('age1')]
if out.returncode or not public:
    sys.exit('age-keygen failed; install age first (brew install age)')
print('PUBLIC KEY (safe to share, goes on the server):', public[0])
print('NEXT: store the private file in your password manager and a second place. It is shown nowhere else.')
