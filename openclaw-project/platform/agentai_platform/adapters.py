from __future__ import annotations
from dataclasses import dataclass
from typing import Protocol

class CapabilityUnavailable(Exception): pass

@dataclass(frozen=True)
class GatewayCapabilities:
    runtime_version: str
    protocol_version: int
    send: bool
    history: bool
    events: bool
    abort: bool
    live_probed: bool
    wait: bool = False       # agent.wait: the runtime says when a run has ended (no guessing from the transcript)
    goals: bool = False      # sessions.describe + sessions.goal.*: durable per-session objectives

    def require(self, operation: str):
        if operation not in {"send","history","events","abort","wait","goals"} or not self.live_probed or self.protocol_version != 4 or not getattr(self,operation):
            raise CapabilityUnavailable("installed capability not verified")

class DisabledGateway:
    def capabilities(self): return GatewayCapabilities("unverified",4,False,False,False,False,False)
    def send(self,*args): raise CapabilityUnavailable("customer execution disabled")
    history = send
    abort = send

class LifecycleDriver(Protocol):
    def execute(self, account_id: str, deployment_id: str, operation_id: str, kind: str, generation: int): ...

class DisabledLifecycle:
    def execute(self,*args): raise CapabilityUnavailable("provisioning disabled")
