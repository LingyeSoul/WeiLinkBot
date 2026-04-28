"""Token usage statistics API endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..services.conversation_service import ConversationService

router = APIRouter()


@router.get("/tokens")
async def token_stats(db: AsyncSession = Depends(get_db)):
    """Get global token usage statistics grouped by model."""
    service = ConversationService(db)
    return await service.get_token_stats()


@router.get("/tokens/{user_id}")
async def user_token_stats(user_id: str, db: AsyncSession = Depends(get_db)):
    """Get token usage statistics for a specific user."""
    service = ConversationService(db)
    return await service.get_user_token_stats(user_id)
