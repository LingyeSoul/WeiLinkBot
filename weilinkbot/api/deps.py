"""FastAPI dependency injection helpers."""

from __future__ import annotations

from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db, get_session_factory
from ..services.llm_service import LLMService
from ..services.conversation_service import ConversationService

# Module-level singletons (initialized in app lifespan)
_llm_service: LLMService | None = None
_bot_service = None  # Avoid circular import with BotService
_memory_service = None  # Avoid circular import with MemoryService
_agent_service = None


def get_llm_service() -> LLMService:
    if _llm_service is None:
        raise RuntimeError("LLMService not initialized")
    return _llm_service


def set_llm_service(service: LLMService) -> None:
    global _llm_service
    _llm_service = service


def get_bot_service():
    if _bot_service is None:
        raise RuntimeError("BotService not initialized")
    return _bot_service


def set_bot_service(service) -> None:
    global _bot_service
    _bot_service = service


def get_memory_service():
    """Get the MemoryService singleton. Returns None if not initialized."""
    return _memory_service


def set_memory_service(service) -> None:
    global _memory_service
    _memory_service = service


def get_agent_service():
    """Get the AgentService singleton. Returns None if not initialized."""
    return _agent_service


def set_agent_service(service) -> None:
    global _agent_service
    _agent_service = service


async def get_conversation_service(
    db: AsyncSession,
) -> ConversationService:
    """Create a ConversationService bound to the request's DB session."""
    return ConversationService(db)
