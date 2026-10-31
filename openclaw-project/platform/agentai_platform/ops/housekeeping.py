"""Bounded cleanup of plaintext pre-migration database snapshots.

Release and migration tooling leaves `backup-*.sqlite3` snapshots next to the live database (mode 0600, root).
They are plaintext, so they are kept to the newest few and never past the 30-day backup maximum. Only files
matching the exact name pattern in this one directory are ever removed (and, with each, its `-wal` / `-shm` sidecars).
"""
from pathlib import Path
import re
import time

PATTERN = re.compile(r'backup-\d{8}T\d{6}Z(-[A-Za-z0-9._-]+)?\.sqlite3')      # upper case too: deploy/release.py names them ...-premigrate-20261012T1830Z-ops.sqlite3, and a lower-case-only pattern matched none of them


def prune_snapshots(directory, *, keep=3, max_age_days=30, now=None):
    now = now or time.time()
    files = sorted((p for p in Path(directory).iterdir() if p.is_file() and not p.is_symlink() and PATTERN.fullmatch(p.name)),
                   key=lambda p: p.stat().st_mtime, reverse=True)
    removed = []
    for index, path in enumerate(files):
        too_old = now - path.stat().st_mtime > max_age_days * 86400
        if index >= keep or (too_old and index > 0):   # never remove the newest snapshot just for age
            path.unlink(); removed.append(path.name)
            for sidecar in (path.with_name(path.name + '-wal'), path.with_name(path.name + '-shm')):      # SQLite leaves these beside a copy that was opened; they go with it
                if sidecar.is_file() and not sidecar.is_symlink():
                    sidecar.unlink()
    return removed
