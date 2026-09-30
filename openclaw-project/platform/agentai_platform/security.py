from __future__ import annotations
from dataclasses import dataclass
import json
import logging
import uuid
from typing import Protocol

@dataclass(frozen=True)
class Principal:
    """Constructed only after identity verification; never from client headers."""
    account_id: str
    actor_id: str
    role: str

class IdentityVerifier(Protocol):
    def verify(self, cookie: str | None) -> Principal | None: ...

class DenyIdentity:
    def verify(self, cookie: str | None) -> None:
        return None

class NotFound(Exception): pass
class Forbidden(Exception): pass


def require_customer(principal: Principal) -> None:
    if principal.role != "customer" or not principal.account_id or not principal.actor_id:
        raise Forbidden("unavailable")


def request_id() -> str:
    # Server-generated: client request IDs are not trusted or echoed into logs.
    return str(uuid.uuid4())


def log_request(service: str, rid: str, status: int, route: str) -> None:
    # Allowlisted metadata only: never headers, body, query, cookie, exception or URL.
    safe_route = route if route in {"health", "readiness", "projects", "operation", "unknown"} else "unknown"
    logging.getLogger("agentai").info(json.dumps({"event":"http_request","service":service,"request_id":rid,"status":status,"route":safe_route},separators=(",",":")))
