"""Let the agent reach its own user outside a task they started.

Publishes notify.user scoped to the calling task's user; gateways (Telegram,
web push/in-app) deliver to channels linked to that user only, respecting
their quiet hours unless urgent.
"""

from __future__ import annotations

from core import events
from core.logging import get_logger
from tools.base import ToolResult, tool

logger = get_logger(__name__)


@tool(
    "notify_user",
    "Send your user a short message outside this task (e.g. a job finished, "
    "or you need something). Delivered to their linked Telegram/dashboard.",
    risk="safe",
)
async def notify_user(message: str, urgent: bool = False) -> ToolResult:
    """Notify the acting task's own user. Never another user — there is no
    parameter for it."""
    from tools.base import current_task_id, current_user_id

    message = message.strip()
    if not message:
        return ToolResult(ok=False, error="empty message")
    if len(message) > 3000:
        return ToolResult(ok=False, error="message too long (max 3000 chars)")

    user_id = current_user_id.get()
    await events.publish(
        events.NOTIFY_USER,
        {
            "user_id": user_id,
            "task_id": current_task_id.get(),
            "message": message,
            "urgent": bool(urgent),
        },
    )
    logger.info(
        "notify published",
        extra={"user_id": str(user_id), "urgent": bool(urgent)},
    )
    return ToolResult(ok=True, data={"sent": True})
