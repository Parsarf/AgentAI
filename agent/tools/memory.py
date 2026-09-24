"""Per-user long-term memory: store, recall (decay-ranked), forget.

Embeddings come from the local sentence-transformers model configured in
settings (no extra operator signup). All queries are user-scoped — a memory
stored by one user can never surface in another user's recall.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime

from core import db
from core.config import settings
from core.logging import get_logger
from tools.base import ToolResult, tool

logger = get_logger(__name__)

_model = None
_DECAY_DAYS = 30.0


async def embed_text(text: str) -> list[float]:
    """Embed text with the configured local model (lazy-loads once)."""
    global _model

    def _load_and_embed(payload: str) -> list[float]:
        global _model
        if _model is None:
            from sentence_transformers import SentenceTransformer

            _model = SentenceTransformer(settings.embeddings.model)
        vector = _model.encode(payload, normalize_embeddings=True)
        return [float(x) for x in vector]

    import asyncio

    return await asyncio.to_thread(_load_and_embed, text)


def _decay_factor(memory) -> float:
    if memory.last_used_at is None:
        days = 30.0
    else:
        days = max(
            0.0, (datetime.now(UTC) - memory.last_used_at).total_seconds() / 86400
        )
    return math.exp(-days / _DECAY_DAYS)


async def recall_for_context(user_id, embedding: list[float], limit: int = 6):
    """Top memories for context injection: cosine distance × importance × decay."""
    candidates = await db.search_memories(user_id, embedding, limit=max(limit * 3, 12))

    def score(m) -> float:
        similarity = 1.0 - (m.distance or 1.0)
        return similarity * (0.35 + 0.65 * m.importance * _decay_factor(m))

    ranked = sorted(candidates, key=score, reverse=True)[:limit]
    return ranked


@tool(
    "remember",
    "Save a durable fact or preference for this user, e.g. 'prefers metric "
    "units'. Keep each memory short and self-contained.",
    risk="safe",
)
async def remember(content: str, category: str = "general", importance: float = 0.5) -> ToolResult:
    """Store a memory scoped to the acting user."""
    from uuid import UUID as _UUID

    from tools.base import current_user_id

    content = content.strip()
    if not content:
        return ToolResult(ok=False, error="nothing to remember (empty content)")
    if len(content) > 2000:
        return ToolResult(ok=False, error="memory too long (max 2000 chars)")
    importance = min(1.0, max(0.0, float(importance)))
    embedding = await embed_text(content)
    memory = await db.add_memory(
        _UUID(current_user_id.get()), content, category.strip() or "general",
        embedding, importance,
    )
    return ToolResult(ok=True, data={"id": str(memory.id), "content": memory.content})


@tool(
    "recall",
    "Search this user's memories by meaning. Returns the closest matches.",
    risk="safe",
)
async def recall(query: str, limit: int = 5) -> list[dict]:
    """Semantic search over the acting user's own memories."""
    from uuid import UUID as _UUID

    from tools.base import current_user_id

    embedding = await embed_text(query)
    memories = await recall_for_context(_UUID(current_user_id.get()), embedding, limit=min(limit, 20))
    return [
        {
            "id": str(m.id),
            "content": m.content,
            "category": m.category,
            "importance": round(m.importance, 2),
        }
        for m in memories
    ]


@tool(
    "forget",
    "Delete one of this user's memories by id (ids come from recall).",
    risk="moderate",
)
async def forget(memory_id: str) -> ToolResult:
    """Forget a memory — ownership enforced by the user-scoped delete."""
    from uuid import UUID as _UUID

    from tools.base import current_user_id

    try:
        mid = _UUID(memory_id)
    except ValueError:
        return ToolResult(ok=False, error="memory_id must be a uuid")
    deleted = await db.delete_memory(_UUID(current_user_id.get()), mid)
    if not deleted:
        # Same message whether it belongs to someone else or never existed.
        return ToolResult(ok=False, error="memory not found")
    return ToolResult(ok=True, data={"forgotten": memory_id})
