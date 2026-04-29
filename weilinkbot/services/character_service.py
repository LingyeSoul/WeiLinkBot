"""Character card CRUD, SillyTavern import/export, and prompt assembly."""

from __future__ import annotations

import base64
import binascii
import json
import logging
import struct
from pathlib import Path
from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import CharacterCard, SystemPrompt

logger = logging.getLogger(__name__)

AVATARS_DIR = Path("data/characters/avatars")


def assemble_st_prompt(card: CharacterCard) -> str:
    """Assemble a SillyTavern-format system prompt from character card fields."""
    parts = [f'[character("{card.name}")]']

    if card.description:
        parts.append(f'[description("{card.description}")]')
    if card.personality:
        parts.append(f'[personality("{card.personality}")]')
    if card.scenario:
        parts.append(f'[scenario("{card.scenario}")]')

    parts.append("<START>")

    if card.first_mes:
        parts.append(f"{{{{char}}}}: {card.first_mes}")

    if card.mes_example:
        parts.append(card.mes_example)

    return "\n".join(parts)


def parse_st_json(data: dict) -> dict:
    """Extract SillyTavern character card fields from a JSON dict.

    Supports both V2 (spec) and V1 (TavernAI legacy) formats.
    """
    # V2 spec wraps data in "data" key; V1 has fields at top level
    char = data.get("data", data)

    return {
        "name": char.get("name", data.get("name", "Unknown")),
        "description": char.get("description", ""),
        "personality": char.get("personality", ""),
        "scenario": char.get("scenario", ""),
        "first_mes": char.get("first_mes"),
        "mes_example": char.get("mes_example"),
    }


def parse_png_character(data: bytes) -> Optional[dict]:
    """Extract character card JSON from a PNG file's tEXt 'chara' chunk.

    SillyTavern embeds character data as Base64-encoded JSON in a PNG tEXt chunk
    with the keyword 'chara'.
    """
    # Verify PNG signature
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        return None

    offset = 8
    while offset < len(data):
        if offset + 8 > len(data):
            break
        length = struct.unpack(">I", data[offset:offset + 4])[0]
        chunk_type = data[offset + 4:offset + 8]

        if chunk_type == b"tEXt":
            chunk_data = data[offset + 8:offset + 8 + length]
            # tEXt format: keyword \0 text
            null_pos = chunk_data.find(b"\0")
            if null_pos != -1:
                keyword = chunk_data[:null_pos].decode("latin-1", errors="replace")
                if keyword == "chara":
                    b64_text = chunk_data[null_pos + 1:].decode("latin-1", errors="replace")
                    try:
                        decoded = base64.b64decode(b64_text)
                        json_data = json.loads(decoded)
                        return parse_st_json(json_data)
                    except Exception as e:
                        logger.error("Failed to decode 'chara' chunk: %s", e)
                        return None

        # Skip past chunk: 4 (length) + 4 (type) + length + 4 (CRC)
        offset += 12 + length

    return None


def export_st_json(card: CharacterCard) -> bytes:
    """Export a character card as SillyTavern V2 JSON."""
    data = {
        "name": card.name,
        "description": card.description or "",
        "personality": card.personality or "",
        "scenario": card.scenario or "",
        "first_mes": card.first_mes or "",
        "mes_example": card.mes_example or "",
        "system_prompt": "",
        "tags": [],
        "creator": "WeiLinkBot",
        "character_version": "1.0",
    }
    result = {
        "spec": "chara_card_v2",
        "spec_version": "2.0",
        "data": data,
    }
    return json.dumps(result, ensure_ascii=False, indent=2).encode("utf-8")


def _make_png_chunk(chunk_type: bytes, data: bytes) -> bytes:
    """Build a PNG chunk with correct CRC."""
    length = struct.pack(">I", len(data))
    crc = binascii.crc32(chunk_type + data) & 0xFFFFFFFF
    return length + chunk_type + data + struct.pack(">I", crc)


def export_st_png(card: CharacterCard, base_png: Optional[bytes] = None) -> bytes:
    """Export a character card as PNG with embedded character data in tEXt 'chara' chunk.

    If base_png is provided, embed into that image. Otherwise create a minimal 1x1 white PNG.
    """
    # Build character card JSON (same as export_st_json but without outer wrapper for ST compat)
    card_data = {
        "name": card.name,
        "description": card.description or "",
        "personality": card.personality or "",
        "scenario": card.scenario or "",
        "first_mes": card.first_mes or "",
        "mes_example": card.mes_example or "",
        "system_prompt": "",
        "tags": [],
        "creator": "WeiLinkBot",
        "character_version": "1.0",
    }
    card_json = json.dumps(
        {"spec": "chara_card_v2", "spec_version": "2.0", "data": card_data},
        ensure_ascii=False,
    )
    b64_data = base64.b64encode(card_json.encode("utf-8")).decode("ascii")

    # Build tEXt chunk: keyword \0 base64_text
    text_payload = b"chara\x00" + b64_data.encode("ascii")
    text_chunk = _make_png_chunk(b"tEXt", text_payload)

    if base_png and base_png[:8] == b"\x89PNG\r\n\x1a\n":
        # Strip existing tEXt 'chara' chunks from base image
        chunks = [base_png[:8]]  # PNG signature
        offset = 8
        while offset < len(base_png):
            if offset + 8 > len(base_png):
                break
            length = struct.unpack(">I", base_png[offset:offset + 4])[0]
            chunk_type = base_png[offset + 4:offset + 8]
            chunk_data = base_png[offset + 8:offset + 8 + length]
            crc = base_png[offset + 8 + length:offset + 12 + length]
            offset += 12 + length

            # Skip old tEXt 'chara' chunks
            if chunk_type == b"tEXt":
                null_pos = chunk_data.find(b"\0")
                if null_pos != -1 and chunk_data[:null_pos] == b"chara":
                    continue

            if chunk_type == b"IEND":
                # Insert new tEXt chunk before IEND
                chunks.append(text_chunk)

            chunks.append(
                struct.pack(">I", len(chunk_data)) + chunk_type + chunk_data + crc
            )

        return b"".join(chunks)

    # Generate minimal 1x1 white PNG
    def _minimal_png() -> bytes:
        sig = b"\x89PNG\r\n\x1a\n"
        ihdr_data = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
        ihdr = _make_png_chunk(b"IHDR", ihdr_data)
        import zlib
        raw = b"\x00\xff\xff\xff"  # filter-byte + white RGB pixel
        compressed = zlib.compress(raw)
        idat = _make_png_chunk(b"IDAT", compressed)
        iend = _make_png_chunk(b"IEND", b"")
        return sig + ihdr + idat + text_chunk + iend

    return _minimal_png()


class CharacterService:
    """Manages character cards in the database."""

    def __init__(self, session: AsyncSession) -> None:
        self._db = session

    async def list_characters(self) -> list[CharacterCard]:
        stmt = select(CharacterCard).order_by(CharacterCard.is_active.desc(), CharacterCard.id)
        result = await self._db.execute(stmt)
        return list(result.scalars().all())

    async def get_character(self, char_id: int) -> Optional[CharacterCard]:
        return await self._db.get(CharacterCard, char_id)

    async def get_character_by_name(self, name: str) -> Optional[CharacterCard]:
        stmt = select(CharacterCard).where(CharacterCard.name == name)
        result = await self._db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_active_character(self) -> Optional[CharacterCard]:
        stmt = select(CharacterCard).where(CharacterCard.is_active == True)
        result = await self._db.execute(stmt)
        return result.scalar_one_or_none()

    async def create_character(self, data: dict) -> CharacterCard:
        card = CharacterCard(**data)
        self._db.add(card)
        await self._db.flush()
        return card

    async def update_character(self, char_id: int, data: dict) -> Optional[CharacterCard]:
        card = await self.get_character(char_id)
        if not card:
            return None
        for key, value in data.items():
            if hasattr(card, key):
                setattr(card, key, value)
        await self._db.flush()
        return card

    async def delete_character(self, char_id: int) -> bool:
        card = await self.get_character(char_id)
        if not card:
            return False
        # Delete avatar file if exists
        if card.avatar_path:
            avatar = Path("data") / card.avatar_path
            if avatar.exists():
                avatar.unlink()
        await self._db.delete(card)
        await self._db.flush()
        return True

    async def activate_character(self, char_id: int) -> Optional[CharacterCard]:
        """Activate a character: set as active, deactivate others, assemble + write system prompt."""
        card = await self.get_character(char_id)
        if not card:
            return None

        # Deactivate all
        await self._db.execute(
            update(CharacterCard).where(CharacterCard.is_active == True).values(is_active=False)
        )
        card.is_active = True

        # Assemble prompt and write to system_prompts as default
        prompt_content = assemble_st_prompt(card)
        await self._set_default_system_prompt(f"[角色] {card.name}", prompt_content)

        await self._db.flush()
        return card

    async def deactivate_character(self) -> None:
        """Deactivate current character and restore default assistant prompt."""
        await self._db.execute(
            update(CharacterCard).where(CharacterCard.is_active == True).values(is_active=False)
        )
        await self._set_default_system_prompt(
            "Default",
            "You are a helpful AI assistant. Reply concisely and helpfully.",
        )
        await self._db.flush()

    async def _set_default_system_prompt(self, name: str, content: str) -> None:
        """Create or update the default system prompt."""
        # Unset all defaults
        await self._db.execute(
            update(SystemPrompt).where(SystemPrompt.is_default == True).values(is_default=False)
        )
        # Check if a prompt with this name exists
        stmt = select(SystemPrompt).where(SystemPrompt.name == name)
        result = await self._db.execute(stmt)
        prompt = result.scalar_one_or_none()
        if prompt:
            prompt.content = content
            prompt.is_default = True
        else:
            prompt = SystemPrompt(name=name, content=content, is_default=True)
            self._db.add(prompt)

    _ALLOWED_AVATAR_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}

    async def save_avatar(self, char_id: int, file_data: bytes, filename: str) -> Optional[str]:
        """Save an avatar image file and return the path."""
        AVATARS_DIR.mkdir(parents=True, exist_ok=True)
        ext = Path(filename).suffix.lower() or ".png"
        if ext not in self._ALLOWED_AVATAR_EXTENSIONS:
            ext = ".png"
        avatar_filename = f"char_{char_id}{ext}"
        avatar_path = AVATARS_DIR / avatar_filename
        avatar_path.write_bytes(file_data)

        card = await self.get_character(char_id)
        if card:
            card.avatar_path = f"characters/avatars/{avatar_filename}"
            await self._db.flush()

        return str(avatar_path)
