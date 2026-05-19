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
    ("llm_presets", "supports_tools", "BOOLEAN NOT NULL DEFAULT 1"),
    ("messages", "is_consolidated", "BOOLEAN NOT NULL DEFAULT 0"),
    ("mcp_servers", "headers", "TEXT NOT NULL DEFAULT '{}'"),
    ("mcp_servers", "tool_timeout", "INTEGER NOT NULL DEFAULT 30"),
    ("mcp_servers", "enabled_tools", "TEXT NOT NULL DEFAULT '[\"*\"]'"),
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


async def _backfill_user_configs(conn) -> None:
    """Create UserConfig rows for users who have conversations but no config.

    Fixes data from older versions that never created UserConfig records.
    """
    result = await conn.execute(text(
        "SELECT DISTINCT c.user_id FROM conversations c "
        "LEFT JOIN user_configs u ON c.user_id = u.user_id "
        "WHERE u.user_id IS NULL"
    ))
    rows = result.fetchall()
    if not rows:
        return
    for (user_id,) in rows:
        await conn.execute(text(
            "INSERT OR IGNORE INTO user_configs (user_id, source, is_blocked) "
            "VALUES (:uid, 'wechat', 0)"
        ), {"uid": user_id})
    logger.info("Auto-migration: backfilled %d UserConfig rows from conversations", len(rows))


async def _migrate_nullable_api_key(conn) -> None:
    """Recreate llm_presets to make api_key and base_url nullable (SQLite limitation)."""
    result = await conn.execute(text("PRAGMA table_info(llm_presets)"))
    col_info = {row[1]: row for row in result.fetchall()}
    if not col_info:
        return  # table doesn't exist yet
    # Check if migration is needed: api_key should already be nullable
    api_key_col = col_info.get("api_key")
    base_url_col = col_info.get("base_url")
    if api_key_col and api_key_col[3] == 0 and base_url_col and base_url_col[3] == 0:
        return  # already nullable

    logger.info("Auto-migration: making llm_presets.api_key and base_url nullable via table rebuild")
    old_cols = set(col_info.keys())

    await conn.execute(text("ALTER TABLE llm_presets RENAME TO llm_presets_old"))
    await conn.execute(text("""
        CREATE TABLE llm_presets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name VARCHAR(100) NOT NULL UNIQUE,
            provider VARCHAR(50) NOT NULL,
            api_key TEXT,
            api_key_encrypted BOOLEAN NOT NULL DEFAULT 0,
            base_url VARCHAR(500),
            model VARCHAR(100) NOT NULL,
            max_tokens INTEGER NOT NULL DEFAULT 2048,
            temperature FLOAT NOT NULL DEFAULT 0.7,
            is_active BOOLEAN NOT NULL DEFAULT 0,
            provider_id INTEGER REFERENCES providers(id) ON DELETE SET NULL,
            capability_text BOOLEAN NOT NULL DEFAULT 1,
            capability_audio BOOLEAN NOT NULL DEFAULT 0,
            capability_image BOOLEAN NOT NULL DEFAULT 0,
            supports_tools BOOLEAN NOT NULL DEFAULT 1,
            preprocess_voice_model_id INTEGER REFERENCES llm_presets(id) ON DELETE SET NULL,
            preprocess_image_model_id INTEGER REFERENCES llm_presets(id) ON DELETE SET NULL,
            preprocess_voice BOOLEAN NOT NULL DEFAULT 0,
            preprocess_image BOOLEAN NOT NULL DEFAULT 0,
            voice_method VARCHAR(10) NOT NULL DEFAULT 'llm',
            asr_language VARCHAR(10),
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """))

    # Only copy columns that exist in both old and new table
    new_result = await conn.execute(text("PRAGMA table_info(llm_presets)"))
    new_cols = {row[1] for row in new_result.fetchall()}
    shared_cols = sorted(old_cols & new_cols, key=lambda c: col_info[c][0])
    col_list = ", ".join(shared_cols)
    await conn.execute(text(
        f"INSERT INTO llm_presets ({col_list}) SELECT {col_list} FROM llm_presets_old"
    ))
    await conn.execute(text("DROP TABLE llm_presets_old"))
    logger.info("Auto-migration: llm_presets table rebuilt successfully")


async def init_db():
    """Create all tables and apply auto-migrations."""
    engine = get_engine()
    async with engine.begin() as conn:
        # Enable WAL mode for better concurrent read/write performance
        await conn.execute(text("PRAGMA journal_mode=WAL"))
        await conn.run_sync(Base.metadata.create_all)
        await _auto_migrate(conn)
        await _backfill_user_configs(conn)
        await _migrate_nullable_api_key(conn)
