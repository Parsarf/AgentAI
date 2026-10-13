"""Hard per-tenant disk caps using fixed-size loop-mounted ext4 images.

The host root filesystem has no project-quota support, so a filesystem of the
exact capped size is mounted at the cell's state path. A tenant that fills it
gets ENOSPC without touching the host or any other tenant (verified live
2026-10-11: a 300 MB volume stopped a 400 MB write at its cap while both cells
and the host stayed healthy). All commands are fixed argv lists; tenant names
and sizes are validated and nothing comes from a customer request.
"""
from dataclasses import dataclass
from pathlib import Path
import re
import subprocess

TENANT = re.compile(r'aa-[a-f0-9]{32}')
MIN_BYTES, MAX_BYTES = 64 * 1024**2, 64 * 1024**3


class VolumeError(Exception): pass


@dataclass(frozen=True)
class VolumeSpec:
    tenant: str
    size_bytes: int

    def __post_init__(self):
        if type(self.tenant) is not str or not TENANT.fullmatch(self.tenant):
            raise ValueError('invalid tenant')
        if type(self.size_bytes) is not int or isinstance(self.size_bytes, bool) \
                or not MIN_BYTES <= self.size_bytes <= MAX_BYTES:
            raise ValueError('invalid volume size')


def default_run(argv, env=None, input_text=None):
    import os
    done = subprocess.run(argv, stdin=subprocess.DEVNULL if input_text is None else None, input=None if input_text is None else input_text.encode(),
                          capture_output=True, timeout=180, env={**os.environ, **env} if env else None)
    return done.returncode, done.stdout.decode('utf-8', 'replace')


class VolumeManager:
    """Creates, mounts, unmounts and purges capped state volumes for one host."""

    def __init__(self, image_root, state_root, run=default_run):
        self.image_root, self.state_root, self.run = Path(image_root), Path(state_root), run
        if not self.image_root.is_absolute() or not self.state_root.is_absolute():
            raise ValueError('absolute roots required')

    def image(self, tenant):
        VolumeSpec(tenant, MIN_BYTES)
        return self.image_root / f'{tenant}.img'

    def auth_dir(self, tenant):
        """Fleet keeps per-cell auth secrets beside the cell state directory."""
        VolumeSpec(tenant, MIN_BYTES)
        return self.state_root.parent / 'auth-profile-secrets' / tenant

    def mountpoint(self, tenant):
        VolumeSpec(tenant, MIN_BYTES)
        return self.state_root / tenant

    def _run(self, argv, what):
        code, out = self.run(argv)
        if code != 0:
            raise VolumeError(f'{what} failed')
        return out

    def is_mounted(self, tenant):
        # findmnt PATH exits non-zero unless PATH is itself a mountpoint.
        code, out = self.run(['findmnt', '-n', '-o', 'TARGET', str(self.mountpoint(tenant))])
        return code == 0 and out.strip() == str(self.mountpoint(tenant))

    def prepare(self, spec):
        """Idempotent: the same tenant always converges on one image of one size."""
        image, mount = self.image(spec.tenant), self.mountpoint(spec.tenant)
        self.image_root.mkdir(mode=0o700, parents=True, exist_ok=True)
        if image.exists():
            if image.lstat().st_size != spec.size_bytes:
                raise VolumeError('existing volume has a different size; resize is a separate operation')
        else:
            self._run(['truncate', '-s', str(spec.size_bytes), str(image)], 'allocate')
            self._run(['mkfs.ext4', '-q', '-m', '0', '-L', spec.tenant[3:15], str(image)], 'format')
        mount.mkdir(mode=0o700, parents=True, exist_ok=True)
        if not self.is_mounted(spec.tenant):
            self._run(['mount', '-o', 'loop,nodev,nosuid', str(image), str(mount)], 'mount')
        return mount

    def release(self, tenant):
        """Unmount only; data stays until the retention purge."""
        if self.is_mounted(tenant):
            self._run(['umount', str(self.mountpoint(tenant))], 'unmount')

    def purge(self, tenant):
        """Retention purge of one exact tenant: must already be unmounted."""
        if self.is_mounted(tenant):
            raise VolumeError('refusing to purge a mounted volume')
        image = self.image(tenant)
        if image.exists() and not image.is_symlink():
            image.unlink()
        mount = self.mountpoint(tenant)
        if mount.is_dir() and not mount.is_symlink() and not any(mount.iterdir()):
            mount.rmdir()
