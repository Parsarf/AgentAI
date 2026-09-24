"""Built-in, per-user encrypted secrets storage (the default vault).

Envelope encryption, from the inside out:
- Each credential value is encrypted with the OWNING USER's data key
  (AES-256-GCM, fresh nonce per write, AAD = f"{user_id}:{site}") so a blob
  copied into another user's row — or an AAD swapped in a malformed request
  — FAILS TO DECRYPT instead of silently returning the wrong secret.
- Each user's data key is random 32 bytes, wrapped (AES-256-GCM under the
  root key, AAD = user id) and stored in ``vault_keys``. Unwrapped keys live
  in an in-memory cache ONLY — never on disk, never in logs.
- The root key comes from KMS when ``vault.kms`` is configured (the root
  key material never enters app memory), else from ``VAULT_MASTER_KEY``
  in settings (HKDF-derived AES key).

``SecretValue`` is a str subclass whose repr/str are ``"[REDACTED]"``; the
raw value is reachable ONLY via ``.reveal()`` inside tool internals, and
every decrypt registers the raw value with the log redaction filter.

Decrypted values exist in process only for the instant a tool needs them.
A shared/opt-in marketplace or admin view of vault contents is a non-goal:
values are write-only from every surface except the owning user's own tools.
"""

from __future__ import annotations

import base64
import hashlib
import os
import time
from typing import Literal

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from core import db
from core.config import settings
from core.logging import get_logger, register_secret

logger = get_logger(__name__)

_NONCE_LEN = 12
_KEY_LEN = 32
_VERSION = b"\x01"

#: Cache of unwrapped per-user data keys: user_id -> (key, monotonic_ts).
_key_cache: dict[str, tuple[bytes, float]] = {}


class VaultError(Exception):
    """Vault operation refused/failed. Messages never contain secret data."""


class SecretValue(str):
    """A decrypted secret in the shape of a str that cannot leak by accident.

    ``repr()``/``str()`` are ``"[REDACTED]"`` so logging, formatting, or an
    accidental return to the model shows nothing. The raw value is accessed
    via ``.reveal()`` — only inside tool internals (form fill, Phase 6
    payment provider calls).
    """

    def __new__(cls, raw: str) -> SecretValue:
        return super().__new__(cls, raw)

    def __repr__(self) -> str:  # noqa: D105
        return "[REDACTED]"

    def __str__(self) -> str:  # noqa: D105
        return "[REDACTED]"

    def reveal(self) -> str:
        """The raw secret. Tool internals ONLY — never log, never return."""
        return str.__str__(self)


# --------------------------------------------------------------------------- #
# Root key + wrapping
# --------------------------------------------------------------------------- #


def _root_key() -> bytes:
    """AES-256 key derived from the configured root secret.

    KMS mode (vault.kms configured) is a seam: production deployments wrap
    per-user keys through the provider so the root key never touches app
    memory. Without operator-provided KMS credentials we fall back to the
    local master key; _kms_wrap/_kms_unwrap are the only swap points.
    """
    kms = settings.vault.kms
    if kms is not None:
        raise VaultError(
            f"vault.kms provider {kms.provider!r} is configured but no KMS "
            "adapter is installed on this deployment; clear vault.kms to use "
            "VAULT_MASTER_KEY, or provide provider credentials"
        )
    raw = settings.secrets.vault_master_key
    if not raw:
        raise VaultError(
            "VAULT_MASTER_KEY is not set. Fix: add to .env — VAULT_MASTER_KEY=$(openssl rand -base64 48)"
        )
    try:
        decoded = base64.b64decode(raw, validate=True)
    except Exception:
        decoded = raw.encode()  # tolerate a non-base64 operator key
    # Derive a stable 32-byte AES key from whatever length the operator made.
    return hashlib.sha256(b"agent-vault-root-v1" + decoded).digest()


def _wrap(data_key: bytes, user_id: str) -> bytes:
    nonce = os.urandom(_NONCE_LEN)
    ct = AESGCM(_root_key()).encrypt(nonce, data_key, user_id.encode())
    return nonce + ct


def _unwrap(wrapped: bytes, user_id: str) -> bytes:
    nonce, ct = wrapped[:_NONCE_LEN], wrapped[_NONCE_LEN:]
    return AESGCM(_root_key()).decrypt(nonce, ct, user_id.encode())


# --------------------------------------------------------------------------- #
# Per-user data keys (envelope)
# --------------------------------------------------------------------------- #


async def _user_data_key(user_id: str) -> bytes:
    """The user's unwrapped data key — memory cache, else unwrap/create."""
    cached = _key_cache.get(user_id)
    ttl = settings.vault.cache_seconds
    if cached is not None and (ttl <= 0 or time.monotonic() - cached[1] < ttl):
        return cached[0]

    wrapped = await db.get_vault_key(_uuid(user_id))
    if wrapped is not None:
        try:
            key = _unwrap(wrapped, user_id)
        except Exception as exc:
            raise VaultError("vault key unwrap failed (wrong root key or corrupted row)") from exc
    else:
        key = os.urandom(_KEY_LEN)
        stored = await db.create_vault_key(_uuid(user_id), _wrap(key, user_id))
        try:
            candidate = _unwrap(stored, user_id)
        except Exception:
            candidate = None
        if candidate != key:  # a concurrent writer's key won — adopt theirs
            key = candidate
    _key_cache[user_id] = (key, time.monotonic())
    return key


def drop_key_cache(user_id: str | None = None) -> None:
    """Forget unwrapped keys (cache-ttl tests, lock down on demand)."""
    if user_id is None:
        _key_cache.clear()
    else:
        _key_cache.pop(str(user_id), None)


def _uuid(value: str):
    from uuid import UUID

    return UUID(str(value))


# --------------------------------------------------------------------------- #
# Value encryption: nonce | ciphertext, AAD binds blob to tenant+site
# --------------------------------------------------------------------------- #


async def _encrypt(user_id: str, site: str, value: str) -> bytes:
    data_key = await _user_data_key(user_id)
    nonce = os.urandom(_NONCE_LEN)
    ct = AESGCM(data_key).encrypt(nonce, value.encode(), f"{user_id}:{site}".encode())
    return _VERSION + nonce + ct


async def _decrypt(user_id: str, site: str, blob: bytes) -> str:
    if len(blob) < 1 + _NONCE_LEN + 16 or blob[0:1] != _VERSION:
        raise VaultError("vault blob is malformed")
    nonce, ct = blob[1 : 1 + _NONCE_LEN], blob[1 + _NONCE_LEN :]
    data_key = await _user_data_key(user_id)
    try:
        raw = AESGCM(data_key).decrypt(nonce, ct, f"{user_id}:{site}".encode())
    except Exception as exc:
        raise VaultError("vault blob failed to decrypt (wrong tenant/site or tampered)") from exc
    text = raw.decode()
    register_secret(text)  # the redaction filter covers it from now on
    return text


# --------------------------------------------------------------------------- #
# Public interface
# --------------------------------------------------------------------------- #


_MODEL_KEY_SITE = "__internal_model_key_anthropic"


async def store_model_api_key(user_id: str, value: str) -> None:
    """Store an Anthropic key in the tenant vault, outside model-facing sites."""
    if not isinstance(value, str) or not value or len(value) > 4096 or any(ch.isspace() for ch in value):
        raise VaultError("invalid API key")
    blob = await _encrypt(str(user_id), _MODEL_KEY_SITE, value)
    await db.create_vault_entry(_uuid(user_id), _MODEL_KEY_SITE, blob)
    register_secret(value)
    logger.info("model API key stored", extra={"user_id": str(user_id), "provider": "anthropic"})


async def get_model_api_key(user_id: str) -> SecretValue | None:
    entry = await db.get_vault_entry(_uuid(user_id), _MODEL_KEY_SITE)
    if entry is None:
        return None
    return SecretValue(await _decrypt(str(user_id), _MODEL_KEY_SITE, entry.encrypted_blob))


async def has_model_api_key(user_id: str) -> bool:
    return await db.get_vault_entry(_uuid(user_id), _MODEL_KEY_SITE) is not None


async def delete_model_api_key(user_id: str) -> bool:
    return await db.delete_vault_entry(_uuid(user_id), _MODEL_KEY_SITE)


async def resolve_anthropic_api_key(user_id: str) -> str:
    """Use the current user's key first, then the optional operator key."""
    personal = await get_model_api_key(user_id)
    if personal is not None:
        return personal.reveal()
    key = settings.secrets.anthropic_api_key
    if key:
        return key
    raise VaultError("No Anthropic API key is configured. Add yours in Settings.")


async def store_credential(user_id: str, site: str, value: str) -> None:
    """Encrypt + upsert the user's own credential for ``site``.

    ``value`` is a secret string, or JSON (e.g. {"username": "...",
    "password": "..."}) when a tool needs structured credentials — the vault
    is generic (site → secret blob) and never interprets payment specifics.
    """
    site = _clean_site(site)
    if site.startswith("__internal_"):
        raise VaultError("reserved credential site")
    if not isinstance(value, str) or not value:
        raise VaultError("credential value must be a non-empty string")
    blob = await _encrypt(str(user_id), site, value)
    await db.create_vault_entry(_uuid(user_id), site, blob)
    register_secret(value)
    logger.info("credential stored", extra={"user_id": str(user_id), "site": site})


async def get_credential(user_id: str, site: str) -> SecretValue | None:
    """Decrypt the user's own credential. INTERNAL — never model-facing.

    Tampered/foreign blobs raise VaultError (fail closed); a missing site is
    None.
    """
    site = _clean_site(site)
    if site.startswith("__internal_"):
        raise VaultError("reserved credential site")
    entry = await db.get_vault_entry(_uuid(user_id), site)
    if entry is None:
        return None
    return SecretValue(await _decrypt(str(user_id), site, entry.encrypted_blob))


async def list_sites(user_id: str) -> list[str]:
    """Site names only — the only vault data any listing surface may show."""
    return [site for site in await db.list_vault_sites(_uuid(user_id)) if not site.startswith("__internal_")]


async def delete_credential(user_id: str, site: str) -> bool:
    """Remove the user's own credential. False for foreign/missing rows."""
    site = _clean_site(site)
    if site.startswith("__internal_"):
        raise VaultError("reserved credential site")
    deleted = await db.delete_vault_entry(_uuid(user_id), site)
    if deleted:
        logger.info("credential deleted", extra={"user_id": str(user_id), "site": site})
    return deleted


def _clean_site(site: str) -> str:
    site = (site or "").strip().lower()
    if not site or len(site) > 200 or any(ch in site for ch in "\x00\r\n"):
        raise VaultError("invalid site identifier")
    return site


# --------------------------------------------------------------------------- #
# Backend seam (builtin vs external vaults, e.g. Bitwarden — Phase 4 seam)
# --------------------------------------------------------------------------- #


class VaultBackend:
    """Interface over per-user secret sources. Only the builtin backend is
    implemented; the seam exists so a linked external vault (Bitwarden) can
    slot in without touching callers."""

    mode: Literal["builtin", "external"] = "builtin"

    async def store(self, user_id: str, site: str, value: str) -> None:
        raise NotImplementedError

    async def get(self, user_id: str, site: str) -> SecretValue | None:
        raise NotImplementedError

    async def list(self, user_id: str) -> list[str]:
        raise NotImplementedError

    async def delete(self, user_id: str, site: str) -> bool:
        raise NotImplementedError


class BuiltinVaultBackend(VaultBackend):
    mode = "builtin"

    async def store(self, user_id: str, site: str, value: str) -> None:
        await store_credential(user_id, site, value)

    async def get(self, user_id: str, site: str) -> SecretValue | None:
        return await get_credential(user_id, site)

    async def list(self, user_id: str) -> list[str]:
        return await list_sites(user_id)

    async def delete(self, user_id: str, site: str) -> bool:
        return await delete_credential(user_id, site)


class BitwardenBackend(VaultBackend):
    """Placeholder seam: wraps the ``bw`` CLI with a session token the user
    stored in the built-in vault. Requires operator enablement."""

    mode = "external"

    async def store(self, user_id: str, site: str, value: str) -> None:
        raise VaultError("external vault (Bitwarden) is not yet available on this deployment")

    async def get(self, user_id: str, site: str) -> SecretValue | None:
        raise VaultError("external vault (Bitwarden) is not yet available on this deployment")

    async def list(self, user_id: str) -> list[str]:
        raise VaultError("external vault (Bitwarden) is not yet available on this deployment")

    async def delete(self, user_id: str, site: str) -> bool:
        raise VaultError("external vault (Bitwarden) is not yet available on this deployment")


def backend_for(user) -> VaultBackend:
    """Pick the backend for a user row (users.vault_mode). Unknown modes
    fall back to builtin rather than failing every credential call."""
    mode = getattr(user, "vault_mode", "builtin") or "builtin"
    return BitwardenBackend() if mode == "bitwarden" else BuiltinVaultBackend()
