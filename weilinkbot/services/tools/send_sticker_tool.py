"""send_sticker tool — send a sticker image to the user by sticker_id."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from .base import Tool, ToolExecutionError
from .sticker_context import get_sticker_context

logger = logging.getLogger(__name__)

STICKERS_DIR = Path("data/stickers/packs")
_ALLOWED_EXTENSIONS = frozenset({".jpg", ".jpeg", ".png", ".gif", ".webp"})
_MAX_FILE_SIZE = 5 * 1024 * 1024  # 5 MB
_GIF_WARNED_USERS: set[str] = set()  # track per-user one-time GIF warning


class SendStickerTool(Tool):
    name = "send_sticker"
    description = (
        "Send a sticker image to the user. Call this after search_sticker "
        "or list_sticker_packs to actually deliver the sticker. "
        "The sticker is sent as an image message (side-effect). "
        "Returns a confirmation string."
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "sticker_id": {
                "type": "integer",
                "description": (
                    "The sticker_id returned by search_sticker or list_sticker_packs."
                ),
            },
        },
        "required": ["sticker_id"],
        "additionalProperties": False,
    }

    def __init__(self, session_factory):
        self._session_factory = session_factory

    async def execute(self, *, sticker_id: int, **kwargs) -> str:
        from ...services.sticker_service import StickerService

        try:
            bot, msg = get_sticker_context()
        except LookupError:
            raise ToolExecutionError("send_sticker called outside a message context")

        # Look up sticker file_path from database
        async with self._session_factory() as db:
            service = StickerService(db)
            from sqlalchemy import select
            from ...models import Sticker
            result = await db.execute(select(Sticker).where(Sticker.id == sticker_id))
            sticker = result.scalar_one_or_none()

        if not sticker:
            raise ToolExecutionError(f"Sticker with id={sticker_id} not found.")

        file_path = sticker.file_path
        full_path = (STICKERS_DIR / file_path).resolve()
        stickers_root = STICKERS_DIR.resolve()
        if not (full_path == stickers_root or stickers_root in full_path.parents):
            raise ToolExecutionError(f"Invalid sticker path for id={sticker_id}")

        if full_path.suffix.lower() not in _ALLOWED_EXTENSIONS:
            raise ToolExecutionError(f"Unsupported file type: {full_path.suffix}")

        if not full_path.exists():
            raise ToolExecutionError(f"Sticker file not found on disk: {file_path}")

        if full_path.stat().st_size > _MAX_FILE_SIZE:
            raise ToolExecutionError(f"Sticker file too large: {full_path.stat().st_size} bytes")

        is_gif = full_path.suffix.lower() == ".gif"
        image_bytes = full_path.read_bytes()

        # Always send the image (static for GIFs — iLink bot API does not
        # support animated images; IMAGE type strips animation).
        try:
            await bot.reply_media(msg, {"image": image_bytes})
        except Exception as e:
            raise ToolExecutionError(f"Failed to send sticker: {e}")

        logger.info("Sent sticker id=%d (%d bytes)", sticker_id, len(image_bytes))

        if is_gif:
            user_id = msg.user_id
            if user_id not in _GIF_WARNED_USERS:
                _GIF_WARNED_USERS.add(user_id)
                await bot.reply(msg, "该表情包为动态图，暂不支持发送动态表情，已发送静态图片。")
            return (
                f"Sticker id={sticker_id} sent (static — animated GIF not supported by API). "
                f"[提示：该表情包为动态图，已发送静态版本]"
            )

        return f"Sticker id={sticker_id} sent successfully."
