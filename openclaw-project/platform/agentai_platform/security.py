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
    role: str                    # what kind of identity this is ('customer'); the person's ROLE in their organization is `org_role`
    organization_id: str = ''    # filled in by whoever verified the request, when known; '' = look it up
    org_role: str = ''           # owner | admin | member | viewer; '' = look it up at the check (permissions.member_role)

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


def allowed(principal: Principal, action: str, resource=None, *, con=None) -> bool:
    """THE permission check (roadmap #12): may this person do this action? Every route wrapper and the tool relay ask here; nothing else decides by role.

    The role is read from the database at the moment of the check when a connection is given (so a role change or a removal takes effect on the next request), else from the
    principal as it was verified. `resource` is the thing acted on; it is checked by the layer that owns it (a connection's grants: connectors.py), not by role."""
    from . import permissions
    if principal is None or principal.role != 'customer' or not principal.account_id or not principal.actor_id:
        return False
    role = permissions.member_role(con, principal.account_id, principal.actor_id) if con is not None else (principal.org_role or None)
    return role is not None and permissions.role_allows(role, action)


def require(principal: Principal, action: str, resource=None, *, con=None) -> None:
    """`allowed`, or NotFound when the person is not an active member at all (one answer for "not yours" and "does not exist"), or NotPermitted when their role lacks the action."""
    from . import permissions
    if principal is None or principal.role != 'customer' or not principal.account_id or not principal.actor_id:
        raise Forbidden('unavailable')
    role = permissions.member_role(con, principal.account_id, principal.actor_id) if con is not None else (principal.org_role or None)
    if role is None:
        raise NotFound('unavailable')
    if not permissions.role_allows(role, action):
        raise permissions.NotPermitted(action)


def request_id() -> str:
    # Server-generated: client request IDs are not trusted or echoed into logs.
    return str(uuid.uuid4())


def log_request(service: str, rid: str, status: int, route: str) -> None:
    # Allowlisted metadata only: never headers, body, query, cookie, exception or URL.
    safe_route = route if route in {"health", "readiness", "projects", "operation", "unknown"} else "unknown"
    logging.getLogger("agentai").info(json.dumps({"event":"http_request","service":service,"request_id":rid,"status":status,"route":safe_route},separators=(",",":")))
