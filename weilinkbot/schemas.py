"""Pydantic schemas for API request/response serialization."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


# ── System Prompts ────────────────────────────────────────────────

class SystemPromptCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    content: str = Field(..., min_length=1)
    is_default: bool = False


class SystemPromptUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    content: Optional[str] = Field(None, min_length=1)
    is_default: Optional[bool] = None


class SystemPromptResponse(BaseModel):
    id: int
    name: str
    content: str
    is_default: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── Messages ─────────────────────────────────────────────────────

class MessageResponse(BaseModel):
    id: int
    role: str
    content: str
    tokens_used: Optional[int] = None
    model: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Conversations ────────────────────────────────────────────────

class ConversationResponse(BaseModel):
    id: int
    user_id: str
    created_at: datetime
    updated_at: datetime
    message_count: int
    last_message: Optional[str] = None

    model_config = {"from_attributes": True}


class ConversationDetailResponse(BaseModel):
    id: int
    user_id: str
    created_at: datetime
    updated_at: datetime
    message_count: int
    messages: list[MessageResponse] = []

    model_config = {"from_attributes": True}


# ── User Config ──────────────────────────────────────────────────

class UserConfigResponse(BaseModel):
    user_id: str
    nickname: Optional[str] = None
    is_blocked: bool = False
    custom_prompt_id: Optional[int] = None
    max_history: int = 20
    created_at: datetime

    model_config = {"from_attributes": True}


class UserConfigUpdate(BaseModel):
    nickname: Optional[str] = None
    is_blocked: Optional[bool] = None
    custom_prompt_id: Optional[int] = None
    max_history: Optional[int] = Field(None, ge=1, le=100)


# ── LLM Config ──────────────────────────────────────────────────

class LLMConfigResponse(BaseModel):
    provider: str
    base_url: str
    model: str
    max_tokens: int
    temperature: float
    api_key_set: bool  # Never expose actual key


class LLMConfigUpdate(BaseModel):
    provider: Optional[str] = None
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    model: Optional[str] = None
    max_tokens: Optional[int] = Field(None, ge=1, le=128000)
    temperature: Optional[float] = Field(None, ge=0, le=2)


# ── Bot Status ──────────────────────────────────────────────────

class BotStatusResponse(BaseModel):
    status: str  # stopped | starting | running | error
    login_url: Optional[str] = None
    error: Optional[str] = None
    user_id: Optional[str] = None
    account_id: Optional[str] = None


# ── Generic ─────────────────────────────────────────────────────

class MessageAction(BaseModel):
    message: str = "OK"
