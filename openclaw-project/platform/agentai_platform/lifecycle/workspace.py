"""Read the files an assistant wrote in its own workspace (host side, read-only).

Runs inside the root cell bridge but treats the workspace as hostile: every path component is opened with O_NOFOLLOW
from a directory descriptor (no symlink or mount tricks), only regular files are read, and counts, depth and sizes are
bounded. Nothing is executed and nothing outside the one workspace is reachable.

Any file format may be delivered. The only content never handed to a customer is a native program or installer: an
assistant cannot write one itself, so one in the workspace was fetched from somewhere else.

    scan(workspace, since)        what is there (no content), and what was left out and why
    read(workspace, path, ...)    one bounded slice of one file
    collect(workspace, since)     both at once, for small results
"""
from __future__ import annotations
import os
import re
import stat

# `skills` and `lumina-ui` are Lumina's own instructions and component descriptions (lifecycle/cell_config.py write_rules), not something the customer asked for.
SKIP_DIRS = {'node_modules', '.git', '__pycache__', '.venv', 'venv', '.cache', '.npm', 'dist', 'build', 'memory', 'tmp', 'scratch', 'skills', 'lumina-ui'}
# The runtime seeds these into a fresh workspace and keeps them itself (persona, first-run ritual, memory): they are its files, not something the customer asked for.
SKIP_NAMES = {'AGENTS.md', 'SOUL.md', 'USER.md', 'IDENTITY.md', 'BOOTSTRAP.md', 'TOOLS.md', 'HEARTBEAT.md', 'MEMORY.md'}
# Leftovers of doing the work, never the work itself.
SKIP_EXT = {'.pyc', '.pyo', '.log', '.tmp', '.temp', '.lock', '.map', '.swp', '.part', '.crdownload'}
# Native programs and installers (see the module note).
PROGRAM_EXT = {'.exe', '.dll', '.msi', '.scr', '.com', '.dmg', '.pkg', '.apk', '.app', '.deb', '.rpm', '.lnk', '.so', '.dylib'}
PROGRAM_MAGIC = (b'MZ', b'\x7fELF', b'\xfe\xed\xfa\xce', b'\xfe\xed\xfa\xcf', b'\xce\xfa\xed\xfe', b'\xcf\xfa\xed\xfe', b'\xca\xfe\xba\xbe')
MAX_FILES, MAX_FILE_BYTES, MAX_TOTAL_BYTES, MAX_DEPTH = 50, 50 * 1024 * 1024, 200 * 1024 * 1024, 6
MAX_SKIPPED = 20
MAX_CHUNK = 2 * 1024 * 1024
MAX_PATH = 240
NAME_OK = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._ ()\[\]+,&@-]{0,100}$')


def is_program(name: str, head: bytes) -> bool:
    """A native program or installer, by name or by its first bytes."""
    return os.path.splitext(name)[1].lower() in PROGRAM_EXT or any(head.startswith(magic) for magic in PROGRAM_MAGIC)


def safe_path(path) -> list[str] | None:
    """The components of a workspace-relative path, or None when it is not one we will open."""
    if not isinstance(path, str) or not 0 < len(path) <= MAX_PATH or path.startswith('/') or '\\' in path or '\x00' in path:
        return None
    parts = path.split('/')
    if len(parts) > MAX_DEPTH or any(not NAME_OK.fullmatch(p) or p in SKIP_DIRS for p in parts[:-1]):
        return None
    if not NAME_OK.fullmatch(parts[-1]) or parts[-1] in SKIP_NAMES:
        return None
    return parts


def _open(workspace, parts):
    """A descriptor for one regular file under the workspace, following no symlink at any level; None when it is not there."""
    try:
        fd = os.open(str(workspace), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except OSError:
        return None
    try:
        for part in parts[:-1]:
            nxt = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = nxt
        handle = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
    except OSError:
        return None
    finally:
        os.close(fd)
    if not stat.S_ISREG(os.fstat(handle).st_mode):
        os.close(handle)
        return None
    return handle


def stat_file(workspace, path):
    """-> {'size', 'mtime'} of one deliverable file, or {'reason'} saying why it cannot be delivered."""
    parts = safe_path(path)
    if parts is None:
        return {'reason': 'not a file in the workspace'}
    handle = _open(workspace, parts)
    if handle is None:
        return {'reason': 'not found'}
    try:
        info = os.fstat(handle)
        if info.st_size == 0:
            return {'reason': 'empty'}
        if info.st_size > MAX_FILE_BYTES:
            return {'reason': 'larger than 50 MB'}
        if is_program(parts[-1], os.pread(handle, 8, 0)):
            return {'reason': 'programs and installers are not delivered'}
        return {'size': info.st_size, 'mtime': int(info.st_mtime)}
    finally:
        os.close(handle)


def read(workspace, path, offset=0, length=MAX_CHUNK) -> bytes | None:
    """One slice of one file (at most MAX_CHUNK bytes); None when the file may not be read."""
    parts = safe_path(path)
    if parts is None or type(offset) is not int or type(length) is not int or offset < 0 or not 0 < length <= MAX_CHUNK:
        return None
    handle = _open(workspace, parts)
    if handle is None:
        return None
    try:
        if os.fstat(handle).st_size > MAX_FILE_BYTES or (offset == 0 and is_program(parts[-1], os.pread(handle, 8, 0))):
            return None
        return os.pread(handle, length, offset)
    finally:
        os.close(handle)


def scan(workspace, since):
    """-> {'files': [{'path','size','mtime'}], 'skipped': [{'path','reason'}]} for regular files modified at or after `since` (epoch seconds).

    `skipped` names what the customer will NOT get although the assistant wrote it, so that can be said plainly."""
    files, skipped, total = [], [], 0

    def skip(path, reason):
        if len(skipped) < MAX_SKIPPED:
            skipped.append({'path': path, 'reason': reason})
    try:
        root = os.open(str(workspace), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except OSError:
        return {'files': files, 'skipped': skipped}
    opened = []
    try:
        stack = [(root, '', 0)]
        while stack:
            fd, prefix, depth = stack.pop()
            try:
                entries = sorted(os.scandir(fd), key=lambda e: e.name)
            except OSError:
                continue
            for entry in entries:
                name = entry.name
                if name.startswith('.') or not NAME_OK.fullmatch(name):
                    continue
                try:
                    st = entry.stat(follow_symlinks=False)
                except OSError:
                    continue
                if stat.S_ISDIR(st.st_mode):
                    if depth + 1 < MAX_DEPTH and name not in SKIP_DIRS:
                        try:
                            child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                        except OSError:
                            continue
                        opened.append(child)
                        stack.append((child, prefix + name + '/', depth + 1))
                    continue
                if not stat.S_ISREG(st.st_mode) or st.st_mtime < since or st.st_size == 0:
                    continue
                if name in SKIP_NAMES or os.path.splitext(name)[1].lower() in SKIP_EXT or len(prefix + name) > MAX_PATH:
                    continue
                path = prefix + name
                if st.st_size > MAX_FILE_BYTES:
                    skip(path, 'larger than 50 MB')
                    continue
                try:
                    handle = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
                except OSError:
                    continue
                try:
                    head = os.pread(handle, 8, 0)
                finally:
                    os.close(handle)
                if is_program(name, head):
                    skip(path, 'programs and installers are not delivered')
                elif len(files) >= MAX_FILES:
                    skip(path, 'more than 50 files in one task')
                elif total + st.st_size > MAX_TOTAL_BYTES:
                    skip(path, 'more than 200 MB in one task')
                else:
                    total += st.st_size
                    files.append({'path': path, 'size': st.st_size, 'mtime': int(st.st_mtime)})
    finally:
        for child in opened:
            os.close(child)
        os.close(root)
    return {'files': files, 'skipped': skipped}


def collect(workspace, since, *, max_total=8 * 1024 * 1024):
    """-> [(relative path using '/', bytes)]: scan and read in one go, for results small enough to travel in one reply."""
    out, total = [], 0
    for item in scan(workspace, since)['files']:
        if total + item['size'] > max_total:
            continue
        data, offset = b'', 0
        while offset < item['size']:
            chunk = read(workspace, item['path'], offset, MAX_CHUNK)
            if not chunk:
                break
            data += chunk
            offset += len(chunk)
        if data and len(data) == item['size']:
            total += len(data)
            out.append((item['path'], data))
    return out
