"""LLM model preset CRUD API endpoints."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import LLMPreset
from ..schemas import (
    LLMPresetCreate,
    LLMPresetUpdate,
    LLMPresetResponse,
    MessageAction,
)
from .deps import get_bot_service

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("", response_model=list[LLMPresetResponse])
async def list_presets(db: AsyncSession = Depends(get_db)):
    """List all LLM model presets."""
    stmt = select(LLMPreset).order_by(LLMPreset.is_active.desc(), LLMPreset.id)
    result = await db.execute(stmt)
    presets = result.scalars().all()
    return [
        LLMPresetResponse(
            **{k: getattr(p, k) for k in LLMPresetResponse.model_fields if k != "api_key_set"},
            api_key_set=bool(p.api_key),
        )
        for p in presets
    ]


@router.post("", response_model=LLMPresetResponse, status_code=201)
async def create_preset(data: LLMPresetCreate, db: AsyncSession = Depends(get_db)):
    """Create a new LLM model preset."""
    existing = await db.execute(
        select(LLMPreset).where(LLMPreset.name == data.name)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Preset name already exists")

    if data.is_active:
        await db.execute(
            update(LLMPreset).where(LLMPreset.is_active == True).values(is_active=False)
        )

    preset = LLMPreset(**data.model_dump())
    db.add(preset)
    await db.flush()

    if data.is_active:
        _activate_preset_in_service(preset)

    return LLMPresetResponse(
        **{k: getattr(preset, k) for k in LLMPresetResponse.model_fields if k != "api_key_set"},
        api_key_set=bool(preset.api_key),
    )


@router.get("/{preset_id}", response_model=LLMPresetResponse)
async def get_preset(preset_id: int, db: AsyncSession = Depends(get_db)):
    """Get a single LLM preset by ID."""
    preset = await db.get(LLMPreset, preset_id)
    if not preset:
        raise HTTPException(status_code=404, detail="Preset not found")
    return LLMPresetResponse(
        **{k: getattr(preset, k) for k in LLMPresetResponse.model_fields if k != "api_key_set"},
        api_key_set=bool(preset.api_key),
    )


@router.put("/{preset_id}", response_model=LLMPresetResponse)
async def update_preset(
    preset_id: int,
    data: LLMPresetUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Update an LLM preset."""
    preset = await db.get(LLMPreset, preset_id)
    if not preset:
        raise HTTPException(status_code=404, detail="Preset not found")

    if data.name is not None:
        existing = await db.execute(
            select(LLMPreset).where(LLMPreset.name == data.name, LLMPreset.id != preset_id)
        )
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=409, detail="Preset name already exists")
        preset.name = data.name

    for field in ["provider", "api_key", "base_url", "model", "max_tokens", "temperature"]:
        val = getattr(data, field)
        if val is not None:
            setattr(preset, field, val.strip() if isinstance(val, str) else val)

    was_active = preset.is_active
    if data.is_active is not None and data.is_active and not was_active:
        await db.execute(
            update(LLMPreset).where(LLMPreset.is_active == True).values(is_active=False)
        )
        preset.is_active = True
        _activate_preset_in_service(preset)
    elif data.is_active is not None:
        preset.is_active = data.is_active

    # If editing the currently active preset, hot-reload
    if preset.is_active:
        _activate_preset_in_service(preset)

    await db.flush()
    return LLMPresetResponse(
        **{k: getattr(preset, k) for k in LLMPresetResponse.model_fields if k != "api_key_set"},
        api_key_set=bool(preset.api_key),
    )


@router.delete("/{preset_id}", response_model=MessageAction)
async def delete_preset(preset_id: int, db: AsyncSession = Depends(get_db)):
    """Delete an LLM preset."""
    preset = await db.get(LLMPreset, preset_id)
    if not preset:
        raise HTTPException(status_code=404, detail="Preset not found")
    if preset.is_active:
        raise HTTPException(status_code=400, detail="Cannot delete the active preset. Switch to another first.")
    await db.delete(preset)
    await db.flush()
    return MessageAction(message=f"Deleted preset '{preset.name}'")


@router.post("/{preset_id}/activate", response_model=MessageAction)
async def activate_preset(preset_id: int, db: AsyncSession = Depends(get_db)):
    """Activate an LLM preset (deactivates all others)."""
    preset = await db.get(LLMPreset, preset_id)
    if not preset:
        raise HTTPException(status_code=404, detail="Preset not found")

    await db.execute(
        update(LLMPreset).where(LLMPreset.is_active == True).values(is_active=False)
    )
    preset.is_active = True
    await db.flush()

    _activate_preset_in_service(preset)
    logger.info("Activated preset: %s (model=%s)", preset.name, preset.model)
    return MessageAction(message=f"Switched to '{preset.name}' ({preset.model})")


def _activate_preset_in_service(preset: LLMPreset) -> None:
    """Apply a preset to the running LLM service."""
    from ..config import LLMConfig
    try:
        bot = get_bot_service()
        config = LLMConfig(
            provider=preset.provider,
            api_key=preset.api_key,
            base_url=preset.base_url,
            model=preset.model,
            max_tokens=preset.max_tokens,
            temperature=preset.temperature,
        )
        bot.llm.update_config(config)
    except RuntimeError:
        pass  # Bot service not yet initialized
