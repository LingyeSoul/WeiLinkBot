"""Web chat API endpoint — allows sending messages from the web UI."""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .deps import get_bot_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/chat", tags=["chat"])


class ChatRequest(BaseModel):
    user_id: str = "web:admin"
    content: str


class ChatResponse(BaseModel):
    status: str
    user_id: str


@router.post("", response_model=ChatResponse)
async def send_message(req: ChatRequest):
    """Accept a chat message from the web UI and process it asynchronously."""
    if not req.content.strip():
        raise HTTPException(status_code=400, detail="Message content cannot be empty")

    bot = get_bot_service()

    # Fire-and-forget: process in background, result delivered via WebSocket
    asyncio.create_task(
        bot.process_web_message(req.user_id, req.content.strip())
    )

    return ChatResponse(status="accepted", user_id=req.user_id)
