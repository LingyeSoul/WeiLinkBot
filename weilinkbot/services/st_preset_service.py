"""SillyTavern preset CRUD and system prompt management."""

from __future__ import annotations

import json

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import STPreset, SystemPrompt


def parse_st_preset_json(raw_json: str) -> dict:
    """Extract key fields from SillyTavern preset JSON."""
    data = json.loads(raw_json)
    system_prompt = ""

    if isinstance(data, list):
        for entry in data:
            if isinstance(entry, dict):
                name = entry.get("name", "").lower()
                if "system" in name or entry.get("role") == "system":
                    system_prompt = entry.get("content", "")


    elif isinstance(data, dict):
        system_prompt = data.get("system_prompt", "")

    return {"system_prompt": system_prompt}


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