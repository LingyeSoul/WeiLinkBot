"""Bot control API endpoints."""

from __future__ import annotations

from fastapi import APIRouter

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
    )


@router.post("/start", response_model=MessageAction)
async def bot_start():
    """Start the bot (login + begin polling)."""
    bot = get_bot_service()
    await bot.start()
    return MessageAction(message="Bot start initiated")


@router.post("/stop", response_model=MessageAction)
async def bot_stop():
    """Stop the bot."""
    bot = get_bot_service()
    await bot.stop()
    return MessageAction(message="Bot stopped")
