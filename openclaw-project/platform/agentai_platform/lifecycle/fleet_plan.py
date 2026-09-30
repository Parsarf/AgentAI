"""Fixed native command preparation for a future host-owned supervisor.

Not an execution adapter: no subprocess or socket access. Installed Fleet help
was inspected; result schemas, host registry and native drain proof still need
verification before any caller may execute these plans. Restore/upgrade need
separate backup/quarantine/token/rollback steps and are intentionally rejected.
"""
from dataclasses import dataclass
import re
from pathlib import Path
from agentai_platform.adapters import CapabilityUnavailable
from .types import Claim, Conflict

@dataclass(frozen=True)
class FleetBinding:
    account_id: str
    deployment_id: str
    tenant_ref: str
    profile_revision: str
    image: str
    port: int
    memory_bytes: int
    cpu_millis: int
    pid_limit: int
    archive_limit_bytes: int
    backup_root: Path

    def __post_init__(self):
        if not re.fullmatch(r'aa-[a-f0-9]{32}',self.tenant_ref): raise ValueError('invalid server tenant binding')
        if not re.fullmatch(r'ghcr.io/openclaw/openclaw@sha256:[a-f0-9]{64}',self.image): raise ValueError('image must be digest pinned')
        for value in [self.port,self.memory_bytes,self.cpu_millis,self.pid_limit,self.archive_limit_bytes]:
            if type(value) is not int or value<1: raise ValueError('positive resource bound required')
        if not 19100<=self.port<=65535 or self.cpu_millis>2000: raise ValueError('invalid trial port/CPU bound')
        if not self.backup_root.is_absolute(): raise ValueError('private backup root required')

class FleetPlanner:
    def __init__(self, bindings):
        # Loaded from host-owned custody, never the app's mutable deployment DB.
        self.bindings=dict(bindings)
    def command(self, claim: Claim):
        binding=self.bindings.get(claim.account_id)
        if not binding or (binding.deployment_id,binding.tenant_ref,binding.profile_revision)!=(claim.deployment_id,claim.tenant_ref,claim.target_profile):
            raise Conflict('host binding mismatch')
        base=('openclaw','fleet');tenant=binding.tenant_ref
        if claim.kind=='create':
            return base+('create',tenant,'--image',binding.image,'--runtime','docker',
                '--port',str(binding.port),'--memory',str(binding.memory_bytes),
                '--cpus',format(binding.cpu_millis/1000,'.3f'),'--pids-limit',str(binding.pid_limit),
                '--network','bridge','--no-start','--json')
        if claim.kind in {'start','stop'}:return base+(claim.kind,tenant)
        if claim.kind=='backup':
            if not re.fullmatch(r'[a-f0-9]{32}',claim.operation_id):raise Conflict('invalid backup identity')
            return base+('backup',tenant,'--out',str(binding.backup_root/(claim.operation_id+'.tgz')),
                         '--max-bytes',str(binding.archive_limit_bytes),'--json')
        if claim.kind=='delete':return base+('rm',tenant) # no force or purge: keep private durable data
        raise CapabilityUnavailable('native upgrade/restore orchestration not verified')
