"""User management API endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..schemas import UserConfigResponse, UserConfigUpdate, MessageAction
from ..services.conversation_service import ConversationService
from ..services.ws_service import get_ws_service

router = APIRouter()


async def _broadcast_users(service: ConversationService):
    """Broadcast updated users list to all WebSocket clients."""
    users = await service.list_user_configs()
    await get_ws_service().broadcast(
        "users",
        [UserConfigResponse.model_validate(u).model_dump(mode="json") for u in users],
    )


async def _get_service(db: AsyncSession = Depends(get_db)) -> ConversationService:
    return ConversationService(db)


@router.get("", response_model=list[UserConfigResponse])
async def list_users(service: ConversationService = Depends(_get_service)):
    """List all user configurations."""
    users = await service.list_user_configs()
    return users


@router.get("/{user_id}", response_model=UserConfigResponse)
async def get_user(
    user_id: str,
    service: ConversationService = Depends(_get_service),
):
    """Get a specific user's configuration."""
    config = await service.get_or_create_user_config(user_id)
    return config


@router.put("/{user_id}", response_model=UserConfigResponse)
async def update_user(
    user_id: str,
    data: UserConfigUpdate,
    service: ConversationService = Depends(_get_service),
):
    """Update user configuration (block/unblock, custom prompt, etc.)."""
    config = await service.update_user_config(
        user_id,
        nickname=data.nickname,
        is_blocked=data.is_blocked,
        custom_prompt_id=data.custom_prompt_id,
        max_history=data.max_history,
    )
    await _broadcast_users(service)
    return config
