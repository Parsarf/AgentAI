#!/usr/bin/env python3
"""Copy the newest encrypted backup sets from the server to this computer (a real off-server copy).

The files are encrypted for your key, so storing them here exposes nothing. Each file is checked against its
manifest. Records the pull on the server so the monitor knows an outside copy exists. Keeps the last 14 locally.
usage: pull-backups.py [--keep N] [--dest DIR]
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

here = Path(__file__).resolve().parent
ssh = [sys.executable, str(here / 'ssh-server')]
ap = argparse.ArgumentParser(); ap.add_argument('--keep', type=int, default=14); ap.add_argument('--dest', default=str(Path.home() / 'agentai-backups'))
args = ap.parse_args()
dest = Path(args.dest); dest.mkdir(mode=0o700, parents=True, exist_ok=True)
REMOTE = '/var/backups/agentai/sets'


def remote(cmd, out=None):
    return subprocess.run(ssh + [cmd], stdout=out if out else subprocess.PIPE, stderr=subprocess.DEVNULL, check=True)


listing = remote(f'ls -1 {REMOTE}').stdout.decode().split()
sets = sorted(s for s in listing if len(s) == 16 and s.endswith('Z'))
pulled = 0
for sid in sets[-args.keep:]:
    target = dest / 'sets' / sid
    if (target / 'manifest.json').exists():
        continue
    target.mkdir(mode=0o700, parents=True, exist_ok=True)
    manifest = json.loads(remote(f'cat {REMOTE}/{sid}/manifest.json').stdout)
    if not manifest.get('complete'):
        print(f'skip {sid}: incomplete set'); continue
    for art in manifest['artifacts']:
        path = target / art['name']
        with open(path, 'wb') as handle: remote(f"cat {REMOTE}/{sid}/{art['name']}", handle)
        os.chmod(path, 0o600)
        if hashlib.sha256(path.read_bytes()).hexdigest() != art['sha256']:
            path.unlink(); sys.exit(f"CORRUPT: {sid}/{art['name']} does not match its manifest; stopped")
    for extra in remote(f'ls -1 {REMOTE}/{sid}').stdout.decode().split():
        if extra.endswith('.manifest.json') or extra == 'manifest.json':
            (target / extra).write_bytes(remote(f'cat {REMOTE}/{sid}/{extra}').stdout)
    pulled += 1; print('pulled', sid, f"({len(manifest['artifacts'])} files, verified)")
local = sorted(p.name for p in (dest / 'sets').iterdir() if p.is_dir())
for old in local[:-args.keep]:
    for f in (dest / 'sets' / old).iterdir(): f.unlink()
    (dest / 'sets' / old).rmdir()
remote("python3 -c \"import json,time;open('/var/lib/agentai-ops/last-pull.json','w').write(json.dumps({'epoch':int(time.time())}))\"")
print(f'done: {pulled} new set(s) in {dest}; {min(len(local), args.keep)} kept')
