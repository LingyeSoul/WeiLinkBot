"""Configuration management — loads from database system_settings table."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# Hardcoded database URL — cannot be read from DB before DB exists.
DATABASE_URL = "sqlite+aiosqlite:///./data/weilinkbot.db"

# Keys whose values are stored encrypted in system_settings.
_ENCRYPTED_KEYS = frozenset({
    "llm.api_key",
    "memory.embedding.api_key",
    "memory.llm.api_key",
})


# ---------------------------------------------------------------------------
# Pydantic config models (kept for type validation and defaults)
# ---------------------------------------------------------------------------

class BotConfig(BaseModel):
    base_url: str = "https://ilinkai.weixin.qq.com"
    cred_path: str = "~/.wechatbot/credentials.json"


class LLMConfig(BaseModel):
    provider: str = "openai"
    api_key: str = ""
    base_url: str = "https://api.openai.com/v1"
    model: str = "gpt-4o-mini"
    max_tokens: int = 2048
    temperature: float = 0.7


# Provider presets
LLM_PRESETS: dict[str, dict[str, str]] = {
    "openai": {"base_url": "https://api.openai.com/v1", "model": "gpt-4o-mini"},
    "deepseek": {"base_url": "https://api.deepseek.com/v1", "model": "deepseek-chat"},
}


class DatabaseConfig(BaseModel):
    url: str = DATABASE_URL


class ServerConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 5292


class EmbeddingConfig(BaseModel):
    provider: str = "openai"
    api_key: str = ""
    base_url: str = ""
    model: str = ""
    local_path: str = "./data/models/bge-small-zh-v1.5"
    quantization: str = "fp32"
    onnx_model_file: str = "onnx/model.onnx"
    modelscope_model_id: str = "Xenova/bge-small-zh-v1.5"


class EmbeddingLLMConfig(BaseModel):
    """LLM config for mem0 memory extraction."""
    provider: str = ""
    api_key: str = ""
    base_url: str = ""
    model: str = ""


class MemoryConfig(BaseModel):
    enabled: bool = False
    db_path: str = "./data/chroma_memory"
    top_k: int = 5
    min_score: float = 0.0
    max_context_chars: int = 2000
    preload_onnx: bool = False
    hnsw_space: str = "cosine"
    hnsw_m: int = 16
    hnsw_construction_ef: int = 200
    hnsw_search_ef: int = 100
    fact_extraction: bool = True
    role_term_blacklist: list[str] = Field(default_factory=list)
    category_budgets: dict[str, int] = Field(default_factory=dict)
    custom_instructions: str = ""
    embedding: EmbeddingConfig = Field(default_factory=EmbeddingConfig)
    llm: EmbeddingLLMConfig = Field(default_factory=EmbeddingLLMConfig)


class AgentConfig(BaseModel):
    max_tool_rounds: int = 5
    enabled_tools: list[str] = Field(default_factory=lambda: ["get_current_time", "calculate"])


class AppConfig(BaseModel):
    bot: BotConfig = Field(default_factory=BotConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    agent: AgentConfig = Field(default_factory=AgentConfig)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    server: ServerConfig = Field(default_factory=ServerConfig)


# ---------------------------------------------------------------------------
# Helpers for dot-separated key ↔ nested dict conversion
# ---------------------------------------------------------------------------

def _set_nested(data: dict[str, Any], key: str, value: Any) -> None:
    """Set a value in a nested dict using a dot-separated key."""
    parts = key.split(".")
    d = data
    for part in parts[:-1]:
        d = d.setdefault(part, {})
    d[parts[-1]] = value


def _flatten_dict(d: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    """Flatten a nested dict to dot-separated keys."""
    items: dict[str, Any] = {}
    for k, v in d.items():
        new_key = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            items.update(_flatten_dict(v, new_key))
        else:
            items[new_key] = v
    return items


def _coerce_value(value: str, target_type: type) -> Any:
    """Coerce a string value to the target type."""
    if target_type is bool:
        return value.lower() in ("1", "true", "yes")
    if target_type is int:
        return int(value)
    if target_type is float:
        return float(value)
    return value


# ---------------------------------------------------------------------------
# Sync SQLAlchemy engine for config reads/writes (avoids async complexity)
# ---------------------------------------------------------------------------

_sync_engine = None


def _get_sync_engine():
    global _sync_engine
    if _sync_engine is None:
        from sqlalchemy import create_engine
        db_path = DATABASE_URL.split("///")[-1]
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        _sync_engine = create_engine(f"sqlite:///{db_path}", echo=False)
    return _sync_engine


# ---------------------------------------------------------------------------
# Core config functions
# ---------------------------------------------------------------------------

def load_config() -> AppConfig:
    """Load configuration from the system_settings database table."""
    from .crypto import decrypt
    from .models import SystemSetting
    from sqlalchemy import select
    from sqlalchemy.orm import Session

    engine = _get_sync_engine()

    # Ensure table exists (safe if already created by async init_db)
    SystemSetting.__table__.create(engine, checkfirst=True)

    data: dict[str, Any] = {}
    with Session(engine) as session:
        rows = session.execute(
            select(SystemSetting.key, SystemSetting.value, SystemSetting.is_encrypted)
        ).all()
        for key, value, encrypted in rows:
            if encrypted and value:
                try:
                    value = decrypt(value)
                except Exception:
                    logger.warning("Failed to decrypt setting '%s', skipping", key)
                    continue
            _set_nested(data, key, value)

    return AppConfig(**data)


def save_config() -> None:
    """Write the current in-memory config to the system_settings table."""
    global _config
    if _config is None:
        return

    from .crypto import encrypt
    from .models import SystemSetting
    from sqlalchemy.orm import Session

    flat = _flatten_dict(_config.model_dump())
    engine = _get_sync_engine()

    with Session(engine) as session:
        for key, value in flat.items():
            encrypted = key in _ENCRYPTED_KEYS
            stored = encrypt(str(value)) if encrypted and value else str(value) if value is not None else ""

            existing = session.get(SystemSetting, key)
            if existing:
                existing.value = stored
                existing.is_encrypted = encrypted
            else:
                session.add(SystemSetting(key=key, value=stored, is_encrypted=encrypted))
        session.commit()


# Singleton config instance
_config: AppConfig | None = None


def get_config() -> AppConfig:
    global _config
    if _config is None:
        _config = load_config()
    return _config


def set_config(config: AppConfig) -> None:
    """Override the global config (used by CLI and tests)."""
    global _config
    _config = config
