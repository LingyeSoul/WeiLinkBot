"""Runtime context for sticker & messaging tools — set per-request in bot_service."""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass
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


# ── Segmented reply result ──────────────────────────────────────────
# Set by SendMessagesTool after sending messages, read by bot_service to
# skip its own reply and use the joined text for history persistence.

@dataclass
class SegmentsResult:
    """Result of a segmented reply — exposed to bot_service.

    complete=False marks a partial send failure: some segments were delivered
    to the user before a send error, so bot_service should send a fallback
    notice instead of its normal reply.
    """

    joined_text: str   # sent segments joined with "\n"
    count: int         # number of segments actually sent
    complete: bool = True  # False = partial send failure


_segments_ctx: ContextVar[SegmentsResult | None] = ContextVar(
    "_segments_ctx", default=None,
)


def set_segments_sent(segments: list[str], *, complete: bool = True) -> None:
    """Record segments sent this turn.

    Takes the segment list directly so joined_text/count stay consistent
    (derived internally). Pass complete=False for a partial send failure.
    """
    _segments_ctx.set(
        SegmentsResult("\n".join(segments), len(segments), complete)
    )


def get_segments_sent() -> SegmentsResult | None:
    """Return the segmented-reply result, or None if not used this turn."""
    return _segments_ctx.get()


def clear_segments_sent() -> None:
    """Reset at the start of each message processing turn to avoid stale state."""
    _segments_ctx.set(None)
