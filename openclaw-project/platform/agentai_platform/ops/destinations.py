"""Backup destinations. Every destination reports whether it is off the host.

`LocalDir` is the first tier (protects against mistakes, corruption and bad releases; it does NOT
survive losing the server). `CommandDestination` wraps an external copier such as rclone or scp
without a shell, so a second copy off the host can be switched on by configuration alone.
"""
import os
from pathlib import Path
import re
import subprocess

NAME = re.compile(r'[A-Za-z0-9][A-Za-z0-9._-]{0,120}(/[A-Za-z0-9][A-Za-z0-9._-]{0,120}){0,2}')


class DestinationError(Exception): pass


def safe_name(name):
    if not isinstance(name, str) or not NAME.fullmatch(name) or '..' in name.split('/'):
        raise DestinationError('invalid object name')
    return name


class LocalDir:
    kind = 'local'

    def __init__(self, root, *, offsite=False):
        self.root, self.offsite = Path(root), offsite
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        info = self.root.lstat()
        if self.root.is_symlink() or info.st_uid != os.geteuid() or info.st_mode & 0o077:
            raise DestinationError('backup root must be private and owned by the backup user')

    def _path(self, name): return self.root / safe_name(name)

    def put(self, src, name):
        target = self._path(name)
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        tmp = target.with_name(target.name + '.partial')
        with open(src, 'rb') as source, open(tmp, 'xb') as out:
            while chunk := source.read(1 << 20): out.write(chunk)
            out.flush(); os.fsync(out.fileno())
        os.chmod(tmp, 0o600)
        os.replace(tmp, target)   # readers never see a half-written object
        return target.stat().st_size

    def size(self, name):
        try: return self._path(name).stat().st_size
        except FileNotFoundError: return None

    def read(self, name): return self._path(name).read_bytes()

    def list(self, prefix=''):
        out = []
        for path in sorted(self.root.rglob('*')):
            if path.is_file() and not path.name.endswith('.partial'):
                name = path.relative_to(self.root).as_posix()
                if name.startswith(prefix): out.append((name, path.stat().st_size, int(path.stat().st_mtime)))
        return out

    def remove(self, name):
        path = self._path(name)
        path.unlink(missing_ok=True)
        parent = path.parent
        while parent != self.root and parent.is_dir() and not any(parent.iterdir()):
            parent.rmdir(); parent = parent.parent


class CommandDestination:
    """argv templates with {src}, {name}, {prefix}; nothing is interpolated through a shell."""
    kind = 'command'

    def __init__(self, put, list_cmd, remove, *, run=None, offsite=True):
        for template in (put, list_cmd, remove):
            if not isinstance(template, list) or not template or not all(isinstance(t, str) for t in template):
                raise DestinationError('command templates must be argv lists')
        self.put_t, self.list_t, self.remove_t, self.offsite = put, list_cmd, remove, offsite
        self.run = run or (lambda argv: subprocess.run(argv, stdin=subprocess.DEVNULL, capture_output=True, timeout=7200))

    def _go(self, template, **values):
        argv = [t.format(**values) for t in template]
        done = self.run(argv)
        if done.returncode != 0: raise DestinationError('destination command failed')
        return done.stdout.decode('utf-8', 'replace') if done.stdout else ''

    def put(self, src, name):
        self._go(self.put_t, src=str(src), name=safe_name(name))
        return Path(src).stat().st_size

    def list(self, prefix=''):
        rows = []
        for line in self._go(self.list_t, prefix=prefix).splitlines():
            parts = line.split('\t')
            if len(parts) == 3 and NAME.fullmatch(parts[0]):
                rows.append((parts[0], int(parts[1]), int(parts[2])))
        return rows

    def size(self, name):
        for n, size, _ in self.list(name):
            if n == name: return size
        return None

    def remove(self, name): self._go(self.remove_t, name=safe_name(name))
