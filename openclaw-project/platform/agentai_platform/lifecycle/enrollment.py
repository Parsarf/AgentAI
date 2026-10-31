"""Host-owned policy for automatic enrollment of newly approved cells.

Only identities come from a validated create claim. Images, storage roots,
resources, profiles and port allocation remain under host custody.
"""
from dataclasses import asdict
import json
import os
from pathlib import Path
import re
import stat

from . import profiles
from .fleet_plan import FleetBinding
from .types import Conflict


class EnrollmentPolicy:
    def __init__(self, config, *, owner_uid=None):
        if type(config) is not dict or set(config) != {'image', 'profile', 'backup_root', 'max_cells'}:
            raise ValueError('invalid enrollment policy')
        if type(config['profile']) is not str or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', config['profile']):
            raise ValueError('invalid enrollment profile')
        if type(config['backup_root']) is not str or not Path(config['backup_root']).is_absolute() or '..' in Path(config['backup_root']).parts:
            raise ValueError('absolute backup root required')
        if type(config['max_cells']) is not int or not 1 <= config['max_cells'] <= 39:
            raise ValueError('enrollment limit must fit the reserved port range')
        self.config = dict(config)
        self.owner_uid = os.geteuid() if owner_uid is None else owner_uid
        # Validate the image and the complete fixed resource profile at startup.
        self._binding('validation', '0' * 32, 'aa-' + '0' * 32, 19101)

    @classmethod
    def load(cls, path, *, owner_uid=0):
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd) as source:
            info = os.fstat(source.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_uid != owner_uid or info.st_mode & 0o022 or info.st_nlink != 1:
                raise PermissionError('enrollment policy must be host-owned without group/world writes or links')
            policy = cls(json.load(source), owner_uid=owner_uid)
            policy._private_directory(Path(policy.config['backup_root']))
            return policy

    def _private_directory(self, path):
        info = path.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != self.owner_uid or info.st_mode & 0o077:
            raise PermissionError('enrollment backup directories must be private and host-owned')

    def _binding(self, account, deployment, tenant, port):
        return FleetBinding(account, deployment, tenant, self.config['profile'], self.config['image'],
                            port, profiles.CELL_MEMORY, profiles.CELL_MILLIS, profiles.CELL_PIDS,
                            2 * 1024**3, Path(self.config['backup_root']) / account,
                            quarantine_port=port + 50, volume_bytes=profiles.VOLUME_BYTES)

    def enroll(self, con, claim):
        """Called under the supervisor's process lock and custody transaction.

        Existing bindings are never replaced. Only an empty private backup
        directory is prepared here; cell creation uses the normal journal.
        """
        from .supervisor import SupervisorBusy
        if claim.kind != 'create' or claim.generation != 1 or claim.target_profile != self.config['profile']:
            raise Conflict('create claim does not match host enrollment policy')
        rows = con.execute('SELECT account,deployment,tenant,port,spec FROM bindings').fetchall()
        if len(rows) >= self.config['max_cells']:
            raise SupervisorBusy('host enrollment capacity')
        used = set()
        for row in rows:
            if row['deployment'] == claim.deployment_id or row['tenant'] == claim.tenant_ref:
                raise Conflict('cell identity already enrolled')
            used.add(row['port'])
            quarantine = json.loads(row['spec']).get('quarantine_port')
            if quarantine is not None:
                used.add(quarantine)
        port = next((p for p in range(19101, 19140) if p not in used and p + 50 not in used), None)
        if port is None:
            raise SupervisorBusy('host enrollment ports exhausted')
        binding = self._binding(claim.account_id, claim.deployment_id, claim.tenant_ref, port)
        self._private_directory(Path(self.config['backup_root']))
        binding.backup_root.mkdir(mode=0o700, exist_ok=True)
        self._private_directory(binding.backup_root)
        spec = asdict(binding)
        spec['backup_root'] = str(binding.backup_root)
        con.execute('INSERT INTO bindings(account,deployment,tenant,port,spec,generation) VALUES (?,?,?,?,?,?)',
                    (binding.account_id, binding.deployment_id, binding.tenant_ref, binding.port,
                     json.dumps(spec, sort_keys=True), claim.generation))
