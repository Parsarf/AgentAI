"""One bot, many linked users.

Every incoming message's chat_id resolves to a user via telegram_links;
unlinked chats get linking instructions instead of a rejection. Linked
messages publish task.requested with the resolved user and source="user".
The bot subscribes to notify.user / task.finished / approval.requested and
delivers ONLY to chats linked to that user. Approvals carry inline
Approve/Deny buttons wired to core.approvals.decide.
"""

from __future__ import annotations

import html
from typing import Any

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from core import approvals, db, events
from core.config import settings
from core.logging import get_logger
from gateway import account_linking

logger = get_logger(__name__)

_app: Application | None = None
_chat_user_cache: dict[str, str] = {}

MAX_TG_LEN = 4000


async def start() -> None:
    """Start polling. Requires TELEGRAM_BOT_TOKEN."""
    global _app
    token = settings.require("telegram_bot_token")
    _app = (
        Application.builder().token(token).build()
    )
    _app.add_handler(CommandHandler("start", _on_start))
    _app.add_handler(CommandHandler("help", _on_start))
    _app.add_handler(CallbackQueryHandler(_on_decision))
    _app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, _on_message))
    await _app.initialize()
    await _app.start()
    await _app.updater.start_polling(drop_pending_updates=True)

    await events.subscribe(events.TASK_FINISHED, _on_task_finished)
    await events.subscribe(events.NOTIFY_USER, _on_notify)
    await events.subscribe(events.APPROVAL_REQUESTED, _on_approval_requested)
    logger.info("telegram gateway up")


async def stop() -> None:
    global _app
    if _app is not None:
        await _app.updater.stop()
        await _app.stop()
        await _app.shutdown()
        _app = None


# --------------------------------------------------------------------------- #
# inbound
# --------------------------------------------------------------------------- #


async def _on_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_chat is None:
        return
    chat_id = str(update.effective_chat.id)
    if await _resolve_user(chat_id):
        await _send_to_chat(
            chat_id,
            "You're linked! Just send me a task in plain language.",
        )
    else:
        await update.effective_chat.send_message(
            "Hi! I'm your personal agent, but this chat isn't linked to an account "
            "yet.\n\n1. Sign up / log in at the web dashboard\n"
            "2. Open Settings → Telegram and generate a link code\n"
            "3. Send that code here (just paste it)"
        )


async def _send_to_chat(chat_id: str, text: str, reply_markup=None) -> None:
    if _app is None:
        return
    text = text or "(empty)"
    for start in range(0, len(text), MAX_TG_LEN):
        await _app.bot.send_message(
            chat_id=chat_id,
            text=text[start : start + MAX_TG_LEN],
            reply_markup=reply_markup,
            parse_mode=None,
        )


async def _resolve_user(chat_id: str) -> str | None:
    user_id = _chat_user_cache.get(chat_id)
    if user_id:
        return user_id
    user_id = await account_linking.user_for_chat(chat_id)
    if user_id:
        _chat_user_cache[chat_id] = user_id
    return user_id


async def _on_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_chat is None or not update.message:
        return
    chat_id = str(update.effective_chat.id)
    user_id = await _resolve_user(chat_id)
    if user_id is None:
        await update.message.reply_text(
            "Hi! I'm your personal agent, but this chat isn't linked to an account "
            "yet.\n\n1. Sign up / log in at the web dashboard\n"
            "2. Open Settings → Telegram and generate a link code\n"
            "3. Send that code here (just paste it)"
        )
        return
    text = (update.message.text or "").strip()
    if _looks_like_link_code(text):
        try:
            linked_user = await account_linking.redeem_link_code(text, chat_id)
            _chat_user_cache[chat_id] = linked_user
            await update.message.reply_text("Linked! You can now talk to your agent here.")
        except ValueError as exc:
            await update.message.reply_text(str(exc))
        return
    await update.message.reply_text("Working on it…")
    await events.publish(
        events.TASK_REQUESTED,
        {"user_id": user_id, "request": text, "source": "user", "chat_id": chat_id},
    )


def _looks_like_link_code(text: str) -> bool:
    return len(text) == 8 and text.isalnum()


async def _on_decision(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Approve/Deny button presses."""
    query = update.callback_query
    if query is None or not query.data or ":" not in query.data:
        return
    verb, approval_id = query.data.split(":", 1)
    chat_id = str(query.message.chat_id) if query.message else None
    user_id = await _resolve_user(chat_id) if chat_id else None
    if user_id is None:
        await query.answer(text="This chat isn't linked to an account.", show_alert=True)
        return
    approved = verb == "approve"
    ok = await approvals.decide(user_id, approval_id, approved)
    await query.answer(text="Approved" if ok and approved else ("Denied" if ok else "No longer pending"))
    if ok:
        with_suppress_edit(query)


def with_suppress_edit(query) -> None:  # pragma: no cover - cosmetic
    try:
        query.edit_message_reply_markup(reply_markup=None)
    except Exception:
        pass


# --------------------------------------------------------------------------- #
# outbound (event subscribers) — deliver ONLY to the owning user's chats
# --------------------------------------------------------------------------- #


async def _chats_for(user_id: str) -> list[str]:
    try:
        return await db.get_chats_for_user(user_id)
    except Exception:
        logger.exception("chat lookup failed", extra={"user_id": user_id})
        return []


async def _on_task_finished(payload: dict[str, Any]) -> None:
    status = payload.get("status", "?")
    summary = payload.get("summary") or ""
    icon = "✅" if status == "done" else "❌"
    text = f"{icon} Task finished ({status})\n\n{summary}"
    for chat_id in await _chats_for(payload["user_id"]):
        await _send_to_chat(chat_id, html.escape(text))


async def _on_notify(payload: dict[str, Any]) -> None:
    urgent = bool(payload.get("urgent"))
    prefix = "🔔 " if urgent else ""
    text = f"{prefix}{payload.get('message', '')}"
    for chat_id in await _chats_for(payload["user_id"]):
        await _send_to_chat(chat_id, html.escape(text))


async def _on_approval_requested(payload: dict[str, Any]) -> None:
    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ Approve", callback_data=f"approve:{payload['approval_id']}"),
                InlineKeyboardButton("❌ Deny", callback_data=f"deny:{payload['approval_id']}"),
            ]
        ]
    )
    details = payload.get("details") or {}
    lines = [
        "⚠️ Approval needed",
        "",
        payload.get("action_summary", "(action)"),
    ]
    if details.get("risk"):
        lines.append(f"Risk: {details['risk']}")
    text = "\n".join(html.escape(line) for line in lines)
    for chat_id in await _chats_for(payload["user_id"]):
        await _send_to_chat(chat_id, text, reply_markup=keyboard)
