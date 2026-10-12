"""Race-safe private file storage for customer artifacts and uploads.

Root-relative access only. Every path component is validated, intermediate
directories are opened with O_DIRECTORY|O_NOFOLLOW, and the leaf with
O_NOFOLLOW, closing the intermediate-symlink race from plans/phase-8b.md:
a symlink swapped in after validation still fails to open. Version ids and
storage refs are database facts, never passed in from clients.
"""
from __future__ import annotations
import os
from pathlib import Path

COMPONENT_LIMIT = 128


def validate_component(part: str) -> str:
    if not isinstance(part, str) or not part or len(part) > COMPONENT_LIMIT:
        raise ValueError('invalid path component')
    if part in {'.', '..'} or '/' in part or '\\' in part or '\x00' in part:
        raise ValueError('invalid path component')
    if part.startswith('.'):
        raise ValueError('invalid path component')
    for ch in part:
        if not (ch.isascii() and (ch.isalnum() or ch in '-_.')):
            raise ValueError('invalid path component')
    return part


class RootStore:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        if self.root.is_symlink() or self.root.stat().st_mode & 0o077:
            raise ValueError('storage root must be a private direct directory (0700)')

    def _open_chain(self, parts, *, create_dirs=False, flags=0):
        """Open the leaf under root, following only real directories."""
        parts = [validate_component(p) for p in parts]
        dir_fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            for part in parts[:-1]:
                try:
                    next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=dir_fd)
                except FileNotFoundError:
                    if not create_dirs:
                        raise
                    os.mkdir(part, 0o700, dir_fd=dir_fd)
                    next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=dir_fd)
                os.close(dir_fd)
                dir_fd = next_fd
            return os.open(parts[-1], flags | os.O_NOFOLLOW, dir_fd=dir_fd)
        finally:
            os.close(dir_fd)

    def write_private(self, parts, data: bytes):
        fd = self._open_chain(parts, create_dirs=True,
                              flags=os.O_WRONLY | os.O_CREAT | os.O_EXCL)
        try:
            os.write(fd, data)
            os.fchmod(fd, 0o600)
        finally:
            os.close(fd)

    def read_private(self, parts, *, max_bytes: int | None = None) -> bytes:
        fd = self._open_chain(parts, flags=os.O_RDONLY)
        try:
            if max_bytes is None:
                chunks = []
                while True:
                    chunk = os.read(fd, 1 << 20)
                    if not chunk:
                        break
                    chunks.append(chunk)
                return b''.join(chunks)
            data = os.read(fd, max_bytes + 1)
            if len(data) > max_bytes:
                raise ValueError('content exceeds bound')
            return data
        finally:
            os.close(fd)

    def delete(self, parts):
        fd = self._open_chain(parts[:-1], flags=os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.unlink(parts[-1], dir_fd=fd)
        except FileNotFoundError:
            pass
        finally:
            os.close(fd)

    def size(self, parts) -> int:
        fd = self._open_chain(parts, flags=os.O_RDONLY)
        try:
            return os.fstat(fd).st_size
        finally:
            os.close(fd)
