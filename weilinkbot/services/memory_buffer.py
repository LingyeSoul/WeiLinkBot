"""Message buffer for batched memory summarization.

Accumulates user messages in memory and triggers summarization when either
a turn-count threshold or a time-based timeout is reached.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class _UserBuffer:
    messages: list[dict[str, str]] = field(default_factory=list)
    last_activity: float = field(default_factory=time.time)
    message_ids: list[int] = field(default_factory=list)


class MemoryBuffer:
    """Accumulates user messages and signals when summarization should run."""

    def __init__(
        self,
        turn_threshold: int = 10,
        timeout_minutes: int = 30,
        on_flush: "asyncio.Task | None" = None,
    ) -> None:
        self._turn_threshold = turn_threshold
        self._timeout_minutes = timeout_minutes
        self._buffers: dict[str, _UserBuffer] = {}

    def update_config(self, turn_threshold: int, timeout_minutes: int) -> None:
        self._turn_threshold = turn_threshold
        self._timeout_minutes = timeout_minutes

    async def add(
        self,
        user_id: str,
        role: str,
        content: str,
        message_id: int | None = None,
    ) -> bool:
        """Add a message to the buffer. Returns True when turn threshold is reached."""
        buf = self._buffers.setdefault(user_id, _UserBuffer())
        buf.messages.append({"role": role, "content": content})
        buf.last_activity = time.time()
        if message_id is not None:
            buf.message_ids.append(message_id)
        reached = len(buf.messages) >= self._turn_threshold
        if reached:
            logger.info(
                "Buffer threshold reached for user %s (%d messages)",
                user_id,
                len(buf.messages),
            )
        return reached

    async def check_timeout(self) -> list[str]:
        """Return user_ids whose buffer timed out (and clear their timeout flag)."""
        now = time.time()
        timeout_secs = self._timeout_minutes * 60
        timed_out: list[str] = []
        for user_id, buf in list(self._buffers.items()):
            if not buf.messages:
                continue
            if now - buf.last_activity >= timeout_secs:
                timed_out.append(user_id)
                logger.info(
                    "Buffer timeout for user %s (%.1f min idle, %d messages)",
                    user_id,
                    (now - buf.last_activity) / 60,
                    len(buf.messages),
                )
        return timed_out

    def flush(self, user_id: str) -> tuple[list[dict[str, str]], list[int]]:
        """Extract messages and message_ids, then clear the buffer."""
        buf = self._buffers.pop(user_id, _UserBuffer())
        return buf.messages, buf.message_ids

    def pending_count(self, user_id: str) -> int:
        buf = self._buffers.get(user_id)
        return len(buf.messages) if buf else 0

    def has_pending(self, user_id: str) -> bool:
        return self.pending_count(user_id) > 0

    @property
    def active_users(self) -> list[str]:
        return [uid for uid, buf in self._buffers.items() if buf.messages]
