"""Conversation and message persistence + context building for LLM."""

from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..models import Conversation, Message, SystemPrompt, UserConfig, LLMPreset
from ..i18n import t as _t

logger = logging.getLogger(__name__)

DEFAULT_SYSTEM_PROMPT = (
    "You are a helpful AI assistant. Reply concisely and helpfully."
)
DEFAULT_MAX_HISTORY = 20


class ConversationService:
    """Manages conversations, messages, and LLM context assembly."""

    def __init__(self, session: AsyncSession) -> None:
        self._db = session

    # ── Conversation CRUD ─────────────────────────────────────────

    async def get_or_create_conversation(self, user_id: str) -> Conversation:
        """Get existing conversation for user or create a new one."""
        stmt = select(Conversation).where(Conversation.user_id == user_id)
        result = await self._db.execute(stmt)
        conv = result.scalar_one_or_none()

        if conv is None:
            conv = Conversation(user_id=user_id, message_count=0)
            self._db.add(conv)
            await self._db.flush()
            logger.info("Created conversation for user %s", user_id)

        return conv

    async def list_conversations(self) -> list[dict]:
        """List all conversations with last message preview."""
        stmt = (
            select(Conversation)
            .options(selectinload(Conversation.messages))
            .order_by(Conversation.updated_at.desc())
        )
        result = await self._db.execute(stmt)
        conversations = result.scalars().all()

        items = []
        for conv in conversations:
            last_msg = conv.messages[-1].content[:100] if conv.messages else None
            items.append({
                "id": conv.id,
                "user_id": conv.user_id,
                "created_at": conv.created_at,
                "updated_at": conv.updated_at,
                "message_count": conv.message_count,
                "last_message": last_msg,
            })
        return items

    # ── Message CRUD ──────────────────────────────────────────────

    async def add_message(
        self,
        user_id: str,
        role: str,
        content: str,
        tokens_used: Optional[int] = None,
        model: Optional[str] = None,
    ) -> Message:
        """Add a message to the user's conversation."""
        conv = await self.get_or_create_conversation(user_id)

        msg = Message(
            conversation_id=conv.id,
            role=role,
            content=content,
            tokens_used=tokens_used,
            model=model,
        )
        self._db.add(msg)
        conv.message_count += 1
        await self._db.flush()

        logger.debug("Added %s message to conversation %d", role, conv.id)
        return msg

    async def get_messages(
        self, user_id: str, limit: int = 50, offset: int = 0
    ) -> list[Message]:
        """Get messages for a user's conversation."""
        stmt = (
            select(Conversation)
            .where(Conversation.user_id == user_id)
            .options(selectinload(Conversation.messages))
        )
        result = await self._db.execute(stmt)
        conv = result.scalar_one_or_none()

        if conv is None:
            return []

        # Return messages in chronological order with pagination
        # Messages are already ordered by created_at via the relationship
        all_msgs = conv.messages
        return all_msgs[offset: offset + limit]

    async def clear_messages(self, user_id: str) -> bool:
        """Delete all messages in a user's conversation."""
        stmt = (
            select(Conversation)
            .where(Conversation.user_id == user_id)
            .options(selectinload(Conversation.messages))
        )
        result = await self._db.execute(stmt)
        conv = result.scalar_one_or_none()

        if conv is None:
            return False

        for msg in conv.messages:
            await self._db.delete(msg)

        conv.message_count = 0
        await self._db.flush()
        logger.info("Cleared conversation for user %s", user_id)
        return True

    # ── Context Building ──────────────────────────────────────────

    async def build_context(
        self,
        user_id: str,
        memories: list[str] | None = None,
        max_context_chars: int = 2000,
    ) -> list[dict[str, str]]:
        """Build OpenAI-format message list for LLM call.

        Structure: [system_prompt + memories, ...recent_history]
        """
        # 1. Get user config (or create defaults)
        user_config = await self._get_user_config(user_id)
        max_history = user_config.max_history if user_config else DEFAULT_MAX_HISTORY

        # 2. Determine system prompt
        system_content = await self._get_system_prompt(user_config)

        # 3. Inject memories into system prompt
        if memories:
            truncated_memories: list[str] = []
            total_chars = 0
            for memory in memories:
                next_total = total_chars + len(memory)
                if next_total > max_context_chars:
                    break
                truncated_memories.append(memory)
                total_chars = next_total
            if truncated_memories:
                memory_block = "\n".join(f"- {m}" for m in truncated_memories)
                system_content += (
                    f"\n\n{_t('memory.context_header')}\n"
                    + memory_block
                )

        # 4. Load recent messages
        messages = await self.get_messages(user_id, limit=max_history)

        # 5. Build context
        context: list[dict[str, str]] = [
            {"role": "system", "content": system_content}
        ]

        for msg in messages:
            if msg.role == "preprocess":
                continue
            context.append({"role": msg.role, "content": msg.content})

        return context

    # ── User Config ───────────────────────────────────────────────

    async def _get_user_config(self, user_id: str) -> Optional[UserConfig]:
        stmt = select(UserConfig).where(UserConfig.user_id == user_id)
        result = await self._db.execute(stmt)
        return result.scalar_one_or_none()

    async def is_blocked(self, user_id: str) -> bool:
        """Check if a user is blocked."""
        config = await self._get_user_config(user_id)
        return config.is_blocked if config else False

    async def get_or_create_user_config(self, user_id: str) -> UserConfig:
        """Get or create user config."""
        config = await self._get_user_config(user_id)
        if config is None:
            config = UserConfig(user_id=user_id)
            self._db.add(config)
            await self._db.flush()
        return config

    async def list_user_configs(self) -> list[UserConfig]:
        stmt = select(UserConfig).order_by(UserConfig.created_at.desc())
        result = await self._db.execute(stmt)
        return list(result.scalars().all())

    async def update_user_config(
        self,
        user_id: str,
        nickname: Optional[str] = None,
        is_blocked: Optional[bool] = None,
        custom_prompt_id: Optional[int] = None,
        max_history: Optional[int] = None,
    ) -> UserConfig:
        config = await self.get_or_create_user_config(user_id)
        if nickname is not None:
            config.nickname = nickname
        if is_blocked is not None:
            config.is_blocked = is_blocked
        if custom_prompt_id is not None:
            config.custom_prompt_id = custom_prompt_id if custom_prompt_id > 0 else None
        if max_history is not None:
            config.max_history = max_history
        await self._db.flush()
        return config

    # ── Token Statistics ──────────────────────────────────────────

    async def _get_model_name_map(self) -> dict[str, str]:
        """Build a {model_id: display_name} mapping from LLMPreset."""
        result = await self._db.execute(
            select(LLMPreset.model, LLMPreset.name).where(LLMPreset.model.isnot(None))
        )
        return {row.model: row.name for row in result.all()}

    async def get_token_stats(self) -> dict:
        """Get token usage statistics grouped by model.

        Returns:
            {
                "models": [{"model": "gpt-4o-mini", "tokens": 12345, "requests": 10}, ...],
                "total_tokens": 12345,
                "total_requests": 10,
            }
        """
        stmt = (
            select(
                Message.model,
                func.coalesce(func.sum(Message.tokens_used), 0).label("total_tokens"),
                func.count(Message.id).label("request_count"),
            )
            .where(Message.role.in_(["assistant", "preprocess"]))
            .where(Message.model.isnot(None))
            .group_by(Message.model)
            .order_by(func.sum(Message.tokens_used).desc())
        )
        result = await self._db.execute(stmt)
        rows = result.all()

        name_map = await self._get_model_name_map()

        models = []
        total_tokens = 0
        total_requests = 0

        for row in rows:
            model_id = row.model or "unknown"
            tokens = int(row.total_tokens)
            count = int(row.request_count)
            models.append({
                "model": model_id,
                "name": name_map.get(model_id, model_id),
                "tokens": tokens,
                "requests": count,
            })
            total_tokens += tokens
            total_requests += count

        return {
            "models": models,
            "total_tokens": total_tokens,
            "total_requests": total_requests,
        }

    async def get_user_token_stats(self, user_id: str) -> dict:
        """Get token usage for a single user's conversation."""
        stmt = (
            select(Conversation)
            .where(Conversation.user_id == user_id)
        )
        result = await self._db.execute(stmt)
        conv = result.scalar_one_or_none()
        if not conv:
            return {"models": [], "total_tokens": 0, "total_requests": 0}

        stmt = (
            select(
                Message.model,
                func.coalesce(func.sum(Message.tokens_used), 0).label("total_tokens"),
                func.count(Message.id).label("request_count"),
            )
            .where(Message.conversation_id == conv.id)
            .where(Message.role.in_(["assistant", "preprocess"]))
            .where(Message.model.isnot(None))
            .group_by(Message.model)
        )
        result = await self._db.execute(stmt)
        rows = result.all()

        name_map = await self._get_model_name_map()

        models = []
        total_tokens = 0
        total_requests = 0
        for row in rows:
            model_id = row.model
            tokens = int(row.total_tokens)
            count = int(row.request_count)
            models.append({
                "model": model_id,
                "name": name_map.get(model_id, model_id),
                "tokens": tokens,
                "requests": count,
            })
            total_tokens += tokens
            total_requests += count

        return {
            "models": models,
            "total_tokens": total_tokens,
            "total_requests": total_requests,
        }

    # ── System Prompt Resolution ──────────────────────────────────

    async def _get_system_prompt(self, user_config: Optional[UserConfig]) -> str:
        """Resolve the system prompt for a user.

        Priority: user-specific prompt > default prompt > hardcoded default.
        """
        # Check user-specific prompt
        if user_config and user_config.custom_prompt_id:
            stmt = select(SystemPrompt).where(SystemPrompt.id == user_config.custom_prompt_id)
            result = await self._db.execute(stmt)
            prompt = result.scalar_one_or_none()
            if prompt:
                return prompt.content

        # Check default prompt
        stmt = select(SystemPrompt).where(SystemPrompt.is_default == True)
        result = await self._db.execute(stmt)
        prompt = result.scalar_one_or_none()
        if prompt:
            return prompt.content

        return DEFAULT_SYSTEM_PROMPT
