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
    custom_prompt_id: Optional[int] = None
    max_history: int = 20
    created_at: datetime

    model_config = {"from_attributes": True}


class UserConfigUpdate(BaseModel):
    nickname: Optional[str] = None
    custom_prompt_id: Optional[int] = None
    max_history: Optional[int] = Field(None, ge=1, le=100)


# ── Providers ──────────────────────────────────────────────────

class ProviderCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    provider_type: str = Field("custom", max_length=50)
    api_key: str = Field(..., min_length=1)
    base_url: str = Field(..., min_length=1, max_length=500)
    description: Optional[str] = None
    is_enabled: bool = True


class ProviderUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    provider_type: Optional[str] = None
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    description: Optional[str] = None
    is_enabled: Optional[bool] = None


class ProviderResponse(BaseModel):
    id: int
    name: str
    provider_type: str
    base_url: str
    api_key_set: bool = True
    description: Optional[str] = None
    is_enabled: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── LLM Presets ──────────────────────────────────────────────────

class LLMPresetCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    provider: str = Field("custom", max_length=50)
    model: str = Field(..., min_length=1, max_length=100)
    max_tokens: int = Field(2048, ge=1, le=128000)
    temperature: float = Field(0.7, ge=0, le=2)
    is_active: bool = False
    provider_id: int
    capability_text: bool = True
    capability_audio: bool = False
    capability_image: bool = False
    supports_tools: bool = True
    preprocess_voice_model_id: Optional[int] = None
    preprocess_image_model_id: Optional[int] = None
    preprocess_voice: bool = False
    preprocess_image: bool = False
    voice_method: str = "llm"
    asr_language: Optional[str] = None


class LLMPresetUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    provider: Optional[str] = None
    model: Optional[str] = None
    max_tokens: Optional[int] = Field(None, ge=1, le=128000)
    temperature: Optional[float] = Field(None, ge=0, le=2)
    is_active: Optional[bool] = None
    provider_id: Optional[int] = None
    capability_text: Optional[bool] = None
    capability_audio: Optional[bool] = None
    capability_image: Optional[bool] = None
    supports_tools: Optional[bool] = None
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
    model: str
    max_tokens: int
    temperature: float
    is_active: bool
    provider_id: Optional[int] = None
    provider_name: Optional[str] = None
    capability_text: bool = True
    capability_audio: bool = False
    capability_image: bool = False
    supports_tools: bool = True
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
    fact_extraction: Optional[bool] = None
    role_term_blacklist: Optional[list[str]] = None
    custom_instructions: Optional[str] = None


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


# ── ST Presets ───────────────────────────────────────────────

class STPresetCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    raw_json: str = Field(..., min_length=1)
    system_prompt: Optional[str] = None



class STPresetUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    raw_json: Optional[str] = None
    system_prompt: Optional[str] = None



class STPresetResponse(BaseModel):
    id: int
    name: str
    is_active: bool
    raw_json: str
    system_prompt: Optional[str] = None

    created_at: datetime

    model_config = {"from_attributes": True}


class STEntryCreate(BaseModel):
    name: str = Field("New Entry", min_length=1, max_length=200)
    identifier: str = ""
    content: str = ""
    role: str = Field("system", pattern=r"^(system|user|assistant)$")
    injection_position: int = Field(0, ge=0, le=1)
    injection_depth: int = Field(4, ge=0, le=100)
    enabled: bool = True


class STEntryUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    identifier: Optional[str] = None
    content: Optional[str] = None
    role: Optional[str] = Field(None, pattern=r"^(system|user|assistant)$")
    injection_position: Optional[int] = Field(None, ge=0, le=1)
    injection_depth: Optional[int] = Field(None, ge=0, le=100)
    enabled: Optional[bool] = None


class STEntryReorder(BaseModel):
    order: list[int]


# ── World Books ──────────────────────────────────────────────

class WorldBookEntryResponse(BaseModel):
    id: int
    world_book_id: int
    key_primary: str
    key_secondary: Optional[str] = None
    content: str
    comment: Optional[str] = None
    enabled: bool
    position: str
    insertion_order: int
    case_sensitive: bool
    selective: bool
    constant: bool
    priority: int

    model_config = {"from_attributes": True}


class WorldBookEntryUpdate(BaseModel):
    key_primary: Optional[str] = None
    key_secondary: Optional[str] = None
    content: Optional[str] = None
    comment: Optional[str] = None
    enabled: Optional[bool] = None
    position: Optional[str] = None
    insertion_order: Optional[int] = None
    case_sensitive: Optional[bool] = None
    selective: Optional[bool] = None
    constant: Optional[bool] = None
    priority: Optional[int] = None


class WorldBookEntryCreate(BaseModel):
    key_primary: str = ""
    key_secondary: Optional[str] = None
    content: str = ""
    comment: Optional[str] = None
    enabled: bool = True
    position: str = "before_char"
    insertion_order: int = 100
    case_sensitive: bool = False
    selective: bool = False
    constant: bool = False
    priority: int = 10


class WorldBookEntryReorder(BaseModel):
    order: list[int]


class WorldBookCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: str = ""
    raw_json: str = Field(..., min_length=1)


class WorldBookUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = None
    raw_json: Optional[str] = None


class WorldBookResponse(BaseModel):
    id: int
    name: str
    description: str
    is_active: bool
    raw_json: str
    created_at: datetime
    updated_at: datetime
    entries: list[WorldBookEntryResponse] = []

    model_config = {"from_attributes": True}


# ── Settings ─────────────────────────────────────────────────

class SettingsResponse(BaseModel):
    server_host: str
    server_port: int
    listen_lan: bool
    language: str
    max_history: int = 20
    disable_base_prompt_on_char: bool = False
    disable_base_prompt_on_preset: bool = False
    disable_base_prompt_on_worldbook: bool = False


class SettingsUpdate(BaseModel):
    server_host: Optional[str] = None
    server_port: Optional[int] = Field(None, ge=1, le=65535)
    listen_lan: Optional[bool] = None
    language: Optional[str] = None
    max_history: Optional[int] = Field(None, ge=1, le=200)
    disable_base_prompt_on_char: Optional[bool] = None
    disable_base_prompt_on_preset: Optional[bool] = None
    disable_base_prompt_on_worldbook: Optional[bool] = None


# ── Agent Config ─────────────────────────────────────────────

class AgentConfigResponse(BaseModel):
    max_tool_rounds: int
    enabled_tools: list[str]
    available_tools: list[str]


class AgentConfigUpdate(BaseModel):
    max_tool_rounds: Optional[int] = Field(None, ge=1, le=20)
    enabled_tools: Optional[list[str]] = None


# ── Skills ─────────────────────────────────────────────────────

class SkillInfo(BaseModel):
    name: str
    description: str
    enabled: bool


class SkillCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)
    content: str
    description: str = ""


class SkillUpdate(BaseModel):
    content: str | None = None
    description: str | None = None


class SkillsResponse(BaseModel):
    skills: list[SkillInfo]


class SkillsUpdate(BaseModel):
    enabled_skills: list[str]


# ── MCP Servers ────────────────────────────────────────────────

class MCPServerCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)
    transport: str = Field(..., pattern=r"^(stdio|sse)$")
    command: str | None = None
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    url: str | None = None
    enabled: bool = True


class MCPServerUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=64)
    transport: str | None = Field(None, pattern=r"^(stdio|sse)$")
    command: str | None = None
    args: list[str] | None = None
    env: dict[str, str] | None = None
    url: str | None = None
    enabled: bool | None = None


class MCPServerResponse(BaseModel):
    id: int
    name: str
    transport: str
    command: str | None
    args: list[str]
    env: dict[str, str]
    url: str | None
    enabled: bool
    status: str = "disconnected"

    model_config = {"from_attributes": True}


class MCPServersResponse(BaseModel):
    servers: list[MCPServerResponse]


# ── Generic ─────────────────────────────────────────────────────

class MessageAction(BaseModel):
    message: str = "OK"
