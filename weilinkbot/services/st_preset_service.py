"""SillyTavern preset CRUD and system prompt management."""

from __future__ import annotations

import json

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import STPreset, SystemPrompt


def parse_st_preset_json(raw_json: str) -> dict:
    """Extract key fields from SillyTavern preset JSON.

    Collects ALL enabled entries whose role is "system" (or whose name
    contains "system") and concatenates them — SillyTavern presets commonly
    have multiple system entries (Main Prompt, NSFW/Smut, etc.).
    """
    data = json.loads(raw_json)
    parts: list[str] = []

    # Gather the entry list from either format
    entries: list[dict] = []
    if isinstance(data, list):
        entries = data
    elif isinstance(data, dict):
        if isinstance(data.get("prompts"), list):
            entries = data["prompts"]
        # Also honour a top-level system_prompt field (rare but exists)
        top = data.get("system_prompt", "")
        if top:
            parts.append(top)

    for entry in entries:
        if not isinstance(entry, dict) or not entry.get("enabled", True):
            continue
        name = entry.get("name", "").lower()
        if entry.get("role") == "system" or "system" in name:
            content = entry.get("content", "").strip()
            if content:
                parts.append(content)

    return {"system_prompt": "\n\n".join(parts)}


def parse_st_entries(raw_json: str) -> list[dict]:
    """Parse raw_json into structured entries for display.

    Handles two formats:
    - SillyTavern preset (dict with ``prompts`` list)
    - Raw prompt manager export (top-level list)
    """
    data = json.loads(raw_json)

    # SillyTavern preset format: object with a "prompts" array
    if isinstance(data, dict):
        items = data.get("prompts")
        if isinstance(items, list):
            data = items
        else:
            return []

    entries = []
    if isinstance(data, list):
        for i, entry in enumerate(data):
            if isinstance(entry, dict):
                entries.append({
                    "index": i,
                    "identifier": entry.get("identifier", ""),
                    "name": entry.get("name", f"Entry {i}"),
                    "content": entry.get("content", ""),
                    "enabled": entry.get("enabled", True),
                    "role": entry.get("role", ""),
                    "injection_position": entry.get("injection_position", 0),
                    "injection_depth": entry.get("injection_depth", 4),
                })
    return entries


class STPresetService:
    """Manages SillyTavern presets in the database."""

    def __init__(self, session: AsyncSession) -> None:
        self._db = session

    async def list_presets(self) -> list[STPreset]:
        stmt = select(STPreset).order_by(STPreset.is_active.desc(), STPreset.id)
        result = await self._db.execute(stmt)
        return list(result.scalars().all())

    async def get_preset(self, preset_id: int) -> STPreset | None:
        return await self._db.get(STPreset, preset_id)

    async def get_preset_by_name(self, name: str) -> STPreset | None:
        stmt = select(STPreset).where(STPreset.name == name)
        result = await self._db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_active_preset(self) -> STPreset | None:
        stmt = select(STPreset).where(STPreset.is_active == True)
        result = await self._db.execute(stmt)
        return result.scalar_one_or_none()

    async def create_preset(self, data: dict) -> STPreset:
        parsed = parse_st_preset_json(data["raw_json"])
        preset = STPreset(
            name=data["name"],
            raw_json=data["raw_json"],
            system_prompt=parsed["system_prompt"],

        )
        self._db.add(preset)
        await self._db.flush()
        return preset

    async def update_preset(self, preset_id: int, data: dict) -> STPreset | None:
        preset = await self.get_preset(preset_id)
        if not preset:
            return None
        for key, value in data.items():
            if key == "raw_json" and value is not None:
                setattr(preset, key, value)
                parsed = parse_st_preset_json(value)
                preset.system_prompt = parsed["system_prompt"]

            elif hasattr(preset, key):
                setattr(preset, key, value)
        await self._db.flush()
        return preset

    async def delete_preset(self, preset_id: int) -> bool:
        preset = await self.get_preset(preset_id)
        if not preset:
            return False
        await self._db.delete(preset)
        await self._db.flush()
        return True

    async def activate_preset(self, preset_id: int) -> STPreset | None:
        """Activate a preset without overwriting system prompt.
        
        Preset system prompt is combined during context building,
        not written directly to system_prompts table.
        """
        preset = await self.get_preset(preset_id)
        if not preset:
            return None
        await self._db.execute(
            update(STPreset).where(STPreset.is_active == True).values(is_active=False)
        )
        preset.is_active = True
        await self._db.flush()
        return preset

    async def deactivate_preset(self) -> None:
        """Deactivate current preset without modifying system prompts."""
        await self._db.execute(
            update(STPreset).where(STPreset.is_active == True).values(is_active=False)
        )
        await self._db.flush()

    async def toggle_entry(self, preset_id: int, entry_index: int, enabled: bool) -> list[dict] | None:
        """Toggle an entry's enabled state, update raw_json and re-parse system prompt."""
        preset = await self.get_preset(preset_id)
        if not preset:
            return None
        try:
            data = json.loads(preset.raw_json)
        except json.JSONDecodeError:
            return None

        # Resolve the actual entries list from either format
        if isinstance(data, dict):
            items = data.get("prompts")
            if not isinstance(items, list) or entry_index < 0 or entry_index >= len(items):
                return None
            items[entry_index]["enabled"] = enabled
        elif isinstance(data, list):
            if entry_index < 0 or entry_index >= len(data):
                return None
            data[entry_index]["enabled"] = enabled
        else:
            return None

        updated_json = json.dumps(data, ensure_ascii=False, indent=2)
        preset.raw_json = updated_json
        parsed = parse_st_preset_json(updated_json)
        preset.system_prompt = parsed["system_prompt"]
        await self._db.flush()
        return parse_st_entries(updated_json)

    async def _set_default_system_prompt(self, name: str, content: str) -> None:
        await self._db.execute(
            update(SystemPrompt).where(SystemPrompt.is_default == True).values(is_default=False)
        )
        stmt = select(SystemPrompt).where(SystemPrompt.name == name)
        result = await self._db.execute(stmt)
        prompt = result.scalar_one_or_none()
        if prompt:
            prompt.content = content
            prompt.is_default = True
        else:
            prompt = SystemPrompt(name=name, content=content, is_default=True)
            self._db.add(prompt)