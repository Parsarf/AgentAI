"""Process entrypoint — brings up the whole multi-user service.

Startup order: load settings (fail loud) → init_db → auto_discover tools →
subscribe the orchestrator → start gateways (web + Telegram) → start the
scheduler service (which also owns the sandbox workspace retention sweep) →
run until system.stop or SIGINT/SIGTERM.
"""

from __future__ import annotations

import asyncio
import contextlib
import signal

import uvicorn

from core import billing, db, events, orchestrator, scheduler_service
from core.config import settings
from core.logging import get_logger
from tools.base import auto_discover

logger = get_logger(__name__)

_stop = asyncio.Event()


def _handle_signal() -> None:
    logger.info("shutdown signal received")
    _stop.set()


async def main() -> None:
    _stop.clear()
    logger.info("starting agent service")
    billing.validate_startup()
    await db.init_db()
    interrupted = await db.recover_interrupted_tasks()
    if interrupted:
        logger.warning("interrupted tasks marked failed without replay", extra={"count": len(interrupted)})
    auto_discover()
    from tools.base import registry

    logger.info("tools discovered", extra={"count": len(registry.all())})
    orchestrator.subscribe()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, _handle_signal)

    # Telegram gateway (optional in dev: skipped when no token is configured).
    telegram_task: asyncio.Task | None = None
    if settings.secrets.telegram_bot_token:
        from gateway import telegram_bot

        telegram_task = asyncio.get_running_loop().create_task(telegram_bot.start())
    else:
        logger.warning("TELEGRAM_BOT_TOKEN empty — Telegram gateway disabled")

    # Web dashboard, in-process.
    from gateway.web_app import app as web_app

    web_config = uvicorn.Config(
        web_app,
        host="0.0.0.0",
        port=8000,
        log_level="info",
        lifespan="off",
    )
    web_server = uvicorn.Server(web_config)
    web_task = asyncio.get_running_loop().create_task(web_server.serve())

    scheduler_service.start()
    logger.info("service up", extra={"base_url": settings.secrets.base_url})

    stop_wait = asyncio.create_task(_stop.wait())
    try:
        done, _ = await asyncio.wait({stop_wait, web_task}, return_when=asyncio.FIRST_COMPLETED)
        if web_task in done and not _stop.is_set():
            logger.error("web server stopped unexpectedly")
            _stop.set()
    finally:
        stop_wait.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await stop_wait
        await _shutdown(web_server, web_task, telegram_task)


async def _shutdown(web_server, web_task: asyncio.Task, telegram_task: asyncio.Task | None) -> None:
    """Bounded, ordered shutdown of the single-process runtime."""
    logger.info("shutting down")
    web_server.should_exit = True
    await orchestrator.unsubscribe_all()
    with contextlib.suppress(Exception):
        await events.publish(events.SYSTEM_STOP, {})
    with contextlib.suppress(Exception):
        await asyncio.wait_for(scheduler_service.stop(), timeout=15)
    await orchestrator.stop_and_drain(timeout=15)
    if telegram_task is not None:
        from gateway import telegram_bot

        # start() returns after polling starts; stop polling BEFORE awaiting
        # any task that might still be in startup or long polling.
        with contextlib.suppress(Exception):
            await asyncio.wait_for(telegram_bot.stop(), timeout=10)
        with contextlib.suppress(Exception):
            await asyncio.wait_for(telegram_task, timeout=10)
    with contextlib.suppress(Exception):
        await asyncio.wait_for(web_task, timeout=10)
    still_open = await db.recover_interrupted_tasks()
    if still_open:
        logger.warning("unfinished tasks marked failed at shutdown", extra={"count": len(still_open)})
    await db.close_pool()
    logger.info("bye")


if __name__ == "__main__":
    asyncio.run(main())
