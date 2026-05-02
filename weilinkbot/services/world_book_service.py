"""SillyTavern world book (lorebook) CRUD and text matching."""

from __future__ import annotations

import json

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..models import WorldBook, WorldBookEntry


def parse_st_world_book_json(raw_json: str) -> list[dict]:
    """Extract entries from SillyTavern world book JSON."""
    data = json.loads(raw_json)
    entries_data = data.get("entries", {})
    result = []
    if isinstance(entries_data, dict):
        for _key, entry in entries_data.items():
            if isinstance(entry, dict):
                keys = entry.get("key", [])
                key_primary = ",".join(keys) if isinstance(keys, list) else str(keys)
                key_secondary = entry.get("keysecondary", [])
                key_sec_str = ",".join(key_secondary) if isinstance(key_secondary, list) else str(key_secondary) if key_secondary else None
                result.append({
                    "key_primary": key_primary,
                    "key_secondary": key_sec_str,
                    "content": entry.get("content", ""),
                    "comment": entry.get("comment") or None,
                    "enabled": entry.get("enabled", True),
                    "position": str(entry.get("position", "before_char")),
                    "insertion_order": entry.get("insertion_order", 100),
                    "case_sensitive": entry.get("case_sensitive", False),
                    "selective": entry.get("selective", False),
                    "constant": entry.get("constant", False),
                    "priority": entry.get("priority", 10),
                })
    elif isinstance(entries_data, list):
        for entry in entries_data:
            if isinstance(entry, dict):
                keys = entry.get("key", [])
                key_primary = ",".join(keys) if isinstance(keys, list) else str(keys)
                result.append({
                    "key_primary": key_primary,
                    "content": entry.get("content", ""),
                    "enabled": entry.get("enabled", True),
                    "position": str(entry.get("position", "before_char")),
                    "insertion_order": entry.get("insertion_order", 100),
                })
    return result


class WorldBookService:
    """Manages SillyTavern world books (lorebooks) in the database."""

    def __init__(self, session: AsyncSession) -> None:
        self._db = session

    async def list_world_books(self) -> list[WorldBook]:
        stmt = select(WorldBook).options(selectinload(WorldBook.entries)).order_by(WorldBook.is_active.desc(), WorldBook.id)
        result = await self._db.execute(stmt)
        return list(result.scalars().all())

    async def get_world_book(self, wb_id: int) -> WorldBook | None:
        stmt = select(WorldBook).options(selectinload(WorldBook.entries)).where(WorldBook.id == wb_id)
        result = await self._db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_world_book_by_name(self, name: str) -> WorldBook | None:
        stmt = select(WorldBook).options(selectinload(WorldBook.entries)).where(WorldBook.name == name)
        result = await self._db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_active_world_book(self) -> WorldBook | None:
        stmt = select(WorldBook).options(selectinload(WorldBook.entries)).where(WorldBook.is_active == True)
        result = await self._db.execute(stmt)
        return result.scalar_one_or_none()

    async def create_world_book(self, data: dict) -> WorldBook:
        entries_data = parse_st_world_book_json(data["raw_json"])
        world_book = WorldBook(
            name=data["name"],
            description=data.get("description", ""),
            raw_json=data["raw_json"],
        )
        self._db.add(world_book)
        await self._db.flush()
        for entry_data in entries_data:
            entry = WorldBookEntry(world_book_id=world_book.id, **entry_data)
            self._db.add(entry)
        await self._db.flush()
        stmt = select(WorldBook).options(selectinload(WorldBook.entries)).where(WorldBook.id == world_book.id)
        result = await self._db.execute(stmt)
        return result.scalar_one()

    async def update_world_book(self, wb_id: int, data: dict) -> WorldBook | None:
        world_book = await self.get_world_book(wb_id)
        if not world_book:
            return None
        if "raw_json" in data and data["raw_json"] is not None:
            world_book.raw_json = data["raw_json"]
            entries_data = parse_st_world_book_json(data["raw_json"])
            for entry in world_book.entries:
                await self._db.delete(entry)
            await self._db.flush()
            for entry_data in entries_data:
                entry = WorldBookEntry(world_book_id=world_book.id, **entry_data)
                self._db.add(entry)
        for key in ("name", "description"):
            if key in data and data[key] is not None and hasattr(world_book, key):
                setattr(world_book, key, data[key])
        await self._db.flush()
        return world_book

    async def delete_world_book(self, wb_id: int) -> bool:
        world_book = await self.get_world_book(wb_id)
        if not world_book:
            return False
        await self._db.delete(world_book)
        await self._db.flush()
        return True

    async def activate_world_book(self, wb_id: int) -> WorldBook | None:
        world_book = await self.get_world_book(wb_id)
        if not world_book:
            return None
        await self._db.execute(
            update(WorldBook).where(WorldBook.is_active == True).values(is_active=False)
        )
        world_book.is_active = True
        await self._db.flush()
        return world_book

    async def deactivate_world_book(self) -> None:
        await self._db.execute(
            update(WorldBook).where(WorldBook.is_active == True).values(is_active=False)
        )
        await self._db.flush()

    async def match_entries(self, text: str) -> list[WorldBookEntry]:
        import logging
        logger = logging.getLogger(__name__)

        world_book = await self.get_active_world_book()
        if not world_book:
            logger.debug("[WorldBook] No active world book found")
            return []

        logger.debug("[WorldBook] Matching against '%s' (active book: '%s', %d entries)", text[:50], world_book.name, len(world_book.entries))

        all_entries: list[WorldBookEntry] = []
        constant_entries: list[WorldBookEntry] = []
        for entry in world_book.entries:
            if not entry.enabled:
                logger.debug("[WorldBook] Skipping disabled entry: %s", entry.comment or entry.key_primary[:30])
                continue
            if entry.constant:
                constant_entries.append(entry)
            else:
                all_entries.append(entry)

        matched: list[WorldBookEntry] = []
        text_lower = text.lower()
        for entry in all_entries:
            keywords = [k.strip() for k in entry.key_primary.split(",") if k.strip()]
            if not keywords:
                logger.debug("[WorldBook] Skipping entry with no keywords: %s", entry.comment or "(no comment)")
                continue
            if entry.case_sensitive:
                keywords_lower = keywords
                search_text = text
            else:
                keywords_lower = [k.lower() for k in keywords]
                search_text = text_lower
            hit_kw = next((kw for kw in keywords_lower if kw in search_text), None)
            if not hit_kw:
                logger.debug("[WorldBook] No match for entry '%s' — keywords: %s", entry.comment or entry.key_primary[:30], keywords_lower)
                continue
            if entry.selective and entry.key_secondary:
                sec_keywords = [k.strip() for k in entry.key_secondary.split(",") if k.strip()]
                if entry.case_sensitive:
                    sec_search = text
                else:
                    sec_search = text_lower
                if not any(sk for sk in sec_keywords if sk in sec_search):
                    logger.debug("[WorldBook] Selective entry '%s' skipped — secondary keywords not found", entry.comment or entry.key_primary[:30])
                    continue
            logger.info("[WorldBook] MATCHED entry '%s' via keyword '%s'", entry.comment or entry.key_primary[:30], hit_kw)
            matched.append(entry)
        matched.sort(key=lambda e: e.insertion_order)
        matched = constant_entries + matched
        logger.info("[WorldBook] Total matched entries: %d (constant=%d, keyword=%d)", len(matched), len(constant_entries), len(matched) - len(constant_entries))
        return matched