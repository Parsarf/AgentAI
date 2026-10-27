"""Host-side helpers for quarantined restore, pinned upgrade and retention purge.

Fleet's own restore refuses to put one tenant's archive into another tenant slug
and swaps the whole data directory (impossible on a capped volume mounted
there), both observed 2026-10-11. The quarantined restore therefore uses the
host's own bounded extractor into a freshly created quarantine cell.
Nothing here executes customer input and nothing runs unless the supervisor's
driver calls it for a host-enrolled binding.
"""
import hashlib
import json
import os
from pathlib import Path
import posixpath
import re
import shutil
import tarfile

from .netpolicy import NetPolicy

TENANT = re.compile(r'aa-[a-f0-9]{32}')
ALLOWED_ROOTS = ('data', 'auth')


class ArchiveRefused(Exception): pass


def quarantine_ref(tenant):
    if type(tenant) is not str or not TENANT.fullmatch(tenant):
        raise ValueError('invalid tenant')
    return 'aa-' + hashlib.sha256(('quarantine:' + tenant).encode()).hexdigest()[:32]


def _safe_name(name):
    if name in ('manifest.json', ''):
        return True
    clean = posixpath.normpath(name)
    if clean.startswith('/') or clean.startswith('..') or '\x00' in name or '\\' in name:
        return False
    return clean.split('/')[0] in ALLOWED_ROOTS


def extract_archive(archive, data_dir, auth_dir, source_tenant, *, max_bytes, uid, gid, member_limit=200000,
                    replace_skeleton=False):
    """Bounded, validated extraction of a Fleet backup into freshly created quarantine dirs.

    Fleet's native restore swaps the whole data directory, which a capped volume
    mounted at that path forbids; and it refuses another tenant's archive. So the
    host extracts itself: manifest must name the source tenant, only regular
    files and directories under data/ or auth/ are written, nothing is followed
    or overwritten, destinations must be empty, and every entry is owned by the
    cell's fixed runtime identity.
    """
    archive, data_dir, auth_dir = Path(archive), Path(data_dir), Path(auth_dir)
    info = archive.lstat()
    if not archive.is_file() or archive.is_symlink() or info.st_nlink != 1 or not 1 <= info.st_size <= max_bytes:
        raise ArchiveRefused('archive is not a bounded regular file')
    for root in (data_dir, auth_dir):
        if root.is_symlink() or not root.is_dir():
            raise ArchiveRefused('destination must be a real directory')
        existing = [e for e in root.iterdir() if e.name != 'lost+found']
        if existing and not replace_skeleton:
            raise ArchiveRefused('destination must be an empty directory')
    if replace_skeleton:
        # Only for a cell the host created seconds ago: remove Fleet's placeholder files.
        for root in (data_dir, auth_dir):
            for entry in root.iterdir():
                if entry.name == 'lost+found':
                    continue
                if entry.is_dir() and not entry.is_symlink():
                    shutil.rmtree(entry)
                else:
                    entry.unlink()
    total = count = 0
    destinations = {'data': data_dir, 'auth': auth_dir}
    with tarfile.open(archive, 'r:gz') as source:
        saw_manifest = False
        for member in source:
            count += 1
            if count > member_limit:
                raise ArchiveRefused('archive has too many members')
            if not _safe_name(member.name) or not (member.isreg() or member.isdir()):
                raise ArchiveRefused('archive contains an unsafe member')
            total += member.size
            if total > max_bytes * 8:
                raise ArchiveRefused('archive expands beyond the bound')
            if member.name == 'manifest.json':
                manifest = json.loads(source.extractfile(member).read(65536))
                if manifest.get('tenant') != source_tenant or manifest.get('kind') != 'openclaw-fleet-cell-backup':
                    raise ArchiveRefused('archive does not belong to this tenant')
                saw_manifest = True
                continue
            if not saw_manifest:
                raise ArchiveRefused('manifest must come first')
            parts = posixpath.normpath(member.name).split('/')
            if len(parts) == 1:
                continue  # the data/ and auth/ roots themselves already exist
            target = destinations[parts[0]].joinpath(*parts[1:])
            if member.isdir():
                target.mkdir(mode=0o700, parents=True, exist_ok=True)
                os.chown(target, uid, gid)
                os.chmod(target, (member.mode & 0o777) | 0o700)
                continue
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, 'wb') as out:
                shutil.copyfileobj(source.extractfile(member), out)
            os.chown(target, uid, gid)
            os.chmod(target, member.mode & 0o777 or 0o600)
        if not saw_manifest:
            raise ArchiveRefused('archive has no manifest')
    return count


class HostIsolation:
    """Maintains the quarantined-subnet set in the cell firewall (atomic reload)."""

    def __init__(self, state_file, ruleset_file, base_policy, run):
        self.state_file, self.ruleset_file = Path(state_file), Path(ruleset_file)
        self.base, self.run = base_policy, run

    def _load(self):
        try:
            return sorted(json.loads(self.state_file.read_text()))
        except FileNotFoundError:
            return []

    def _apply(self, subnets):
        policy = NetPolicy(self.base.cell_pool, self.base.bridge_gateway,
                           self.base.model_proxy_port, tuple(subnets), self.base.tool_relay_port)
        tmp = self.ruleset_file.with_suffix('.new')
        tmp.write_text(policy.ruleset())
        code, _ = self.run(['nft', '-c', '-f', str(tmp)])
        if code != 0:
            tmp.unlink(); raise RuntimeError('firewall ruleset failed validation')
        code, _ = self.run(['nft', '-f', str(tmp)])
        if code != 0:
            tmp.unlink(); raise RuntimeError('firewall reload failed')
        os.replace(tmp, self.ruleset_file)
        self.state_file.write_text(json.dumps(subnets))

    def subnet_of(self, tenant):
        code, out = self.run(['docker', 'network', 'inspect', f'openclaw-cell-{tenant}-net',
                              '--format', '{{(index .IPAM.Config 0).Subnet}}'])
        subnet = out.strip()
        if code != 0 or not re.fullmatch(r'\d{1,3}(\.\d{1,3}){3}/\d{1,2}', subnet):
            raise RuntimeError('cell network not found')
        return subnet

    def quarantine(self, tenant):
        subnet = self.subnet_of(tenant)
        current = self._load()
        if subnet not in current:
            self._apply(sorted(current + [subnet]))
        return subnet

    def release(self, tenant):
        subnet = self.subnet_of(tenant)
        self._apply([s for s in self._load() if s != subnet])

    def is_quarantined(self, tenant):
        return self.subnet_of(tenant) in self._load()
