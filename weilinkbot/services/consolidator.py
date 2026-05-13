"""Session compression / Consolidator service.

Periodically compresses old conversation messages into concise summaries
using the LLM, then marks the original messages as consolidated.

Inspired by nanobot's Consolidator + AutoCompact architecture.

When context is built, consolidated messages are excluded but their
summary (stored in MemorySummary) is injected as context.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select, update, func
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import AppConfig
from ..models import Message, Conversation, MemorySummary
from .llm_service import LLMService

logger = logging.getLogger(__name__)

_CONSOLIDATION_PROMPT = (
    "You are a conversation summarizer. Compress the following conversation "
    "into a concise summary that preserves:\n"
    "1. Key facts, decisions, and commitments\n"
    "2. User preferences and important context\n"
    "3. Action items or unresolved questions\n"
    "4. Emotional context if significant\n\n"
    "Be concise but complete. Output ONLY the summary text, no preamble."
)


class Consolidator:
    """Compresses old conversation messages into summaries.

    When triggered for a user:
    1. Fetches the oldest N non-consolidated messages
    2. Sends them to the LLM for summarization
    3. Stores the summary in MemorySummary
    4. Marks the original messages as consolidated (is_consolidated=True)

    Consolidated messages are excluded from context building, reducing
    token usage while preserving key information via the summary.
    """

    def __init__(
        self,
        llm_service: LLMService,
        config: AppConfig,
    ) -> None:
        self._llm = llm_service
        self._config = config
        self._threshold = config.agent.consolidation_threshold
        self._ratio = config.agent.consolidation_ratio

    async def should_consolidate(
        self,
        db: AsyncSession,
        user_id: str,
    ) -> bool:
        """Check if a user has enough non-consolidated messages to trigger compression."""
        # Get the user's conversation
        conv = await db.scalar(
            select(Conversation).where(Conversation.user_id == user_id)
        )
        if not conv:
            return False

        # Count non-consolidated messages
        count = await db.scalar(
            select(func.count()).select_from(Message).where(
                Message.conversation_id == conv.id,
                Message.is_consolidated == False,
                Message.role.in_(["user", "assistant"]),
            )
        )
        return count is not None and count >= self._threshold

    async def consolidate(
        self,
        db: AsyncSession,
        user_id: str,
    ) -> Optional[str]:
        """Compress old messages for a user. Returns summary text or None.

        Strategy:
        - Take the oldest batch of non-consolidated messages
        - Target compressing to `consolidation_ratio` of the original
        - Store summary in MemorySummary
        - Mark messages as consolidated
        """
        conv = await db.scalar(
            select(Conversation).where(Conversation.user_id == user_id)
        )
        if not conv:
            return None

        # Get non-consolidated messages, oldest first
        messages = (await db.execute(
            select(Message).where(
                Message.conversation_id == conv.id,
                Message.is_consolidated == False,
                Message.role.in_(["user", "assistant"]),
            ).order_by(Message.created_at.asc())
        )).scalars().all()

        if len(messages) < self._threshold:
            return None

        # Compress the oldest batch (leave recent messages untouched)
        batch_size = max(
            self._threshold,
            int(len(messages) * self._ratio),
        )
        # Keep at least 5 recent messages uncompressed
        batch_size = min(batch_size, len(messages) - 5)
        if batch_size <= 0:
            return None

        batch = messages[:batch_size]

        # Format for LLM
        conversation_text = "\n".join(
            f"[{m.role}] {m.content[:500]}" for m in batch
        )

        summary_text = await self._llm_summarize(conversation_text)
        if not summary_text:
            logger.warning("Consolidation summarization failed for user %s", user_id)
            return None

        # Determine message range description
        first_id = batch[0].id
        last_id = batch[-1].id
        message_range = f"messages {first_id}-{last_id} ({len(batch)} messages)"

        # Store summary
        summary = MemorySummary(
            user_id=user_id,
            content=summary_text,
            message_range=f"consolidated: {message_range}",
            tokens_used=0,
        )
        db.add(summary)

        # Mark messages as consolidated
        msg_ids = [m.id for m in batch]
        await db.execute(
            update(Message).where(Message.id.in_(msg_ids)).values(is_consolidated=True)
        )

        await db.flush()
        logger.info(
            "Consolidated %d messages for user %s into summary (range: %s)",
            len(batch), user_id, message_range,
        )
        return summary_text

    async def _llm_summarize(self, conversation_text: str) -> Optional[str]:
        """Use LLM to produce a concise summary of the conversation."""
        try:
            text, tokens, _ = await self._llm.chat(
                messages=[
                    {"role": "system", "content": _CONSOLIDATION_PROMPT},
                    {"role": "user", "content": conversation_text},
                ],
                temperature=0.3,
                max_tokens=500,
            )
            if text and text.strip():
                return text.strip()
        except Exception as e:
            logger.error("Consolidation LLM call failed: %s", e)
        return None

    async def auto_compact(
        self,
        db: AsyncSession,
        user_id: str,
    ) -> Optional[str]:
        """Auto-compact: consolidate if threshold is met.

        Called after normal summarization to proactively compress
        old messages that haven't been consolidated yet.
        """
        if await self.should_consolidate(db, user_id):
            return await self.consolidate(db, user_id)
        return None
