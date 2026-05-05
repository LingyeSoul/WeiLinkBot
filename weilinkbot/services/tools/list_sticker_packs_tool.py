"""list_sticker_packs tool — browse sticker pack series and their contents."""

from __future__ import annotations

from typing import Any

from .base import Tool


class ListStickerPacksTool(Tool):
    name = "list_sticker_packs"
    description = (
        "List all sticker pack series, or list the stickers inside a specific pack. "
        "Call without arguments to see all available packs. "
        "Call with a pack_id to see the stickers in that pack."
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "pack_id": {
                "type": "integer",
                "description": (
                    "Optional pack ID to list stickers in a specific pack. "
                    "Omit to list all packs."
                ),
            },
        },
        "required": [],
        "additionalProperties": False,
    }

    def __init__(self, session_factory):
        self._session_factory = session_factory

    async def execute(self, *, pack_id: int | None = None, **kwargs) -> str:
        from ...services.sticker_service import StickerService

        async with self._session_factory() as db:
            service = StickerService(db)

            if pack_id is not None:
                pack = await service.get_pack(pack_id)
                if not pack:
                    return f"Sticker pack with id={pack_id} not found."

                stickers = sorted(pack.stickers, key=lambda s: s.sort_order)
                lines = [
                    f"Pack '{pack.name}' (id={pack.id}) — {len(stickers)} sticker(s)",
                ]
                if pack.description:
                    lines.append(f"Description: {pack.description}")
                for s in stickers:
                    lines.append(
                        f"- sticker_id={s.id}: {s.text_description or '(no description)'}"
                    )
                if stickers:
                    lines.append("Call send_sticker with one of the sticker_id values above to send a sticker.")
                return "\n".join(lines)

            packs = await service.list_packs()

        if not packs:
            return "No sticker packs found."

        lines = [f"Found {len(packs)} sticker pack(s):"]
        for p in packs:
            desc = f" — {p['description']}" if p.get("description") else ""
            lines.append(
                f"- id={p['id']}: {p['name']} ({p['sticker_count']} stickers){desc}"
            )
        lines.append("Call list_sticker_packs with a pack_id to see stickers in a specific pack.")
        return "\n".join(lines)
