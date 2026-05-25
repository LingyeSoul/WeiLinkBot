"""send_file — send a workspace file to the current WeChat user."""

from __future__ import annotations

import logging
from typing import Any

from .base import Tool, ToolExecutionError
from .sticker_context import get_sticker_context

logger = logging.getLogger(__name__)

_MAX_FILE_SIZE = 200 * 1024 * 1024  # 200 MB


class SendFileTool(Tool):
    name = "send_file"
    description = (
        "Send a file from the workspace to the current WeChat user. "
        "The SDK auto-detects file type: image extensions (.jpg, .png, etc.) "
        "are sent as images, video extensions (.mp4, etc.) as video, "
        "and everything else as a file attachment. "
        "Use this after browser_download to deliver downloaded files."
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": (
                    "Relative path of the file within the workspace "
                    "(e.g., 'downloads/report.pdf')."
                ),
            },
            "caption": {
                "type": "string",
                "description": "Optional caption or description to send with the file.",
            },
        },
        "required": ["path"],
        "additionalProperties": False,
    }

    def __init__(self, workspace_service) -> None:
        self._ws = workspace_service

    async def execute(
        self,
        *,
        path: str,
        caption: str | None = None,
        **kwargs,
    ) -> str:
        try:
            bot, msg = get_sticker_context()
        except LookupError:
            raise ToolExecutionError("send_file called outside a message context")

        # Resolve and validate path through sandbox
        abs_path = self._ws.sandbox.resolve(path)

        if not abs_path.exists():
            raise ToolExecutionError(f"File not found: {path}")
        if not abs_path.is_file():
            raise ToolExecutionError(f"Not a file: {path}")

        # Extension check
        self._ws.sandbox.check_extension(abs_path)

        # Size check
        file_size = abs_path.stat().st_size
        if file_size > _MAX_FILE_SIZE:
            raise ToolExecutionError(
                f"File too large: {file_size:,} bytes (max {_MAX_FILE_SIZE:,} bytes)"
            )
        if file_size == 0:
            raise ToolExecutionError("File is empty")

        # Read bytes and send
        file_bytes = abs_path.read_bytes()
        filename = abs_path.name

        content: dict[str, Any] = {"file": file_bytes, "file_name": filename}
        if caption:
            content["caption"] = caption

        try:
            await bot.reply_media(msg, content)
        except Exception as e:
            raise ToolExecutionError(f"Failed to send file: {e}")

        logger.info("Sent file '%s' (%d bytes) to user %s", filename, file_size, msg.user_id)
        return f"Sent '{filename}' ({file_size:,} bytes) to the user."
