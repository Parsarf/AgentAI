"""Vault tenancy under attack (spec accept): same site name, two users;
swapped blobs, copied blobs, and forged user ids all fail closed — and the
model-facing surface only ever exposes site names."""

from __future__ import annotations

import pytest

from core import db
from core import secrets_vault as sv
from tests.p2_conftest import task_context
from tools.base import call_tool


async def _user(tag: str) -> db.User:
    import uuid

    return await db.create_user(f"vt-{tag}-{uuid.uuid4()}@example.com", password_hash="x")


async def test_same_site_two_users_isolated(db_pool):
    alice, bob = await _user("a"), await _user("b")
    await sv.store_credential(str(alice.id), "mail.example", "alice-mail-pw")
    await sv.store_credential(str(bob.id), "mail.example", "bob-mail-pw")

    assert (await sv.get_credential(str(alice.id), "mail.example")).reveal() == "alice-mail-pw"
    assert (await sv.get_credential(str(bob.id), "mail.example")).reveal() == "bob-mail-pw"


async def test_swapped_blob_between_users_fails_closed(db_pool):
    alice, bob = await _user("a"), await _user("b")
    await sv.store_credential(str(alice.id), "swap.tld", "alice-secret")
    await sv.store_credential(str(bob.id), "swap.tld", "bob-secret")

    blob_a = await db.get_vault_entry(alice.id, "swap.tld")
    blob_b = await db.get_vault_entry(bob.id, "swap.tld")
    # Deliberately swap the rows:
    await db.create_vault_entry(alice.id, "swap.tld", blob_b.encrypted_blob)
    await db.create_vault_entry(bob.id, "swap.tld", blob_a.encrypted_blob)

    with pytest.raises(sv.VaultError):
        await sv.get_credential(str(alice.id), "swap.tld")
    with pytest.raises(sv.VaultError):
        await sv.get_credential(str(bob.id), "swap.tld")


async def test_forged_user_id_cannot_read(db_pool):
    alice, mallory = await _user("a"), await _user("m")
    await sv.store_credential(str(alice.id), "forge.tld", "alice-secret")

    # Mallory calls the internal getter with their own id: no row, no leak.
    assert (await sv.get_credential(str(mallory.id), "forge.tld")) is None

    # Copying alice's blob under mallory's row cryptographically fails (AAD).
    blob = await db.get_vault_entry(alice.id, "forge.tld")
    await db.create_vault_entry(mallory.id, "forge.tld", blob.encrypted_blob)
    with pytest.raises(sv.VaultError):
        await sv.get_credential(str(mallory.id), "forge.tld")


async def test_list_sites_never_crosses_users(db_pool):
    alice, bob = await _user("a"), await _user("b")
    await sv.store_credential(str(alice.id), "a-only.tld", "v1")
    await sv.store_credential(str(bob.id), "b-only.tld", "v2")

    assert await sv.list_sites(str(alice.id)) == ["a-only.tld"]
    assert await sv.list_sites(str(bob.id)) == ["b-only.tld"]


async def test_model_facing_tool_returns_names_only(db_pool):
    """list_available_accounts is the ONLY vault tool the model gets — site
    names for the acting user, never values, never another user's rows."""
    alice, bob = await _user("a"), await _user("b")
    await sv.store_credential(str(alice.id), "tool.tld", '{"username":"a","password":"pw-a"}')

    with task_context(str(alice.id), "t-a"):
        listed = await call_tool("list_available_accounts", {})
        assert listed.ok and listed.data == ["tool.tld"]

    with task_context(str(bob.id), "t-b"):
        listed = await call_tool("list_available_accounts", {})
        assert listed.ok and listed.data == []  # existence not leaked either

    # The registry must not expose any vault getter as a tool.
    from tools.base import registry

    assert registry.get("get_credential") is None
    assert "get_credential_for_user" not in registry.all()


async def test_delete_is_owner_scoped(db_pool):
    alice, bob = await _user("a"), await _user("b")
    await sv.store_credential(str(alice.id), "del.tld", "v")
    assert await sv.delete_credential(str(bob.id), "del.tld") is False
    assert (await sv.get_credential(str(alice.id), "del.tld")) is not None
    assert await sv.delete_credential(str(alice.id), "del.tld") is True
    assert await sv.get_credential(str(alice.id), "del.tld") is None


async def test_bitwarden_seam_raises_not_available(db_pool, monkeypatch):
    from core.secrets_vault import BitwardenBackend

    backend = BitwardenBackend()
    with pytest.raises(sv.VaultError, match="not yet available"):
        await backend.get("whatever", "site.tld")
    with pytest.raises(sv.VaultError, match="not yet available"):
        await backend.store("whatever", "site.tld", "v")


async def test_web_vault_route_stores_without_echoing(db_pool):
    """Users write their own credentials via settings; the response never
    echoes the value, and only the owner's row exists."""
    import secrets as _secrets
    from datetime import UTC, datetime

    import httpx

    from core import auth
    from gateway.web_app import app

    user = await _user("web")
    await db.update_user(user.id, status="active")
    raw_token = _secrets.token_urlsafe(32)
    await db.create_session(
        user.id, auth._token_hash(raw_token), datetime.now(UTC) + auth.SESSION_TTL
    )

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test", follow_redirects=False
    ) as client:
        client.cookies.set("agent_session", raw_token)
        page = (await client.get("/settings")).text
        csrf = page.split('name="csrf" value="')[1].split('"')[0]

        r = await client.post(
            "/settings/vault",
            data={"site": "Web.Example", "username": "u1",
                  "password": "web-pw-secret", "csrf": csrf},
        )
        assert r.status_code == 303
        assert "web-pw-secret" not in r.text

        # Stored normalized, decryptable by the owner only:
        assert await sv.list_sites(str(user.id)) == ["web.example"]
        got = await sv.get_credential(str(user.id), "web.example")
        assert '"web-pw-secret"' in got.reveal()

        # Settings page shows the site name, never a value:
        page = (await client.get("/settings")).text
        assert "web.example" in page and "web-pw-secret" not in page

        # Removal:
        r = await client.post(
            "/settings/vault/delete", data={"site": "web.example", "csrf": csrf}
        )
        assert r.status_code == 303
        assert await sv.list_sites(str(user.id)) == []
