"""Bot control API endpoints."""

from __future__ import annotations

from fastapi import APIRouter

from ..i18n import t
from ..schemas import BotStatusResponse, MessageAction
from .deps import get_bot_service

router = APIRouter()


@router.get("/status", response_model=BotStatusResponse)
async def bot_status():
    """Get current bot status."""
    bot = get_bot_service()
    creds = bot.credentials
    return BotStatusResponse(
        status=bot.state.value,
        login_url=bot.login_url,
        error=bot.error,
        user_id=creds.user_id if creds else None,
        account_id=creds.account_id if creds else None,
        active_model=bot.llm.config.model,
        uptime_seconds=bot.uptime_seconds,
        session_messages=bot.message_count,
        session_token_stats=bot.session_token_stats,
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
