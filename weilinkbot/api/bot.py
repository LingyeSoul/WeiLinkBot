"""Bot control API endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import LLMPreset
from ..i18n import t
from ..schemas import BotStatusResponse, MessageAction
from .deps import get_bot_service

router = APIRouter()


@router.get("/status", response_model=BotStatusResponse)
async def bot_status(db: AsyncSession = Depends(get_db)):
    """Get current bot status."""
    bot = get_bot_service()
    creds = bot.credentials
    result = await db.execute(select(LLMPreset).where(LLMPreset.is_active == True))
    active_preset = result.scalar_one_or_none()
    # Resolve model display names for session token stats
    session_stats = bot.session_token_stats
    preset_rows = await db.execute(
        select(LLMPreset.model, LLMPreset.name).where(LLMPreset.model.isnot(None))
    )
    name_map = {row.model: row.name for row in preset_rows.all()}
    for m in session_stats.get("models", []):
        m["name"] = name_map.get(m["model"], m["model"])

    return BotStatusResponse(
        status=bot.state.value,
        login_url=bot.login_url,
        error=bot.error,
        user_id=creds.user_id if creds else None,
        account_id=creds.account_id if creds else None,
        active_model_name=active_preset.name if active_preset else None,
        active_model=bot.llm.config.model,
        uptime_seconds=bot.uptime_seconds,
        session_messages=bot.message_count,
        session_token_stats=session_stats,
    )


@router.post("/start", response_model=MessageAction)
async def bot_start():
    """Start the bot (login + begin polling)."""
    bot = get_bot_service()
    await bot.start()
    return MessageAction(message=t("api.bot_start_initiated"))


@router.post("/stop", response_model=MessageAction)
async def bot_stop():
    """Stop the bot."""
    bot = get_bot_service()
    await bot.stop()
    return MessageAction(message=t("api.bot_stopped"))


@router.post("/unbind", response_model=MessageAction)
async def bot_unbind():
    """Unbind current WeChat account and restart with a fresh QR login."""
    bot = get_bot_service()
    await bot.unbind_and_relogin()
    return MessageAction(message=t("api.bot_unbound"))
