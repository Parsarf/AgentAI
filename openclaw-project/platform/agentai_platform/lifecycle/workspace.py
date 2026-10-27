"""Collect the files an assistant wrote during a task from its own workspace (host side, read-only).

Runs inside the root cell bridge but treats the workspace as hostile: every path component is opened with O_NOFOLLOW
from a directory descriptor (no symlink or mount tricks), only regular files with an allowlisted extension are read,
and counts, depth and sizes are bounded. Nothing is executed and nothing outside the one workspace is reachable.
"""
from __future__ import annotations
import os
import re
import stat

ALLOWED_EXT = {'.txt', '.md', '.csv', '.json', '.py', '.js', '.ts', '.tsx', '.jsx', '.html', '.css', '.sql', '.pdf', '.png', '.jpg', '.jpeg'}
SKIP_DIRS = {'node_modules', '.git', '__pycache__', '.venv', 'venv', '.cache', '.npm', 'dist', 'build', 'memory'}
# The runtime seeds these into a fresh workspace and keeps them itself (persona, first-run ritual, memory): they are its files, not something the customer asked for.
SKIP_NAMES = {'AGENTS.md', 'SOUL.md', 'USER.md', 'IDENTITY.md', 'BOOTSTRAP.md', 'TOOLS.md', 'HEARTBEAT.md', 'MEMORY.md'}
MAX_FILES, MAX_FILE_BYTES, MAX_TOTAL_BYTES, MAX_DEPTH = 10, 2 * 1024 * 1024, 8 * 1024 * 1024, 4
NAME_OK = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._ -]{0,100}$')


def collect(workspace, since):
    """-> [(relative path using '/', bytes)] of regular allowlisted files modified at or after `since` (epoch seconds)."""
    out, total = [], 0
    try:
        root = os.open(str(workspace), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except OSError:
        return out
    try:
        stack = [(root, '', 0)]
        opened = []
        while stack and len(out) < MAX_FILES:
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
                if not stat.S_ISREG(st.st_mode) or st.st_mtime < since or st.st_size == 0 or st.st_size > MAX_FILE_BYTES:
                    continue
                if name in SKIP_NAMES or os.path.splitext(name)[1].lower() not in ALLOWED_EXT or total + st.st_size > MAX_TOTAL_BYTES:
                    continue
                try:
                    handle = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
                except OSError:
                    continue
                try:
                    data = os.read(handle, MAX_FILE_BYTES + 1)
                finally:
                    os.close(handle)
                if not data or len(data) > MAX_FILE_BYTES:
                    continue
                total += len(data)
                out.append((prefix + name, data))
                if len(out) >= MAX_FILES:
                    break
        for child in opened:
            os.close(child)
    finally:
        os.close(root)
    return out
