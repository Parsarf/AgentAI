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

    def require(self, operation: str):
        if operation not in {"send","history","events","abort"} or not self.live_probed or self.protocol_version != 3 or not getattr(self,operation):
            raise CapabilityUnavailable("installed capability not verified")

class GatewayClient(Protocol):
    # Must bind deployment/account internally, not receive a client-provided URL/key.
    def capabilities(self) -> GatewayCapabilities: ...
    def send(self, conversation_id: str, task_id: str, operation_id: str, message: str): ...
    def history(self, conversation_id: str, cursor: str | None): ...
    def abort(self, task_id: str, operation_id: str): ...

class DisabledGateway:
    def capabilities(self): return GatewayCapabilities("unverified",3,False,False,False,False,False)
    def send(self,*args): raise CapabilityUnavailable("customer execution disabled")
    history = send
    abort = send

class LifecycleDriver(Protocol):
    def execute(self, account_id: str, deployment_id: str, operation_id: str, kind: str, generation: int): ...

class DisabledLifecycle:
    def execute(self,*args): raise CapabilityUnavailable("provisioning disabled")
