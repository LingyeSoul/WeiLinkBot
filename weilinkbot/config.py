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
    host: str = "127.0.0.1"
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
    llm_provider_id: int = 0  # 0 = not linked to a provider (manual / fallback)


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

    # Buffer & trigger
    turn_threshold: int = 10
    timeout_minutes: int = 30

    # Time decay for retrieval
    time_decay_days: int = 30

    # Reranking weights
    rerank_weight: float = 0.7
    exact_sim_weight: float = 0.3
    expand_factor: int = 2


class AgentConfig(BaseModel):
    max_tool_rounds: int = 5
    tool_timeout_seconds: float = 60.0
    max_tool_result_chars: int = 30_000
    consecutive_fail_limit: int = 3
    max_context_tokens: int = 0  # 0 = use max_history message count; >0 = token budget
    max_concurrent_requests: int = 3  # global concurrency limit for LLM calls
    consolidation_threshold: int = 30  # min messages before consolidation triggers
    consolidation_ratio: float = 0.3  # target compression ratio
    enabled_tools: list[str] = Field(default_factory=lambda: [
        "get_current_time", "calculate",
        "browser_fetch", "browser_eval", "browser_use", "browser_download",
    ])
    enabled_skills: list[str] = Field(default_factory=list)
    disabled_skills: list[str] = Field(default_factory=list)
    enabled_workspace_tools: list[str] = Field(
        default_factory=lambda: ["workspace_read", "workspace_list", "workspace_grep", "workspace_write", "workspace_edit", "workspace_shell", "send_file"]
    )
    enabled_sticker_tools: list[str] = Field(
        default_factory=lambda: ["search_sticker", "send_sticker", "list_sticker_packs"]
    )
    tool_prompt_injection: bool = True  # inject tool-aware system prompt to guide tool usage


class StickerConfig(BaseModel):
    enabled: bool = True


class SecurityConfig(BaseModel):
    """Tool-call guard configuration."""
    enabled: bool = True
    block_on_critical: bool = True   # block CRITICAL severity findings
    block_on_high: bool = True       # block HIGH severity findings
    disabled_rules: list[str] = Field(default_factory=list)
    custom_sensitive_paths: list[str] = Field(default_factory=list)


class WorkspaceConfig(BaseModel):
    enabled: bool = True
    root: str = "workspace"
    blocked_extensions: list[str] = Field(default_factory=lambda: [
        ".exe", ".bat", ".cmd", ".com", ".msi", ".scr",
        ".dll", ".so", ".dylib",
        ".sh", ".bash", ".zsh", ".ps1", ".psm1",
        ".vbs", ".vbe",
        ".jar", ".class",
        ".elf", ".appimage",
    ])
    read_max_size: int = 1_048_576
    write_max_size: int = 524_288
    list_max_entries: int = 500
    grep_max_results: int = 100


class BrowserConfig(BaseModel):
    """Obscura headless browser configuration."""
    enabled: bool = True
    binary_path: str = ""  # empty = auto-detect (tools/bin/obscura.exe or PATH)
    stealth: bool = False  # default anti-fingerprinting mode
    default_timeout: int = 30
    serve_port: int = 9222  # CDP server port for puppeteer/playwright
    download_dir: str = "downloads"  # subdirectory within workspace for browser downloads


class AppConfig(BaseModel):
    bot: BotConfig = Field(default_factory=BotConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    agent: AgentConfig = Field(default_factory=AgentConfig)
    browser: BrowserConfig = Field(default_factory=BrowserConfig)
    sticker: StickerConfig = Field(default_factory=StickerConfig)
    workspace: WorkspaceConfig = Field(default_factory=WorkspaceConfig)
    security: SecurityConfig = Field(default_factory=SecurityConfig)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    server: ServerConfig = Field(default_factory=ServerConfig)


# ---------------------------------------------------------------------------
# Helpers for dot-separated key ↔ nested dict conversion
# ---------------------------------------------------------------------------

def _set_nested(data: dict[str, Any], key: str, value: Any) -> None:
    """Set a value in a nested dict using a dot-separated key."""
    # Parse string values that look like Python/JSON literals (lists, dicts)
    if isinstance(value, str) and value:
        stripped = value.strip()
        if stripped.startswith(("[", "{")):
            import json
            try:
                value = json.loads(stripped)
            except (json.JSONDecodeError, ValueError):
                try:
                    import ast
                    value = ast.literal_eval(stripped)
                except (ValueError, SyntaxError):
                    pass
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
    from sqlalchemy import select
    from sqlalchemy.orm import Session

    flat = _flatten_dict(_config.model_dump())
    engine = _get_sync_engine()

    with Session(engine) as session:
        # Load all existing settings in one query
        existing = {row.key: row for row in session.execute(select(SystemSetting)).scalars().all()}

        for key, value in flat.items():
            encrypted = key in _ENCRYPTED_KEYS
            stored = encrypt(str(value)) if encrypted and value else str(value) if value is not None else ""

            if key in existing:
                existing[key].value = stored
                existing[key].is_encrypted = encrypted
            else:
                session.add(SystemSetting(key=key, value=stored, is_encrypted=encrypted))
        session.commit()


def dispose_config_engine() -> None:
    """Dispose the sync config engine. Call on app shutdown."""
    global _sync_engine
    if _sync_engine is not None:
        _sync_engine.dispose()
        _sync_engine = None


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
