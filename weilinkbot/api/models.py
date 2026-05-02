"""LLM model preset CRUD API endpoints."""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..database import get_db
from ..i18n import t
from ..models import LLMPreset, Provider, resolve_provider_credentials
from ..schemas import (
    LLMPresetCreate,
    LLMPresetUpdate,
    LLMPresetResponse,
    MessageAction,
)
from .deps import get_bot_service
from ..services.ws_service import get_ws_service

logger = logging.getLogger(__name__)

router = APIRouter()


def _build_preset_response(preset: LLMPreset) -> LLMPresetResponse:
    """Build LLMPresetResponse from a preset, including provider_name if linked."""
    return LLMPresetResponse(
        id=preset.id,
        name=preset.name,
        provider=preset.provider,
        model=preset.model,
        max_tokens=preset.max_tokens,
        temperature=preset.temperature,
        is_active=preset.is_active,
        provider_id=preset.provider_id,
        provider_name=preset.provider_ref.name if preset.provider_ref else None,
        capability_text=preset.capability_text,
        capability_audio=preset.capability_audio,
        capability_image=preset.capability_image,
        preprocess_voice_model_id=preset.preprocess_voice_model_id,
        preprocess_image_model_id=preset.preprocess_image_model_id,
        preprocess_voice=preset.preprocess_voice,
        preprocess_image=preset.preprocess_image,
        voice_method=preset.voice_method,
        asr_language=preset.asr_language,
        created_at=preset.created_at,
    )


async def _load_preset_with_provider(preset_id: int, db: AsyncSession):
    """Load a preset with its provider eagerly loaded."""
    result = await db.execute(
        select(LLMPreset).where(LLMPreset.id == preset_id)
    )
    return result.scalar_one_or_none()


async def _broadcast_models(db):
    """Broadcast updated models list to all WebSocket clients."""
    stmt = select(LLMPreset).options(selectinload(LLMPreset.provider_ref)).order_by(LLMPreset.is_active.desc(), LLMPreset.id)
    result = await db.execute(stmt)
    presets = result.scalars().all()
    await get_ws_service().broadcast(
        "models",
        [_build_preset_response(p).model_dump(mode="json") for p in presets],
    )


@router.get("", response_model=list[LLMPresetResponse])
async def list_presets(db: AsyncSession = Depends(get_db)):
    """List all LLM model presets."""
    stmt = select(LLMPreset).options(selectinload(LLMPreset.provider_ref)).order_by(LLMPreset.is_active.desc(), LLMPreset.id)
    result = await db.execute(stmt)
    presets = result.scalars().all()
    return [_build_preset_response(p) for p in presets]


@router.post("", response_model=LLMPresetResponse, status_code=201)
async def create_preset(data: LLMPresetCreate, db: AsyncSession = Depends(get_db)):
    """Create a new LLM model preset."""
    existing = await db.execute(
        select(LLMPreset).where(LLMPreset.name == data.name)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail=t("api.preset_exists"))

    # Validate provider_id
    provider = await db.get(Provider, data.provider_id)
    if not provider:
        raise HTTPException(status_code=400, detail=t("api.provider_not_found"))
    if not provider.is_enabled:
        raise HTTPException(status_code=400, detail=t("api.provider_disabled"))

    if data.is_active:
        await db.execute(
            update(LLMPreset).where(LLMPreset.is_active == True).values(is_active=False)
        )

    preset = LLMPreset(**data.model_dump())
    # Set provider type from the linked Provider
    preset.provider = provider.provider_type
    db.add(preset)
    await db.flush()

    # Refresh to load provider_ref relationship
    await db.refresh(preset, ["provider_ref"])

    if data.is_active:
        await _activate_preset_in_service(preset, db)

    await _broadcast_models(db)
    return _build_preset_response(preset)


@router.get("/{preset_id}", response_model=LLMPresetResponse)
async def get_preset(preset_id: int, db: AsyncSession = Depends(get_db)):
    """Get a single LLM preset by ID."""
    result = await db.execute(
        select(LLMPreset).options(selectinload(LLMPreset.provider_ref)).where(LLMPreset.id == preset_id)
    )
    preset = result.scalar_one_or_none()
    if not preset:
        raise HTTPException(status_code=404, detail=t("api.preset_not_found"))
    return _build_preset_response(preset)


@router.put("/{preset_id}", response_model=LLMPresetResponse)
async def update_preset(
    preset_id: int,
    data: LLMPresetUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Update an LLM preset."""
    preset = await db.get(LLMPreset, preset_id)
    if not preset:
        raise HTTPException(status_code=404, detail=t("api.preset_not_found"))

    if data.name is not None:
        existing = await db.execute(
            select(LLMPreset).where(LLMPreset.name == data.name, LLMPreset.id != preset_id)
        )
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=409, detail=t("api.preset_exists"))
        preset.name = data.name

    # Validate provider_id if being changed
    if data.provider_id is not None:
        provider = await db.get(Provider, data.provider_id)
        if not provider:
            raise HTTPException(status_code=400, detail=t("api.provider_not_found"))
        if not provider.is_enabled:
            raise HTTPException(status_code=400, detail=t("api.provider_disabled"))
        preset.provider_id = data.provider_id
        preset.provider = provider.provider_type

    for field in [
        "model", "max_tokens", "temperature",
        "capability_text", "capability_audio", "capability_image",
        "preprocess_voice_model_id", "preprocess_image_model_id",
        "preprocess_voice", "preprocess_image",
        "voice_method", "asr_language",
    ]:
        val = getattr(data, field)
        if val is not None:
            setattr(preset, field, val.strip() if isinstance(val, str) else val)

    was_active = preset.is_active
    if data.is_active is not None and data.is_active and not was_active:
        await db.execute(
            update(LLMPreset).where(LLMPreset.is_active == True).values(is_active=False)
        )
        preset.is_active = True
        await _activate_preset_in_service(preset, db)
    elif data.is_active is not None:
        preset.is_active = data.is_active

    # If editing the currently active preset, hot-reload
    if preset.is_active:
        await _activate_preset_in_service(preset, db)

    await db.flush()
    await db.refresh(preset, ["provider_ref"])
    await _broadcast_models(db)
    return _build_preset_response(preset)


@router.delete("/{preset_id}", response_model=MessageAction)
async def delete_preset(preset_id: int, db: AsyncSession = Depends(get_db)):
    """Delete an LLM preset."""
    preset = await db.get(LLMPreset, preset_id)
    if not preset:
        raise HTTPException(status_code=404, detail=t("api.preset_not_found"))
    if preset.is_active:
        raise HTTPException(status_code=400, detail=t("api.cannot_delete_active"))
    await db.delete(preset)
    await db.flush()
    await _broadcast_models(db)
    return MessageAction(message=t("api.deleted_preset", name=preset.name))


@router.post("/{preset_id}/activate", response_model=MessageAction)
async def activate_preset(preset_id: int, db: AsyncSession = Depends(get_db)):
    """Activate an LLM preset (deactivates all others)."""
    preset = await db.get(LLMPreset, preset_id)
    if not preset:
        raise HTTPException(status_code=404, detail=t("api.preset_not_found"))

    await db.execute(
        update(LLMPreset).where(LLMPreset.is_active == True).values(is_active=False)
    )
    preset.is_active = True
    await db.flush()
    await db.refresh(preset, ["provider_ref"])

    await _activate_preset_in_service(preset, db)
    await _broadcast_models(db)
    logger.info("Activated preset: %s (model=%s)", preset.name, preset.model)
    return MessageAction(message=t("api.switched_preset", name=preset.name, model=preset.model))


async def _activate_preset_in_service(preset: LLMPreset, db: AsyncSession) -> None:
    """Apply a preset to the running LLM service, resolving credentials from Provider."""
    from ..config import LLMConfig
    try:
        provider_type, api_key, base_url = await resolve_provider_credentials(preset, db)
        bot = get_bot_service()
        config = LLMConfig(
            provider=provider_type,
            api_key=api_key,
            base_url=base_url,
            model=preset.model,
            max_tokens=preset.max_tokens,
            temperature=preset.temperature,
        )
        bot.llm.update_config(config)
        asyncio.create_task(bot._load_preprocess_config())
    except ValueError as e:
        logger.warning("Cannot activate preset '%s': %s", preset.name, e)
    except RuntimeError:
        pass  # Bot service not yet initialized
