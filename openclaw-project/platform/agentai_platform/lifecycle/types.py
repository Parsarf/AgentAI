from dataclasses import dataclass
from typing import Protocol
from agentai_platform.adapters import CapabilityUnavailable

KINDS = frozenset({'create', 'start', 'stop', 'upgrade', 'backup', 'restore', 'delete'})

class Conflict(Exception): pass
class CapacityWait(Exception): pass

@dataclass(frozen=True)
class Claim:
    account_id: str
    deployment_id: str
    tenant_ref: str
    operation_id: str
    kind: str
    generation: int
    target_profile: str
    backup_ref: str | None
    fence: int
    owner: str

@dataclass(frozen=True)
class Receipt:
    # Only a trusted driver constructs receipts. Never decoded from a client request.
    account_id: str
    deployment_id: str
    operation_id: str
    generation: int
    state: str
    applied: bool
    quiesced: bool
    backup_ref: str | None = None

class Driver(Protocol):
    def check(self, kind: str) -> None: ...
    def execute(self, claim: Claim) -> Receipt: ...
    def reconcile(self, claim: Claim) -> Receipt | None: ...

class DisabledDriver:
    def check(self, kind): raise CapabilityUnavailable('native lifecycle not verified')
    def execute(self, claim): self.check(claim.kind)
    def reconcile(self, claim): self.check(claim.kind)
