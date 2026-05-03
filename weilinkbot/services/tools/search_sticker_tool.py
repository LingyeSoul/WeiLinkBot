"""search_sticker tool — search sticker pack library by keyword."""

from __future__ import annotations

from typing import Any

from .base import Tool


class SearchStickerTool(Tool):
    name = "search_sticker"
    description = (
        "Search the sticker pack library by keyword to find matching stickers. "
        "Returns the top matching stickers with their descriptions. "
        "Use this when you want to send a sticker/emoji to the user."
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "keyword": {
                "type": "string",
                "description": "Search keyword to match against sticker text descriptions (e.g. 'happy', 'sad', 'angry').",
            },
        },
        "required": ["keyword"],
        "additionalProperties": False,
    }

    def __init__(self, session_factory):
        self._session_factory = session_factory

    async def execute(self, *, keyword: str, **kwargs) -> str:
        from ...services.sticker_service import StickerService

        async with self._session_factory() as db:
            service = StickerService(db)
            results = await service.search_stickers(keyword)

        if not results:
            return f"No stickers found for keyword '{keyword}'."

        lines = [f"Found {len(results)} sticker(s) for '{keyword}':"]
        for r in results:
            lines.append(
                f"- [{r['pack_name']}] id={r['sticker_id']}: {r['text_description']} (file: {r['file_path']})"
            )
        lines.append("Use the file_path to send the sticker image to the user.")
        return "\n".join(lines)
