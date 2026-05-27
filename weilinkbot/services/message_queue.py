"""Concurrency control and per-user message queuing for BotService.

Prevents race conditions when multiple messages arrive from the same user
and limits concurrent LLM API calls to avoid provider rate limits.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict
from typing import Any

logger = logging.getLogger(__name__)

# Idle timeout for per-user locks/queues cleanup (1 hour)
_IDLE_CLEANUP_SECONDS = 3600.0


class MessageQueue:
    """Per-user message queue with global concurrency semaphore.

    - Global semaphore limits total concurrent LLM requests
    - Per-user locks serialize message processing for each user
    - Pending messages queue up while a user's previous message is being processed
    """

    def __init__(self, max_concurrent: int = 3) -> None:
        self._max_concurrent = max_concurrent
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._user_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._user_queues: dict[str, asyncio.Queue] = defaultdict(asyncio.Queue)
        self._active_tasks: dict[str, asyncio.Task] = {}
        self._user_last_access: dict[str, float] = {}

    def _touch(self, user_id: str) -> None:
        self._user_last_access[user_id] = time.monotonic()

    async def acquire(self) -> None:
        """Acquire a slot from the global concurrency semaphore."""
        await self._semaphore.acquire()

    def release(self) -> None:
        """Release a slot back to the global concurrency semaphore."""
        self._semaphore.release()

    def get_user_lock(self, user_id: str) -> asyncio.Lock:
        """Get the per-user lock for serializing message processing."""
        self._touch(user_id)
        return self._user_locks[user_id]

    def enqueue(self, user_id: str, msg: Any) -> None:
        """Enqueue a message for a user who already has an active task."""
        self._touch(user_id)
        self._user_queues[user_id].put_nowait(msg)
        logger.debug("Enqueued message for user %s", user_id)

    def has_pending(self, user_id: str) -> bool:
        """Check if a user has pending messages in the queue."""
        return not self._user_queues[user_id].empty()

    async def dequeue(self, user_id: str) -> Any | None:
        """Get the next pending message for a user, or None if empty."""
        q = self._user_queues[user_id]
        try:
            return q.get_nowait()
        except asyncio.QueueEmpty:
            return None

    def set_active_task(self, user_id: str, task: asyncio.Task) -> None:
        """Track the active processing task for a user."""
        self._touch(user_id)
        self._active_tasks[user_id] = task

    def clear_active_task(self, user_id: str) -> None:
        """Mark a user's task as completed."""
        self._active_tasks.pop(user_id, None)

    def is_user_active(self, user_id: str) -> bool:
        """Check if a user currently has an active processing task."""
        task = self._active_tasks.get(user_id)
        if task is None:
            return False
        if task.done():
            self._active_tasks.pop(user_id, None)
            return False
        return True

    @property
    def active_count(self) -> int:
        """Number of users currently being processed."""
        return len(self._active_tasks)

    def update_concurrency(self, max_concurrent: int) -> None:
        """Update the global concurrency limit at runtime.

        When *increasing*, releases extra permits onto the existing semaphore so
        waiting tasks are woken immediately.  When *decreasing*, updates the
        tracked limit — in-flight tasks complete naturally and new ``acquire``
        calls will block once the semaphore is drained to the new level.
        """
        old = self._max_concurrent
        if max_concurrent == old:
            return
        self._max_concurrent = max_concurrent
        if max_concurrent > old:
            for _ in range(max_concurrent - old):
                self._semaphore.release()
        logger.info(
            "Updated global concurrency limit %d → %d", old, max_concurrent,
        )

    def cleanup_idle(self, max_idle: float = _IDLE_CLEANUP_SECONDS) -> int:
        """Remove locks/queues for users idle longer than max_idle seconds. Returns count removed."""
        now = time.monotonic()
        idle_users = [
            uid for uid, last in self._user_last_access.items()
            if now - last > max_idle and uid not in self._active_tasks
        ]
        for uid in idle_users:
            self._user_locks.pop(uid, None)
            q = self._user_queues.pop(uid, None)
            self._user_last_access.pop(uid, None)
            if q and not q.empty():
                # Re-create if messages still pending (edge case)
                self._user_queues[uid] = q
                self._user_last_access[uid] = now
        removed = len(idle_users)
        if removed:
            logger.debug("Cleaned up %d idle user entries from message queue", removed)
        return removed
