"""Configuration management — loads from config.yaml + environment variables."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field


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
    url: str = "sqlite+aiosqlite:///./data/weilinkbot.db"


class ServerConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 5292


class AppConfig(BaseModel):
    bot: BotConfig = Field(default_factory=BotConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    server: ServerConfig = Field(default_factory=ServerConfig)


def _deep_merge(base: dict, override: dict) -> dict:
    """Merge override into base, recursively."""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _env_override(data: dict[str, Any], prefix: str = "WEILINKBOT_") -> dict[str, Any]:
    """Override config values from environment variables.

    e.g. WEILINKBOT_LLM__API_KEY -> data["llm"]["api_key"]
    """
    for key, value in os.environ.items():
        if not key.startswith(prefix):
            continue
        parts = key[len(prefix):].lower().split("__")
        if len(parts) == 2:
            section, field = parts
            if section in data and isinstance(data[section], dict):
                # Type coerce
                existing = data[section].get(field)
                if isinstance(existing, int):
                    data[section][field] = int(value)
                elif isinstance(existing, float):
                    data[section][field] = float(value)
                elif isinstance(existing, bool):
                    data[section][field] = value.lower() in ("1", "true", "yes")
                else:
                    data[section][field] = value
    return data


def load_config(config_path: str | Path = "config.yaml") -> AppConfig:
    """Load configuration from YAML file with environment variable overrides."""
    # Load .env file into os.environ (if it exists)
    load_dotenv()

    config_path = Path(config_path)
    data: dict[str, Any] = {}

    if config_path.exists():
        with open(config_path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

    data = _env_override(data)
    return AppConfig(**data)


# Singleton config instance
_config: AppConfig | None = None


def get_config() -> AppConfig:
    global _config
    if _config is None:
        # Try multiple config paths
        for path in ["config.yaml", "../config.yaml"]:
            if Path(path).exists():
                _config = load_config(path)
                break
        else:
            _config = load_config()
    return _config


def set_config(config: AppConfig) -> None:
    """Override the global config (used by CLI and tests)."""
    global _config
    _config = config
