"""Vault cryptography: envelope roundtrip, tamper refusal, per-user key
separation, SecretValue redaction, and the KMS seam (mocked provider key)."""

from __future__ import annotations

import base64

import pytest

from core import db
from core import secrets_vault as sv
from core.secrets_vault import SecretValue, VaultError


async def _user() -> db.User:
    import uuid

    return await db.create_user(f"vc-{uuid.uuid4()}@example.com", password_hash="x")


async def test_roundtrip_and_fresh_nonce(db_pool):
    user = await _user()
    await sv.store_credential(str(user.id), "Example.com", "value-1")

    first = await db.get_vault_entry(user.id, "example.com")
    await sv.store_credential(str(user.id), "example.com", "value-1")
    second = await db.get_vault_entry(user.id, "example.com")

    # Same plaintext, fresh nonce per write ⇒ different ciphertexts.
    assert first.encrypted_blob != second.encrypted_blob
    got = await sv.get_credential(str(user.id), "example.com")
    assert isinstance(got, SecretValue)
    assert got.reveal() == "value-1"


async def test_secret_value_never_leaks_via_repr_or_str(db_pool):
    secret = SecretValue("hunter2!")
    assert repr(secret) == "[REDACTED]"
    assert str(secret) == "[REDACTED]"
    assert "hunter2!" not in f"{secret} {secret!r}"
    assert secret.reveal() == "hunter2!"


async def test_tampered_ciphertext_fails_closed(db_pool):
    user = await _user()
    await sv.store_credential(str(user.id), "site.tld", "precious")
    entry = await db.get_vault_entry(user.id, "site.tld")

    for mutate in (
        lambda b: b[:-1] + bytes([b[-1] ^ 0x01]),          # flip last ct byte
        lambda b: b[:2] + bytes([b[2] ^ 0x01]) + b[3:],    # flip a nonce byte
        lambda b: b[:10],                                   # truncate
    ):
        await db.create_vault_entry(user.id, "site.tld", mutate(entry.encrypted_blob))
        with pytest.raises(VaultError):
            await sv.get_credential(str(user.id), "site.tld")

    # Restoring the genuine blob makes it readable again (the refusal was
    # cryptographic, not state corruption).
    await db.create_vault_entry(user.id, "site.tld", entry.encrypted_blob)
    assert (await sv.get_credential(str(user.id), "site.tld")).reveal() == "precious"


async def test_wrong_site_aad_fails(db_pool):
    """A blob moved to a DIFFERENT site of the SAME user fails (AAD bind)."""
    user = await _user()
    await sv.store_credential(str(user.id), "alpha.tld", "alpha-secret")
    blob = await db.get_vault_entry(user.id, "alpha.tld")
    await db.create_vault_entry(user.id, "beta.tld", blob.encrypted_blob)
    with pytest.raises(VaultError):
        await sv.get_credential(str(user.id), "beta.tld")


async def test_per_user_keys_are_independent(db_pool):
    alice, bob = await _user(), await _user()
    await sv.store_credential(str(alice.id), "shared.tld", "alice-value")
    await sv.store_credential(str(bob.id), "shared.tld", "bob-value")

    wrapped_a = await db.get_vault_key(alice.id)
    wrapped_b = await db.get_vault_key(bob.id)
    assert wrapped_a != wrapped_b  # different data keys, both envelope-wrapped

    assert (await sv.get_credential(str(alice.id), "shared.tld")).reveal() == "alice-value"
    assert (await sv.get_credential(str(bob.id), "shared.tld")).reveal() == "bob-value"


async def test_decrypt_registers_value_with_log_redaction(db_pool, monkeypatch):
    registered: list[str] = []
    monkeypatch.setattr(sv, "register_secret", lambda v: registered.append(v))
    user = await _user()
    await sv.store_credential(str(user.id), "redact.tld", "shhh-value")
    await sv.get_credential(str(user.id), "redact.tld")
    assert "shhh-value" in registered


async def test_kms_seam_mocked_provider_key(db_pool, monkeypatch):
    """With a KMS-style root configured (mocked here as a swapped root key),
    wrapping/unwrap still works — and a blob written under root A cannot be
    read after the root changes to B."""
    import hashlib

    key_a = base64.b64encode(b"a" * 32)
    key_b = base64.b64encode(b"b" * 32)
    current = {"key": key_a}
    monkeypatch.setattr(
        sv, "_root_key",
        lambda: hashlib.sha256(b"agent-vault-root-v1" + current["key"]).digest(),
    )

    user = await _user()
    await sv.store_credential(str(user.id), "kms.tld", "wrapped-secret")
    assert (await sv.get_credential(str(user.id), "kms.tld")).reveal() == "wrapped-secret"

    current["key"] = key_b  # root rotated / provider key changed
    sv.drop_key_cache(str(user.id))  # force a re-unwrap from vault_keys
    with pytest.raises(VaultError):
        await sv.get_credential(str(user.id), "kms.tld")


async def test_missing_master_key_fails_with_actionable_error(db_pool, monkeypatch):
    from core.config import settings

    monkeypatch.setattr(settings.secrets, "vault_master_key", None)
    user = await _user()
    with pytest.raises(VaultError, match="openssl rand"):
        await sv.store_credential(str(user.id), "x.tld", "v")


async def test_key_cache_drop(db_pool):
    user = await _user()
    await sv.store_credential(str(user.id), "cache.tld", "v")
    assert str(user.id) in sv._key_cache
    sv.drop_key_cache(str(user.id))
    assert str(user.id) not in sv._key_cache
    # still readable: key re-unwraps from vault_keys
    assert (await sv.get_credential(str(user.id), "cache.tld")).reveal() == "v"
