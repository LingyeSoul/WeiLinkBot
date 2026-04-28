"""LLM and bot configuration API endpoints."""

from __future__ import annotations

from fastapi import APIRouter

from ..config import get_config, LLM_PRESETS
from ..schemas import LLMConfigResponse, LLMConfigUpdate, MessageAction
from .deps import get_bot_service

router = APIRouter()


@router.get("", response_model=LLMConfigResponse)
async def get_llm_config():
    """Get current LLM configuration (API key is masked)."""
    config = get_config()
    return LLMConfigResponse(
        provider=config.llm.provider,
        base_url=config.llm.base_url,
        model=config.llm.model,
        max_tokens=config.llm.max_tokens,
        temperature=config.llm.temperature,
        api_key_set=bool(config.llm.api_key),
    )


@router.put("", response_model=MessageAction)
async def update_llm_config(data: LLMConfigUpdate):
    """Update LLM configuration. Changes take effect immediately."""
    config = get_config()
    bot = get_bot_service()
    llm = bot.llm

    if data.provider is not None:
        llm.apply_preset(data.provider, config.llm)
    if data.api_key is not None:
        config.llm.api_key = data.api_key
    if data.base_url is not None:
        config.llm.base_url = data.base_url
    if data.model is not None:
        config.llm.model = data.model
    if data.max_tokens is not None:
        config.llm.max_tokens = data.max_tokens
    if data.temperature is not None:
        config.llm.temperature = data.temperature

    # Hot-reload LLM service
    llm.update_config(config.llm)
    return MessageAction(message="LLM config updated")


@router.get("/presets")
async def get_presets():
    """Get available LLM provider presets."""
    return LLM_PRESETS
