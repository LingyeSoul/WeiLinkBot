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

from .config import get_config

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    pass


_engine = None
_session_factory = None


def get_engine():
    global _engine
    if _engine is None:
        config = get_config()
        db_url = config.database.url
        # Ensure parent directory exists for SQLite file paths
        if "sqlite" in db_url:
            db_path = db_url.split("///")[-1] if "///" in db_url else ""
            if db_path and db_path != ":memory:":
                Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        _engine = create_async_engine(db_url, echo=False)
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


async def init_db():
    """Create all tables and apply auto-migrations."""
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _auto_migrate(conn)
