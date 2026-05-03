"""send_sticker tool — read a sticker image from disk and send it via reply_media."""

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


class SendStickerTool(Tool):
    name = "send_sticker"
    description = (
        "Send a sticker image to the user. Call this after search_sticker "
        "to actually deliver the sticker. The sticker is sent as an image "
        "message (side-effect). Returns a confirmation string."
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "file_path": {
                "type": "string",
                "description": (
                    "The sticker file_path returned by search_sticker "
                    "(e.g. '1/42.png')."
                ),
            },
        },
        "required": ["file_path"],
        "additionalProperties": False,
    }

    async def execute(self, *, file_path: str, **kwargs) -> str:
        try:
            bot, msg = get_sticker_context()
        except LookupError:
            raise ToolExecutionError("send_sticker called outside a message context")

        # Path traversal guard: resolved path must stay inside STICKERS_DIR
        stickers_root = STICKERS_DIR.resolve()
        full_path = (STICKERS_DIR / file_path).resolve()
        if not (full_path == stickers_root or stickers_root in full_path.parents):
            raise ToolExecutionError(f"Invalid sticker path: {file_path}")

        if full_path.suffix.lower() not in _ALLOWED_EXTENSIONS:
            raise ToolExecutionError(f"Unsupported file type: {full_path.suffix}")

        if not full_path.exists():
            raise ToolExecutionError(f"Sticker file not found: {file_path}")

        if full_path.stat().st_size > _MAX_FILE_SIZE:
            raise ToolExecutionError(f"Sticker file too large: {full_path.stat().st_size} bytes")

        image_bytes = full_path.read_bytes()

        try:
            await bot.reply_media(msg, {"image": image_bytes})
        except Exception as e:
            raise ToolExecutionError(f"Failed to send sticker: {e}")

        logger.info("Sent sticker %s (%d bytes)", file_path, len(image_bytes))
        return f"Sticker {file_path} sent successfully."
