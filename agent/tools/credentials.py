"""Model-facing surface over the per-user vault — deliberately tiny.

The ONLY tool the model can call is ``list_available_accounts`` (site names,
own user). No tool exists through which a secret VALUE could reach the
model's context, so there is nothing to approve and nothing to leak.

Everything secret-shaped is internal: ``get_credential_for_user`` is used by
tools that ACT on secrets (browser login now; payment providers in Phase 6)
and returns a ``SecretValue`` whose str/repr are "[REDACTED]" — the raw value
is reachable only via ``.reveal()`` at the instant of use.

External vaults: ``users.vault_mode`` selects the backend. Only "builtin"
ships; "bitwarden" is a working seam that raises a clear not-available error
until an operator enables it.
"""

from __future__ import annotations

import json

from core.secrets_vault import SecretValue, VaultBackend, backend_for
from tools.base import tool

__all__ = ["list_available_accounts", "get_credential_for_user", "VaultBackend"]


@tool(
    "list_available_accounts",
    "List the site names this user has stored credentials for (names only — "
    "values can never be read back through any tool). Use with browser_login.",
    risk="safe",
)
async def list_available_accounts() -> list[str]:
    """Site names only, scoped to the acting user."""
    from tools.base import current_user_id as _uid  # explicit: tenancy from context

    user = await _current_user()
    backend = backend_for(user)
    return await backend.list(_uid.get() or "")


async def get_credential_for_user(user_id: str, site: str) -> SecretValue | None:
    """Internal: decrypt the user's own credential for a tool's use.

    NOT exported to the model. Returns a SecretValue; call ``.reveal()`` only
    at the instant of use (form fill, provider API call).
    """
    user = await _current_user(user_id)
    backend = backend_for(user)
    return await backend.get(str(user_id), site)


def secret_password(value: SecretValue) -> str:
    """The password half of a structured credential (or the raw value when
    the stored secret is a plain string). Used ONLY at fill time."""
    try:
        parsed = json.loads(value.reveal())
    except ValueError:
        return value.reveal()
    if isinstance(parsed, dict) and "password" in parsed:
        return str(parsed["password"])
    return value.reveal()


async def store_credential_for_user(user_id: str, site: str, value: str) -> None:
    """Internal: web settings route writes through this (users own their
    vault; the agent never writes credentials for them)."""
    user = await _current_user(user_id)
    backend = backend_for(user)
    await backend.store(str(user_id), site, value)


async def _current_user(user_id: str | None = None):
    """Load the user row for backend selection. Tenancy: ids come from task
    context (tools) or an authenticated session (web), never from the model."""
    from core import db

    if user_id is None:
        from tools.base import current_user_id

        user_id = current_user_id.get() or ""
    from uuid import UUID

    return await db.get_user(UUID(str(user_id)))
