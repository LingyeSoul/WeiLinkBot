"""Event log service — in-memory ring buffer."""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from dataclasses import dataclass, asdict
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class BotEvent:
    id: int
    timestamp: float
    level: str           # "info" | "warning" | "error"
    category: str        # bot / message / llm / command / preprocess / system
    event: str           # "bot.start" etc.
    message: str         # human-readable description
    detail: Optional[dict] = None

    def to_dict(self) -> dict:
        return asdict(self)


class EventLog:
    """Singleton event log with ring buffer."""

    _instance: Optional["EventLog"] = None

    def __init__(self, maxlen: int = 500) -> None:
        self._events: deque[BotEvent] = deque(maxlen=maxlen)
        self._id_counter: int = 0
        self._lock: asyncio.Lock = asyncio.Lock()

    @classmethod
    def get_instance(cls) -> "EventLog":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    async def push(
        self,
        level: str,
        category: str,
        event: str,
        message: str,
        detail: Optional[dict] = None,
    ) -> BotEvent:
        """Record an event and broadcast via unified WebSocket."""
        async with self._lock:
            self._id_counter += 1
            evt = BotEvent(
                id=self._id_counter,
                timestamp=time.time(),
                level=level,
                category=category,
                event=event,
                message=message,
                detail=detail,
            )
            self._events.append(evt)

        try:
            from .ws_service import get_ws_service
            await get_ws_service().broadcast("event", evt.to_dict())
        except Exception:
            pass

        return evt

    def get_since(self, since_id: int) -> list[BotEvent]:
        """Get events after the given ID."""
        return [e for e in self._events if e.id > since_id]

    @property
    def total(self) -> int:
        return len(self._events)


def get_event_log() -> EventLog:
    return EventLog.get_instance()
