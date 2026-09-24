"""A tiny async pub/sub event bus.

Components talk through events instead of importing each other. Every event
payload that concerns a specific user carries that user_id — publish()
enforces it for the user-scoped event names. Handler exceptions are caught
and logged so one broken subscriber can never crash others or leak across
users.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from core.logging import get_logger

logger = get_logger(__name__)

EventHandler = Callable[[dict], Awaitable[None]]

TASK_REQUESTED = "task.requested"
TASK_PROGRESS = "task.progress"
TASK_FINISHED = "task.finished"
APPROVAL_REQUESTED = "approval.requested"
APPROVAL_DECIDED = "approval.decided"
JOB_FIRED = "job.fired"
JOB_CHANGED = "job.changed"
NOTIFY_USER = "notify.user"
USAGE_UPDATED = "usage.updated"
SYSTEM_STOP = "system.stop"

#: Events whose payload must carry user_id — everything except system.stop.
USER_SCOPED_EVENTS = frozenset(
    {
        TASK_REQUESTED,
        TASK_PROGRESS,
        TASK_FINISHED,
        APPROVAL_REQUESTED,
        APPROVAL_DECIDED,
        JOB_FIRED,
        JOB_CHANGED,
        NOTIFY_USER,
        USAGE_UPDATED,
    }
)

_subscribers: dict[str, list[EventHandler]] = {}


async def subscribe(event_name: str, handler: EventHandler) -> None:
    _subscribers.setdefault(event_name, []).append(handler)


async def unsubscribe(event_name: str, handler: EventHandler) -> None:
    handlers = _subscribers.get(event_name)
    if handlers and handler in handlers:
        handlers.remove(handler)


async def publish(event_name: str, payload: dict) -> None:
    """Publish to every subscriber of this event name.

    User-scoped events REQUIRE a user_id in the payload — a missing one is a
    programming error, not a soft warning.
    """
    if event_name in USER_SCOPED_EVENTS and not payload.get("user_id"):
        raise ValueError(f"event '{event_name}' is user-scoped: payload requires user_id")
    for handler in list(_subscribers.get(event_name, [])):
        try:
            await handler(payload)
        except Exception:
            logger.exception(
                "event handler failed", extra={"event": event_name}
            )


async def wait_for(
    event_name: str,
    predicate: Callable[[dict], bool] | None = None,
    timeout: float = 30.0,
) -> dict | None:
    """Await the next event matching ``predicate``. None on timeout.

    Used by core.approvals to block for a user's decision (default deny on
    timeout is the caller's policy, not this function's).
    """
    loop = asyncio.get_running_loop()
    fut: asyncio.Future[dict] = loop.create_future()

    async def handler(payload: dict) -> None:
        if fut.done():
            return
        if predicate is None or predicate(payload):
            fut.set_result(payload)

    await subscribe(event_name, handler)
    try:
        return await asyncio.wait_for(fut, timeout)
    except TimeoutError:
        return None
    finally:
        await unsubscribe(event_name, handler)


def clear_all() -> None:
    """Drop every subscription. Test isolation only — never call in prod code."""
    _subscribers.clear()
