"""Unified WebSocket endpoint for real-time data push."""

from __future__ import annotations

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..services.ws_service import get_ws_service

router = APIRouter()


@router.websocket("/ws")
async def unified_ws(ws: WebSocket):
    """Unified WebSocket endpoint — pushes all data updates."""
    ws_service = get_ws_service()
    await ws_service.connect(ws)
    try:
        # Send initial state snapshot
        await ws_service.send_initial_state(ws)
        # Keep connection alive
        while True:
            _ = await ws.receive_text()
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        await ws_service.disconnect(ws)
