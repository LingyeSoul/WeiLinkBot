"""Runtime context for sticker tools — set per-request in bot_service."""

from __future__ import annotations

from contextvars import ContextVar
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from wechatbot import WeChatBot, IncomingMessage

_bot_ctx: ContextVar[WeChatBot] = ContextVar("_bot_ctx")
_msg_ctx: ContextVar[IncomingMessage] = ContextVar("_msg_ctx")


def set_sticker_context(bot: WeChatBot, msg: IncomingMessage) -> None:
    """Call before agent.run() to make bot+msg available to sticker tools."""
    _bot_ctx.set(bot)
    _msg_ctx.set(msg)


def get_sticker_context() -> tuple[WeChatBot, IncomingMessage]:
    """Return (bot, msg). Raises LookupError if not set."""
    return _bot_ctx.get(), _msg_ctx.get()
