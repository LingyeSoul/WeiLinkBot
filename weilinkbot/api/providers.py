"""LLM provider CRUD API endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..i18n import t
from ..models import Provider, LLMPreset, encrypt_provider_api_key
from ..schemas import (
    ProviderCreate,
    ProviderUpdate,
    ProviderResponse,
    LLMPresetResponse,
    MessageAction,
)
from ..services.ws_service import get_ws_service

router = APIRouter()


async def _broadcast_providers(db):
    """Broadcast updated providers list to all WebSocket clients."""
    stmt = select(Provider).order_by(Provider.id)
    result = await db.execute(stmt)
    providers = result.scalars().all()
    await get_ws_service().broadcast(
        "providers",
        [
            ProviderResponse(
                **{k: getattr(p, k) for k in ProviderResponse.model_fields if k != "api_key_set"},
                api_key_set=bool(p.api_key),
            ).model_dump(mode="json")
            for p in providers
        ],
    )


@router.get("", response_model=list[ProviderResponse])
async def list_providers(db: AsyncSession = Depends(get_db)):
    """List all providers."""
    stmt = select(Provider).order_by(Provider.id)
    result = await db.execute(stmt)
    providers = result.scalars().all()
    return [
        ProviderResponse(
            **{k: getattr(p, k) for k in ProviderResponse.model_fields if k != "api_key_set"},
            api_key_set=bool(p.api_key),
        )
        for p in providers
    ]


@router.post("", response_model=ProviderResponse, status_code=201)
async def create_provider(data: ProviderCreate, db: AsyncSession = Depends(get_db)):
    """Create a new provider."""
    existing = await db.execute(
        select(Provider).where(Provider.name == data.name)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail=t("api.provider_exists"))

    provider = Provider(**data.model_dump())
    if provider.api_key:
        provider.api_key, provider.api_key_encrypted = encrypt_provider_api_key(provider.api_key)
    db.add(provider)
    await db.flush()
    await _broadcast_providers(db)
    return ProviderResponse(
        **{k: getattr(provider, k) for k in ProviderResponse.model_fields if k != "api_key_set"},
        api_key_set=bool(provider.api_key),
    )


@router.get("/{provider_id}", response_model=ProviderResponse)
async def get_provider(provider_id: int, db: AsyncSession = Depends(get_db)):
    """Get a single provider by ID."""
    provider = await db.get(Provider, provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail=t("api.provider_not_found"))
    return ProviderResponse(
        **{k: getattr(provider, k) for k in ProviderResponse.model_fields if k != "api_key_set"},
        api_key_set=bool(provider.api_key),
    )


@router.put("/{provider_id}", response_model=ProviderResponse)
async def update_provider(
    provider_id: int,
    data: ProviderUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Update a provider."""
    provider = await db.get(Provider, provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail=t("api.provider_not_found"))

    if data.name is not None:
        existing = await db.execute(
            select(Provider).where(Provider.name == data.name, Provider.id != provider_id)
        )
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=409, detail=t("api.provider_exists"))
        provider.name = data.name

    for field in ["provider_type", "base_url", "description"]:
        val = getattr(data, field)
        if val is not None:
            setattr(provider, field, val.strip() if isinstance(val, str) else val)

    if data.is_enabled is not None:
        provider.is_enabled = data.is_enabled

    if data.api_key is not None:
        provider.api_key, provider.api_key_encrypted = encrypt_provider_api_key(data.api_key.strip())

    await db.flush()
    await _broadcast_providers(db)
    return ProviderResponse(
        **{k: getattr(provider, k) for k in ProviderResponse.model_fields if k != "api_key_set"},
        api_key_set=bool(provider.api_key),
    )


@router.delete("/{provider_id}", response_model=MessageAction)
async def delete_provider(provider_id: int, db: AsyncSession = Depends(get_db)):
    """Delete a provider."""
    provider = await db.get(Provider, provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail=t("api.provider_not_found"))

    existing = await db.execute(
        select(LLMPreset).where(LLMPreset.provider_id == provider_id)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail=t("api.provider_in_use"))

    await db.delete(provider)
    await db.flush()
    await _broadcast_providers(db)
    return MessageAction(message=t("api.deleted_provider", name=provider.name))


@router.get("/{provider_id}/models", response_model=list[LLMPresetResponse])
async def list_provider_models(provider_id: int, db: AsyncSession = Depends(get_db)):
    """List LLMPresets that reference this provider."""
    provider = await db.get(Provider, provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail=t("api.provider_not_found"))

    stmt = select(LLMPreset).where(LLMPreset.provider_id == provider_id).order_by(LLMPreset.id)
    result = await db.execute(stmt)
    presets = result.scalars().all()
    return [
        LLMPresetResponse(
            **{k: getattr(p, k) for k in LLMPresetResponse.model_fields if k != "api_key_set"},
            api_key_set=bool(p.api_key),
        )
        for p in presets
    ]