"""Per-user Anthropic keys: hidden storage and both model dispatch paths."""

from __future__ import annotations

import secrets
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from claude_agent_sdk import ResultMessage

from core import auth, db, orchestrator, router
from core import secrets_vault as vault
from core.config import settings
from gateway.web_app import app


async def test_key_is_tenant_bound_and_not_a_model_visible_credential(users_a_b):
    alice, bob = users_a_b
    await vault.store_model_api_key(str(alice.id), "alice-secret-model-key")
    await vault.store_model_api_key(str(bob.id), "bob-secret-model-key")
    assert (await vault.get_model_api_key(str(alice.id))).reveal() == "alice-secret-model-key"
    assert (await vault.get_model_api_key(str(bob.id))).reveal() == "bob-secret-model-key"
    assert await vault.list_sites(str(alice.id)) == []
    with pytest.raises(vault.VaultError, match="reserved"):
        await vault.get_credential(str(alice.id), "__internal_model_key_anthropic")
    with pytest.raises(vault.VaultError, match="reserved"):
        await vault.store_credential(str(alice.id), "__internal_model_key_anthropic", "bad")
    await vault.delete_model_api_key(str(alice.id))
    assert await vault.get_model_api_key(str(alice.id)) is None
    assert (await vault.get_model_api_key(str(bob.id))).reveal() == "bob-secret-model-key"


async def test_router_uses_owners_key_not_operator_key(users_a_b, monkeypatch):
    alice, _ = users_a_b
    await vault.store_model_api_key(str(alice.id), "alice-secret-model-key")
    seen = []

    class FakeClient:
        def __init__(self, api_key):
            seen.append(api_key)
            self.messages = SimpleNamespace(create=self.create)

        async def create(self, **_kwargs):
            return SimpleNamespace(
                usage=SimpleNamespace(input_tokens=10, output_tokens=2),
                content=[SimpleNamespace(type="text", text="ok")],
                stop_reason="end_turn",
            )

        async def close(self):
            pass

    monkeypatch.setattr(router.anthropic, "AsyncAnthropic", FakeClient)
    monkeypatch.setattr(router, "_get_client", lambda: pytest.fail("operator key used"))
    reply = await router.call(alice.id, None, "cheap", [{"role": "user", "content": "hi"}], max_tokens=8)
    assert reply.text == "ok"
    assert seen == ["alice-secret-model-key"]


async def test_sdk_loop_uses_owners_key(users_a_b, monkeypatch, tmp_path):
    alice, _ = users_a_b
    await vault.store_model_api_key(str(alice.id), "alice-secret-model-key")
    task = await db.create_task(alice.id, "tiny task", "user")

    async def fake_context(*_args):
        return "system", [{"role": "user", "content": "tiny task"}]

    async def fake_start(*_args):
        return Path(tmp_path)

    async def fake_query(*, prompt, options):
        assert options.env["ANTHROPIC_API_KEY"] == "alice-secret-model-key"
        yield ResultMessage(
            subtype="success",
            duration_ms=1,
            duration_api_ms=1,
            is_error=False,
            num_turns=1,
            session_id="fake",
            result="done",
            total_cost_usd=0.004,
        )

    import claude_agent_sdk

    monkeypatch.setattr(orchestrator, "build_context", fake_context)
    monkeypatch.setattr(orchestrator.sandbox, "start_task_sandbox", fake_start)
    monkeypatch.setattr(orchestrator, "get_sdk_mcp_server", lambda: {})
    monkeypatch.setattr(claude_agent_sdk, "query", fake_query)
    await orchestrator._loop(alice.id, task.id, alice, task, "user", 2)
    assert (await db.get_task(alice.id, task.id)).status == "done"


async def test_missing_key_has_actionable_error(users_a_b, monkeypatch):
    alice, _ = users_a_b
    monkeypatch.setattr(settings.secrets, "anthropic_api_key", None)
    with pytest.raises(vault.VaultError, match="Add yours in Settings"):
        await vault.resolve_anthropic_api_key(str(alice.id))


async def test_settings_key_save_and_remove_never_echoes(users_a_b):
    alice, _ = users_a_b
    raw_token = secrets.token_urlsafe(32)
    await db.create_session(alice.id, auth._token_hash(raw_token), datetime.now(UTC) + auth.SESSION_TTL)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        client.cookies.set("agent_session", raw_token)
        page = (await client.get("/settings")).text
        csrf = page.split('name="csrf" value="')[1].split('"')[0]
        response = await client.post(
            "/settings/model-key", data={"csrf": csrf, "api_key": "secret-canary-api-key"}
        )
        assert response.status_code == 303
        assert "secret-canary-api-key" not in response.text
        page = (await client.get("/settings")).text
        assert "Your Anthropic key is saved" in page
        assert "secret-canary-api-key" not in page
        bad = await client.post("/settings/model-key/delete", data={"csrf": "wrong"})
        assert bad.status_code == 403
        assert await vault.has_model_api_key(str(alice.id))
        removed = await client.post("/settings/model-key/delete", data={"csrf": csrf})
        assert removed.status_code == 303
        assert not await vault.has_model_api_key(str(alice.id))
