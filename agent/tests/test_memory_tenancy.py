"""Memory tools: identical recall across users returns only one's own rows;
forget is ownership-checked; context injection is user-scoped."""

from __future__ import annotations

from tests.p2_conftest import task_context
from tools import memory
from tools.base import call_tool


async def _embed(text: str, monkeypatch) -> list[float]:
    monkeypatch.setattr(memory, "embed_text", _fake_embed)
    return await memory.embed_text(text)


_FAKE_VECTORS: dict[str, list[float]] = {}


async def _fake_embed(text: str) -> list[float]:
    # deterministic 384-dim pseudo-embedding by content hash
    import hashlib

    digest = hashlib.sha256(text.encode()).digest()
    vector = (digest * 12)[:384]
    return [b / 255.0 for b in vector]


async def test_identical_recall_is_per_user(users_a_b, monkeypatch):
    alice, bob = users_a_b
    monkeypatch.setattr(memory, "embed_text", _fake_embed)
    content = "alice and bob both store this exact sentence"
    with task_context(str(alice.id), "t1"):
        await call_tool("remember", {"content": content, "importance": 0.9})
    with task_context(str(bob.id), "t2"):
        await call_tool("remember", {"content": content, "importance": 0.9})

    with task_context(str(alice.id), "t1"):
        a_results = await call_tool("recall", {"query": content})
    with task_context(str(bob.id), "t2"):
        b_results = await call_tool("recall", {"query": content})

    assert a_results.ok and b_results.ok
    assert len(a_results.data) == 1 and len(b_results.data) == 1
    assert {r["id"] for r in a_results.data}.isdisjoint({r["id"] for r in b_results.data})


async def test_forget_ownership(users_a_b, monkeypatch):
    alice, bob = users_a_b
    monkeypatch.setattr(memory, "embed_text", _fake_embed)
    with task_context(str(alice.id), "t1"):
        saved = await call_tool("remember", {"content": "alice private note"})
        alice_mem_id = saved.data["id"]

        # Bob tries to forget Alice's memory:
        with task_context(str(bob.id), "t2"):
            result = await call_tool("forget", {"memory_id": alice_mem_id})
        assert result.ok is False and "not found" in result.error

        # Alice forgets her own:
        with task_context(str(alice.id), "t1"):
            result = await call_tool("forget", {"memory_id": alice_mem_id})
        assert result.ok is True


async def test_recall_for_context_user_scoped(users_a_b, monkeypatch):
    alice, _ = users_a_b
    monkeypatch.setattr(memory, "embed_text", _fake_embed)
    with task_context(str(alice.id), "t1"):
        await call_tool("remember", {"content": "alice likes skiing", "importance": 1.0})
    embedding = await _fake_embed("alice likes skiing")
    for_alice = await memory.recall_for_context(alice.id, embedding, limit=5)
    assert len(for_alice) == 1
