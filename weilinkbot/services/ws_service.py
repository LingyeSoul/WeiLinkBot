"""Unified WebSocket push service — drives frontend data updates."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Optional

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class WsService:
    """Manages WebSocket connections and broadcasts data updates."""

    _instance: Optional["WsService"] = None

    def __init__(self) -> None:
        self._connections: set[WebSocket] = set()
        self._lock: asyncio.Lock = asyncio.Lock()

    @classmethod
    def get_instance(cls) -> "WsService":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    async def connect(self, ws: WebSocket) -> None:
        """Accept and register a WebSocket connection."""
        await ws.accept()
        async with self._lock:
            self._connections.add(ws)
        client_id = id(ws)
        logger.info("[WS] Client connected — id=%d, total=%d", client_id, len(self._connections))

    async def disconnect(self, ws: WebSocket) -> None:
        """Remove a WebSocket connection."""
        client_id = id(ws)
        async with self._lock:
            self._connections.discard(ws)
        logger.info("[WS] Client disconnected — id=%d, total=%d", client_id, len(self._connections))

    @staticmethod
    def _serialize(data: Any) -> str:
        """Serialize data to JSON string with datetime support."""
        def _default_serializer(obj):
            from datetime import datetime, date
            if isinstance(obj, (datetime, date)):
                return obj.isoformat()
            raise TypeError(f"Object of type {type(obj)} is not JSON serializable")
        return json.dumps(data, default=_default_serializer)

    async def _send_json(self, ws: WebSocket, data: Any) -> None:
        """Send JSON data to a single WebSocket client."""
        message = self._serialize(data)
        msg_type = data.get("type", "unknown") if isinstance(data, dict) else "unknown"
        logger.debug("[WS] Sending JSON to client %d — type=%s, size=%d bytes", id(ws), msg_type, len(message))
        await ws.send_text(message)

    async def broadcast(self, msg_type: str, data: Any) -> None:
        """Send a message to all connected clients."""
        message = self._serialize({"type": msg_type, "data": data})
        disconnected: list[WebSocket] = []
        async with self._lock:
            connections = list(self._connections)
        count = len(connections)
        
        if count == 0:
            logger.warning("[WS] Broadcast type=%s — NO clients connected, message dropped!", msg_type)
            return
        
        logger.info("[WS] Broadcasting type=%s to %d client(s), payload_size=%d bytes", 
                    msg_type, count, len(message))
        
        success_count = 0
        for ws in connections:
            client_id = id(ws)
            try:
                await ws.send_text(message)
                success_count += 1
            except Exception as e:
                logger.error("[WS] Failed to send to client %d: %s", client_id, str(e))
                disconnected.append(ws)
        
        logger.info("[WS] Broadcast complete — type=%s, success=%d/%d", msg_type, success_count, count)
        
        if disconnected:
            async with self._lock:
                for ws in disconnected:
                    self._connections.discard(ws)
            logger.warning("[WS] Removed %d disconnected client(s)", len(disconnected))

    async def send_initial_state(self, ws: WebSocket) -> None:
        """Send current state snapshot to a newly connected client.

        Each section is independently wrapped so one failure doesn't block the rest.
        """
        client_id = id(ws)
        logger.info("[WS] Sending initial state to client %d", client_id)
        
        from ..database import get_session_factory
        from ..models import (
            SystemPrompt,
            LLMPreset,
            UserConfig,
            CharacterCard,
            Provider,
            get_preset_api_key,
        )
        from ..schemas import (
            SystemPromptResponse,
            UserConfigResponse,
            CharacterCardResponse,
            ProviderResponse,
            ConversationResponse,
        )
        from sqlalchemy import select
        from .event_log import get_event_log

        async def _safe_send(msg_type: str, data: Any) -> None:
            """Send a message, logging but not raising on failure."""
            try:
                item_count = len(data) if isinstance(data, list) else 1
                await self._send_json(ws, {"type": msg_type, "data": data})
                logger.info("[WS] Initial state sent — type=%s, items=%d", msg_type, item_count)
            except Exception as e:
                logger.error("[WS] Failed to send initial %s to client %d: %s", msg_type, client_id, str(e))

        # Bot status
        try:
            bot_service = _get_bot_service()
            if bot_service:
                from ..services.bot_service import _get_bot_status_dict
                status = await _get_bot_status_dict(bot_service)
                await _safe_send("bot_status", status)
        except Exception:
            logger.exception("Failed to build initial bot_status")

        try:
            session_factory = get_session_factory()
            async with session_factory() as db:
                # Prompts
                try:
                    result = await db.execute(
                        select(SystemPrompt).order_by(SystemPrompt.is_default.desc(), SystemPrompt.id)
                    )
                    prompts = result.scalars().all()
                    await _safe_send(
                        "prompts",
                        [SystemPromptResponse.model_validate(p).model_dump(mode="json") for p in prompts],
                    )
                except Exception:
                    logger.exception("Failed to send initial prompts")

                # Models
                try:
                    from ..schemas import LLMPresetResponse
                    result = await db.execute(
                        select(LLMPreset).order_by(LLMPreset.is_active.desc(), LLMPreset.id)
                    )
                    models = result.scalars().all()
                    await _safe_send(
                        "models",
                        [
                            LLMPresetResponse(
                                **{k: getattr(m, k) for k in LLMPresetResponse.model_fields if k != "api_key_set"},
                                api_key_set=bool(get_preset_api_key(m)),
                            ).model_dump(mode="json")
                            for m in models
                        ],
                    )
                except Exception:
                    logger.exception("Failed to send initial models")

                # Users
                try:
                    result = await db.execute(select(UserConfig))
                    users = result.scalars().all()
                    await _safe_send(
                        "users",
                        [UserConfigResponse.model_validate(u).model_dump(mode="json") for u in users],
                    )
                except Exception:
                    logger.exception("Failed to send initial users")

                # Characters
                try:
                    result = await db.execute(select(CharacterCard).order_by(CharacterCard.id))
                    chars = result.scalars().all()
                    await _safe_send(
                        "characters",
                        [CharacterCardResponse.model_validate(c).model_dump(mode="json") for c in chars],
                    )
                except Exception:
                    logger.exception("Failed to send initial characters")

                # Providers
                try:
                    result = await db.execute(select(Provider).order_by(Provider.id))
                    providers = result.scalars().all()
                    await _safe_send(
                        "providers",
                        [ProviderResponse.model_validate(p).model_dump(mode="json") for p in providers],
                    )
                except Exception:
                    logger.exception("Failed to send initial providers")

                # ST Presets
                try:
                    from ..models import STPreset
                    from ..schemas import STPresetResponse
                    result = await db.execute(select(STPreset).order_by(STPreset.id))
                    st_presets = result.scalars().all()
                    await _safe_send(
                        "st_presets",
                        [STPresetResponse.model_validate(p).model_dump(mode="json") for p in st_presets],
                    )
                except Exception:
                    logger.exception("Failed to send initial st_presets")

                # World Books
                try:
                    from ..models import WorldBook
                    from ..schemas import WorldBookResponse
                    from sqlalchemy.orm import selectinload
                    result = await db.execute(
                        select(WorldBook).options(selectinload(WorldBook.entries)).order_by(WorldBook.id)
                    )
                    world_books = result.scalars().all()
                    await _safe_send(
                        "world_books",
                        [WorldBookResponse.model_validate(wb).model_dump(mode="json") for wb in world_books],
                    )
                except Exception:
                    logger.exception("Failed to send initial world_books")

                # Conversations
                try:
                    from ..models import Conversation
                    result = await db.execute(select(Conversation))
                    convs = result.scalars().all()
                    await _safe_send(
                        "conversations",
                        [ConversationResponse.model_validate(c).model_dump(mode="json") for c in convs],
                    )
                except Exception:
                    logger.exception("Failed to send initial conversations")

            # Events (last 50)
            try:
                event_log = get_event_log()
                recent_events = list(event_log._events)[-50:]
                await _safe_send("events_init", [e.to_dict() for e in recent_events])
            except Exception:
                logger.exception("Failed to send initial events")

        except Exception:
            logger.exception("Failed to open DB session for initial state")


def _get_bot_service():
    """Get bot service instance (lazy import to avoid circular deps)."""
    try:
        from ..api.deps import _bot_service

        return _bot_service
    except Exception:
        return None


def get_ws_service() -> WsService:
    """Get the global WebSocket service instance."""
    return WsService.get_instance()
