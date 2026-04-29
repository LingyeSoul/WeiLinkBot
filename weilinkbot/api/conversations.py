"""Conversation and message API endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..i18n import t
from ..schemas import (
    ConversationResponse,
    ConversationDetailResponse,
    MessageResponse,
    MessageAction,
)
from ..services.conversation_service import ConversationService

router = APIRouter()


async def _get_service(db: AsyncSession = Depends(get_db)) -> ConversationService:
    return ConversationService(db)


@router.get("", response_model=list[ConversationResponse])
async def list_conversations(service: ConversationService = Depends(_get_service)):
    """List all conversations with last message preview."""
    return await service.list_conversations()


@router.get("/{user_id}", response_model=ConversationDetailResponse)
async def get_conversation(
    user_id: str,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    service: ConversationService = Depends(_get_service),
):
    """Get messages for a user's conversation."""
    from ..models import Conversation
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    stmt = (
        select(Conversation)
        .where(Conversation.user_id == user_id)
        .options(selectinload(Conversation.messages))
    )
    result = await service._db.execute(stmt)
    conv = result.scalar_one_or_none()

    if conv is None:
        raise HTTPException(status_code=404, detail=t("api.conv_not_found"))

    messages = await service.get_messages(user_id, limit=limit, offset=offset)
    return ConversationDetailResponse(
        id=conv.id,
        user_id=conv.user_id,
        created_at=conv.created_at,
        updated_at=conv.updated_at,
        message_count=conv.message_count,
        messages=[MessageResponse.model_validate(m) for m in messages],
    )


@router.delete("/{user_id}", response_model=MessageAction)
async def clear_conversation(
    user_id: str,
    service: ConversationService = Depends(_get_service),
):
    """Clear all messages in a user's conversation."""
    cleared = await service.clear_messages(user_id)
    if not cleared:
        raise HTTPException(status_code=404, detail=t("api.conv_not_found"))
    return MessageAction(message=t("api.cleared_conv", user_id=user_id))
