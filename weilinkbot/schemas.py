"""Pydantic schemas for API request/response serialization."""

from __future__ import annotations

from datetime import datetime
from typing import Optional, Annotated

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


# ── LLM Presets ──────────────────────────────────────────────────

class LLMPresetCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    provider: str = Field("custom", max_length=50)
    api_key: str = Field(..., min_length=1)
    base_url: str = Field(..., min_length=1, max_length=500)
    model: str = Field(..., min_length=1, max_length=100)
    max_tokens: int = Field(2048, ge=1, le=128000)
    temperature: float = Field(0.7, ge=0, le=2)
    is_active: bool = False
    capability_text: bool = True
    capability_audio: bool = False
    capability_image: bool = False
    preprocess_voice_model_id: Optional[int] = None
    preprocess_image_model_id: Optional[int] = None
    preprocess_voice: bool = False
    preprocess_image: bool = False
    voice_method: str = "llm"
    asr_language: Optional[str] = None


class LLMPresetUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    provider: Optional[str] = None
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    model: Optional[str] = None
    max_tokens: Optional[int] = Field(None, ge=1, le=128000)
    temperature: Optional[float] = Field(None, ge=0, le=2)
    is_active: Optional[bool] = None
    capability_text: Optional[bool] = None
    capability_audio: Optional[bool] = None
    capability_image: Optional[bool] = None
    preprocess_voice_model_id: Optional[int] = None
    preprocess_image_model_id: Optional[int] = None
    preprocess_voice: Optional[bool] = None
    preprocess_image: Optional[bool] = None
    voice_method: Optional[str] = None
    asr_language: Optional[str] = None


class LLMPresetResponse(BaseModel):
    id: int
    name: str
    provider: str
    base_url: str
    model: str
    max_tokens: int
    temperature: float
    is_active: bool
    api_key_set: bool = True  # Never expose actual key
    capability_text: bool = True
    capability_audio: bool = False
    capability_image: bool = False
    preprocess_voice_model_id: Optional[int] = None
    preprocess_image_model_id: Optional[int] = None
    preprocess_voice: bool = False
    preprocess_image: bool = False
    voice_method: str = "llm"
    asr_language: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


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


# ── Character Cards ─────────────────────────────────────────────

class CharacterCardCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: str = ""
    personality: str = ""
    scenario: str = ""
    first_mes: Optional[str] = None
    mes_example: Optional[str] = None


class CharacterCardUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = None
    personality: Optional[str] = None
    scenario: Optional[str] = None
    first_mes: Optional[str] = None
    mes_example: Optional[str] = None


class CharacterCardResponse(BaseModel):
    id: int
    name: str
    avatar_path: Optional[str] = None
    description: str
    personality: str
    scenario: str
    first_mes: Optional[str] = None
    mes_example: Optional[str] = None
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── Bot Status ──────────────────────────────────────────────────

class BotStatusResponse(BaseModel):
    status: str  # stopped | starting | running | error
    login_url: Optional[str] = None
    error: Optional[str] = None
    user_id: Optional[str] = None
    account_id: Optional[str] = None
    active_model_name: Optional[str] = None
    active_model: Optional[str] = None
    uptime_seconds: Optional[float] = None
    session_messages: int = 0
    session_token_stats: Optional[dict[str, object]] = None


# ── Memory Config ──────────────────────────────────────────────

class MemoryConfigUpdate(BaseModel):
    enabled: Optional[bool] = None
    embedding_provider: Optional[str] = None
    embedding_model: Optional[str] = None
    embedding_base_url: Optional[str] = None
    embedding_api_key: Optional[str] = None
    embedding_local_path: Optional[str] = None
    embedding_quantization: Optional[str] = None
    embedding_onnx_model_file: Optional[str] = None
    embedding_modelscope_model_id: Optional[str] = None
    llm_provider: Optional[str] = None
    llm_model: Optional[str] = None
    llm_base_url: Optional[str] = None
    llm_api_key: Optional[str] = None
    top_k: Annotated[Optional[int], Field(ge=1, le=100)] = None
    min_score: Annotated[Optional[float], Field(ge=0.0, le=1.0)] = None
    max_context_chars: Annotated[Optional[int], Field(ge=100, le=100000)] = None
    preload_onnx: Optional[bool] = None
    hnsw_space: Optional[str] = None
    hnsw_m: Annotated[Optional[int], Field(ge=1, le=1000)] = None
    hnsw_construction_ef: Annotated[Optional[int], Field(ge=1, le=1000)] = None
    hnsw_search_ef: Annotated[Optional[int], Field(ge=1, le=1000)] = None


class MemoryConfigTestResponse(BaseModel):
    success: bool
    message: str
    latency_ms: Optional[float] = None


class MemoryConfigUpdateResponse(BaseModel):
    available: bool
    embedding_model: str
    embedding_provider: str
    embedding_base_url: str
    embedding_api_key_set: bool
    embedding_local_path: str = ""
    embedding_quantization: str = ""
    embedding_onnx_model_file: str = ""
    embedding_modelscope_model_id: str = ""
    llm_model: Optional[str] = None
    llm_api_key_set: bool
    top_k: int
    min_score: float = 0.0
    max_context_chars: int = 2000
    preload_onnx: bool = False
    hnsw_space: str = "cosine"
    hnsw_m: int = 16
    hnsw_construction_ef: int = 200
    hnsw_search_ef: int = 100
    init_error: Optional[str] = None


# ── Generic ─────────────────────────────────────────────────────

class MessageAction(BaseModel):
    message: str = "OK"
