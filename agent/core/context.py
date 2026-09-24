"""Builds the model's context window per task, scoped to the acting user.

Assembles: system prompt + runtime facts, the user's most relevant memories,
and the task's step history (summarized via the cheap model once long), under
a token budget. Everything pulled is user-scoped by construction — every
query in here carries the acting user_id.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from core.config import settings
from core.logging import get_logger

logger = get_logger(__name__)

# Rough estimator: ~4 chars/token for English + JSON. Deliberately coarse —
# the budget exists to leave headroom, not to be a tokenizer.
CHARS_PER_TOKEN = 4
_MEMORIES_IN_CONTEXT = 6
_HISTORY_RESERVE = 0.6  # fraction of budget history may occupy before summarizing


def _tokens(text: str) -> int:
    return max(1, len(text) // CHARS_PER_TOKEN)


async def build_context(
    user_id,
    task_id,
    request: str,
    step_history: list[dict[str, Any]],
    *,
    summarize_long_history: bool = True,
) -> tuple[str, list[dict[str, Any]]]:
    """Return (system_text, messages) for one model call.

    `step_history` is the running message list for this task (may be empty on
    step 0). Oldest history is summarized — never silently dropped — when the
    budget tightens.
    """
    from tools.memory import embed_text, recall_for_context

    budget = settings.limits.context_token_budget

    # ---- memories: top-N relevant for THIS user, decay-ranked
    memory_block = ""
    try:
        embedding = await embed_text(request)
        memories = await recall_for_context(user_id, embedding, limit=_MEMORIES_IN_CONTEXT)
    except Exception:
        logger.exception("memory recall for context failed", extra={"user_id": str(user_id)})
        memories = []
    if memories:
        lines = [f"- [{m.category}] {m.content}" for m in memories]
        memory_block = (
            "Things you remember for this user (most relevant first):\n" + "\n".join(lines)
        )

    now = datetime.now(UTC)
    runtime = (
        f"Current UTC time: {now.strftime('%Y-%m-%d %H:%M')}\n"
        f"Task id: {task_id}"
    )
    system_parts = [
        _load_system_prompt(),
        runtime,
    ]
    if memory_block:
        system_parts.append(memory_block)
    system = "\n\n".join(part for part in system_parts if part)

    system_tokens = _tokens(system) + _tokens(request) + 800  # headroom: schemas + reply
    history_budget = int(budget * _HISTORY_RESERVE) - system_tokens

    history_tokens = sum(_tokens(str(m.get("content", ""))) for m in step_history)
    if history_tokens > max(history_budget, 0) and summarize_long_history and len(step_history) > 4:
        step_history = await _summarize_history(user_id, task_id, step_history)

    messages = list(step_history) if step_history else []
    messages.append({"role": "user", "content": request})
    return system, messages


async def _summarize_history(user_id, task_id, step_history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Compress old turns into one assistant-visible summary message."""
    from core import router

    keep = step_history[-4:]
    old = step_history[:-4]
    transcript = "\n".join(
        f"{m.get('role')}: {str(m.get('content'))[:2000]}" for m in old
    )
    try:
        reply = await router.call(
            user_id,
            task_id,
            "cheap",
            [
                {
                    "role": "user",
                    "content": (
                        "Summarize this agent-task transcript in under 250 words. "
                        "Keep: what was asked, what was tried, tool results that "
                        "matter, open questions.\n\n" + transcript
                    ),
                }
            ],
            max_tokens=600,
        )
        summary = reply.text.strip()
    except Exception:
        logger.exception("history summarization failed", extra={"user_id": str(user_id)})
        summary = "(earlier steps summarized: transcript omitted)"
    logger.info(
        "history summarized",
        extra={"user_id": str(user_id), "old_messages": len(old), "kept": len(keep)},
    )
    return [{"role": "user", "content": f"[Earlier in this task]\n{summary}"}] + keep


_PROMPT_CACHE: str | None = None


def _load_system_prompt() -> str:
    global _PROMPT_CACHE
    if _PROMPT_CACHE is None:
        from pathlib import Path

        prompt_path = Path(__file__).resolve().parent / "prompts" / "system.md"
        _PROMPT_CACHE = prompt_path.read_text()
    return _PROMPT_CACHE
