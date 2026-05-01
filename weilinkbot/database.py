"""Database engine, session factory, and initialization."""

from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

logger = logging.getLogger(__name__)

# Hardcoded database URL — cannot be stored in the DB itself (bootstrap problem).
DATABASE_URL = "sqlite+aiosqlite:///./data/weilinkbot.db"


class Base(DeclarativeBase):
    pass


_engine = None
_session_factory = None


def get_engine():
    global _engine
    if _engine is None:
        db_path = DATABASE_URL.split("///")[-1] if "///" in DATABASE_URL else ""
        if db_path and db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        _engine = create_async_engine(
        DATABASE_URL,
        echo=False,
        connect_args={"timeout": 30},
    )
    return _engine


def get_session_factory():
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            get_engine(), class_=AsyncSession, expire_on_commit=False
        )
    return _session_factory


async def get_db():
    """FastAPI dependency — yields an async DB session."""
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


# Columns added after initial table creation — safe to re-run.
_MIGRATIONS: list[tuple[str, str, str]] = [
    # (table, column, column_type)
    ("llm_presets", "provider_id", "INTEGER REFERENCES providers(id) ON DELETE SET NULL"),
    ("llm_presets", "capability_text", "BOOLEAN NOT NULL DEFAULT 1"),
    ("llm_presets", "capability_audio", "BOOLEAN NOT NULL DEFAULT 0"),
    ("llm_presets", "capability_image", "BOOLEAN NOT NULL DEFAULT 0"),
    ("llm_presets", "preprocess_model_id", "INTEGER REFERENCES llm_presets(id) ON DELETE SET NULL"),
    ("llm_presets", "preprocess_voice_model_id", "INTEGER REFERENCES llm_presets(id) ON DELETE SET NULL"),
    ("llm_presets", "preprocess_image_model_id", "INTEGER REFERENCES llm_presets(id) ON DELETE SET NULL"),
    ("llm_presets", "preprocess_voice", "BOOLEAN NOT NULL DEFAULT 0"),
    ("llm_presets", "preprocess_image", "BOOLEAN NOT NULL DEFAULT 0"),
    ("llm_presets", "voice_method", "VARCHAR(10) NOT NULL DEFAULT 'llm'"),
    ("llm_presets", "asr_language", "VARCHAR(10)"),
    ("user_configs", "source", "VARCHAR(20) NOT NULL DEFAULT 'wechat'"),
    ("llm_presets", "api_key_encrypted", "BOOLEAN NOT NULL DEFAULT 0"),
]


async def _auto_migrate(conn) -> None:
    """Add missing columns to existing tables."""
    for table, column, col_type in _MIGRATIONS:
        result = await conn.execute(text(f"PRAGMA table_info({table})"))
        existing = {row[1] for row in result.fetchall()}
        if column not in existing:
            await conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}"))
            logger.info("Auto-migration: added %s.%s", table, column)

    # Data migration: copy old preprocess_model_id → both new columns
    result = await conn.execute(text("PRAGMA table_info(llm_presets)"))
    cols = {row[1] for row in result.fetchall()}
    if "preprocess_voice_model_id" in cols and "preprocess_model_id" in cols:
        await conn.execute(text(
            "UPDATE llm_presets SET preprocess_voice_model_id = preprocess_model_id "
            "WHERE preprocess_voice_model_id IS NULL AND preprocess_model_id IS NOT NULL"
        ))
        await conn.execute(text(
            "UPDATE llm_presets SET preprocess_image_model_id = preprocess_model_id "
            "WHERE preprocess_image_model_id IS NULL AND preprocess_model_id IS NOT NULL"
        ))

    # Data migration: encrypt existing plaintext api_keys
    if "api_key_encrypted" in cols:
        result = await conn.execute(text(
            "SELECT id, api_key FROM llm_presets WHERE api_key_encrypted = 0 AND api_key != ''"
        ))
        rows = result.fetchall()
        if rows:
            from .crypto import encrypt
            for row in rows:
                encrypted_key = encrypt(row[1])
                await conn.execute(
                    text("UPDATE llm_presets SET api_key = :val, api_key_encrypted = 1 WHERE id = :id"),
                    {"val": encrypted_key, "id": row[0]},
                )
            logger.info("Auto-migration: encrypted %d LLMPreset api_keys", len(rows))


async def init_db():
    """Create all tables and apply auto-migrations."""
    engine = get_engine()
    async with engine.begin() as conn:
        # Enable WAL mode for better concurrent read/write performance
        await conn.execute(text("PRAGMA journal_mode=WAL"))
        await conn.run_sync(Base.metadata.create_all)
        await _auto_migrate(conn)
