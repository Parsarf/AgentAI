"""One-use proof from OpenClaw's awaited before_tool_call hook.

The hook supplies session/run/call identity and overwrites the transport nonce.
The model's task IDs and the timing of transcript writes are not authority.
The app must still match the returned identity to an admitted funded delivery.
"""
from contextlib import closing
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import time

TOOLS = {'lumina_browser', 'lumina_browser_step', 'lumina_task_update'}
MAX_BYTES = 24_000
MAX_AGE_SECONDS = 1800


def _db(root, relative):
    path = root / relative
    for parent in (path, *path.parents):
        if parent.is_symlink():
            raise ValueError('symlink')
        if parent == root:
            break
    return sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=1)


def active(root):
    """The worker's bounded active-turn inventory, independent of tool proof."""
    try:
        with closing(_db(Path(root).absolute(), 'state/openclaw.sqlite')) as state:
            rows = state.execute('SELECT session_id,session_key,turn_claim_run_id FROM worker_session_placements WHERE turn_claim_id IS NOT NULL AND turn_claim_run_id IS NOT NULL LIMIT 33').fetchall()
        return rows if len(rows) <= 32 else None
    except (OSError, sqlite3.Error, ValueError):
        return None


def inspect_origin(root, name, arguments, nonce=None, *, clock=time.time):
    """Consume a proof once; return identity and a fixed, content-free status."""
    def denied(status):
        return {'origin': None, 'status': status}
    if not isinstance(name, str) or name not in TOOLS or not isinstance(arguments, dict):
        return denied('invalid_arguments')
    if not isinstance(nonce, str) or not re.fullmatch(r'[a-f0-9]{32}', nonce):
        return denied('proof_missing')
    directory, handle = None, None
    try:
        # Traverse from a directory descriptor: a cell cannot redirect this
        # root reader through a symlink between checking and opening a path.
        root = Path(root).absolute()
        directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        child = os.open('tool-origins', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
        os.close(directory)
        directory = child
        filename = nonce + '.json'
        handle = os.open(filename, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW, dir_fd=directory)
        info = os.fstat(handle)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_mode & 0o077 or not 0 < info.st_size <= MAX_BYTES:
            return denied('proof_invalid')
        data = os.read(handle, MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            return denied('proof_invalid')
        proof = json.loads(data)
        if not isinstance(proof, dict) or proof.get('version') != 2 or proof.get('name') != name:
            return denied('proof_invalid')
        started = proof.get('started_ms')
        if type(started) not in (int, float) or not 0 <= clock() - started / 1000 <= MAX_AGE_SECONDS:
            return denied('proof_expired')
        if not all(isinstance(proof.get(k), str) and 0 < len(proof[k]) < 512 for k in ('session_key', 'run_id', 'call_id')):
            return denied('proof_invalid')
        if proof.get('arguments') != arguments:
            return denied('argument_mismatch')
        # Unlink is the atomic claim. Two concurrent requests cannot both
        # consume the same receipt, including across relay process restarts.
        os.unlink(filename, dir_fd=directory)
        return {'origin': {k: proof[k] for k in ('session_key', 'run_id', 'call_id')}, 'status': 'verified'}
    except FileNotFoundError:
        return denied('proof_missing_or_consumed')
    except (OSError, ValueError, TypeError):
        return denied('proof_unavailable')
    finally:
        if handle is not None:
            os.close(handle)
        if directory is not None:
            os.close(directory)


def resolve(root, name, arguments, nonce=None):
    return inspect_origin(root, name, arguments, nonce)['origin']
