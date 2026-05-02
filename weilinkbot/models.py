"""SQLAlchemy ORM models."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class SystemPrompt(Base):
    __tablename__ = "system_prompts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, server_default=func.now(), onupdate=_utcnow
    )

    # Backref from UserConfig
    user_configs: Mapped[list["UserConfig"]] = relationship(back_populates="custom_prompt")

    def __repr__(self) -> str:
        return f"<SystemPrompt id={self.id} name={self.name!r} default={self.is_default}>"


class UserConfig(Base):
    __tablename__ = "user_configs"

    user_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    nickname: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    source: Mapped[str] = mapped_column(String(20), default="wechat", nullable=False)
    is_blocked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    custom_prompt_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("system_prompts.id"), nullable=True
    )
    max_history: Mapped[int] = mapped_column(Integer, default=20, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, server_default=func.now()
    )

    custom_prompt: Mapped[Optional["SystemPrompt"]] = relationship(back_populates="user_configs")

    def __repr__(self) -> str:
        return f"<UserConfig user_id={self.user_id!r} blocked={self.is_blocked}>"


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, server_default=func.now(), onupdate=_utcnow
    )
    message_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    messages: Mapped[list["Message"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan",
        order_by="Message.created_at"
    )

    def __repr__(self) -> str:
        return f"<Conversation id={self.id} user_id={self.user_id!r} msgs={self.message_count}>"


class Provider(Base):
    """LLM API provider — stores shared API key and base URL."""
    __tablename__ = "providers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    provider_type: Mapped[str] = mapped_column(String(50), nullable=False)
    api_key: Mapped[str] = mapped_column(Text, nullable=False)
    api_key_encrypted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    base_url: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, server_default=func.now(), onupdate=_utcnow
    )

    # Back-reference from LLMPreset
    presets: Mapped[list["LLMPreset"]] = relationship(back_populates="provider_ref")

    def __repr__(self) -> str:
        return f"<Provider id={self.id} name={self.name!r} type={self.provider_type}>"


class LLMPreset(Base):
    """A saved LLM model configuration that can be activated."""
    __tablename__ = "llm_presets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    api_key: Mapped[str] = mapped_column(Text, nullable=False)
    api_key_encrypted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    base_url: Mapped[str] = mapped_column(String(500), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    max_tokens: Mapped[int] = mapped_column(Integer, default=2048, nullable=False)
    temperature: Mapped[float] = mapped_column(default=0.7, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Link to Provider (nullable for backward compatibility)
    provider_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("providers.id", ondelete="SET NULL"), nullable=True
    )

    # Capability flags
    capability_text: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    capability_audio: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    capability_image: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Agent tool calling support
    supports_tools: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Preprocessing model configuration
    preprocess_voice_model_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("llm_presets.id", ondelete="SET NULL"), nullable=True
    )
    preprocess_image_model_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("llm_presets.id", ondelete="SET NULL"), nullable=True
    )
    preprocess_voice: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    preprocess_image: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    voice_method: Mapped[str] = mapped_column(String(10), default="llm", nullable=False)
    asr_language: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, server_default=func.now()
    )

    # Relationship
    provider_ref: Mapped[Optional["Provider"]] = relationship(back_populates="presets")

    def __repr__(self) -> str:
        return f"<LLMPreset id={self.id} name={self.name!r} model={self.model!r} active={self.is_active}>"


class STPreset(Base):
    """SillyTavern prompt preset."""
    __tablename__ = "st_presets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    raw_json: Mapped[str] = mapped_column(Text, nullable=False)
    system_prompt: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, server_default=func.now()
    )

    def __repr__(self) -> str:
        return f"<STPreset id={self.id} name={self.name!r} active={self.is_active}>"


class WorldBook(Base):
    """SillyTavern World Book / Lorebook."""
    __tablename__ = "world_books"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    raw_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, server_default=func.now(), onupdate=_utcnow
    )

    entries: Mapped[list["WorldBookEntry"]] = relationship(
        back_populates="world_book", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<WorldBook id={self.id} name={self.name!r} active={self.is_active}>"


class WorldBookEntry(Base):
    """A single entry in a World Book."""
    __tablename__ = "world_book_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    world_book_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("world_books.id", ondelete="CASCADE"), nullable=False, index=True
    )
    key_primary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    key_secondary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    position: Mapped[str] = mapped_column(String(50), default="before_char", nullable=False)
    insertion_order: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    case_sensitive: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    selective: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    constant: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=10, nullable=False)

    world_book: Mapped["WorldBook"] = relationship(back_populates="entries")

    def __repr__(self) -> str:
        return f"<WorldBookEntry id={self.id} wb={self.world_book_id} keys={self.key_primary!r}>"


class CharacterCard(Base):
    """A SillyTavern-compatible character card."""
    __tablename__ = "character_cards"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    avatar_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    personality: Mapped[str] = mapped_column(Text, nullable=False, default="")
    scenario: Mapped[str] = mapped_column(Text, nullable=False, default="")
    first_mes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    mes_example: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, server_default=func.now(), onupdate=_utcnow
    )

    def __repr__(self) -> str:
        return f"<CharacterCard id={self.id} name={self.name!r} active={self.is_active}>"


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False)  # user / assistant / system
    content: Mapped[str] = mapped_column(Text, nullable=False)
    tokens_used: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    model: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, server_default=func.now()
    )

    conversation: Mapped["Conversation"] = relationship(back_populates="messages")

    def __repr__(self) -> str:
        return f"<Message id={self.id} role={self.role!r} conv={self.conversation_id}>"


class SystemSetting(Base):
    """Key-value system configuration stored in the database."""
    __tablename__ = "system_settings"

    key: Mapped[str] = mapped_column(String(200), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False, default="")
    is_encrypted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, server_default=func.now(), onupdate=_utcnow
    )

    def __repr__(self) -> str:
        return f"<SystemSetting key={self.key!r} encrypted={self.is_encrypted}>"


def get_preset_api_key(preset: LLMPreset) -> str:
    """Return decrypted api_key from a preset."""
    from .crypto import decrypt
    if preset.api_key_encrypted and preset.api_key:
        return decrypt(preset.api_key)
    return preset.api_key


def encrypt_preset_api_key(api_key: str) -> tuple[str, bool]:
    """Encrypt an api_key for storage in LLMPreset. Returns (encrypted_value, True)."""
    from .crypto import encrypt
    if api_key:
        return encrypt(api_key), True
    return api_key, False


def get_provider_api_key(provider: Provider) -> str:
    """Return decrypted api_key from a provider."""
    from .crypto import decrypt
    if provider.api_key_encrypted and provider.api_key:
        return decrypt(provider.api_key)
    return provider.api_key


def encrypt_provider_api_key(api_key: str) -> tuple[str, bool]:
    """Encrypt an api_key for storage in Provider. Returns (encrypted_value, True)."""
    from .crypto import encrypt
    if api_key:
        return encrypt(api_key), True
    return api_key, False


async def resolve_provider_credentials(preset: "LLMPreset", db) -> tuple[str, str, str]:
    """Load the linked Provider and return (provider_type, decrypted_api_key, base_url).

    Raises ValueError if the preset has no provider_id or the provider is not found.
    """
    from sqlalchemy import select as _select
    if not preset.provider_id:
        raise ValueError(f"Preset '{preset.name}' has no provider_id set")
    result = await db.execute(_select(Provider).where(Provider.id == preset.provider_id))
    provider = result.scalar_one_or_none()
    if not provider:
        raise ValueError(f"Provider id={preset.provider_id} not found")
    return provider.provider_type, get_provider_api_key(provider), provider.base_url
