"""send_messages — send a reply as multiple sequential messages.

Lets the LLM split a reply into several messages sent one after another
(e.g. breaking long content into points, or simulating human typing rhythm).
The segments are sent immediately via bot.reply; on success a ContextVar is
set so bot_service knows to skip its own reply and persist the joined text.
"""

from __future__ import annotations

import logging
from typing import Any

from .base import Tool, ToolExecutionError
from .sticker_context import get_sticker_context, set_segments_sent

logger = logging.getLogger(__name__)


class SendMessagesTool(Tool):
    name = "send_messages"
    # Terminal: messages are already delivered to the user via bot.reply —
    # continuing the loop would risk duplicate sends.
    terminal = True
    description = (
        "Send your reply as multiple sequential messages to the user. Each "
        "string in the 'messages' array is sent as a separate message, in "
        "order. By default you SHOULD use this tool for your reply: split it "
        "into individual sentences as much as possible, with each sentence as "
        "its own array element, to simulate a human sending multiple messages "
        "one after another (max ~10 segments). Only reply as plain text when "
        "the response is a single short sentence that needs no splitting. The "
        "content is sent immediately upon calling this tool — do NOT repeat "
        "these messages in your follow-up response."
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "messages": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Message segments in send order. Each becomes a separate "
                    "message to the user. Must contain at least one segment."
                ),
            },
        },
        "required": ["messages"],
        "additionalProperties": False,
    }

    async def execute(self, *, messages: list[str], **kwargs) -> str:
        from ...config import get_config

        try:
            bot, msg = get_sticker_context()
        except LookupError:
            raise ToolExecutionError("send_messages called outside a message context")

        if not isinstance(messages, list) or not messages:
            raise ToolExecutionError("messages must be a non-empty array")

        config = get_config()
        max_count = config.agent.segment_max_count
        max_chars = config.agent.segment_max_chars

        # Drop whitespace-only segments
        valid = [m for m in messages if isinstance(m, str) and m.strip()]
        if not valid:
            raise ToolExecutionError("messages must contain at least one non-empty segment")

        if len(valid) > max_count:
            raise ToolExecutionError(
                f"Too many segments: {len(valid)} (max {max_count})"
            )
        for i, seg in enumerate(valid):
            if len(seg) > max_chars:
                raise ToolExecutionError(
                    f"Segment {i + 1} too long: {len(seg)} chars (max {max_chars})"
                )

        # Send serially to preserve order; record what actually goes out so
        # bot_service can persist history and skip its own reply.
        sent: list[str] = []
        for seg in valid:
            try:
                await bot.reply(msg, seg)
            except Exception:
                # Partial failure: mark as incomplete so bot_service sends a
                # fallback notice instead of its normal reply (and does NOT
                # let the LLM re-send these already-delivered segments).
                if sent:
                    set_segments_sent(sent, complete=False)
                logger.warning(
                    "send_messages: segment %d/%d failed after %d sent",
                    len(sent) + 1, len(valid), len(sent), exc_info=True,
                )
                # Generic message only — don't leak the raw exception to the LLM.
                raise ToolExecutionError(
                    f"Failed to send segment {len(sent) + 1} "
                    f"({len(sent)} already sent)"
                )
            sent.append(seg)

        set_segments_sent(sent)  # complete=True
        logger.info("Sent %d segmented messages to user %s", len(sent), msg.user_id)
        return f"Sent {len(sent)} messages to the user."
